"""Tests for single_node_sim.metrics module."""

import pytest
from unittest.mock import Mock, patch

from single_node_sim.metrics import (
    MetricsSummary,
    PoolSnapshot,
    Role,
    SingleNodeMetrics,
    TxRecord,
    TxState,
)
from sparse_blobpool.core.simulator import Simulator


class TestTxState:
    def test_all_states_exist(self) -> None:
        """All expected TxState values exist."""
        assert TxState.PENDING is not None
        assert TxState.FETCHING is not None
        assert TxState.COMPLETE is not None
        assert TxState.EVICTED is not None
        assert TxState.EXPIRED is not None

    def test_states_are_distinct(self) -> None:
        """All TxState values are distinct."""
        states = [TxState.PENDING, TxState.FETCHING, TxState.COMPLETE, TxState.EVICTED, TxState.EXPIRED]
        assert len(set(states)) == 5


class TestRole:
    def test_all_roles_exist(self) -> None:
        """All expected Role values exist."""
        assert Role.PROVIDER is not None
        assert Role.SAMPLER is not None

    def test_roles_are_distinct(self) -> None:
        """All Role values are distinct."""
        assert Role.PROVIDER != Role.SAMPLER


class TestTxRecord:
    def test_creation(self) -> None:
        """TxRecord can be created with required fields."""
        record = TxRecord(
            tx_hash="0xabc",
            announced_at=1.0,
            role=Role.PROVIDER,
            state_history=[(1.0, TxState.PENDING)],
        )

        assert record.tx_hash == "0xabc"
        assert record.announced_at == 1.0
        assert record.role == Role.PROVIDER
        assert record.state_history == [(1.0, TxState.PENDING)]
        assert record.completed_at is None
        assert record.evicted_at is None
        assert record.eviction_reason is None

    def test_optional_fields(self) -> None:
        """TxRecord optional fields can be set."""
        record = TxRecord(
            tx_hash="0xabc",
            announced_at=1.0,
            role=Role.SAMPLER,
            state_history=[(1.0, TxState.PENDING), (2.0, TxState.COMPLETE)],
            completed_at=2.0,
        )

        assert record.completed_at == 2.0


class TestPoolSnapshot:
    def test_creation(self) -> None:
        """PoolSnapshot can be created."""
        snap = PoolSnapshot(
            timestamp=5.0,
            tx_count=10,
            size_bytes=1024000,
        )

        assert snap.timestamp == 5.0
        assert snap.tx_count == 10
        assert snap.size_bytes == 1024000


class TestMetricsSummary:
    def test_creation(self) -> None:
        """MetricsSummary can be created."""
        summary = MetricsSummary(
            total_announcements=100,
            total_completions=80,
            total_evictions=15,
            avg_completion_time=2.5,
            peak_pool_size=5000000,
            peak_tx_count=50,
        )

        assert summary.total_announcements == 100
        assert summary.total_completions == 80
        assert summary.total_evictions == 15
        assert summary.avg_completion_time == 2.5
        assert summary.peak_pool_size == 5000000
        assert summary.peak_tx_count == 50


