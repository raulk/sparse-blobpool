"""BlockProducer actor for simulating block production."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import TYPE_CHECKING

from .actor import Actor, EventPayload, TimerKind, TimerPayload
from .types import ActorId

if TYPE_CHECKING:
    from ..p2p.node import Node
    from ..pool.blobpool import BlobTxEntry
    from .simulator import Simulator


BLOCK_PRODUCER_ID = ActorId("block-producer")


class InclusionPolicy(Enum):
    """Policies for selecting which transactions to include in blocks."""

    CONSERVATIVE = auto()  # Only include if full blob held locally
    OPTIMISTIC = auto()  # Include if available (any cells)
    PROACTIVE = auto()  # Would trigger resampling first (not implemented)


@dataclass
class SlotConfig:
    """Configuration for block production timing."""

    slot_duration: float = 12.0  # seconds per slot
    max_blobs_per_block: int = 6  # maximum blob count per block


class BlockProducer(Actor):
    """Actor that produces blocks at regular slot intervals.

    Simulates the Ethereum beacon chain block production process. At each slot,
    selects a proposer from the registered nodes and builds a block containing
    blob transactions from that node's blobpool.
    """

    def __init__(
        self,
        simulator: Simulator,
        slot_config: SlotConfig | None = None,
        inclusion_policy: InclusionPolicy = InclusionPolicy.CONSERVATIVE,
    ) -> None:
        super().__init__(BLOCK_PRODUCER_ID, simulator)
        self._slot_config = slot_config or SlotConfig()
        self._inclusion_policy = inclusion_policy
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
        """Register a node that can be selected as block proposer."""
        if node_id not in self._node_ids:
            self._node_ids.append(node_id)

    def register_nodes(self, node_ids: list[ActorId]) -> None:
        """Register multiple nodes as potential block proposers."""
        for node_id in node_ids:
            self.register_node(node_id)

    def start(self) -> None:
        """Start block production by scheduling the first slot tick."""
        self.schedule_timer(
            delay=self._slot_config.slot_duration,
            kind=TimerKind.SLOT_TICK,
        )

    def on_event(self, payload: EventPayload) -> None:
        """Handle slot tick events."""
        match payload:
            case TimerPayload(kind=TimerKind.SLOT_TICK):
                self._produce_block()

    def _produce_block(self) -> None:
        """Produce a block for the current slot."""
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
        """Select the proposer for the current slot using round-robin."""
        return self._node_ids[self._current_slot % len(self._node_ids)]

    def _get_node(self, node_id: ActorId) -> Node | None:
        """Get a Node actor by ID."""
        from ..p2p.node import Node

        actor = self._simulator.actors.get(node_id)
        if isinstance(actor, Node):
            return actor
        return None

    def _select_blobs(self, proposer: Node) -> list[BlobTxEntry]:
        """Select blob transactions from proposer's blobpool.

        Transactions are sorted by effective tip (priority fee) and selected
        greedily until the blob limit is reached.
        """
        candidates = [tx for tx in proposer.pool.iter_by_priority() if self._is_includable(tx)]

        selected: list[BlobTxEntry] = []
        blob_count = 0

        for tx in candidates:
            if blob_count + tx.blob_count <= self._slot_config.max_blobs_per_block:
                selected.append(tx)
                blob_count += tx.blob_count

        return selected

    def _is_includable(self, tx: BlobTxEntry) -> bool:
        """Check if a transaction is includable based on inclusion policy."""
        match self._inclusion_policy:
            case InclusionPolicy.CONSERVATIVE:
                return tx.has_full_availability
            case InclusionPolicy.OPTIMISTIC:
                return tx.available_column_count() > 0
            case InclusionPolicy.PROACTIVE:
                # Proactive would trigger resampling - not implemented
                return tx.has_full_availability

    def _broadcast_block(self, proposer_id: ActorId, included_txs: list[BlobTxEntry]) -> None:
        """Broadcast block announcement to all nodes."""
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
        """Advance to the next slot and schedule the next tick."""
        self._current_slot += 1
        self.schedule_timer(
            delay=self._slot_config.slot_duration,
            kind=TimerKind.SLOT_TICK,
        )
