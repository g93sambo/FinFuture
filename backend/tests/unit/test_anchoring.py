"""
Unit tests for backend/services/anchoring.py
Testing Merkle tree computation, proof generation, dry-run anchoring, and Ethereum Mainnet hard guard.
"""

import hashlib
import pytest
from unittest.mock import MagicMock, patch
from services.anchoring import (
    compute_merkle_root,
    generate_merkle_proof,
    AnchoringService,
    MainnetForbiddenError,
    SEPOLIA_CHAIN_ID,
    MAINNET_CHAIN_ID,
)


def test_compute_merkle_root_empty():
    root = compute_merkle_root([])
    assert root == hashlib.sha256(b"").hexdigest()


def test_compute_merkle_root_single_leaf():
    leaf = "a" * 64
    root = compute_merkle_root([leaf])
    assert root == leaf


def test_compute_merkle_root_two_leaves():
    h1 = "1" * 64
    h2 = "2" * 64
    expected = hashlib.sha256(bytes.fromhex(h1) + bytes.fromhex(h2)).hexdigest()
    root = compute_merkle_root([h1, h2])
    assert root == expected


def test_compute_merkle_root_odd_leaves():
    # 3 leaves: h3 is duplicated at layer 0 to form 4 leaves
    h1 = "1" * 64
    h2 = "2" * 64
    h3 = "3" * 64

    p1 = hashlib.sha256(bytes.fromhex(h1) + bytes.fromhex(h2)).digest()
    p2 = hashlib.sha256(bytes.fromhex(h3) + bytes.fromhex(h3)).digest()
    expected_root = hashlib.sha256(p1 + p2).hexdigest()

    root = compute_merkle_root([h1, h2, h3])
    assert root == expected_root


def test_generate_merkle_proof():
    h1 = "1" * 64
    h2 = "2" * 64
    proof = generate_merkle_proof(0, [h1, h2])
    assert len(proof) == 1
    assert proof[0]["position"] == "right"
    assert proof[0]["hash"] == h2


@pytest.mark.asyncio
async def test_dry_run_mode_when_unconfigured():
    service = AnchoringService(rpc_url=None, private_key=None)
    hashes = ["a" * 64, "b" * 64]
    result = await service.anchor_hashes(hashes)

    assert result.status == "dry_run"
    assert result.chain_id == SEPOLIA_CHAIN_ID
    assert result.tx_hash.startswith("0x")
    assert len(result.tx_hash) == 66
    assert result.entries_count == 2
    assert result.merkle_root == compute_merkle_root(hashes)


@pytest.mark.asyncio
async def test_mainnet_hard_guard_raises_error():
    # Configure mock Web3 returning Mainnet chain ID 1
    service = AnchoringService(
        rpc_url="https://mainnet.infura.io/v3/dummy",
        private_key="0x" + "1" * 64,
        contract_address="0x" + "2" * 40,
    )

    mock_w3 = MagicMock()
    mock_w3.is_connected.return_value = True
    mock_w3.eth.chain_id = MAINNET_CHAIN_ID  # 1

    with patch("services.anchoring.settings.dry_run", False), \
         patch("services.anchoring.Web3", return_value=mock_w3), \
         patch.object(service, "_is_configured", return_value=True):
        with pytest.raises(MainnetForbiddenError) as exc_info:
            await service.anchor_hashes(["c" * 64])
        assert "Connected to Ethereum Mainnet (Chain ID 1)" in str(exc_info.value)


@pytest.mark.asyncio
async def test_anchor_client_audit_trail(db_session):
    from services.audit_logger import log_audit_entry
    from services.anchoring import get_anchoring_service

    client_id = "anchor-client-test"
    await log_audit_entry(db_session, client_id, "TEST1", "SYSTEM", {"a": 1})
    await log_audit_entry(db_session, client_id, "TEST2", "SYSTEM", {"b": 2})

    service = get_anchoring_service()
    result = await service.anchor_client_audit_trail(db_session, client_id)

    assert result.status == "dry_run"
    assert result.entries_count == 2
    assert result.merkle_root is not None


@pytest.mark.asyncio
async def test_verify_anchor_dry_run():
    service = AnchoringService()
    valid_tx = "0x" + "f" * 64
    invalid_tx = "bad_tx"

    assert await service.verify_anchor("dummy_root", valid_tx) is True
    assert await service.verify_anchor("dummy_root", invalid_tx) is False
