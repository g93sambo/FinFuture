"""
backend/services/anchoring.py
=============================
Merkle root generation, inclusion proofs, and Ethereum Sepolia testnet anchoring.
Nothing is sent unless an RPC URL and wallet key are configured; Ethereum Mainnet (Chain ID 1) is refused.
"""

import os
import time
import logging
import hashlib
from typing import List, Optional, Dict, Any, Tuple
from dataclasses import dataclass
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from core.config import settings
from db.models import DBAuditLog

try:
    from web3 import Web3
    from eth_account import Account
    HAS_WEB3 = True
except ImportError:
    HAS_WEB3 = False
    Web3 = None
    Account = None

logger = logging.getLogger(__name__)

SEPOLIA_CHAIN_ID = 11155111
MAINNET_CHAIN_ID = 1
SEPOLIA_EXPLORER = "https://sepolia.etherscan.io"


class MainnetForbiddenError(RuntimeError):
    """Raised when an operation attempts to run against Ethereum Mainnet (Chain ID 1)."""
    pass


@dataclass
class AnchoringResult:
    merkle_root: str
    tx_hash: Optional[str]  # None unless a transaction was actually sent
    block_number: Optional[int]
    status: str  # "confirmed" | "submitted" | "not_configured" | "failed"
    chain_id: int
    timestamp: datetime
    entries_count: int
    explorer_url: Optional[str] = None
    wallet_address: Optional[str] = None
    error: Optional[str] = None


def compute_merkle_root(leaf_hashes: List[str]) -> str:
    """
    Computes binary Merkle tree root from a list of hexadecimal hash strings.
    If empty, returns SHA-256 of empty bytes.
    If odd count at any level, duplicates the last node per RFC 6962.
    """
    if not leaf_hashes:
        return hashlib.sha256(b"").hexdigest()

    if len(leaf_hashes) == 1:
        clean = leaf_hashes[0].lower().replace("0x", "")
        if len(clean) < 64:
            clean = clean.zfill(64)
        return clean[:64]

    # Convert all leaves to raw 32-byte digests
    current_layer: List[bytes] = []
    for h in leaf_hashes:
        clean = h.lower().replace("0x", "")
        if len(clean) < 64:
            clean = clean.zfill(64)
        current_layer.append(bytes.fromhex(clean[:64]))

    while len(current_layer) > 1:
        if len(current_layer) % 2 != 0:
            current_layer.append(current_layer[-1])  # Duplicate last leaf

        next_layer: List[bytes] = []
        for i in range(0, len(current_layer), 2):
            left = current_layer[i]
            right = current_layer[i + 1]
            parent = hashlib.sha256(left + right).digest()
            next_layer.append(parent)
        current_layer = next_layer

    return current_layer[0].hex()


def generate_merkle_proof(leaf_index: int, leaf_hashes: List[str]) -> List[Dict[str, str]]:
    """Generates Merkle audit proof for a specific leaf index."""
    if not leaf_hashes or leaf_index >= len(leaf_hashes):
        return []

    proof: List[Dict[str, str]] = []
    current_layer: List[bytes] = [
        bytes.fromhex(h.lower().replace("0x", "").zfill(64)[:64]) for h in leaf_hashes
    ]
    idx = leaf_index

    while len(current_layer) > 1:
        if len(current_layer) % 2 != 0:
            current_layer.append(current_layer[-1])

        sibling_idx = idx + 1 if idx % 2 == 0 else idx - 1
        position = "right" if idx % 2 == 0 else "left"
        proof.append({"position": position, "hash": current_layer[sibling_idx].hex()})

        next_layer: List[bytes] = []
        for i in range(0, len(current_layer), 2):
            parent = hashlib.sha256(current_layer[i] + current_layer[i + 1]).digest()
            next_layer.append(parent)

        idx = idx // 2
        current_layer = next_layer

    return proof


