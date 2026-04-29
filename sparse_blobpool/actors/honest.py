"""Node actor implementing eth/71 sparse blobpool protocol."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from hashlib import sha256
from typing import TYPE_CHECKING

from sparse_blobpool.config import InclusionPolicy
from sparse_blobpool.core.actor import Actor, EventPayload, Message
from sparse_blobpool.pool.blobpool import (
    Blobpool,
    BlobTxEntry,
    PoolFull,
    RBFRejected,
    SenderLimitExceeded,
)
from sparse_blobpool.protocol.commands import (
    BroadcastTransaction,
    ProduceBlock,
    ProviderObservationTimeout,
    RequestTimeout,
    TxCleanup,
)
from sparse_blobpool.protocol.constants import ALL_ONES
from sparse_blobpool.protocol.messages import (
    Block,
    BlockBroadcast,
    Cells,
    EthProtocol,
    GetCells,
    GetPooledTransactions,
    NewPooledTransactionHashes,
    PooledTransactions,
    full_blob_tx_size,
)

if TYPE_CHECKING:
    from sparse_blobpool.config import SimulationConfig
    from sparse_blobpool.core.simulator import Simulator
    from sparse_blobpool.core.types import ActorId, RequestId, TxHash
    from sparse_blobpool.metrics.collector import MetricsCollector


class Role(Enum):
    """Node's role for a specific transaction."""

    PROVIDER = auto()  # Fetch and store full blob payload
    SAMPLER = auto()  # Sample custody-aligned cells only
    LEGACY_PROVIDER = auto()  # Received full blob payload through eth/70


class TxState(Enum):
    """State of a transaction being processed."""

    ANNOUNCED = auto()  # Received announcement, awaiting decision
    AWAITING_PROVIDERS = auto()  # Sampler waiting for provider announcements
    FETCHING_TX = auto()  # Requesting transaction body
    FETCHING_CELLS = auto()  # Requesting cells
    COMPLETE = auto()  # All data received


@dataclass
class PendingTx:
    tx_hash: TxHash
    role: Role
    state: TxState
    provider_peers: set[ActorId] = field(default_factory=set)
    sampler_peers: set[ActorId] = field(default_factory=set)
    legacy_peers: set[ActorId] = field(default_factory=set)
    tx_body_received: bool = False
    cells_received: int = 0  # bitmap of received columns
    pending_request_id: RequestId | None = None
    first_seen: float = 0.0
    # Role assigned by _determine_role; role may be later overridden to
    # LEGACY_PROVIDER on fallback, so we preserve the original to track
    # whether a sampler succeeded via eth/71 or fell back to eth/70.
    original_role: Role | None = None


