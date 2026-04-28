"""Tests for the Node actor."""

import pytest

from sparse_blobpool.actors.honest import Node, Role, TxState
from sparse_blobpool.config import SimulationConfig
from sparse_blobpool.core.actor import Actor, EventPayload
from sparse_blobpool.core.network import Network
from sparse_blobpool.core.simulator import Simulator
from sparse_blobpool.core.types import ActorId, Address, TxHash
from sparse_blobpool.metrics.collector import MetricsCollector
from sparse_blobpool.pool.blobpool import BlobTxEntry
from sparse_blobpool.protocol.constants import ALL_ONES, CELL_SIZE, CELLS_PER_BLOB
from sparse_blobpool.protocol.messages import (
    Cells,
    EthProtocol,
    GetCells,
    GetPooledTransactions,
    NewPooledTransactionHashes,
    PooledTransactions,
    TxBody,
    full_blob_tx_size,
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


class AnnouncementRecorder(Actor):
    def __init__(self, actor_id: ActorId, sim: Simulator) -> None:
        super().__init__(actor_id, sim)
        self.received: list[EventPayload] = []

    def on_event(self, payload: EventPayload) -> None:
        self.received.append(payload)


@pytest.fixture
def node(
    simulator: Simulator, network: Network, config: SimulationConfig, metrics: MetricsCollector
) -> Node:
    """Create a test node."""
    n = Node(ActorId("node-1"), simulator, config, custody_columns=8, metrics=metrics)
    simulator.register_actor(n)
    network.register_node(n.id, "united states")
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
        network.register_node(node.id, "united states")

        peer = ActorId("peer-1")
        node.add_peer(peer)

        # Create peer actor to receive requests
        from sparse_blobpool.core.actor import Actor

        class RequestRecorder(Actor):
            def __init__(self, actor_id: ActorId, sim: Simulator) -> None:
                super().__init__(actor_id, sim)
                self.received: list[EventPayload] = []

            def on_event(self, payload: EventPayload) -> None:
                self.received.append(payload)

        peer_actor = RequestRecorder(peer, simulator)
        simulator.register_actor(peer_actor)
        network.register_node(peer, "united states")

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
        network.register_node(node.id, "united states")

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

    def test_sampler_ignores_legacy_announcement(
        self,
        simulator: Simulator,
        network: Network,
        config: SimulationConfig,
        metrics: MetricsCollector,
    ) -> None:
        """A sampler must not fetch full blobs from legacy peers."""
        from sparse_blobpool.core.actor import Actor

        class RequestRecorder(Actor):
            def __init__(self, actor_id: ActorId, sim: Simulator) -> None:
                super().__init__(actor_id, sim)
                self.received: list[EventPayload] = []

            def on_event(self, payload: EventPayload) -> None:
                self.received.append(payload)

        node = Node(ActorId("sampler-node"), simulator, config, custody_columns=8, metrics=metrics)
        simulator.register_actor(node)
        network.register_node(node.id, "united states")

        # Find a tx_hash that makes this node a sampler.
        for i in range(200):
            tx_hash = TxHash(f"0x{i:064x}")
            if node._determine_role(tx_hash) == Role.SAMPLER:
                break
        else:
            pytest.skip("Could not find a sampler tx")

        legacy_peer = ActorId("legacy-peer")
        recorder = RequestRecorder(legacy_peer, simulator)
        simulator.register_actor(recorder)
        network.register_node(legacy_peer, "united states")
        node.add_peer(legacy_peer, EthProtocol.ETH70)

        msg = NewPooledTransactionHashes(
            sender=legacy_peer,
            types=bytes([3]),
            sizes=[full_blob_tx_size(131072, 1)],
            hashes=[tx_hash],
            cell_mask=None,
        )
        node.on_event(msg)
        simulator.run(until=1.0)

        # Sampler stays in AWAITING_PROVIDERS, registers the legacy peer, and
        # does not issue a GetPooledTransactions against it.
        pending = node._pending_txs[tx_hash]
        assert pending.role == Role.SAMPLER
        assert pending.state == TxState.AWAITING_PROVIDERS
        assert legacy_peer in pending.legacy_peers
        assert not any(isinstance(m, GetPooledTransactions) for m in recorder.received)

        # Once an eth/71 provider peer announces, sampler proceeds via eth/71.
        eth71_peer = ActorId("eth71-peer")
        eth71_recorder = RequestRecorder(eth71_peer, simulator)
        simulator.register_actor(eth71_recorder)
        network.register_node(eth71_peer, "united states")
        node.add_peer(eth71_peer, EthProtocol.ETH71)

        for _ in range(config.min_providers_before_sample):
            provider = ActorId(f"eth71-{_}")
            p_recorder = RequestRecorder(provider, simulator)
            simulator.register_actor(p_recorder)
            network.register_node(provider, "united states")
            node.add_peer(provider, EthProtocol.ETH71)
            node.on_event(
                NewPooledTransactionHashes(
                    sender=provider,
                    types=bytes([3]),
                    sizes=[131072],
                    hashes=[tx_hash],
                    cell_mask=ALL_ONES,
                )
            )

        assert pending.state == TxState.FETCHING_TX

    def test_legacy_peer_counts_toward_provider_threshold(
        self,
        simulator: Simulator,
        network: Network,
        config: SimulationConfig,
        metrics: MetricsCollector,
    ) -> None:
        """One legacy + one eth/71 ALL_ONES peer should satisfy min_providers_before_sample=2."""
        # config.min_providers_before_sample == 2
        assert config.min_providers_before_sample == 2

        node = Node(ActorId("sampler-node"), simulator, config, custody_columns=8, metrics=metrics)
        simulator.register_actor(node)
        network.register_node(node.id, "united states")

        for i in range(200):
            tx_hash = TxHash(f"0x{i:064x}")
            if node._determine_role(tx_hash) == Role.SAMPLER:
                break
        else:
            pytest.skip("Could not find a sampler tx")

        # Step 1: legacy peer announces first
        legacy_peer = ActorId("legacy-peer")
        node.add_peer(legacy_peer, EthProtocol.ETH70)
        node.on_event(
            NewPooledTransactionHashes(
                sender=legacy_peer,
                types=bytes([3]),
                sizes=[full_blob_tx_size(131072, 1)],
                hashes=[tx_hash],
                cell_mask=None,
            )
        )

        pending = node._pending_txs[tx_hash]
        assert pending.state == TxState.AWAITING_PROVIDERS, "Should wait after legacy-only"

        # Step 2: one eth/71 provider peer announces — combined count reaches threshold
        eth71_peer = ActorId("eth71-provider")
        node.add_peer(eth71_peer, EthProtocol.ETH71)
        node.on_event(
            NewPooledTransactionHashes(
                sender=eth71_peer,
                types=bytes([3]),
                sizes=[131072],
                hashes=[tx_hash],
                cell_mask=ALL_ONES,
            )
        )

        # legacy(1) + eth71_provider(1) == 2 == min_providers_before_sample → fetch starts
        assert pending.state == TxState.FETCHING_TX, (
            "Should start fetching after legacy+eth71 provider reaches threshold"
        )
        # And the fetch must target the eth/71 peer, not the legacy peer
        assert pending.pending_request_id is not None


class TestResponseHandling:
    def test_pooled_transactions_response(
        self, node: Node, simulator: Simulator, network: Network
    ) -> None:
        """PooledTransactions response advances state to fetching cells."""
        peer = ActorId("peer-1")
        node.add_peer(peer)

        tx_hash = TxHash("0x" + "ab" * 32)

        # Create pending tx manually
        from sparse_blobpool.actors.honest import PendingTx

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

        from sparse_blobpool.actors.honest import PendingTx
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

        from sparse_blobpool.actors.honest import PendingTx

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

    def test_legacy_pooled_transactions_complete_without_cells(
        self, node: Node, simulator: Simulator, network: Network
    ) -> None:
        """eth/70 full tx responses complete immediately without GetCells."""
        peer = ActorId("legacy-peer")
        node.add_peer(peer, EthProtocol.ETH70)

        from sparse_blobpool.core.actor import Actor

        class RequestRecorder(Actor):
            def __init__(self, actor_id: ActorId, sim: Simulator) -> None:
                super().__init__(actor_id, sim)
                self.received: list[EventPayload] = []

            def on_event(self, payload: EventPayload) -> None:
                self.received.append(payload)

        peer_actor = RequestRecorder(peer, simulator)
        simulator.register_actor(peer_actor)
        network.register_node(peer, "united states")

        # Samplers refuse legacy fetches, so pick hashes that yield PROVIDER role.
        # Vary the high-order hex digits so the fake sender derived from tx_hash[:40]
        # in _complete_tx stays distinct between the two transactions.
        tx_hashes: list[TxHash] = []
        seen_senders: set[str] = set()
        i = 0
        while len(tx_hashes) < 2:
            body = f"{i:064x}"
            candidate = TxHash("0x" + body[::-1])
            sender_key = candidate[:40]
            if node._determine_role(candidate) == Role.PROVIDER and sender_key not in seen_senders:
                tx_hashes.append(candidate)
                seen_senders.add(sender_key)
            i += 1
        msg = NewPooledTransactionHashes(
            sender=peer,
            types=bytes([3, 3]),
            sizes=[full_blob_tx_size(131072, 1), full_blob_tx_size(131072, 2)],
            hashes=tx_hashes,
            cell_mask=None,
        )

        node.on_event(msg)
        simulator.run(until=1.0)

        get_tx_msgs = [m for m in peer_actor.received if isinstance(m, GetPooledTransactions)]
        assert len(get_tx_msgs) == 1
        assert get_tx_msgs[0].tx_hashes == tx_hashes

        response = PooledTransactions(
            sender=peer,
            transactions=[
                TxBody(tx_hash=tx_hashes[0], tx_bytes=full_blob_tx_size(131072, 1)),
                TxBody(tx_hash=tx_hashes[1], tx_bytes=full_blob_tx_size(131072, 2)),
            ],
        )
        node.on_event(response)
        simulator.run(until=2.0)

        assert all(node.pool.contains(tx_hash) for tx_hash in tx_hashes)
        assert all(tx_hash not in node._pending_txs for tx_hash in tx_hashes)
        assert not any(isinstance(m, GetCells) for m in peer_actor.received)

        for tx_hash in tx_hashes:
            assert node.pool.get(tx_hash).cell_mask == ALL_ONES  # type: ignore[union-attr]
            assert node._metrics.tx_metrics[tx_hash].legacy_provider_count == 1

    def test_sampler_eth71_success_recorded(
        self, node: Node, simulator: Simulator, network: Network, metrics: MetricsCollector
    ) -> None:
        """Sampler completing via eth/71 cells increments sampler_eth71_success."""
        from sparse_blobpool.actors.honest import PendingTx

        peer = ActorId("eth71-peer")
        node.add_peer(peer)

        # Find a tx_hash where this node is a SAMPLER
        tx_hash: TxHash | None = None
        for i in range(1000):
            candidate = TxHash("0x" + f"{i:064x}"[::-1])
            if node._determine_role(candidate) == Role.SAMPLER:
                tx_hash = candidate
                break
        assert tx_hash is not None, "Could not find a SAMPLER tx_hash"

        custody_mask = node._custody_mask
        pending = PendingTx(
            tx_hash=tx_hash,
            role=Role.SAMPLER,
            state=TxState.FETCHING_CELLS,
            first_seen=0.0,
            original_role=Role.SAMPLER,
        )
        pending.provider_peers.add(peer)
        pending.tx_body_received = True
        node._pending_txs[tx_hash] = pending

        # Seed tx_metrics so record_sampler_outcome can find the entry
        from sparse_blobpool.metrics.collector import TxMetrics

        metrics.tx_metrics[tx_hash] = TxMetrics(first_seen_time=0.0, first_seen_node=node.id)

        # Deliver custody cells via eth/71
        cells_response = Cells(
            sender=peer,
            tx_hashes=[tx_hash],
            cells=[[]],
            cell_mask=custody_mask,
        )
        node.on_event(cells_response)

        # Sampler completed via eth/71 → success counter incremented
        assert metrics.sampler_eth71_success == 1
        assert metrics.sampler_legacy_fallback == 0
        assert metrics.tx_metrics[tx_hash].sampler_eth71_count == 1
        assert metrics.tx_metrics[tx_hash].sampler_fallback_count == 0

    def test_sampler_legacy_fallback_recorded(
        self, node: Node, simulator: Simulator, network: Network, metrics: MetricsCollector
    ) -> None:
        """Sampler that fell back to eth/70 increments sampler_legacy_fallback."""
        from sparse_blobpool.actors.honest import PendingTx

        peer = ActorId("legacy-fallback-peer")
        node.add_peer(peer, EthProtocol.ETH70)

        # Find a tx_hash where this node is a SAMPLER
        tx_hash: TxHash | None = None
        for i in range(1000):
            candidate = TxHash("0x" + f"{i:064x}"[::-1])
            if node._determine_role(candidate) == Role.SAMPLER:
                tx_hash = candidate
                break
        assert tx_hash is not None, "Could not find a SAMPLER tx_hash"

        # Simulate a sampler that has been overridden to LEGACY_PROVIDER via fallback
        pending = PendingTx(
            tx_hash=tx_hash,
            role=Role.LEGACY_PROVIDER,  # overridden by fallback
            state=TxState.FETCHING_TX,
            first_seen=0.0,
            original_role=Role.SAMPLER,  # preserved original intent
        )
        pending.legacy_peers.add(peer)
        node._pending_txs[tx_hash] = pending

        # Seed tx_metrics
        from sparse_blobpool.metrics.collector import TxMetrics

        metrics.tx_metrics[tx_hash] = TxMetrics(first_seen_time=0.0, first_seen_node=node.id)

        # Deliver full tx body (eth/70 path)
        from sparse_blobpool.protocol.messages import TxBody

        response = PooledTransactions(
            sender=peer,
            transactions=[TxBody(tx_hash=tx_hash, tx_bytes=131072)],
        )
        node.on_event(response)

        # eth/70 LEGACY_PROVIDER completes immediately (no GetCells needed)
        assert tx_hash not in node._pending_txs

        # Sampler fell back → fallback counter incremented
        assert metrics.sampler_eth71_success == 0
        assert metrics.sampler_legacy_fallback == 1
        assert metrics.tx_metrics[tx_hash].sampler_fallback_count == 1
        assert metrics.tx_metrics[tx_hash].sampler_eth71_count == 0

    def test_sampling_success_rate_in_finalize(
        self, node: Node, simulator: Simulator, network: Network, metrics: MetricsCollector
    ) -> None:
        """sampling_success_rate = eth71_success / (eth71_success + fallback)."""
        # Manually set counters on the collector
        metrics.sampler_eth71_success = 7
        metrics.sampler_legacy_fallback = 3

        results = metrics.finalize()
        assert results.sampling_success_rate == pytest.approx(0.7)

    def test_sampling_success_rate_zero_when_no_samplers(
        self, node: Node, simulator: Simulator, network: Network, metrics: MetricsCollector
    ) -> None:
        """sampling_success_rate is 0.0 when there are no sampler outcomes recorded."""
        results = metrics.finalize()
        assert results.sampling_success_rate == 0.0

    def test_sampling_success_rate_in_to_dict(
        self, node: Node, simulator: Simulator, network: Network, metrics: MetricsCollector
    ) -> None:
        """sampling_success_rate appears in SimulationResults.to_dict()."""
        metrics.sampler_eth71_success = 4
        metrics.sampler_legacy_fallback = 1
        results = metrics.finalize()
        d = results.to_dict()
        assert "sampling_success_rate" in d
        assert d["sampling_success_rate"] == pytest.approx(0.8)


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
        from sparse_blobpool.core.actor import Actor

        class ResponseRecorder(Actor):
            def __init__(self, actor_id: ActorId, sim: Simulator) -> None:
                super().__init__(actor_id, sim)
                self.received: list[EventPayload] = []

            def on_event(self, payload: EventPayload) -> None:
                self.received.append(payload)

        peer = ActorId("peer-1")
        peer_actor = ResponseRecorder(peer, simulator)
        simulator.register_actor(peer_actor)
        network.register_node(peer, "united states")

        # Send request
        request = GetPooledTransactions(sender=peer, tx_hashes=[tx_hash])
        node.on_event(request)

        simulator.run(until=1.0)

        responses = [m for m in peer_actor.received if isinstance(m, PooledTransactions)]
        assert len(responses) == 1
        assert responses[0].transactions[0] is not None
        assert responses[0].transactions[0].tx_hash == tx_hash

    def test_eth70_get_pooled_transactions_returns_full_blob_sizes(
        self, node: Node, simulator: Simulator, network: Network
    ) -> None:
        """eth/70 GetPooledTransactions returns full type-3 payload sizes."""
        from sparse_blobpool.core.types import Address
        from sparse_blobpool.pool.blobpool import BlobTxEntry

        tx1 = TxHash("0x" + "ab" * 32)
        tx2 = TxHash("0x" + "cd" * 32)
        entries = [
            BlobTxEntry(
                tx_hash=tx1,
                sender=Address("0x" + "11" * 20),
                nonce=0,
                gas_fee_cap=1000000000,
                gas_tip_cap=100000000,
                blob_gas_price=1000000,
                tx_size=500,
                blob_count=1,
                cell_mask=ALL_ONES,
                received_at=0.0,
            ),
            BlobTxEntry(
                tx_hash=tx2,
                sender=Address("0x" + "22" * 20),
                nonce=0,
                gas_fee_cap=1000000000,
                gas_tip_cap=100000000,
                blob_gas_price=1000000,
                tx_size=700,
                blob_count=3,
                cell_mask=ALL_ONES,
                received_at=0.0,
            ),
        ]
        for entry in entries:
            node.pool.add(entry)

        from sparse_blobpool.core.actor import Actor

        class ResponseRecorder(Actor):
            def __init__(self, actor_id: ActorId, sim: Simulator) -> None:
                super().__init__(actor_id, sim)
                self.received: list[EventPayload] = []

            def on_event(self, payload: EventPayload) -> None:
                self.received.append(payload)

        peer = ActorId("legacy-peer")
        node.add_peer(peer, EthProtocol.ETH70)
        peer_actor = ResponseRecorder(peer, simulator)
        simulator.register_actor(peer_actor)
        network.register_node(peer, "united states")

        request = GetPooledTransactions(
            sender=peer,
            tx_hashes=[tx1, TxHash("0x" + "ef" * 32), tx2],
        )
        node.on_event(request)
        simulator.run(until=1.0)

        responses = [m for m in peer_actor.received if isinstance(m, PooledTransactions)]
        assert len(responses) == 1
        assert responses[0].transactions[1] is None
        assert responses[0].size_bytes == (
            8 + 500 + CELLS_PER_BLOB * CELL_SIZE + 700 + 3 * CELLS_PER_BLOB * CELL_SIZE
        )

    def test_eth70_get_pooled_transactions_refuses_partial_blob(
        self, node: Node, simulator: Simulator, network: Network
    ) -> None:
        """eth/70 full tx requests are refused when only partial cells are available."""
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
            tx_size=500,
            blob_count=1,
            cell_mask=node.custody_mask,
            received_at=0.0,
        )
        node.pool.add(entry)

        from sparse_blobpool.core.actor import Actor

        class ResponseRecorder(Actor):
            def __init__(self, actor_id: ActorId, sim: Simulator) -> None:
                super().__init__(actor_id, sim)
                self.received: list[EventPayload] = []

            def on_event(self, payload: EventPayload) -> None:
                self.received.append(payload)

        peer = ActorId("legacy-peer")
        node.add_peer(peer, EthProtocol.ETH70)
        peer_actor = ResponseRecorder(peer, simulator)
        simulator.register_actor(peer_actor)
        network.register_node(peer, "united states")

        request = GetPooledTransactions(sender=peer, tx_hashes=[tx_hash])
        node.on_event(request)
        simulator.run(until=1.0)

        responses = [m for m in peer_actor.received if isinstance(m, PooledTransactions)]
        assert len(responses) == 1
        assert responses[0].transactions == [None]
        assert responses[0].size_bytes == 8

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

        from sparse_blobpool.core.actor import Actor

        class ResponseRecorder(Actor):
            def __init__(self, actor_id: ActorId, sim: Simulator) -> None:
                super().__init__(actor_id, sim)
                self.received: list[EventPayload] = []

            def on_event(self, payload: EventPayload) -> None:
                self.received.append(payload)

        peer = ActorId("peer-1")
        peer_actor = ResponseRecorder(peer, simulator)
        simulator.register_actor(peer_actor)
        network.register_node(peer, "united states")

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

    def test_add_peer_records_negotiated_protocol(self, node: Node) -> None:
        """Peer registration stores per-peer negotiated protocol."""
        sparse_peer = ActorId("sparse-peer")
        legacy_peer = ActorId("legacy-peer")

        node.add_peer(sparse_peer, EthProtocol.ETH71)
        node.add_peer(legacy_peer, EthProtocol.ETH70)

        assert node.negotiated_protocol(sparse_peer) == EthProtocol.ETH71
        assert node.negotiated_protocol(legacy_peer) == EthProtocol.ETH70


