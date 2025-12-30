"""Base classes for adversary actors."""

from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ...core.actor import Actor, EventPayload, Message, TimerPayload

if TYPE_CHECKING:
    from ...core.simulator import Simulator
    from ...core.types import ActorId


@dataclass
class AttackConfig:
    start_time: float = 0.0
    duration: float | None = None  # None = run until simulation ends


class Adversary(Actor):
    """Base class for adversary actors.

    Adversaries control one or more malicious nodes in the network and can
    intercept, modify, or generate messages to execute attacks.
    """

    def __init__(
        self,
        actor_id: ActorId,
        simulator: Simulator,
        controlled_nodes: list[ActorId],
        attack_config: AttackConfig,
    ) -> None:
        super().__init__(actor_id, simulator)
        self._controlled_nodes = controlled_nodes
        self._attack_config = attack_config
        self._attack_started = False
        self._attack_stopped = False

    @property
    def controlled_nodes(self) -> list[ActorId]:
        return self._controlled_nodes

    @property
    def attack_config(self) -> AttackConfig:
        return self._attack_config

    def on_event(self, payload: EventPayload) -> None:
        match payload:
            case Message() as msg:
                self._on_message(msg)
            case TimerPayload() as timer:
                self._on_timer(timer)

    def _on_message(self, msg: Message) -> None:
        pass

    def _on_timer(self, timer: TimerPayload) -> None:
        pass

    @abstractmethod
    def execute(self) -> None:
        """Start the attack. Called when attack_config.start_time is reached."""
        ...

    def stop(self) -> None:
        self._attack_stopped = True