def verify_merkle_proof(leaf_hash: str, proof: List[Dict[str, str]], merkle_root: str) -> bool:
    """Recomputes the root from a leaf and its inclusion proof and compares it to ``merkle_root``."""
    node = bytes.fromhex(leaf_hash.lower().replace("0x", "").zfill(64)[:64])
    for step in proof:
        sibling = bytes.fromhex(step["hash"])
        node = hashlib.sha256(node + sibling if step["position"] == "right" else sibling + node).digest()
    return node.hex() == merkle_root.lower().replace("0x", "")


def sepolia_tx_url(tx_hash: str) -> str:
    return f"{SEPOLIA_EXPLORER}/tx/{tx_hash}"


class AnchoringService:
    """
    Anchors audit-trail Merkle roots on the Ethereum Sepolia testnet.

    The root is written as the data payload of a zero-value transaction from the configured
    wallet (to itself, or to AUDIT_CONTRACT_ADDRESS when set), so anyone can look the
    transaction up on Etherscan and compare the input data with the root. Without an RPC URL
    and a funded wallet key nothing is sent and the result says so (status "not_configured";
    tx_hash is None). Mainnet (chain ID 1) is refused.
    """

    def __init__(
        self,
        rpc_url: Optional[str] = None,
        private_key: Optional[str] = None,
        contract_address: Optional[str] = None,
    ):
        self.rpc_url = rpc_url or settings.sepolia_rpc_url or os.getenv("SEPOLIA_RPC_URL", "")
        self.private_key = private_key or settings.sepolia_private_key or os.getenv("SEPOLIA_PRIVATE_KEY", "")
        self.contract_address = contract_address or settings.audit_contract_address or os.getenv("AUDIT_CONTRACT_ADDRESS", "")
        self.target_chain_id = settings.sepolia_chain_id

    def _is_configured(self) -> bool:
        if not HAS_WEB3 or not self.rpc_url or not self.private_key:
            return False
        if "mainnet" in self.rpc_url.lower():
            return False
        return True

    def _not_anchored(self, merkle_root: str, entries_count: int, ts: datetime, status: str, error: Optional[str] = None) -> AnchoringResult:
        return AnchoringResult(
            merkle_root=merkle_root,
            tx_hash=None,
            block_number=None,
            status=status,
            chain_id=self.target_chain_id,
            timestamp=ts,
            entries_count=entries_count,
            error=error,
        )

    async def anchor_hashes(self, leaf_hashes: List[str]) -> AnchoringResult:
        """Computes the Merkle root of ``leaf_hashes`` and anchors it on Sepolia when configured."""
        import asyncio

        now = datetime.now(timezone.utc)
        merkle_root = compute_merkle_root(leaf_hashes)

        if settings.dry_run or not self._is_configured():
            return self._not_anchored(merkle_root, len(leaf_hashes), now, "not_configured")

        def _submit_sepolia_tx() -> AnchoringResult:
            w3 = Web3(Web3.HTTPProvider(self.rpc_url))
            if not w3.is_connected():
                return self._not_anchored(merkle_root, len(leaf_hashes), now, "failed", "Sepolia RPC unreachable")

            # HARD GUARD: Never allow Mainnet execution!
            chain_id = w3.eth.chain_id
            if chain_id == MAINNET_CHAIN_ID:
                raise MainnetForbiddenError(
                    "FATAL SECURITY VIOLATION: Connected to Ethereum Mainnet (Chain ID 1). "
                    "Anchoring is strictly restricted to Sepolia testnet. Aborting immediately."
                )
            if chain_id != self.target_chain_id:
                return self._not_anchored(
                    merkle_root, len(leaf_hashes), now, "failed", f"RPC is on chain {chain_id}, not Sepolia"
                )

            account = Account.from_key(self.private_key)
            tx = {
                "chainId": chain_id,
                "from": account.address,
                "to": self.contract_address if self.contract_address else account.address,
                "value": 0,
                "nonce": w3.eth.get_transaction_count(account.address),
                "gas": 60000,
                "gasPrice": w3.eth.gas_price,
                "data": bytes.fromhex(merkle_root),  # the 32-byte Merkle root
            }
            signed_tx = w3.eth.account.sign_transaction(tx, private_key=self.private_key)
            tx_hash_bytes = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
            tx_hash = "0x" + tx_hash_bytes.hex().replace("0x", "")

            block_number = None
            try:
                receipt = w3.eth.wait_for_transaction_receipt(tx_hash_bytes, timeout=30)
                block_number = receipt.blockNumber
                status = "confirmed" if receipt.status == 1 else "failed"
            except Exception:
                status = "submitted"

            return AnchoringResult(
                merkle_root=merkle_root,
                tx_hash=tx_hash,
                block_number=block_number,
                status=status,
                chain_id=chain_id,
                timestamp=now,
                entries_count=len(leaf_hashes),
                explorer_url=sepolia_tx_url(tx_hash),
                wallet_address=account.address,
            )

        try:
            return await asyncio.to_thread(_submit_sepolia_tx)
        except MainnetForbiddenError:
            raise
        except Exception as e:
            # Typical causes: wallet has no Sepolia ETH, bad key, RPC rate limit
            logger.warning("Sepolia anchoring failed: %s", e)
            return self._not_anchored(merkle_root, len(leaf_hashes), now, "failed", type(e).__name__)

    def get_sepolia_health(self) -> Dict[str, Any]:
        """Reports whether anchoring is configured and the Sepolia RPC's current block height."""
        if not HAS_WEB3 or not self.rpc_url:
            return {"configured": False, "connected": False, "anchoring_enabled": False}
        try:
            w3 = Web3(Web3.HTTPProvider(self.rpc_url))
            if w3.is_connected():
                health = {
                    "configured": True,
                    "connected": True,
                    "chain_id": int(w3.eth.chain_id),
                    "block_number": int(w3.eth.block_number),
                    "gas_price_gwei": float(f"{int(w3.eth.gas_price) / 1e9:.6g}"),
                    "anchoring_enabled": self._is_configured(),
                }
                if self.private_key:
                    address = Account.from_key(self.private_key).address
                    health["wallet_address"] = address
                    health["wallet_url"] = f"{SEPOLIA_EXPLORER}/address/{address}"
                    health["wallet_balance_eth"] = round(int(w3.eth.get_balance(address)) / 1e18, 6)
                return health
            return {"configured": True, "connected": False, "anchoring_enabled": False, "error": "RPC unreachable"}
        except Exception as e:
            # Never echo the exception: RPC URLs usually embed the provider API key
            logger.warning("Sepolia health check failed: %s", e)
            return {"configured": True, "connected": False, "anchoring_enabled": False, "error": "RPC error"}

    async def anchor_client_audit_trail(self, db: AsyncSession, client_id: str) -> AnchoringResult:
        """Anchors the Merkle root of all of a client's audit entries."""
        stmt = select(DBAuditLog).where(DBAuditLog.client_id == client_id).order_by(DBAuditLog.timestamp.asc())
        entries = (await db.execute(stmt)).scalars().all()
        leaf_hashes = [e.entry_hash for e in entries if getattr(e, "entry_hash", None)]
        return await self.anchor_hashes(leaf_hashes)

    async def verify_anchor(self, merkle_root: str, tx_hash: str) -> bool:
        """Checks on-chain that transaction ``tx_hash`` carries ``merkle_root`` in its input data."""
        import asyncio

        if not self._is_configured() or not tx_hash:
            return False

        def _verify_sepolia_tx() -> bool:
            w3 = Web3(Web3.HTTPProvider(self.rpc_url))
            if not w3.is_connected():
                return False
            tx = w3.eth.get_transaction(tx_hash)
            input_data = tx.input.hex().lower().replace("0x", "")
            return merkle_root.lower().replace("0x", "") in input_data

        try:
            return await asyncio.to_thread(_verify_sepolia_tx)
        except Exception:
            return False


# Global singleton
_anchoring_service_instance: Optional[AnchoringService] = None


def get_anchoring_service() -> AnchoringService:
    global _anchoring_service_instance
    if _anchoring_service_instance is None:
        _anchoring_service_instance = AnchoringService()
    return _anchoring_service_instance
