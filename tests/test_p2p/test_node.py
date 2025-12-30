"""Tests for the Node actor."""

import pytest

from sparse_blobpool.config import SimulationConfig
from sparse_blobpool.core.network import Network
from sparse_blobpool.core.simulator import Simulator
from sparse_blobpool.core.types import ActorId, TxHash
from sparse_blobpool.metrics.collector import MetricsCollector
from sparse_blobpool.p2p.node import Node, Role, TxState
from sparse_blobpool.protocol.constants import ALL_ONES
from sparse_blobpool.protocol.messages import (
    Cells,
    GetCells,
    GetPooledTransactions,
    NewPooledTransactionHashes,
    PooledTransactions,
    TxBody,
)


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
    """Create and configure network."""
    net = Network(simulator, metrics)
    simulator._network = net
    return net


@pytest.fixture
def node(
    simulator: Simulator, network: Network, config: SimulationConfig, metrics: MetricsCollector
) -> Node:
    """Create a test node."""
    n = Node(ActorId("node-1"), simulator, config, custody_columns=8, metrics=metrics)
    simulator.register_actor(n)
    network.register_node(n.id, region=None)
    return n


def make_node(
    actor_id: ActorId, simulator: Simulator, config: SimulationConfig, custody_columns: int = 8
) -> Node:
    """Create a node with default metrics."""
    metrics = MetricsCollector(simulator=simulator)
    return Node(actor_id, simulator, config, custody_columns, metrics)


class TestRoleDetermination:
    def test_role_is_deterministic(self, simulator: Simulator, config: SimulationConfig) -> None:
        """Same node + tx_hash always produces same role."""
        node = make_node(ActorId("test-node"), simulator, config)

        tx_hash = TxHash("0x" + "ab" * 32)
        role1 = node._determine_role(tx_hash)
        role2 = node._determine_role(tx_hash)

        assert role1 == role2

    def test_role_distribution_approximates_p(
        self, simulator: Simulator, config: SimulationConfig
    ) -> None:
        """Role distribution should approximate provider_probability over many txs."""
        node = make_node(ActorId("test-node"), simulator, config)

        provider_count = 0
        total = 1000

        for i in range(total):
            tx_hash = TxHash(f"0x{i:064x}")
            if node._determine_role(tx_hash) == Role.PROVIDER:
                provider_count += 1

        # Allow 5% deviation from expected 15%
        ratio = provider_count / total
        assert 0.10 <= ratio <= 0.20, f"Provider ratio {ratio} outside expected range"

    def test_different_nodes_get_different_roles(
        self, simulator: Simulator, config: SimulationConfig
    ) -> None:
        """Different nodes should get different role assignments for same tx."""
        node1 = make_node(ActorId("node-1"), simulator, config)
        node2 = make_node(ActorId("node-2"), simulator, config)

        # Test with enough txs to find at least one difference
        different_found = False
        for i in range(100):
            tx_hash = TxHash(f"0x{i:064x}")
            if node1._determine_role(tx_hash) != node2._determine_role(tx_hash):
                different_found = True
                break

        assert different_found, "Nodes should have different roles for at least some txs"


class TestCustodyMask:
    def test_custody_mask_has_correct_bit_count(
        self, simulator: Simulator, config: SimulationConfig
    ) -> None:
        """Custody mask should have exactly custody_columns bits set."""
        node = make_node(ActorId("test-node"), simulator, config)

        bit_count = bin(node._custody_mask).count("1")
        assert bit_count == 8

    def test_custody_mask_is_deterministic(
        self, simulator: Simulator, config: SimulationConfig
    ) -> None:
        """Same node ID should produce same custody mask."""
        sim1 = Simulator(seed=1)
        sim2 = Simulator(seed=2)
        node1 = make_node(ActorId("test-node"), sim1, config)
        node2 = make_node(ActorId("test-node"), sim2, config)

        # Note: custody mask uses node ID hash, not simulator RNG
        assert node1._custody_mask == node2._custody_mask

    def test_different_nodes_have_different_custody(
        self, simulator: Simulator, config: SimulationConfig
    ) -> None:
        """Different nodes should have different custody assignments."""
        node1 = make_node(ActorId("node-1"), simulator, config)
        node2 = make_node(ActorId("node-2"), simulator, config)

        assert node1._custody_mask != node2._custody_mask


