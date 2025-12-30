"""eth/71 protocol message types for sparse blobpool."""

from dataclasses import dataclass, field

from ..core.actor import Message
from ..core.types import ActorId, Address, TxHash
from .constants import CELL_SIZE, MESSAGE_OVERHEAD


@dataclass
class NewPooledTransactionHashes(Message):
    """Announce new transactions to a peer (eth/71 0x08).

    For type 3 (blob) transactions, cell_mask indicates which columns
    the announcer has available. ALL_ONES means full blob availability.
    """

    types: bytes  # 1 byte per tx (3 = blob tx)
    sizes: list[int]  # transaction sizes in bytes
    hashes: list[TxHash]  # 32 bytes each
    cell_mask: int | None = None  # uint128 bitmap, None if no type-3 txs

    @property
    def size_bytes(self) -> int:
        return (
            MESSAGE_OVERHEAD
            + len(self.types)  # types
            + len(self.sizes) * 4  # sizes (uint32)
            + len(self.hashes) * 32  # hashes
            + (16 if self.cell_mask is not None else 0)  # cell_mask
        )


@dataclass
class TxBody:
    """Transaction body without blob data (for type-3 txs, blobs are elided)."""

    tx_hash: TxHash
    tx_bytes: int  # size of tx envelope without blobs

    @property
    def size_bytes(self) -> int:
        return self.tx_bytes


@dataclass
class GetPooledTransactions(Message):
    """Request transaction bodies (eth/71 0x09).

    For type-3 txs, responses elide blob payloads.
    """

    tx_hashes: list[TxHash]

    @property
    def size_bytes(self) -> int:
        return MESSAGE_OVERHEAD + len(self.tx_hashes) * 32


@dataclass
class PooledTransactions(Message):
    """Response with transaction bodies (eth/71 0x0A).

    For type-3 txs, blob payloads are elided (set to None).
    """

    transactions: list[TxBody | None]  # None for unavailable txs

    @property
    def size_bytes(self) -> int:
        return MESSAGE_OVERHEAD + sum(tx.size_bytes if tx else 0 for tx in self.transactions)


@dataclass
class Cell:
    """A single cell (2048 bytes) with its KZG proof."""

    data: bytes = field(repr=False)  # CELL_SIZE bytes
    proof: bytes = field(repr=False)  # 48 bytes KZG proof

    @property
    def size_bytes(self) -> int:
        return CELL_SIZE + 48


@dataclass
class GetCells(Message):
    """Request specific cells for blob transactions (eth/71 0x12).

    cell_mask is a uint128 bitmap indicating which column indices are needed.
    """

    tx_hashes: list[TxHash]
    cell_mask: int  # uint128 bitmap of requested columns

    @property
    def size_bytes(self) -> int:
        return MESSAGE_OVERHEAD + len(self.tx_hashes) * 32 + 16


@dataclass
class Cells(Message):
    """Response with requested cells (eth/71 0x13).

    cells is a list of lists: cells[tx_index][column_index].
    Only columns indicated in cell_mask are populated.
    """

    tx_hashes: list[TxHash]
    cells: list[list[Cell | None]]  # per-tx, per-column
    cell_mask: int  # actual columns provided (uint128)

    @property
    def size_bytes(self) -> int:
        cell_count = sum(sum(1 for c in tx_cells if c is not None) for tx_cells in self.cells)
        return (
            MESSAGE_OVERHEAD
            + len(self.tx_hashes) * 32  # hashes
            + 16  # cell_mask
            + cell_count * (CELL_SIZE + 48)  # cells with proofs
        )


@dataclass
class Block:
    """A block containing blob transaction inclusions."""

    slot: int
    proposer: ActorId
    blob_tx_hashes: list[TxHash]


@dataclass
class BlockAnnouncement(Message):
    """Announce a new block with included blob transactions."""

    block: Block

    @property
    def size_bytes(self) -> int:
        # slot (8) + proposer (~32) + header overhead (24) + hashes
        return 64 + len(self.block.blob_tx_hashes) * 32


@dataclass
class BroadcastTransaction(Message):
    """Event to inject a new transaction into a node's pool and announce it.

    This is not a network message but a local event used to inject transactions
    into the simulation. The receiving node will add the tx to its pool and
    announce to all peers as a provider.
    """

    tx_hash: TxHash
    tx_sender: Address
    nonce: int
    gas_fee_cap: int
    gas_tip_cap: int
    blob_gas_price: int
    tx_size: int
    blob_count: int
    cell_mask: int  # Cells the origin has (ALL_ONES for full blob)

    @property
    def size_bytes(self) -> int:
        return 0  # Local event, not transmitted over network
