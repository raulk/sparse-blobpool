"""Tests for refactored block production.

These tests define the NEW behavior we want:
1. Simulator.nodes derives Node actors from _actors (no separate _nodes list)
2. BlockProducer sends ProduceBlock message to selected node
3. Node handles ProduceBlock - selects blobs, creates block, broadcasts
"""

import pytest

from sparse_blobpool.actors.honest import Node
from sparse_blobpool.config import Region, SimulationConfig
from sparse_blobpool.core.network import Network
from sparse_blobpool.core.simulator import Simulator
from sparse_blobpool.core.types import ActorId, Address, TxHash
from sparse_blobpool.metrics.collector import MetricsCollector
from sparse_blobpool.pool.blobpool import BlobTxEntry
from sparse_blobpool.protocol.constants import ALL_ONES


@pytest.fixture
def config() -> SimulationConfig:
    return SimulationConfig(
        slot_duration=1.0,
        max_blobs_per_block=6,
    )


@pytest.fixture
def simulator() -> Simulator:
    return Simulator(seed=42)


@pytest.fixture
def metrics(simulator: Simulator) -> MetricsCollector:
    return MetricsCollector(simulator=simulator)


@pytest.fixture
def network(simulator: Simulator, metrics: MetricsCollector) -> Network:
    net = Network(simulator, metrics)
    simulator._network = net
    return net


def create_node(
    simulator: Simulator,
    network: Network,
    config: SimulationConfig,
    node_id: str,
    region: Region = Region.NA,
) -> Node:
    """Helper to create and register a node."""
    metrics = MetricsCollector(simulator=simulator)
    node = Node(ActorId(node_id), simulator, config, custody_columns=8, metrics=metrics)
    simulator.register_actor(node)
    network.register_node(node.id, region)
    return node


def create_blob_tx(
    tx_hash: str,
    sender: str,
    nonce: int = 0,
    gas_tip_cap: int = 100000000,
    blob_count: int = 1,
    cell_mask: int = ALL_ONES,
) -> BlobTxEntry:
    return BlobTxEntry(
        tx_hash=TxHash(tx_hash),
        sender=Address(sender),
        nonce=nonce,
        gas_fee_cap=1000000000,
        gas_tip_cap=gas_tip_cap,
        blob_gas_price=1000000,
        tx_size=131072,
        blob_count=blob_count,
        cell_mask=cell_mask,
        received_at=0.0,
    )


class TestUnifiedNodes:
    """Tests for unified node access via Simulator.nodes property."""

    def test_simulator_nodes_returns_node_actors_from_actors_dict(
        self,
        simulator: Simulator,
        network: Network,
        config: SimulationConfig,
    ) -> None:
        """Simulator.nodes should return Node actors from _actors dict."""
        # Create some nodes
        node1 = create_node(simulator, network, config, "node-1")
        node2 = create_node(simulator, network, config, "node-2")

        # The nodes property should return these from _actors
        nodes = simulator.nodes
        assert len(nodes) == 2
        assert node1 in nodes
        assert node2 in nodes

    def test_simulator_nodes_excludes_non_node_actors(
        self,
        simulator: Simulator,
        network: Network,
        config: SimulationConfig,
    ) -> None:
        """Simulator.nodes should not include non-Node actors."""
        from sparse_blobpool.actors.block_producer import BlockProducer

        # Create a node and a block producer
        node = create_node(simulator, network, config, "node-1")
        bp = BlockProducer(simulator, config=config)
        simulator.register_actor(bp)

        nodes = simulator.nodes
        assert len(nodes) == 1
        assert node in nodes
        # BlockProducer should not be in nodes
        assert bp not in nodes

    def test_simulator_nodes_without_explicit_setup(
        self,
        simulator: Simulator,
    ) -> None:
        """Simulator.nodes should work without calling _nodes setter."""
        # Empty simulator should return empty list, not raise
        nodes = simulator.nodes
        assert nodes == []


