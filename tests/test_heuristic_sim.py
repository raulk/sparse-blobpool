from __future__ import annotations

import random

from heuristic_sim.config import (
    ALL_ONES,
    CELLS_PER_BLOB,
    EvictionPolicy,
    HeuristicConfig,
    Role,
    Scenario,
    columns_to_mask,
    mask_to_columns,
    popcount,
)
from heuristic_sim.events import Event, EventLoop
from heuristic_sim.metrics import SimulationResult
from heuristic_sim.node import Node, TokenBucket
from heuristic_sim.peers import (
    FreeRiderBehavior,
    HonestBehavior,
    NonAnnouncerBehavior,
    PeerState,
    SelectiveSignalerBehavior,
    SpammerBehavior,
    SpooferBehavior,
    WithholderBehavior,
)
from heuristic_sim.pool import TxEntry, TxStore
from heuristic_sim.runner import run_simulation

# ---------------------------------------------------------------------------
# Task 1: Event loop
# ---------------------------------------------------------------------------


class TestEventLoop:
    def test_events_processed_in_timestamp_order(self):
        log = []
        loop = EventLoop()
        loop.schedule(Event(t=3.0, kind="c"))
        loop.schedule(Event(t=1.0, kind="a"))
        loop.schedule(Event(t=2.0, kind="b"))
        for event in loop.run():
            log.append(event.kind)
        assert log == ["a", "b", "c"]

    def test_empty_loop_produces_nothing(self):
        loop = EventLoop()
        assert list(loop.run()) == []


# ---------------------------------------------------------------------------
# Task 2: Heuristic config and protocol types
# ---------------------------------------------------------------------------


class TestHeuristicConfig:
    def test_defaults_match_mitigations_report(self):
        cfg = HeuristicConfig()
        assert cfg.includability_discount == 0.7
        assert cfg.saturation_timeout == 30.0
        assert cfg.min_independent_peers == 2
        assert cfg.c_extra_max == 4
        assert cfg.max_random_failure_rate == 0.1
        assert cfg.tracking_window == 100
        assert cfg.k_high == 2
        assert cfg.k_low == 4

    def test_cell_mask_helpers(self):
        mask = columns_to_mask([0, 3, 7])
        assert mask_to_columns(mask) == [0, 3, 7]
        assert popcount(mask) == 3
        assert popcount(ALL_ONES) == 128


# ---------------------------------------------------------------------------
# Task 3: Peer state and tracking
# ---------------------------------------------------------------------------


class TestPeerState:
    def test_random_column_failure_rate(self):
        peer = PeerState(peer_id="p1", behavior="honest", connected_at=0.0)
        for _ in range(8):
            peer.record_random_column_result(success=True)
        for _ in range(2):
            peer.record_random_column_result(success=False)
        assert peer.random_column_failure_rate() == 0.2

    def test_failure_rate_sliding_window(self):
        peer = PeerState(peer_id="p1", behavior="honest", connected_at=0.0)
        for _ in range(100):
            peer.record_random_column_result(success=False)
        for _ in range(100):
            peer.record_random_column_result(success=True)
        assert peer.random_column_failure_rate() == 0.0

    def test_provider_rate(self):
        peer = PeerState(peer_id="p1", behavior="honest", connected_at=0.0)
        peer.provider_announcements += 3
        peer.sampler_announcements += 7
        assert peer.provider_rate() == 0.3

    def test_provider_rate_no_announcements(self):
        peer = PeerState(peer_id="p1", behavior="honest", connected_at=0.0)
        assert peer.provider_rate() == 0.0

    def test_is_inbound_default(self):
        peer = PeerState(peer_id="p1", behavior="honest", connected_at=0.0)
        assert peer.is_inbound is True

    def test_request_tracking_fields(self):
        peer = PeerState(peer_id="p1", behavior="honest", connected_at=0.0)
        assert peer.requests_received == 0
        assert peer.requests_sent_to == 0

    def test_bandwidth_fields_default_zero(self):
        peer = PeerState(peer_id="p1", behavior="honest", connected_at=0.0)
        assert peer.bytes_in == 0
        assert peer.bytes_out == 0


# ---------------------------------------------------------------------------
# Task 4: Transaction state and blobpool store
# ---------------------------------------------------------------------------