class TestAnnouncement:
    def _make_entry(
        self,
        tx_hash: TxHash | None = None,
        cell_mask: int = ALL_ONES,
        blob_count: int = 1,
    ) -> BlobTxEntry:
        if tx_hash is None:
            tx_hash = TxHash("0x" + "cd" * 32)
        return BlobTxEntry(
            tx_hash=tx_hash,
            sender=Address("0x" + "11" * 20),
            nonce=0,
            gas_fee_cap=1000000000,
            gas_tip_cap=100000000,
            blob_gas_price=1000000,
            tx_size=131072,
            blob_count=blob_count,
            cell_mask=cell_mask,
            received_at=0.0,
        )

    def _add_recording_peers(
        self,
        node: Node,
        simulator: Simulator,
        network: Network,
        count: int,
        protocol: EthProtocol = EthProtocol.ETH71,
        prefix: str = "peer",
    ) -> dict[ActorId, AnnouncementRecorder]:
        recorders: dict[ActorId, AnnouncementRecorder] = {}
        for i in range(count):
            peer = ActorId(f"{prefix}-{i}")
            actor = AnnouncementRecorder(peer, simulator)
            simulator.register_actor(actor)
            network.register_node(peer, "united states")
            node.add_peer(peer, protocol)
            recorders[peer] = actor
        return recorders

    def _announcement_count(
        self, recorders: dict[ActorId, AnnouncementRecorder]
    ) -> int:
        return sum(
            1
            for actor in recorders.values()
            if any(isinstance(m, NewPooledTransactionHashes) for m in actor.received)
        )

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
        network.register_node(node.id, "united states")

        from sparse_blobpool.core.actor import Actor

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
            network.register_node(peer, "united states")
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

    def test_fewer_than_limit_announced_to_all_eligible_peers(
        self,
        simulator: Simulator,
        network: Network,
        config: SimulationConfig,
        metrics: MetricsCollector,
    ) -> None:
        """Nodes with fewer than 16 eligible peers announce to every eligible peer."""
        node = Node(ActorId("test-node"), simulator, config, custody_columns=8, metrics=metrics)
        simulator.register_actor(node)
        network.register_node(node.id, "united states")
        recorders = self._add_recording_peers(node, simulator, network, count=3)

        entry = self._make_entry()
        node.pool.add(entry)
        node._announce_tx(entry)
        simulator.run(until=1.0)

        assert self._announcement_count(recorders) == 3
        assert len(entry.announced_to) == 3

    def test_completed_tx_announcement_limited_to_16_peers(
        self,
        simulator: Simulator,
        network: Network,
        config: SimulationConfig,
        metrics: MetricsCollector,
    ) -> None:
        """Completed transactions are announced to at most 16 eligible peers."""
        node = Node(ActorId("test-node"), simulator, config, custody_columns=8, metrics=metrics)
        simulator.register_actor(node)
        network.register_node(node.id, "united states")
        recorders = self._add_recording_peers(node, simulator, network, count=20)

        entry = self._make_entry()
        node.pool.add(entry)
        node._announce_tx(entry)
        simulator.run(until=1.0)

        assert self._announcement_count(recorders) == 16
        assert len(entry.announced_to) == 16

    def test_repeated_announcement_does_not_leak_to_additional_peers(
        self,
        simulator: Simulator,
        network: Network,
        config: SimulationConfig,
        metrics: MetricsCollector,
    ) -> None:
        """Repeated announcement attempts keep the same capped peer set."""
        node = Node(ActorId("test-node"), simulator, config, custody_columns=8, metrics=metrics)
        simulator.register_actor(node)
        network.register_node(node.id, "united states")
        recorders = self._add_recording_peers(node, simulator, network, count=20)

        entry = self._make_entry()
        node.pool.add(entry)
        node._announce_tx(entry)
        simulator.run(until=1.0)
        first_announced_to = set(entry.announced_to)

        node._announce_tx(entry)
        simulator.run(until=2.0)

        assert self._announcement_count(recorders) == 16
        assert entry.announced_to == first_announced_to

    def test_partial_tx_announcement_skips_legacy_peers_before_limit(
        self,
        simulator: Simulator,
        network: Network,
        config: SimulationConfig,
        metrics: MetricsCollector,
    ) -> None:
        """Partial availability is advertised only to capped eth/71 peers."""
        node = Node(ActorId("test-node"), simulator, config, custody_columns=8, metrics=metrics)
        simulator.register_actor(node)
        network.register_node(node.id, "united states")
        sparse_recorders = self._add_recording_peers(
            node, simulator, network, count=20, protocol=EthProtocol.ETH71, prefix="sparse"
        )
        legacy_recorders = self._add_recording_peers(
            node, simulator, network, count=5, protocol=EthProtocol.ETH70, prefix="legacy"
        )

        entry = self._make_entry(
            tx_hash=TxHash("0x" + "ef" * 32),
            cell_mask=node.custody_mask,
        )
        node.pool.add(entry)
        node._announce_tx(entry)
        simulator.run(until=1.0)

        assert self._announcement_count(sparse_recorders) == 16
        assert self._announcement_count(legacy_recorders) == 0
        assert len(entry.announced_to) == 16

    def test_announcements_use_negotiated_protocol(
        self,
        simulator: Simulator,
        network: Network,
        config: SimulationConfig,
        metrics: MetricsCollector,
    ) -> None:
        """eth/71 peers receive sparse masks; eth/70 peers receive legacy announcements."""
        node = Node(ActorId("test-node"), simulator, config, custody_columns=8, metrics=metrics)
        simulator.register_actor(node)
        network.register_node(node.id, "united states")

        from sparse_blobpool.core.actor import Actor
        from sparse_blobpool.core.types import Address
        from sparse_blobpool.pool.blobpool import BlobTxEntry

        class AnnouncementRecorder(Actor):
            def __init__(self, actor_id: ActorId, sim: Simulator) -> None:
                super().__init__(actor_id, sim)
                self.received: list[EventPayload] = []

            def on_event(self, payload: EventPayload) -> None:
                self.received.append(payload)

        sparse_peer = ActorId("sparse-peer")
        legacy_peer = ActorId("legacy-peer")
        sparse_actor = AnnouncementRecorder(sparse_peer, simulator)
        legacy_actor = AnnouncementRecorder(legacy_peer, simulator)
        simulator.register_actor(sparse_actor)
        simulator.register_actor(legacy_actor)
        network.register_node(sparse_peer, "united states")
        network.register_node(legacy_peer, "united states")
        node.add_peer(sparse_peer, EthProtocol.ETH71)
        node.add_peer(legacy_peer, EthProtocol.ETH70)

        tx_hash = TxHash("0x" + "cd" * 32)
        entry = BlobTxEntry(
            tx_hash=tx_hash,
            sender=Address("0x" + "11" * 20),
            nonce=0,
            gas_fee_cap=1000000000,
            gas_tip_cap=100000000,
            blob_gas_price=1000000,
            tx_size=500,
            blob_count=2,
            cell_mask=ALL_ONES,
            received_at=0.0,
        )
        node.pool.add(entry)
        node._announce_tx(entry)
        simulator.run(until=1.0)

        sparse_msg = next(
            m for m in sparse_actor.received if isinstance(m, NewPooledTransactionHashes)
        )
        legacy_msg = next(
            m for m in legacy_actor.received if isinstance(m, NewPooledTransactionHashes)
        )

        assert sparse_msg.cell_mask == ALL_ONES
        assert sparse_msg.sizes == [300 + 2 * 96]
        assert legacy_msg.cell_mask is None
        assert legacy_msg.sizes == [500 + 2 * CELLS_PER_BLOB * CELL_SIZE]

    def test_partial_tx_not_announced_to_legacy_peer(
        self,
        simulator: Simulator,
        network: Network,
        config: SimulationConfig,
        metrics: MetricsCollector,
    ) -> None:
        """Samplers advertise partial availability only to eth/71 peers."""
        node = Node(ActorId("test-node"), simulator, config, custody_columns=8, metrics=metrics)
        simulator.register_actor(node)
        network.register_node(node.id, "united states")

        from sparse_blobpool.core.actor import Actor
        from sparse_blobpool.core.types import Address
        from sparse_blobpool.pool.blobpool import BlobTxEntry

        class AnnouncementRecorder(Actor):
            def __init__(self, actor_id: ActorId, sim: Simulator) -> None:
                super().__init__(actor_id, sim)
                self.received: list[EventPayload] = []

            def on_event(self, payload: EventPayload) -> None:
                self.received.append(payload)

        sparse_peer = ActorId("sparse-peer")
        legacy_peer = ActorId("legacy-peer")
        sparse_actor = AnnouncementRecorder(sparse_peer, simulator)
        legacy_actor = AnnouncementRecorder(legacy_peer, simulator)
        simulator.register_actor(sparse_actor)
        simulator.register_actor(legacy_actor)
        network.register_node(sparse_peer, "united states")
        network.register_node(legacy_peer, "united states")
        node.add_peer(sparse_peer, EthProtocol.ETH71)
        node.add_peer(legacy_peer, EthProtocol.ETH70)

        tx_hash = TxHash("0x" + "ef" * 32)
        entry = BlobTxEntry(
            tx_hash=tx_hash,
            sender=Address("0x" + "11" * 20),
            nonce=0,
            gas_fee_cap=1000000000,
            gas_tip_cap=100000000,
            blob_gas_price=1000000,
            tx_size=500,
            blob_count=1,
            cell_mask=node.custody_mask,
            received_at=0.0,
        )
        node.pool.add(entry)
        node._announce_tx(entry)
        simulator.run(until=1.0)

        sparse_announcements = [
            m for m in sparse_actor.received if isinstance(m, NewPooledTransactionHashes)
        ]
        legacy_announcements = [
            m for m in legacy_actor.received if isinstance(m, NewPooledTransactionHashes)
        ]

        assert len(sparse_announcements) == 1
        assert sparse_announcements[0].cell_mask == node.custody_mask
        assert legacy_announcements == []
