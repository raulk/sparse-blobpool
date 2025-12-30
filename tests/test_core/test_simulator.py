"""Tests for the discrete event simulator."""

from dataclasses import dataclass

import pytest

from sparse_blobpool.core.actor import Actor, Command, EventPayload
from sparse_blobpool.core.simulator import Event, Simulator
from sparse_blobpool.core.types import ActorId


@dataclass
class DummyCommand(Command):
    """Simple command for testing."""

    order: int = 0

    @property
    def size_bytes(self) -> int:
        return 0


class RecordingActor(Actor):
    """Test actor that records all received events."""

    def __init__(self, actor_id: ActorId, simulator: Simulator) -> None:
        super().__init__(actor_id, simulator)
        self.events: list[EventPayload] = []

    def on_event(self, payload: EventPayload) -> None:
        self.events.append(payload)


class TestEvent:
    def test_event_ordering_by_timestamp(self) -> None:
        """Events are ordered by timestamp first."""
        e1 = Event(
            timestamp=1.0,
            priority=0,
            target_id=ActorId("a"),
            payload=DummyCommand(),
        )
        e2 = Event(
            timestamp=2.0,
            priority=0,
            target_id=ActorId("a"),
            payload=DummyCommand(),
        )

        assert e1 < e2

    def test_event_ordering_by_priority(self) -> None:
        """Events with same timestamp are ordered by priority (lower first)."""
        e1 = Event(
            timestamp=1.0,
            priority=0,
            target_id=ActorId("a"),
            payload=DummyCommand(),
        )
        e2 = Event(
            timestamp=1.0,
            priority=1,
            target_id=ActorId("a"),
            payload=DummyCommand(),
        )

        assert e1 < e2

    def test_event_equality(self) -> None:
        """Events with same timestamp and priority are equal for ordering."""
        e1 = Event(
            timestamp=1.0,
            priority=0,
            target_id=ActorId("a"),
            payload=DummyCommand(),
        )
        e2 = Event(
            timestamp=1.0,
            priority=0,
            target_id=ActorId("b"),
            payload=DummyCommand(order=99),
        )

        # They compare equal because target_id and payload are not compared
        assert not (e1 < e2)
        assert not (e2 < e1)


