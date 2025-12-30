"""Tests for the Network component and latency model."""

from dataclasses import dataclass

from sparse_blobpool.config import Region
from sparse_blobpool.core.actor import Actor, EventPayload, Message
from sparse_blobpool.core.network import (
    LATENCY_DEFAULTS,
    CoDelConfig,
    CoDelState,
    LatencyParams,
    Network,
)
from sparse_blobpool.core.simulator import Simulator
from sparse_blobpool.core.types import ActorId
from sparse_blobpool.metrics.collector import MetricsCollector


def make_network(sim: Simulator, **kwargs) -> Network:  # type: ignore[no-untyped-def]
    """Create network with default metrics."""
    metrics = MetricsCollector(simulator=sim)
    return Network(sim, metrics, **kwargs)


@dataclass
class SampleMessage(Message):
    """Simple message for testing with configurable size."""

    content: str
    _size: int = 100

    @property
    def size_bytes(self) -> int:
        return self._size


class RecordingActor(Actor):
    """Actor that records received messages with timestamps."""

    def __init__(self, actor_id: ActorId, simulator: Simulator) -> None:
        super().__init__(actor_id, simulator)
        self.received: list[tuple[float, Message]] = []

    def on_event(self, payload: EventPayload) -> None:
        if isinstance(payload, Message):
            self.received.append((self.simulator.current_time, payload))


class TestLatencyParams:
    def test_latency_defaults_cover_all_region_pairs(self) -> None:
        """Default latency matrix covers all region combinations."""
        regions = list(Region)
        for r1 in regions:
            for r2 in regions:
                assert (r1, r2) in LATENCY_DEFAULTS

    def test_latency_defaults_symmetric(self) -> None:
        """Cross-region latencies are symmetric."""
        for (r1, r2), params in LATENCY_DEFAULTS.items():
            if r1 != r2:
                reverse = LATENCY_DEFAULTS[(r2, r1)]
                assert params.base_ms == reverse.base_ms
                assert params.jitter_ratio == reverse.jitter_ratio

    def test_same_region_faster_than_cross_region(self) -> None:
        """Same-region latency is lower than cross-region."""
        for region in Region:
            same_region = LATENCY_DEFAULTS[(region, region)]
            for other_region in Region:
                if other_region != region:
                    cross_region = LATENCY_DEFAULTS[(region, other_region)]
                    assert same_region.base_ms < cross_region.base_ms


