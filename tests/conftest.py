"""Shared pytest fixtures for sparse blobpool tests."""

import pytest

from sparse_blobpool.core.network import Network
from sparse_blobpool.core.simulator import Simulator
from sparse_blobpool.metrics.collector import MetricsCollector


@pytest.fixture
def simulator() -> Simulator:
    """Create a fresh simulator with default seed."""
    return Simulator(seed=42)


@pytest.fixture
def metrics(simulator: Simulator) -> MetricsCollector:
    """Create a metrics collector."""
    return MetricsCollector(simulator=simulator)


@pytest.fixture
def simulator_with_network(
    simulator: Simulator, metrics: MetricsCollector
) -> tuple[Simulator, Network]:
    """Create a simulator with network configured."""
    network = Network(simulator, metrics)
    simulator._network = network
    return simulator, network
