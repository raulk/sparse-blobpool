"""Tests for single_node_sim.params module."""

import pytest
from dataclasses import FrozenInstanceError

from single_node_sim.availability import AvailabilityMode
from single_node_sim.params import PRESETS, EvictionPolicy, HeuristicParams


class TestHeuristicParams:
    def test_default_values(self) -> None:
        """HeuristicParams has sensible defaults."""
        params = HeuristicParams()

        assert params.max_pool_bytes == 2 * 1024**3
        assert params.max_txs_per_sender == 16
        assert params.eviction_policy == EvictionPolicy.FEE_BASED
        assert params.age_weight == 0.0
        assert params.provider_probability == 0.15
        assert params.custody_columns == 8
        assert params.tx_ttl == 300.0
        assert params.max_announcements_per_second == 100.0
        assert params.burst_allowance == 50
        assert params.availability_mode == AvailabilityMode.INSTANT
        assert params.seed == 42

    def test_frozen_dataclass(self) -> None:
        """HeuristicParams is immutable (frozen)."""
        params = HeuristicParams()

        with pytest.raises(FrozenInstanceError):
            params.max_pool_bytes = 100  # type: ignore[misc]

    def test_custom_parameter_creation(self) -> None:
        """Custom parameters can be specified."""
        params = HeuristicParams(
            max_pool_bytes=512 * 1024 * 1024,
            max_txs_per_sender=8,
            eviction_policy=EvictionPolicy.AGE_BASED,
            age_weight=0.5,
            provider_probability=0.3,
            custody_columns=16,
            tx_ttl=60.0,
            max_announcements_per_second=50.0,
            burst_allowance=25,
            availability_mode=AvailabilityMode.SIMULATED_PARTIAL,
            seed=123,
        )

        assert params.max_pool_bytes == 512 * 1024 * 1024
        assert params.max_txs_per_sender == 8
        assert params.eviction_policy == EvictionPolicy.AGE_BASED
        assert params.age_weight == 0.5
        assert params.provider_probability == 0.3
        assert params.custody_columns == 16
        assert params.tx_ttl == 60.0
        assert params.max_announcements_per_second == 50.0
        assert params.burst_allowance == 25
        assert params.availability_mode == AvailabilityMode.SIMULATED_PARTIAL
        assert params.seed == 123

    def test_params_equality(self) -> None:
        """Two HeuristicParams with same values are equal."""
        params1 = HeuristicParams(seed=100)
        params2 = HeuristicParams(seed=100)

        assert params1 == params2

    def test_params_inequality(self) -> None:
        """Two HeuristicParams with different values are not equal."""
        params1 = HeuristicParams(seed=100)
        params2 = HeuristicParams(seed=200)

        assert params1 != params2


class TestEvictionPolicy:
    def test_fee_based_policy_exists(self) -> None:
        """FEE_BASED eviction policy exists."""
        assert EvictionPolicy.FEE_BASED is not None

    def test_age_based_policy_exists(self) -> None:
        """AGE_BASED eviction policy exists."""
        assert EvictionPolicy.AGE_BASED is not None

    def test_hybrid_policy_exists(self) -> None:
        """HYBRID eviction policy exists."""
        assert EvictionPolicy.HYBRID is not None

    def test_all_policies_are_distinct(self) -> None:
        """All eviction policies are distinct."""
        policies = [EvictionPolicy.FEE_BASED, EvictionPolicy.AGE_BASED, EvictionPolicy.HYBRID]
        assert len(set(policies)) == 3


class TestPresets:
    def test_default_preset_exists(self) -> None:
        """Default preset exists and is valid."""
        assert "default" in PRESETS
        assert isinstance(PRESETS["default"], HeuristicParams)

    def test_aggressive_eviction_preset_exists(self) -> None:
        """Aggressive eviction preset exists and has reduced pool size."""
        assert "aggressive_eviction" in PRESETS
        preset = PRESETS["aggressive_eviction"]
        assert preset.max_pool_bytes == 512 * 1024 * 1024
        assert preset.age_weight == 0.3

    def test_high_provider_preset_exists(self) -> None:
        """High provider preset exists and has increased probability."""
        assert "high_provider" in PRESETS
        preset = PRESETS["high_provider"]
        assert preset.provider_probability == 0.5

    def test_strict_rate_limit_preset_exists(self) -> None:
        """Strict rate limit preset exists and has reduced rate."""
        assert "strict_rate_limit" in PRESETS
        preset = PRESETS["strict_rate_limit"]
        assert preset.max_announcements_per_second == 10.0

    def test_short_ttl_preset_exists(self) -> None:
        """Short TTL preset exists and has reduced TTL."""
        assert "short_ttl" in PRESETS
        preset = PRESETS["short_ttl"]
        assert preset.tx_ttl == 30.0

    def test_all_presets_are_valid_heuristic_params(self) -> None:
        """All presets are valid HeuristicParams instances."""
        for name, preset in PRESETS.items():
            assert isinstance(preset, HeuristicParams), f"Preset {name} is not HeuristicParams"

    def test_all_presets_are_frozen(self) -> None:
        """All presets are frozen (immutable)."""
        for name, preset in PRESETS.items():
            with pytest.raises(FrozenInstanceError):
                preset.seed = 999  # type: ignore[misc]