class TestAnnouncementHandling:
    def test_new_tx_creates_pending_entry(
        self, node: Node, simulator: Simulator, network: Network
    ) -> None:
        """Receiving announcement for new tx creates pending entry."""
        peer = ActorId("peer-1")
        node.add_peer(peer)

        tx_hash = TxHash("0x" + "ab" * 32)
        msg = NewPooledTransactionHashes(
            sender=peer,
            types=bytes([3]),
            sizes=[131072],
            hashes=[tx_hash],
            cell_mask=ALL_ONES,
        )

        # Deliver message directly
        node.on_event(msg)

        assert tx_hash in node._pending_txs
        pending = node._pending_txs[tx_hash]
        assert peer in pending.provider_peers

    def test_duplicate_announcement_adds_peer(
        self, node: Node, simulator: Simulator, network: Network
    ) -> None:
        """Duplicate announcement from different peer adds that peer."""
        peer1 = ActorId("peer-1")
        peer2 = ActorId("peer-2")
        node.add_peer(peer1)
        node.add_peer(peer2)

        tx_hash = TxHash("0x" + "ab" * 32)

        msg1 = NewPooledTransactionHashes(
            sender=peer1,
            types=bytes([3]),
            sizes=[131072],
            hashes=[tx_hash],
            cell_mask=ALL_ONES,
        )
        msg2 = NewPooledTransactionHashes(
            sender=peer2,
            types=bytes([3]),
            sizes=[131072],
            hashes=[tx_hash],
            cell_mask=ALL_ONES,
        )

        node.on_event(msg1)
        node.on_event(msg2)

        pending = node._pending_txs[tx_hash]
        assert peer1 in pending.provider_peers
        assert peer2 in pending.provider_peers

    def test_known_tx_ignored(self, node: Node, simulator: Simulator, network: Network) -> None:
        """Announcement for tx already in pool is ignored."""
        from sparse_blobpool.core.types import Address
        from sparse_blobpool.pool.blobpool import BlobTxEntry

        tx_hash = TxHash("0x" + "ab" * 32)

        # Add tx to pool
        entry = BlobTxEntry(
            tx_hash=tx_hash,
            sender=Address("0x" + "11" * 20),
            nonce=0,
            gas_fee_cap=1000000000,
            gas_tip_cap=100000000,
            blob_gas_price=1000000,
            tx_size=131072,
            blob_count=1,
            cell_mask=ALL_ONES,
            received_at=0.0,
        )
        node.pool.add(entry)

        peer = ActorId("peer-1")
        msg = NewPooledTransactionHashes(
            sender=peer,
            types=bytes([3]),
            sizes=[131072],
            hashes=[tx_hash],
            cell_mask=ALL_ONES,
        )

        node.on_event(msg)

        # Should not create pending entry
        assert tx_hash not in node._pending_txs

    def test_non_blob_tx_ignored(self, node: Node, simulator: Simulator, network: Network) -> None:
        """Non-blob transactions (type != 3) are ignored."""
        peer = ActorId("peer-1")
        tx_hash = TxHash("0x" + "ab" * 32)

        msg = NewPooledTransactionHashes(
            sender=peer,
            types=bytes([2]),  # Type 2 = EIP-1559, not blob
            sizes=[1000],
            hashes=[tx_hash],
            cell_mask=None,
        )

        node.on_event(msg)

        assert tx_hash not in node._pending_txs


