"""Node actor implementing eth/71 sparse blobpool protocol."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from hashlib import sha256
from typing import TYPE_CHECKING

from ..core.actor import Actor, EventPayload, Message, TimerKind, TimerPayload
from ..pool.blobpool import Blobpool, BlobTxEntry, PoolFull, RBFRejected, SenderLimitExceeded
from ..protocol.constants import ALL_ONES
from ..protocol.messages import (
    BlockAnnouncement,
    BroadcastTransaction,
    Cells,
    GetCells,
    GetPooledTransactions,
    NewPooledTransactionHashes,
    PooledTransactions,
)

if TYPE_CHECKING:
    from ..config import SimulationConfig
    from ..core.simulator import Simulator
    from ..core.types import ActorId, RequestId, TxHash
    from ..metrics.collector import MetricsCollector


class Role(Enum):
    """Node's role for a specific transaction."""

    PROVIDER = auto()  # Fetch and store full blob payload
    SAMPLER = auto()  # Sample custody-aligned cells only


class TxState(Enum):
    """State of a transaction being processed."""

    ANNOUNCED = auto()  # Received announcement, awaiting decision
    AWAITING_PROVIDERS = auto()  # Sampler waiting for provider announcements
    FETCHING_TX = auto()  # Requesting transaction body
    FETCHING_CELLS = auto()  # Requesting cells
    COMPLETE = auto()  # All data received


@dataclass
class PendingTx:
    """Tracks state for a transaction being fetched."""

    tx_hash: TxHash
    role: Role
    state: TxState
    provider_peers: set[ActorId] = field(default_factory=set)
    sampler_peers: set[ActorId] = field(default_factory=set)
    tx_body_received: bool = False
    cells_received: int = 0  # bitmap of received columns
    pending_request_id: RequestId | None = None
    first_seen: float = 0.0


@dataclass
class PendingRequest:
    """Tracks an outstanding request."""

    request_id: RequestId
    tx_hash: TxHash
    target_peer: ActorId
    request_type: str  # "tx" or "cells"
    sent_at: float


