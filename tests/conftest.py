"""Shared pytest fixtures for sparse blobpool tests."""

import pytest

from sparse_blobpool.core.network import Network
from sparse_blobpool.core.simulator import Simulator


@pytest.fixture
def simulator() -> Simulator:
    """Create a fresh simulator with default seed."""
    return Simulator(seed=42)


@pytest.fixture
def simulator_with_network(simulator: Simulator) -> tuple[Simulator, Network]:
    """Create a simulator with network actor registered."""
    network = Network(simulator)
    simulator.register_actor(network)
    return simulator, network
