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
async def test_nothing_is_anchored_when_unconfigured():
    service = AnchoringService(rpc_url=None, private_key=None)
    hashes = ["a" * 64, "b" * 64]
    result = await service.anchor_hashes(hashes)

    # No wallet: no transaction, and no hash-shaped placeholder that could be mistaken for one
    assert result.status == "not_configured"
    assert result.chain_id == SEPOLIA_CHAIN_ID
    assert result.tx_hash is None
    assert result.explorer_url is None
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

    assert result.status == "not_configured"
    assert result.entries_count == 2
    assert result.merkle_root is not None


@pytest.mark.asyncio
async def test_verify_anchor_requires_a_real_chain_lookup():
    # Without a configured RPC nothing can be verified, so a well-formed hash is not "valid"
    service = AnchoringService(rpc_url=None, private_key=None)
    assert await service.verify_anchor("dummy_root", "0x" + "f" * 64) is False
    assert await service.verify_anchor("dummy_root", "bad_tx") is False


@pytest.mark.asyncio
async def test_successful_sepolia_anchor_returns_explorer_link():
    service = AnchoringService(rpc_url="https://sepolia.example/rpc", private_key="0x" + "1" * 64)
    mock_w3 = MagicMock()
    mock_w3.is_connected.return_value = True
    mock_w3.eth.chain_id = SEPOLIA_CHAIN_ID
    mock_w3.eth.get_transaction_count.return_value = 0
    mock_w3.eth.gas_price = 1
    mock_w3.eth.account.sign_transaction.return_value = MagicMock(raw_transaction=b"raw")
    mock_w3.eth.send_raw_transaction.return_value = bytes.fromhex("ab" * 32)
    mock_w3.eth.wait_for_transaction_receipt.return_value = MagicMock(blockNumber=123, status=1)

    with patch("services.anchoring.settings.dry_run", False), patch("services.anchoring.Web3", return_value=mock_w3):
        result = await service.anchor_hashes(["c" * 64, "d" * 64])

    assert result.status == "confirmed"
    assert result.tx_hash == "0x" + "ab" * 32
    assert result.explorer_url == "https://sepolia.etherscan.io/tx/0x" + "ab" * 32
    assert result.block_number == 123
    sent = mock_w3.eth.account.sign_transaction.call_args[0][0]
    assert sent["data"] == bytes.fromhex(result.merkle_root)
    assert sent["value"] == 0


def test_merkle_proofs_verify_against_the_root():
    from services.anchoring import verify_merkle_proof

    leaves = [f"{i:064x}" for i in range(1, 8)]
    root = compute_merkle_root(leaves)
    for i, leaf in enumerate(leaves):
        assert verify_merkle_proof(leaf, generate_merkle_proof(i, leaves), root)
    assert not verify_merkle_proof(leaves[0], generate_merkle_proof(1, leaves), root)
