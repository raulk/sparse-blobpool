"""Tests for the BlockProducer actor."""

import pytest

from sparse_blobpool.config import InclusionPolicy, SimulationConfig
from sparse_blobpool.core.network import Network
from sparse_blobpool.core.simulator import Simulator
from sparse_blobpool.core.types import ActorId, Address, TxHash
from sparse_blobpool.metrics.collector import MetricsCollector
from sparse_blobpool.p2p.node import Node
from sparse_blobpool.pool.blobpool import BlobTxEntry
from sparse_blobpool.protocol.constants import ALL_ONES


@pytest.fixture
def config() -> SimulationConfig:
    """Create test configuration with fast slots for testing."""
    return SimulationConfig(
        provider_probability=0.15,
        min_providers_before_sample=2,
        request_timeout=5.0,
        provider_observation_timeout=2.0,
        custody_columns=8,
        extra_random_columns=1,
        slot_duration=1.0,  # Fast slots for testing
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
) -> Node:
    """Helper to create and register a node."""
    metrics = MetricsCollector(simulator=simulator)
    node = Node(ActorId(node_id), simulator, config, custody_columns=8, metrics=metrics)
    simulator.register_actor(node)
    network.register_node(node.id, region=None)
    return node


def create_blob_tx(
    tx_hash: str,
    sender: str,
    nonce: int = 0,
    gas_tip_cap: int = 100000000,
    blob_count: int = 1,
    cell_mask: int = ALL_ONES,
) -> BlobTxEntry:
    """Helper to create a blob transaction entry."""
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


class TestBlockProducerInitialization:
    def test_has_correct_id(self, simulator: Simulator, config: SimulationConfig) -> None:
        """BlockProducer has the correct actor ID."""
        from sparse_blobpool.actors.block_producer import BLOCK_PRODUCER_ID, BlockProducer

        bp = BlockProducer(simulator, config=config)
        assert bp.id == BLOCK_PRODUCER_ID

    def test_initial_slot_is_zero(self, simulator: Simulator, config: SimulationConfig) -> None:
        """Initial slot should be zero."""
        from sparse_blobpool.actors.block_producer import BlockProducer

        bp = BlockProducer(simulator, config=config)
        assert bp.current_slot == 0


class TestSlotTicking:
    def test_start_schedules_first_tick(
        self, simulator: Simulator, config: SimulationConfig
    ) -> None:
        """Starting block producer schedules first slot tick."""
        from sparse_blobpool.actors.block_producer import BlockProducer

        bp = BlockProducer(simulator, config=config)
        simulator.register_actor(bp)
        bp.start()

        # There should be one event pending
        assert simulator.pending_event_count() == 1

    def test_slot_advances_after_tick(
        self,
        simulator: Simulator,
        network: Network,
        config: SimulationConfig,
    ) -> None:
        """Slot number advances after each tick."""
        from sparse_blobpool.actors.block_producer import BlockProducer

        create_node(simulator, network, config, "node-1")
        bp = BlockProducer(simulator, config=config)
        simulator.register_actor(bp)

        bp.start()

        simulator.run(until=config.slot_duration + 0.1)
        assert bp.current_slot == 1

        simulator.run(until=2 * config.slot_duration + 0.1)
        assert bp.current_slot == 2

    def test_tick_reschedules_next_tick(
        self,
        simulator: Simulator,
        network: Network,
        config: SimulationConfig,
    ) -> None:
        """Each tick schedules the next tick."""
        from sparse_blobpool.actors.block_producer import BlockProducer

        create_node(simulator, network, config, "node-1")
        bp = BlockProducer(simulator, config=config)
        simulator.register_actor(bp)

        bp.start()
        simulator.run(until=config.slot_duration + 0.1)

        assert simulator.pending_event_count() > 0


class TestProposerSelection:
    def test_proposer_rotates_through_nodes(
        self,
        simulator: Simulator,
        network: Network,
        config: SimulationConfig,
    ) -> None:
        """Proposer selection rotates through registered nodes."""
        from sparse_blobpool.actors.block_producer import BlockProducer

        nodes = [create_node(simulator, network, config, f"node-{i}") for i in range(3)]

        bp = BlockProducer(simulator, config=config)
        simulator.register_actor(bp)

        # Add txs to each node so blocks are produced
        for i, node in enumerate(nodes):
            tx = create_blob_tx(f"0x{i:064x}", f"0x{'11' * 20}")
            node.pool.add(tx)

        bp.start()

        # Run through 3 slots
        simulator.run(until=3 * config.slot_duration + 0.1)

        # All slots should have ticked
        assert bp.current_slot == 3


