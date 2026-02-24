# Single-node blobpool heuristic tuning simulator: implementation plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a standalone discrete-event simulator that models one honest EIP-8070 blobpool node connected to D=50 peers, with 6 attack profiles and 6 detection heuristics, to tune misbehavior detection thresholds.

**Architecture:** Single Python file (`heuristic_sim/blobpool_sim.py`) with a heapq event loop, dataclass-based state, peer behavior generators, and a heuristic engine that produces disconnect/evict decisions. A Jupyter notebook and CLI sweep script import it.

**Tech Stack:** Python 3.14, standard library only (heapq, dataclasses, random, hashlib, collections). matplotlib for plotting in notebook/sweep. No dependency on the existing `sparse_blobpool` or `single_node_sim` packages.

---

### Task 1: Project scaffolding and event loop

**Files:**
- Create: `heuristic_sim/__init__.py`
- Create: `heuristic_sim/blobpool_sim.py`
- Create: `tests/test_heuristic_sim.py`

**Step 1: Write the failing test**

```python
# tests/test_heuristic_sim.py
"""Tests for the single-node blobpool heuristic simulator."""

from heuristic_sim.blobpool_sim import Event, EventLoop


class TestEventLoop:
    def test_events_processed_in_timestamp_order(self):
        log = []
        loop = EventLoop()
        loop.schedule(Event(t=3.0, kind="c"))
        loop.schedule(Event(t=1.0, kind="a"))
        loop.schedule(Event(t=2.0, kind="b"))
        for event in loop.run():
            log.append(event.kind)
        assert log == ["a", "b", "c"]

    def test_empty_loop_produces_nothing(self):
        loop = EventLoop()
        assert list(loop.run()) == []
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_heuristic_sim.py -v`
Expected: FAIL with ImportError

**Step 3: Write minimal implementation**

```python
# heuristic_sim/__init__.py
"""Standalone single-node blobpool heuristic tuning simulator."""

# heuristic_sim/blobpool_sim.py
"""Single-node EIP-8070 blobpool heuristic simulator.

Models one honest node with D peers. Peers follow honest or attack behavior
profiles. The node runs 6 detection heuristics (H1-H6) and disconnects
misbehaving peers. Used to tune heuristic thresholds by measuring detection
rates, latency, and false positive rates across attack scenarios.
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass, field
from typing import Any, Iterator

# === Protocol constants (EIP-8070) ===

CELLS_PER_BLOB = 128
ALL_ONES = (1 << CELLS_PER_BLOB) - 1
RECONSTRUCTION_THRESHOLD = 64
DEFAULT_MESH_DEGREE = 50
MAX_TXS_PER_SENDER = 16


# === Event loop ===

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
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_heuristic_sim.py -v`
Expected: PASS (2 tests)

**Step 5: Commit**

```bash
git add heuristic_sim/ tests/test_heuristic_sim.py
git commit -m "feat(heuristic-sim): add event loop scaffold"
```

---

### Task 2: Heuristic config and protocol types

**Files:**
- Modify: `heuristic_sim/blobpool_sim.py`
- Modify: `tests/test_heuristic_sim.py`

**Step 1: Write the failing test**

```python
class TestHeuristicConfig:
    def test_defaults_match_mitigations_report(self):
        cfg = HeuristicConfig()
        assert cfg.includability_discount == 0.7
        assert cfg.saturation_timeout == 30.0
        assert cfg.min_independent_peers == 2
        assert cfg.c_extra_max == 4
        assert cfg.max_random_failure_rate == 0.1
        assert cfg.tracking_window == 100
        assert cfg.k_high == 2
        assert cfg.k_low == 4

    def test_cell_mask_helpers(self):
        mask = columns_to_mask([0, 3, 7])
        assert mask_to_columns(mask) == [0, 3, 7]
        assert popcount(mask) == 3
        assert popcount(ALL_ONES) == 128
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_heuristic_sim.py::TestHeuristicConfig -v`
Expected: FAIL with ImportError

**Step 3: Write minimal implementation**

Add to `blobpool_sim.py`:

```python
from enum import Enum, auto

# === Cell mask helpers ===

def columns_to_mask(columns: list[int]) -> int:
    mask = 0
    for c in columns:
        mask |= 1 << c
    return mask

def mask_to_columns(mask: int) -> list[int]:
    return [i for i in range(CELLS_PER_BLOB) if mask & (1 << i)]

def popcount(mask: int) -> int:
    return bin(mask).count("1")


# === Configuration ===

@dataclass(frozen=True)
class HeuristicConfig:
    # H1: Includability filter
    includability_discount: float = 0.7

    # H2: Saturation eviction
    saturation_timeout: float = 30.0
    min_independent_peers: int = 2

    # H3: Enhanced sampling noise
    c_extra_max: int = 4

    # H4: Random column failure tracking
    max_random_failure_rate: float = 0.1
    tracking_window: int = 100

    # H5: Contribution-based peer scoring
    k_high: int = 2
    k_low: int = 4
    score_threshold: float = 0.5

    # H6: Conservative inclusion
    conservative_inclusion: bool = True

    # General
    provider_probability: float = 0.15
    custody_columns: int = 8
    tx_ttl: float = 300.0
    pool_capacity: int = 15000
    blob_base_fee: float = 1.0


class Role(Enum):
    PROVIDER = auto()
    SAMPLER = auto()
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_heuristic_sim.py -v`
Expected: PASS (4 tests)

**Step 5: Commit**

```bash
git add heuristic_sim/blobpool_sim.py tests/test_heuristic_sim.py
git commit -m "feat(heuristic-sim): add config, constants, and cell mask helpers"
```

---

### Task 3: Peer state and tracking

**Files:**
- Modify: `heuristic_sim/blobpool_sim.py`
- Modify: `tests/test_heuristic_sim.py`

**Step 1: Write the failing test**

```python
class TestPeerState:
    def test_random_column_failure_rate(self):
        peer = PeerState(peer_id="p1", behavior="honest", connected_at=0.0)
        for _ in range(8):
            peer.record_random_column_result(success=True)
        for _ in range(2):
            peer.record_random_column_result(success=False)
        assert peer.random_column_failure_rate() == 0.2

    def test_failure_rate_sliding_window(self):
        peer = PeerState(peer_id="p1", behavior="honest", connected_at=0.0)
        # Fill window with failures
        for _ in range(100):
            peer.record_random_column_result(success=False)
        # Now add successes, pushing failures out
        for _ in range(100):
            peer.record_random_column_result(success=True)
        assert peer.random_column_failure_rate() == 0.0

    def test_provider_rate(self):
        peer = PeerState(peer_id="p1", behavior="honest", connected_at=0.0)
        peer.provider_announcements += 3
        peer.sampler_announcements += 7
        assert peer.provider_rate() == 0.3

    def test_provider_rate_no_announcements(self):
        peer = PeerState(peer_id="p1", behavior="honest", connected_at=0.0)
        assert peer.provider_rate() == 0.0
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_heuristic_sim.py::TestPeerState -v`
Expected: FAIL with ImportError

**Step 3: Write minimal implementation**

Add to `blobpool_sim.py`:

```python
from collections import deque

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
    _random_col_results: deque[bool] = field(
        default_factory=lambda: deque(maxlen=100)
    )
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
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_heuristic_sim.py -v`
Expected: PASS (8 tests)

