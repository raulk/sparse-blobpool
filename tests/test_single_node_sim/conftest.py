"""Shared pytest fixtures for single_node_sim tests."""

import pytest

from single_node_sim.events import BlockIncluded, CellsReceived, TxAnnouncement
from single_node_sim.params import PRESETS, HeuristicParams
from sparse_blobpool.core.simulator import Simulator
from sparse_blobpool.protocol.constants import ALL_ONES


@pytest.fixture
def default_params() -> HeuristicParams:
    """Create default HeuristicParams."""
    return HeuristicParams()


@pytest.fixture
def simple_events() -> list[TxAnnouncement]:
    """Create a simple list of transaction announcements for testing."""
    return [
        TxAnnouncement(
            timestamp=0.0,
            tx_hash="0xabc1",
            sender="0xsender1",
            nonce=0,
            gas_fee_cap=1_000_000_000,
            gas_tip_cap=100_000_000,
            tx_size=131_072,
            blob_count=1,
            cell_mask=ALL_ONES,
        ),
        TxAnnouncement(
            timestamp=1.0,
            tx_hash="0xabc2",
            sender="0xsender2",
            nonce=0,
            gas_fee_cap=2_000_000_000,
            gas_tip_cap=200_000_000,
            tx_size=131_072,
            blob_count=2,
            cell_mask=ALL_ONES,
        ),
        TxAnnouncement(
            timestamp=2.0,
            tx_hash="0xabc3",
            sender="0xsender1",
            nonce=1,
            gas_fee_cap=1_500_000_000,
            gas_tip_cap=150_000_000,
            tx_size=131_072,
            blob_count=1,
            cell_mask=ALL_ONES,
        ),
    ]


@pytest.fixture
def simulator() -> Simulator:
    """Create a fresh simulator with default seed."""
    return Simulator(seed=42)


@pytest.fixture
def aggressive_eviction_params() -> HeuristicParams:
    """Create params with aggressive eviction settings."""
    return PRESETS["aggressive_eviction"]


@pytest.fixture
def high_provider_params() -> HeuristicParams:
    """Create params with high provider probability."""
    return PRESETS["high_provider"]


@pytest.fixture
def strict_rate_limit_params() -> HeuristicParams:
    """Create params with strict rate limiting."""
    return PRESETS["strict_rate_limit"]


@pytest.fixture
def short_ttl_params() -> HeuristicParams:
    """Create params with short TTL."""
    return PRESETS["short_ttl"]


@pytest.fixture
def cells_received_event() -> CellsReceived:
    """Create a CellsReceived event."""
    return CellsReceived(
        timestamp=0.5,
        tx_hash="0xabc1",
        cell_mask=0xFF,
    )


@pytest.fixture
def block_included_event() -> BlockIncluded:
    """Create a BlockIncluded event."""
    return BlockIncluded(
        timestamp=12.0,
        tx_hashes=["0xabc1", "0xabc2"],
    )
