"""Actor base class and event payloads."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import TYPE_CHECKING, Any, Union

from .types import NETWORK_ACTOR_ID, ActorId

if TYPE_CHECKING:
    from .simulator import Simulator


class TimerKind(Enum):
    """Types of timer events."""

    TX_EXPIRATION_CHECK = auto()
    PROVIDER_OBSERVATION_TIMEOUT = auto()
    RESAMPLING = auto()
    ANNOUNCEMENT_BATCH = auto()
    SLOT_TICK = auto()
    TX_CLEANUP = auto()
    REQUEST_TIMEOUT = auto()


@dataclass
class TimerPayload:
    """Payload for timer events."""

    kind: TimerKind
    context: dict[str, Any] = field(default_factory=dict)


@dataclass
class Message:
    """Base class for all protocol messages."""

    sender: ActorId

    @property
    def size_bytes(self) -> int:
        """Size of the message in bytes for bandwidth accounting."""
        return 8  # Base overhead


@dataclass
class SendRequest:
    """Request for Network actor to deliver a message."""

    msg: Message
    from_: ActorId
    to: ActorId


# Union of all event payload types
EventPayload = Union[Message, TimerPayload, SendRequest]  # noqa: UP007 -- runtime needed for 3.11


class Actor(ABC):
    """Base class for all simulation actors.

    Actors are stateful entities with a single entrypoint (on_event) that the
    Simulator invokes. Actors communicate via messages; the Network actor
    models transport delays.
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
        """Request message delivery via Network actor."""
        from .simulator import Event

        self._simulator.schedule(
            Event(
                timestamp=self._simulator.current_time,
                priority=0,
                target_id=NETWORK_ACTOR_ID,
                payload=SendRequest(msg=msg, from_=self._id, to=to),
            )
        )

    def schedule_timer(
        self, delay: float, kind: TimerKind, context: dict[str, Any] | None = None
    ) -> None:
        """Schedule a self-targeted timer."""
        from .simulator import Event

        self._simulator.schedule(
            Event(
                timestamp=self._simulator.current_time + delay,
                priority=1,  # Timers have lower priority than messages
                target_id=self._id,
                payload=TimerPayload(kind=kind, context=context or {}),
            )
        )
