"""Property-based tests for role distribution."""

from hypothesis import given, settings
from hypothesis import strategies as st

from sparse_blobpool.config import SimulationConfig
from sparse_blobpool.core.simulator import Simulator
from sparse_blobpool.core.types import ActorId, TxHash
from sparse_blobpool.metrics.collector import MetricsCollector
from sparse_blobpool.p2p.node import Node, Role


def make_node(
    actor_id: ActorId, simulator: Simulator, config: SimulationConfig, custody_columns: int = 8
) -> Node:
    """Create a node with default metrics."""
    metrics = MetricsCollector(simulator=simulator)
    return Node(actor_id, simulator, config, custody_columns, metrics)


class TestRoleDistribution:
    """Property-based tests for node role determination."""

    @given(
        node_id=st.text(min_size=1, max_size=32, alphabet="abcdef0123456789"),
        tx_hash=st.text(min_size=32, max_size=64, alphabet="abcdef0123456789"),
    )
    @settings(max_examples=100)
    def test_role_is_deterministic(self, node_id: str, tx_hash: str) -> None:
        """Same node+tx always produces same role."""
        sim = Simulator()
        config = SimulationConfig()
        node = make_node(ActorId(node_id), sim, config, custody_columns=8)

        role1 = node._determine_role(TxHash(tx_hash))
        role2 = node._determine_role(TxHash(tx_hash))

        assert role1 == role2

    @given(
        seed=st.integers(min_value=0, max_value=2**32 - 1),
    )
    @settings(max_examples=20)
    def test_provider_ratio_approximately_correct(self, seed: int) -> None:
        """Provider ratio should be approximately p=0.15 over many samples."""
        sim = Simulator(seed=seed)
        config = SimulationConfig(provider_probability=0.15)
        node = make_node(ActorId(f"node_{seed}"), sim, config, custody_columns=8)

        # Generate many tx hashes and count providers
        num_samples = 1000
        provider_count = 0

        for i in range(num_samples):
            tx_hash = TxHash(f"{seed:08x}{i:08x}")
            role = node._determine_role(tx_hash)
            if role == Role.PROVIDER:
                provider_count += 1

        observed_ratio = provider_count / num_samples

        # Should be within 5% of target (0.15 ± 0.05)
        assert 0.10 <= observed_ratio <= 0.20

    @given(
        p=st.floats(min_value=0.01, max_value=0.99),
        seed=st.integers(min_value=0, max_value=2**16),
    )
    @settings(max_examples=10)
    def test_provider_probability_respected(self, p: float, seed: int) -> None:
        """Provider probability parameter affects role distribution."""
        sim = Simulator(seed=seed)
        config = SimulationConfig(provider_probability=p)
        node = make_node(ActorId(f"node_{seed}"), sim, config, custody_columns=8)

        num_samples = 500
        provider_count = 0

        for i in range(num_samples):
            tx_hash = TxHash(f"{seed:04x}{i:04x}00")
            role = node._determine_role(tx_hash)
            if role == Role.PROVIDER:
                provider_count += 1

        observed_ratio = provider_count / num_samples

        # Should be within 15% of target probability (generous for small samples)
        assert abs(observed_ratio - p) < 0.15

    def test_different_nodes_get_different_roles(self) -> None:
        """Different nodes should get different roles for same tx."""
        sim = Simulator(seed=42)
        config = SimulationConfig(provider_probability=0.5)  # 50% for clearer test

        # Create multiple nodes
        nodes = [make_node(ActorId(f"node_{i}"), sim, config, custody_columns=8) for i in range(20)]

        tx_hash = TxHash("deadbeef" * 8)

        # Count unique roles (should see both)
        roles = {node._determine_role(tx_hash) for node in nodes}

        # With 50% probability and 20 nodes, extremely likely to see both roles
        assert len(roles) == 2  # Both PROVIDER and SAMPLER

    @given(
        tx_hashes=st.lists(
            st.text(min_size=32, max_size=64, alphabet="0123456789abcdef"),
            min_size=10,
            max_size=50,
        ),
    )
    @settings(max_examples=20)
    def test_role_only_depends_on_node_and_tx(self, tx_hashes: list[str]) -> None:
        """Role determination only depends on node ID and tx hash."""
        sim1 = Simulator(seed=1)
        sim2 = Simulator(seed=999)  # Different seed
        config = SimulationConfig()

        node1 = make_node(ActorId("same_node"), sim1, config, custody_columns=8)
        node2 = make_node(ActorId("same_node"), sim2, config, custody_columns=8)

        # Same node ID should produce same roles regardless of simulator state
        for tx_hash_str in tx_hashes:
            tx_hash = TxHash(tx_hash_str)
            assert node1._determine_role(tx_hash) == node2._determine_role(tx_hash)


class TestCustodyMask:
    """Property-based tests for custody mask generation."""

    @given(
        node_id=st.text(min_size=1, max_size=32, alphabet="abcdef0123456789"),
    )
    @settings(max_examples=50)
    def test_custody_mask_is_deterministic(self, node_id: str) -> None:
        """Same node ID always produces same custody mask."""
        sim = Simulator()
        config = SimulationConfig()

        node1 = make_node(ActorId(node_id), sim, config, custody_columns=8)
        node2 = make_node(ActorId(node_id), sim, config, custody_columns=8)

        assert node1._custody_mask == node2._custody_mask

    @given(
        columns=st.integers(min_value=1, max_value=32),
        seed=st.integers(min_value=0, max_value=2**16),
    )
    @settings(max_examples=30)
    def test_custody_mask_has_correct_bits(self, columns: int, seed: int) -> None:
        """Custody mask has exactly the right number of bits set."""
        sim = Simulator(seed=seed)
        config = SimulationConfig()

        node = make_node(ActorId(f"node_{seed}"), sim, config, custody_columns=columns)

        # Count bits set in mask
        bit_count = bin(node._custody_mask).count("1")

        assert bit_count == columns