**Step 5: Commit**

```bash
git add heuristic_sim/blobpool_sim.py tests/test_heuristic_sim.py
git commit -m "feat(heuristic-sim): add peer state with failure tracking"
```

---

### Task 4: Transaction state and blobpool store

**Files:**
- Modify: `heuristic_sim/blobpool_sim.py`
- Modify: `tests/test_heuristic_sim.py`

**Step 1: Write the failing test**

```python
class TestTxState:
    def test_add_and_lookup(self):
        pool = TxStore(capacity=100)
        tx = TxEntry(
            tx_hash="0xabc", sender="0x1", nonce=0,
            fee=10.0, first_seen=1.0, role=Role.SAMPLER,
        )
        pool.add(tx)
        assert pool.get("0xabc") is tx
        assert pool.count == 1

    def test_sender_limit(self):
        pool = TxStore(capacity=100, max_per_sender=2)
        for i in range(3):
            tx = TxEntry(
                tx_hash=f"0x{i}", sender="0x1", nonce=i,
                fee=10.0, first_seen=1.0, role=Role.SAMPLER,
            )
            pool.add(tx)
        assert pool.count == 2  # third rejected

    def test_capacity_evicts_lowest_fee(self):
        pool = TxStore(capacity=2)
        for i, fee in enumerate([5.0, 10.0, 15.0]):
            tx = TxEntry(
                tx_hash=f"0x{i}", sender=f"0x{i}", nonce=0,
                fee=fee, first_seen=1.0, role=Role.SAMPLER,
            )
            pool.add(tx)
        assert pool.count == 2
        assert pool.get("0x0") is None  # lowest fee evicted
        assert pool.get("0x1") is not None
        assert pool.get("0x2") is not None

    def test_record_announcer(self):
        pool = TxStore(capacity=100)
        tx = TxEntry(
            tx_hash="0xabc", sender="0x1", nonce=0,
            fee=10.0, first_seen=1.0, role=Role.SAMPLER,
        )
        pool.add(tx)
        tx.announcers.add("peer_1")
        tx.announcers.add("peer_2")
        assert len(tx.announcers) == 2
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_heuristic_sim.py::TestTxState -v`
Expected: FAIL with ImportError

**Step 3: Write minimal implementation**

Add to `blobpool_sim.py`:

```python
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
        """Add tx to store. Returns list of evicted tx hashes."""
        sender_txs = self._by_sender.get(tx.sender, [])
        if len(sender_txs) >= self._max_per_sender:
            return []  # rejected silently

        evicted: list[str] = []
        while len(self._txs) >= self._capacity:
            victim = self._evict_lowest_fee()
            if victim:
                evicted.append(victim)
            else:
                return []  # cannot make room

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
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_heuristic_sim.py -v`
Expected: PASS (12 tests)

**Step 5: Commit**

```bash
git add heuristic_sim/blobpool_sim.py tests/test_heuristic_sim.py
git commit -m "feat(heuristic-sim): add tx store with sender limits and fee eviction"
```

---

### Task 5: Peer behavior generators

**Files:**
- Modify: `heuristic_sim/blobpool_sim.py`
- Modify: `tests/test_heuristic_sim.py`

**Step 1: Write the failing test**

```python
import random

class TestPeerBehaviors:
    def test_honest_peer_generates_announcements(self):
        rng = random.Random(42)
        peer = HonestBehavior(peer_id="h1", rng=rng)
        events = peer.generate_events(t_start=0.0, t_end=10.0, tx_rate=1.0)
        assert len(events) > 0
        assert all(e.kind == "announce" for e in events)
        # Honest peers announce with correct cell_mask
        provider_count = sum(
            1 for e in events if e.data["cell_mask"] == ALL_ONES
        )
        # With p=0.15, expect roughly 15% providers over enough samples
        assert 0 <= provider_count <= len(events)

    def test_spammer_generates_below_fee(self):
        rng = random.Random(42)
        peer = SpammerBehavior(
            peer_id="s1", rng=rng, rate=5.0, below_includability=True
        )
        events = peer.generate_events(
            t_start=0.0, t_end=10.0, blob_base_fee=1.0,
            includability_discount=0.7,
        )
        assert len(events) > 0
        # All spam txs below includability threshold
        for e in events:
            assert e.data["fee"] < 1.0 * 0.7

    def test_withholder_fails_random_columns(self):
        rng = random.Random(42)
        peer = WithholderBehavior(
            peer_id="w1", rng=rng, random_fail_rate=1.0,
        )
        custody = columns_to_mask([0, 1, 2, 3, 4, 5, 6, 7])
        # Request custody + random columns
        requested = [0, 1, 2, 3, 50]  # 50 is random
        result = peer.respond_to_cell_request(requested, custody)
        # Custody columns succeed, random column fails
        assert 0 in result["served"]
        assert 50 in result["failed"]

    def test_selective_signaler_exclusive_announcements(self):
        rng = random.Random(42)
        peer = SelectiveSignalerBehavior(
            peer_id="ss1", rng=rng,
            n_senders=3, txs_per_sender=16,
        )
        events = peer.generate_events(t_start=0.0, t_end=60.0)
        # All announcements are exclusive (not seen by other peers)
        assert all(e.data.get("exclusive", False) for e in events)
        # Nonce chaining: 16 txs per sender
        senders = {}
        for e in events:
            s = e.data["sender"]
            senders.setdefault(s, []).append(e.data["nonce"])
        for s, nonces in senders.items():
            assert len(nonces) <= 16
            assert nonces == sorted(nonces)
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_heuristic_sim.py::TestPeerBehaviors -v`
Expected: FAIL with ImportError

**Step 3: Write minimal implementation**

Add to `blobpool_sim.py`:

```python
from hashlib import sha256

class PeerBehavior:
    """Base for all peer behavior generators."""

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
        self, peer_id: str, rng: random.Random,
        provider_prob: float = 0.15, custody_columns: int = 8,
    ) -> None:
        super().__init__(peer_id, rng)
        self.label = "honest"
        self.provider_prob = provider_prob
        self.custody_columns = custody_columns
        self._custody = self._pick_custody()

    def _pick_custody(self) -> list[int]:
        return self.rng.sample(range(CELLS_PER_BLOB), self.custody_columns)

    def generate_events(self, **kwargs: Any) -> list[Event]:
        t_start = kwargs.get("t_start", 0.0)
        t_end = kwargs.get("t_end", 300.0)
        tx_rate = kwargs.get("tx_rate", 1.0)
        blob_base_fee = kwargs.get("blob_base_fee", 1.0)

        events: list[Event] = []
        t = t_start + self.rng.expovariate(tx_rate)
        while t < t_end:
            sender = f"honest_sender_{self.rng.randint(0, 999)}"
            nonce = self.rng.randint(0, 15)
            is_provider = self.rng.random() < self.provider_prob
            cell_mask = ALL_ONES if is_provider else columns_to_mask(self._custody)
            fee = blob_base_fee * self.rng.uniform(0.8, 3.0)

            events.append(Event(
                t=t, kind="announce",
                data={
                    "peer_id": self.peer_id,
                    "tx_hash": self._make_tx_hash(sender, nonce),
                    "sender": sender, "nonce": nonce,
                    "fee": fee,
                    "cell_mask": cell_mask,
                    "is_provider": is_provider,
                    "exclusive": False,
                },
            ))
            t += self.rng.expovariate(tx_rate)
        return events

    def respond_to_cell_request(
        self, columns: list[int], requester_custody: int,
    ) -> dict[str, list[int]]:
        return {"served": columns, "failed": []}


class SpammerBehavior(PeerBehavior):
    def __init__(
        self, peer_id: str, rng: random.Random,
        rate: float = 10.0, below_includability: bool = True,
    ) -> None:
        super().__init__(peer_id, rng)
        self.label = "spammer"
        self.rate = rate
        self.below_includability = below_includability

    def generate_events(self, **kwargs: Any) -> list[Event]:
        t_start = kwargs.get("t_start", 0.0)
        t_end = kwargs.get("t_end", 300.0)
        blob_base_fee = kwargs.get("blob_base_fee", 1.0)
        includability_discount = kwargs.get("includability_discount", 0.7)

        events: list[Event] = []
        t = t_start + self.rng.expovariate(self.rate)
        sender_counter = 0
        while t < t_end:
            sender = f"spam_{self.peer_id}_{sender_counter}"
            sender_counter += 1
            if self.below_includability:
                fee = blob_base_fee * includability_discount * self.rng.uniform(0.1, 0.99)
            else:
                fee = blob_base_fee * self.rng.uniform(0.8, 1.5)

            events.append(Event(
                t=t, kind="announce",
                data={
                    "peer_id": self.peer_id,
                    "tx_hash": self._make_tx_hash(sender, 0),
                    "sender": sender, "nonce": 0,
                    "fee": fee,
                    "cell_mask": ALL_ONES,
                    "is_provider": True,
                    "exclusive": False,
                },
            ))
            t += self.rng.expovariate(self.rate)
        return events

    def respond_to_cell_request(
        self, columns: list[int], requester_custody: int,
    ) -> dict[str, list[int]]:
        return {"served": [], "failed": columns}


class WithholderBehavior(PeerBehavior):
    """T2.1: Serves custody columns but fails on random columns."""

    def __init__(
        self, peer_id: str, rng: random.Random,
        random_fail_rate: float = 1.0,
    ) -> None:
        super().__init__(peer_id, rng)
        self.label = "withholder"
        self.random_fail_rate = random_fail_rate

    def generate_events(self, **kwargs: Any) -> list[Event]:
        t_start = kwargs.get("t_start", 0.0)
        t_end = kwargs.get("t_end", 300.0)
        tx_rate = kwargs.get("tx_rate", 1.0)
        blob_base_fee = kwargs.get("blob_base_fee", 1.0)

        events: list[Event] = []
        t = t_start + self.rng.expovariate(tx_rate)
        while t < t_end:
            sender = f"legit_sender_{self.rng.randint(0, 999)}"
            nonce = self.rng.randint(0, 15)
            fee = blob_base_fee * self.rng.uniform(0.8, 3.0)
            events.append(Event(
                t=t, kind="announce",
                data={
                    "peer_id": self.peer_id,
                    "tx_hash": self._make_tx_hash(sender, nonce),
                    "sender": sender, "nonce": nonce,
                    "fee": fee,
                    "cell_mask": ALL_ONES,
                    "is_provider": True,
                    "exclusive": False,
                },
            ))
            t += self.rng.expovariate(tx_rate)
        return events

    def respond_to_cell_request(
        self, columns: list[int], requester_custody: int,
    ) -> dict[str, list[int]]:
        custody_cols = mask_to_columns(requester_custody)
        served = []
        failed = []
        for col in columns:
            if col in custody_cols:
                served.append(col)
            elif self.rng.random() < self.random_fail_rate:
                failed.append(col)
            else:
                served.append(col)
        return {"served": served, "failed": failed}


class SpooferBehavior(PeerBehavior):
    """T2.2: Claims provider, fails on all cell requests."""

    def __init__(self, peer_id: str, rng: random.Random) -> None:
        super().__init__(peer_id, rng)
        self.label = "spoofer"

    def generate_events(self, **kwargs: Any) -> list[Event]:
        t_start = kwargs.get("t_start", 0.0)
        t_end = kwargs.get("t_end", 300.0)
        tx_rate = kwargs.get("tx_rate", 1.0)
        blob_base_fee = kwargs.get("blob_base_fee", 1.0)

        events: list[Event] = []
        t = t_start + self.rng.expovariate(tx_rate)
        while t < t_end:
            sender = f"legit_sender_{self.rng.randint(0, 999)}"
            nonce = self.rng.randint(0, 15)
            fee = blob_base_fee * self.rng.uniform(0.8, 3.0)
            events.append(Event(
                t=t, kind="announce",
                data={
                    "peer_id": self.peer_id,
                    "tx_hash": self._make_tx_hash(sender, nonce),
                    "sender": sender, "nonce": nonce,
                    "fee": fee,
                    "cell_mask": ALL_ONES,
                    "is_provider": True,
                    "exclusive": False,
                },
            ))
            t += self.rng.expovariate(tx_rate)
        return events

    def respond_to_cell_request(
        self, columns: list[int], requester_custody: int,
    ) -> dict[str, list[int]]:
        return {"served": [], "failed": columns}


class FreeRiderBehavior(PeerBehavior):
    """T3.1: Always sampler, never provider."""

    def __init__(
        self, peer_id: str, rng: random.Random,
        custody_columns: int = 8,
    ) -> None:
        super().__init__(peer_id, rng)
        self.label = "free_rider"
        self._custody = self.rng.sample(range(CELLS_PER_BLOB), custody_columns)

    def generate_events(self, **kwargs: Any) -> list[Event]:
        t_start = kwargs.get("t_start", 0.0)
        t_end = kwargs.get("t_end", 300.0)
        tx_rate = kwargs.get("tx_rate", 1.0)
        blob_base_fee = kwargs.get("blob_base_fee", 1.0)

        events: list[Event] = []
        t = t_start + self.rng.expovariate(tx_rate)
        while t < t_end:
            sender = f"legit_sender_{self.rng.randint(0, 999)}"
            nonce = self.rng.randint(0, 15)
            fee = blob_base_fee * self.rng.uniform(0.8, 3.0)
            events.append(Event(
                t=t, kind="announce",
                data={
                    "peer_id": self.peer_id,
                    "tx_hash": self._make_tx_hash(sender, nonce),
                    "sender": sender, "nonce": nonce,
                    "fee": fee,
                    "cell_mask": columns_to_mask(self._custody),
                    "is_provider": False,  # always sampler
                    "exclusive": False,
                },
            ))
            t += self.rng.expovariate(tx_rate)
        return events

    def respond_to_cell_request(
        self, columns: list[int], requester_custody: int,
    ) -> dict[str, list[int]]:
        served = [c for c in columns if c in self._custody]
        failed = [c for c in columns if c not in self._custody]
        return {"served": served, "failed": failed}


class NonAnnouncerBehavior(PeerBehavior):
    """T3.3: Requests cells from us but never announces anything."""

    def __init__(self, peer_id: str, rng: random.Random) -> None:
        super().__init__(peer_id, rng)
        self.label = "non_announcer"

    def generate_events(self, **kwargs: Any) -> list[Event]:
        # Generates no announcements; only cell requests (modeled as
        # inbound request events on our node)
        t_start = kwargs.get("t_start", 0.0)
        t_end = kwargs.get("t_end", 300.0)
        request_rate = kwargs.get("tx_rate", 0.5)

        events: list[Event] = []
        t = t_start + self.rng.expovariate(request_rate)
        while t < t_end:
            events.append(Event(
                t=t, kind="inbound_request",
                data={"peer_id": self.peer_id},
            ))
            t += self.rng.expovariate(request_rate)
        return events

    def respond_to_cell_request(
        self, columns: list[int], requester_custody: int,
    ) -> dict[str, list[int]]:
        return {"served": [], "failed": columns}


class SelectiveSignalerBehavior(PeerBehavior):
    """T4.2: Announces txs exclusively to victim, nonce-chains them."""

    def __init__(
        self, peer_id: str, rng: random.Random,
        n_senders: int = 10, txs_per_sender: int = 16,
    ) -> None:
        super().__init__(peer_id, rng)
        self.label = "selective_signaler"
        self.n_senders = n_senders
        self.txs_per_sender = txs_per_sender

    def generate_events(self, **kwargs: Any) -> list[Event]:
        t_start = kwargs.get("t_start", 0.0)
        t_end = kwargs.get("t_end", 300.0)

        events: list[Event] = []
        injection_interval = (t_end - t_start) / (
            self.n_senders * self.txs_per_sender
        )
        t = t_start + injection_interval

        for s in range(self.n_senders):
            sender = f"attack_{self.peer_id}_sender_{s}"
            for nonce in range(self.txs_per_sender):
                if t >= t_end:
                    break
                events.append(Event(
                    t=t, kind="announce",
                    data={
                        "peer_id": self.peer_id,
                        "tx_hash": self._make_tx_hash(sender, nonce),
                        "sender": sender, "nonce": nonce,
                        "fee": 2.0,  # above includability to bypass H1
                        "cell_mask": ALL_ONES,
                        "is_provider": True,
                        "exclusive": True,
                    },
                ))
                t += injection_interval
        return events

    def respond_to_cell_request(
        self, columns: list[int], requester_custody: int,
    ) -> dict[str, list[int]]:
        return {"served": columns, "failed": []}
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_heuristic_sim.py -v`
Expected: PASS (16 tests)

