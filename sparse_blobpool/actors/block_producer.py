"""BlockProducer actor for simulating block production."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sparse_blobpool.config import SimulationConfig
from sparse_blobpool.core.actor import Actor, EventPayload, TimerKind, TimerPayload
from sparse_blobpool.core.types import ActorId
from sparse_blobpool.protocol.commands import ProduceBlock

if TYPE_CHECKING:
    from sparse_blobpool.core.simulator import Simulator


BLOCK_PRODUCER_ID = ActorId("block-producer")


class BlockProducer(Actor):
    def __init__(
        self,
        simulator: Simulator,
        config: SimulationConfig | None = None,
    ) -> None:
        super().__init__(BLOCK_PRODUCER_ID, simulator)
        self._config = config or SimulationConfig()
        self._current_slot = 0

    @property
    def current_slot(self) -> int:
        return self._current_slot

    def start(self) -> None:
        self.schedule_timer(
            delay=self._config.slot_duration,
            kind=TimerKind.SLOT_TICK,
        )

    def on_event(self, payload: EventPayload) -> None:
        match payload:
            case TimerPayload(kind=TimerKind.SLOT_TICK):
                self._on_slot_tick()

    def _on_slot_tick(self) -> None:
        nodes = self._simulator.nodes
        if not nodes:
            self._advance_slot()
            return

        proposer = self._select_proposer(nodes)
        msg = ProduceBlock(sender=self._id, slot=self._current_slot)
        self.send(msg, proposer.id)

        self._advance_slot()

    def _select_proposer(self, nodes: list) -> object:
        return nodes[self._current_slot % len(nodes)]

    def _advance_slot(self) -> None:
        self._current_slot += 1
        self.schedule_timer(
            delay=self._config.slot_duration,
            kind=TimerKind.SLOT_TICK,
        )
