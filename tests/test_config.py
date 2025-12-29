"""Tests for simulation configuration."""

from sparse_blobpool.config import Region, SimulationConfig, TopologyStrategy


class TestRegion:
    def test_all_regions_defined(self) -> None:
        """All expected regions are defined."""
        regions = list(Region)
        assert len(regions) == 3
        assert Region.NA in regions
        assert Region.EU in regions
        assert Region.AS in regions


class TestTopologyStrategy:
    def test_all_strategies_defined(self) -> None:
        """All expected topology strategies are defined."""
        strategies = list(TopologyStrategy)
        assert len(strategies) == 2
        assert TopologyStrategy.RANDOM_GRAPH in strategies
        assert TopologyStrategy.GEOGRAPHIC_KADEMLIA in strategies


class TestSimulationConfig:
    def test_default_values(self) -> None:
        """Default configuration matches EIP-8070 spec values."""
        config = SimulationConfig()

        # Network
        assert config.node_count == 2000
        assert config.mesh_degree == 50

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

    def test_region_distribution_sums_to_one(self) -> None:
        """Default region distribution sums to 1.0."""
        config = SimulationConfig()
        total = sum(config.region_distribution.values())
        assert abs(total - 1.0) < 0.001

    def test_region_distribution_all_regions(self) -> None:
        """Default region distribution covers all regions."""
        config = SimulationConfig()
        for region in Region:
            assert region in config.region_distribution

    def test_custom_values(self) -> None:
        """Custom configuration values are applied."""
        config = SimulationConfig(
            node_count=100,
            mesh_degree=25,
            provider_probability=0.20,
            seed=999,
        )

        assert config.node_count == 100
        assert config.mesh_degree == 25
        assert config.provider_probability == 0.20
        assert config.seed == 999

    def test_config_is_frozen(self) -> None:
        """Configuration is immutable after creation."""
        config = SimulationConfig()

        try:
            config.node_count = 100  # type: ignore[misc]
            raise AssertionError("Should have raised FrozenInstanceError")
        except AttributeError:
            pass  # Expected for frozen dataclass
