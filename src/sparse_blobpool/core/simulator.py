"""Discrete event simulation engine."""

from __future__ import annotations

import heapq
from dataclasses import dataclass, field
from random import Random
from typing import TYPE_CHECKING, TypeVar

if TYPE_CHECKING:
    from .actor import Actor, EventPayload
    from .types import ActorId

ActorT = TypeVar("ActorT", bound="Actor")


@dataclass(order=True)
class Event:
    """A scheduled event in the simulation.

    Events are ordered by (timestamp, priority) for the priority queue.
    Lower priority values are processed first when timestamps are equal.
    """

    timestamp: float
    target_id: ActorId = field(compare=False)
    payload: EventPayload = field(compare=False)
    priority: int = 0


class Simulator:
    """Single-threaded, deterministic discrete event simulator.

    Uses a min-heap priority queue for event scheduling and processing.
    All randomness is derived from a seeded RNG for reproducibility.
    """

    def __init__(self, seed: int = 42) -> None:
        self._current_time: float = 0.0
        self._event_queue: list[Event] = []
        self._actors: dict[ActorId, Actor] = {}
        self._rng = Random(seed)
        self._events_processed: int = 0

    @property
    def current_time(self) -> float:
        return self._current_time

    @property
    def rng(self) -> Random:
        return self._rng

    @property
    def actors(self) -> dict[ActorId, Actor]:
        return self._actors

    def actors_by_type(self, actor_type: type[ActorT]) -> list[ActorT]:
        """Return all actors of a specific type.

        Uses generic type parameter to provide proper type hints for the
        returned list.
        """
        return [actor for actor in self._actors.values() if isinstance(actor, actor_type)]

    @property
    def events_processed(self) -> int:
        return self._events_processed

    def register_actor(self, actor: Actor) -> None:
        """Register an actor with the simulator."""
        if actor.id in self._actors:
            raise ValueError(f"Actor {actor.id} already registered")
        self._actors[actor.id] = actor

    def schedule(self, event: Event) -> None:
        """Schedule an event for future processing."""
        if event.timestamp < self._current_time:
            raise ValueError(
                f"Cannot schedule event in the past: {event.timestamp} < {self._current_time}"
            )
        heapq.heappush(self._event_queue, event)

    def run(self, until: float) -> None:
        """Run the simulation until the specified time.

        Processes events in timestamp order, advancing simulation time
        as each event is processed.
        """
        while self._event_queue and self._current_time < until:
            event = heapq.heappop(self._event_queue)

            # Don't process events beyond our target time
            if event.timestamp > until:
                # Put it back and stop
                heapq.heappush(self._event_queue, event)
                break

            self._current_time = event.timestamp

            if event.target_id not in self._actors:
                raise RuntimeError(f"Event targeted unknown actor: {event.target_id}")

            actor = self._actors[event.target_id]
            actor.on_event(event.payload)
            self._events_processed += 1

    def run_until_empty(self) -> None:
        """Run the simulation until the event queue is empty."""
        while self._event_queue:
            event = heapq.heappop(self._event_queue)
            self._current_time = event.timestamp

            if event.target_id not in self._actors:
                raise RuntimeError(f"Event targeted unknown actor: {event.target_id}")

            actor = self._actors[event.target_id]
            actor.on_event(event.payload)
            self._events_processed += 1

    def pending_event_count(self) -> int:
        """Return the number of pending events in the queue."""
        return len(self._event_queue)
