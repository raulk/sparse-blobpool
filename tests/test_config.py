"""Tests for simulation configuration."""

import pytest

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
        assert config.outbound_broadcast_peer_limit == 16
        assert config.interconnection_policy == GEOGRAPHIC

        # Protocol (EIP-8070)
        assert config.provider_probability == 0.15
        assert config.legacy_protocol_probability == 0.0
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
            outbound_broadcast_peer_limit=None,
            provider_probability=0.20,
            interconnection_policy=LATENCY_AWARE,
            seed=999,
        )

        assert config.node_count == 100
        assert config.mesh_degree == 25
        assert config.outbound_broadcast_peer_limit is None
        assert config.provider_probability == 0.20
        assert config.interconnection_policy == LATENCY_AWARE
        assert config.seed == 999

    def test_outbound_broadcast_peer_limit_validation(self) -> None:
        """Outbound broadcast peer limit must be positive or unlimited."""
        SimulationConfig(outbound_broadcast_peer_limit=1)
        SimulationConfig(outbound_broadcast_peer_limit=None)

        with pytest.raises(ValueError, match="outbound_broadcast_peer_limit"):
            SimulationConfig(outbound_broadcast_peer_limit=0)

        with pytest.raises(ValueError, match="outbound_broadcast_peer_limit"):
            SimulationConfig(outbound_broadcast_peer_limit=-1)

    def test_legacy_protocol_probability_validation(self) -> None:
        """Legacy protocol probability must be in [0, 1]."""
        SimulationConfig(legacy_protocol_probability=0.0)
        SimulationConfig(legacy_protocol_probability=1.0)

        with pytest.raises(ValueError, match="legacy_protocol_probability"):
            SimulationConfig(legacy_protocol_probability=-0.1)

        with pytest.raises(ValueError, match="legacy_protocol_probability"):
            SimulationConfig(legacy_protocol_probability=1.1)

    def test_config_is_frozen(self) -> None:
        """Configuration is immutable after creation."""
        config = SimulationConfig()

        try:
            config.node_count = 100  # type: ignore[misc]
            raise AssertionError("Should have raised FrozenInstanceError")
        except AttributeError:
            pass  # Expected for frozen dataclass