**Step 5: Commit**

```bash
git add heuristic_sim/blobpool_sim.py tests/test_heuristic_sim.py
git commit -m "feat(heuristic-sim): add 7 peer behavior generators"
```

---

### Task 6: Node logic (announcement handling + cell request/response cycle)

**Files:**
- Modify: `heuristic_sim/blobpool_sim.py`
- Modify: `tests/test_heuristic_sim.py`

**Step 1: Write the failing test**

```python
class TestNodeAnnounce:
    def test_honest_announcement_accepted(self):
        cfg = HeuristicConfig()
        node = Node(cfg, seed=42)
        node.add_peer(PeerState("p1", "honest", 0.0))
        events = node.handle_announce(
            peer_id="p1", tx_hash="0xabc", sender="s1", nonce=0,
            fee=1.0, cell_mask=ALL_ONES, is_provider=True,
            exclusive=False, t=1.0,
        )
        assert node.pool.contains("0xabc")
        # Should schedule a saturation check
        sat_events = [e for e in events if e.kind == "saturation_check"]
        assert len(sat_events) == 1
        assert sat_events[0].t == 1.0 + cfg.saturation_timeout

    def test_h1_rejects_below_includability(self):
        cfg = HeuristicConfig(includability_discount=0.7, blob_base_fee=1.0)
        node = Node(cfg, seed=42)
        node.add_peer(PeerState("p1", "honest", 0.0))
        events = node.handle_announce(
            peer_id="p1", tx_hash="0xabc", sender="s1", nonce=0,
            fee=0.5, cell_mask=ALL_ONES, is_provider=True,
            exclusive=False, t=1.0,
        )
        assert not node.pool.contains("0xabc")

    def test_duplicate_announce_records_additional_peer(self):
        cfg = HeuristicConfig()
        node = Node(cfg, seed=42)
        node.add_peer(PeerState("p1", "honest", 0.0))
        node.add_peer(PeerState("p2", "honest", 0.0))
        node.handle_announce(
            peer_id="p1", tx_hash="0xabc", sender="s1", nonce=0,
            fee=1.0, cell_mask=ALL_ONES, is_provider=True,
            exclusive=False, t=1.0,
        )
        node.handle_announce(
            peer_id="p2", tx_hash="0xabc", sender="s1", nonce=0,
            fee=1.0, cell_mask=ALL_ONES, is_provider=True,
            exclusive=False, t=2.0,
        )
        tx = node.pool.get("0xabc")
        assert tx is not None
        assert tx.announcers == {"p1", "p2"}


class TestNodeCellRequest:
    def test_cell_request_includes_c_extra(self):
        cfg = HeuristicConfig(c_extra_max=4, custody_columns=8)
        node = Node(cfg, seed=42)
        columns = node.compute_request_columns(is_provider=False)
        custody = mask_to_columns(node.custody_mask)
        # Should include custody columns plus 1-4 extra
        assert len(columns) > len(custody)
        assert len(columns) <= len(custody) + cfg.c_extra_max
        # All custody columns present
        for c in custody:
            assert c in columns

    def test_provider_requests_all_columns(self):
        cfg = HeuristicConfig()
        node = Node(cfg, seed=42)
        columns = node.compute_request_columns(is_provider=True)
        assert len(columns) == CELLS_PER_BLOB
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_heuristic_sim.py::TestNodeAnnounce -v`
Expected: FAIL with ImportError

**Step 3: Write minimal implementation**

Add to `blobpool_sim.py`:

```python
class Node:
    """The single honest node being simulated."""

    def __init__(self, config: HeuristicConfig, seed: int = 42) -> None:
        self.config = config
        self.rng = random.Random(seed)
        self.pool = TxStore(
            capacity=config.pool_capacity,
            max_per_sender=MAX_TXS_PER_SENDER,
        )
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
                "t": t, "event": "disconnect",
                "peer_id": peer_id, "reason": reason,
                "behavior": peer.behavior,
            })

    def _determine_role(self, tx_hash: str) -> Role:
        h = sha256(f"role:{tx_hash}:{self.rng.random()}".encode()).digest()
        p = int.from_bytes(h[:8], "big") / (2**64)
        if p < self.config.provider_probability:
            return Role.PROVIDER
        return Role.SAMPLER

    def compute_request_columns(self, is_provider: bool) -> list[int]:
        if is_provider:
            return list(range(CELLS_PER_BLOB))
        custody = mask_to_columns(self.custody_mask)
        non_custody = [c for c in range(CELLS_PER_BLOB) if c not in custody]
        c_extra = self.rng.randint(1, self.config.c_extra_max)
        extra = self.rng.sample(non_custody, min(c_extra, len(non_custody)))
        return custody + extra

    def handle_announce(
        self, peer_id: str, tx_hash: str, sender: str, nonce: int,
        fee: float, cell_mask: int, is_provider: bool,
        exclusive: bool, t: float,
    ) -> list[Event]:
        follow_up: list[Event] = []
        peer = self.peers.get(peer_id)
        if peer is None or peer.disconnected:
            return follow_up

        # Track provider/sampler ratio for this peer
        if is_provider:
            peer.provider_announcements += 1
        else:
            peer.sampler_announcements += 1
        peer.announcements_made += 1

        # H1: Includability filter
        if fee < self.config.blob_base_fee * self.config.includability_discount:
            self.log.append({
                "t": t, "event": "reject_h1",
                "tx_hash": tx_hash, "peer_id": peer_id, "fee": fee,
            })
            return follow_up

        existing = self.pool.get(tx_hash)
        if existing is not None:
            existing.announcers.add(peer_id)
            return follow_up

        role = self._determine_role(tx_hash)
        tx = TxEntry(
            tx_hash=tx_hash, sender=sender, nonce=nonce,
            fee=fee, first_seen=t, role=role,
            cell_mask=0, announcers={peer_id},
        )
        evicted = self.pool.add(tx)
        if not self.pool.contains(tx_hash):
            return follow_up  # rejected by sender limit or capacity

        for ev_hash in evicted:
            self.log.append({
                "t": t, "event": "evict_capacity", "tx_hash": ev_hash,
            })

        # Schedule saturation check (H2)
        follow_up.append(Event(
            t=t + self.config.saturation_timeout,
            kind="saturation_check",
            data={"tx_hash": tx_hash},
        ))

        # Schedule cell request
        request_cols = self.compute_request_columns(
            is_provider=(role == Role.PROVIDER),
        )
        follow_up.append(Event(
            t=t + 0.1,  # small delay for request
            kind="request_cells",
            data={
                "peer_id": peer_id, "tx_hash": tx_hash,
                "columns": request_cols,
                "custody_columns": mask_to_columns(self.custody_mask),
            },
        ))

        self.log.append({
            "t": t, "event": "accept",
            "tx_hash": tx_hash, "role": role.name,
            "peer_id": peer_id,
        })
        return follow_up

    def handle_cells_response(
        self, peer_id: str, tx_hash: str,
        served: list[int], failed: list[int],
        custody_columns: list[int], t: float,
    ) -> list[Event]:
        """Process cell response, track random column failures (H4)."""
        follow_up: list[Event] = []
        peer = self.peers.get(peer_id)
        if peer is None or peer.disconnected:
            return follow_up

        # Classify columns as custody vs random
        for col in served:
            if col not in custody_columns:
                peer.record_random_column_result(success=True)
            peer.cells_served += 1

        for col in failed:
            if col not in custody_columns:
                peer.record_random_column_result(success=False)

        # H4: Check random column failure rate
        if (
            len(peer._random_col_results) >= 10
            and peer.random_column_failure_rate()
                > self.config.max_random_failure_rate
        ):
            self.disconnect_peer(peer_id, "h4_random_col_failure", t)
            return follow_up

        # Update tx cell_mask
        tx = self.pool.get(tx_hash)
        if tx is not None:
            tx.cell_mask |= columns_to_mask(served)

        return follow_up

    def handle_saturation_check(
        self, tx_hash: str, t: float,
    ) -> list[Event]:
        """H2: Evict tx if not corroborated by enough independent peers."""
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
                "tx_hash": tx_hash,
                "announcers": len(independent),
            })
        return []

    def handle_inbound_request(
        self, peer_id: str, t: float,
    ) -> list[Event]:
        """Track inbound requests from peers (for non-announcer detection)."""
        peer = self.peers.get(peer_id)
        if peer is None or peer.disconnected:
            return []
        # Peer requests from us but never announces
        # Detection happens in periodic scoring
        return []

    def handle_block(
        self, included_txs: list[str], t: float,
    ) -> list[Event]:
        """Remove included txs. Credit contributing peers (H5)."""
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
        """H5: Compute contribution-based scores, disconnect low scorers."""
        follow_up: list[Event] = []
        for peer in self.peers.values():
            if peer.disconnected:
                continue

            duration = t - peer.connected_at
            duration_score = min(duration / 300.0, 1.0)
            contribution_score = min(peer.included_contributions / 10.0, 1.0)
            failure_penalty = peer.random_column_failure_rate()
            announcer_penalty = (
                0.0 if peer.announcements_made > 0
                else 0.3 if duration > 60.0 else 0.0
            )

            peer.score = (
                0.3 * duration_score
                + 0.4 * contribution_score
                - 0.2 * failure_penalty
                - 0.1 * announcer_penalty
            )

        return follow_up
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_heuristic_sim.py -v`
Expected: PASS (21 tests)

**Step 5: Commit**

```bash
git add heuristic_sim/blobpool_sim.py tests/test_heuristic_sim.py
git commit -m "feat(heuristic-sim): add node logic with H1-H5 heuristics"
```

---

### Task 7: Simulation runner and scenario config

**Files:**
- Modify: `heuristic_sim/blobpool_sim.py`
- Modify: `tests/test_heuristic_sim.py`

**Step 1: Write the failing test**

```python
class TestSimulation:
    def test_honest_only_no_disconnects(self):
        scenario = Scenario(
            n_honest=20,
            attackers=[],
            tx_arrival_rate=1.0,
            t_end=60.0,
        )
        result = run_simulation(HeuristicConfig(), scenario, seed=42)
        assert result.disconnects_by_behavior.get("honest", 0) == 0
        assert result.total_accepted > 0

    def test_spammer_below_fee_all_rejected(self):
        scenario = Scenario(
            n_honest=10,
            attackers=[(5, "spammer", {"rate": 5.0, "below_includability": True})],
            tx_arrival_rate=0.5,
            t_end=30.0,
        )
        result = run_simulation(HeuristicConfig(), scenario, seed=42)
        # All spam below includability should be rejected by H1
        assert result.h1_rejections > 0

    def test_withholder_detected_by_h4(self):
        scenario = Scenario(
            n_honest=10,
            attackers=[(3, "withholder", {"random_fail_rate": 1.0})],
            tx_arrival_rate=1.0,
            t_end=120.0,
        )
        result = run_simulation(HeuristicConfig(), scenario, seed=42)
        # Withholders should be disconnected
        assert result.disconnects_by_behavior.get("withholder", 0) > 0

    def test_selective_signaler_evicted_by_h2(self):
        scenario = Scenario(
            n_honest=10,
            attackers=[
                (3, "selective_signaler", {"n_senders": 5, "txs_per_sender": 16}),
            ],
            tx_arrival_rate=0.5,
            t_end=120.0,
        )
        result = run_simulation(HeuristicConfig(), scenario, seed=42)
        # Selective signaler txs should be evicted by saturation check
        assert result.h2_evictions > 0
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_heuristic_sim.py::TestSimulation -v`
Expected: FAIL with ImportError

**Step 3: Write minimal implementation**

Add to `blobpool_sim.py`:

```python
@dataclass
class Scenario:
    n_honest: int = 40
    attackers: list[tuple[int, str, dict[str, Any]]] = field(default_factory=list)
    tx_arrival_rate: float = 2.0
    t_end: float = 300.0
    blob_base_fee: float = 1.0
    block_interval: float = 12.0


@dataclass
class SimulationResult:
    total_accepted: int = 0
    total_rejected: int = 0
    h1_rejections: int = 0
    h2_evictions: int = 0
    h4_disconnects: int = 0
    disconnects_by_behavior: dict[str, int] = field(default_factory=dict)
    false_positives: int = 0
    detection_latencies: dict[str, list[float]] = field(default_factory=dict)
    peer_scores: dict[str, list[tuple[float, float]]] = field(default_factory=dict)
    pool_occupancy: list[tuple[float, int]] = field(default_factory=list)
    log: list[dict[str, Any]] = field(default_factory=list)


BEHAVIOR_CLASSES: dict[str, type[PeerBehavior]] = {
    "spammer": SpammerBehavior,
    "withholder": WithholderBehavior,
    "spoofer": SpooferBehavior,
    "free_rider": FreeRiderBehavior,
    "non_announcer": NonAnnouncerBehavior,
    "selective_signaler": SelectiveSignalerBehavior,
}


def run_simulation(
    config: HeuristicConfig,
    scenario: Scenario,
    seed: int = 42,
) -> SimulationResult:
    rng = random.Random(seed)
    node = Node(config, seed=seed)
    loop = EventLoop()
    behaviors: dict[str, PeerBehavior] = {}

    # Create honest peers
    for i in range(scenario.n_honest):
        pid = f"honest_{i}"
        peer = PeerState(pid, "honest", connected_at=0.0)
        node.add_peer(peer)
        behavior = HonestBehavior(pid, random.Random(rng.randint(0, 2**32)))
        behaviors[pid] = behavior
        for event in behavior.generate_events(
            t_start=0.0, t_end=scenario.t_end,
            tx_rate=scenario.tx_arrival_rate / scenario.n_honest,
            blob_base_fee=scenario.blob_base_fee,
        ):
            loop.schedule(event)

    # Create attacker peers
    for count, behavior_name, kwargs in scenario.attackers:
        for i in range(count):
            pid = f"{behavior_name}_{i}"
            peer = PeerState(pid, behavior_name, connected_at=0.0)
            node.add_peer(peer)
            cls = BEHAVIOR_CLASSES[behavior_name]
            behavior = cls(pid, random.Random(rng.randint(0, 2**32)), **kwargs)
            behaviors[pid] = behavior
            gen_kwargs: dict[str, Any] = {
                "t_start": 0.0, "t_end": scenario.t_end,
                "blob_base_fee": scenario.blob_base_fee,
            }
            if behavior_name == "spammer":
                gen_kwargs["includability_discount"] = config.includability_discount
            elif behavior_name not in ("selective_signaler", "non_announcer"):
                gen_kwargs["tx_rate"] = scenario.tx_arrival_rate / scenario.n_honest
            for event in behavior.generate_events(**gen_kwargs):
                loop.schedule(event)

    # Schedule periodic block production
    t = scenario.block_interval
    while t < scenario.t_end:
        loop.schedule(Event(t=t, kind="block", data={}))
        t += scenario.block_interval

    # Schedule periodic peer scoring
    t = 30.0
    while t < scenario.t_end:
        loop.schedule(Event(t=t, kind="score_peers", data={}))
        t += 30.0

    # Run event loop
    for event in loop.run():
        match event.kind:
            case "announce":
                d = event.data
                follow_ups = node.handle_announce(
                    peer_id=d["peer_id"], tx_hash=d["tx_hash"],
                    sender=d["sender"], nonce=d["nonce"],
                    fee=d["fee"], cell_mask=d["cell_mask"],
                    is_provider=d["is_provider"],
                    exclusive=d.get("exclusive", False),
                    t=event.t,
                )
                for fu in follow_ups:
                    loop.schedule(fu)

            case "request_cells":
                d = event.data
                pid = d["peer_id"]
                beh = behaviors.get(pid)
                if beh and not node.peers[pid].disconnected:
                    result = beh.respond_to_cell_request(
                        d["columns"], node.custody_mask,
                    )
                    follow_ups = node.handle_cells_response(
                        peer_id=pid, tx_hash=d["tx_hash"],
                        served=result["served"], failed=result["failed"],
                        custody_columns=d["custody_columns"],
                        t=event.t,
                    )
                    for fu in follow_ups:
                        loop.schedule(fu)

            case "saturation_check":
                node.handle_saturation_check(d["tx_hash"], event.t)

            case "inbound_request":
                node.handle_inbound_request(event.data["peer_id"], event.t)

            case "block":
                # Simulate block including some pool txs
                includable = [
                    tx.tx_hash for tx in node.pool.iter_all()
                    if (not config.conservative_inclusion
                        or tx.cell_mask == ALL_ONES)
                ][:6]  # max 6 blobs per block
                if includable:
                    node.handle_block(includable, event.t)

            case "score_peers":
                node.score_peers(event.t)

    # Compile results
    result = SimulationResult(log=node.log)
    for entry in node.log:
        match entry["event"]:
            case "accept":
                result.total_accepted += 1
            case "reject_h1":
                result.h1_rejections += 1
                result.total_rejected += 1
            case "evict_h2_saturation":
                result.h2_evictions += 1
            case "disconnect":
                behavior = entry["behavior"]
                result.disconnects_by_behavior[behavior] = (
                    result.disconnects_by_behavior.get(behavior, 0) + 1
                )
                if behavior == "honest":
                    result.false_positives += 1
                if "h4" in entry["reason"]:
                    result.h4_disconnects += 1

    result.pool_occupancy = [
        (entry["t"], node.pool.count)
        for entry in node.log
        if entry["event"] in ("accept", "evict_h2_saturation", "evict_capacity")
    ]

    return result
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_heuristic_sim.py -v`
Expected: PASS (25 tests)

**Step 5: Commit**

```bash
git add heuristic_sim/blobpool_sim.py tests/test_heuristic_sim.py
git commit -m "feat(heuristic-sim): add simulation runner with scenario config"
```

---

### Task 8: Metrics summary and result analysis

**Files:**
- Modify: `heuristic_sim/blobpool_sim.py`
- Modify: `tests/test_heuristic_sim.py`

**Step 1: Write the failing test**

```python
class TestMetrics:
    def test_detection_rate(self):
        scenario = Scenario(
            n_honest=10,
            attackers=[
                (3, "withholder", {"random_fail_rate": 1.0}),
                (2, "spoofer", {}),
            ],
            tx_arrival_rate=2.0,
            t_end=120.0,
        )
        result = run_simulation(HeuristicConfig(), scenario, seed=42)
        summary = result.detection_summary()
        # Withholders and spoofers should have >0 detection rate
        assert summary["withholder"]["detected"] > 0
        assert summary["spoofer"]["detected"] > 0
        assert summary["honest"]["detected"] == 0

    def test_summary_table(self):
        scenario = Scenario(
            n_honest=10,
            attackers=[(2, "spammer", {"rate": 5.0, "below_includability": True})],
            tx_arrival_rate=1.0,
            t_end=30.0,
        )
        result = run_simulation(HeuristicConfig(), scenario, seed=42)
        table = result.summary_table()
        assert "Behavior" in table
        assert "honest" in table
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_heuristic_sim.py::TestMetrics -v`
Expected: FAIL with AttributeError

**Step 3: Write minimal implementation**

Add methods to `SimulationResult`:

```python
# Add to SimulationResult class:

    def detection_summary(self) -> dict[str, dict[str, Any]]:
        """Per-behavior detection rates."""
        # Count total peers and detected (disconnected) peers per behavior
        peer_counts: dict[str, int] = {}
        for entry in self.log:
            if entry["event"] == "disconnect":
                behavior = entry["behavior"]
                self.disconnects_by_behavior.setdefault(behavior, 0)

        # Rebuild from log: count accepts per behavior via peer tracking
        # Use disconnects_by_behavior which was already computed
        summary: dict[str, dict[str, Any]] = {}
        all_behaviors = set(self.disconnects_by_behavior.keys()) | {"honest"}
        for behavior in all_behaviors:
            summary[behavior] = {
                "detected": self.disconnects_by_behavior.get(behavior, 0),
            }
        return summary

    def summary_table(self) -> str:
        """Human-readable summary table."""
        lines = [
            f"{'Behavior':<20} {'Detected':<10} {'H1 Rej':<10} "
            f"{'H2 Evict':<10} {'H4 Disc':<10} {'FP':<5}",
            "-" * 65,
        ]
        summary = self.detection_summary()
        for behavior, stats in sorted(summary.items()):
            lines.append(
                f"{behavior:<20} {stats['detected']:<10} "
                f"{self.h1_rejections if behavior == 'spammer' else '-':<10} "
                f"{self.h2_evictions if behavior == 'selective_signaler' else '-':<10} "
                f"{self.h4_disconnects if behavior in ('withholder', 'spoofer') else '-':<10} "
                f"{self.false_positives if behavior == 'honest' else '-':<5}"
            )
        lines.append(f"\nTotal accepted: {self.total_accepted}")
        lines.append(f"Total rejected: {self.total_rejected}")
        lines.append(f"Pool size at end: {self.pool_occupancy[-1][1] if self.pool_occupancy else 0}")
        return "\n".join(lines)
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_heuristic_sim.py -v`
Expected: PASS (27 tests)

**Step 5: Commit**

```bash
git add heuristic_sim/blobpool_sim.py tests/test_heuristic_sim.py
git commit -m "feat(heuristic-sim): add detection summary and result analysis"
```

---

### Task 9: CLI parameter sweep script

**Files:**
- Create: `heuristic_sim/sweep.py`

**Step 1: Write the script**

```python
#!/usr/bin/env python3
"""Parameter sweep for blobpool heuristic tuning.

Usage:
    uv run python -m heuristic_sim.sweep
    uv run python -m heuristic_sim.sweep --param saturation_timeout --range 10,20,30,45,60
"""

from __future__ import annotations

import argparse
import itertools
import sys
from dataclasses import asdict

from heuristic_sim.blobpool_sim import (
    HeuristicConfig,
    Scenario,
    SimulationResult,
    run_simulation,
)

DEFAULT_SCENARIO = Scenario(
    n_honest=30,
    attackers=[
        (5, "withholder", {"random_fail_rate": 0.5}),
        (3, "selective_signaler", {"n_senders": 5, "txs_per_sender": 16}),
        (3, "spammer", {"rate": 5.0, "below_includability": True}),
        (2, "spoofer", {}),
        (2, "free_rider", {}),
        (2, "non_announcer", {}),
    ],
    tx_arrival_rate=2.0,
    t_end=120.0,
)

SWEEP_RANGES: dict[str, list[float]] = {
    "includability_discount": [0.5, 0.6, 0.7, 0.8, 0.9],
    "saturation_timeout": [10.0, 20.0, 30.0, 45.0, 60.0],
    "c_extra_max": [1, 2, 3, 4, 6],
    "max_random_failure_rate": [0.05, 0.1, 0.15, 0.2, 0.3],
    "k_high": [1, 2, 3],
    "k_low": [2, 3, 4, 6],
}


def run_sweep(
    param: str, values: list[float], scenario: Scenario, seed: int = 42,
) -> list[tuple[float, SimulationResult]]:
    results: list[tuple[float, SimulationResult]] = []
    for val in values:
        overrides = {param: type(getattr(HeuristicConfig(), param))(val)}
        config = HeuristicConfig(**overrides)
        result = run_simulation(config, scenario, seed=seed)
        results.append((val, result))
    return results


def print_sweep_table(param: str, results: list[tuple[float, SimulationResult]]) -> None:
    print(f"\n{'='*80}")
    print(f"Sweep: {param}")
    print(f"{'='*80}")
    header = (
        f"{'Value':<12} {'Accepted':<10} {'H1 Rej':<8} {'H2 Evict':<10} "
        f"{'H4 Disc':<8} {'FP':<5} {'Detect%':<8}"
    )
    print(header)
    print("-" * len(header))
    for val, result in results:
        total_attackers = sum(result.disconnects_by_behavior.values()) - result.false_positives
        total_attack_peers = sum(
            1 for b, c in result.disconnects_by_behavior.items() if b != "honest"
        )
        detect_pct = (
            f"{100 * total_attackers / max(total_attack_peers, 1):.0f}%"
            if total_attack_peers > 0 else "N/A"
        )
        print(
            f"{val:<12} {result.total_accepted:<10} {result.h1_rejections:<8} "
            f"{result.h2_evictions:<10} {result.h4_disconnects:<8} "
            f"{result.false_positives:<5} {detect_pct:<8}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Blobpool heuristic parameter sweep")
    parser.add_argument(
        "--param", type=str, default=None,
        help="Parameter to sweep (default: sweep all)",
    )
    parser.add_argument(
        "--range", type=str, default=None,
        help="Comma-separated values to sweep (default: use built-in ranges)",
    )
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    if args.param:
        values = (
            [float(v) for v in args.range.split(",")]
            if args.range
            else SWEEP_RANGES.get(args.param, [])
        )
        if not values:
            print(f"No range defined for {args.param}", file=sys.stderr)
            sys.exit(1)
        results = run_sweep(args.param, values, DEFAULT_SCENARIO, args.seed)
        print_sweep_table(args.param, results)
    else:
        for param, values in SWEEP_RANGES.items():
            results = run_sweep(param, values, DEFAULT_SCENARIO, args.seed)
            print_sweep_table(param, results)


if __name__ == "__main__":
    main()
```

**Step 2: Run to verify it works**

Run: `uv run python -m heuristic_sim.sweep --param saturation_timeout`
Expected: Table output showing detection metrics across saturation_timeout values

**Step 3: Commit**

```bash
git add heuristic_sim/sweep.py
git commit -m "feat(heuristic-sim): add CLI parameter sweep script"
```

---

### Task 10: Jupyter notebook for interactive exploration

**Files:**
- Create: `heuristic_sim/notebook.ipynb`

**Step 1: Create the notebook**

Cell 1 (markdown):
```markdown
# Blobpool heuristic tuning simulator

Interactive exploration of EIP-8070 detection heuristics (H1-H6) against 6 attack profiles.
```

Cell 2 (code):
```python
from heuristic_sim.blobpool_sim import (
    HeuristicConfig, Scenario, run_simulation, SimulationResult,
)
import matplotlib.pyplot as plt

# Default config with mitigations report values
cfg = HeuristicConfig()
print(f"Config: {cfg}")
```

Cell 3 (code - scenario setup):
```python
scenario = Scenario(
    n_honest=30,
    attackers=[
        (5, "withholder", {"random_fail_rate": 0.5}),
        (3, "selective_signaler", {"n_senders": 5, "txs_per_sender": 16}),
        (3, "spammer", {"rate": 5.0, "below_includability": True}),
        (2, "spoofer", {}),
        (2, "free_rider", {}),
        (2, "non_announcer", {}),
    ],
    tx_arrival_rate=2.0,
    t_end=300.0,
)
result = run_simulation(cfg, scenario)
print(result.summary_table())
```

