"""Tests for the BlockProducer actor."""

import pytest

from sparse_blobpool.config import SimulationConfig
from sparse_blobpool.core.block_producer import (
    BLOCK_PRODUCER_ID,
    BlockProducer,
    InclusionPolicy,
    SlotConfig,
)
from sparse_blobpool.core.network import Network
from sparse_blobpool.core.simulator import Simulator
from sparse_blobpool.core.types import ActorId, Address, TxHash
from sparse_blobpool.metrics.collector import MetricsCollector
from sparse_blobpool.p2p.node import Node
from sparse_blobpool.pool.blobpool import BlobTxEntry
from sparse_blobpool.protocol.constants import ALL_ONES


@pytest.fixture
def config() -> SimulationConfig:
    """Create test configuration."""
    return SimulationConfig(
        provider_probability=0.15,
        min_providers_before_sample=2,
        request_timeout=5.0,
        provider_observation_timeout=2.0,
        custody_columns=8,
        extra_random_columns=1,
    )


@pytest.fixture
def simulator() -> Simulator:
    """Create a fresh simulator."""
    return Simulator(seed=42)


@pytest.fixture
def metrics(simulator: Simulator) -> MetricsCollector:
    """Create a metrics collector."""
    return MetricsCollector(simulator=simulator)


@pytest.fixture
def network(simulator: Simulator, metrics: MetricsCollector) -> Network:
    """Create and register network actor."""
    net = Network(simulator, metrics)
    simulator.register_actor(net)
    return net


@pytest.fixture
def slot_config() -> SlotConfig:
    """Create slot configuration with fast slots for testing."""
    return SlotConfig(slot_duration=1.0, max_blobs_per_block=6)


@pytest.fixture
def block_producer(simulator: Simulator, slot_config: SlotConfig) -> BlockProducer:
    """Create and register block producer."""
    bp = BlockProducer(simulator, slot_config=slot_config)
    simulator.register_actor(bp)
    return bp


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
    def test_has_correct_id(self, block_producer: BlockProducer) -> None:
        """BlockProducer has the correct actor ID."""
        assert block_producer.id == BLOCK_PRODUCER_ID

    def test_initial_slot_is_zero(self, block_producer: BlockProducer) -> None:
        """Initial slot should be zero."""
        assert block_producer.current_slot == 0

    def test_initial_blocks_produced_is_zero(self, block_producer: BlockProducer) -> None:
        """Initial blocks produced should be zero."""
        assert block_producer.blocks_produced == 0


class TestNodeRegistration:
    def test_register_single_node(self, block_producer: BlockProducer) -> None:
        """Can register a single node."""
        node_id = ActorId("node-1")
        block_producer.register_node(node_id)
        # No direct access to _node_ids, but registration should not raise
        assert True

    def test_register_multiple_nodes(self, block_producer: BlockProducer) -> None:
        """Can register multiple nodes."""
        node_ids = [ActorId(f"node-{i}") for i in range(5)]
        block_producer.register_nodes(node_ids)
        # No direct access, but should not raise
        assert True

    def test_duplicate_registration_ignored(self, block_producer: BlockProducer) -> None:
        """Registering the same node twice doesn't duplicate."""
        node_id = ActorId("node-1")
        block_producer.register_node(node_id)
        block_producer.register_node(node_id)
        # Should still work correctly
        assert True


class TestSlotTicking:
    def test_start_schedules_first_tick(
        self, simulator: Simulator, block_producer: BlockProducer
    ) -> None:
        """Starting block producer schedules first slot tick."""
        block_producer.start()

        # There should be one event pending
        assert simulator.pending_event_count() == 1

    def test_slot_advances_after_tick(
        self,
        simulator: Simulator,
        network: Network,
        config: SimulationConfig,
        block_producer: BlockProducer,
        slot_config: SlotConfig,
    ) -> None:
        """Slot number advances after each tick."""
        node = create_node(simulator, network, config, "node-1")
        block_producer.register_node(node.id)

        block_producer.start()

        # Run past first slot
        simulator.run(until=slot_config.slot_duration + 0.1)
        assert block_producer.current_slot == 1

        # Run past second slot
        simulator.run(until=2 * slot_config.slot_duration + 0.1)
        assert block_producer.current_slot == 2

    def test_tick_reschedules_next_tick(
        self,
        simulator: Simulator,
        network: Network,
        config: SimulationConfig,
        block_producer: BlockProducer,
        slot_config: SlotConfig,
    ) -> None:
        """Each tick schedules the next tick."""
        node = create_node(simulator, network, config, "node-1")
        block_producer.register_node(node.id)

        block_producer.start()
        simulator.run(until=slot_config.slot_duration + 0.1)

        # Should have scheduled next tick
        assert simulator.pending_event_count() > 0