class TestTxState:
    def test_add_and_lookup(self):
        pool = TxStore(capacity=100)
        tx = TxEntry(
            tx_hash="0xabc", sender="0x1", nonce=0, fee=10.0, first_seen=1.0, role=Role.SAMPLER
        )
        pool.add(tx)
        assert pool.get("0xabc") is tx
        assert pool.count == 1

    def test_sender_limit(self):
        pool = TxStore(capacity=100, max_per_sender=2)
        for i in range(3):
            tx = TxEntry(
                tx_hash=f"0x{i}",
                sender="0x1",
                nonce=i,
                fee=10.0,
                first_seen=1.0,
                role=Role.SAMPLER,
            )
            pool.add(tx)
        assert pool.count == 2

    def test_capacity_evicts_lowest_fee(self):
        pool = TxStore(capacity=2)
        for i, fee in enumerate([5.0, 10.0, 15.0]):
            tx = TxEntry(
                tx_hash=f"0x{i}",
                sender=f"0x{i}",
                nonce=0,
                fee=fee,
                first_seen=1.0,
                role=Role.SAMPLER,
            )
            pool.add(tx)
        assert pool.count == 2
        assert pool.get("0x0") is None
        assert pool.get("0x1") is not None
        assert pool.get("0x2") is not None

    def test_record_announcer(self):
        pool = TxStore(capacity=100)
        tx = TxEntry(
            tx_hash="0xabc", sender="0x1", nonce=0, fee=10.0, first_seen=1.0, role=Role.SAMPLER
        )
        pool.add(tx)
        tx.announcers.add("peer_1")
        tx.announcers.add("peer_2")
        assert len(tx.announcers) == 2


# ---------------------------------------------------------------------------
# Task 5: Peer behavior generators
# ---------------------------------------------------------------------------


class TestPeerBehaviors:
    def test_honest_peer_generates_announcements_and_requests(self):
        rng = random.Random(42)
        peer = HonestBehavior(peer_id="h1", rng=rng)
        events = peer.generate_events(t_start=0.0, t_end=10.0, tx_rate=1.0)
        assert len(events) > 0
        announces = [e for e in events if e.kind == "announce"]
        requests = [e for e in events if e.kind == "inbound_request"]
        assert len(announces) > 0
        assert len(requests) == len(announces)
        provider_count = sum(1 for e in announces if e.data["cell_mask"] == ALL_ONES)
        assert 0 <= provider_count <= len(announces)

    def test_spammer_generates_below_fee(self):
        rng = random.Random(42)
        peer = SpammerBehavior(peer_id="s1", rng=rng, rate=5.0, below_includability=True)
        events = peer.generate_events(
            t_start=0.0, t_end=10.0, blob_base_fee=1.0, includability_discount=0.7,
        )
        assert len(events) > 0
        for e in events:
            assert e.data["fee"] < 1.0 * 0.7

    def test_withholder_fails_random_columns(self):
        rng = random.Random(42)
        peer = WithholderBehavior(peer_id="w1", rng=rng, random_fail_rate=1.0)
        custody = columns_to_mask([0, 1, 2, 3, 4, 5, 6, 7])
        requested = [0, 1, 2, 3, 50]
        result = peer.respond_to_cell_request(requested, custody)
        assert 0 in result["served"]
        assert 50 in result["failed"]

    def test_selective_signaler_exclusive_announcements(self):
        rng = random.Random(42)
        peer = SelectiveSignalerBehavior(peer_id="ss1", rng=rng, n_senders=3, txs_per_sender=16)
        events = peer.generate_events(t_start=0.0, t_end=60.0)
        assert all(e.data.get("exclusive", False) for e in events)
        senders: dict[str, list[int]] = {}
        for e in events:
            s = e.data["sender"]
            senders.setdefault(s, []).append(e.data["nonce"])
        for _s, nonces in senders.items():
            assert len(nonces) <= 16
            assert nonces == sorted(nonces)

    def test_free_rider_never_provider(self):
        rng = random.Random(42)
        peer = FreeRiderBehavior(peer_id="fr1", rng=rng)
        events = peer.generate_events(t_start=0.0, t_end=10.0, tx_rate=2.0)
        assert len(events) > 0
        assert all(not e.data["is_provider"] for e in events)

    def test_spoofer_fails_all_cells(self):
        rng = random.Random(42)
        peer = SpooferBehavior(peer_id="sp1", rng=rng)
        result = peer.respond_to_cell_request([0, 1, 2, 50, 100], 0)
        assert result["served"] == []
        assert len(result["failed"]) == 5

    def test_non_announcer_generates_requests_not_announces(self):
        rng = random.Random(42)
        peer = NonAnnouncerBehavior(peer_id="na1", rng=rng)
        events = peer.generate_events(t_start=0.0, t_end=10.0, tx_rate=1.0)
        assert len(events) > 0
        assert all(e.kind == "inbound_request" for e in events)


