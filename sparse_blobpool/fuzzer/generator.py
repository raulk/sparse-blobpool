from __future__ import annotations

from typing import TYPE_CHECKING

import coolname.impl

from sparse_blobpool.config import SimulationConfig
from sparse_blobpool.core.topology import (
    DIVERSE,
    GEOGRAPHIC,
    LATENCY_AWARE,
    RANDOM,
)

if TYPE_CHECKING:
    from random import Random

    from sparse_blobpool.core.topology import InterconnectionPolicy
    from sparse_blobpool.fuzzer.config import IntRange, ParameterRanges

INTERCONNECTION_POLICIES: list[InterconnectionPolicy] = [
    RANDOM,
    GEOGRAPHIC,
    LATENCY_AWARE,
    DIVERSE,
]


def generate_run_id(rng: Random) -> str:
    coolname.impl.replace_random(rng)
    words = coolname.impl.generate(3)
    return "-".join(words)


def generate_num_transactions(rng: Random, range_: IntRange) -> int:
    return rng.randint(range_[0], range_[1])


def generate_simulation_config(
    rng: Random,
    ranges: ParameterRanges,
    duration: float,
) -> SimulationConfig:
    return SimulationConfig(
        node_count=rng.randint(*ranges.node_count),
        mesh_degree=rng.randint(*ranges.mesh_degree),
        interconnection_policy=rng.choice(INTERCONNECTION_POLICIES),
        provider_probability=rng.uniform(*ranges.provider_probability),
        min_providers_before_sample=rng.randint(*ranges.min_providers_before_sample),
        extra_random_columns=rng.randint(*ranges.extra_random_columns),
        max_columns_per_request=rng.randint(*ranges.max_columns_per_request),
        custody_columns=rng.randint(*ranges.custody_columns),
        provider_observation_timeout=rng.uniform(*ranges.provider_observation_timeout),
        request_timeout=rng.uniform(*ranges.request_timeout),
        tx_expiration=rng.uniform(*ranges.tx_expiration),
        blobpool_max_bytes=rng.randint(*ranges.blobpool_max_bytes),
        max_txs_per_sender=rng.randint(*ranges.max_txs_per_sender),
        default_bandwidth=rng.uniform(*ranges.default_bandwidth),
        duration=duration,
        seed=rng.randint(0, 2**31 - 1),
    )


def validate_config(config: SimulationConfig) -> tuple[bool, list[str]]:
    errors: list[str] = []

    if config.mesh_degree > config.node_count - 1:
        errors.append(
            f"mesh_degree ({config.mesh_degree}) > node_count - 1 ({config.node_count - 1})"
        )

    if config.custody_columns > 128:
        errors.append(f"custody_columns ({config.custody_columns}) > 128")

    if config.max_columns_per_request > config.custody_columns:
        errors.append(
            f"max_columns_per_request ({config.max_columns_per_request}) > "
            f"custody_columns ({config.custody_columns})"
        )

    if config.request_timeout <= config.provider_observation_timeout:
        errors.append(
            f"request_timeout ({config.request_timeout}) <= "
            f"provider_observation_timeout ({config.provider_observation_timeout})"
        )

    return (len(errors) == 0, errors)


def config_to_dict(config: SimulationConfig) -> dict[str, object]:
    policy_name = config.interconnection_policy.__name__
    return {
        "node_count": config.node_count,
        "interconnection_policy": policy_name,
        "mesh_degree": config.mesh_degree,
        "provider_probability": config.provider_probability,
        "min_providers_before_sample": config.min_providers_before_sample,
        "extra_random_columns": config.extra_random_columns,
        "max_columns_per_request": config.max_columns_per_request,
        "custody_columns": config.custody_columns,
        "provider_observation_timeout": config.provider_observation_timeout,
        "request_timeout": config.request_timeout,
        "tx_expiration": config.tx_expiration,
        "blobpool_max_bytes": config.blobpool_max_bytes,
        "max_txs_per_sender": config.max_txs_per_sender,
        "slot_duration": config.slot_duration,
        "max_blobs_per_block": config.max_blobs_per_block,
        "inclusion_policy": config.inclusion_policy.name,
        "seed": config.seed,
        "duration": config.duration,
        "default_bandwidth": config.default_bandwidth,
    }
