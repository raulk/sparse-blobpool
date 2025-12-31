"""Actor base class and event payloads."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from sparse_blobpool.core.events import Command, Event, EventPayload, Message

if TYPE_CHECKING:
    from sparse_blobpool.core.simulator import Simulator
    from sparse_blobpool.core.types import ActorId

# Re-export for backwards compatibility
__all__ = ["Actor", "Command", "Event", "EventPayload", "Message"]


class Actor(ABC):
    """Base class for all simulation actors.

    Actors are stateful entities with a single entrypoint (on_event) that the
    Simulator invokes. Actors communicate via messages delivered through the
    Network component.
    """

    def __init__(self, actor_id: ActorId, simulator: Simulator) -> None:
        self._id = actor_id
        self._simulator = simulator

    @property
    def id(self) -> ActorId:
        return self._id

    @property
    def simulator(self) -> Simulator:
        return self._simulator

    @abstractmethod
    def on_event(self, payload: EventPayload) -> None:
        """Single entrypoint for all events. Dispatch based on payload type."""
        ...

    def send(self, msg: Message, to: ActorId) -> None:
        """Send a message to another actor via the network."""
        self._simulator.network.deliver(msg, self._id, to)

    def schedule_command(self, delay: float, command: Command) -> None:
        """Schedule a self-targeted command after a delay."""
        self._simulator.schedule(
            Event(
                timestamp=self._simulator.current_time + delay,
                priority=1,  # Commands have lower priority than messages
                target_id=self._id,
                payload=command,
            )
        )