# ---------------------------------------------------------------------------
# Task 6: Node class with H1-H5 heuristics
# ---------------------------------------------------------------------------


class TestNodeAnnounce:
    def test_honest_announcement_accepted(self):
        cfg = HeuristicConfig()
        node = Node(cfg, seed=42)
        node.add_peer(PeerState("p1", "honest", 0.0))
        events = node.handle_announce(
            peer_id="p1", tx_hash="0xabc", sender="s1", nonce=0,
            fee=1.0, cell_mask=ALL_ONES, is_provider=True, exclusive=False, t=1.0,
        )
        assert node.pool.contains("0xabc")
        sat_events = [e for e in events if e.kind == "saturation_check"]
        assert len(sat_events) == 1
        assert sat_events[0].t == 1.0 + cfg.saturation_timeout

    def test_h1_rejects_below_includability(self):
        cfg = HeuristicConfig(includability_discount=0.7, blob_base_fee=1.0)
        node = Node(cfg, seed=42)
        node.add_peer(PeerState("p1", "honest", 0.0))
        node.handle_announce(
            peer_id="p1", tx_hash="0xabc", sender="s1", nonce=0,
            fee=0.5, cell_mask=ALL_ONES, is_provider=True, exclusive=False, t=1.0,
        )
        assert not node.pool.contains("0xabc")

    def test_duplicate_announce_records_additional_peer(self):
        cfg = HeuristicConfig()
        node = Node(cfg, seed=42)
        node.add_peer(PeerState("p1", "honest", 0.0))
        node.add_peer(PeerState("p2", "honest", 0.0))
        node.handle_announce(
            peer_id="p1", tx_hash="0xabc", sender="s1", nonce=0,
            fee=1.0, cell_mask=ALL_ONES, is_provider=True, exclusive=False, t=1.0,
        )
        node.handle_announce(
            peer_id="p2", tx_hash="0xabc", sender="s1", nonce=0,
            fee=1.0, cell_mask=ALL_ONES, is_provider=True, exclusive=False, t=2.0,
        )
        tx = node.pool.get("0xabc")
        assert tx is not None
        assert tx.announcers == {"p1", "p2"}


class TestNodeCellRequest:
    def test_cell_request_includes_c_extra(self):
        cfg = HeuristicConfig(c_extra_max=4, custody_columns=8)
        node = Node(cfg, seed=42)
        columns = node.compute_request_columns(is_provider=False)
        custody = mask_to_columns(node.custody_mask)
        assert len(columns) > len(custody)
        assert len(columns) <= len(custody) + cfg.c_extra_max
        for c in custody:
            assert c in columns

    def test_provider_requests_all_columns(self):
        cfg = HeuristicConfig()
        node = Node(cfg, seed=42)
        columns = node.compute_request_columns(is_provider=True)
        assert len(columns) == CELLS_PER_BLOB


class TestNodeInboundRequest:
    def test_request_counted(self):
        cfg = HeuristicConfig()
        node = Node(cfg, seed=42)
        node.add_peer(PeerState("p1", "non_announcer", 0.0))
        node.handle_inbound_request("p1", [0, 1, 2], t=10.0)
        assert node.peers["p1"].requests_received == 1

    def test_request_accumulates_bandwidth(self):
        cfg = HeuristicConfig()
        node = Node(cfg, seed=42)
        node.add_peer(PeerState("p1", "non_announcer", 0.0))
        node.handle_inbound_request("p1", [0, 1, 2, 3], t=10.0)
        assert node.peers["p1"].bytes_in > 0
        assert node.peers["p1"].bytes_out > 0

    def test_high_request_ratio_disconnects(self):
        cfg = HeuristicConfig(max_request_to_announce_ratio=2.0)
        node = Node(cfg, seed=42)
        node.add_peer(PeerState("p1", "non_announcer", 0.0))
        peer = node.peers["p1"]
        peer.announcements_made = 1
        for i in range(3):
            node.handle_inbound_request("p1", [0], t=61.0 + i)
        assert peer.disconnected
        assert peer.disconnect_reason == "h5_request_ratio"

    def test_request_ratio_not_checked_before_warmup(self):
        """Peers connected < 60s are not checked for request ratio."""
        cfg = HeuristicConfig(max_request_to_announce_ratio=2.0)
        node = Node(cfg, seed=42)
        node.add_peer(PeerState("p1", "non_announcer", 0.0))
        peer = node.peers["p1"]
        peer.announcements_made = 1
        for i in range(5):
            node.handle_inbound_request("p1", [0], t=30.0 + i)
        assert not peer.disconnected


