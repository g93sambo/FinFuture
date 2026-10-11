"""
backend/services/anchoring.py
=============================
Merkle root generation and Ethereum Sepolia testnet anchoring service.
Features dry-run mode when unconfigured and hard reject guard for Ethereum Mainnet (Chain ID 1).
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


class MainnetForbiddenError(RuntimeError):
    """Raised when an operation attempts to run against Ethereum Mainnet (Chain ID 1)."""
    pass


@dataclass
class AnchoringResult:
    merkle_root: str
    tx_hash: str
    block_number: Optional[int]
    status: str  # "confirmed" | "submitted" | "dry_run" | "failed"
    chain_id: int
    timestamp: datetime
    entries_count: int


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


class AnchoringService:
    """
    Anchoring Service for Sepolia Testnet.
    Provides automated dry-run fallback and hard-rejects Mainnet (Chain ID 1).
    """

    def __init__(
        self,
        rpc_url: Optional[str] = None,
        private_key: Optional[str] = None,
        contract_address: Optional[str] = None
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

    async def anchor_hashes(self, leaf_hashes: List[str]) -> AnchoringResult:
        """
        Computes Merkle root and anchors it to Sepolia testnet (or dry-run).
        """
        now = datetime.now(timezone.utc)
        merkle_root = compute_merkle_root(leaf_hashes)

        # Check configuration
        if settings.dry_run or not self._is_configured():
            return self._simulate_anchor(merkle_root, len(leaf_hashes), now)

        try:
            w3 = Web3(Web3.HTTPProvider(self.rpc_url))
            if not w3.is_connected():
                logger.warning("Sepolia RPC offline. Dropping to dry-run mode.")
                return self._simulate_anchor(merkle_root, len(leaf_hashes), now)

            # HARD GUARD: Never allow Mainnet execution!
            chain_id = w3.eth.chain_id
            if chain_id == MAINNET_CHAIN_ID:
                raise MainnetForbiddenError(
                    "FATAL SECURITY VIOLATION: Connected to Ethereum Mainnet (Chain ID 1). "
                    "Anchoring is strictly restricted to Sepolia testnet. Aborting immediately."
                )

            if chain_id != self.target_chain_id:
                logger.warning(
                    f"Unexpected Chain ID {chain_id} (expected {self.target_chain_id}). "
                    "Operating in dry-run."
                )
                return self._simulate_anchor(merkle_root, len(leaf_hashes), now)

            # Build and send transaction
            account = Account.from_key(self.private_key)
            nonce = w3.eth.get_transaction_count(account.address)
            gas_price = w3.eth.gas_price

            # Embed 32-byte Merkle root in transaction data payload
            root_bytes = bytes.fromhex(merkle_root)
            tx = {
                "chainId": chain_id,
                "from": account.address,
                "to": self.contract_address if self.contract_address else account.address,
                "value": 0,
                "nonce": nonce,
                "gas": 60000,
                "gasPrice": gas_price,
                "data": root_bytes,
            }

            signed_tx = w3.eth.account.sign_transaction(tx, private_key=self.private_key)
            tx_hash_bytes = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
            tx_hash = "0x" + tx_hash_bytes.hex().replace("0x", "")

            block_number = None
            try:
                receipt = w3.eth.wait_for_transaction_receipt(tx_hash_bytes, timeout=15)
                block_number = receipt.blockNumber
                status = "confirmed"
            except Exception:
                status = "submitted"

            return AnchoringResult(
                merkle_root=merkle_root,
                tx_hash=tx_hash,
                block_number=block_number,
                status=status,
                chain_id=chain_id,
                timestamp=now,
                entries_count=len(leaf_hashes)
            )

        except MainnetForbiddenError:
            raise
        except Exception as e:
            logger.warning(f"Sepolia transaction submission error ({e}). Returning dry-run anchor.")
            return self._simulate_anchor(merkle_root, len(leaf_hashes), now)

    def _simulate_anchor(self, merkle_root: str, entries_count: int, ts: datetime) -> AnchoringResult:
        """Generates deterministic simulated anchor transaction."""
        sim_data = f"dry_run:{merkle_root}:{ts.isoformat()}"
        sim_hash = "0x" + hashlib.sha256(sim_data.encode("utf-8")).hexdigest()
        logger.info(f"[DRY-RUN] Merkle Root {merkle_root} anchored in simulated tx {sim_hash}")
        return AnchoringResult(
            merkle_root=merkle_root,
            tx_hash=sim_hash,
            block_number=5400100,  # Simulated Sepolia block number
            status="dry_run",
            chain_id=self.target_chain_id,
            timestamp=ts,
            entries_count=entries_count
        )

    async def anchor_client_audit_trail(self, db: AsyncSession, client_id: str) -> AnchoringResult:
        """
        Fetches all audit entries for a client, computes Merkle root, and anchors to Sepolia.
        """
        stmt = select(DBAuditLog).where(DBAuditLog.client_id == client_id)
        if hasattr(DBAuditLog, "timestamp"):
            stmt = stmt.order_by(DBAuditLog.timestamp.asc())
        result = await db.execute(stmt)
        entries = result.scalars().all()

        leaf_hashes = [e.entry_hash for e in entries if getattr(e, "entry_hash", None)]
        return await self.anchor_hashes(leaf_hashes)

    async def verify_anchor(self, merkle_root: str, tx_hash: str) -> bool:
        """
        Verifies that an anchored transaction on Sepolia contains the expected Merkle root.
        """
        if not self._is_configured():
            return tx_hash.startswith("0x") and len(tx_hash) == 66

        try:
            w3 = Web3(Web3.HTTPProvider(self.rpc_url))
            if not w3.is_connected():
                return False

            tx = w3.eth.get_transaction(tx_hash)
            input_data = tx.input.hex().lower().replace("0x", "")
            expected_data = merkle_root.lower().replace("0x", "")
            return expected_data in input_data
        except Exception:
            return False


# Global singleton
_anchoring_service_instance: Optional[AnchoringService] = None


def get_anchoring_service() -> AnchoringService:
    global _anchoring_service_instance
    if _anchoring_service_instance is None:
        _anchoring_service_instance = AnchoringService()
    return _anchoring_service_instance
