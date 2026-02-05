from dataclasses import dataclass
from enum import Enum, auto

from single_node_sim.availability import AvailabilityMode


class EvictionPolicy(Enum):
    FEE_BASED = auto()
    AGE_BASED = auto()
    HYBRID = auto()


@dataclass(frozen=True)
class HeuristicParams:
    max_pool_bytes: int = 2 * 1024**3
    max_txs_per_sender: int = 16
    eviction_policy: EvictionPolicy = EvictionPolicy.FEE_BASED
    age_weight: float = 0.0
    provider_probability: float = 0.15
    custody_columns: int = 8
    tx_ttl: float = 300.0
    max_announcements_per_second: float = 100.0
    burst_allowance: int = 50
    availability_mode: AvailabilityMode = AvailabilityMode.INSTANT
    seed: int = 42


PRESETS: dict[str, HeuristicParams] = {
    "default": HeuristicParams(),
    "aggressive_eviction": HeuristicParams(max_pool_bytes=512 * 1024 * 1024, age_weight=0.3),
    "high_provider": HeuristicParams(provider_probability=0.5),
    "strict_rate_limit": HeuristicParams(max_announcements_per_second=10.0),
    "short_ttl": HeuristicParams(tx_ttl=30.0),
}
