"""Tests for the Network actor and latency model."""

from dataclasses import dataclass

from sparse_blobpool.config import Region
from sparse_blobpool.core.actor import Actor, EventPayload, Message
from sparse_blobpool.core.network import LATENCY_DEFAULTS, LatencyParams, Network
from sparse_blobpool.core.simulator import Simulator
from sparse_blobpool.core.types import ActorId


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
        """Network actor can be created and registered."""
        sim = Simulator()
        network = Network(sim)
        sim.register_actor(network)

        assert network.id == ActorId("network")
        assert network.messages_delivered == 0
        assert network.total_bytes == 0

    def test_message_delivery(self) -> None:
        """Messages are delivered to target actors."""
        sim = Simulator()
        network = Network(sim)
        sim.register_actor(network)

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
        network = Network(sim)
        sim.register_actor(network)

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
        network1 = Network(sim1)
        sim1.register_actor(network1)

        sender1 = RecordingActor(ActorId("sender"), sim1)
        receiver1 = RecordingActor(ActorId("receiver"), sim1)
        sim1.register_actor(sender1)
        sim1.register_actor(receiver1)

        network1.register_node(ActorId("sender"), Region.NA)
        network1.register_node(ActorId("receiver"), Region.NA)

        sender1.send(SampleMessage(sender=ActorId("sender"), content="test"), to=ActorId("receiver"))
        sim1.run_until_empty()
        same_region_time = receiver1.received[0][0]

        # Cross-region test
        sim2 = Simulator(seed=42)
        network2 = Network(sim2)
        sim2.register_actor(network2)

        sender2 = RecordingActor(ActorId("sender"), sim2)
        receiver2 = RecordingActor(ActorId("receiver"), sim2)
        sim2.register_actor(sender2)
        sim2.register_actor(receiver2)

        network2.register_node(ActorId("sender"), Region.NA)
        network2.register_node(ActorId("receiver"), Region.AS)  # Different region

        sender2.send(SampleMessage(sender=ActorId("sender"), content="test"), to=ActorId("receiver"))
        sim2.run_until_empty()
        cross_region_time = receiver2.received[0][0]

        # NA-AS (90ms base) should be much higher than NA-NA (20ms base)
        assert cross_region_time > same_region_time * 2

    def test_larger_messages_take_longer(self) -> None:
        """Larger messages take longer to transmit."""
        sim1 = Simulator(seed=42)
        network1 = Network(sim1, default_bandwidth=1_000_000)  # 1 MB/s
        sim1.register_actor(network1)

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
        network2 = Network(sim2, default_bandwidth=1_000_000)
        sim2.register_actor(network2)

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
        network = Network(sim)
        sim.register_actor(network)

        sender = RecordingActor(ActorId("sender"), sim)
        receiver = RecordingActor(ActorId("receiver"), sim)
        sim.register_actor(sender)
        sim.register_actor(receiver)
        network.register_node(ActorId("sender"), Region.NA)
        network.register_node(ActorId("receiver"), Region.NA)

        sender.send(
            SampleMessage(sender=ActorId("sender"), content="msg1", _size=100), to=ActorId("receiver")
        )
        sender.send(
            SampleMessage(sender=ActorId("sender"), content="msg2", _size=200), to=ActorId("receiver")
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
        network = Network(sim, latency_matrix=custom_matrix)
        sim.register_actor(network)

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
        network = Network(sim)
        sim.register_actor(network)

        sender = RecordingActor(ActorId("sender"), sim)
        receiver = RecordingActor(ActorId("receiver"), sim)
        sim.register_actor(sender)
        sim.register_actor(receiver)

        # Don't register nodes - should use NA defaults
        sender.send(SampleMessage(sender=ActorId("sender"), content="test"), to=ActorId("receiver"))
        sim.run_until_empty()

        # Should still work with default region
        assert len(receiver.received) == 1