class TestSingleNodeMetrics:
    @pytest.fixture
    def metrics(self) -> SingleNodeMetrics:
        """Create a SingleNodeMetrics instance with mock simulator."""
        simulator = Simulator(seed=42)
        return SingleNodeMetrics(simulator)

    def test_record_announcement_creates_tx_record(self, metrics: SingleNodeMetrics) -> None:
        """record_announcement creates a TxRecord."""
        metrics.record_announcement("0xabc", Role.PROVIDER)

        records = metrics.get_tx_records()
        assert "0xabc" in records
        assert records["0xabc"].role == Role.PROVIDER
        assert records["0xabc"].announced_at == 0.0
        assert len(records["0xabc"].state_history) == 1
        assert records["0xabc"].state_history[0] == (0.0, TxState.PENDING)

    def test_record_state_transition_updates_history(self, metrics: SingleNodeMetrics) -> None:
        """record_state_transition updates state_history."""
        metrics.record_announcement("0xabc", Role.SAMPLER)
        metrics.record_state_transition("0xabc", TxState.FETCHING)

        records = metrics.get_tx_records()
        assert len(records["0xabc"].state_history) == 2
        assert records["0xabc"].state_history[1][1] == TxState.FETCHING

    def test_record_state_transition_ignores_unknown_tx(self, metrics: SingleNodeMetrics) -> None:
        """record_state_transition ignores unknown tx_hash."""
        metrics.record_state_transition("0xunknown", TxState.FETCHING)

        records = metrics.get_tx_records()
        assert "0xunknown" not in records

    def test_record_completion_sets_completed_at(self, metrics: SingleNodeMetrics) -> None:
        """record_completion sets completed_at."""
        metrics.record_announcement("0xabc", Role.PROVIDER)
        metrics.record_completion("0xabc")

        records = metrics.get_tx_records()
        assert records["0xabc"].completed_at == 0.0
        assert records["0xabc"].state_history[-1][1] == TxState.COMPLETE

    def test_record_completion_ignores_unknown_tx(self, metrics: SingleNodeMetrics) -> None:
        """record_completion ignores unknown tx_hash."""
        metrics.record_completion("0xunknown")

        records = metrics.get_tx_records()
        assert "0xunknown" not in records

    def test_record_eviction_sets_evicted_at_and_reason(self, metrics: SingleNodeMetrics) -> None:
        """record_eviction sets evicted_at and reason."""
        metrics.record_announcement("0xabc", Role.SAMPLER)
        metrics.record_eviction("0xabc", "fee_too_low")

        records = metrics.get_tx_records()
        assert records["0xabc"].evicted_at == 0.0
        assert records["0xabc"].eviction_reason == "fee_too_low"
        assert records["0xabc"].state_history[-1][1] == TxState.EVICTED

    def test_record_eviction_ignores_unknown_tx(self, metrics: SingleNodeMetrics) -> None:
        """record_eviction ignores unknown tx_hash."""
        metrics.record_eviction("0xunknown", "some_reason")

        records = metrics.get_tx_records()
        assert "0xunknown" not in records

    def test_snapshot_captures_pool_state(self, metrics: SingleNodeMetrics) -> None:
        """snapshot captures pool state."""
        mock_pool = Mock()
        mock_pool.tx_count = 5
        mock_pool.size_bytes = 100000

        metrics.snapshot(mock_pool)

        snapshots = metrics.get_snapshots()
        assert len(snapshots) == 1
        assert snapshots[0].tx_count == 5
        assert snapshots[0].size_bytes == 100000

    def test_snapshot_updates_peaks(self, metrics: SingleNodeMetrics) -> None:
        """snapshot updates peak values."""
        mock_pool1 = Mock()
        mock_pool1.tx_count = 5
        mock_pool1.size_bytes = 100000

        mock_pool2 = Mock()
        mock_pool2.tx_count = 10
        mock_pool2.size_bytes = 200000

        mock_pool3 = Mock()
        mock_pool3.tx_count = 3
        mock_pool3.size_bytes = 50000

        metrics.snapshot(mock_pool1)
        metrics.snapshot(mock_pool2)
        metrics.snapshot(mock_pool3)

        summary = metrics.summary()
        assert summary.peak_tx_count == 10
        assert summary.peak_pool_size == 200000

    def test_summary_computes_correct_aggregates(self, metrics: SingleNodeMetrics) -> None:
        """summary computes correct aggregate values."""
        metrics.record_announcement("0x1", Role.PROVIDER)
        metrics.record_announcement("0x2", Role.SAMPLER)
        metrics.record_announcement("0x3", Role.PROVIDER)

        metrics.record_completion("0x1")
        metrics.record_completion("0x2")
        metrics.record_eviction("0x3", "ttl_expired")

        summary = metrics.summary()
        assert summary.total_announcements == 3
        assert summary.total_completions == 2
        assert summary.total_evictions == 1

    def test_summary_avg_completion_time(self) -> None:
        """summary computes correct average completion time."""
        simulator = Simulator(seed=42)
        metrics = SingleNodeMetrics(simulator)

        metrics.record_announcement("0x1", Role.PROVIDER)
        simulator._current_time = 2.0  # Advance time
        metrics.record_completion("0x1")

        metrics.record_announcement("0x2", Role.SAMPLER)
        simulator._current_time = 6.0  # Advance time
        metrics.record_completion("0x2")

        summary = metrics.summary()
        assert summary.avg_completion_time == 3.0

    def test_summary_avg_completion_time_no_completions(self, metrics: SingleNodeMetrics) -> None:
        """summary returns 0.0 avg_completion_time when no completions."""
        metrics.record_announcement("0x1", Role.PROVIDER)

        summary = metrics.summary()
        assert summary.avg_completion_time == 0.0

    def test_debug_log_contains_expected_entries(self, metrics: SingleNodeMetrics) -> None:
        """debug_log contains expected entries."""
        metrics.record_announcement("0xabcdef123456789", Role.PROVIDER)
        metrics.record_state_transition("0xabcdef123456789", TxState.FETCHING)
        metrics.record_completion("0xabcdef123456789")

        log = metrics.get_debug_log()
        assert len(log) == 3
        assert "ANNOUNCE" in log[0]
        assert "STATE" in log[1]
        assert "FETCHING" in log[1]
        assert "COMPLETE" in log[2]

    def test_get_tx_records_returns_copy(self, metrics: SingleNodeMetrics) -> None:
        """get_tx_records returns a copy."""
        metrics.record_announcement("0x1", Role.PROVIDER)

        records1 = metrics.get_tx_records()
        records2 = metrics.get_tx_records()

        assert records1 is not records2
        assert records1 == records2

    def test_get_snapshots_returns_copy(self, metrics: SingleNodeMetrics) -> None:
        """get_snapshots returns a copy."""
        mock_pool = Mock()
        mock_pool.tx_count = 5
        mock_pool.size_bytes = 100000

        metrics.snapshot(mock_pool)

        snaps1 = metrics.get_snapshots()
        snaps2 = metrics.get_snapshots()

        assert snaps1 is not snaps2
        assert snaps1 == snaps2

    def test_get_debug_log_returns_copy(self, metrics: SingleNodeMetrics) -> None:
        """get_debug_log returns a copy."""
        metrics.record_announcement("0x1", Role.PROVIDER)

        log1 = metrics.get_debug_log()
        log2 = metrics.get_debug_log()

        assert log1 is not log2
        assert log1 == log2

    def test_record_rejection(self, metrics: SingleNodeMetrics) -> None:
        """record_rejection stores rejection reason."""
        metrics.record_rejection("0xabc", "rate_limited")

        log = metrics.get_debug_log()
        assert len(log) == 1
        assert "REJECT" in log[0]
        assert "rate_limited" in log[0]
