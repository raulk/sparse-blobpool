"""Base classes for events and commands."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
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


class Command(ABC):
    """Base class for all local commands.

    Commands differ from Messages:
    - Commands are local events (timers, internal triggers)
    - Messages are network-transmitted protocol data
    """

    @property
    @abstractmethod
    def size_bytes(self) -> int:
        """Size is always 0 for commands (not transmitted)."""
        ...


# Union of all event payload types
EventPayload = Message | Command
