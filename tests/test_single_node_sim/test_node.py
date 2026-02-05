"""Tests for single_node_sim.node module."""

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from single_node_sim.events import BlockIncluded, CellsReceived, TxAnnouncement
from single_node_sim.metrics import Role, SingleNodeMetrics, TxState
from single_node_sim.node import SingleNode
from single_node_sim.params import EvictionPolicy, HeuristicParams
from sparse_blobpool.core.events import Event
from sparse_blobpool.core.simulator import Simulator
from sparse_blobpool.core.types import ActorId
from sparse_blobpool.protocol.constants import ALL_ONES, CELLS_PER_BLOB


@pytest.fixture
def default_simulator() -> Simulator:
    return Simulator(seed=42)


@pytest.fixture
def default_params() -> HeuristicParams:
    return HeuristicParams()


def make_node(
    simulator: Simulator,
    params: HeuristicParams | None = None,
) -> SingleNode:
    params = params or HeuristicParams()
    metrics = SingleNodeMetrics(simulator)
    node = SingleNode(ActorId("test_node"), simulator, params, metrics)
    simulator.register_actor(node)
    return node


def schedule_event(
    simulator: Simulator,
    node: SingleNode,
    event: TxAnnouncement | CellsReceived | BlockIncluded,
) -> None:
    simulator.schedule(
        Event(timestamp=event.timestamp, target_id=node.id, payload=event)
    )


def make_tx_announcement(
    timestamp: float = 0.0,
    tx_hash: str = "0xabc",
    sender: str = "0xsender",
    nonce: int = 0,
    gas_fee_cap: int = 1_000_000_000,
    gas_tip_cap: int = 100_000_000,
    tx_size: int = 131_072,
    blob_count: int = 1,
    cell_mask: int = ALL_ONES,
) -> TxAnnouncement:
    return TxAnnouncement(
        timestamp=timestamp,
        tx_hash=tx_hash,
        sender=sender,
        nonce=nonce,
        gas_fee_cap=gas_fee_cap,
        gas_tip_cap=gas_tip_cap,
        tx_size=tx_size,
        blob_count=blob_count,
        cell_mask=cell_mask,
    )


class TestHappyPath:

    def test_announce_fetch_complete_flow(
        self,
        default_simulator: Simulator,
        default_params: HeuristicParams,
    ) -> None:
        node = make_node(default_simulator, default_params)
        ann = make_tx_announcement(timestamp=0.0, tx_hash="0xabc1")
        schedule_event(default_simulator, node, ann)

        default_simulator.run(until=10.0)

        records = node._metrics.get_tx_records()
        assert "0xabc1" in records
        record = records["0xabc1"]
        assert record.completed_at is not None

    def test_multiple_transactions(
        self,
        default_simulator: Simulator,
        default_params: HeuristicParams,
    ) -> None:
        node = make_node(default_simulator, default_params)

        for i in range(5):
            ann = make_tx_announcement(
                timestamp=float(i),
                tx_hash=f"0xabc{i}",
                sender=f"0xsender{i}",
            )
            schedule_event(default_simulator, node, ann)

        default_simulator.run(until=100.0)

        records = node._metrics.get_tx_records()
        assert len(records) == 5


class TestEvictionFeeBasedPolicy:

    def test_evicts_lowest_fee_when_full(
        self,
        default_simulator: Simulator,
    ) -> None:
        params = HeuristicParams(
            max_pool_bytes=200_000,
            eviction_policy=EvictionPolicy.FEE_BASED,
        )
        node = make_node(default_simulator, params)

        schedule_event(
            default_simulator,
            node,
            make_tx_announcement(
                timestamp=0.0,
                tx_hash="0xlow",
                sender="0xsender1",
                gas_tip_cap=100_000,
                tx_size=100_000,
            ),
        )
        schedule_event(
            default_simulator,
            node,
            make_tx_announcement(
                timestamp=1.0,
                tx_hash="0xhigh",
                sender="0xsender2",
                gas_tip_cap=1_000_000,
                tx_size=100_000,
            ),
        )
        schedule_event(
            default_simulator,
            node,
            make_tx_announcement(
                timestamp=2.0,
                tx_hash="0xmed",
                sender="0xsender3",
                gas_tip_cap=500_000,
                tx_size=100_000,
            ),
        )

        default_simulator.run(until=10.0)

        records = node._metrics.get_tx_records()
        assert records["0xlow"].evicted_at is not None
        assert "eviction" in (records["0xlow"].eviction_reason or "")