class TestProviderFlow:
    def test_provider_requests_full_blob(
        self,
        simulator: Simulator,
        network: Network,
        config: SimulationConfig,
        metrics: MetricsCollector,
    ) -> None:
        """Provider role should request all cells."""
        # Create a node that will be provider for our test tx
        # We need to find a tx_hash that makes this node a provider
        node = Node(ActorId("provider-node"), simulator, config, custody_columns=8, metrics=metrics)
        simulator.register_actor(node)
        network.register_node(node.id, region=None)

        peer = ActorId("peer-1")
        node.add_peer(peer)

        # Create peer actor to receive requests
        from sparse_blobpool.core.actor import Actor, EventPayload

        class RequestRecorder(Actor):
            def __init__(self, actor_id: ActorId, sim: Simulator) -> None:
                super().__init__(actor_id, sim)
                self.received: list[EventPayload] = []

            def on_event(self, payload: EventPayload) -> None:
                self.received.append(payload)

        peer_actor = RequestRecorder(peer, simulator)
        simulator.register_actor(peer_actor)
        network.register_node(peer, region=None)

        # Find a tx that makes this node a provider
        for i in range(100):
            tx_hash = TxHash(f"0x{i:064x}")
            if node._determine_role(tx_hash) == Role.PROVIDER:
                break
        else:
            pytest.skip("Could not find a tx that makes node a provider")

        msg = NewPooledTransactionHashes(
            sender=peer,
            types=bytes([3]),
            sizes=[131072],
            hashes=[tx_hash],
            cell_mask=ALL_ONES,
        )

        node.on_event(msg)

        # Run simulation to deliver messages
        simulator.run(until=1.0)

        # Should have received GetPooledTransactions
        get_tx_msgs = [m for m in peer_actor.received if isinstance(m, GetPooledTransactions)]
        assert len(get_tx_msgs) == 1
        assert tx_hash in get_tx_msgs[0].tx_hashes


class TestSamplerFlow:
    def test_sampler_waits_for_providers(
        self,
        simulator: Simulator,
        network: Network,
        config: SimulationConfig,
        metrics: MetricsCollector,
    ) -> None:
        """Sampler should wait for min_providers_before_sample provider announcements."""
        node = Node(ActorId("sampler-node"), simulator, config, custody_columns=8, metrics=metrics)
        simulator.register_actor(node)
        network.register_node(node.id, region=None)

        # Find a tx that makes this node a sampler
        for i in range(100):
            tx_hash = TxHash(f"0x{i:064x}")
            if node._determine_role(tx_hash) == Role.SAMPLER:
                break
        else:
            pytest.skip("Could not find a tx that makes node a sampler")

        peer1 = ActorId("peer-1")
        node.add_peer(peer1)

        # First provider announcement
        msg1 = NewPooledTransactionHashes(
            sender=peer1,
            types=bytes([3]),
            sizes=[131072],
            hashes=[tx_hash],
            cell_mask=ALL_ONES,
        )
        node.on_event(msg1)

        pending = node._pending_txs[tx_hash]
        assert pending.state == TxState.AWAITING_PROVIDERS

        # Second provider announcement should trigger fetch
        peer2 = ActorId("peer-2")
        node.add_peer(peer2)

        msg2 = NewPooledTransactionHashes(
            sender=peer2,
            types=bytes([3]),
            sizes=[131072],
            hashes=[tx_hash],
            cell_mask=ALL_ONES,
        )
        node.on_event(msg2)

        # Now should be fetching
        assert pending.state == TxState.FETCHING_TX


