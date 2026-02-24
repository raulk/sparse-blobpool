from __future__ import annotations

from heuristic_sim.blobpool_sim import (
    ALL_ONES,
    Event,
    EventLoop,
    HeuristicConfig,
    PeerState,
    Role,
    TxEntry,
    TxStore,
    columns_to_mask,
    mask_to_columns,
    popcount,
)

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