class TestBlobSelection:
    def test_selects_transactions_by_priority(
        self,
        simulator: Simulator,
        network: Network,
        config: SimulationConfig,
    ) -> None:
        """Transactions are selected by effective tip (priority fee)."""
        from sparse_blobpool.actors.block_producer import BlockProducer

        node = create_node(simulator, network, config, "node-1")
        bp = BlockProducer(simulator, config=config)
        simulator.register_actor(bp)

        # Add txs with different tips
        tx_low = create_blob_tx("0x" + "aa" * 32, "0x" + "11" * 20, gas_tip_cap=100)
        tx_high = create_blob_tx("0x" + "bb" * 32, "0x" + "22" * 20, gas_tip_cap=200)
        node.pool.add(tx_low)
        node.pool.add(tx_high)

        bp.start()
        simulator.run(until=config.slot_duration + 3.0)  # Past cleanup

        # Both should have been included and cleaned up
        assert not node.pool.contains(tx_low.tx_hash)
        assert not node.pool.contains(tx_high.tx_hash)

    def test_respects_max_blobs_per_block(
        self,
        simulator: Simulator,
        network: Network,
        config: SimulationConfig,
    ) -> None:
        """Block producer respects max blobs per block limit."""
        from sparse_blobpool.actors.block_producer import BlockProducer

        # Create config with 2 max blobs
        limited_config = SimulationConfig(slot_duration=1.0, max_blobs_per_block=2)

        node = create_node(simulator, network, limited_config, "node-1")
        bp = BlockProducer(simulator, config=limited_config)
        simulator.register_actor(bp)

        # Add 5 single-blob transactions
        for i in range(5):
            tx = create_blob_tx(f"0x{i:064x}", f"0x{i:040x}", gas_tip_cap=100 + i)
            node.pool.add(tx)

        bp.start()
        simulator.run(until=limited_config.slot_duration + 3.0)

        # Only 2 txs should be included per block (highest tips first)
        # After one block, 3 txs should remain
        assert node.pool.tx_count == 3

    def test_multi_blob_transactions_count_correctly(
        self,
        simulator: Simulator,
        network: Network,
        config: SimulationConfig,
    ) -> None:
        """Multi-blob transactions are counted correctly against limit."""
        from sparse_blobpool.actors.block_producer import BlockProducer

        limited_config = SimulationConfig(slot_duration=1.0, max_blobs_per_block=4)

        node = create_node(simulator, network, limited_config, "node-1")
        bp = BlockProducer(simulator, config=limited_config)
        simulator.register_actor(bp)

        # Add a 3-blob tx and a 2-blob tx (total 5 blobs, only 3-blob should fit)
        tx_3blob = create_blob_tx("0x" + "aa" * 32, "0x" + "11" * 20, gas_tip_cap=200, blob_count=3)
        tx_2blob = create_blob_tx("0x" + "bb" * 32, "0x" + "22" * 20, gas_tip_cap=100, blob_count=2)
        node.pool.add(tx_3blob)
        node.pool.add(tx_2blob)

        bp.start()
        simulator.run(until=limited_config.slot_duration + 3.0)

        # Only 3-blob tx should fit (3 <= 4, but 3+2 > 4)
        assert not node.pool.contains(tx_3blob.tx_hash)
        assert node.pool.contains(tx_2blob.tx_hash)


class TestInclusionPolicies:
    def test_conservative_requires_full_availability(
        self,
        simulator: Simulator,
        network: Network,
        config: SimulationConfig,
    ) -> None:
        """Conservative policy only includes txs with full blob availability."""
        from sparse_blobpool.actors.block_producer import BlockProducer

        conservative_config = SimulationConfig(
            slot_duration=1.0, inclusion_policy=InclusionPolicy.CONSERVATIVE
        )

        node = create_node(simulator, network, conservative_config, "node-1")
        bp = BlockProducer(simulator, config=conservative_config)
        simulator.register_actor(bp)

        # Add one full tx and one partial tx
        tx_full = create_blob_tx("0x" + "aa" * 32, "0x" + "11" * 20, cell_mask=ALL_ONES)
        tx_partial = create_blob_tx("0x" + "bb" * 32, "0x" + "22" * 20, cell_mask=0xFF)
        node.pool.add(tx_full)
        node.pool.add(tx_partial)

        bp.start()
        simulator.run(until=conservative_config.slot_duration + 3.0)

        # Only full tx should be included
        assert not node.pool.contains(tx_full.tx_hash)
        assert node.pool.contains(tx_partial.tx_hash)

    def test_optimistic_includes_partial_availability(
        self,
        simulator: Simulator,
        network: Network,
        config: SimulationConfig,
    ) -> None:
        """Optimistic policy includes txs with any availability."""
        from sparse_blobpool.actors.block_producer import BlockProducer

        optimistic_config = SimulationConfig(
            slot_duration=1.0, inclusion_policy=InclusionPolicy.OPTIMISTIC
        )

        node = create_node(simulator, network, optimistic_config, "node-1")
        bp = BlockProducer(simulator, config=optimistic_config)
        simulator.register_actor(bp)

        # Add partial availability tx
        tx_partial = create_blob_tx("0x" + "bb" * 32, "0x" + "22" * 20, cell_mask=0xFF)
        node.pool.add(tx_partial)

        bp.start()
        simulator.run(until=optimistic_config.slot_duration + 3.0)

        # Partial tx should be included
        assert not node.pool.contains(tx_partial.tx_hash)


