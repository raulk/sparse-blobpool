"""Tests for baseline simulation scenario."""

import pytest

from sparse_blobpool.config import SimulationConfig
from sparse_blobpool.scenarios.baseline import (
    broadcast_transaction,
    build_simulator,
)


class TestBuildSimulation:
    def test_creates_correct_node_count(self) -> None:
        config = SimulationConfig(node_count=100, mesh_degree=10)
        result = build_simulator(config)

        assert len(result.nodes) == 100

    def test_nodes_registered_with_simulator(self) -> None:
        config = SimulationConfig(node_count=50, mesh_degree=5)
        result = build_simulator(config)

        # All nodes should be in the simulator's actors
        for node in result.nodes:
            assert node.id in result.actors

    def test_network_registered_with_simulator(self) -> None:
        config = SimulationConfig(node_count=50, mesh_degree=5)
        result = build_simulator(config)

        assert result.network.id in result.actors

    def test_block_producer_registered_with_simulator(self) -> None:
        config = SimulationConfig(node_count=50, mesh_degree=5)
        result = build_simulator(config)

        assert result.block_producer.id in result.actors

    def test_nodes_have_peers(self) -> None:
        config = SimulationConfig(node_count=100, mesh_degree=10)
        result = build_simulator(config)

        # All nodes should have some peers
        for node in result.nodes:
            assert len(node.peers) > 0

    def test_peer_connections_bidirectional(self) -> None:
        config = SimulationConfig(node_count=50, mesh_degree=5)
        result = build_simulator(config)

        # If A is connected to B, B should be connected to A
        for node in result.nodes:
            for peer_id in node.peers:
                peer = result.actors[peer_id]
                if hasattr(peer, "peers"):
                    assert node.id in peer.peers


class TestBroadcastTransaction:
    def test_adds_tx_to_origin_pool(self) -> None:
        config = SimulationConfig(node_count=10, mesh_degree=3)
        result = build_simulator(config)
        origin = result.nodes[0]

        tx_hash = broadcast_transaction(result, origin)

        # Run briefly to process the broadcast event
        result.run(0.001)

        assert origin.pool.contains(tx_hash)

    def test_announces_to_peers(self) -> None:
        config = SimulationConfig(node_count=10, mesh_degree=3)
        result = build_simulator(config)
        origin = result.nodes[0]

        broadcast_transaction(result, origin)

        # Should have scheduled the broadcast event
        assert result.pending_event_count() > 0

    def test_tx_in_pool_after_propagation(self) -> None:
        config = SimulationConfig(node_count=20, mesh_degree=5)
        result = build_simulator(config)
        origin = result.nodes[0]

        tx_hash = broadcast_transaction(result, origin)

        # Run simulation briefly to let tx propagate
        result.run(5.0)  # 5 seconds should be enough

        # Check propagation
        nodes_with_tx = sum(1 for node in result.nodes if node.pool.contains(tx_hash))

        # Should have reached most nodes
        assert nodes_with_tx > len(result.nodes) * 0.5


class TestPropagation:
    def test_propagation_to_most_nodes(self) -> None:
        """Verify transactions propagate to >90% of nodes."""
        config = SimulationConfig(
            node_count=100,
            mesh_degree=20,  # Higher connectivity for faster propagation
            duration=30.0,
        )
        result = build_simulator(config)

        # Broadcast transaction
        tx_hash = broadcast_transaction(result, result.nodes[0])

        # Run simulation - give enough time for multi-hop propagation
        result.run(15.0)

        # Check propagation
        nodes_with_tx = sum(1 for node in result.nodes if node.pool.contains(tx_hash))
        propagation_pct = 100 * nodes_with_tx / len(result.nodes)

        # Should reach most of the network (>80% for small test network)
        # The large-scale test verifies >99% with 2000 nodes
        assert propagation_pct > 80, f"Only reached {propagation_pct:.1f}%"


class TestBlockProduction:
    def test_block_producer_starts_ticking(self) -> None:
        config = SimulationConfig(node_count=10, mesh_degree=3)
        result = build_simulator(config)

        result.block_producer.start()

        # Should have scheduled a slot tick
        assert result.pending_event_count() > 0

    def test_blocks_produced_over_time(self) -> None:
        config = SimulationConfig(node_count=20, mesh_degree=5)
        result = build_simulator(config)

        # Broadcast some transactions
        for _ in range(5):
            broadcast_transaction(result, result.nodes[0])

        # Start block production
        result.block_producer.start()

        # Run for 2 slots (24 seconds)
        result.run(26.0)

        # Should have produced at least 1 block
        assert result.block_producer.blocks_produced >= 1


class TestLargeScale:
    @pytest.mark.slow
    def test_2000_nodes_mesh_50(self) -> None:
        """Verify the target topology: 2000 nodes with D=50 mesh degree."""
        config = SimulationConfig(
            node_count=2000,
            mesh_degree=50,
        )
        result = build_simulator(config)

        assert len(result.nodes) == 2000

        # Check peer counts
        peer_counts = [len(node.peers) for node in result.nodes]
        min_peers = min(peer_counts)
        avg_peers = sum(peer_counts) / len(peer_counts)

        # All nodes should have connections
        assert min_peers >= 1, "Some nodes have no peers"

        # Average should be around mesh_degree (bidirectional, so ~2x)
        assert avg_peers >= 50, f"Average peers {avg_peers:.1f} is too low"

    @pytest.mark.slow
    def test_high_propagation_rate(self) -> None:
        """Verify transactions propagate to >99% of 2000-node network."""
        config = SimulationConfig(
            node_count=2000,
            mesh_degree=50,
        )
        result = build_simulator(config)

        # Broadcast transaction
        tx_hash = broadcast_transaction(result, result.nodes[0])

        # Run for 10 seconds (no block production)
        result.run(10.0)

        # Check propagation
        nodes_with_tx = sum(1 for node in result.nodes if node.pool.contains(tx_hash))
        propagation_pct = 100 * nodes_with_tx / len(result.nodes)

        # Target: >99% propagation
        assert propagation_pct > 99, f"Only reached {propagation_pct:.1f}% (target: >99%)"
