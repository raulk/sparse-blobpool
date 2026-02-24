from __future__ import annotations

import heapq
from collections import deque
from dataclasses import dataclass, field
from enum import Enum, auto
from hashlib import sha256
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import random
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


# ---------------------------------------------------------------------------
# Task 5: Peer behavior generators
# ---------------------------------------------------------------------------


class PeerBehavior:
    def __init__(self, peer_id: str, rng: random.Random) -> None:
        self.peer_id = peer_id
        self.rng = rng
        self.label = "base"

    def generate_events(self, **kwargs: Any) -> list[Event]:
        raise NotImplementedError

    def respond_to_cell_request(
        self, columns: list[int], requester_custody: int
    ) -> dict[str, list[int]]:
        raise NotImplementedError

    def _make_tx_hash(self, sender: str, nonce: int) -> str:
        return sha256(f"{sender}:{nonce}:{self.rng.random()}".encode()).hexdigest()[:16]


class HonestBehavior(PeerBehavior):
    def __init__(
        self,
        peer_id: str,
        rng: random.Random,
        *,
        provider_prob: float = 0.15,
        custody_columns: int = 8,
    ) -> None:
        super().__init__(peer_id, rng)
        self.label = "honest"
        self.provider_prob = provider_prob
        self.custody = rng.sample(range(CELLS_PER_BLOB), custody_columns)

    def generate_events(self, **kwargs: Any) -> list[Event]:
        t_start: float = kwargs["t_start"]
        t_end: float = kwargs["t_end"]
        tx_rate: float = kwargs.get("tx_rate", 1.0)
        blob_base_fee: float = kwargs.get("blob_base_fee", 1.0)

        events: list[Event] = []
        t = t_start + self.rng.expovariate(tx_rate)
        while t < t_end:
            sender = f"sender_{self.rng.randint(0, 999)}"
            nonce = self.rng.randint(0, 15)
            fee = blob_base_fee * self.rng.uniform(0.8, 3.0)
            is_provider = self.rng.random() < self.provider_prob
            cell_mask = ALL_ONES if is_provider else columns_to_mask(self.custody)
            events.append(Event(
                t=t,
                kind="announce",
                data={
                    "tx_hash": self._make_tx_hash(sender, nonce),
                    "sender": sender,
                    "nonce": nonce,
                    "fee": fee,
                    "cell_mask": cell_mask,
                    "is_provider": is_provider,
                    "exclusive": False,
                    "peer_id": self.peer_id,
                },
            ))
            t += self.rng.expovariate(tx_rate)
        return events

    def respond_to_cell_request(
        self, columns: list[int], requester_custody: int
    ) -> dict[str, list[int]]:
        return {"served": list(columns), "failed": []}


class SpammerBehavior(PeerBehavior):
    def __init__(
        self,
        peer_id: str,
        rng: random.Random,
        *,
        rate: float = 10.0,
        below_includability: bool = True,
    ) -> None:
        super().__init__(peer_id, rng)
        self.label = "spammer"
        self.rate = rate
        self.below_includability = below_includability

    def generate_events(self, **kwargs: Any) -> list[Event]:
        t_start: float = kwargs["t_start"]
        t_end: float = kwargs["t_end"]
        blob_base_fee: float = kwargs.get("blob_base_fee", 1.0)
        includability_discount: float = kwargs.get("includability_discount", 0.7)

        events: list[Event] = []
        t = t_start + self.rng.expovariate(self.rate)
        sender_counter = 0
        while t < t_end:
            sender = f"spam_{self.peer_id}_{sender_counter}"
            sender_counter += 1
            nonce = 0
            if self.below_includability:
                fee = blob_base_fee * includability_discount * self.rng.uniform(0.1, 0.99)
            else:
                fee = blob_base_fee * self.rng.uniform(0.8, 1.5)
            events.append(Event(
                t=t,
                kind="announce",
                data={
                    "tx_hash": self._make_tx_hash(sender, nonce),
                    "sender": sender,
                    "nonce": nonce,
                    "fee": fee,
                    "cell_mask": ALL_ONES,
                    "is_provider": True,
                    "exclusive": False,
                    "peer_id": self.peer_id,
                },
            ))
            t += self.rng.expovariate(self.rate)
        return events

    def respond_to_cell_request(
        self, columns: list[int], requester_custody: int
    ) -> dict[str, list[int]]:
        return {"served": [], "failed": list(columns)}


