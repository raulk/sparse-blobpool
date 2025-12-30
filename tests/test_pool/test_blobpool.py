"""Tests for Blobpool state management."""

import pytest

from sparse_blobpool.config import SimulationConfig
from sparse_blobpool.core.types import Address, TxHash
from sparse_blobpool.pool.blobpool import (
    Blobpool,
    BlobTxEntry,
    PoolFull,
    RBFRejected,
    SenderLimitExceeded,
)
from sparse_blobpool.protocol.constants import ALL_ONES, CELLS_PER_BLOB


@pytest.fixture
def config() -> SimulationConfig:
    """Create a test config with small limits for testing."""
    return SimulationConfig(
        blobpool_max_bytes=10000,  # Small pool for eviction tests
        max_txs_per_sender=3,
    )


@pytest.fixture
def pool(config: SimulationConfig) -> Blobpool:
    """Create a fresh blobpool."""
    return Blobpool(config)


def make_tx_entry(
    tx_hash: str = "0x1234",
    sender: str = "0xsender1",
    nonce: int = 0,
    gas_fee_cap: int = 1000,
    gas_tip_cap: int = 100,
    blob_gas_price: int = 50,
    tx_size: int = 500,
    blob_count: int = 1,
    cell_mask: int = ALL_ONES,
    received_at: float = 0.0,
) -> BlobTxEntry:
    """Helper to create test transaction entries."""
    return BlobTxEntry(
        tx_hash=TxHash(tx_hash),
        sender=Address(sender),
        nonce=nonce,
        gas_fee_cap=gas_fee_cap,
        gas_tip_cap=gas_tip_cap,
        blob_gas_price=blob_gas_price,
        tx_size=tx_size,
        blob_count=blob_count,
        cell_mask=cell_mask,
        received_at=received_at,
    )


class TestBlobTxEntry:
    def test_effective_tip(self) -> None:
        entry = make_tx_entry(gas_tip_cap=150)
        assert entry.effective_tip == 150

    def test_total_blob_cells(self) -> None:
        entry = make_tx_entry(blob_count=3)
        assert entry.total_blob_cells == 3 * CELLS_PER_BLOB

    def test_has_full_availability(self) -> None:
        entry = make_tx_entry(cell_mask=ALL_ONES)
        assert entry.has_full_availability

        partial_entry = make_tx_entry(cell_mask=0b1111)
        assert not partial_entry.has_full_availability

    def test_available_column_count(self) -> None:
        entry = make_tx_entry(cell_mask=0b10101010)
        assert entry.available_column_count() == 4

        full_entry = make_tx_entry(cell_mask=ALL_ONES)
        assert full_entry.available_column_count() == CELLS_PER_BLOB


class TestBlobpoolBasic:
    def test_add_and_get(self, pool: Blobpool) -> None:
        entry = make_tx_entry()
        result = pool.add(entry)

        assert result.added
        assert result.replaced is None
        assert result.evicted == []
        assert pool.contains(entry.tx_hash)
        assert pool.get(entry.tx_hash) == entry

    def test_add_updates_size(self, pool: Blobpool) -> None:
        entry = make_tx_entry(tx_size=1000)
        pool.add(entry)

        assert pool.size_bytes == 1000
        assert pool.tx_count == 1

    def test_get_nonexistent_returns_none(self, pool: Blobpool) -> None:
        assert pool.get(TxHash("0xnonexistent")) is None

    def test_contains_nonexistent_returns_false(self, pool: Blobpool) -> None:
        assert not pool.contains(TxHash("0xnonexistent"))

    def test_remove(self, pool: Blobpool) -> None:
        entry = make_tx_entry()
        pool.add(entry)
        removed = pool.remove(entry.tx_hash)

        assert removed == entry
        assert not pool.contains(entry.tx_hash)
        assert pool.size_bytes == 0

    def test_remove_nonexistent_returns_none(self, pool: Blobpool) -> None:
        assert pool.remove(TxHash("0xnonexistent")) is None

    def test_remove_batch(self, pool: Blobpool) -> None:
        entries = [make_tx_entry(tx_hash=f"0x{i}", nonce=i) for i in range(3)]
        for e in entries:
            pool.add(e)

        removed = pool.remove_batch([entries[0].tx_hash, entries[2].tx_hash])
        assert len(removed) == 2
        assert pool.tx_count == 1
        assert pool.contains(entries[1].tx_hash)

    def test_clear(self, pool: Blobpool) -> None:
        for i in range(3):
            pool.add(make_tx_entry(tx_hash=f"0x{i}", nonce=i))

        pool.clear()
        assert pool.tx_count == 0
        assert pool.size_bytes == 0


