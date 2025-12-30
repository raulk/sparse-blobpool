"""Tests for eth/71 protocol messages."""

from sparse_blobpool.core.types import ActorId, TxHash
from sparse_blobpool.protocol.constants import ALL_ONES, CELL_SIZE, MESSAGE_OVERHEAD
from sparse_blobpool.protocol.messages import (
    Block,
    BlockAnnouncement,
    Cell,
    Cells,
    GetCells,
    GetPooledTransactions,
    NewPooledTransactionHashes,
    PooledTransactions,
    TxBody,
)


class TestNewPooledTransactionHashes:
    def test_size_bytes_without_cell_mask(self) -> None:
        """Size calculation for non-blob transactions."""
        msg = NewPooledTransactionHashes(
            sender=ActorId("node1"),
            types=bytes([1, 2]),  # 2 txs, not type 3
            sizes=[100, 200],
            hashes=[TxHash("a" * 64), TxHash("b" * 64)],
            cell_mask=None,
        )
        # overhead(8) + types(2) + sizes(2*4=8) + hashes(2*32=64) = 82
        assert msg.size_bytes == MESSAGE_OVERHEAD + 2 + 8 + 64

    def test_size_bytes_with_cell_mask(self) -> None:
        """Size calculation for blob transactions includes cell_mask."""
        msg = NewPooledTransactionHashes(
            sender=ActorId("node1"),
            types=bytes([3]),  # type 3 = blob tx
            sizes=[1000],
            hashes=[TxHash("a" * 64)],
            cell_mask=ALL_ONES,
        )
        # overhead(8) + types(1) + sizes(4) + hashes(32) + cell_mask(16) = 61
        assert msg.size_bytes == MESSAGE_OVERHEAD + 1 + 4 + 32 + 16

    def test_inherits_from_message(self) -> None:
        """NewPooledTransactionHashes has sender from Message base."""
        msg = NewPooledTransactionHashes(
            sender=ActorId("node1"),
            types=bytes([3]),
            sizes=[1000],
            hashes=[TxHash("a" * 64)],
            cell_mask=ALL_ONES,
        )
        assert msg.sender == ActorId("node1")


class TestGetPooledTransactions:
    def test_size_bytes(self) -> None:
        """Size is overhead plus 32 bytes per hash."""
        msg = GetPooledTransactions(
            sender=ActorId("node1"),
            tx_hashes=[TxHash("a" * 64), TxHash("b" * 64), TxHash("c" * 64)],
        )
        assert msg.size_bytes == MESSAGE_OVERHEAD + 3 * 32


class TestPooledTransactions:
    def test_size_bytes_with_available_txs(self) -> None:
        """Size includes actual transaction sizes."""
        tx1 = TxBody(tx_hash=TxHash("a" * 64), tx_bytes=500)
        tx2 = TxBody(tx_hash=TxHash("b" * 64), tx_bytes=300)
        msg = PooledTransactions(
            sender=ActorId("node1"),
            transactions=[tx1, tx2],
        )
        assert msg.size_bytes == MESSAGE_OVERHEAD + 500 + 300

    def test_size_bytes_with_none_txs(self) -> None:
        """None transactions contribute 0 to size."""
        tx1 = TxBody(tx_hash=TxHash("a" * 64), tx_bytes=500)
        msg = PooledTransactions(
            sender=ActorId("node1"),
            transactions=[tx1, None, None],
        )
        assert msg.size_bytes == MESSAGE_OVERHEAD + 500

    def test_size_bytes_all_unavailable(self) -> None:
        """All None transactions means just overhead."""
        msg = PooledTransactions(
            sender=ActorId("node1"),
            transactions=[None, None],
        )
        assert msg.size_bytes == MESSAGE_OVERHEAD


class TestGetCells:
    def test_size_bytes(self) -> None:
        """Size is overhead + hashes + cell_mask."""
        msg = GetCells(
            sender=ActorId("node1"),
            tx_hashes=[TxHash("a" * 64), TxHash("b" * 64)],
            cell_mask=0xFF,  # request 8 columns
        )
        # overhead(8) + hashes(2*32=64) + cell_mask(16) = 88
        assert msg.size_bytes == MESSAGE_OVERHEAD + 64 + 16


class TestCells:
    def test_size_bytes_with_cells(self) -> None:
        """Size includes all cells with their proofs."""
        cell = Cell(data=b"\x00" * CELL_SIZE, proof=b"\x00" * 48)
        msg = Cells(
            sender=ActorId("node1"),
            tx_hashes=[TxHash("a" * 64)],
            cells=[[cell, cell, None]],  # 2 cells for 1 tx
            cell_mask=0x03,  # columns 0 and 1
        )
        # overhead(8) + hashes(32) + cell_mask(16) + cells(2 * (2048+48))
        expected = MESSAGE_OVERHEAD + 32 + 16 + 2 * (CELL_SIZE + 48)
        assert msg.size_bytes == expected

    def test_size_bytes_empty_cells(self) -> None:
        """Empty response has just overhead and metadata."""
        msg = Cells(
            sender=ActorId("node1"),
            tx_hashes=[TxHash("a" * 64)],
            cells=[[]],
            cell_mask=0,
        )
        assert msg.size_bytes == MESSAGE_OVERHEAD + 32 + 16

    def test_size_bytes_multiple_txs(self) -> None:
        """Cells for multiple transactions are summed."""
        cell = Cell(data=b"\x00" * CELL_SIZE, proof=b"\x00" * 48)
        msg = Cells(
            sender=ActorId("node1"),
            tx_hashes=[TxHash("a" * 64), TxHash("b" * 64)],
            cells=[
                [cell, None],  # tx1: 1 cell
                [cell, cell, cell],  # tx2: 3 cells
            ],
            cell_mask=0x07,
        )
        # overhead(8) + hashes(2*32=64) + cell_mask(16) + cells(4 * (2048+48))
        expected = MESSAGE_OVERHEAD + 64 + 16 + 4 * (CELL_SIZE + 48)
        assert msg.size_bytes == expected


class TestCell:
    def test_size_bytes(self) -> None:
        """Cell is CELL_SIZE data plus 48 byte proof."""
        cell = Cell(data=b"\x00" * CELL_SIZE, proof=b"\x00" * 48)
        assert cell.size_bytes == CELL_SIZE + 48


class TestBlockAnnouncement:
    def test_size_bytes(self) -> None:
        """Block announcement includes header plus tx hashes."""
        block = Block(
            slot=100,
            proposer=ActorId("node1"),
            blob_tx_hashes=[TxHash("a" * 64), TxHash("b" * 64)],
        )
        msg = BlockAnnouncement(sender=ActorId("producer"), block=block)
        # 64 (header) + 2*32 (hashes)
        assert msg.size_bytes == 64 + 2 * 32

    def test_block_fields(self) -> None:
        """Block stores slot, proposer, and tx hashes."""
        block = Block(
            slot=42,
            proposer=ActorId("validator"),
            blob_tx_hashes=[TxHash("tx1")],
        )
        assert block.slot == 42
        assert block.proposer == ActorId("validator")
        assert block.blob_tx_hashes == [TxHash("tx1")]
