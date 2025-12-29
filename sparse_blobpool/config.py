"""Simulation configuration."""

from dataclasses import dataclass, field
from enum import Enum, auto


class Region(Enum):
    """Geographic regions for network latency modeling."""

    NA = auto()  # North America
    EU = auto()  # Europe
    AS = auto()  # Asia


class TopologyStrategy(Enum):
    """Network topology generation strategies."""

    RANDOM_GRAPH = auto()
    GEOGRAPHIC_KADEMLIA = auto()


@dataclass(frozen=True)
class SimulationConfig:
    """Configuration for the sparse blobpool simulation."""

    # Network topology
    node_count: int = 2000
    region_distribution: dict[Region, float] = field(
        default_factory=lambda: {
            Region.NA: 0.4,
            Region.EU: 0.4,
            Region.AS: 0.2,
        }
    )
    topology: TopologyStrategy = TopologyStrategy.GEOGRAPHIC_KADEMLIA
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

    # Simulation parameters
    seed: int = 42
    duration: float = 600.0  # 10 minutes

    # Node bandwidth (bytes/sec)
    default_bandwidth: float = 100 * 1024 * 1024  # 100 MB/s