class TestProduceBlockMessage:
    """Tests for ProduceBlock message handling in Node."""

    def test_produce_block_message_exists(self) -> None:
        """ProduceBlock message type should exist."""
        from sparse_blobpool.protocol.commands import ProduceBlock

        msg = ProduceBlock(sender=ActorId("block-producer"), slot=1)
        assert msg.slot == 1
        assert msg.sender == ActorId("block-producer")

    def test_node_handles_produce_block_event(
        self,
        simulator: Simulator,
        network: Network,
        config: SimulationConfig,
    ) -> None:
        """Node should handle ProduceBlock message and produce a block."""
        from sparse_blobpool.protocol.commands import ProduceBlock

        node = create_node(simulator, network, config, "node-1")

        # Add a transaction to the pool
        tx = create_blob_tx("0x" + "aa" * 32, "0x" + "11" * 20)
        node.pool.add(tx)

        # Send ProduceBlock message
        msg = ProduceBlock(sender=ActorId("block-producer"), slot=0)
        node.on_event(msg)

        # Node should have broadcast BlockAnnouncement (via network)
        # The tx should be scheduled for cleanup (meaning block was produced)
        simulator.run(until=3.0)  # Run past cleanup delay
        assert not node.pool.contains(tx.tx_hash)

    def test_node_broadcasts_block_to_peers(
        self,
        simulator: Simulator,
        network: Network,
        config: SimulationConfig,
    ) -> None:
        """Node producing a block should broadcast to all peers."""
        from sparse_blobpool.protocol.commands import ProduceBlock

        node1 = create_node(simulator, network, config, "node-1")
        node2 = create_node(simulator, network, config, "node-2")
        node3 = create_node(simulator, network, config, "node-3")

        # Set up peer connections
        node1.add_peer(node2.id)
        node1.add_peer(node3.id)
        node2.add_peer(node1.id)
        node3.add_peer(node1.id)

        # Add same tx to all nodes' pools BEFORE block production
        tx = create_blob_tx("0x" + "aa" * 32, "0x" + "11" * 20)
        node1.pool.add(tx)
        node2.pool.add(create_blob_tx("0x" + "aa" * 32, "0x" + "11" * 20))
        node3.pool.add(create_blob_tx("0x" + "aa" * 32, "0x" + "11" * 20))

        # Verify all pools contain the tx
        assert node1.pool.contains(tx.tx_hash)
        assert node2.pool.contains(tx.tx_hash)
        assert node3.pool.contains(tx.tx_hash)

        # Produce block on node1
        msg = ProduceBlock(sender=ActorId("block-producer"), slot=0)
        node1.on_event(msg)

        # Run past cleanup delay (2s) + network delay buffer
        simulator.run(until=4.0)

        # All nodes should have processed the block announcement and cleaned up
        assert not node1.pool.contains(tx.tx_hash)
        assert not node2.pool.contains(tx.tx_hash)
        assert not node3.pool.contains(tx.tx_hash)


class TestBlockProducerAsTimer:
    """Tests for BlockProducer as a simple timer."""

    def test_block_producer_sends_produce_block_message(
        self,
        simulator: Simulator,
        network: Network,
        config: SimulationConfig,
    ) -> None:
        """BlockProducer should send ProduceBlock message to selected node."""
        from sparse_blobpool.actors.block_producer import BlockProducer

        node = create_node(simulator, network, config, "node-1")

        bp = BlockProducer(simulator, config=config)
        simulator.register_actor(bp)

        # Add tx so block will be produced
        tx = create_blob_tx("0x" + "aa" * 32, "0x" + "11" * 20)
        node.pool.add(tx)

        bp.start()
        simulator.run(until=config.slot_duration + 0.1)

        # Node should have produced a block (tx scheduled for cleanup)
        simulator.run(until=config.slot_duration + 3.0)
        assert not node.pool.contains(tx.tx_hash)

    def test_block_producer_does_not_select_blobs(
        self,
        simulator: Simulator,
        network: Network,
        config: SimulationConfig,
    ) -> None:
        """BlockProducer should not have blob selection logic."""
        from sparse_blobpool.actors.block_producer import BlockProducer

        bp = BlockProducer(simulator, config=config)

        # These methods should not exist on BlockProducer
        assert not hasattr(bp, "_select_blobs")
        assert not hasattr(bp, "_is_includable")
        assert not hasattr(bp, "_broadcast_block")
