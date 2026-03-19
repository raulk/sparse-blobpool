from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any

CELLS_PER_BLOB = 128
ALL_ONES = (1 << CELLS_PER_BLOB) - 1
RECONSTRUCTION_THRESHOLD = 64
DEFAULT_MESH_DEGREE = 50
MAX_TXS_PER_SENDER = 16
ANNOUNCE_MSG_BYTES = 200
CELL_BYTES = 2048
REQUEST_MSG_OVERHEAD = 64


def columns_to_mask(columns: list[int]) -> int:
    mask = 0
    for c in columns:
        mask |= 1 << c
    return mask


def mask_to_columns(mask: int) -> list[int]:
    return [i for i in range(CELLS_PER_BLOB) if mask & (1 << i)]


def popcount(mask: int) -> int:
    return bin(mask).count("1")


class Role(Enum):
    PROVIDER = auto()
    SAMPLER = auto()


class EvictionPolicy(Enum):
    FEE_BASED = auto()
    AGE_BASED = auto()
    HYBRID = auto()


@dataclass(frozen=True)
class HeuristicConfig:
    includability_discount: float = 0.7
    saturation_timeout: float = 30.0
    min_independent_peers: int = 2
    c_extra_max: int = 4
    max_random_failure_rate: float = 0.1
    tracking_window: int = 100
    k_high: int = 2
    k_low: int = 4
    score_threshold: float = 0.5
    conservative_inclusion: bool = True
    provider_probability: float = 0.15
    custody_columns: int = 8
    tx_ttl: float = 300.0
    pool_capacity: int = 15000
    blob_base_fee: float = 1.0
    max_request_to_announce_ratio: float = 5.0
    inbound_score_discount: float = 0.15
    provider_rate_tolerance: float = 0.3
    eviction_policy: EvictionPolicy = EvictionPolicy.FEE_BASED
    age_weight: float = 0.5
    max_announcements_per_second: float = 100.0
    burst_allowance: int = 50


PRESETS: dict[str, HeuristicConfig] = {
    "default": HeuristicConfig(),
    "aggressive_eviction": HeuristicConfig(
        pool_capacity=5000,
        eviction_policy=EvictionPolicy.HYBRID,
    ),
    "strict_rate_limit": HeuristicConfig(
        max_announcements_per_second=10.0,
        burst_allowance=20,
    ),
    "short_ttl": HeuristicConfig(tx_ttl=30.0),
    "high_provider": HeuristicConfig(provider_probability=0.5),
}


@dataclass
class Scenario:
    n_honest: int = 40
    attackers: list[tuple[int, str, dict[str, Any]]] = field(default_factory=list)
    tx_arrival_rate: float = 2.0
    t_end: float = 300.0
    blob_base_fee: float = 1.0
    block_interval: float = 12.0
    inbound_ratio: float = 0.68