class TestNodeScoring:
    def test_inbound_peers_scored_lower(self):
        cfg = HeuristicConfig(inbound_score_discount=0.15)
        node = Node(cfg, seed=42)
        node.add_peer(PeerState("inbound", "honest", 0.0, is_inbound=True))
        node.add_peer(PeerState("outbound", "honest", 0.0, is_inbound=False))
        for pid in ("inbound", "outbound"):
            p = node.peers[pid]
            p.announcements_made = 10
            p.included_contributions = 5
            p.provider_announcements = 2
            p.sampler_announcements = 8
        node.score_peers(t=300.0)
        assert node.peers["outbound"].score > node.peers["inbound"].score

    def test_provider_rate_deviation_penalized(self):
        cfg = HeuristicConfig(provider_rate_tolerance=0.3)
        node = Node(cfg, seed=42)
        node.add_peer(PeerState("normal", "honest", 0.0, is_inbound=False))
        node.add_peer(PeerState("always_prov", "honest", 0.0, is_inbound=False))
        for pid in ("normal", "always_prov"):
            p = node.peers[pid]
            p.announcements_made = 10
            p.included_contributions = 5
        node.peers["normal"].provider_announcements = 2
        node.peers["normal"].sampler_announcements = 8
        node.peers["always_prov"].provider_announcements = 10
        node.peers["always_prov"].sampler_announcements = 0
        node.score_peers(t=300.0)
        assert node.peers["normal"].score > node.peers["always_prov"].score

    def test_request_ratio_penalty_applied(self):
        cfg = HeuristicConfig(max_request_to_announce_ratio=5.0)
        node = Node(cfg, seed=42)
        node.add_peer(PeerState("low_req", "honest", 0.0, is_inbound=False))
        node.add_peer(PeerState("high_req", "honest", 0.0, is_inbound=False))
        for pid in ("low_req", "high_req"):
            p = node.peers[pid]
            p.announcements_made = 10
            p.included_contributions = 5
            p.provider_announcements = 2
            p.sampler_announcements = 8
        node.peers["low_req"].requests_received = 1
        node.peers["high_req"].requests_received = 50
        node.score_peers(t=300.0)
        assert node.peers["low_req"].score > node.peers["high_req"].score


# ---------------------------------------------------------------------------
# Task 7: Simulation runner
# ---------------------------------------------------------------------------


class TestSimulation:
    def test_honest_only_no_disconnects(self):
        scenario = Scenario(n_honest=20, attackers=[], tx_arrival_rate=1.0, t_end=60.0)
        result = run_simulation(HeuristicConfig(), scenario, seed=42)
        assert result.disconnects_by_behavior.get("honest", 0) == 0
        assert result.total_accepted > 0

    def test_spammer_below_fee_all_rejected(self):
        scenario = Scenario(
            n_honest=10,
            attackers=[(5, "spammer", {"rate": 5.0, "below_includability": True})],
            tx_arrival_rate=0.5, t_end=30.0,
        )
        result = run_simulation(HeuristicConfig(), scenario, seed=42)
        assert result.h1_rejections > 0

    def test_withholder_detected_by_h4(self):
        scenario = Scenario(
            n_honest=10,
            attackers=[(3, "withholder", {"random_fail_rate": 1.0})],
            tx_arrival_rate=1.0, t_end=120.0,
        )
        result = run_simulation(HeuristicConfig(), scenario, seed=42)
        assert result.disconnects_by_behavior.get("withholder", 0) > 0

    def test_selective_signaler_evicted_by_h2(self):
        scenario = Scenario(
            n_honest=10,
            attackers=[(3, "selective_signaler", {"n_senders": 5, "txs_per_sender": 16})],
            tx_arrival_rate=0.5, t_end=120.0,
        )
        result = run_simulation(HeuristicConfig(), scenario, seed=42)
        assert result.h2_evictions > 0


# ---------------------------------------------------------------------------
# Task 8: Metrics summary
# ---------------------------------------------------------------------------


