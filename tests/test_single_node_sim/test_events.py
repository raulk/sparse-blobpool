"""Tests for single_node_sim.events module."""

import pytest
from dataclasses import FrozenInstanceError

from single_node_sim.events import (
    BlockIncluded,
    CellsReceived,
    TxAnnouncement,
    normalize_event,
)
from sparse_blobpool.protocol.constants import ALL_ONES


class TestTxAnnouncement:
    def test_creation_with_defaults(self) -> None:
        """TxAnnouncement can be created with default cell_mask."""
        ann = TxAnnouncement(
            timestamp=1.0,
            tx_hash="0xabc",
            sender="0xsender",
            nonce=0,
            gas_fee_cap=1000,
            gas_tip_cap=100,
            tx_size=1024,
            blob_count=1,
        )

        assert ann.timestamp == 1.0
        assert ann.tx_hash == "0xabc"
        assert ann.sender == "0xsender"
        assert ann.nonce == 0
        assert ann.gas_fee_cap == 1000
        assert ann.gas_tip_cap == 100
        assert ann.tx_size == 1024
        assert ann.blob_count == 1
        assert ann.cell_mask == ALL_ONES

    def test_creation_with_custom_cell_mask(self) -> None:
        """TxAnnouncement can be created with custom cell_mask."""
        custom_mask = 0xFF00FF00
        ann = TxAnnouncement(
            timestamp=1.0,
            tx_hash="0xabc",
            sender="0xsender",
            nonce=0,
            gas_fee_cap=1000,
            gas_tip_cap=100,
            tx_size=1024,
            blob_count=1,
            cell_mask=custom_mask,
        )

        assert ann.cell_mask == custom_mask

    def test_frozen(self) -> None:
        """TxAnnouncement is immutable (frozen)."""
        ann = TxAnnouncement(
            timestamp=1.0,
            tx_hash="0xabc",
            sender="0xsender",
            nonce=0,
            gas_fee_cap=1000,
            gas_tip_cap=100,
            tx_size=1024,
            blob_count=1,
        )

        with pytest.raises(FrozenInstanceError):
            ann.timestamp = 2.0  # type: ignore[misc]


class TestCellsReceived:
    def test_creation(self) -> None:
        """CellsReceived can be created with required fields."""
        cells = CellsReceived(
            timestamp=0.5,
            tx_hash="0xabc",
            cell_mask=0xFF,
        )

        assert cells.timestamp == 0.5
        assert cells.tx_hash == "0xabc"
        assert cells.cell_mask == 0xFF

    def test_frozen(self) -> None:
        """CellsReceived is immutable (frozen)."""
        cells = CellsReceived(
            timestamp=0.5,
            tx_hash="0xabc",
            cell_mask=0xFF,
        )

        with pytest.raises(FrozenInstanceError):
            cells.cell_mask = 0x00  # type: ignore[misc]


class TestBlockIncluded:
    def test_creation(self) -> None:
        """BlockIncluded can be created with required fields."""
        block = BlockIncluded(
            timestamp=12.0,
            tx_hashes=["0xabc", "0xdef"],
        )

        assert block.timestamp == 12.0
        assert block.tx_hashes == ["0xabc", "0xdef"]

    def test_empty_tx_hashes(self) -> None:
        """BlockIncluded can have empty tx_hashes list."""
        block = BlockIncluded(
            timestamp=12.0,
            tx_hashes=[],
        )

        assert block.tx_hashes == []

    def test_frozen(self) -> None:
        """BlockIncluded is immutable (frozen)."""
        block = BlockIncluded(
            timestamp=12.0,
            tx_hashes=["0xabc"],
        )

        with pytest.raises(FrozenInstanceError):
            block.timestamp = 13.0  # type: ignore[misc]


