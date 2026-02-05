"""Tests for single_node_sim.runner module."""

import pytest

from single_node_sim import run
from single_node_sim.events import BlockIncluded, TxAnnouncement
from single_node_sim.params import PRESETS, EvictionPolicy, HeuristicParams
from sparse_blobpool.protocol.constants import ALL_ONES


def make_tx_announcement(
    timestamp: float = 0.0,
    tx_hash: str = "0xabc",
    sender: str = "0xsender",
    nonce: int = 0,
    gas_fee_cap: int = 1_000_000_000,
    gas_tip_cap: int = 100_000_000,
    tx_size: int = 131_072,
    blob_count: int = 1,
    cell_mask: int = ALL_ONES,
) -> TxAnnouncement:
    return TxAnnouncement(
        timestamp=timestamp,
        tx_hash=tx_hash,
        sender=sender,
        nonce=nonce,
        gas_fee_cap=gas_fee_cap,
        gas_tip_cap=gas_tip_cap,
        tx_size=tx_size,
        blob_count=blob_count,
        cell_mask=cell_mask,
    )


class TestEmptyEvents:

    def test_empty_events_returns_valid_result(self) -> None:
        result = run(events=[])

        assert result is not None
        summary = result.metrics.summary()
        assert summary.total_announcements == 0
        assert summary.total_completions == 0
        assert summary.total_evictions == 0

    def test_empty_events_with_custom_params(self) -> None:
        params = HeuristicParams(seed=123)
        result = run(events=[], params=params)

        assert result is not None


class TestSingleTransactionFlow:

    def test_single_transaction_completes(self) -> None:
        events = [make_tx_announcement(timestamp=0.0, tx_hash="0xabc")]
        result = run(events=events)

        summary = result.metrics.summary()
        assert summary.total_announcements == 1
        assert summary.total_completions >= 0

    def test_single_transaction_records_captured(self) -> None:
        events = [make_tx_announcement(timestamp=0.0, tx_hash="0xabc")]
        result = run(events=events)

        records = result.metrics.get_tx_records()
        assert "0xabc" in records


class TestMultipleTransactions:

    def test_multiple_transactions_processed(self) -> None:
        events = [
            make_tx_announcement(timestamp=0.0, tx_hash="0x1", sender="0xs1"),
            make_tx_announcement(timestamp=1.0, tx_hash="0x2", sender="0xs2"),
            make_tx_announcement(timestamp=2.0, tx_hash="0x3", sender="0xs3"),
        ]
        result = run(events=events)

        summary = result.metrics.summary()
        assert summary.total_announcements == 3

    def test_transactions_from_same_sender(self) -> None:
        events = [
            make_tx_announcement(timestamp=0.0, tx_hash="0x1", sender="0xs", nonce=0),
            make_tx_announcement(timestamp=1.0, tx_hash="0x2", sender="0xs", nonce=1),
            make_tx_announcement(timestamp=2.0, tx_hash="0x3", sender="0xs", nonce=2),
        ]
        result = run(events=events)

        summary = result.metrics.summary()
        assert summary.total_announcements == 3


class TestPresetParameters:

    def test_default_preset(self) -> None:
        events = [make_tx_announcement(timestamp=0.0, tx_hash="0xabc")]
        result = run(events=events, params=PRESETS["default"])

        assert result is not None

    def test_aggressive_eviction_preset(self) -> None:
        events = [make_tx_announcement(timestamp=0.0, tx_hash="0xabc")]
        result = run(events=events, params=PRESETS["aggressive_eviction"])

        assert result is not None

    def test_high_provider_preset(self) -> None:
        events = [make_tx_announcement(timestamp=0.0, tx_hash="0xabc")]
        result = run(events=events, params=PRESETS["high_provider"])

        assert result is not None

    def test_strict_rate_limit_preset(self) -> None:
        events = [make_tx_announcement(timestamp=0.0, tx_hash="0xabc")]
        result = run(events=events, params=PRESETS["strict_rate_limit"])

        assert result is not None

    def test_short_ttl_preset(self) -> None:
        events = [make_tx_announcement(timestamp=0.0, tx_hash="0xabc")]
        result = run(events=events, params=PRESETS["short_ttl"])

        assert result is not None