class TestMetrics:
    def test_detection_rate(self):
        scenario = Scenario(
            n_honest=10,
            attackers=[
                (3, "withholder", {"random_fail_rate": 1.0}),
                (2, "spoofer", {}),
            ],
            tx_arrival_rate=2.0, t_end=120.0,
        )
        result = run_simulation(HeuristicConfig(), scenario, seed=42)
        summary = result.detection_summary()
        assert summary["withholder"]["detected"] > 0
        assert summary["spoofer"]["detected"] > 0
        assert summary["honest"]["detected"] == 0

    def test_summary_table(self):
        scenario = Scenario(
            n_honest=10,
            attackers=[(2, "spammer", {"rate": 5.0, "below_includability": True})],
            tx_arrival_rate=1.0, t_end=30.0,
        )
        result = run_simulation(HeuristicConfig(), scenario, seed=42)
        table = result.summary_table()
        assert "Behavior" in table
        assert "honest" in table


# ---------------------------------------------------------------------------
# Task 11: Integration test with all 6 attacks
# ---------------------------------------------------------------------------


class TestFullIntegration:
    """Integration test: all 6 attacks running simultaneously."""

    def test_all_attacks_detected_no_false_positives(self):
        scenario = Scenario(
            n_honest=30,
            attackers=[
                (3, "spammer", {"rate": 5.0, "below_includability": True}),
                (3, "withholder", {"random_fail_rate": 1.0}),
                (2, "spoofer", {}),
                (2, "free_rider", {}),
                (2, "non_announcer", {}),
                (3, "selective_signaler", {"n_senders": 5, "txs_per_sender": 16}),
            ],
            tx_arrival_rate=2.0,
            t_end=300.0,
        )
        result = run_simulation(HeuristicConfig(), scenario, seed=42)

        assert result.false_positives == 0, f"False positives: {result.false_positives}"
        assert result.h1_rejections > 0, "H1 should reject below-fee spam"
        assert result.h2_evictions > 0, "H2 should evict uncorroborated txs"
        assert result.disconnects_by_behavior.get("withholder", 0) > 0, (
            "H4 should disconnect withholders"
        )
        assert result.disconnects_by_behavior.get("spoofer", 0) > 0, (
            "H4 should disconnect spoofers"
        )
        assert result.disconnects_by_behavior.get("non_announcer", 0) > 0, (
            "H5 should disconnect non-announcers via request ratio"
        )

    def test_results_reproducible(self):
        scenario = Scenario(
            n_honest=10,
            attackers=[(3, "withholder", {"random_fail_rate": 0.8})],
            tx_arrival_rate=1.0,
            t_end=60.0,
        )
        r1 = run_simulation(HeuristicConfig(), scenario, seed=99)
        r2 = run_simulation(HeuristicConfig(), scenario, seed=99)
        assert r1.total_accepted == r2.total_accepted
        assert r1.h4_disconnects == r2.h4_disconnects

    def test_inbound_outbound_split(self):
        scenario = Scenario(n_honest=50, attackers=[], inbound_ratio=0.68)
        result = run_simulation(HeuristicConfig(), scenario, seed=42)
        n_outbound = round(50 * (1 - 0.68))
        n_inbound = 50 - n_outbound
        inbound_peers = [
            e for e in result.log
            if e["event"] == "accept"
        ]
        # Verify through the node's peer state (re-run to inspect)
        from heuristic_sim.runner import _create_peers_and_events
        import random as stdlib_random
        rng = stdlib_random.Random(42)
        node = Node(HeuristicConfig(), seed=rng.randint(0, 2**32))
        loop = EventLoop()
        _create_peers_and_events(scenario, HeuristicConfig(), node, loop, rng)
        actual_inbound = sum(1 for p in node.peers.values() if p.is_inbound)
        actual_outbound = sum(1 for p in node.peers.values() if not p.is_inbound)
        assert actual_inbound == n_inbound
        assert actual_outbound == n_outbound

    def test_bandwidth_tracked(self):
        scenario = Scenario(
            n_honest=10,
            attackers=[(2, "non_announcer", {})],
            tx_arrival_rate=1.0,
            t_end=120.0,
        )
        result = run_simulation(HeuristicConfig(), scenario, seed=42)
        assert "honest" in result.bandwidth_by_behavior
        honest_bw = result.bandwidth_by_behavior["honest"]
        assert honest_bw["in"] > 0
        assert honest_bw["out"] > 0

    def test_pool_occupancy_tracked_over_time(self):
        scenario = Scenario(
            n_honest=10, attackers=[], tx_arrival_rate=2.0, t_end=60.0,
        )
        result = run_simulation(HeuristicConfig(), scenario, seed=42)
        assert len(result.pool_occupancy) > 1
        # Timestamps should be monotonically non-decreasing
        for i in range(1, len(result.pool_occupancy)):
            assert result.pool_occupancy[i][0] >= result.pool_occupancy[i - 1][0]