class WithholderBehavior(PeerBehavior):
    """T2.1: claims provider but withholds columns outside requester's custody."""

    def __init__(
        self,
        peer_id: str,
        rng: random.Random,
        *,
        random_fail_rate: float = 1.0,
        provider_prob: float = 0.15,
        custody_columns: int = 8,
    ) -> None:
        super().__init__(peer_id, rng)
        self.label = "withholder"
        self.random_fail_rate = random_fail_rate
        self.provider_prob = provider_prob
        self.custody = rng.sample(range(CELLS_PER_BLOB), custody_columns)

    def generate_events(self, **kwargs: Any) -> list[Event]:
        t_start: float = kwargs["t_start"]
        t_end: float = kwargs["t_end"]
        tx_rate: float = kwargs.get("tx_rate", 1.0)
        blob_base_fee: float = kwargs.get("blob_base_fee", 1.0)

        events: list[Event] = []
        t = t_start + self.rng.expovariate(tx_rate)
        while t < t_end:
            sender = f"sender_{self.rng.randint(0, 999)}"
            nonce = self.rng.randint(0, 15)
            fee = blob_base_fee * self.rng.uniform(0.8, 3.0)
            events.append(Event(
                t=t,
                kind="announce",
                data={
                    "tx_hash": self._make_tx_hash(sender, nonce),
                    "sender": sender,
                    "nonce": nonce,
                    "fee": fee,
                    "cell_mask": ALL_ONES,
                    "is_provider": True,
                    "exclusive": False,
                    "peer_id": self.peer_id,
                },
            ))
            t += self.rng.expovariate(tx_rate)
        return events

    def respond_to_cell_request(
        self, columns: list[int], requester_custody: int
    ) -> dict[str, list[int]]:
        custody_cols = mask_to_columns(requester_custody)
        custody_set = set(custody_cols)
        served: list[int] = []
        failed: list[int] = []
        for col in columns:
            if col in custody_set:
                served.append(col)
            elif self.rng.random() < self.random_fail_rate:
                failed.append(col)
            else:
                served.append(col)
        return {"served": served, "failed": failed}


class SpooferBehavior(PeerBehavior):
    """T2.2: claims provider but has no real data at all."""

    def __init__(
        self,
        peer_id: str,
        rng: random.Random,
        *,
        provider_prob: float = 0.15,
        custody_columns: int = 8,
    ) -> None:
        super().__init__(peer_id, rng)
        self.label = "spoofer"
        self.provider_prob = provider_prob
        self.custody = rng.sample(range(CELLS_PER_BLOB), custody_columns)

    def generate_events(self, **kwargs: Any) -> list[Event]:
        t_start: float = kwargs["t_start"]
        t_end: float = kwargs["t_end"]
        tx_rate: float = kwargs.get("tx_rate", 1.0)
        blob_base_fee: float = kwargs.get("blob_base_fee", 1.0)

        events: list[Event] = []
        t = t_start + self.rng.expovariate(tx_rate)
        while t < t_end:
            sender = f"sender_{self.rng.randint(0, 999)}"
            nonce = self.rng.randint(0, 15)
            fee = blob_base_fee * self.rng.uniform(0.8, 3.0)
            events.append(Event(
                t=t,
                kind="announce",
                data={
                    "tx_hash": self._make_tx_hash(sender, nonce),
                    "sender": sender,
                    "nonce": nonce,
                    "fee": fee,
                    "cell_mask": ALL_ONES,
                    "is_provider": True,
                    "exclusive": False,
                    "peer_id": self.peer_id,
                },
            ))
            t += self.rng.expovariate(tx_rate)
        return events

    def respond_to_cell_request(
        self, columns: list[int], requester_custody: int
    ) -> dict[str, list[int]]:
        return {"served": [], "failed": list(columns)}


