"""Base classes for events and commands."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sparse_blobpool.core.types import ActorId


@dataclass
class Message:
    """Base class for all protocol messages transmitted over the network."""

    sender: ActorId

    @property
    def size_bytes(self) -> int:
        """Size of the message in bytes for bandwidth accounting."""
        return 8  # Base overhead


@dataclass
class Command:
    """Base class for all local commands.

    Commands differ from Messages:
    - Commands are local events (timers, internal triggers)
    - Messages are network-transmitted protocol data
    """


EventPayload = Message | Command


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
    sequence: int = 0
