"""Simulation configuration."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sparse_blobpool.core.topology import InterconnectionPolicy


class InclusionPolicy(Enum):
    CONSERVATIVE = auto()  # Only include if full blob held locally
    OPTIMISTIC = auto()  # Include if available (any cells)
    PROACTIVE = auto()  # Would trigger resampling first (not implemented)


@dataclass(frozen=True)
class SimulationConfig:
    """Configuration for the sparse blobpool simulation."""

    # Network topology
    node_count: int = 2000
    interconnection_policy: InterconnectionPolicy = None  # type: ignore[assignment]
    mesh_degree: int = 50  # D - number of peers per node

    # Protocol parameters (EIP-8070)
    provider_probability: float = 0.15  # p
    min_providers_before_sample: int = 2
    extra_random_columns: int = 1  # C_extra
    max_columns_per_request: int = 8  # C_req
    custody_columns: int = 8  # columns per node

    # Timeouts (seconds)
    provider_observation_timeout: float = 2.0
    request_timeout: float = 5.0
    tx_expiration: float = 300.0  # 5 minutes

    # Resource limits
    blobpool_max_bytes: int = 2 * 1024**3  # 2GB
    max_txs_per_sender: int = 16

    # Block production
    slot_duration: float = 12.0  # seconds per slot
    max_blobs_per_block: int = 6
    inclusion_policy: InclusionPolicy = InclusionPolicy.CONSERVATIVE

    # Simulation parameters
    seed: int = 42
    duration: float = 600.0  # 10 minutes

    # Node bandwidth (bytes/sec)
    default_bandwidth: float = 100 * 1024 * 1024  # 100 MB/s

    def __post_init__(self) -> None:
        if self.interconnection_policy is None:
            from sparse_blobpool.core.topology import GEOGRAPHIC

            object.__setattr__(self, "interconnection_policy", GEOGRAPHIC)