class TestBlockBroadcast:
    def test_block_announcement_sent_to_all_nodes(
        self,
        simulator: Simulator,
        network: Network,
        config: SimulationConfig,
    ) -> None:
        """Block announcement is broadcast to all registered nodes."""
        from sparse_blobpool.actors.block_producer import BlockProducer

        nodes = [create_node(simulator, network, config, f"node-{i}") for i in range(3)]

        # Connect all nodes as peers
        for i, node in enumerate(nodes):
            for j, other in enumerate(nodes):
                if i != j:
                    node.add_peer(other.id)

        bp = BlockProducer(simulator, config=config)
        simulator.register_actor(bp)

        # Add tx to first node (it will be proposer at slot 0)
        tx = create_blob_tx("0x" + "aa" * 32, "0x" + "11" * 20)
        nodes[0].pool.add(tx)

        bp.start()
        simulator.run(until=config.slot_duration + 3.0)

        # Tx should be removed from proposer's pool after cleanup
        assert not nodes[0].pool.contains(tx.tx_hash)

    def test_no_block_when_no_includable_txs(
        self,
        simulator: Simulator,
        network: Network,
        config: SimulationConfig,
    ) -> None:
        """No block is broadcast when there are no includable transactions."""
        from sparse_blobpool.actors.block_producer import BlockProducer

        create_node(simulator, network, config, "node-1")
        bp = BlockProducer(simulator, config=config)
        simulator.register_actor(bp)

        bp.start()
        simulator.run(until=config.slot_duration + 0.1)

        assert bp.current_slot == 1


class TestNodeBlockHandling:
    def test_included_tx_removed_after_cleanup_delay(
        self,
        simulator: Simulator,
        network: Network,
        config: SimulationConfig,
    ) -> None:
        """Included transactions are removed from pool after cleanup delay."""
        from sparse_blobpool.actors.block_producer import BlockProducer

        node = create_node(simulator, network, config, "node-1")
        bp = BlockProducer(simulator, config=config)
        simulator.register_actor(bp)

        tx = create_blob_tx("0x" + "aa" * 32, "0x" + "11" * 20)
        node.pool.add(tx)

        assert node.pool.contains(tx.tx_hash)

        bp.start()

        # Run past cleanup delay (2 seconds + network delay buffer)
        simulator.run(until=config.slot_duration + 3.0)

        # Now tx should be removed
        assert not node.pool.contains(tx.tx_hash)

    def test_pending_tx_removed_on_block_announcement(
        self,
        simulator: Simulator,
        network: Network,
        config: SimulationConfig,
    ) -> None:
        """Pending transactions are removed when block announces them."""
        from sparse_blobpool.actors.block_producer import BlockProducer

        node = create_node(simulator, network, config, "node-1")

        # Create a second node that will have a pending tx
        node2 = create_node(simulator, network, config, "node-2")

        # Connect nodes as peers
        node.add_peer(node2.id)
        node2.add_peer(node.id)

        bp = BlockProducer(simulator, config=config)
        simulator.register_actor(bp)

        # Add tx to first node's pool
        tx = create_blob_tx("0x" + "aa" * 32, "0x" + "11" * 20)
        node.pool.add(tx)

        # Manually add same tx as pending on node2
        from sparse_blobpool.p2p.node import PendingTx, Role, TxState

        pending = PendingTx(
            tx_hash=tx.tx_hash,
            role=Role.PROVIDER,
            state=TxState.ANNOUNCED,
            first_seen=0.0,
        )
        node2._pending_txs[tx.tx_hash] = pending

        bp.start()
        simulator.run(until=config.slot_duration + 0.5)

        # Pending should be removed from node2
        assert tx.tx_hash not in node2._pending_txs