class Node(Actor):
    """Node actor implementing the eth/71 sparse blobpool protocol.

    Each node maintains a local blobpool and processes incoming announcements
    by probabilistically deciding to act as a provider (fetch full blob) or
    sampler (fetch custody-aligned cells only).
    """

    def __init__(
        self,
        actor_id: ActorId,
        simulator: Simulator,
        config: SimulationConfig,
        custody_columns: int,
        metrics: MetricsCollector | None = None,
    ) -> None:
        super().__init__(actor_id, simulator)
        self._config = config
        self._pool = Blobpool(config)
        self._custody_columns = custody_columns
        self._metrics = metrics

        # Peer connections
        self._peers: set[ActorId] = set()

        # Transaction processing state
        self._pending_txs: dict[TxHash, PendingTx] = {}
        self._pending_requests: dict[RequestId, PendingRequest] = {}
        self._next_request_id: int = 0

        # Custody column assignment (deterministic from node ID)
        self._custody_mask = self._compute_custody_mask()

    @property
    def pool(self) -> Blobpool:
        return self._pool

    @property
    def peers(self) -> set[ActorId]:
        return self._peers

    def add_peer(self, peer_id: ActorId) -> None:
        """Add a peer connection."""
        self._peers.add(peer_id)

    def remove_peer(self, peer_id: ActorId) -> None:
        """Remove a peer connection."""
        self._peers.discard(peer_id)

    def on_event(self, payload: EventPayload) -> None:
        """Dispatch events to appropriate handlers."""
        match payload:
            case BroadcastTransaction() as msg:
                self._handle_broadcast_transaction(msg)
            case NewPooledTransactionHashes() as msg:
                self._handle_announcement(msg)
            case GetPooledTransactions() as msg:
                self._handle_get_transactions(msg)
            case PooledTransactions() as msg:
                self._handle_transactions(msg)
            case GetCells() as msg:
                self._handle_get_cells(msg)
            case Cells() as msg:
                self._handle_cells(msg)
            case BlockAnnouncement() as msg:
                self._handle_block_announcement(msg)
            case TimerPayload(kind=TimerKind.REQUEST_TIMEOUT, context=ctx):
                self._handle_request_timeout(ctx)
            case TimerPayload(kind=TimerKind.PROVIDER_OBSERVATION_TIMEOUT, context=ctx):
                self._handle_provider_observation_timeout(ctx)
            case TimerPayload(kind=TimerKind.TX_CLEANUP, context=ctx):
                self._handle_tx_cleanup(ctx)
            case Message():
                pass  # Unknown message type

    def _handle_broadcast_transaction(self, msg: BroadcastTransaction) -> None:
        """Handle a local broadcast transaction event.

        Creates a pool entry for the transaction and announces to all peers.
        Used for injecting transactions into the simulation.
        """
        entry = BlobTxEntry(
            tx_hash=msg.tx_hash,
            sender=msg.tx_sender,
            nonce=msg.nonce,
            gas_fee_cap=msg.gas_fee_cap,
            gas_tip_cap=msg.gas_tip_cap,
            blob_gas_price=msg.blob_gas_price,
            tx_size=msg.tx_size,
            blob_count=msg.blob_count,
            cell_mask=msg.cell_mask,
            received_at=self._simulator.current_time,
        )

        try:
            self._pool.add(entry)

            # Record metrics - origin node is always a provider with full blob
            if self._metrics is not None:
                self._metrics.record_tx_seen(self._id, msg.tx_hash, Role.PROVIDER, msg.cell_mask)

            self._announce_tx(entry)
        except (RBFRejected, SenderLimitExceeded, PoolFull):
            pass  # Transaction rejected

    def _determine_role(self, tx_hash: TxHash) -> Role:
        """Determine role for a transaction using hash-based probability.

        Uses a deterministic hash of (node_id, tx_hash) to decide role.
        This ensures consistent role assignment if the same tx is seen again.
        """
        combined = f"{self._id}:{tx_hash}".encode()
        hash_bytes = sha256(combined).digest()
        # Use first 8 bytes as a float in [0, 1)
        hash_int = int.from_bytes(hash_bytes[:8], "big")
        probability = hash_int / (2**64)

        if probability < self._config.provider_probability:
            return Role.PROVIDER
        return Role.SAMPLER

    def _compute_custody_mask(self) -> int:
        """Compute custody column mask from node ID.

        Deterministically assigns custody_columns columns based on node ID hash.
        """
        hash_bytes = sha256(self._id.encode()).digest()
        # Use hash to seed column selection
        seed = int.from_bytes(hash_bytes[:8], "big")
        rng = self._simulator.rng.__class__(seed)

        columns = set[int]()
        while len(columns) < self._custody_columns:
            col = rng.randint(0, 127)
            columns.add(col)

        mask = 0
        for col in columns:
            mask |= 1 << col
        return mask

    def _handle_announcement(self, msg: NewPooledTransactionHashes) -> None:
        """Process a NewPooledTransactionHashes announcement."""
        sender = msg.sender

        for i, tx_hash in enumerate(msg.hashes):
            tx_type = msg.types[i] if i < len(msg.types) else 0

            # Skip non-blob transactions
            if tx_type != 3:
                continue

            # Skip if already in pool
            if self._pool.contains(tx_hash):
                continue

            # Check if we're already processing this tx
            if tx_hash in self._pending_txs:
                pending = self._pending_txs[tx_hash]
                # Record peer based on their availability
                if msg.cell_mask == ALL_ONES:
                    pending.provider_peers.add(sender)
                else:
                    pending.sampler_peers.add(sender)

                # If sampler awaiting providers and we now have enough, proceed
                if (
                    pending.state == TxState.AWAITING_PROVIDERS
                    and len(pending.provider_peers) >= self._config.min_providers_before_sample
                ):
                    self._start_sampler_fetch(tx_hash)
                continue

            # New transaction - determine our role
            role = self._determine_role(tx_hash)

            pending = PendingTx(
                tx_hash=tx_hash,
                role=role,
                state=TxState.ANNOUNCED,
                first_seen=self._simulator.current_time,
            )

            # Track announcing peer
            if msg.cell_mask == ALL_ONES:
                pending.provider_peers.add(sender)
            else:
                pending.sampler_peers.add(sender)

            self._pending_txs[tx_hash] = pending

            if role == Role.PROVIDER:
                # Provider: fetch full blob immediately from a provider peer
                if msg.cell_mask == ALL_ONES:
                    self._start_provider_fetch(tx_hash, sender)
                else:
                    # Need to wait for a provider announcement
                    pending.state = TxState.AWAITING_PROVIDERS
                    self._schedule_provider_observation_timeout(tx_hash)
            else:
                # Sampler: wait for min_providers_before_sample provider announcements
                if len(pending.provider_peers) >= self._config.min_providers_before_sample:
                    self._start_sampler_fetch(tx_hash)
                else:
                    pending.state = TxState.AWAITING_PROVIDERS
                    self._schedule_provider_observation_timeout(tx_hash)

    def _start_provider_fetch(self, tx_hash: TxHash, from_peer: ActorId) -> None:
        """Start fetching full transaction and blob data as provider."""
        pending = self._pending_txs.get(tx_hash)
        if pending is None:
            return

        pending.state = TxState.FETCHING_TX

        # Request transaction body
        request_id = self._allocate_request_id()
        self._send_get_transactions(tx_hash, from_peer, request_id)

    def _start_sampler_fetch(self, tx_hash: TxHash) -> None:
        """Start fetching transaction and custody cells as sampler."""
        pending = self._pending_txs.get(tx_hash)
        if pending is None:
            return

        pending.state = TxState.FETCHING_TX

        # Pick a provider peer to request from
        if pending.provider_peers:
            target = next(iter(pending.provider_peers))
        elif pending.sampler_peers:
            target = next(iter(pending.sampler_peers))
        else:
            return  # No peers to request from

        request_id = self._allocate_request_id()
        self._send_get_transactions(tx_hash, target, request_id)

    def _send_get_transactions(
        self, tx_hash: TxHash, to_peer: ActorId, request_id: RequestId
    ) -> None:
        """Send GetPooledTransactions request."""
        pending = self._pending_txs.get(tx_hash)
        if pending is None:
            return

        pending.pending_request_id = request_id
        self._pending_requests[request_id] = PendingRequest(
            request_id=request_id,
            tx_hash=tx_hash,
            target_peer=to_peer,
            request_type="tx",
            sent_at=self._simulator.current_time,
        )

        msg = GetPooledTransactions(sender=self._id, tx_hashes=[tx_hash])
        self.send(msg, to_peer)
        self._schedule_request_timeout(request_id)

    def _handle_get_transactions(self, msg: GetPooledTransactions) -> None:
        """Handle incoming GetPooledTransactions request."""
        from ..protocol.messages import PooledTransactions, TxBody

        transactions: list[TxBody | None] = []

        for tx_hash in msg.tx_hashes:
            entry = self._pool.get(tx_hash)
            if entry is not None:
                transactions.append(TxBody(tx_hash=entry.tx_hash, tx_bytes=entry.tx_size))
            else:
                transactions.append(None)

        response = PooledTransactions(sender=self._id, transactions=transactions)
        self.send(response, msg.sender)

    def _handle_transactions(self, msg: PooledTransactions) -> None:
        """Handle PooledTransactions response."""
        for tx_body in msg.transactions:
            if tx_body is None:
                continue

            tx_hash = tx_body.tx_hash
            pending = self._pending_txs.get(tx_hash)
            if pending is None:
                continue

            # Clear pending request
            if pending.pending_request_id is not None:
                self._pending_requests.pop(pending.pending_request_id, None)
                pending.pending_request_id = None

            pending.tx_body_received = True

            # Now fetch cells
            if pending.role == Role.PROVIDER:
                self._request_all_cells(tx_hash, msg.sender)
            else:
                self._request_custody_cells(tx_hash, msg.sender)

    def _request_all_cells(self, tx_hash: TxHash, from_peer: ActorId) -> None:
        """Request all cells (provider role)."""
        pending = self._pending_txs.get(tx_hash)
        if pending is None:
            return

        pending.state = TxState.FETCHING_CELLS
        request_id = self._allocate_request_id()

        pending.pending_request_id = request_id
        self._pending_requests[request_id] = PendingRequest(
            request_id=request_id,
            tx_hash=tx_hash,
            target_peer=from_peer,
            request_type="cells",
            sent_at=self._simulator.current_time,
        )

        msg = GetCells(sender=self._id, tx_hashes=[tx_hash], cell_mask=ALL_ONES)
        self.send(msg, from_peer)
        self._schedule_request_timeout(request_id)

    def _request_custody_cells(self, tx_hash: TxHash, from_peer: ActorId) -> None:
        """Request custody-aligned cells plus extra random columns (sampler role)."""
        pending = self._pending_txs.get(tx_hash)
        if pending is None:
            return

        pending.state = TxState.FETCHING_CELLS
        request_id = self._allocate_request_id()

        # Add C_extra random columns to custody mask
        extra_columns = self._select_extra_columns(pending.provider_peers)
        request_mask = self._custody_mask | extra_columns

        pending.pending_request_id = request_id
        self._pending_requests[request_id] = PendingRequest(
            request_id=request_id,
            tx_hash=tx_hash,
            target_peer=from_peer,
            request_type="cells",
            sent_at=self._simulator.current_time,
        )

        msg = GetCells(sender=self._id, tx_hashes=[tx_hash], cell_mask=request_mask)
        self.send(msg, from_peer)
        self._schedule_request_timeout(request_id)

    def _select_extra_columns(self, provider_peers: set[ActorId]) -> int:
        """Select C_extra random columns not in custody set."""
        extra_mask = 0
        available_cols = [i for i in range(128) if not (self._custody_mask & (1 << i))]

        if available_cols:
            # Select C_extra random columns
            count = min(self._config.extra_random_columns, len(available_cols))
            selected = self._simulator.rng.sample(available_cols, count)
            for col in selected:
                extra_mask |= 1 << col

        return extra_mask

    def _handle_get_cells(self, msg: GetCells) -> None:
        """Handle incoming GetCells request."""
        from ..protocol.messages import Cell, Cells

        cells_response: list[list[Cell | None]] = []

        for tx_hash in msg.tx_hashes:
            entry = self._pool.get(tx_hash)
            if entry is None:
                cells_response.append([])
                continue

            # Return cells we have that match the request mask
            available_mask = entry.cell_mask & msg.cell_mask
            tx_cells: list[Cell | None] = []

            for col in range(128):
                if available_mask & (1 << col):
                    # We have this cell - create dummy cell data
                    tx_cells.append(Cell(data=b"\x00" * 2048, proof=b"\x00" * 48))
                elif msg.cell_mask & (1 << col):
                    tx_cells.append(None)  # Requested but we don't have it

            cells_response.append(tx_cells)

        # Compute actual mask of what we're providing
        provided_mask = 0
        for tx_hash, _entry_cells in zip(msg.tx_hashes, cells_response, strict=False):
            entry = self._pool.get(tx_hash)
            if entry:
                provided_mask |= entry.cell_mask & msg.cell_mask

        response = Cells(
            sender=self._id,
            tx_hashes=msg.tx_hashes,
            cells=cells_response,
            cell_mask=provided_mask,
        )
        self.send(response, msg.sender)

    def _handle_cells(self, msg: Cells) -> None:
        """Handle Cells response."""
        for tx_hash in msg.tx_hashes:
            pending = self._pending_txs.get(tx_hash)
            if pending is None:
                continue

            # Clear pending request
            if pending.pending_request_id is not None:
                self._pending_requests.pop(pending.pending_request_id, None)
                pending.pending_request_id = None

            # Update received cells
            pending.cells_received |= msg.cell_mask

            # Check if we have enough
            if pending.role == Role.PROVIDER:
                if msg.cell_mask == ALL_ONES:
                    self._complete_tx(tx_hash, ALL_ONES)
            else:
                # Sampler just needs custody columns
                if (pending.cells_received & self._custody_mask) == self._custody_mask:
                    self._complete_tx(tx_hash, pending.cells_received)

    def _complete_tx(self, tx_hash: TxHash, cell_mask: int) -> None:
        """Complete transaction processing and add to pool."""
        pending = self._pending_txs.pop(tx_hash, None)
        if pending is None:
            return

        # Create pool entry (we don't have full tx metadata in this sim,
        # so we create a minimal entry)
        from ..core.types import Address

        entry = BlobTxEntry(
            tx_hash=tx_hash,
            sender=Address(f"0x{tx_hash[:40]}"),  # Derive fake sender from hash
            nonce=0,
            gas_fee_cap=1000000000,
            gas_tip_cap=100000000,
            blob_gas_price=1000000,
            tx_size=131072,  # Default blob tx size
            blob_count=1,
            cell_mask=cell_mask,
            received_at=self._simulator.current_time,
        )

        try:
            self._pool.add(entry)

            # Record metrics
            if self._metrics is not None:
                self._metrics.record_tx_seen(self._id, tx_hash, pending.role, cell_mask)

            # Announce to peers
            self._announce_tx(entry)
        except (RBFRejected, SenderLimitExceeded, PoolFull):
            pass  # Transaction rejected

    def _announce_tx(self, entry: BlobTxEntry) -> None:
        """Announce transaction to peers that haven't seen it."""
        for peer in self._peers:
            if peer in entry.announced_to:
                continue

            msg = NewPooledTransactionHashes(
                sender=self._id,
                types=bytes([3]),
                sizes=[entry.tx_size],
                hashes=[entry.tx_hash],
                cell_mask=entry.cell_mask,
            )
            self.send(msg, peer)
            entry.announced_to.add(peer)

    def _allocate_request_id(self) -> RequestId:
        """Allocate a unique request ID."""
        from ..core.types import RequestId

        request_id = RequestId(self._next_request_id)
        self._next_request_id += 1
        return request_id

    def _schedule_request_timeout(self, request_id: RequestId) -> None:
        """Schedule a timeout for a pending request."""
        self.schedule_timer(
            delay=self._config.request_timeout,
            kind=TimerKind.REQUEST_TIMEOUT,
            context={"request_id": request_id},
        )

    def _schedule_provider_observation_timeout(self, tx_hash: TxHash) -> None:
        """Schedule timeout for observing provider announcements."""
        self.schedule_timer(
            delay=self._config.provider_observation_timeout,
            kind=TimerKind.PROVIDER_OBSERVATION_TIMEOUT,
            context={"tx_hash": tx_hash},
        )

    def _handle_request_timeout(self, context: dict[str, object]) -> None:
        """Handle a request timeout."""
        from ..core.types import RequestId

        request_id = context.get("request_id")
        if not isinstance(request_id, int):
            return

        request_id = RequestId(request_id)
        request = self._pending_requests.pop(request_id, None)
        if request is None:
            return  # Already completed

        pending = self._pending_txs.get(request.tx_hash)
        if pending is None:
            return

        # Try another peer
        if request.request_type == "tx":
            # Find another peer to try
            tried_peer = request.target_peer
            other_peers = (pending.provider_peers | pending.sampler_peers) - {tried_peer}
            if other_peers:
                new_peer = next(iter(other_peers))
                new_request_id = self._allocate_request_id()
                self._send_get_transactions(request.tx_hash, new_peer, new_request_id)
            else:
                # No more peers, give up
                self._pending_txs.pop(request.tx_hash, None)
        else:
            # Cell request timeout - try another peer or give up
            self._pending_txs.pop(request.tx_hash, None)

    def _handle_provider_observation_timeout(self, context: dict[str, object]) -> None:
        """Handle timeout waiting for provider announcements."""
        tx_hash = context.get("tx_hash")
        if not isinstance(tx_hash, str):
            return

        from ..core.types import TxHash

        tx_hash = TxHash(tx_hash)
        pending = self._pending_txs.get(tx_hash)
        if pending is None:
            return

        if pending.state != TxState.AWAITING_PROVIDERS:
            return  # Already moved on

        # Proceed with whatever peers we have
        if pending.provider_peers or pending.sampler_peers:
            if pending.role == Role.PROVIDER:
                target = next(iter(pending.provider_peers or pending.sampler_peers))
                self._start_provider_fetch(tx_hash, target)
            else:
                self._start_sampler_fetch(tx_hash)
        else:
            # No peers, drop the tx
            self._pending_txs.pop(tx_hash, None)

    def _handle_block_announcement(self, msg: BlockAnnouncement) -> None:
        """Handle a block announcement by marking included txs for cleanup."""
        for tx_hash in msg.block.blob_tx_hashes:
            # Remove from pending if still there
            self._pending_txs.pop(tx_hash, None)

            # Schedule cleanup for txs in our pool
            if self._pool.contains(tx_hash):
                # Record inclusion metrics
                if self._metrics is not None:
                    self._metrics.record_inclusion(tx_hash, msg.block.slot)

                self._schedule_tx_cleanup(tx_hash)

    def _schedule_tx_cleanup(self, tx_hash: TxHash) -> None:
        """Schedule cleanup of an included transaction after a short delay."""
        # Delay cleanup slightly to allow block propagation
        cleanup_delay = 2.0  # seconds
        self.schedule_timer(
            delay=cleanup_delay,
            kind=TimerKind.TX_CLEANUP,
            context={"tx_hash": tx_hash},
        )

    def _handle_tx_cleanup(self, context: dict[str, object]) -> None:
        """Remove a transaction from the pool after block inclusion."""
        tx_hash = context.get("tx_hash")
        if not isinstance(tx_hash, str):
            return

        from ..core.types import TxHash

        tx_hash = TxHash(tx_hash)
        self._pool.remove(tx_hash)