class TestNetwork:
    def test_network_creation(self) -> None:
        """Network component can be created and configured."""
        sim = Simulator()
        network = make_network(sim)
        sim._network = network

        assert network.messages_delivered == 0
        assert network.total_bytes == 0

    def test_message_delivery(self) -> None:
        """Messages are delivered to target actors."""
        sim = Simulator()
        network = make_network(sim)
        sim._network = network

        sender = RecordingActor(ActorId("sender"), sim)
        receiver = RecordingActor(ActorId("receiver"), sim)
        sim.register_actor(sender)
        sim.register_actor(receiver)

        # Register nodes with network
        network.register_node(ActorId("sender"), Region.NA)
        network.register_node(ActorId("receiver"), Region.NA)

        # Send a message
        msg = SampleMessage(sender=ActorId("sender"), content="hello")
        sender.send(msg, to=ActorId("receiver"))

        # Run simulation
        sim.run_until_empty()

        assert len(receiver.received) == 1
        assert receiver.received[0][1].content == "hello"  # type: ignore[union-attr]

    def test_message_delivery_has_latency(self) -> None:
        """Message delivery takes time based on latency model."""
        sim = Simulator()
        network = make_network(sim)
        sim._network = network

        sender = RecordingActor(ActorId("sender"), sim)
        receiver = RecordingActor(ActorId("receiver"), sim)
        sim.register_actor(sender)
        sim.register_actor(receiver)

        network.register_node(ActorId("sender"), Region.NA)
        network.register_node(ActorId("receiver"), Region.NA)

        # Send at time 0
        msg = SampleMessage(sender=ActorId("sender"), content="hello")
        sender.send(msg, to=ActorId("receiver"))

        sim.run_until_empty()

        # Message should arrive after some delay (NA-NA base is 20ms)
        arrival_time = receiver.received[0][0]
        assert arrival_time > 0.0
        assert arrival_time < 0.1  # Should be around 20ms + jitter + transmission

    def test_cross_region_higher_latency(self) -> None:
        """Cross-region messages have higher latency than same-region."""
        # Same-region test
        sim1 = Simulator(seed=42)
        network1 = make_network(sim1)
        sim1._network = network1

        sender1 = RecordingActor(ActorId("sender"), sim1)
        receiver1 = RecordingActor(ActorId("receiver"), sim1)
        sim1.register_actor(sender1)
        sim1.register_actor(receiver1)

        network1.register_node(ActorId("sender"), Region.NA)
        network1.register_node(ActorId("receiver"), Region.NA)

        sender1.send(
            SampleMessage(sender=ActorId("sender"), content="test"), to=ActorId("receiver")
        )
        sim1.run_until_empty()
        same_region_time = receiver1.received[0][0]

        # Cross-region test
        sim2 = Simulator(seed=42)
        network2 = make_network(sim2)
        sim2._network = network2

        sender2 = RecordingActor(ActorId("sender"), sim2)
        receiver2 = RecordingActor(ActorId("receiver"), sim2)
        sim2.register_actor(sender2)
        sim2.register_actor(receiver2)

        network2.register_node(ActorId("sender"), Region.NA)
        network2.register_node(ActorId("receiver"), Region.AS)  # Different region

        sender2.send(
            SampleMessage(sender=ActorId("sender"), content="test"), to=ActorId("receiver")
        )
        sim2.run_until_empty()
        cross_region_time = receiver2.received[0][0]

        # NA-AS (90ms base) should be much higher than NA-NA (20ms base)
        assert cross_region_time > same_region_time * 2

    def test_larger_messages_take_longer(self) -> None:
        """Larger messages take longer to transmit."""
        sim1 = Simulator(seed=42)
        network1 = make_network(sim1, default_bandwidth=1_000_000)  # 1 MB/s
        sim1._network = network1

        sender1 = RecordingActor(ActorId("sender"), sim1)
        receiver1 = RecordingActor(ActorId("receiver"), sim1)
        sim1.register_actor(sender1)
        sim1.register_actor(receiver1)
        network1.register_node(ActorId("sender"), Region.NA)
        network1.register_node(ActorId("receiver"), Region.NA)

        # Small message
        sender1.send(
            SampleMessage(sender=ActorId("sender"), content="small", _size=1000),
            to=ActorId("receiver"),
        )
        sim1.run_until_empty()
        small_time = receiver1.received[0][0]

        # Large message
        sim2 = Simulator(seed=42)
        network2 = make_network(sim2, default_bandwidth=1_000_000)
        sim2._network = network2

        sender2 = RecordingActor(ActorId("sender"), sim2)
        receiver2 = RecordingActor(ActorId("receiver"), sim2)
        sim2.register_actor(sender2)
        sim2.register_actor(receiver2)
        network2.register_node(ActorId("sender"), Region.NA)
        network2.register_node(ActorId("receiver"), Region.NA)

        sender2.send(
            SampleMessage(sender=ActorId("sender"), content="large", _size=100_000),
            to=ActorId("receiver"),
        )
        sim2.run_until_empty()
        large_time = receiver2.received[0][0]

        # 100KB at 1MB/s = 100ms extra transmission time
        assert large_time > small_time + 0.05

    def test_bandwidth_accounting(self) -> None:
        """Network tracks total bytes transmitted."""
        sim = Simulator()
        network = make_network(sim)
        sim._network = network

        sender = RecordingActor(ActorId("sender"), sim)
        receiver = RecordingActor(ActorId("receiver"), sim)
        sim.register_actor(sender)
        sim.register_actor(receiver)
        network.register_node(ActorId("sender"), Region.NA)
        network.register_node(ActorId("receiver"), Region.NA)

        sender.send(
            SampleMessage(sender=ActorId("sender"), content="msg1", _size=100),
            to=ActorId("receiver"),
        )
        sender.send(
            SampleMessage(sender=ActorId("sender"), content="msg2", _size=200),
            to=ActorId("receiver"),
        )

        sim.run_until_empty()

        assert network.messages_delivered == 2
        assert network.total_bytes == 300

    def test_custom_latency_matrix(self) -> None:
        """Custom latency matrix can be provided."""
        custom_matrix = {
            (Region.NA, Region.NA): LatencyParams(5.0, 0.0),  # Very fast, no jitter
        }

        sim = Simulator(seed=42)
        network = make_network(sim, latency_matrix=custom_matrix)
        sim._network = network

        sender = RecordingActor(ActorId("sender"), sim)
        receiver = RecordingActor(ActorId("receiver"), sim)
        sim.register_actor(sender)
        sim.register_actor(receiver)
        network.register_node(ActorId("sender"), Region.NA)
        network.register_node(ActorId("receiver"), Region.NA)

        # Very small message to minimize transmission time
        sender.send(
            SampleMessage(sender=ActorId("sender"), content="test", _size=1), to=ActorId("receiver")
        )
        sim.run_until_empty()

        # Should be very close to 5ms = 0.005s
        arrival_time = receiver.received[0][0]
        assert 0.004 < arrival_time < 0.006

    def test_unregistered_nodes_use_defaults(self) -> None:
        """Unregistered nodes default to NA region."""
        sim = Simulator()
        network = make_network(sim)
        sim._network = network

        sender = RecordingActor(ActorId("sender"), sim)
        receiver = RecordingActor(ActorId("receiver"), sim)
        sim.register_actor(sender)
        sim.register_actor(receiver)

        # Don't register nodes - should use NA defaults
        sender.send(SampleMessage(sender=ActorId("sender"), content="test"), to=ActorId("receiver"))
        sim.run_until_empty()

        # Should still work with default region
        assert len(receiver.received) == 1