class TestSimulator:
    def test_initial_state(self) -> None:
        """Simulator starts at time 0 with empty queue."""
        sim = Simulator(seed=42)

        assert sim.current_time == 0.0
        assert sim.pending_event_count() == 0
        assert sim.events_processed == 0

    def test_register_actor(self) -> None:
        """Actors can be registered with the simulator."""
        sim = Simulator()
        actor = RecordingActor(ActorId("test"), sim)
        sim.register_actor(actor)

        assert ActorId("test") in sim.actors
        assert sim.actors[ActorId("test")] is actor

    def test_register_duplicate_actor_raises(self) -> None:
        """Registering the same actor ID twice raises ValueError."""
        sim = Simulator()
        actor1 = RecordingActor(ActorId("test"), sim)
        actor2 = RecordingActor(ActorId("test"), sim)
        sim.register_actor(actor1)

        with pytest.raises(ValueError, match="already registered"):
            sim.register_actor(actor2)

    def test_schedule_event(self) -> None:
        """Events can be scheduled for future processing."""
        sim = Simulator()
        event = Event(
            timestamp=1.0,
            priority=0,
            target_id=ActorId("test"),
            payload=DummyCommand(),
        )
        sim.schedule(event)

        assert sim.pending_event_count() == 1

    def test_schedule_past_event_raises(self) -> None:
        """Cannot schedule events in the past."""
        sim = Simulator()
        actor = RecordingActor(ActorId("test"), sim)
        sim.register_actor(actor)

        # Advance time
        sim.schedule(
            Event(timestamp=1.0, target_id=ActorId("test"), payload=DummyCommand())
        )
        sim.run(until=2.0)

        # Try to schedule in the past
        with pytest.raises(ValueError, match="past"):
            sim.schedule(
                Event(
                    timestamp=0.5,
                    target_id=ActorId("test"),
                    payload=DummyCommand(),
                )
            )

    def test_run_processes_events_in_order(self) -> None:
        """Events are processed in timestamp order."""
        sim = Simulator()
        actor = RecordingActor(ActorId("test"), sim)
        sim.register_actor(actor)

        # Schedule events out of order
        sim.schedule(
            Event(
                timestamp=3.0,
                target_id=ActorId("test"),
                payload=DummyCommand(order=3),
            )
        )
        sim.schedule(
            Event(
                timestamp=1.0,
                target_id=ActorId("test"),
                payload=DummyCommand(order=1),
            )
        )
        sim.schedule(
            Event(
                timestamp=2.0,
                target_id=ActorId("test"),
                payload=DummyCommand(order=2),
            )
        )

        sim.run(until=10.0)

        assert len(actor.events) == 3
        assert actor.events[0].order == 1  # type: ignore[union-attr]
        assert actor.events[1].order == 2  # type: ignore[union-attr]
        assert actor.events[2].order == 3  # type: ignore[union-attr]

    def test_run_advances_time(self) -> None:
        """Simulation time advances as events are processed."""
        sim = Simulator()
        actor = RecordingActor(ActorId("test"), sim)
        sim.register_actor(actor)

        sim.schedule(
            Event(timestamp=5.0, target_id=ActorId("test"), payload=DummyCommand())
        )
        sim.run(until=10.0)

        assert sim.current_time == 5.0

    def test_run_respects_until_boundary(self) -> None:
        """Events beyond the until time are not processed."""
        sim = Simulator()
        actor = RecordingActor(ActorId("test"), sim)
        sim.register_actor(actor)

        sim.schedule(
            Event(timestamp=5.0, target_id=ActorId("test"), payload=DummyCommand())
        )
        sim.schedule(
            Event(timestamp=15.0, target_id=ActorId("test"), payload=DummyCommand())
        )

        sim.run(until=10.0)

        assert len(actor.events) == 1
        assert sim.pending_event_count() == 1  # The 15.0 event is still pending

    def test_run_until_empty(self) -> None:
        """run_until_empty processes all events regardless of time."""
        sim = Simulator()
        actor = RecordingActor(ActorId("test"), sim)
        sim.register_actor(actor)

        sim.schedule(
            Event(
                timestamp=100.0,
                target_id=ActorId("test"),
                payload=DummyCommand(),
            )
        )
        sim.schedule(
            Event(
                timestamp=200.0,
                target_id=ActorId("test"),
                payload=DummyCommand(),
            )
        )

        sim.run_until_empty()

        assert len(actor.events) == 2
        assert sim.current_time == 200.0
        assert sim.pending_event_count() == 0

    def test_deterministic_with_seed(self) -> None:
        """Simulator RNG is deterministic with the same seed."""
        sim1 = Simulator(seed=12345)
        sim2 = Simulator(seed=12345)

        values1 = [sim1.rng.random() for _ in range(10)]
        values2 = [sim2.rng.random() for _ in range(10)]

        assert values1 == values2

    def test_event_to_unknown_actor_raises(self) -> None:
        """Processing an event for an unknown actor raises RuntimeError."""
        sim = Simulator()
        sim.schedule(
            Event(
                timestamp=1.0,
                target_id=ActorId("unknown"),
                payload=DummyCommand(),
            )
        )

        with pytest.raises(RuntimeError, match="unknown actor"):
            sim.run(until=2.0)

    def test_actors_by_type(self) -> None:
        """actors_by_type filters actors by their class."""
        sim = Simulator()

        class TypeA(Actor):
            def on_event(self, payload: EventPayload) -> None:
                pass

        class TypeB(Actor):
            def on_event(self, payload: EventPayload) -> None:
                pass

        a1 = TypeA(ActorId("a1"), sim)
        a2 = TypeA(ActorId("a2"), sim)
        b1 = TypeB(ActorId("b1"), sim)
        sim.register_actor(a1)
        sim.register_actor(a2)
        sim.register_actor(b1)

        type_a_actors = sim.actors_by_type(TypeA)
        type_b_actors = sim.actors_by_type(TypeB)

        assert len(type_a_actors) == 2
        assert len(type_b_actors) == 1
        assert all(isinstance(a, TypeA) for a in type_a_actors)
        assert all(isinstance(b, TypeB) for b in type_b_actors)


class TestActorCommandScheduling:
    def test_schedule_command(self) -> None:
        """Actors can schedule commands for themselves."""
        sim = Simulator()

        @dataclass
        class DelayedCommand(Command):
            delayed: bool = False

            @property
            def size_bytes(self) -> int:
                return 0

        class CommandSchedulingActor(Actor):
            def __init__(self, actor_id: ActorId, simulator: Simulator) -> None:
                super().__init__(actor_id, simulator)
                self.received_delayed = False

            def on_event(self, payload: EventPayload) -> None:
                match payload:
                    case DummyCommand():
                        self.schedule_command(1.0, DelayedCommand(delayed=True))
                    case DelayedCommand(delayed=True):
                        self.received_delayed = True

        actor = CommandSchedulingActor(ActorId("test"), sim)
        sim.register_actor(actor)

        # Manually schedule initial event
        sim.schedule(
            Event(
                timestamp=0.0,
                target_id=ActorId("test"),
                payload=DummyCommand(),
            )
        )

        sim.run(until=0.5)
        assert sim.pending_event_count() == 1  # Command scheduled for 1.0
        assert not actor.received_delayed

        sim.run(until=2.0)
        assert sim.current_time == 1.0  # Command was processed
        assert actor.received_delayed
