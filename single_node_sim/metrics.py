"""Metrics collection for single-node blobpool simulation."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sparse_blobpool.core.simulator import Simulator
    from sparse_blobpool.pool.blobpool import Blobpool


class TxState(Enum):
    PENDING = auto()
    FETCHING = auto()
    COMPLETE = auto()
    EVICTED = auto()
    EXPIRED = auto()


class Role(Enum):
    PROVIDER = auto()
    SAMPLER = auto()


@dataclass
class TxRecord:
    tx_hash: str
    announced_at: float
    role: Role
    state_history: list[tuple[float, TxState]]
    completed_at: float | None = None
    evicted_at: float | None = None
    eviction_reason: str | None = None


@dataclass
class PoolSnapshot:
    timestamp: float
    tx_count: int
    size_bytes: int


@dataclass
class MetricsSummary:
    total_announcements: int
    total_completions: int
    total_evictions: int
    avg_completion_time: float
    peak_pool_size: int
    peak_tx_count: int


class SingleNodeMetrics:
    def __init__(self, simulator: Simulator) -> None:
        self._simulator = simulator
        self._tx_records: dict[str, TxRecord] = {}
        self._snapshots: list[PoolSnapshot] = []
        self._debug_log: list[str] = []
        self._peak_size = 0
        self._peak_tx_count = 0
        self._rejections: dict[str, str] = {}

    def record_announcement(self, tx_hash: str, role: Role) -> None:
        current_time = self._simulator.current_time
        record = TxRecord(
            tx_hash=tx_hash,
            announced_at=current_time,
            role=role,
            state_history=[(current_time, TxState.PENDING)],
        )
        self._tx_records[tx_hash] = record
        self._log(f"ANNOUNCE tx={tx_hash[:16]}... role={role.name}")

    def record_state_transition(self, tx_hash: str, state: TxState) -> None:
        record = self._tx_records.get(tx_hash)
        if record is None:
            return
        current_time = self._simulator.current_time
        record.state_history.append((current_time, state))
        self._log(f"STATE tx={tx_hash[:16]}... -> {state.name}")

    def record_completion(self, tx_hash: str) -> None:
        record = self._tx_records.get(tx_hash)
        if record is None:
            return
        current_time = self._simulator.current_time
        record.completed_at = current_time
        record.state_history.append((current_time, TxState.COMPLETE))
        self._log(f"COMPLETE tx={tx_hash[:16]}...")

    def record_eviction(self, tx_hash: str, reason: str) -> None:
        record = self._tx_records.get(tx_hash)
        if record is None:
            return
        current_time = self._simulator.current_time
        record.evicted_at = current_time
        record.eviction_reason = reason
        record.state_history.append((current_time, TxState.EVICTED))
        self._log(f"EVICT tx={tx_hash[:16]}... reason={reason}")

    def record_rejection(self, tx_hash: str, reason: str) -> None:
        self._rejections[tx_hash] = reason
        self._log(f"REJECT tx={tx_hash[:16]}... reason={reason}")

    def snapshot(self, pool: Blobpool) -> None:
        current_time = self._simulator.current_time
        snap = PoolSnapshot(
            timestamp=current_time,
            tx_count=pool.tx_count,
            size_bytes=pool.size_bytes,
        )
        self._snapshots.append(snap)

        if pool.size_bytes > self._peak_size:
            self._peak_size = pool.size_bytes
        if pool.tx_count > self._peak_tx_count:
            self._peak_tx_count = pool.tx_count

    def get_snapshots(self) -> list[PoolSnapshot]:
        return self._snapshots.copy()

    def get_tx_records(self) -> dict[str, TxRecord]:
        return self._tx_records.copy()

    def summary(self) -> MetricsSummary:
        total_announcements = len(self._tx_records)
        total_completions = sum(
            1 for r in self._tx_records.values() if r.completed_at is not None
        )
        total_evictions = sum(
            1 for r in self._tx_records.values() if r.evicted_at is not None
        )

        completion_times: list[float] = []
        for record in self._tx_records.values():
            if record.completed_at is not None:
                completion_times.append(record.completed_at - record.announced_at)

        avg_completion_time = (
            sum(completion_times) / len(completion_times) if completion_times else 0.0
        )

        return MetricsSummary(
            total_announcements=total_announcements,
            total_completions=total_completions,
            total_evictions=total_evictions,
            avg_completion_time=avg_completion_time,
            peak_pool_size=self._peak_size,
            peak_tx_count=self._peak_tx_count,
        )

    def get_debug_log(self) -> list[str]:
        return self._debug_log.copy()

    def _log(self, message: str) -> None:
        self._debug_log.append(f"[{self._simulator.current_time:.3f}] {message}")