class TestCoDelState:
    def test_default_values(self) -> None:
        """CoDelState initializes with zero values."""
        state = CoDelState()
        assert state.queue_bytes == 0.0
        assert state.queue_start_time == 0.0
        assert state.drop_count == 0
        assert state.last_drop_time == 0.0


class TestCoDelConfig:
    def test_default_values(self) -> None:
        """CoDelConfig has sensible defaults."""
        config = CoDelConfig()
        assert config.target_delay == 0.005  # 5ms
        assert config.interval == 0.100  # 100ms
        assert config.max_queue_bytes == 10 * 1024 * 1024  # 10 MB
        assert config.drain_rate == 100 * 1024 * 1024  # 100 MB/s

    def test_custom_values(self) -> None:
        """CoDelConfig accepts custom values."""
        config = CoDelConfig(
            target_delay=0.010,
            interval=0.200,
            max_queue_bytes=5 * 1024 * 1024,
            drain_rate=50 * 1024 * 1024,
        )
        assert config.target_delay == 0.010
        assert config.interval == 0.200


class TestCoDelBehavior:
    def test_codel_state_created_per_link(self) -> None:
        """CoDel state is created and tracked per link."""
        sim = Simulator()
        network = make_network(sim)
        sim._network = network

        # Get state for a link - creates new state
        state1 = network._get_codel_state(ActorId("a"), ActorId("b"))
        assert state1.queue_bytes == 0.0

        # Same link returns same state
        state2 = network._get_codel_state(ActorId("a"), ActorId("b"))
        assert state1 is state2

        # Different link returns different state
        state3 = network._get_codel_state(ActorId("a"), ActorId("c"))
        assert state1 is not state3

    def test_codel_adds_queue_delay(self) -> None:
        """CoDel adds delay when queue builds up."""
        sim = Simulator()
        # Use small drain rate to build queue
        codel_config = CoDelConfig(drain_rate=1000)  # 1 KB/s
        network = make_network(sim, codel_config=codel_config)
        sim._network = network

        # Calculate delay for a large message
        delay = network._codel_delay(ActorId("a"), ActorId("b"), 10000)

        # With 10KB at 1KB/s drain rate, sojourn should be ~10s
        assert delay > 1.0  # Should be significant

    def test_codel_queue_drains_over_time(self) -> None:
        """CoDel queue drains based on elapsed time."""
        sim = Simulator()
        codel_config = CoDelConfig(drain_rate=1000)  # 1 KB/s
        network = make_network(sim, codel_config=codel_config)
        sim._network = network

        # Add bytes to queue
        network._codel_delay(ActorId("a"), ActorId("b"), 1000)
        state = network._get_codel_state(ActorId("a"), ActorId("b"))
        initial_bytes = state.queue_bytes

        # Advance time by 0.5 seconds (should drain 500 bytes)
        sim._current_time = 0.5

        # Add more bytes - this triggers drain calculation
        network._codel_delay(ActorId("a"), ActorId("b"), 100)
        # Queue should be: initial - drained + new = 1000 - 500 + 100 = 600
        assert state.queue_bytes < initial_bytes

    def test_codel_respects_max_queue_size(self) -> None:
        """CoDel caps queue at max size."""
        sim = Simulator()
        codel_config = CoDelConfig(max_queue_bytes=1000, drain_rate=1)  # 1 KB max
        network = make_network(sim, codel_config=codel_config)
        sim._network = network

        # Try to add more than max
        network._codel_delay(ActorId("a"), ActorId("b"), 5000)
        state = network._get_codel_state(ActorId("a"), ActorId("b"))

        # Should be capped at max
        assert state.queue_bytes == 1000.0

    def test_congestion_increases_delay(self) -> None:
        """Sustained congestion increases delay via drop count."""
        sim = Simulator()
        # Configure for easy testing
        codel_config = CoDelConfig(
            target_delay=0.001,  # 1ms target
            interval=0.001,  # 1ms interval
            drain_rate=1000,  # 1 KB/s
        )
        network = make_network(sim, codel_config=codel_config)
        sim._network = network

        # First message - builds queue
        _ = network._codel_delay(ActorId("a"), ActorId("b"), 100)

        # Advance time past interval
        sim._current_time = 0.01

        # Second message - should trigger drop count increment
        _ = network._codel_delay(ActorId("a"), ActorId("b"), 100)

        # Advance time again
        sim._current_time = 0.02

        # Third message - more delays
        _ = network._codel_delay(ActorId("a"), ActorId("b"), 100)

        # Delays should generally increase with congestion
        # (exact values depend on queue state)
        state = network._get_codel_state(ActorId("a"), ActorId("b"))
        assert state.drop_count > 0  # Should have started counting