class TestResponseHandling:
    def test_pooled_transactions_response(
        self, node: Node, simulator: Simulator, network: Network
    ) -> None:
        """PooledTransactions response advances state to fetching cells."""
        peer = ActorId("peer-1")
        node.add_peer(peer)

        tx_hash = TxHash("0x" + "ab" * 32)

        # Create pending tx manually
        from sparse_blobpool.p2p.node import PendingTx

        pending = PendingTx(
            tx_hash=tx_hash,
            role=Role.PROVIDER,
            state=TxState.FETCHING_TX,
            first_seen=0.0,
        )
        pending.provider_peers.add(peer)
        node._pending_txs[tx_hash] = pending

        # Send response
        response = PooledTransactions(
            sender=peer,
            transactions=[TxBody(tx_hash=tx_hash, tx_bytes=131072)],
        )
        node.on_event(response)

        assert pending.tx_body_received
        assert pending.state == TxState.FETCHING_CELLS

    def test_cells_response_completes_provider(
        self, node: Node, simulator: Simulator, network: Network
    ) -> None:
        """Cells response with all cells completes provider flow."""
        peer = ActorId("peer-1")
        node.add_peer(peer)

        tx_hash = TxHash("0x" + "ab" * 32)

        from sparse_blobpool.p2p.node import PendingTx
        from sparse_blobpool.protocol.messages import Cell

        pending = PendingTx(
            tx_hash=tx_hash,
            role=Role.PROVIDER,
            state=TxState.FETCHING_CELLS,
            first_seen=0.0,
        )
        pending.provider_peers.add(peer)
        pending.tx_body_received = True
        node._pending_txs[tx_hash] = pending

        # Send cells response with all cells
        cells_response = Cells(
            sender=peer,
            tx_hashes=[tx_hash],
            cells=[[Cell(data=b"\x00" * 2048, proof=b"\x00" * 48) for _ in range(128)]],
            cell_mask=ALL_ONES,
        )
        node.on_event(cells_response)

        # Should be removed from pending and added to pool
        assert tx_hash not in node._pending_txs
        assert node.pool.contains(tx_hash)

    def test_cells_response_completes_sampler(
        self, node: Node, simulator: Simulator, network: Network
    ) -> None:
        """Cells response with custody cells completes sampler flow."""
        peer = ActorId("peer-1")
        node.add_peer(peer)

        tx_hash = TxHash("0x" + "ab" * 32)

        from sparse_blobpool.p2p.node import PendingTx

        pending = PendingTx(
            tx_hash=tx_hash,
            role=Role.SAMPLER,
            state=TxState.FETCHING_CELLS,
            first_seen=0.0,
        )
        pending.provider_peers.add(peer)
        pending.tx_body_received = True
        node._pending_txs[tx_hash] = pending

        # Send cells response with custody columns
        custody_mask = node._custody_mask
        cells_response = Cells(
            sender=peer,
            tx_hashes=[tx_hash],
            cells=[[]],  # Cells list structure doesn't matter for mask tracking
            cell_mask=custody_mask,
        )
        node.on_event(cells_response)

        # Should be completed
        assert tx_hash not in node._pending_txs
        assert node.pool.contains(tx_hash)


class TestRequestHandling:
    def test_get_pooled_transactions_returns_known_txs(
        self, node: Node, simulator: Simulator, network: Network
    ) -> None:
        """GetPooledTransactions returns transactions from pool."""
        from sparse_blobpool.core.types import Address
        from sparse_blobpool.pool.blobpool import BlobTxEntry

        tx_hash = TxHash("0x" + "ab" * 32)
        entry = BlobTxEntry(
            tx_hash=tx_hash,
            sender=Address("0x" + "11" * 20),
            nonce=0,
            gas_fee_cap=1000000000,
            gas_tip_cap=100000000,
            blob_gas_price=1000000,
            tx_size=131072,
            blob_count=1,
            cell_mask=ALL_ONES,
            received_at=0.0,
        )
        node.pool.add(entry)

        # Create peer to receive response
        from sparse_blobpool.core.actor import Actor, EventPayload

        class ResponseRecorder(Actor):
            def __init__(self, actor_id: ActorId, sim: Simulator) -> None:
                super().__init__(actor_id, sim)
                self.received: list[EventPayload] = []

            def on_event(self, payload: EventPayload) -> None:
                self.received.append(payload)

        peer = ActorId("peer-1")
        peer_actor = ResponseRecorder(peer, simulator)
        simulator.register_actor(peer_actor)
        network.register_node(peer, region=None)

        # Send request
        request = GetPooledTransactions(sender=peer, tx_hashes=[tx_hash])
        node.on_event(request)

        simulator.run(until=1.0)

        responses = [m for m in peer_actor.received if isinstance(m, PooledTransactions)]
        assert len(responses) == 1
        assert responses[0].transactions[0] is not None
        assert responses[0].transactions[0].tx_hash == tx_hash

    def test_get_cells_returns_available_cells(
        self, node: Node, simulator: Simulator, network: Network
    ) -> None:
        """GetCells returns cells from pool based on availability mask."""
        from sparse_blobpool.core.types import Address
        from sparse_blobpool.pool.blobpool import BlobTxEntry

        tx_hash = TxHash("0x" + "ab" * 32)
        entry = BlobTxEntry(
            tx_hash=tx_hash,
            sender=Address("0x" + "11" * 20),
            nonce=0,
            gas_fee_cap=1000000000,
            gas_tip_cap=100000000,
            blob_gas_price=1000000,
            tx_size=131072,
            blob_count=1,
            cell_mask=ALL_ONES,  # All cells available
            received_at=0.0,
        )
        node.pool.add(entry)

        from sparse_blobpool.core.actor import Actor, EventPayload

        class ResponseRecorder(Actor):
            def __init__(self, actor_id: ActorId, sim: Simulator) -> None:
                super().__init__(actor_id, sim)
                self.received: list[EventPayload] = []

            def on_event(self, payload: EventPayload) -> None:
                self.received.append(payload)

        peer = ActorId("peer-1")
        peer_actor = ResponseRecorder(peer, simulator)
        simulator.register_actor(peer_actor)
        network.register_node(peer, region=None)

        # Request specific columns
        request_mask = 0b11111111  # First 8 columns
        request = GetCells(sender=peer, tx_hashes=[tx_hash], cell_mask=request_mask)
        node.on_event(request)

        simulator.run(until=1.0)

        responses = [m for m in peer_actor.received if isinstance(m, Cells)]
        assert len(responses) == 1
        assert responses[0].cell_mask & request_mask == request_mask