class TestBySenderIndex:
    def test_get_by_sender(self, pool: Blobpool) -> None:
        sender = "0xsender1"
        entries = [make_tx_entry(tx_hash=f"0x{i}", sender=sender, nonce=i) for i in range(2)]
        for e in entries:
            pool.add(e)

        by_sender = pool.get_by_sender(Address(sender))
        assert len(by_sender) == 2
        assert {e.tx_hash for e in by_sender} == {entries[0].tx_hash, entries[1].tx_hash}

    def test_sender_tx_count(self, pool: Blobpool) -> None:
        sender = "0xsender1"
        for i in range(2):
            pool.add(make_tx_entry(tx_hash=f"0x{i}", sender=sender, nonce=i))

        assert pool.sender_tx_count(Address(sender)) == 2
        assert pool.sender_tx_count(Address("0xother")) == 0

    def test_remove_updates_sender_index(self, pool: Blobpool) -> None:
        sender = "0xsender1"
        entry = make_tx_entry(sender=sender)
        pool.add(entry)
        pool.remove(entry.tx_hash)

        assert pool.sender_tx_count(Address(sender)) == 0
        assert pool.get_by_sender(Address(sender)) == []


class TestRBF:
    def test_rbf_success(self, pool: Blobpool) -> None:
        original = make_tx_entry(gas_fee_cap=1000, gas_tip_cap=100)
        pool.add(original)

        # 10% bump required
        replacement = make_tx_entry(
            tx_hash="0xreplacement",
            nonce=original.nonce,
            sender=original.sender,
            gas_fee_cap=1100,
            gas_tip_cap=110,
        )
        result = pool.add(replacement)

        assert result.added
        assert result.replaced == original.tx_hash
        assert pool.tx_count == 1
        assert pool.contains(replacement.tx_hash)
        assert not pool.contains(original.tx_hash)

    def test_rbf_rejected_insufficient_fee_cap(self, pool: Blobpool) -> None:
        original = make_tx_entry(gas_fee_cap=1000, gas_tip_cap=100)
        pool.add(original)

        # Fee cap not bumped enough
        replacement = make_tx_entry(
            tx_hash="0xreplacement",
            nonce=original.nonce,
            sender=original.sender,
            gas_fee_cap=1050,  # Only 5% bump
            gas_tip_cap=110,
        )
        with pytest.raises(RBFRejected) as exc_info:
            pool.add(replacement)

        assert exc_info.value.existing_hash == original.tx_hash
        assert pool.contains(original.tx_hash)
        assert not pool.contains(replacement.tx_hash)

    def test_rbf_rejected_insufficient_tip_cap(self, pool: Blobpool) -> None:
        original = make_tx_entry(gas_fee_cap=1000, gas_tip_cap=100)
        pool.add(original)

        # Tip cap not bumped enough
        replacement = make_tx_entry(
            tx_hash="0xreplacement",
            nonce=original.nonce,
            sender=original.sender,
            gas_fee_cap=1100,
            gas_tip_cap=105,  # Only 5% bump
        )
        with pytest.raises(RBFRejected):
            pool.add(replacement)

    def test_different_nonce_not_rbf(self, pool: Blobpool) -> None:
        entry1 = make_tx_entry(nonce=0)
        entry2 = make_tx_entry(tx_hash="0x5678", nonce=1)
        pool.add(entry1)
        result = pool.add(entry2)

        assert result.added
        assert result.replaced is None
        assert pool.tx_count == 2

    def test_different_sender_not_rbf(self, pool: Blobpool) -> None:
        entry1 = make_tx_entry(sender="0xsender1")
        entry2 = make_tx_entry(tx_hash="0x5678", sender="0xsender2")
        pool.add(entry1)
        result = pool.add(entry2)

        assert result.added
        assert result.replaced is None
        assert pool.tx_count == 2


