"""Tests for simulation configuration."""

from sparse_blobpool.config import SimulationConfig
from sparse_blobpool.core.topology import (
    DIVERSE,
    GEOGRAPHIC,
    LATENCY_AWARE,
    RANDOM,
)


class TestInterconnectionPolicy:
    def test_all_policies_are_callable(self) -> None:
        """All interconnection policies are callable functions."""
        assert callable(RANDOM)
        assert callable(GEOGRAPHIC)
        assert callable(LATENCY_AWARE)
        assert callable(DIVERSE)


class TestSimulationConfig:
    def test_default_values(self) -> None:
        """Default configuration matches EIP-8070 spec values."""
        config = SimulationConfig()

        # Network
        assert config.node_count == 2000
        assert config.mesh_degree == 50
        assert config.interconnection_policy == GEOGRAPHIC

        # Protocol (EIP-8070)
        assert config.provider_probability == 0.15
        assert config.min_providers_before_sample == 2
        assert config.extra_random_columns == 1
        assert config.max_columns_per_request == 8
        assert config.custody_columns == 8

        # Timeouts
        assert config.provider_observation_timeout == 2.0
        assert config.request_timeout == 5.0
        assert config.tx_expiration == 300.0

        # Resources
        assert config.blobpool_max_bytes == 2 * 1024**3
        assert config.max_txs_per_sender == 16

        # Simulation
        assert config.seed == 42
        assert config.duration == 600.0

    def test_custom_values(self) -> None:
        """Custom configuration values are applied."""
        config = SimulationConfig(
            node_count=100,
            mesh_degree=25,
            provider_probability=0.20,
            interconnection_policy=LATENCY_AWARE,
            seed=999,
        )

        assert config.node_count == 100
        assert config.mesh_degree == 25
        assert config.provider_probability == 0.20
        assert config.interconnection_policy == LATENCY_AWARE
        assert config.seed == 999

    def test_config_is_frozen(self) -> None:
        """Configuration is immutable after creation."""
        config = SimulationConfig()

        try:
            config.node_count = 100  # type: ignore[misc]
            raise AssertionError("Should have raised FrozenInstanceError")
        except AttributeError:
            pass  # Expected for frozen dataclass
