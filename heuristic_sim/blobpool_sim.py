from __future__ import annotations

import heapq
import random
from collections import deque
from dataclasses import dataclass, field
from enum import Enum, auto
from hashlib import sha256
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
ANNOUNCE_MSG_BYTES = 200
CELL_BYTES = 2048
REQUEST_MSG_OVERHEAD = 64

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
    max_request_to_announce_ratio: float = 5.0
    inbound_score_discount: float = 0.15
    provider_rate_tolerance: float = 0.3


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
    is_inbound: bool = True
    score: float = 0.0
    provider_announcements: int = 0
    sampler_announcements: int = 0
    announcements_made: int = 0
    cells_served: int = 0
    included_contributions: int = 0
    requests_received: int = 0
    requests_sent_to: int = 0
    bytes_in: int = 0
    bytes_out: int = 0
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
            # Honest peers also request cells from the target node
            # (they learn about txs from other peers and need cells too)
            n_cols = len(self.custody) + self.rng.randint(1, 4)
            requested_cols = self.rng.sample(range(CELLS_PER_BLOB), min(n_cols, CELLS_PER_BLOB))
            events.append(Event(
                t=t + self.rng.uniform(0.05, 0.2),
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


# ---------------------------------------------------------------------------
# Task 6: Node class with H1-H5 heuristics
# ---------------------------------------------------------------------------


class Node:
    def __init__(self, config: HeuristicConfig, seed: int = 42) -> None:
        self.config = config
        self.rng = random.Random(seed)
        self.pool = TxStore(capacity=config.pool_capacity, max_per_sender=MAX_TXS_PER_SENDER)
        self.peers: dict[str, PeerState] = {}
        self.custody_mask = self._pick_custody()
        self.log: list[dict[str, Any]] = []

    def _pick_custody(self) -> int:
        cols = self.rng.sample(range(CELLS_PER_BLOB), self.config.custody_columns)
        return columns_to_mask(cols)

    def add_peer(self, peer: PeerState) -> None:
        self.peers[peer.peer_id] = peer

    def disconnect_peer(self, peer_id: str, reason: str, t: float) -> None:
        peer = self.peers.get(peer_id)
        if peer and not peer.disconnected:
            peer.disconnected = True
            peer.disconnect_reason = reason
            peer.disconnect_time = t
            self.log.append({
                "t": t, "event": "disconnect", "peer_id": peer_id,
                "reason": reason, "behavior": peer.behavior,
            })

    def _determine_role(self, tx_hash: str) -> Role:
        h = sha256(f"role:{tx_hash}:{self.rng.random()}".encode()).digest()
        p = int.from_bytes(h[:8], "big") / (2**64)
        return Role.PROVIDER if p < self.config.provider_probability else Role.SAMPLER

    def compute_request_columns(self, *, is_provider: bool) -> list[int]:
        if is_provider:
            return list(range(CELLS_PER_BLOB))
        custody = mask_to_columns(self.custody_mask)
        non_custody = [c for c in range(CELLS_PER_BLOB) if c not in custody]
        c_extra = self.rng.randint(1, self.config.c_extra_max)
        extra = self.rng.sample(non_custody, min(c_extra, len(non_custody)))
        return custody + extra

    def handle_announce(
        self, peer_id: str, tx_hash: str, sender: str, nonce: int,
        fee: float, cell_mask: int, is_provider: bool, exclusive: bool, t: float,
    ) -> list[Event]:
        follow_up: list[Event] = []
        peer = self.peers.get(peer_id)
        if peer is None or peer.disconnected:
            return follow_up

        if is_provider:
            peer.provider_announcements += 1
        else:
            peer.sampler_announcements += 1
        peer.announcements_made += 1
        peer.bytes_in += ANNOUNCE_MSG_BYTES

        # H1: reject txs that can't be included at the current blob base fee
        if fee < self.config.blob_base_fee * self.config.includability_discount:
            self.log.append({
                "t": t, "event": "reject_h1", "tx_hash": tx_hash,
                "peer_id": peer_id, "fee": fee,
            })
            return follow_up

        existing = self.pool.get(tx_hash)
        if existing is not None:
            existing.announcers.add(peer_id)
            return follow_up

        role = self._determine_role(tx_hash)
        tx = TxEntry(
            tx_hash=tx_hash, sender=sender, nonce=nonce, fee=fee,
            first_seen=t, role=role, cell_mask=0, announcers={peer_id},
        )
        evicted = self.pool.add(tx)
        if not self.pool.contains(tx_hash):
            return follow_up

        for ev_hash in evicted:
            self.log.append({"t": t, "event": "evict_capacity", "tx_hash": ev_hash})

        # H2: verify the tx is independently announced by enough peers
        follow_up.append(Event(
            t=t + self.config.saturation_timeout,
            kind="saturation_check",
            data={"tx_hash": tx_hash},
        ))

        # H3: request cells with C_extra noise columns to detect withholders
        request_cols = self.compute_request_columns(is_provider=(role == Role.PROVIDER))
        peer.requests_sent_to += 1
        peer.bytes_out += REQUEST_MSG_OVERHEAD + len(request_cols) * 2
        follow_up.append(Event(
            t=t + 0.1,
            kind="request_cells",
            data={
                "peer_id": peer_id, "tx_hash": tx_hash,
                "columns": request_cols,
                "custody_columns": mask_to_columns(self.custody_mask),
            },
        ))

        self.log.append({
            "t": t, "event": "accept", "tx_hash": tx_hash,
            "role": role.name, "peer_id": peer_id,
        })
        return follow_up

    def handle_cells_response(
        self, peer_id: str, tx_hash: str,
        served: list[int], failed: list[int],
        custody_columns: list[int], t: float,
    ) -> list[Event]:
        follow_up: list[Event] = []
        peer = self.peers.get(peer_id)
        if peer is None or peer.disconnected:
            return follow_up

        peer.bytes_in += len(served) * CELL_BYTES

        custody_set = set(custody_columns)
        for col in served:
            if col not in custody_set:
                peer.record_random_column_result(success=True)
            peer.cells_served += 1

        for col in failed:
            if col not in custody_set:
                peer.record_random_column_result(success=False)

        # H4: disconnect peers with excessive random column failure rates
        if (
            len(peer._random_col_results) >= 10
            and peer.random_column_failure_rate() > self.config.max_random_failure_rate
        ):
            self.disconnect_peer(peer_id, "h4_random_col_failure", t)
            return follow_up

        tx = self.pool.get(tx_hash)
        if tx is not None:
            tx.cell_mask |= columns_to_mask(served)

        return follow_up

    def handle_saturation_check(self, tx_hash: str, t: float) -> list[Event]:
        tx = self.pool.get(tx_hash)
        if tx is None:
            return []
        independent = {
            p for p in tx.announcers
            if p in self.peers and not self.peers[p].disconnected
        }
        if len(independent) < self.config.min_independent_peers:
            self.pool.remove(tx_hash)
            self.log.append({
                "t": t, "event": "evict_h2_saturation",
                "tx_hash": tx_hash, "announcers": len(independent),
            })
        return []

    def handle_inbound_request(
        self, peer_id: str, columns: list[int], t: float,
    ) -> list[Event]:
        peer = self.peers.get(peer_id)
        if peer is None or peer.disconnected:
            return []

        peer.requests_received += 1
        peer.bytes_in += REQUEST_MSG_OVERHEAD + len(columns) * 2
        peer.bytes_out += len(columns) * CELL_BYTES

        self.log.append({
            "t": t, "event": "inbound_request_tracked",
            "peer_id": peer_id, "n_columns": len(columns),
        })

        # H5: disconnect peers with excessive request-to-announcement ratio
        total_ann = max(peer.announcements_made, 1)
        duration = t - peer.connected_at
        if (
            duration > 60.0
            and peer.requests_received / total_ann > self.config.max_request_to_announce_ratio
        ):
            self.disconnect_peer(peer_id, "h5_request_ratio", t)

        return []

    def handle_block(self, included_txs: list[str], t: float) -> list[Event]:
        for tx_hash in included_txs:
            tx = self.pool.get(tx_hash)
            if tx is not None:
                for peer_id in tx.announcers:
                    peer = self.peers.get(peer_id)
                    if peer:
                        peer.included_contributions += 1
                self.pool.remove(tx_hash)
        return []

    def score_peers(self, t: float) -> list[Event]:
        for peer in self.peers.values():
            if peer.disconnected:
                continue
            duration = t - peer.connected_at

            duration_score = min(duration / 300.0, 1.0)
            contribution_score = min(peer.included_contributions / 10.0, 1.0)
            failure_penalty = peer.random_column_failure_rate()
            announcer_penalty = 0.0 if peer.announcements_made > 0 else (0.3 if duration > 60.0 else 0.0)

            total_ann = max(peer.announcements_made, 1)
            request_ratio = peer.requests_received / total_ann
            request_ratio_penalty = min(request_ratio / self.config.max_request_to_announce_ratio, 1.0)

            expected_p = self.config.provider_probability
            actual_p = peer.provider_rate()
            provider_deviation = abs(actual_p - expected_p)
            provider_penalty = max(0.0, provider_deviation - self.config.provider_rate_tolerance)

            inbound_penalty = self.config.inbound_score_discount if peer.is_inbound else 0.0

            peer.score = (
                0.20 * duration_score
                + 0.30 * contribution_score
                - 0.15 * failure_penalty
                - 0.10 * announcer_penalty
                - 0.10 * request_ratio_penalty
                - 0.05 * provider_penalty
                - 0.10 * inbound_penalty
            )
        return []


# ---------------------------------------------------------------------------
# Task 7: Simulation runner
# ---------------------------------------------------------------------------


@dataclass
class Scenario:
    n_honest: int = 40
    attackers: list[tuple[int, str, dict[str, Any]]] = field(default_factory=list)
    tx_arrival_rate: float = 2.0
    t_end: float = 300.0
    blob_base_fee: float = 1.0
    block_interval: float = 12.0
    inbound_ratio: float = 0.68


@dataclass
class SimulationResult:
    total_accepted: int = 0
    total_rejected: int = 0
    h1_rejections: int = 0
    h2_evictions: int = 0
    h4_disconnects: int = 0
    h5_disconnects: int = 0
    disconnects_by_behavior: dict[str, int] = field(default_factory=dict)
    false_positives: int = 0
    detection_latencies: dict[str, list[float]] = field(default_factory=dict)
    peer_scores: dict[str, list[tuple[float, float]]] = field(default_factory=dict)
    pool_occupancy: list[tuple[float, int]] = field(default_factory=list)
    peer_counts: dict[str, int] = field(default_factory=dict)
    bandwidth_by_behavior: dict[str, dict[str, int]] = field(default_factory=dict)
    log: list[dict[str, Any]] = field(default_factory=list)

    # --- Task 8: Metrics summary ---

    def detection_summary(self) -> dict[str, dict[str, Any]]:
        summary: dict[str, dict[str, Any]] = {}
        all_behaviors = set(self.disconnects_by_behavior.keys()) | {"honest"}
        for behavior in all_behaviors:
            summary[behavior] = {
                "detected": self.disconnects_by_behavior.get(behavior, 0),
            }
        return summary

    def summary_table(self) -> str:
        lines = [
            f"{'Behavior':<20} {'Peers':<8} {'Detected':<12} {'H1 Rej':<10} {'H2 Evict':<10} "
            f"{'H4 Disc':<10} {'H5 Disc':<10} {'FP':<5}",
            "-" * 85,
        ]
        summary = self.detection_summary()
        all_behaviors = set(self.peer_counts.keys()) | set(summary.keys())
        for behavior in sorted(all_behaviors):
            total = self.peer_counts.get(behavior, 0)
            detected = self.disconnects_by_behavior.get(behavior, 0)
            det_str = f"{detected}/{total}" if total > 0 else "0"
            h1 = str(self.h1_rejections) if behavior == "spammer" else "-"
            h2 = str(self.h2_evictions) if behavior == "selective_signaler" else "-"
            h4 = str(self.h4_disconnects) if behavior in ("withholder", "spoofer") else "-"
            h5 = str(self.h5_disconnects) if behavior in ("free_rider", "non_announcer") else "-"
            fp = str(self.false_positives) if behavior == "honest" else "-"
            lines.append(
                f"{behavior:<20} {total:<8} {det_str:<12} "
                f"{h1:<10} {h2:<10} {h4:<10} {h5:<10} {fp:<5}"
            )
        lines.append(f"\nTotal accepted: {self.total_accepted}")
        lines.append(f"Total rejected: {self.total_rejected}")
        lines.append(f"Pool size at end: {self.pool_occupancy[-1][1] if self.pool_occupancy else 0}")
        if self.bandwidth_by_behavior:
            lines.append("\nBandwidth by behavior (bytes):")
            for beh, bw in sorted(self.bandwidth_by_behavior.items()):
                lines.append(f"  {beh:<20} in={bw['in']:>10,}  out={bw['out']:>10,}")
        return "\n".join(lines)


BEHAVIOR_CLASSES: dict[str, type[PeerBehavior]] = {
    "spammer": SpammerBehavior,
    "withholder": WithholderBehavior,
    "spoofer": SpooferBehavior,
    "free_rider": FreeRiderBehavior,
    "non_announcer": NonAnnouncerBehavior,
    "selective_signaler": SelectiveSignalerBehavior,
}


def _create_peers_and_events(
    scenario: Scenario, config: HeuristicConfig, node: Node,
    loop: EventLoop, rng: random.Random,
) -> dict[str, PeerBehavior]:
    """Wire up honest + attacker peers and schedule their initial events."""
    behaviors: dict[str, PeerBehavior] = {}
    gen_kwargs: dict[str, Any] = {
        "t_start": 0.0, "t_end": scenario.t_end,
        "tx_rate": scenario.tx_arrival_rate,
        "blob_base_fee": scenario.blob_base_fee,
        "includability_discount": config.includability_discount,
    }

    n_outbound = round(scenario.n_honest * (1 - scenario.inbound_ratio))
    for i in range(scenario.n_honest):
        pid = f"honest_{i}"
        behavior = HonestBehavior(pid, random.Random(rng.randint(0, 2**32)))
        behaviors[pid] = behavior
        is_inbound = i >= n_outbound
        node.add_peer(PeerState(pid, "honest", 0.0, is_inbound=is_inbound))
        for ev in behavior.generate_events(**gen_kwargs):
            loop.schedule(ev)

    for count, btype, bkwargs in scenario.attackers:
        cls = BEHAVIOR_CLASSES[btype]
        for i in range(count):
            pid = f"{btype}_{i}"
            behavior = cls(pid, random.Random(rng.randint(0, 2**32)), **bkwargs)
            behaviors[pid] = behavior
            node.add_peer(PeerState(pid, btype, 0.0, is_inbound=True))
            for ev in behavior.generate_events(**gen_kwargs):
                loop.schedule(ev)

    return behaviors


def _schedule_periodic_events(scenario: Scenario, loop: EventLoop) -> None:
    """Schedule block production and peer scoring ticks."""
    t = scenario.block_interval
    while t < scenario.t_end:
        loop.schedule(Event(t=t, kind="block"))
        t += scenario.block_interval

    t = 30.0
    while t < scenario.t_end:
        loop.schedule(Event(t=t, kind="score_peers"))
        t += 30.0


def _dispatch_event(
    event: Event, node: Node, behaviors: dict[str, PeerBehavior],
    loop: EventLoop,
) -> None:
    """Route a single event to the appropriate Node handler and reschedule follow-ups."""
    if event.kind == "announce":
        d = event.data
        follow_ups = node.handle_announce(
            peer_id=d["peer_id"], tx_hash=d["tx_hash"], sender=d["sender"],
            nonce=d["nonce"], fee=d["fee"], cell_mask=d["cell_mask"],
            is_provider=d["is_provider"], exclusive=d["exclusive"], t=event.t,
        )
        for fu in follow_ups:
            loop.schedule(fu)

    elif event.kind == "request_cells":
        d = event.data
        peer_id = d["peer_id"]
        behavior = behaviors.get(peer_id)
        if behavior is None:
            return
        result = behavior.respond_to_cell_request(
            d["columns"], node.custody_mask,
        )
        follow_ups = node.handle_cells_response(
            peer_id=peer_id, tx_hash=d["tx_hash"],
            served=result["served"], failed=result["failed"],
            custody_columns=d["custody_columns"], t=event.t,
        )
        for fu in follow_ups:
            loop.schedule(fu)

    elif event.kind == "saturation_check":
        node.handle_saturation_check(event.data["tx_hash"], event.t)

    elif event.kind == "inbound_request":
        node.handle_inbound_request(
            event.data["peer_id"], event.data.get("columns", []), event.t,
        )

    elif event.kind == "block":
        includable = [
            tx.tx_hash for tx in node.pool.iter_all()
            if tx.cell_mask == ALL_ONES
        ]
        selected = includable[:6]
        node.handle_block(selected, event.t)

    elif event.kind == "score_peers":
        node.score_peers(event.t)


def _compile_results(node: Node) -> SimulationResult:
    """Aggregate the node's event log into a SimulationResult."""
    result = SimulationResult(log=list(node.log))
    for entry in node.log:
        ev = entry["event"]
        if ev == "accept":
            result.total_accepted += 1
        elif ev == "reject_h1":
            result.total_rejected += 1
            result.h1_rejections += 1
        elif ev == "evict_h2_saturation":
            result.h2_evictions += 1
        elif ev == "disconnect":
            behavior = entry["behavior"]
            result.disconnects_by_behavior[behavior] = (
                result.disconnects_by_behavior.get(behavior, 0) + 1
            )
            if entry["reason"] == "h4_random_col_failure":
                result.h4_disconnects += 1
            elif entry["reason"] == "h5_request_ratio":
                result.h5_disconnects += 1
            if behavior == "honest":
                result.false_positives += 1

    for peer in node.peers.values():
        beh = peer.behavior
        result.peer_counts[beh] = result.peer_counts.get(beh, 0) + 1
        bw = result.bandwidth_by_behavior.setdefault(beh, {"in": 0, "out": 0})
        bw["in"] += peer.bytes_in
        bw["out"] += peer.bytes_out

    result.pool_occupancy.append((0.0, node.pool.count))
    return result


def run_simulation(
    config: HeuristicConfig, scenario: Scenario, seed: int = 42,
) -> SimulationResult:
    rng = random.Random(seed)
    node = Node(config, seed=rng.randint(0, 2**32))
    loop = EventLoop()

    behaviors = _create_peers_and_events(scenario, config, node, loop, rng)
    _schedule_periodic_events(scenario, loop)

    for event in loop.run():
        _dispatch_event(event, node, behaviors, loop)

    return _compile_results(node)
