"""Tests for the MetricsCollector."""

from sparse_blobpool.actors.honest import Role
from sparse_blobpool.core.simulator import Simulator
from sparse_blobpool.core.types import ActorId, TxHash
from sparse_blobpool.metrics.collector import MetricsCollector
from sparse_blobpool.protocol.constants import ALL_ONES


class TestMetricsCollector:
    def test_register_node(self) -> None:
        sim = Simulator()
        metrics = MetricsCollector(simulator=sim)

        metrics.register_node(ActorId("node1"), "united states", custody_mask=0xFF)
        metrics.register_node(ActorId("node2"), "germany", custody_mask=0xFF00)

        assert metrics.node_count == 2
        assert metrics.node_countries[ActorId("node1")] == "united states"
        assert metrics.node_countries[ActorId("node2")] == "germany"
        assert metrics.node_custody_masks[ActorId("node1")] == 0xFF
        assert metrics.node_custody_masks[ActorId("node2")] == 0xFF00

    def test_record_bandwidth(self) -> None:
        sim = Simulator()
        metrics = MetricsCollector(simulator=sim)

        metrics.record_bandwidth(ActorId("a"), ActorId("b"), 1000, is_control=True)
        metrics.record_bandwidth(ActorId("a"), ActorId("c"), 2000, is_control=False)

        assert metrics.bytes_sent[ActorId("a")] == 3000
        assert metrics.bytes_received[ActorId("b")] == 1000
        assert metrics.bytes_received[ActorId("c")] == 2000
        assert metrics.bytes_sent_control[ActorId("a")] == 1000
        assert metrics.bytes_sent_data[ActorId("a")] == 2000

    def test_record_tx_seen_provider(self) -> None:
        sim = Simulator()
        metrics = MetricsCollector(simulator=sim, node_count=10)

        tx_hash = TxHash("abc123")
        metrics.record_tx_seen(ActorId("node1"), tx_hash, Role.PROVIDER, ALL_ONES)

        assert tx_hash in metrics.tx_metrics
        tx_metrics = metrics.tx_metrics[tx_hash]
        assert tx_metrics.provider_count == 1
        assert tx_metrics.sampler_count == 0
        assert ActorId("node1") in tx_metrics.nodes_seen

    def test_record_tx_seen_sampler(self) -> None:
        sim = Simulator()
        metrics = MetricsCollector(simulator=sim, node_count=10)

        tx_hash = TxHash("abc123")
        partial_mask = 0xFF  # Only 8 columns
        metrics.record_tx_seen(ActorId("node1"), tx_hash, Role.SAMPLER, partial_mask)

        tx_metrics = metrics.tx_metrics[tx_hash]
        assert tx_metrics.provider_count == 0
        assert tx_metrics.sampler_count == 1

    def test_propagation_complete_tracking(self) -> None:
        sim = Simulator()
        metrics = MetricsCollector(simulator=sim, node_count=10)

        tx_hash = TxHash("abc123")

        # Add 9 nodes (90%) - not complete
        for i in range(9):
            metrics.record_tx_seen(ActorId(f"node{i}"), tx_hash, Role.PROVIDER, ALL_ONES)

        tx_metrics = metrics.tx_metrics[tx_hash]
        assert tx_metrics.propagation_complete_time is None

        # Add 10th node (100%) - complete
        metrics.record_tx_seen(ActorId("node9"), tx_hash, Role.PROVIDER, ALL_ONES)
        assert tx_metrics.propagation_complete_time is not None

    def test_record_inclusion(self) -> None:
        sim = Simulator()
        metrics = MetricsCollector(simulator=sim)

        tx_hash = TxHash("abc123")
        # First record the tx being seen
        metrics.record_tx_seen(ActorId("node1"), tx_hash, Role.PROVIDER, ALL_ONES)

        # Then record inclusion
        metrics.record_inclusion(tx_hash, slot=5)

        assert metrics.tx_metrics[tx_hash].included_at_slot == 5

    def test_finalize_returns_results(self) -> None:
        sim = Simulator()
        metrics = MetricsCollector(simulator=sim, node_count=10)

        # Record some activity
        tx_hash = TxHash("abc123")
        for i in range(10):
            metrics.record_tx_seen(ActorId(f"node{i}"), tx_hash, Role.PROVIDER, ALL_ONES)

        metrics.record_bandwidth(ActorId("a"), ActorId("b"), 1000)

        results = metrics.finalize()

        assert results.total_bandwidth_bytes == 1000
        assert results.propagation_success_rate == 1.0
        assert results.observed_provider_ratio == 1.0  # All providers

    def test_snapshot_creates_timeseries(self) -> None:
        from dataclasses import dataclass

        from sparse_blobpool.core.actor import Actor, Command, EventPayload
        from sparse_blobpool.core.simulator import Event

        @dataclass
        class DummyCommand(Command):
            @property
            def size_bytes(self) -> int:
                return 0

        sim = Simulator()
        metrics = MetricsCollector(simulator=sim, sample_interval=1.0)

        # Need a dummy actor to advance time
        class DummyActor(Actor):
            def on_event(self, payload: EventPayload) -> None:
                pass

        actor = DummyActor(ActorId("dummy"), sim)
        sim.register_actor(actor)

        # Schedule and process an event to advance time
        sim.schedule(Event(timestamp=2.0, target_id=ActorId("dummy"), payload=DummyCommand()))
        sim.run(until=3.0)

        # Take snapshot at time 2.0
        metrics.snapshot()

        assert len(metrics.bandwidth_timeseries) == 1
        assert metrics.bandwidth_timeseries[0].timestamp == 2.0


class TestSimulationResults:
    def test_to_dict(self) -> None:
        sim = Simulator()
        metrics = MetricsCollector(simulator=sim, node_count=10)

        tx_hash = TxHash("abc123")
        for i in range(10):
            metrics.record_tx_seen(ActorId(f"node{i}"), tx_hash, Role.PROVIDER, ALL_ONES)

        results = metrics.finalize()
        result_dict = results.to_dict()

        assert "total_bandwidth_bytes" in result_dict
        assert "bandwidth_per_blob" in result_dict
        assert "observed_provider_ratio" in result_dict