# ---------------------------------------------------------------------------
# Ported features: EvictionPolicy, TokenBucket
# ---------------------------------------------------------------------------


class TestEvictionPolicy:
    def test_fee_based_evicts_lowest_fee(self):
        pool = TxStore(capacity=2, eviction_policy=EvictionPolicy.FEE_BASED)
        for i, fee in enumerate([5.0, 10.0, 15.0]):
            pool.add(TxEntry(
                tx_hash=f"tx{i}", sender=f"s{i}", nonce=0,
                fee=fee, first_seen=float(i), role=Role.SAMPLER,
            ))
        assert pool.count == 2
        assert pool.get("tx0") is None
        assert pool.get("tx1") is not None

    def test_age_based_evicts_oldest(self):
        pool = TxStore(capacity=2, eviction_policy=EvictionPolicy.AGE_BASED)
        for i, fee in enumerate([15.0, 5.0, 10.0]):
            pool.add(TxEntry(
                tx_hash=f"tx{i}", sender=f"s{i}", nonce=0,
                fee=fee, first_seen=float(i), role=Role.SAMPLER,
            ))
        assert pool.count == 2
        # tx0 is oldest (first_seen=0.0), should be evicted
        assert pool.get("tx0") is None
        assert pool.get("tx1") is not None
        assert pool.get("tx2") is not None

    def test_hybrid_considers_both_fee_and_age(self):
        pool = TxStore(
            capacity=2, eviction_policy=EvictionPolicy.HYBRID, age_weight=0.5,
        )
        # tx0: low fee, old
        # tx1: high fee, recent
        # tx2: medium fee, medium age
        pool.add(TxEntry(
            tx_hash="old_cheap", sender="s0", nonce=0,
            fee=1.0, first_seen=0.0, role=Role.SAMPLER,
        ))
        pool.add(TxEntry(
            tx_hash="new_expensive", sender="s1", nonce=0,
            fee=10.0, first_seen=10.0, role=Role.SAMPLER,
        ))
        pool.add(TxEntry(
            tx_hash="mid", sender="s2", nonce=0,
            fee=5.0, first_seen=5.0, role=Role.SAMPLER,
        ))
        assert pool.count == 2
        # old_cheap should be evicted (worst combined score)
        assert pool.get("old_cheap") is None
        assert pool.get("new_expensive") is not None


class TestTokenBucket:
    def test_initial_burst_allowed(self):
        bucket = TokenBucket(rate=1.0, burst=3)
        assert bucket.consume(0.0)
        assert bucket.consume(0.0)
        assert bucket.consume(0.0)
        assert not bucket.consume(0.0)

    def test_refills_over_time(self):
        bucket = TokenBucket(rate=1.0, burst=1)
        assert bucket.consume(0.0)
        assert not bucket.consume(0.0)
        assert bucket.consume(1.0)

    def test_rate_limiting_in_node(self):
        cfg = HeuristicConfig(max_announcements_per_second=1.0, burst_allowance=2)
        node = Node(cfg, seed=42)
        node.add_peer(PeerState("p1", "honest", 0.0))
        # First two consume the burst
        node.handle_announce(
            peer_id="p1", tx_hash="tx1", sender="s1", nonce=0,
            fee=1.0, cell_mask=ALL_ONES, is_provider=True, exclusive=False, t=0.0,
        )
        node.handle_announce(
            peer_id="p1", tx_hash="tx2", sender="s2", nonce=0,
            fee=1.0, cell_mask=ALL_ONES, is_provider=True, exclusive=False, t=0.0,
        )
        # Third at same time should be rate-limited
        node.handle_announce(
            peer_id="p1", tx_hash="tx3", sender="s3", nonce=0,
            fee=1.0, cell_mask=ALL_ONES, is_provider=True, exclusive=False, t=0.0,
        )
        assert node.pool.contains("tx1")
        assert node.pool.contains("tx2")
        assert not node.pool.contains("tx3")
        rate_limited = [e for e in node.log if e["event"] == "reject_rate_limit"]
        assert len(rate_limited) == 1
