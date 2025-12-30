"""Discrete event simulation engine."""

from __future__ import annotations

import heapq
from dataclasses import dataclass, field
from random import Random
from typing import TYPE_CHECKING, TypeVar

from .actor import SendRequest
from .types import NETWORK_ACTOR_ID

if TYPE_CHECKING:
    from ..metrics.collector import MetricsCollector
    from ..metrics.results import SimulationResults
    from ..p2p.node import Node
    from ..p2p.topology import TopologyResult
    from .actor import Actor, EventPayload
    from .block_producer import BlockProducer
    from .network import Network
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

        self._network: Network | None = None
        self._block_producer: BlockProducer | None = None
        self._topology: TopologyResult | None = None
        self._metrics: MetricsCollector | None = None

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
        return [actor for actor in self._actors.values() if isinstance(actor, actor_type)]

    @property
    def events_processed(self) -> int:
        return self._events_processed

    @property
    def nodes(self) -> list[Node]:
        """Return all Node actors registered with this simulator."""
        from ..actors.honest import Node

        return [actor for actor in self._actors.values() if isinstance(actor, Node)]

    @property
    def network(self) -> Network:
        if self._network is None:
            raise RuntimeError("Simulator not configured with network")
        return self._network

    @property
    def block_producer(self) -> BlockProducer:
        if self._block_producer is None:
            raise RuntimeError("Simulator not configured with block_producer")
        return self._block_producer

    @property
    def topology(self) -> TopologyResult:
        if self._topology is None:
            raise RuntimeError("Simulator not configured with topology")
        return self._topology

    @property
    def metrics(self) -> MetricsCollector:
        if self._metrics is None:
            raise RuntimeError("Simulator not configured with metrics")
        return self._metrics

    def finalize_metrics(self) -> SimulationResults:
        return self.metrics.finalize()

    def register_actor(self, actor: Actor) -> None:
        if actor.id in self._actors:
            raise ValueError(f"Actor {actor.id} already registered")
        self._actors[actor.id] = actor

    def schedule(self, event: Event) -> None:
        if event.timestamp < self._current_time:
            raise ValueError(
                f"Cannot schedule event in the past: {event.timestamp} < {self._current_time}"
            )
        heapq.heappush(self._event_queue, event)

    def run(self, until: float) -> None:
        """Processes events in timestamp order up to the specified time."""
        while self._event_queue and self._current_time < until:
            event = heapq.heappop(self._event_queue)

            # Don't process events beyond our target time
            if event.timestamp > until:
                # Put it back and stop
                heapq.heappush(self._event_queue, event)
                break

            self._current_time = event.timestamp
            self._dispatch_event(event)
            self._events_processed += 1

    def run_until_empty(self) -> None:
        while self._event_queue:
            event = heapq.heappop(self._event_queue)
            self._current_time = event.timestamp
            self._dispatch_event(event)
            self._events_processed += 1

    def _dispatch_event(self, event: Event) -> None:
        if event.target_id == NETWORK_ACTOR_ID:
            if self._network is None:
                raise RuntimeError("Network not configured")
            if not isinstance(event.payload, SendRequest):
                raise RuntimeError(f"Network received non-SendRequest: {type(event.payload)}")
            self._network.handle_send_request(event.payload)
        else:
            if event.target_id not in self._actors:
                raise RuntimeError(f"Event targeted unknown actor: {event.target_id}")
            actor = self._actors[event.target_id]
            actor.on_event(event.payload)

    def pending_event_count(self) -> int:
        return len(self._event_queue)