@dataclass
class PendingRequest:
    request_id: RequestId
    tx_hashes: list[TxHash]
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
        metrics: MetricsCollector,
        protocols: set[EthProtocol] | None = None,
    ) -> None:
        super().__init__(actor_id, simulator)
        self._config = config
        self._pool = Blobpool(config)
        self._custody_columns = custody_columns
        self._metrics = metrics

        # Peer connections
        self._peers: set[ActorId] = set()
        self._protocols = protocols or {EthProtocol.ETH70, EthProtocol.ETH71}
        self._peer_protocols: dict[ActorId, EthProtocol] = {}

        # Transaction processing state
        self._pending_txs: dict[TxHash, PendingTx] = {}
        self._pending_requests: dict[RequestId, PendingRequest] = {}
        self._next_request_id: int = 0
        self._included_txs: set[TxHash] = set()
        self._seen_blocks: set[tuple[int, ActorId]] = set()

        # Custody column assignment (deterministic from node ID)
        self._custody_mask = self._compute_custody_mask()

    @property
    def pool(self) -> Blobpool:
        return self._pool

    @property
    def peers(self) -> set[ActorId]:
        return self._peers

    @property
    def protocols(self) -> set[EthProtocol]:
        return set(self._protocols)

    @property
    def custody_mask(self) -> int:
        return self._custody_mask

    def add_peer(
        self,
        peer_id: ActorId,
        negotiated_protocol: EthProtocol | None = None,
    ) -> None:
        self._peers.add(peer_id)
        self._peer_protocols[peer_id] = negotiated_protocol or self._default_peer_protocol()

    def remove_peer(self, peer_id: ActorId) -> None:
        self._peers.discard(peer_id)
        self._peer_protocols.pop(peer_id, None)

    def negotiated_protocol(self, peer_id: ActorId) -> EthProtocol:
        return self._peer_protocols.get(peer_id, self._default_peer_protocol())

    def supports_protocol(self, protocol: EthProtocol) -> bool:
        return protocol in self._protocols

    def _default_peer_protocol(self) -> EthProtocol:
        if EthProtocol.ETH71 in self._protocols:
            return EthProtocol.ETH71
        return EthProtocol.ETH70

    def on_event(self, payload: EventPayload) -> None:
        match payload:
            # Commands
            case BroadcastTransaction() as cmd:
                self._handle_broadcast_transaction(cmd)
            case ProduceBlock() as cmd:
                self._handle_produce_block(cmd)
            case RequestTimeout() as cmd:
                self._handle_request_timeout(cmd)
            case ProviderObservationTimeout() as cmd:
                self._handle_provider_observation_timeout(cmd)
            case TxCleanup() as cmd:
                self._handle_tx_cleanup(cmd)
            # Messages
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
            case BlockBroadcast() as msg:
                self._handle_block_announcement(msg)
            case Message():
                pass  # Unknown message type

    def _handle_broadcast_transaction(self, cmd: BroadcastTransaction) -> None:
        entry = BlobTxEntry(
            tx_hash=cmd.tx_hash,
            sender=cmd.tx_sender,
            nonce=cmd.nonce,
            gas_fee_cap=cmd.gas_fee_cap,
            gas_tip_cap=cmd.gas_tip_cap,
            blob_gas_price=cmd.blob_gas_price,
            tx_size=cmd.tx_size,
            blob_count=cmd.blob_count,
            cell_mask=cmd.cell_mask,
            received_at=self._simulator.current_time,
        )

        try:
            self._pool.add(entry)

            # Record metrics - origin node is always a provider with full blob
            self._metrics.record_tx_seen(self._id, cmd.tx_hash, Role.PROVIDER, cmd.cell_mask)

            self._announce_tx(entry)
            self._schedule_tx_expiration(entry.tx_hash)
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
        sender = msg.sender
        peer_protocol = self.negotiated_protocol(sender)
        legacy_fetch_hashes: list[TxHash] = []

        for i, tx_hash in enumerate(msg.hashes):
            if tx_hash in self._included_txs:
                continue

            tx_type = msg.types[i] if i < len(msg.types) else 0

            # Skip non-blob transactions
            if tx_type != 3:
                continue

            # Skip if already in pool
            if self._pool.contains(tx_hash):
                continue

            uses_legacy = peer_protocol == EthProtocol.ETH70 or msg.cell_mask is None

            # Check if we're already processing this tx
            if tx_hash in self._pending_txs:
                pending = self._pending_txs[tx_hash]

                if uses_legacy:
                    pending.legacy_peers.add(sender)
                    if pending.role == Role.SAMPLER:
                        # Legacy peers count toward min_providers_before_sample so
                        # samplers don't have to wait for multiple eth/71 announcements
                        # when legacy nodes have already confirmed availability.
                        # We still need at least one eth/71 provider peer to actually
                        # perform the sparse cell fetch.
                        if (
                            pending.state == TxState.AWAITING_PROVIDERS
                            and pending.provider_peers
                            and self._provider_count(pending)
                            >= self._config.min_providers_before_sample
                        ):
                            self._start_sampler_fetch(tx_hash)
                        continue
                    if pending.state in {TxState.ANNOUNCED, TxState.AWAITING_PROVIDERS}:
                        pending.role = Role.LEGACY_PROVIDER
                        legacy_fetch_hashes.append(tx_hash)
                    continue

                # Record peer based on their availability
                if msg.cell_mask == ALL_ONES:
                    pending.provider_peers.add(sender)
                else:
                    pending.sampler_peers.add(sender)

                # If sampler awaiting providers and we now have enough, proceed.
                # Legacy peers count toward the threshold alongside eth/71 providers.
                if (
                    pending.state == TxState.AWAITING_PROVIDERS
                    and pending.provider_peers
                    and self._provider_count(pending) >= self._config.min_providers_before_sample
                ):
                    self._start_sampler_fetch(tx_hash)
                continue

            if uses_legacy:
                # Determine role first: samplers must not fetch full blobs via eth/70.
                # Instead they register the legacy peer and wait for an eth/71
                # announcement that advertises cell availability.
                role = self._determine_role(tx_hash)
                if role == Role.SAMPLER:
                    pending = PendingTx(
                        tx_hash=tx_hash,
                        role=Role.SAMPLER,
                        state=TxState.AWAITING_PROVIDERS,
                        first_seen=self._simulator.current_time,
                        original_role=Role.SAMPLER,
                    )
                    pending.legacy_peers.add(sender)
                    self._pending_txs[tx_hash] = pending
                    self._schedule_provider_observation_timeout(tx_hash)
                    continue

                pending = PendingTx(
                    tx_hash=tx_hash,
                    role=Role.LEGACY_PROVIDER,
                    state=TxState.ANNOUNCED,
                    first_seen=self._simulator.current_time,
                    original_role=Role.LEGACY_PROVIDER,
                )
                pending.legacy_peers.add(sender)
                self._pending_txs[tx_hash] = pending
                legacy_fetch_hashes.append(tx_hash)
                continue

            # New transaction - determine our role
            role = self._determine_role(tx_hash)

            pending = PendingTx(
                tx_hash=tx_hash,
                role=role,
                state=TxState.ANNOUNCED,
                first_seen=self._simulator.current_time,
                original_role=role,
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

        if legacy_fetch_hashes:
            self._start_legacy_fetch(legacy_fetch_hashes, sender)

    def _start_provider_fetch(self, tx_hash: TxHash, from_peer: ActorId) -> None:
        pending = self._pending_txs.get(tx_hash)
        if pending is None:
            return

        pending.state = TxState.FETCHING_TX

        # Request transaction body
        request_id = self._allocate_request_id()
        self._send_get_transactions(tx_hash, from_peer, request_id)

    def _start_legacy_fetch(self, tx_hashes: list[TxHash], from_peer: ActorId) -> None:
        request_hashes = [tx_hash for tx_hash in tx_hashes if tx_hash in self._pending_txs]
        if not request_hashes:
            return

        request_id = self._allocate_request_id()
        for tx_hash in request_hashes:
            pending = self._pending_txs[tx_hash]
            pending.role = Role.LEGACY_PROVIDER
            pending.state = TxState.FETCHING_TX

        self._send_get_transactions(request_hashes, from_peer, request_id)

    def _start_sampler_fetch(self, tx_hash: TxHash) -> None:
        pending = self._pending_txs.get(tx_hash)
        if pending is None:
            return

        pending.state = TxState.FETCHING_TX

        # Pick a provider peer to request from
        target = self._pick_peer(pending.provider_peers) or self._pick_peer(pending.sampler_peers)
        if target is None:
            return  # No peers to request from

        request_id = self._allocate_request_id()
        self._send_get_transactions(tx_hash, target, request_id)

    def _send_get_transactions(
        self, tx_hash: TxHash | list[TxHash], to_peer: ActorId, request_id: RequestId
    ) -> None:
        tx_hashes = [tx_hash] if not isinstance(tx_hash, list) else tx_hash
        request_hashes = [hash_ for hash_ in tx_hashes if hash_ in self._pending_txs]
        if not request_hashes:
            return

        for hash_ in request_hashes:
            self._pending_txs[hash_].pending_request_id = request_id

        self._pending_requests[request_id] = PendingRequest(
            request_id=request_id,
            tx_hashes=request_hashes,
            target_peer=to_peer,
            request_type="tx",
            sent_at=self._simulator.current_time,
        )

        msg = GetPooledTransactions(sender=self._id, tx_hashes=request_hashes)
        self.send(msg, to_peer)
        self._schedule_request_timeout(request_id)

    def _handle_get_transactions(self, msg: GetPooledTransactions) -> None:
        from sparse_blobpool.protocol.messages import PooledTransactions, TxBody

        transactions: list[TxBody | None] = []
        legacy_response = self.negotiated_protocol(msg.sender) == EthProtocol.ETH70

        for tx_hash in msg.tx_hashes:
            entry = self._pool.get(tx_hash)
            if entry is not None:
                if legacy_response:
                    if not entry.has_full_availability:
                        transactions.append(None)
                        continue
                    tx_bytes = full_blob_tx_size(entry.tx_size, entry.blob_count)
                else:
                    # Approximate elided wrapper size: 300 bytes base + 96 bytes per blob
                    tx_bytes = 300 + (entry.blob_count * 96)
                transactions.append(TxBody(tx_hash=entry.tx_hash, tx_bytes=tx_bytes))
            else:
                transactions.append(None)

        response = PooledTransactions(sender=self._id, transactions=transactions)
        self.send(response, msg.sender)

    def _handle_transactions(self, msg: PooledTransactions) -> None:
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

            if pending.role == Role.LEGACY_PROVIDER:
                self._complete_tx(tx_hash, ALL_ONES)
                continue

            # Now fetch cells
            if pending.role == Role.PROVIDER:
                self._request_all_cells(tx_hash, msg.sender)
            else:
                self._request_custody_cells(tx_hash, msg.sender)

    def _request_all_cells(self, tx_hash: TxHash, from_peer: ActorId) -> None:
        pending = self._pending_txs.get(tx_hash)
        if pending is None:
            return

        pending.state = TxState.FETCHING_CELLS
        request_id = self._allocate_request_id()

        pending.pending_request_id = request_id
        self._pending_requests[request_id] = PendingRequest(
            request_id=request_id,
            tx_hashes=[tx_hash],
            target_peer=from_peer,
            request_type="cells",
            sent_at=self._simulator.current_time,
        )

        msg = GetCells(sender=self._id, tx_hashes=[tx_hash], cell_mask=ALL_ONES)
        self.send(msg, from_peer)
        self._schedule_request_timeout(request_id)

    def _request_custody_cells(self, tx_hash: TxHash, from_peer: ActorId) -> None:
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
            tx_hashes=[tx_hash],
            target_peer=from_peer,
            request_type="cells",
            sent_at=self._simulator.current_time,
        )

        msg = GetCells(sender=self._id, tx_hashes=[tx_hash], cell_mask=request_mask)
        self.send(msg, from_peer)
        self._schedule_request_timeout(request_id)

    def _select_extra_columns(self, provider_peers: set[ActorId]) -> int:
        extra_mask = 0
        available_cols = [i for i in range(128) if not (self._custody_mask & (1 << i))]

        if available_cols:
            # Select C_extra random columns
            count = min(self._config.extra_random_columns, len(available_cols))
            selected = self._simulator.rng.sample(available_cols, count)
            for col in selected:
                extra_mask |= 1 << col

        return extra_mask

    def _provider_count(self, pending: PendingTx) -> int:
        """Number of peers that have confirmed full availability for this tx.

        Counts both eth/71 provider peers (cell_mask == ALL_ONES) and legacy
        eth/70 peers, since both signal that the full blob is available.
        """
        return len(pending.provider_peers) + len(pending.legacy_peers)

    def _handle_get_cells(self, msg: GetCells) -> None:
        from sparse_blobpool.protocol.messages import Cell, Cells

        if EthProtocol.ETH71 not in self._protocols:
            return

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
        if EthProtocol.ETH71 not in self._protocols:
            return

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
        if tx_hash in self._included_txs:
            self._pending_txs.pop(tx_hash, None)
            return

        pending = self._pending_txs.pop(tx_hash, None)
        if pending is None:
            return

        # Record sampler outcome before further processing
        if pending.original_role == Role.SAMPLER:
            via_eth71 = pending.role == Role.SAMPLER  # False if fell back to LEGACY_PROVIDER
            self._metrics.record_sampler_outcome(tx_hash, via_eth71=via_eth71)

        # Create pool entry (we don't have full tx metadata in this sim,
        # so we create a minimal entry)
        from sparse_blobpool.core.types import Address

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
            self._metrics.record_tx_seen(self._id, tx_hash, pending.role, cell_mask)

            # Announce to peers
            self._announce_tx(entry)
            self._schedule_tx_expiration(entry.tx_hash)
        except (RBFRejected, SenderLimitExceeded, PoolFull):
            pass  # Transaction rejected

    def _announce_tx(self, entry: BlobTxEntry) -> None:
        for peer in self._select_announcement_peers(entry):
            protocol = self.negotiated_protocol(peer)
            is_legacy = protocol == EthProtocol.ETH70
            if peer in entry.announced_to:
                continue

            # eth/71 announcements advertise availability with cell_mask and an elided wrapper
            # size. eth/70 announcements omit cell_mask and rely on full tx fetches.
            announced_size = (
                full_blob_tx_size(entry.tx_size, entry.blob_count)
                if is_legacy
                else 300 + (entry.blob_count * 96)
            )
            msg = NewPooledTransactionHashes(
                sender=self._id,
                types=bytes([3]),
                sizes=[announced_size],
                hashes=[entry.tx_hash],
                cell_mask=None if is_legacy else entry.cell_mask,
            )
            self.send(msg, peer)
            entry.announced_to.add(peer)

    def _select_announcement_peers(self, entry: BlobTxEntry) -> list[ActorId]:
        eligible = [
            peer
            for peer in self._peers
            if entry.has_full_availability or self.negotiated_protocol(peer) != EthProtocol.ETH70
        ]
        ordered = sorted(eligible, key=lambda peer: self._announcement_peer_key(entry, peer))
        limit = self._config.outbound_broadcast_peer_limit
        if limit is None:
            return ordered
        return ordered[:limit]

    def _announcement_peer_key(self, entry: BlobTxEntry, peer: ActorId) -> tuple[bytes, ActorId]:
        material = f"{self._id}:{entry.tx_hash}:{peer}".encode()
        return sha256(material).digest(), peer

    def _allocate_request_id(self) -> RequestId:
        from sparse_blobpool.core.types import RequestId

        request_id = RequestId(self._next_request_id)
        self._next_request_id += 1
        return request_id

    def _schedule_request_timeout(self, request_id: RequestId) -> None:
        self.schedule_command(
            self._config.request_timeout,
            RequestTimeout(request_id=request_id),
        )

    def _schedule_provider_observation_timeout(self, tx_hash: TxHash) -> None:
        self.schedule_command(
            self._config.provider_observation_timeout,
            ProviderObservationTimeout(tx_hash=tx_hash),
        )

    def _schedule_tx_expiration(self, tx_hash: TxHash) -> None:
        self.schedule_command(self._config.tx_expiration, TxCleanup(tx_hash=tx_hash))

    @staticmethod
    def _pick_peer(peers: set[ActorId]) -> ActorId | None:
        if not peers:
            return None
        return min(peers)

    def _handle_request_timeout(self, cmd: RequestTimeout) -> None:
        request = self._pending_requests.pop(cmd.request_id, None)
        if request is None:
            return  # Already completed

        pending = self._pending_txs.get(request.tx_hashes[0]) if request.tx_hashes else None
        if pending is None:
            return

        # Try another peer
        tried_peer = request.target_peer
        other_peers = (pending.provider_peers | pending.sampler_peers) - {tried_peer}
        new_peer = self._pick_peer(other_peers)

        if new_peer is not None:
            new_request_id = self._allocate_request_id()
            if request.request_type == "tx":
                self._send_get_transactions(request.tx_hashes, new_peer, new_request_id)
            else:
                # Retry cell request with another peer
                from sparse_blobpool.protocol.messages import GetCells

                pending.pending_request_id = new_request_id
                self._pending_requests[new_request_id] = PendingRequest(
                    request_id=new_request_id,
                    tx_hashes=request.tx_hashes,
                    target_peer=new_peer,
                    request_type="cells",
                    sent_at=self._simulator.current_time,
                )

                # Determine appropriate mask for retry
                if pending.role == Role.PROVIDER:
                    mask = ALL_ONES
                else:
                    extra_columns = self._select_extra_columns(pending.provider_peers)
                    mask = self._custody_mask | extra_columns

                msg = GetCells(sender=self._id, tx_hashes=request.tx_hashes, cell_mask=mask)
                self.send(msg, new_peer)
                self._schedule_request_timeout(new_request_id)
        elif pending.legacy_peers:
            # No more eth/71 peers, fall back to legacy to avoid network partition
            legacy_peer = self._pick_peer(pending.legacy_peers)
            if legacy_peer is not None:
                self._start_legacy_fetch(request.tx_hashes, legacy_peer)
        else:
            # No more peers at all, drop the tx
            for tx_hash in request.tx_hashes:
                self._pending_txs.pop(tx_hash, None)

    def _handle_provider_observation_timeout(self, cmd: ProviderObservationTimeout) -> None:
        pending = self._pending_txs.get(cmd.tx_hash)
        if pending is None:
            return

        if pending.state != TxState.AWAITING_PROVIDERS:
            return  # Already moved on

        # Proceed with whatever peers we have
        if pending.provider_peers or pending.sampler_peers:
            if pending.role == Role.PROVIDER:
                target = self._pick_peer(pending.provider_peers or pending.sampler_peers)
                if target is not None:
                    self._start_provider_fetch(cmd.tx_hash, target)
            else:
                self._start_sampler_fetch(cmd.tx_hash)
        elif pending.legacy_peers:
            # Sampler has waited but found no eth/71 peers: fall back to legacy to avoid
            # network partition if all peers are legacy-only. A single legacy-only peer
            # is better than nothing.
            if pending.role == Role.SAMPLER:
                legacy_peer = self._pick_peer(pending.legacy_peers)
                if legacy_peer is not None:
                    self._start_legacy_fetch([cmd.tx_hash], legacy_peer)
        else:
            # No peers at all, drop the tx
            self._pending_txs.pop(cmd.tx_hash, None)

    def _handle_block_announcement(self, msg: BlockBroadcast) -> None:
        block_key = (msg.block.slot, msg.block.proposer)
        if block_key in self._seen_blocks:
            return
        self._seen_blocks.add(block_key)

        for peer in sorted(self._peers):
            if peer != msg.sender:
                self.send(msg, peer)

        # Perform DA check: do we have the required data for all txs in this block?
        da_passed = self._check_block_da(msg.block.blob_tx_hashes)
        self._metrics.record_da_check(da_passed)

        for tx_hash in msg.block.blob_tx_hashes:
            self._included_txs.add(tx_hash)

            # Remove from pending if still there
            self._pending_txs.pop(tx_hash, None)

            # Schedule cleanup for txs in our pool
            if self._pool.contains(tx_hash):
                # Record inclusion metrics
                self._metrics.record_inclusion(tx_hash, msg.block.slot)

                self._schedule_tx_cleanup(tx_hash)

    def _check_block_da(self, tx_hashes: list[TxHash]) -> bool:
        """Check if DA requirements are met for all transactions in a block.

        For providers: must hold full blob (all cells)
        For samplers: must hold all custody columns
        """
        for tx_hash in tx_hashes:
            entry = self._pool.get(tx_hash)
            if entry is None:
                return False

            if entry.has_full_availability:
                continue

            if (entry.cell_mask & self._custody_mask) != self._custody_mask:
                return False

        return True

    def _schedule_tx_cleanup(self, tx_hash: TxHash) -> None:
        # Delay cleanup slightly to allow block propagation
        cleanup_delay = 2.0  # seconds
        self.schedule_command(cleanup_delay, TxCleanup(tx_hash=tx_hash))

    def _handle_tx_cleanup(self, cmd: TxCleanup) -> None:
        self._pool.remove(cmd.tx_hash)

    def _handle_produce_block(self, cmd: ProduceBlock) -> None:
        selected_txs = self._select_blobs_for_block()

        if not selected_txs:
            return

        block = Block(
            slot=cmd.slot,
            proposer=self._id,
            blob_tx_hashes=[tx.tx_hash for tx in selected_txs],
        )

        announcement = BlockBroadcast(sender=self._id, block=block)

        # If the simulator exposes a BlockProducer with diagnostic counters,
        # increment them so scenarios can report counts without additional wiring.
        try:
            bp = self._simulator.block_producer
            if hasattr(bp, "blocks_produced"):
                bp.blocks_produced += 1
            if hasattr(bp, "total_blobs_included"):
                bp.total_blobs_included += sum(tx.blob_count for tx in selected_txs)
        except Exception:
            pass

        self._handle_block_announcement(announcement)

    def _select_blobs_for_block(self) -> list[BlobTxEntry]:
        candidates = [
            tx
            for tx in self._pool.iter_by_priority()
            if tx.tx_hash not in self._included_txs and self._is_includable(tx)
        ]

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
                return tx.has_full_availability