class TestCustomParameters:

    def test_custom_seed(self) -> None:
        events = [make_tx_announcement(timestamp=0.0, tx_hash="0xabc")]
        params = HeuristicParams(seed=12345)

        result1 = run(events=events, params=params)
        result2 = run(events=events, params=params)

        summary1 = result1.metrics.summary()
        summary2 = result2.metrics.summary()
        assert summary1 == summary2

    def test_custom_eviction_policy(self) -> None:
        events = [make_tx_announcement(timestamp=0.0, tx_hash="0xabc")]
        params = HeuristicParams(eviction_policy=EvictionPolicy.AGE_BASED)

        result = run(events=events, params=params)

        assert result is not None

    def test_custom_pool_size(self) -> None:
        events = [
            make_tx_announcement(timestamp=0.0, tx_hash="0x1", sender="0xs1", tx_size=100_000),
            make_tx_announcement(timestamp=1.0, tx_hash="0x2", sender="0xs2", tx_size=100_000),
            make_tx_announcement(timestamp=2.0, tx_hash="0x3", sender="0xs3", tx_size=100_000),
        ]
        params = HeuristicParams(max_pool_bytes=150_000)

        result = run(events=events, params=params)

        summary = result.metrics.summary()
        assert summary.total_evictions > 0


class TestBlockInclusion:

    def test_block_removes_transactions(self) -> None:
        events: list = [
            make_tx_announcement(timestamp=0.0, tx_hash="0x1"),
            make_tx_announcement(timestamp=0.1, tx_hash="0x2", sender="0xs2"),
            BlockIncluded(timestamp=5.0, tx_hashes=["0x1"]),
        ]

        result = run(events=events)

        records = result.metrics.get_tx_records()
        assert records["0x1"].completed_at is not None


class TestSimulationResult:

    def test_result_has_node(self) -> None:
        events = [make_tx_announcement(timestamp=0.0, tx_hash="0xabc")]
        result = run(events=events)

        assert hasattr(result, "node")
        assert result.node is not None

    def test_result_has_metrics(self) -> None:
        events = [make_tx_announcement(timestamp=0.0, tx_hash="0xabc")]
        result = run(events=events)

        assert hasattr(result, "metrics")
        assert result.metrics is not None

    def test_result_has_final_time(self) -> None:
        events = [make_tx_announcement(timestamp=0.0, tx_hash="0xabc")]
        result = run(events=events)

        assert hasattr(result, "final_time")
        assert result.final_time >= 0

    def test_metrics_summary_available(self) -> None:
        events = [make_tx_announcement(timestamp=0.0, tx_hash="0xabc")]
        result = run(events=events)

        summary = result.metrics.summary()
        assert summary is not None

    def test_metrics_tx_records_available(self) -> None:
        events = [make_tx_announcement(timestamp=0.0, tx_hash="0xabc")]
        result = run(events=events)

        records = result.metrics.get_tx_records()
        assert isinstance(records, dict)

    def test_metrics_snapshots_available(self) -> None:
        events = [make_tx_announcement(timestamp=0.0, tx_hash="0xabc")]
        result = run(events=events)

        snapshots = result.metrics.get_snapshots()
        assert isinstance(snapshots, list)

    def test_metrics_debug_log_available(self) -> None:
        events = [make_tx_announcement(timestamp=0.0, tx_hash="0xabc")]
        result = run(events=events)

        debug_log = result.metrics.get_debug_log()
        assert isinstance(debug_log, list)


class TestDictEvents:

    def test_dict_events_normalized(self) -> None:
        events: list[dict] = [
            {
                "timestamp": 0.0,
                "tx_hash": "0xabc",
                "sender": "0xsender",
                "nonce": 0,
                "gas_fee_cap": 1_000_000_000,
                "gas_tip_cap": 100_000_000,
                "tx_size": 131_072,
                "blob_count": 1,
            },
        ]

        result = run(events=events)

        summary = result.metrics.summary()
        assert summary.total_announcements == 1

    def test_mixed_dict_and_dataclass_events(self) -> None:
        events: list = [
            make_tx_announcement(timestamp=0.0, tx_hash="0x1"),
            {
                "timestamp": 1.0,
                "tx_hash": "0x2",
                "sender": "0xsender2",
                "nonce": 0,
                "gas_fee_cap": 1_000_000_000,
                "gas_tip_cap": 100_000_000,
                "tx_size": 131_072,
                "blob_count": 1,
            },
        ]

        result = run(events=events)

        summary = result.metrics.summary()
        assert summary.total_announcements == 2


class TestPresetByName:

    def test_preset_by_name(self) -> None:
        events = [make_tx_announcement(timestamp=0.0, tx_hash="0xabc")]
        result = run(events=events, preset="default")

        assert result is not None

    def test_invalid_preset_name_raises(self) -> None:
        events = [make_tx_announcement(timestamp=0.0, tx_hash="0xabc")]

        with pytest.raises(KeyError):
            run(events=events, preset="nonexistent")