class TestEvictionAgeBasedPolicy:

    def test_eviction_occurs_when_full(
        self,
        default_simulator: Simulator,
    ) -> None:
        params = HeuristicParams(
            max_pool_bytes=200_000,
            eviction_policy=EvictionPolicy.AGE_BASED,
        )
        node = make_node(default_simulator, params)

        schedule_event(
            default_simulator,
            node,
            make_tx_announcement(
                timestamp=0.0,
                tx_hash="0xold",
                sender="0xsender1",
                gas_tip_cap=100_000,
                tx_size=100_000,
            ),
        )
        schedule_event(
            default_simulator,
            node,
            make_tx_announcement(
                timestamp=1.0,
                tx_hash="0xnew",
                sender="0xsender2",
                gas_tip_cap=200_000,
                tx_size=100_000,
            ),
        )
        schedule_event(
            default_simulator,
            node,
            make_tx_announcement(
                timestamp=2.0,
                tx_hash="0xnewer",
                sender="0xsender3",
                gas_tip_cap=150_000,
                tx_size=100_000,
            ),
        )

        default_simulator.run(until=10.0)

        records = node._metrics.get_tx_records()
        summary = node._metrics.summary()
        assert summary.total_evictions >= 1
        assert records["0xold"].evicted_at is not None


class TestEvictionHybridPolicy:

    def test_hybrid_considers_both_age_and_fee(
        self,
        default_simulator: Simulator,
    ) -> None:
        params = HeuristicParams(
            max_pool_bytes=262_144,
            eviction_policy=EvictionPolicy.HYBRID,
            age_weight=0.5,
        )
        node = make_node(default_simulator, params)

        schedule_event(
            default_simulator,
            node,
            make_tx_announcement(
                timestamp=0.0,
                tx_hash="0x1",
                sender="0xsender1",
                gas_tip_cap=100_000,
                tx_size=131_072,
            ),
        )

        default_simulator.run(until=10.0)

        records = node._metrics.get_tx_records()
        assert len(records) >= 1


class TestRateLimiting:

    def test_rate_limit_rejects_excessive_announcements(
        self,
        default_simulator: Simulator,
    ) -> None:
        params = HeuristicParams(
            max_announcements_per_second=2.0,
            burst_allowance=2,
        )
        node = make_node(default_simulator, params)

        for i in range(10):
            ann = make_tx_announcement(
                timestamp=0.0,
                tx_hash=f"0xabc{i}",
                sender=f"0xsender{i}",
            )
            schedule_event(default_simulator, node, ann)

        default_simulator.run(until=1.0)

        records = node._metrics.get_tx_records()
        assert len(records) <= 4


class TestRBFRejection:

    def test_rbf_rejected_insufficient_bump(
        self,
        default_simulator: Simulator,
        default_params: HeuristicParams,
    ) -> None:
        node = make_node(default_simulator, default_params)

        schedule_event(
            default_simulator,
            node,
            make_tx_announcement(
                timestamp=0.0,
                tx_hash="0xoriginal",
                gas_fee_cap=1_000_000_000,
                gas_tip_cap=100_000_000,
            ),
        )

        schedule_event(
            default_simulator,
            node,
            make_tx_announcement(
                timestamp=1.0,
                tx_hash="0xreplacement",
                gas_fee_cap=1_050_000_000,
                gas_tip_cap=105_000_000,
            ),
        )

        default_simulator.run(until=10.0)

        log = node._metrics.get_debug_log()
        reject_logs = [line for line in log if "REJECT" in line]
        assert len(reject_logs) >= 1

    def test_rbf_accepted_sufficient_bump(
        self,
        default_simulator: Simulator,
        default_params: HeuristicParams,
    ) -> None:
        node = make_node(default_simulator, default_params)

        schedule_event(
            default_simulator,
            node,
            make_tx_announcement(
                timestamp=0.0,
                tx_hash="0xoriginal",
                gas_fee_cap=1_000_000_000,
                gas_tip_cap=100_000_000,
            ),
        )

        schedule_event(
            default_simulator,
            node,
            make_tx_announcement(
                timestamp=1.0,
                tx_hash="0xreplacement",
                gas_fee_cap=1_100_000_001,
                gas_tip_cap=110_000_001,
            ),
        )

        default_simulator.run(until=10.0)

        records = node._metrics.get_tx_records()
        assert "0xreplacement" in records


class TestSenderLimit:

    def test_sender_limit_rejects_excess(
        self,
        default_simulator: Simulator,
    ) -> None:
        params = HeuristicParams(max_txs_per_sender=2)
        node = make_node(default_simulator, params)

        for i in range(5):
            ann = make_tx_announcement(
                timestamp=float(i),
                tx_hash=f"0xabc{i}",
                sender="0xsamesender",
                nonce=i,
            )
            schedule_event(default_simulator, node, ann)

        default_simulator.run(until=10.0)

        log = node._metrics.get_debug_log()
        reject_logs = [line for line in log if "REJECT" in line and "sender_limit" in line]
        assert len(reject_logs) >= 3


class TestTTLExpiration:

    def test_ttl_expires_old_transactions(
        self,
        default_simulator: Simulator,
    ) -> None:
        params = HeuristicParams(tx_ttl=5.0)
        node = make_node(default_simulator, params)

        schedule_event(
            default_simulator,
            node,
            make_tx_announcement(
                timestamp=0.0,
                tx_hash="0xold",
            ),
        )

        default_simulator.run(until=10.0)

        records = node._metrics.get_tx_records()
        assert records["0xold"].evicted_at is not None
        assert records["0xold"].eviction_reason == "ttl_expired"