Cell 4 (code - detection timeline plot):
```python
fig, axes = plt.subplots(2, 2, figsize=(14, 10))

# Pool occupancy over time
if result.pool_occupancy:
    ts, counts = zip(*result.pool_occupancy)
    axes[0, 0].plot(ts, counts)
    axes[0, 0].set_title("Pool occupancy")
    axes[0, 0].set_xlabel("Time (s)")
    axes[0, 0].set_ylabel("Tx count")

# Disconnects over time
disconnect_times: dict[str, list[float]] = {}
for entry in result.log:
    if entry["event"] == "disconnect":
        b = entry["behavior"]
        disconnect_times.setdefault(b, []).append(entry["t"])

for behavior, times in disconnect_times.items():
    axes[0, 1].hist(times, bins=20, alpha=0.7, label=behavior)
axes[0, 1].set_title("Disconnect timing by behavior")
axes[0, 1].set_xlabel("Time (s)")
axes[0, 1].legend()

# H1 rejections over time
h1_times = [e["t"] for e in result.log if e["event"] == "reject_h1"]
if h1_times:
    axes[1, 0].hist(h1_times, bins=30)
    axes[1, 0].set_title("H1 rejections over time")
    axes[1, 0].set_xlabel("Time (s)")

# H2 evictions over time
h2_times = [e["t"] for e in result.log if e["event"] == "evict_h2_saturation"]
if h2_times:
    axes[1, 1].hist(h2_times, bins=30)
    axes[1, 1].set_title("H2 saturation evictions over time")
    axes[1, 1].set_xlabel("Time (s)")

plt.tight_layout()
plt.show()
```

Cell 5 (code - parameter sensitivity):
```python
# Sweep saturation_timeout
timeouts = [10, 20, 30, 45, 60, 90]
h2_evictions = []
false_positives = []
for timeout in timeouts:
    cfg_t = HeuristicConfig(saturation_timeout=timeout)
    r = run_simulation(cfg_t, scenario)
    h2_evictions.append(r.h2_evictions)
    false_positives.append(r.false_positives)

fig, ax1 = plt.subplots(figsize=(10, 5))
ax1.plot(timeouts, h2_evictions, "b-o", label="H2 evictions (attacks caught)")
ax1.set_xlabel("Saturation timeout (s)")
ax1.set_ylabel("H2 evictions", color="b")
ax2 = ax1.twinx()
ax2.plot(timeouts, false_positives, "r-s", label="False positives")
ax2.set_ylabel("False positives", color="r")
ax1.legend(loc="upper left")
ax2.legend(loc="upper right")
plt.title("Saturation timeout sensitivity")
plt.show()
```

**Step 2: Verify notebook loads**

Run: `uv run python -c "import json; json.load(open('heuristic_sim/notebook.ipynb'))"`
Expected: No error

**Step 3: Commit**

```bash
git add heuristic_sim/notebook.ipynb
git commit -m "feat(heuristic-sim): add Jupyter notebook for interactive exploration"
```

---

### Task 11: Integration test with all 6 attacks

**Files:**
- Modify: `tests/test_heuristic_sim.py`

**Step 1: Write the integration test**

```python
class TestFullIntegration:
    """Integration test: all 6 attacks running simultaneously."""

    def test_all_attacks_detected_no_false_positives(self):
        scenario = Scenario(
            n_honest=30,
            attackers=[
                (3, "spammer", {"rate": 5.0, "below_includability": True}),
                (3, "withholder", {"random_fail_rate": 1.0}),
                (2, "spoofer", {}),
                (2, "free_rider", {}),
                (2, "non_announcer", {}),
                (3, "selective_signaler", {"n_senders": 5, "txs_per_sender": 16}),
            ],
            tx_arrival_rate=2.0,
            t_end=300.0,
        )
        result = run_simulation(HeuristicConfig(), scenario, seed=42)

        # No honest peers disconnected
        assert result.false_positives == 0, (
            f"False positives: {result.false_positives}"
        )

        # Spam below includability rejected
        assert result.h1_rejections > 0, "H1 should reject below-fee spam"

        # Selective signaler txs evicted
        assert result.h2_evictions > 0, "H2 should evict uncorroborated txs"

        # Withholders and spoofers disconnected
        assert result.disconnects_by_behavior.get("withholder", 0) > 0, (
            "H4 should disconnect withholders"
        )
        assert result.disconnects_by_behavior.get("spoofer", 0) > 0, (
            "H4 should disconnect spoofers"
        )

    def test_results_reproducible(self):
        scenario = Scenario(
            n_honest=10,
            attackers=[(3, "withholder", {"random_fail_rate": 0.8})],
            tx_arrival_rate=1.0,
            t_end=60.0,
        )
        r1 = run_simulation(HeuristicConfig(), scenario, seed=99)
        r2 = run_simulation(HeuristicConfig(), scenario, seed=99)
        assert r1.total_accepted == r2.total_accepted
        assert r1.h4_disconnects == r2.h4_disconnects
```

**Step 2: Run test to verify it passes**

Run: `uv run pytest tests/test_heuristic_sim.py::TestFullIntegration -v`
Expected: PASS (2 tests)

**Step 3: Commit**

```bash
git add tests/test_heuristic_sim.py
git commit -m "test(heuristic-sim): add integration test with all 6 attacks"
```

---

### Task 12: Add justfile recipes

**Files:**
- Modify: `justfile`

**Step 1: Add recipes**

Append to the justfile:

```just
# --- Heuristic Simulator ---

# Run heuristic simulator tests
test-heuristic:
    uv run pytest tests/test_heuristic_sim.py -v

# Run parameter sweep (all params)
sweep:
    uv run python -m heuristic_sim.sweep

# Run parameter sweep for a specific param
sweep-param param:
    uv run python -m heuristic_sim.sweep --param {{param}}
```

**Step 2: Verify recipes work**

Run: `just test-heuristic`
Expected: All tests pass

**Step 3: Commit**

```bash
git add justfile
git commit -m "feat(heuristic-sim): add justfile recipes for testing and sweeps"
```

---

## Decisions

- **Standalone module (`heuristic_sim/`)** instead of extending `single_node_sim/`: the existing package depends on `sparse_blobpool` framework classes (Simulator, Actor, Blobpool). The new simulator is self-contained with no external dependencies beyond stdlib + matplotlib.
- **`Event.data` as `dict[str, Any]`** instead of typed event subclasses: keeps the single-file approach manageable. The match/case on `event.kind` strings is sufficient for 9 event types.
- **Peer behaviors generate all events upfront** rather than reactively: simpler to implement. The event loop still processes them in timestamp order. For behaviors that need to react (like cell responses), the runner dispatches to `behavior.respond_to_cell_request()` synchronously during the loop.
- **H5 (peer scoring) runs periodically** (every 30s) rather than on every event: avoids O(peers * events) overhead.
- **H6 (conservative inclusion) is just a flag** on the block handler: txs are only "includable" if `cell_mask == ALL_ONES`.
- **Free-rider (T3.1) and non-announcer (T3.3) detection** deferred to H5 scoring: these require statistical observation over time, not immediate heuristic triggers. The scoring function penalizes peers with 0% provider rate or 0 announcements.