class FreeRiderBehavior(PeerBehavior):
    """T3.1: only serves custody columns, never claims provider."""

    def __init__(
        self,
        peer_id: str,
        rng: random.Random,
        *,
        custody_columns: int = 8,
    ) -> None:
        super().__init__(peer_id, rng)
        self.label = "free_rider"
        self.custody = rng.sample(range(CELLS_PER_BLOB), custody_columns)

    def generate_events(self, **kwargs: Any) -> list[Event]:
        t_start: float = kwargs["t_start"]
        t_end: float = kwargs["t_end"]
        tx_rate: float = kwargs.get("tx_rate", 1.0)
        blob_base_fee: float = kwargs.get("blob_base_fee", 1.0)

        events: list[Event] = []
        t = t_start + self.rng.expovariate(tx_rate)
        while t < t_end:
            sender = f"sender_{self.rng.randint(0, 999)}"
            nonce = self.rng.randint(0, 15)
            fee = blob_base_fee * self.rng.uniform(0.8, 3.0)
            events.append(Event(
                t=t,
                kind="announce",
                data={
                    "tx_hash": self._make_tx_hash(sender, nonce),
                    "sender": sender,
                    "nonce": nonce,
                    "fee": fee,
                    "cell_mask": columns_to_mask(self.custody),
                    "is_provider": False,
                    "exclusive": False,
                    "peer_id": self.peer_id,
                },
            ))
            t += self.rng.expovariate(tx_rate)
        return events

    def respond_to_cell_request(
        self, columns: list[int], requester_custody: int
    ) -> dict[str, list[int]]:
        custody_set = set(self.custody)
        served = [c for c in columns if c in custody_set]
        failed = [c for c in columns if c not in custody_set]
        return {"served": served, "failed": failed}


class NonAnnouncerBehavior(PeerBehavior):
    """T3.3: never announces txs, only requests cells from us."""

    def __init__(self, peer_id: str, rng: random.Random) -> None:
        super().__init__(peer_id, rng)
        self.label = "non_announcer"

    def generate_events(self, **kwargs: Any) -> list[Event]:
        t_start: float = kwargs["t_start"]
        t_end: float = kwargs["t_end"]
        tx_rate: float = kwargs.get("tx_rate", 1.0)

        events: list[Event] = []
        t = t_start + self.rng.expovariate(tx_rate)
        while t < t_end:
            requested_cols = self.rng.sample(
                range(CELLS_PER_BLOB), self.rng.randint(1, 8)
            )
            events.append(Event(
                t=t,
                kind="inbound_request",
                data={
                    "columns": requested_cols,
                    "peer_id": self.peer_id,
                },
            ))
            t += self.rng.expovariate(tx_rate)
        return events

    def respond_to_cell_request(
        self, columns: list[int], requester_custody: int
    ) -> dict[str, list[int]]:
        return {"served": [], "failed": list(columns)}


class SelectiveSignalerBehavior(PeerBehavior):
    """T4.2: floods exclusive txs to monopolize victim's view of senders."""

    def __init__(
        self,
        peer_id: str,
        rng: random.Random,
        *,
        n_senders: int = 10,
        txs_per_sender: int = 16,
    ) -> None:
        super().__init__(peer_id, rng)
        self.label = "selective_signaler"
        self.n_senders = n_senders
        self.txs_per_sender = txs_per_sender

    def generate_events(self, **kwargs: Any) -> list[Event]:
        t_start: float = kwargs["t_start"]
        t_end: float = kwargs["t_end"]

        total_txs = self.n_senders * self.txs_per_sender
        duration = t_end - t_start
        interval = duration if total_txs <= 1 else duration / total_txs

        events: list[Event] = []
        t = t_start
        for s in range(self.n_senders):
            sender = f"target_sender_{s}"
            for nonce in range(self.txs_per_sender):
                events.append(Event(
                    t=t,
                    kind="announce",
                    data={
                        "tx_hash": self._make_tx_hash(sender, nonce),
                        "sender": sender,
                        "nonce": nonce,
                        "fee": 2.0,
                        "cell_mask": ALL_ONES,
                        "is_provider": True,
                        "exclusive": True,
                        "peer_id": self.peer_id,
                    },
                ))
                t += interval
        return events

    def respond_to_cell_request(
        self, columns: list[int], requester_custody: int
    ) -> dict[str, list[int]]:
        return {"served": list(columns), "failed": []}
