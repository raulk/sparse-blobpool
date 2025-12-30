"""BlockProducer actor for simulating block production."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..config import InclusionPolicy, SimulationConfig
from ..core.actor import Actor, EventPayload, TimerKind, TimerPayload
from ..core.types import ActorId

if TYPE_CHECKING:
    from ..core.simulator import Simulator
    from ..pool.blobpool import BlobTxEntry
    from .honest import Node


BLOCK_PRODUCER_ID = ActorId("block-producer")


class BlockProducer(Actor):
    """Actor that produces blocks at regular slot intervals.

    Simulates the Ethereum beacon chain block production process. At each slot,
    selects a proposer from the registered nodes and builds a block containing
    blob transactions from that node's blobpool.
    """

    def __init__(
        self,
        simulator: Simulator,
        config: SimulationConfig | None = None,
    ) -> None:
        super().__init__(BLOCK_PRODUCER_ID, simulator)
        self._config = config or SimulationConfig()
        self._current_slot = 0
        self._node_ids: list[ActorId] = []
        self._blocks_produced = 0
        self._total_blobs_included = 0

    @property
    def current_slot(self) -> int:
        return self._current_slot

    @property
    def blocks_produced(self) -> int:
        return self._blocks_produced

    @property
    def total_blobs_included(self) -> int:
        return self._total_blobs_included

    def register_node(self, node_id: ActorId) -> None:
        if node_id not in self._node_ids:
            self._node_ids.append(node_id)

    def register_nodes(self, node_ids: list[ActorId]) -> None:
        for node_id in node_ids:
            self.register_node(node_id)

    def start(self) -> None:
        self.schedule_timer(
            delay=self._config.slot_duration,
            kind=TimerKind.SLOT_TICK,
        )

    def on_event(self, payload: EventPayload) -> None:
        match payload:
            case TimerPayload(kind=TimerKind.SLOT_TICK):
                self._produce_block()

    def _produce_block(self) -> None:
        if not self._node_ids:
            self._advance_slot()
            return

        proposer_id = self._select_proposer()
        proposer = self._get_node(proposer_id)

        if proposer is None:
            self._advance_slot()
            return

        selected_txs = self._select_blobs(proposer)

        if selected_txs:
            self._broadcast_block(proposer_id, selected_txs)

        self._advance_slot()

    def _select_proposer(self) -> ActorId:
        return self._node_ids[self._current_slot % len(self._node_ids)]

    def _get_node(self, node_id: ActorId) -> Node | None:
        from .honest import Node

        actor = self._simulator.actors.get(node_id)
        if isinstance(actor, Node):
            return actor
        return None

    def _select_blobs(self, proposer: Node) -> list[BlobTxEntry]:
        """Select txs by effective tip until blob limit is reached."""
        candidates = [tx for tx in proposer.pool.iter_by_priority() if self._is_includable(tx)]

        selected: list[BlobTxEntry] = []
        blob_count = 0

        for tx in candidates:
            if blob_count + tx.blob_count <= self._config.max_blobs_per_block:
                selected.append(tx)
                blob_count += tx.blob_count

        return selected

    def _is_includable(self, tx: BlobTxEntry) -> bool:
        match self._config.inclusion_policy:
            case InclusionPolicy.CONSERVATIVE:
                return tx.has_full_availability
            case InclusionPolicy.OPTIMISTIC:
                return tx.available_column_count() > 0
            case InclusionPolicy.PROACTIVE:
                # Proactive would trigger resampling - not implemented
                return tx.has_full_availability

    def _broadcast_block(self, proposer_id: ActorId, included_txs: list[BlobTxEntry]) -> None:
        from ..protocol.messages import Block, BlockAnnouncement

        block = Block(
            slot=self._current_slot,
            proposer=proposer_id,
            blob_tx_hashes=[tx.tx_hash for tx in included_txs],
        )

        announcement = BlockAnnouncement(sender=self._id, block=block)

        for node_id in self._node_ids:
            self.send(announcement, node_id)

        self._blocks_produced += 1
        self._total_blobs_included += sum(tx.blob_count for tx in included_txs)

    def _advance_slot(self) -> None:
        self._current_slot += 1
        self.schedule_timer(
            delay=self._config.slot_duration,
            kind=TimerKind.SLOT_TICK,
        )