class TestPeerManagement:
    def test_add_peer(self, node: Node) -> None:
        """Can add peers to node."""
        peer = ActorId("peer-1")
        node.add_peer(peer)
        assert peer in node.peers

    def test_remove_peer(self, node: Node) -> None:
        """Can remove peers from node."""
        peer = ActorId("peer-1")
        node.add_peer(peer)
        node.remove_peer(peer)
        assert peer not in node.peers

    def test_remove_nonexistent_peer_is_safe(self, node: Node) -> None:
        """Removing non-existent peer doesn't raise."""
        peer = ActorId("nonexistent")
        node.remove_peer(peer)  # Should not raise


class TestAnnouncement:
    def test_completed_tx_announced_to_peers(
        self,
        simulator: Simulator,
        network: Network,
        config: SimulationConfig,
        metrics: MetricsCollector,
    ) -> None:
        """Completed transaction is announced to all peers."""
        node = Node(ActorId("test-node"), simulator, config, custody_columns=8, metrics=metrics)
        simulator.register_actor(node)
        network.register_node(node.id, region=None)

        from sparse_blobpool.core.actor import Actor, EventPayload

        class AnnouncementRecorder(Actor):
            def __init__(self, actor_id: ActorId, sim: Simulator) -> None:
                super().__init__(actor_id, sim)
                self.received: list[EventPayload] = []

            def on_event(self, payload: EventPayload) -> None:
                self.received.append(payload)

        peers = [ActorId(f"peer-{i}") for i in range(3)]
        peer_actors = []
        for peer in peers:
            actor = AnnouncementRecorder(peer, simulator)
            simulator.register_actor(actor)
            network.register_node(peer, region=None)
            node.add_peer(peer)
            peer_actors.append(actor)

        # Complete a transaction
        from sparse_blobpool.core.types import Address
        from sparse_blobpool.pool.blobpool import BlobTxEntry

        tx_hash = TxHash("0x" + "cd" * 32)
        entry = BlobTxEntry(
            tx_hash=tx_hash,
            sender=Address("0x" + "11" * 20),
            nonce=0,
            gas_fee_cap=1000000000,
            gas_tip_cap=100000000,
            blob_gas_price=1000000,
            tx_size=131072,
            blob_count=1,
            cell_mask=ALL_ONES,
            received_at=0.0,
        )
        node.pool.add(entry)
        node._announce_tx(entry)

        simulator.run(until=1.0)

        # All peers should receive announcement
        for actor in peer_actors:
            announcements = [m for m in actor.received if isinstance(m, NewPooledTransactionHashes)]
            assert len(announcements) == 1
            assert tx_hash in announcements[0].hashes
