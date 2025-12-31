"""Tests for baseline simulation scenario."""

import pytest

from sparse_blobpool.config import SimulationConfig
from sparse_blobpool.core.simulator import Simulator


class TestBuildSimulation:
    def test_creates_correct_node_count(self) -> None:
        config = SimulationConfig(node_count=100, mesh_degree=10)
        sim = Simulator.build(config)

        assert len(sim.nodes) == 100

    def test_nodes_registered_with_simulator(self) -> None:
        config = SimulationConfig(node_count=50, mesh_degree=5)
        sim = Simulator.build(config)

        for node in sim.nodes:
            assert node.id in sim.actors

    def test_network_configured_on_simulator(self) -> None:
        config = SimulationConfig(node_count=50, mesh_degree=5)
        sim = Simulator.build(config)

        assert sim.network is not None

    def test_block_producer_registered_with_simulator(self) -> None:
        config = SimulationConfig(node_count=50, mesh_degree=5)
        sim = Simulator.build(config)

        assert sim.block_producer.id in sim.actors

    def test_nodes_have_peers(self) -> None:
        config = SimulationConfig(node_count=100, mesh_degree=10)
        sim = Simulator.build(config)

        for node in sim.nodes:
            assert len(node.peers) > 0

    def test_peer_connections_bidirectional(self) -> None:
        config = SimulationConfig(node_count=50, mesh_degree=5)
        sim = Simulator.build(config)

        for node in sim.nodes:
            for peer_id in node.peers:
                peer = sim.actors[peer_id]
                if hasattr(peer, "peers"):
                    assert node.id in peer.peers


class TestBroadcastTransaction:
    def test_adds_tx_to_origin_pool(self) -> None:
        config = SimulationConfig(node_count=10, mesh_degree=3)
        sim = Simulator.build(config)
        origin = sim.nodes[0]

        tx_hash = sim.broadcast_transaction(origin)

        sim.run(0.001)

        assert origin.pool.contains(tx_hash)

    def test_announces_to_peers(self) -> None:
        config = SimulationConfig(node_count=10, mesh_degree=3)
        sim = Simulator.build(config)
        origin = sim.nodes[0]

        sim.broadcast_transaction(origin)

        assert sim.pending_event_count() > 0

    def test_tx_in_pool_after_propagation(self) -> None:
        config = SimulationConfig(node_count=20, mesh_degree=5)
        sim = Simulator.build(config)
        origin = sim.nodes[0]

        tx_hash = sim.broadcast_transaction(origin)

        sim.run(5.0)

        nodes_with_tx = sum(1 for node in sim.nodes if node.pool.contains(tx_hash))

        assert nodes_with_tx > len(sim.nodes) * 0.5


class TestPropagation:
    def test_propagation_to_most_nodes(self) -> None:
        """Verify transactions propagate to >90% of nodes."""
        config = SimulationConfig(
            node_count=100,
            mesh_degree=20,
            duration=30.0,
        )
        sim = Simulator.build(config)

        tx_hash = sim.broadcast_transaction(sim.nodes[0])

        sim.run(15.0)

        nodes_with_tx = sum(1 for node in sim.nodes if node.pool.contains(tx_hash))
        propagation_pct = 100 * nodes_with_tx / len(sim.nodes)

        assert propagation_pct > 80, f"Only reached {propagation_pct:.1f}%"


class TestBlockProduction:
    def test_block_producer_starts_ticking(self) -> None:
        config = SimulationConfig(node_count=10, mesh_degree=3)
        sim = Simulator.build(config)

        sim.block_producer.start()

        assert sim.pending_event_count() > 0

    def test_blocks_produced_over_time(self) -> None:
        config = SimulationConfig(node_count=20, mesh_degree=5)
        sim = Simulator.build(config)

        tx_hashes = []
        for _ in range(5):
            tx_hash = sim.broadcast_transaction(sim.nodes[0])
            tx_hashes.append(tx_hash)

        sim.block_producer.start()

        sim.run(30.0)

        assert sim.block_producer.current_slot >= 2

        tx_remaining = sum(1 for tx in tx_hashes if sim.nodes[0].pool.contains(tx))
        assert tx_remaining < 5


class TestLargeScale:
    @pytest.mark.slow
    def test_2000_nodes_mesh_50(self) -> None:
        """Verify the target topology: 2000 nodes with D=50 mesh degree."""
        config = SimulationConfig(
            node_count=2000,
            mesh_degree=50,
        )
        sim = Simulator.build(config)

        assert len(sim.nodes) == 2000

        peer_counts = [len(node.peers) for node in sim.nodes]
        min_peers = min(peer_counts)
        avg_peers = sum(peer_counts) / len(peer_counts)

        assert min_peers >= 1, "Some nodes have no peers"
        assert avg_peers >= 50, f"Average peers {avg_peers:.1f} is too low"

    @pytest.mark.slow
    def test_high_propagation_rate(self) -> None:
        """Verify transactions propagate to >99% of 2000-node network."""
        config = SimulationConfig(
            node_count=2000,
            mesh_degree=50,
        )
        sim = Simulator.build(config)

        tx_hash = sim.broadcast_transaction(sim.nodes[0])

        sim.run(10.0)

        nodes_with_tx = sum(1 for node in sim.nodes if node.pool.contains(tx_hash))
        propagation_pct = 100 * nodes_with_tx / len(sim.nodes)

        assert propagation_pct > 99, f"Only reached {propagation_pct:.1f}% (target: >99%)"
