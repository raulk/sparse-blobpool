"""Single node actor for isolated blobpool simulation."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import TYPE_CHECKING

from single_node_sim.availability import AvailabilityMode
from single_node_sim.events import BlockIncluded, CellsReceived, TxAnnouncement
from single_node_sim.metrics import Role, SingleNodeMetrics, TxState
from single_node_sim.params import EvictionPolicy, HeuristicParams
from sparse_blobpool.config import SimulationConfig
from sparse_blobpool.core.actor import Actor, Command, EventPayload
from sparse_blobpool.pool.blobpool import (
    Blobpool,
    BlobTxEntry,
    PoolFull,
    RBFRejected,
    SenderLimitExceeded,
)
from sparse_blobpool.protocol.constants import ALL_ONES

__all__ = ["PendingTx", "SingleNode", "TokenBucket", "TxCleanup"]

if TYPE_CHECKING:
    from sparse_blobpool.core.simulator import Simulator
    from sparse_blobpool.core.types import ActorId


class TokenBucket:
    """Rate limiter using token bucket algorithm."""

    def __init__(self, rate: float, burst: int) -> None:
        self._rate = rate
        self._burst = burst
        self._tokens = float(burst)
        self._last_update = 0.0

    def consume(self, current_time: float) -> bool:
        elapsed = current_time - self._last_update
        self._last_update = current_time

        self._tokens = min(self._burst, self._tokens + elapsed * self._rate)

        if self._tokens >= 1.0:
            self._tokens -= 1.0
            return True
        return False


@dataclass
class TxCleanup(Command):
    """Cleanup command for expired transactions."""

    tx_hash: str


@dataclass
class PendingTx:
    """Tracks a transaction being processed by the node."""

    tx_hash: str
    role: Role
    state: TxState
    announced_at: float
    cell_mask: int = 0
    sender: str = ""
    nonce: int = 0
    gas_fee_cap: int = 0
    gas_tip_cap: int = 0
    tx_size: int = 0
    blob_count: int = 0


class SingleNode(Actor):
    """Single node actor for blobpool simulation.

    Processes transaction announcements, tracks cell availability, and manages
    eviction based on configurable policies. Unlike the full Node actor, this
    operates in isolation without peer-to-peer networking.
    """

    def __init__(
        self,
        actor_id: ActorId,
        simulator: Simulator,
        params: HeuristicParams,
        metrics: SingleNodeMetrics,
    ) -> None:
        super().__init__(actor_id, simulator)
        self._params = params
        self._metrics = metrics
        self._pool = Blobpool(self._make_config())
        self._pending: dict[str, PendingTx] = {}
        self._custody_mask = self._compute_custody_mask()
        self._rate_limiter = TokenBucket(
            params.max_announcements_per_second,
            params.burst_allowance,
        )

    @property
    def pool(self) -> Blobpool:
        return self._pool

    @property
    def custody_mask(self) -> int:
        return self._custody_mask

    @property
    def params(self) -> HeuristicParams:
        return self._params

    def _make_config(self) -> SimulationConfig:
        return SimulationConfig(
            blobpool_max_bytes=self._params.max_pool_bytes,
            max_txs_per_sender=self._params.max_txs_per_sender,
            provider_probability=self._params.provider_probability,
            custody_columns=self._params.custody_columns,
            tx_expiration=self._params.tx_ttl,
            seed=self._params.seed,
        )

    def _compute_custody_mask(self) -> int:
        hash_bytes = sha256(self._id.encode()).digest()
        seed = int.from_bytes(hash_bytes[:8], "big")
        rng = self._simulator.rng.__class__(seed)

        columns = set[int]()
        while len(columns) < self._params.custody_columns:
            col = rng.randint(0, 127)
            columns.add(col)

        mask = 0
        for col in columns:
            mask |= 1 << col
        return mask

    def _determine_role(self, tx_hash: str) -> Role:
        combined = f"{self._id}:{tx_hash}".encode()
        hash_bytes = sha256(combined).digest()
        hash_int = int.from_bytes(hash_bytes[:8], "big")
        probability = hash_int / (2**64)

        if probability < self._params.provider_probability:
            return Role.PROVIDER
        return Role.SAMPLER

    def on_event(self, payload: EventPayload) -> None:
        match payload:
            case TxAnnouncement() as event:
                self._handle_announcement(event)
            case CellsReceived() as event:
                self._handle_cells(event)
            case BlockIncluded() as event:
                self._handle_block(event)
            case TxCleanup() as cmd:
                self._handle_cleanup(cmd)

    def _handle_announcement(self, event: TxAnnouncement) -> None:
        if not self._rate_limiter.consume(self._simulator.current_time):
            self._metrics.record_rejection(event.tx_hash, "rate_limited")
            return

        if self._pool.contains(event.tx_hash):
            return

        if event.tx_hash in self._pending:
            return

        role = self._determine_role(event.tx_hash)
        self._metrics.record_announcement(event.tx_hash, role)

        pending = PendingTx(
            tx_hash=event.tx_hash,
            role=role,
            state=TxState.PENDING,
            announced_at=self._simulator.current_time,
            cell_mask=0,
            sender=event.sender,
            nonce=event.nonce,
            gas_fee_cap=event.gas_fee_cap,
            gas_tip_cap=event.gas_tip_cap,
            tx_size=event.tx_size,
            blob_count=event.blob_count,
        )
        self._pending[event.tx_hash] = pending

        self._schedule_tx_expiration(event.tx_hash)

        match self._params.availability_mode:
            case AvailabilityMode.INSTANT:
                self._complete_instantly(pending, event.cell_mask)
            case AvailabilityMode.SIMULATED_PARTIAL | AvailabilityMode.TRACE_DRIVEN:
                pending.state = TxState.FETCHING
                self._metrics.record_state_transition(event.tx_hash, TxState.FETCHING)

    def _complete_instantly(self, pending: PendingTx, cell_mask: int) -> None:
        if pending.role == Role.PROVIDER:
            pending.cell_mask = ALL_ONES
        else:
            pending.cell_mask = cell_mask & self._custody_mask

        self._try_complete(pending)

    def _handle_cells(self, event: CellsReceived) -> None:
        pending = self._pending.get(event.tx_hash)
        if pending is None:
            return

        pending.cell_mask |= event.cell_mask
        self._try_complete(pending)

    def _try_complete(self, pending: PendingTx) -> None:
        is_complete = False

        if pending.role == Role.PROVIDER:
            is_complete = pending.cell_mask == ALL_ONES
        else:
            is_complete = (pending.cell_mask & self._custody_mask) == self._custody_mask

        if not is_complete:
            return

        self._pending.pop(pending.tx_hash, None)

        entry = BlobTxEntry(
            tx_hash=pending.tx_hash,
            sender=pending.sender,
            nonce=pending.nonce,
            gas_fee_cap=pending.gas_fee_cap,
            gas_tip_cap=pending.gas_tip_cap,
            blob_gas_price=pending.gas_fee_cap,
            tx_size=pending.tx_size,
            blob_count=pending.blob_count,
            cell_mask=pending.cell_mask,
            received_at=self._simulator.current_time,
        )

        try:
            add_result = self._pool.add(entry)
            if not add_result.added:
                self._metrics.record_rejection(pending.tx_hash, "pool_add_failed")
                return

            for evicted_hash in add_result.evicted:
                self._metrics.record_eviction(evicted_hash, "eviction_fee_based")

            self._metrics.record_completion(pending.tx_hash)
            self._metrics.snapshot(self._pool)

        except PoolFull:
            self._metrics.record_rejection(pending.tx_hash, "pool_full")
        except RBFRejected:
            self._metrics.record_rejection(pending.tx_hash, "rbf_rejected")
        except SenderLimitExceeded:
            self._metrics.record_rejection(pending.tx_hash, "sender_limit")

    def _handle_block(self, event: BlockIncluded) -> None:
        for tx_hash in event.tx_hashes:
            self._pending.pop(tx_hash, None)
            if self._pool.contains(tx_hash):
                self._pool.remove(tx_hash)
                self._metrics.snapshot(self._pool)

    def _handle_cleanup(self, cmd: TxCleanup) -> None:
        pending = self._pending.pop(cmd.tx_hash, None)
        if pending is not None:
            self._metrics.record_eviction(cmd.tx_hash, "ttl_expired")
            return

        if self._pool.contains(cmd.tx_hash):
            self._pool.remove(cmd.tx_hash)
            self._metrics.record_eviction(cmd.tx_hash, "ttl_expired")
            self._metrics.snapshot(self._pool)

    def _schedule_tx_expiration(self, tx_hash: str) -> None:
        self.schedule_command(self._params.tx_ttl, TxCleanup(tx_hash=tx_hash))

    def _evict_by_policy(self) -> str | None:
        if self._pool.tx_count == 0:
            return None

        match self._params.eviction_policy:
            case EvictionPolicy.FEE_BASED:
                return self._evict_lowest_tip()
            case EvictionPolicy.AGE_BASED:
                return self._evict_oldest()
            case EvictionPolicy.HYBRID:
                return self._evict_hybrid()

    def _evict_lowest_tip(self) -> str | None:
        entries = list(self._pool.iter_by_priority())
        if not entries:
            return None

        lowest = entries[-1]
        self._pool.remove(lowest.tx_hash)
        self._metrics.record_eviction(lowest.tx_hash, "eviction_lowest_tip")
        return lowest.tx_hash

    def _evict_oldest(self) -> str | None:
        oldest: BlobTxEntry | None = None
        for entry in self._pool.iter_by_priority():
            if oldest is None or entry.received_at < oldest.received_at:
                oldest = entry

        if oldest is None:
            return None

        self._pool.remove(oldest.tx_hash)
        self._metrics.record_eviction(oldest.tx_hash, "eviction_oldest")
        return oldest.tx_hash

    def _evict_hybrid(self) -> str | None:
        current_time = self._simulator.current_time
        entries = list(self._pool.iter_by_priority())
        if not entries:
            return None

        max_tip = max(e.effective_tip for e in entries)
        max_age = max(current_time - e.received_at for e in entries) or 1.0

        age_weight = self._params.age_weight
        fee_weight = 1.0 - age_weight

        worst: BlobTxEntry | None = None
        worst_score = float("inf")

        for entry in entries:
            normalized_tip = entry.effective_tip / max_tip if max_tip > 0 else 0.0
            normalized_age = (current_time - entry.received_at) / max_age

            score = fee_weight * normalized_tip - age_weight * normalized_age
            if score < worst_score:
                worst_score = score
                worst = entry

        if worst is None:
            return None

        self._pool.remove(worst.tx_hash)
        self._metrics.record_eviction(worst.tx_hash, "eviction_hybrid")
        return worst.tx_hash
