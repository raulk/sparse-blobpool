"""eth/71 protocol message types for sparse blobpool."""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from sparse_blobpool.core.base import Message
from sparse_blobpool.protocol.constants import CELL_SIZE, MESSAGE_OVERHEAD

if TYPE_CHECKING:
    from sparse_blobpool.core.types import ActorId, TxHash


@dataclass
class NewPooledTransactionHashes(Message):
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
    tx_hash: TxHash
    tx_bytes: int

    @property
    def size_bytes(self) -> int:
        return self.tx_bytes


@dataclass
class GetPooledTransactions(Message):
    tx_hashes: list[TxHash]

    @property
    def size_bytes(self) -> int:
        return MESSAGE_OVERHEAD + len(self.tx_hashes) * 32


@dataclass
class PooledTransactions(Message):
    transactions: list[TxBody | None]  # None for unavailable txs

    @property
    def size_bytes(self) -> int:
        return MESSAGE_OVERHEAD + sum(tx.size_bytes if tx else 0 for tx in self.transactions)


@dataclass
class Cell:
    data: bytes = field(repr=False)  # CELL_SIZE bytes
    proof: bytes = field(repr=False)  # 48 bytes KZG proof

    @property
    def size_bytes(self) -> int:
        return CELL_SIZE + 48


@dataclass
class GetCells(Message):
    tx_hashes: list[TxHash]
    cell_mask: int  # uint128 bitmap of requested columns

    @property
    def size_bytes(self) -> int:
        return MESSAGE_OVERHEAD + len(self.tx_hashes) * 32 + 16


@dataclass
class Cells(Message):
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
    slot: int
    proposer: ActorId
    blob_tx_hashes: list[TxHash]


@dataclass
class BlockBroadcast(Message):
    block: Block

    @property
    def size_bytes(self) -> int:
        # slot (8) + proposer (~32) + header overhead (24) + hashes
        return 64 + len(self.block.blob_tx_hashes) * 32