class TestNormalizeEvent:
    def test_passthrough_tx_announcement(self) -> None:
        """normalize_event passes through TxAnnouncement unchanged."""
        ann = TxAnnouncement(
            timestamp=1.0,
            tx_hash="0xabc",
            sender="0xsender",
            nonce=0,
            gas_fee_cap=1000,
            gas_tip_cap=100,
            tx_size=1024,
            blob_count=1,
        )

        result = normalize_event(ann)

        assert result is ann

    def test_passthrough_cells_received(self) -> None:
        """normalize_event passes through CellsReceived unchanged."""
        cells = CellsReceived(
            timestamp=0.5,
            tx_hash="0xabc",
            cell_mask=0xFF,
        )

        result = normalize_event(cells)

        assert result is cells

    def test_passthrough_block_included(self) -> None:
        """normalize_event passes through BlockIncluded unchanged."""
        block = BlockIncluded(
            timestamp=12.0,
            tx_hashes=["0xabc"],
        )

        result = normalize_event(block)

        assert result is block

    def test_dict_to_tx_announcement(self) -> None:
        """normalize_event converts dict with sender to TxAnnouncement."""
        event_dict: dict = {
            "timestamp": 1.0,
            "tx_hash": "0xabc",
            "sender": "0xsender",
            "nonce": 0,
            "gas_fee_cap": 1000,
            "gas_tip_cap": 100,
            "tx_size": 1024,
            "blob_count": 1,
        }

        result = normalize_event(event_dict)

        assert isinstance(result, TxAnnouncement)
        assert result.timestamp == 1.0
        assert result.tx_hash == "0xabc"
        assert result.sender == "0xsender"
        assert result.cell_mask == ALL_ONES

    def test_dict_to_tx_announcement_with_cell_mask(self) -> None:
        """normalize_event preserves cell_mask from dict."""
        event_dict: dict = {
            "timestamp": 1.0,
            "tx_hash": "0xabc",
            "sender": "0xsender",
            "nonce": 0,
            "gas_fee_cap": 1000,
            "gas_tip_cap": 100,
            "tx_size": 1024,
            "blob_count": 1,
            "cell_mask": 0xFF00,
        }

        result = normalize_event(event_dict)

        assert isinstance(result, TxAnnouncement)
        assert result.cell_mask == 0xFF00

    def test_dict_to_cells_received(self) -> None:
        """normalize_event converts dict with cell_mask (no sender) to CellsReceived."""
        event_dict: dict = {
            "timestamp": 0.5,
            "tx_hash": "0xabc",
            "cell_mask": 0xFF,
        }

        result = normalize_event(event_dict)

        assert isinstance(result, CellsReceived)
        assert result.timestamp == 0.5
        assert result.tx_hash == "0xabc"
        assert result.cell_mask == 0xFF

    def test_dict_to_block_included(self) -> None:
        """normalize_event converts dict with tx_hashes to BlockIncluded."""
        event_dict: dict = {
            "timestamp": 12.0,
            "tx_hashes": ["0xabc", "0xdef"],
        }

        result = normalize_event(event_dict)

        assert isinstance(result, BlockIncluded)
        assert result.timestamp == 12.0
        assert result.tx_hashes == ["0xabc", "0xdef"]


class TestEventOrdering:
    def test_ordering_by_timestamp(self) -> None:
        """Events can be sorted by timestamp."""
        events = [
            TxAnnouncement(
                timestamp=3.0,
                tx_hash="0xc",
                sender="0xs",
                nonce=0,
                gas_fee_cap=1000,
                gas_tip_cap=100,
                tx_size=1024,
                blob_count=1,
            ),
            TxAnnouncement(
                timestamp=1.0,
                tx_hash="0xa",
                sender="0xs",
                nonce=0,
                gas_fee_cap=1000,
                gas_tip_cap=100,
                tx_size=1024,
                blob_count=1,
            ),
            TxAnnouncement(
                timestamp=2.0,
                tx_hash="0xb",
                sender="0xs",
                nonce=0,
                gas_fee_cap=1000,
                gas_tip_cap=100,
                tx_size=1024,
                blob_count=1,
            ),
        ]

        sorted_events = sorted(events, key=lambda e: e.timestamp)

        assert sorted_events[0].tx_hash == "0xa"
        assert sorted_events[1].tx_hash == "0xb"
        assert sorted_events[2].tx_hash == "0xc"

    def test_mixed_event_types_ordering(self) -> None:
        """Different event types can be sorted together by timestamp."""
        events: list = [
            BlockIncluded(timestamp=3.0, tx_hashes=["0xabc"]),
            TxAnnouncement(
                timestamp=1.0,
                tx_hash="0xabc",
                sender="0xs",
                nonce=0,
                gas_fee_cap=1000,
                gas_tip_cap=100,
                tx_size=1024,
                blob_count=1,
            ),
            CellsReceived(timestamp=2.0, tx_hash="0xabc", cell_mask=0xFF),
        ]

        sorted_events = sorted(events, key=lambda e: e.timestamp)

        assert isinstance(sorted_events[0], TxAnnouncement)
        assert isinstance(sorted_events[1], CellsReceived)
        assert isinstance(sorted_events[2], BlockIncluded)