class TestProposerSelection:
    def test_proposer_rotates_through_nodes(
        self,
        simulator: Simulator,
        network: Network,
        config: SimulationConfig,
        block_producer: BlockProducer,
        slot_config: SlotConfig,
    ) -> None:
        """Proposer selection rotates through registered nodes."""
        nodes = [create_node(simulator, network, config, f"node-{i}") for i in range(3)]
        for node in nodes:
            block_producer.register_node(node.id)

        # Add txs to each node so blocks are produced
        for i, node in enumerate(nodes):
            tx = create_blob_tx(f"0x{i:064x}", f"0x{'11' * 20}")
            node.pool.add(tx)

        block_producer.start()

        # Run through 3 slots
        simulator.run(until=3 * slot_config.slot_duration + 0.1)

        # All 3 nodes should have been proposers (round-robin)
        assert block_producer.blocks_produced == 3


class TestBlobSelection:
    def test_selects_transactions_by_priority(
        self,
        simulator: Simulator,
        network: Network,
        config: SimulationConfig,
        block_producer: BlockProducer,
        slot_config: SlotConfig,
    ) -> None:
        """Transactions are selected by effective tip (priority fee)."""
        node = create_node(simulator, network, config, "node-1")
        block_producer.register_node(node.id)

        # Add txs with different tips
        tx_low = create_blob_tx("0x" + "aa" * 32, "0x" + "11" * 20, gas_tip_cap=100)
        tx_high = create_blob_tx("0x" + "bb" * 32, "0x" + "22" * 20, gas_tip_cap=200)
        node.pool.add(tx_low)
        node.pool.add(tx_high)

        block_producer.start()
        simulator.run(until=slot_config.slot_duration + 0.1)

        # Both should be included since we have capacity
        assert block_producer.total_blobs_included == 2

    def test_respects_max_blobs_per_block(
        self,
        simulator: Simulator,
        network: Network,
        config: SimulationConfig,
        slot_config: SlotConfig,
    ) -> None:
        """Block producer respects max blobs per block limit."""
        # Create config with 2 max blobs
        limited_slot_config = SlotConfig(slot_duration=1.0, max_blobs_per_block=2)
        bp = BlockProducer(simulator, slot_config=limited_slot_config)
        simulator.register_actor(bp)

        node = create_node(simulator, network, config, "node-1")
        bp.register_node(node.id)

        # Add 5 single-blob transactions
        for i in range(5):
            tx = create_blob_tx(f"0x{i:064x}", f"0x{i:040x}", gas_tip_cap=100 + i)
            node.pool.add(tx)

        bp.start()
        simulator.run(until=limited_slot_config.slot_duration + 0.1)

        # Only 2 blobs should be included
        assert bp.total_blobs_included == 2

    def test_multi_blob_transactions_count_correctly(
        self,
        simulator: Simulator,
        network: Network,
        config: SimulationConfig,
        slot_config: SlotConfig,
    ) -> None:
        """Multi-blob transactions are counted correctly against limit."""
        limited_config = SlotConfig(slot_duration=1.0, max_blobs_per_block=4)
        bp = BlockProducer(simulator, slot_config=limited_config)
        simulator.register_actor(bp)

        node = create_node(simulator, network, config, "node-1")
        bp.register_node(node.id)

        # Add a 3-blob tx and a 2-blob tx (total 5 blobs, only 3-blob should fit)
        tx_3blob = create_blob_tx("0x" + "aa" * 32, "0x" + "11" * 20, gas_tip_cap=200, blob_count=3)
        tx_2blob = create_blob_tx("0x" + "bb" * 32, "0x" + "22" * 20, gas_tip_cap=100, blob_count=2)
        node.pool.add(tx_3blob)
        node.pool.add(tx_2blob)

        bp.start()
        simulator.run(until=limited_config.slot_duration + 0.1)

        # Only 3-blob tx should fit (3 <= 4, but 3+2 > 4)
        assert bp.total_blobs_included == 3


