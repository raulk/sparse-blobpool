from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from heuristic_sim.config import MAX_TXS_PER_SENDER, EvictionPolicy, Role

if TYPE_CHECKING:
    from collections.abc import Iterator


@dataclass
class TxEntry:
    tx_hash: str
    sender: str
    nonce: int
    fee: float
    first_seen: float
    role: Role
    cell_mask: int = 0
    announcers: set[str] = field(default_factory=set)
    evicted: bool = False
    eviction_reason: str = ""


class TxStore:
    def __init__(
        self,
        capacity: int = 15000,
        max_per_sender: int = MAX_TXS_PER_SENDER,
        eviction_policy: EvictionPolicy = EvictionPolicy.FEE_BASED,
        age_weight: float = 0.5,
    ) -> None:
        self._capacity = capacity
        self._max_per_sender = max_per_sender
        self._eviction_policy = eviction_policy
        self._age_weight = age_weight
        self._txs: dict[str, TxEntry] = {}
        self._by_sender: dict[str, list[str]] = {}

    @property
    def count(self) -> int:
        return len(self._txs)

    def get(self, tx_hash: str) -> TxEntry | None:
        return self._txs.get(tx_hash)

    def contains(self, tx_hash: str) -> bool:
        return tx_hash in self._txs

    def add(self, tx: TxEntry) -> list[str]:
        """Add a transaction, returning hashes of any evicted txs.

        Returns an empty list without inserting if the sender limit is reached.
        """
        sender_txs = self._by_sender.get(tx.sender, [])
        if len(sender_txs) >= self._max_per_sender:
            return []

        evicted: list[str] = []
        while len(self._txs) >= self._capacity:
            victim = self._evict_one()
            if victim:
                evicted.append(victim)
            else:
                return []

        self._txs[tx.tx_hash] = tx
        self._by_sender.setdefault(tx.sender, []).append(tx.tx_hash)
        return evicted

    def remove(self, tx_hash: str) -> TxEntry | None:
        tx = self._txs.pop(tx_hash, None)
        if tx is not None:
            sender_txs = self._by_sender.get(tx.sender, [])
            if tx_hash in sender_txs:
                sender_txs.remove(tx_hash)
        return tx

    def iter_all(self) -> Iterator[TxEntry]:
        yield from self._txs.values()

    def _evict_one(self) -> str | None:
        if not self._txs:
            return None
        match self._eviction_policy:
            case EvictionPolicy.FEE_BASED:
                return self._evict_lowest_fee()
            case EvictionPolicy.AGE_BASED:
                return self._evict_oldest()
            case EvictionPolicy.HYBRID:
                return self._evict_hybrid()

    def _evict_lowest_fee(self) -> str | None:
        if not self._txs:
            return None
        worst = min(self._txs.values(), key=lambda t: t.fee)
        self.remove(worst.tx_hash)
        worst.evicted = True
        worst.eviction_reason = "capacity"
        return worst.tx_hash

    def _evict_oldest(self) -> str | None:
        if not self._txs:
            return None
        oldest = min(self._txs.values(), key=lambda t: t.first_seen)
        self.remove(oldest.tx_hash)
        oldest.evicted = True
        oldest.eviction_reason = "capacity_age"
        return oldest.tx_hash

    def _evict_hybrid(self) -> str | None:
        """Evict by combined fee + age score.

        Score = (1 - age_weight) * normalized_fee + age_weight * normalized_recency.
        Lowest score (low fee, old entry) gets evicted.
        """
        if not self._txs:
            return None
        entries = list(self._txs.values())
        if len(entries) == 1:
            return self._evict_lowest_fee()

        max_fee = max(e.fee for e in entries)
        min_seen = min(e.first_seen for e in entries)
        max_seen = max(e.first_seen for e in entries)
        age_range = max_seen - min_seen
        if age_range == 0:
            return self._evict_lowest_fee()

        fee_w = 1.0 - self._age_weight
        age_w = self._age_weight

        def score(e: TxEntry) -> float:
            fee_norm = e.fee / max_fee if max_fee > 0 else 0.0
            recency_norm = (e.first_seen - min_seen) / age_range
            return fee_w * fee_norm + age_w * recency_norm

        worst = min(entries, key=score)
        self.remove(worst.tx_hash)
        worst.evicted = True
        worst.eviction_reason = "capacity_hybrid"
        return worst.tx_hash
