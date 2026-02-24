from __future__ import annotations

import heapq
from collections import deque
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterator

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CELLS_PER_BLOB = 128
ALL_ONES = (1 << CELLS_PER_BLOB) - 1
RECONSTRUCTION_THRESHOLD = 64
DEFAULT_MESH_DEGREE = 50
MAX_TXS_PER_SENDER = 16

# ---------------------------------------------------------------------------
# Task 1: Event loop
# ---------------------------------------------------------------------------


@dataclass(order=True)
class Event:
    t: float
    kind: str = field(compare=False)
    data: dict[str, Any] = field(default_factory=dict, compare=False)


class EventLoop:
    def __init__(self) -> None:
        self._queue: list[Event] = []
        self._time = 0.0

    @property
    def now(self) -> float:
        return self._time

    def schedule(self, event: Event) -> None:
        heapq.heappush(self._queue, event)

    def run(self) -> Iterator[Event]:
        while self._queue:
            event = heapq.heappop(self._queue)
            self._time = event.t
            yield event


# ---------------------------------------------------------------------------
# Task 2: Heuristic config and protocol types
# ---------------------------------------------------------------------------


def columns_to_mask(columns: list[int]) -> int:
    mask = 0
    for c in columns:
        mask |= 1 << c
    return mask


def mask_to_columns(mask: int) -> list[int]:
    return [i for i in range(CELLS_PER_BLOB) if mask & (1 << i)]


def popcount(mask: int) -> int:
    return bin(mask).count("1")


@dataclass(frozen=True)
class HeuristicConfig:
    includability_discount: float = 0.7
    saturation_timeout: float = 30.0
    min_independent_peers: int = 2
    c_extra_max: int = 4
    max_random_failure_rate: float = 0.1
    tracking_window: int = 100
    k_high: int = 2
    k_low: int = 4
    score_threshold: float = 0.5
    conservative_inclusion: bool = True
    provider_probability: float = 0.15
    custody_columns: int = 8
    tx_ttl: float = 300.0
    pool_capacity: int = 15000
    blob_base_fee: float = 1.0


class Role(Enum):
    PROVIDER = auto()
    SAMPLER = auto()


# ---------------------------------------------------------------------------
# Task 3: Peer state and tracking
# ---------------------------------------------------------------------------


@dataclass
class PeerState:
    peer_id: str
    behavior: str
    connected_at: float
    score: float = 0.0
    provider_announcements: int = 0
    sampler_announcements: int = 0
    announcements_made: int = 0
    cells_served: int = 0
    included_contributions: int = 0
    _random_col_results: deque[bool] = field(default_factory=lambda: deque(maxlen=100))
    disconnected: bool = False
    disconnect_reason: str = ""
    disconnect_time: float = 0.0

    def record_random_column_result(self, success: bool) -> None:
        self._random_col_results.append(success)

    def random_column_failure_rate(self) -> float:
        if not self._random_col_results:
            return 0.0
        failures = sum(1 for r in self._random_col_results if not r)
        return failures / len(self._random_col_results)

    def provider_rate(self) -> float:
        total = self.provider_announcements + self.sampler_announcements
        if total == 0:
            return 0.0
        return self.provider_announcements / total


# ---------------------------------------------------------------------------
# Task 4: Transaction state and blobpool store
# ---------------------------------------------------------------------------


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
        self, capacity: int = 15000, max_per_sender: int = MAX_TXS_PER_SENDER
    ) -> None:
        self._capacity = capacity
        self._max_per_sender = max_per_sender
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
            victim = self._evict_lowest_fee()
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

    def _evict_lowest_fee(self) -> str | None:
        if not self._txs:
            return None
        worst = min(self._txs.values(), key=lambda t: t.fee)
        self.remove(worst.tx_hash)
        worst.evicted = True
        worst.eviction_reason = "capacity"
        return worst.tx_hash