class TestSenderLimit:
    def test_sender_limit_exceeded(self, pool: Blobpool) -> None:
        sender = "0xsender1"
        # Add max allowed (3 in test config)
        for i in range(3):
            pool.add(make_tx_entry(tx_hash=f"0x{i}", sender=sender, nonce=i))

        # Fourth should fail
        with pytest.raises(SenderLimitExceeded) as exc_info:
            pool.add(make_tx_entry(tx_hash="0x99", sender=sender, nonce=3))

        assert exc_info.value.sender == Address(sender)
        assert exc_info.value.count == 3
        assert exc_info.value.max_count == 3

    def test_rbf_bypasses_sender_limit(self, pool: Blobpool) -> None:
        sender = "0xsender1"
        # Fill to limit
        for i in range(3):
            pool.add(make_tx_entry(tx_hash=f"0x{i}", sender=sender, nonce=i))

        # RBF should still work
        replacement = make_tx_entry(
            tx_hash="0xreplacement",
            sender=sender,
            nonce=1,  # Replace nonce 1
            gas_fee_cap=1100,
            gas_tip_cap=110,
        )
        result = pool.add(replacement)

        assert result.added
        assert result.replaced == TxHash("0x1")


class TestEviction:
    def test_eviction_when_pool_full(self, pool: Blobpool) -> None:
        # Config has 10000 byte limit
        # Add transactions to near limit
        for i in range(10):
            pool.add(
                make_tx_entry(
                    tx_hash=f"0x{i}",
                    sender=f"0xsender{i}",
                    tx_size=900,
                    gas_tip_cap=100 + i,  # Higher tips for later txs
                )
            )

        assert pool.size_bytes == 9000

        # Add one more that requires eviction
        result = pool.add(
            make_tx_entry(
                tx_hash="0xnew",
                sender="0xnewsender",
                tx_size=2000,
                gas_tip_cap=500,  # High priority
            )
        )

        assert result.added
        assert len(result.evicted) >= 1
        # Lowest priority tx (0x0 with tip 100) should be evicted
        assert TxHash("0x0") in result.evicted

    def test_pool_full_when_new_tx_is_lowest_priority(self, pool: Blobpool) -> None:
        # Fill pool with high priority txs
        for i in range(10):
            pool.add(
                make_tx_entry(
                    tx_hash=f"0x{i}",
                    sender=f"0xsender{i}",
                    tx_size=900,
                    gas_tip_cap=1000,  # High priority
                )
            )

        # Try to add low priority tx that requires eviction
        with pytest.raises(PoolFull):
            pool.add(
                make_tx_entry(
                    tx_hash="0xnew",
                    sender="0xnewsender",
                    tx_size=2000,
                    gas_tip_cap=1,  # Lower than all existing
                )
            )


class TestCellMaskOperations:
    def test_update_cell_mask(self, pool: Blobpool) -> None:
        entry = make_tx_entry(cell_mask=0b1111)
        pool.add(entry)

        success = pool.update_cell_mask(entry.tx_hash, 0b11111111)
        assert success
        assert pool.get(entry.tx_hash).cell_mask == 0b11111111  # type: ignore[union-attr]

    def test_update_cell_mask_nonexistent(self, pool: Blobpool) -> None:
        assert not pool.update_cell_mask(TxHash("0xnonexistent"), 0xFF)

    def test_merge_cells(self, pool: Blobpool) -> None:
        entry = make_tx_entry(cell_mask=0b1010)
        pool.add(entry)

        new_mask = pool.merge_cells(entry.tx_hash, 0b0101)
        assert new_mask == 0b1111

    def test_merge_cells_nonexistent(self, pool: Blobpool) -> None:
        assert pool.merge_cells(TxHash("0xnonexistent"), 0xFF) is None


class TestIteration:
    def test_iter_by_priority(self, pool: Blobpool) -> None:
        entries = [
            make_tx_entry(tx_hash="0x1", sender="0xs1", gas_tip_cap=100),
            make_tx_entry(tx_hash="0x2", sender="0xs2", gas_tip_cap=300),
            make_tx_entry(tx_hash="0x3", sender="0xs3", gas_tip_cap=200),
        ]
        for e in entries:
            pool.add(e)

        by_priority = pool.iter_by_priority()
        assert [e.tx_hash for e in by_priority] == [
            TxHash("0x2"),
            TxHash("0x3"),
            TxHash("0x1"),
        ]

    def test_iter_expired(self, pool: Blobpool) -> None:
        entries = [
            make_tx_entry(tx_hash="0x1", sender="0xs1", received_at=0.0),
            make_tx_entry(tx_hash="0x2", sender="0xs2", received_at=100.0),
            make_tx_entry(tx_hash="0x3", sender="0xs3", received_at=200.0),
        ]
        for e in entries:
            pool.add(e)

        # At time 350 with TTL 300, tx at 0.0 is expired
        expired = pool.iter_expired(current_time=350.0, ttl=300.0)
        assert len(expired) == 1
        assert expired[0].tx_hash == TxHash("0x1")
