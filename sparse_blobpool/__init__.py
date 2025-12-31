"""Discrete event simulator for EIP-8070 sparse blobpool."""

from sparse_blobpool.config import SimulationConfig
from sparse_blobpool.core.topology import (
    DIVERSE,
    GEOGRAPHIC,
    LATENCY_AWARE,
    RANDOM,
    InterconnectionPolicy,
)

__all__ = [
    "DIVERSE",
    "GEOGRAPHIC",
    "LATENCY_AWARE",
    "RANDOM",
    "InterconnectionPolicy",
    "SimulationConfig",
]