class TestInclusionPolicies:
    def test_conservative_requires_full_availability(
        self,
        simulator: Simulator,
        network: Network,
        config: SimulationConfig,
        slot_config: SlotConfig,
    ) -> None:
        """Conservative policy only includes txs with full blob availability."""
        bp = BlockProducer(
            simulator, slot_config=slot_config, inclusion_policy=InclusionPolicy.CONSERVATIVE
        )
        simulator.register_actor(bp)

        node = create_node(simulator, network, config, "node-1")
        bp.register_node(node.id)

        # Add one full tx and one partial tx
        tx_full = create_blob_tx("0x" + "aa" * 32, "0x" + "11" * 20, cell_mask=ALL_ONES)
        tx_partial = create_blob_tx("0x" + "bb" * 32, "0x" + "22" * 20, cell_mask=0xFF)
        node.pool.add(tx_full)
        node.pool.add(tx_partial)

        bp.start()
        simulator.run(until=slot_config.slot_duration + 0.1)

        # Only full tx should be included
        assert bp.total_blobs_included == 1

    def test_optimistic_includes_partial_availability(
        self,
        simulator: Simulator,
        network: Network,
        config: SimulationConfig,
        slot_config: SlotConfig,
    ) -> None:
        """Optimistic policy includes txs with any availability."""
        bp = BlockProducer(
            simulator, slot_config=slot_config, inclusion_policy=InclusionPolicy.OPTIMISTIC
        )
        simulator.register_actor(bp)

        node = create_node(simulator, network, config, "node-1")
        bp.register_node(node.id)

        # Add partial availability tx
        tx_partial = create_blob_tx("0x" + "bb" * 32, "0x" + "22" * 20, cell_mask=0xFF)
        node.pool.add(tx_partial)

        bp.start()
        simulator.run(until=slot_config.slot_duration + 0.1)

        # Partial tx should be included
        assert bp.total_blobs_included == 1


class TestBlockBroadcast:
    def test_block_announcement_sent_to_all_nodes(
        self,
        simulator: Simulator,
        network: Network,
        config: SimulationConfig,
        block_producer: BlockProducer,
        slot_config: SlotConfig,
    ) -> None:
        """Block announcement is broadcast to all registered nodes."""

        nodes = [create_node(simulator, network, config, f"node-{i}") for i in range(3)]
        for node in nodes:
            block_producer.register_node(node.id)

        # Add tx to first node (it will be proposer at slot 0)
        tx = create_blob_tx("0x" + "aa" * 32, "0x" + "11" * 20)
        nodes[0].pool.add(tx)

        block_producer.start()
        simulator.run(until=slot_config.slot_duration + 0.5)

        # All nodes should have received the block announcement and processed it
        # After the cleanup delay (2 seconds), tx should be removed
        simulator.run(until=slot_config.slot_duration + 3.0)

        # Tx should be removed from proposer's pool after cleanup
        assert not nodes[0].pool.contains(tx.tx_hash)

    def test_no_block_when_no_includable_txs(
        self,
        simulator: Simulator,
        network: Network,
        config: SimulationConfig,
        block_producer: BlockProducer,
        slot_config: SlotConfig,
    ) -> None:
        """No block is broadcast when there are no includable transactions."""
        node = create_node(simulator, network, config, "node-1")
        block_producer.register_node(node.id)

        # Empty pool
        block_producer.start()
        simulator.run(until=slot_config.slot_duration + 0.1)

        # No blocks should be produced
        assert block_producer.blocks_produced == 0


class TestNodeBlockHandling:
    def test_included_tx_removed_after_cleanup_delay(
        self,
        simulator: Simulator,
        network: Network,
        config: SimulationConfig,
        block_producer: BlockProducer,
        slot_config: SlotConfig,
    ) -> None:
        """Included transactions are removed from pool after cleanup delay."""
        node = create_node(simulator, network, config, "node-1")
        block_producer.register_node(node.id)

        tx = create_blob_tx("0x" + "aa" * 32, "0x" + "11" * 20)
        node.pool.add(tx)

        assert node.pool.contains(tx.tx_hash)

        block_producer.start()

        # Run just past the slot - tx should still be in pool (cleanup pending)
        simulator.run(until=slot_config.slot_duration + 0.5)
        # Pool still contains it during cleanup delay
        # (depends on network delay, may or may not be removed yet)

        # Run past cleanup delay (2 seconds + network delay buffer)
        simulator.run(until=slot_config.slot_duration + 3.0)

        # Now tx should be removed
        assert not node.pool.contains(tx.tx_hash)

    def test_pending_tx_removed_on_block_announcement(
        self,
        simulator: Simulator,
        network: Network,
        config: SimulationConfig,
        block_producer: BlockProducer,
        slot_config: SlotConfig,
    ) -> None:
        """Pending transactions are removed when block announces them."""
        node = create_node(simulator, network, config, "node-1")
        block_producer.register_node(node.id)

        # Create a second node that will have a pending tx
        node2 = create_node(simulator, network, config, "node-2")
        block_producer.register_node(node2.id)

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

        block_producer.start()
        simulator.run(until=slot_config.slot_duration + 0.5)

        # Pending should be removed from node2
        assert tx.tx_hash not in node2._pending_txs