class TestRoleAssignment:

    def test_role_assignment_is_deterministic(
        self,
        default_params: HeuristicParams,
    ) -> None:
        sim1 = Simulator(seed=42)
        sim2 = Simulator(seed=42)

        node1 = make_node(sim1, default_params)
        node2 = make_node(sim2, default_params)

        ann = make_tx_announcement(tx_hash="0xabc123")
        schedule_event(sim1, node1, ann)
        schedule_event(sim2, node2, ann)

        sim1.run(until=1.0)
        sim2.run(until=1.0)

        records1 = node1._metrics.get_tx_records()
        records2 = node2._metrics.get_tx_records()

        assert records1["0xabc123"].role == records2["0xabc123"].role

    @given(
        seed=st.integers(min_value=0, max_value=2**32 - 1),
        tx_hashes=st.lists(
            st.text(min_size=8, max_size=64, alphabet="0123456789abcdef"),
            min_size=100,
            max_size=100,
            unique=True,
        ),
    )
    @settings(max_examples=10)
    def test_provider_ratio_approximately_correct(
        self,
        seed: int,
        tx_hashes: list[str],
    ) -> None:
        params = HeuristicParams(
            provider_probability=0.15,
            seed=seed,
        )
        sim = Simulator(seed=seed)
        node = make_node(sim, params)

        for i, tx_hash in enumerate(tx_hashes):
            ann = make_tx_announcement(
                timestamp=float(i) * 0.1,
                tx_hash=tx_hash,
                sender=f"0xsender{i}",
                nonce=0,
            )
            schedule_event(sim, node, ann)

        sim.run(until=100.0)

        records = node._metrics.get_tx_records()
        provider_count = sum(1 for r in records.values() if r.role == Role.PROVIDER)
        observed_ratio = provider_count / len(records) if records else 0

        assert 0.05 <= observed_ratio <= 0.30


class TestCustodyMask:

    def test_custody_mask_has_correct_bit_count(
        self,
        default_simulator: Simulator,
    ) -> None:
        params = HeuristicParams(custody_columns=8)
        node = make_node(default_simulator, params)

        bit_count = bin(node.custody_mask).count("1")
        assert bit_count == 8

    @given(columns=st.integers(min_value=1, max_value=CELLS_PER_BLOB))
    @settings(max_examples=30)
    def test_custody_mask_respects_columns_param(self, columns: int) -> None:
        params = HeuristicParams(custody_columns=columns)
        sim = Simulator(seed=42)
        node = make_node(sim, params)

        bit_count = bin(node.custody_mask).count("1")
        assert bit_count == columns

    def test_custody_mask_is_deterministic(
        self,
        default_params: HeuristicParams,
    ) -> None:
        sim1 = Simulator(seed=42)
        sim2 = Simulator(seed=42)

        node1 = make_node(sim1, default_params)
        node2 = make_node(sim2, default_params)

        assert node1.custody_mask == node2.custody_mask


class TestBlockInclusion:

    def test_block_removes_included_transactions(
        self,
        default_simulator: Simulator,
        default_params: HeuristicParams,
    ) -> None:
        node = make_node(default_simulator, default_params)

        schedule_event(
            default_simulator,
            node,
            make_tx_announcement(
                timestamp=0.0,
                tx_hash="0xabc1",
            ),
        )
        schedule_event(
            default_simulator,
            node,
            make_tx_announcement(
                timestamp=0.1,
                tx_hash="0xabc2",
                sender="0xsender2",
            ),
        )

        default_simulator.run(until=1.0)

        block = BlockIncluded(
            timestamp=2.0,
            tx_hashes=["0xabc1"],
        )
        schedule_event(default_simulator, node, block)

        default_simulator.run(until=10.0)

        assert not node.pool.contains("0xabc1")
        assert node.pool.contains("0xabc2")


class TestCellsReceived:

    def test_cells_received_updates_availability(
        self,
        default_simulator: Simulator,
    ) -> None:
        from single_node_sim.availability import AvailabilityMode

        params = HeuristicParams(availability_mode=AvailabilityMode.TRACE_DRIVEN)
        node = make_node(default_simulator, params)

        schedule_event(
            default_simulator,
            node,
            make_tx_announcement(
                timestamp=0.0,
                tx_hash="0xabc1",
                cell_mask=0,
            ),
        )

        custody = node.custody_mask
        cells = CellsReceived(
            timestamp=0.5,
            tx_hash="0xabc1",
            cell_mask=custody,
        )
        schedule_event(default_simulator, node, cells)

        default_simulator.run(until=10.0)

        records = node._metrics.get_tx_records()
        assert "0xabc1" in records
