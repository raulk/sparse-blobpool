"""Tests for protocol constants."""

from sparse_blobpool.protocol.constants import (
    ALL_ONES,
    CELL_SIZE,
    CELLS_PER_BLOB,
    MAX_BLOBS_PER_TX,
    RECONSTRUCTION_THRESHOLD,
)


class TestCellConstants:
    def test_cell_size_is_2048_bytes(self) -> None:
        assert CELL_SIZE == 2048

    def test_cells_per_blob_is_128(self) -> None:
        assert CELLS_PER_BLOB == 128

    def test_reconstruction_threshold_is_64(self) -> None:
        """Need 64 cells for Reed-Solomon reconstruction."""
        assert RECONSTRUCTION_THRESHOLD == 64

    def test_reconstruction_threshold_is_half_of_cells(self) -> None:
        """RS reconstruction needs 50% of cells."""
        assert RECONSTRUCTION_THRESHOLD == CELLS_PER_BLOB // 2

    def test_max_blobs_per_tx_is_6(self) -> None:
        assert MAX_BLOBS_PER_TX == 6


class TestCellMaskConstants:
    def test_all_ones_has_128_bits_set(self) -> None:
        """ALL_ONES should have exactly CELLS_PER_BLOB bits set."""
        assert bin(ALL_ONES).count("1") == CELLS_PER_BLOB

    def test_all_ones_is_uint128_max_for_128_columns(self) -> None:
        """ALL_ONES should be (2^128 - 1)."""
        assert ALL_ONES == (1 << 128) - 1

    def test_all_ones_fits_in_16_bytes(self) -> None:
        """ALL_ONES should fit in uint128 (16 bytes)."""
        assert ALL_ONES.bit_length() <= 128
