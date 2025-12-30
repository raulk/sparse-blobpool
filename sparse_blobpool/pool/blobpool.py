"""Blobpool state management with RBF and eviction support."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from sparse_blobpool.protocol.constants import ALL_ONES, CELL_SIZE, CELLS_PER_BLOB

if TYPE_CHECKING:
    from sparse_blobpool.config import SimulationConfig
    from sparse_blobpool.core.types import ActorId, Address, TxHash


@dataclass
class BlobTxEntry:
    """A blob transaction entry in the pool.

    Stores transaction metadata and cell availability without holding
    actual blob data. Cell data is requested on-demand from peers.
    """

    tx_hash: TxHash
    sender: Address
    nonce: int
    gas_fee_cap: int  # maxFeePerGas in wei
    gas_tip_cap: int  # maxPriorityFeePerGas in wei
    blob_gas_price: int  # maxFeePerBlobGas in wei
    tx_size: int  # envelope size without blob data
    blob_count: int  # number of blobs (1-6)
    cell_mask: int = ALL_ONES  # uint128 bitmap of available columns
    received_at: float = 0.0  # simulation timestamp when received
    announced_to: set[ActorId] = field(default_factory=set)

    @property
    def effective_tip(self) -> int:
        return self.gas_tip_cap

    @property
    def total_blob_cells(self) -> int:
        return self.blob_count * CELLS_PER_BLOB

    @property
    def total_blob_size(self) -> int:
        return self.total_blob_cells * CELL_SIZE

    @property
    def has_full_availability(self) -> bool:
        return self.cell_mask == ALL_ONES

    def available_column_count(self) -> int:
        return bin(self.cell_mask).count("1")


class RBFRejected(Exception):
    """Transaction rejected due to insufficient fee bump for RBF."""

    def __init__(self, existing_hash: TxHash, required_bump_pct: int = 10) -> None:
        self.existing_hash = existing_hash
        self.required_bump_pct = required_bump_pct
        super().__init__(
            f"RBF rejected: must bump fees by at least {required_bump_pct}% "
            f"to replace {existing_hash}"
        )


class PoolFull(Exception):
    """Transaction rejected because pool is at capacity."""

    def __init__(self, pool_size: int, max_size: int) -> None:
        self.pool_size = pool_size
        self.max_size = max_size
        super().__init__(f"Pool full: {pool_size}/{max_size} bytes")


class SenderLimitExceeded(Exception):
    """Transaction rejected due to per-sender limit."""

    def __init__(self, sender: Address, count: int, max_count: int) -> None:
        self.sender = sender
        self.count = count
        self.max_count = max_count
        super().__init__(f"Sender {sender} has {count}/{max_count} transactions")


@dataclass
class AddResult:
    """Result of adding a transaction to the pool."""

    added: bool
    replaced: TxHash | None = None  # hash of replaced tx if RBF occurred
    evicted: list[TxHash] = field(default_factory=list)  # hashes evicted for space


class Blobpool:
    """Manages blob transaction storage with RBF support and eviction.

    Transactions are indexed by hash and by sender. The pool enforces:
    - Maximum total size in bytes
    - Maximum transactions per sender
    - RBF rules requiring 10% fee bump to replace same-nonce transactions
    """

    RBF_BUMP_PERCENT = 10  # Required fee bump percentage for RBF

    def __init__(self, config: SimulationConfig) -> None:
        self._config = config
        self._txs: dict[TxHash, BlobTxEntry] = {}
        self._by_sender: dict[Address, dict[int, TxHash]] = {}  # sender -> nonce -> hash
        self._total_size = 0

    @property
    def size_bytes(self) -> int:
        return self._total_size

    @property
    def tx_count(self) -> int:
        return len(self._txs)

    def get(self, tx_hash: TxHash) -> BlobTxEntry | None:
        return self._txs.get(tx_hash)

    def contains(self, tx_hash: TxHash) -> bool:
        return tx_hash in self._txs

    def get_by_sender(self, sender: Address) -> list[BlobTxEntry]:
        nonce_map = self._by_sender.get(sender, {})
        return [self._txs[h] for h in nonce_map.values()]

    def sender_tx_count(self, sender: Address) -> int:
        return len(self._by_sender.get(sender, {}))

    def add(self, entry: BlobTxEntry) -> AddResult:
        """Add a transaction to the pool.

        Handles RBF replacement if a transaction with the same sender/nonce exists.
        May evict lower-priority transactions if pool is full.

        Raises:
            RBFRejected: If replacement doesn't meet fee bump requirements.
            SenderLimitExceeded: If sender has too many non-replaceable transactions.
        """
        result = AddResult(added=False)

        # Check for existing transaction with same sender/nonce (RBF candidate)
        sender_nonces = self._by_sender.get(entry.sender, {})
        existing_hash = sender_nonces.get(entry.nonce)

        if existing_hash is not None:
            existing = self._txs[existing_hash]
            if not self._can_replace(existing, entry):
                raise RBFRejected(existing_hash, self.RBF_BUMP_PERCENT)
            # Remove the existing transaction (will be replaced)
            self._remove_internal(existing_hash)
            result.replaced = existing_hash

        # Check sender limit (after potential RBF removal)
        current_count = self.sender_tx_count(entry.sender)
        if current_count >= self._config.max_txs_per_sender:
            raise SenderLimitExceeded(entry.sender, current_count, self._config.max_txs_per_sender)

        # Evict if needed to make room
        space_needed = entry.tx_size
        while self._total_size + space_needed > self._config.blobpool_max_bytes:
            evicted = self._evict_lowest_priority(
                exclude=entry.tx_hash, min_priority=entry.effective_tip
            )
            if evicted is None:
                # Can't evict anything (new tx would be lowest priority)
                raise PoolFull(self._total_size, self._config.blobpool_max_bytes)
            result.evicted.append(evicted)

        # Add the transaction
        self._txs[entry.tx_hash] = entry
        if entry.sender not in self._by_sender:
            self._by_sender[entry.sender] = {}
        self._by_sender[entry.sender][entry.nonce] = entry.tx_hash
        self._total_size += entry.tx_size
        result.added = True

        return result

    def remove(self, tx_hash: TxHash) -> BlobTxEntry | None:
        if tx_hash not in self._txs:
            return None
        return self._remove_internal(tx_hash)

    def remove_batch(self, tx_hashes: list[TxHash]) -> list[BlobTxEntry]:
        return [e for h in tx_hashes if (e := self.remove(h)) is not None]

    def update_cell_mask(self, tx_hash: TxHash, new_mask: int) -> bool:
        entry = self._txs.get(tx_hash)
        if entry is None:
            return False
        entry.cell_mask = new_mask
        return True

    def merge_cells(self, tx_hash: TxHash, received_mask: int) -> int | None:
        entry = self._txs.get(tx_hash)
        if entry is None:
            return None
        entry.cell_mask |= received_mask
        return entry.cell_mask

    def iter_by_priority(self) -> list[BlobTxEntry]:
        return sorted(self._txs.values(), key=lambda e: e.effective_tip, reverse=True)

    def iter_expired(self, current_time: float, ttl: float) -> list[BlobTxEntry]:
        cutoff = current_time - ttl
        return [e for e in self._txs.values() if e.received_at < cutoff]

    def clear(self) -> None:
        self._txs.clear()
        self._by_sender.clear()
        self._total_size = 0

    def _can_replace(self, existing: BlobTxEntry, replacement: BlobTxEntry) -> bool:
        """Check if replacement meets RBF fee bump requirements.

        Both gas_fee_cap and gas_tip_cap must be bumped by at least RBF_BUMP_PERCENT.
        """
        min_fee_cap = existing.gas_fee_cap * (100 + self.RBF_BUMP_PERCENT) // 100
        min_tip_cap = existing.gas_tip_cap * (100 + self.RBF_BUMP_PERCENT) // 100

        return replacement.gas_fee_cap >= min_fee_cap and replacement.gas_tip_cap >= min_tip_cap

    def _remove_internal(self, tx_hash: TxHash) -> BlobTxEntry:
        """Internal removal without existence check."""
        entry = self._txs.pop(tx_hash)
        self._total_size -= entry.tx_size

        # Update sender index
        sender_nonces = self._by_sender.get(entry.sender)
        if sender_nonces:
            sender_nonces.pop(entry.nonce, None)
            if not sender_nonces:
                del self._by_sender[entry.sender]

        return entry

    def _evict_lowest_priority(
        self, exclude: TxHash | None = None, min_priority: int | None = None
    ) -> TxHash | None:
        """Evict the lowest priority transaction. Returns evicted hash or None.

        Only evicts if there's a transaction with priority lower than min_priority.
        """
        if not self._txs:
            return None

        # Find lowest priority (lowest effective_tip)
        lowest: BlobTxEntry | None = None
        for entry in self._txs.values():
            if entry.tx_hash == exclude:
                continue
            if lowest is None or entry.effective_tip < lowest.effective_tip:
                lowest = entry

        if lowest is None:
            return None

        # Don't evict if lowest priority is >= the incoming tx priority
        if min_priority is not None and lowest.effective_tip >= min_priority:
            return None

        self._remove_internal(lowest.tx_hash)
        return lowest.tx_hash
