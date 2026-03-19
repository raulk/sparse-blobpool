from __future__ import annotations

import random
from hashlib import sha256
from typing import Any

from heuristic_sim.config import (
    ANNOUNCE_MSG_BYTES,
    CELL_BYTES,
    CELLS_PER_BLOB,
    MAX_TXS_PER_SENDER,
    REQUEST_MSG_OVERHEAD,
    HeuristicConfig,
    Role,
    columns_to_mask,
    mask_to_columns,
)
from heuristic_sim.events import Event
from heuristic_sim.peers import PeerState
from heuristic_sim.pool import TxEntry, TxStore


class TokenBucket:
    """Rate limiter using token bucket algorithm."""

    def __init__(self, rate: float, burst: int) -> None:
        self._rate = rate
        self._burst = burst
        self._tokens = float(burst)
        self._last_update = 0.0

    def consume(self, current_time: float) -> bool:
        elapsed = current_time - self._last_update
        self._last_update = current_time
        self._tokens = min(self._burst, self._tokens + elapsed * self._rate)
        if self._tokens >= 1.0:
            self._tokens -= 1.0
            return True
        return False


class Node:
    def __init__(self, config: HeuristicConfig, seed: int = 42) -> None:
        self.config = config
        self.rng = random.Random(seed)
        self.pool = TxStore(
            capacity=config.pool_capacity,
            max_per_sender=MAX_TXS_PER_SENDER,
            eviction_policy=config.eviction_policy,
            age_weight=config.age_weight,
        )
        self.peers: dict[str, PeerState] = {}
        self.custody_mask = self._pick_custody()
        self.log: list[dict[str, Any]] = []
        self.pool_snapshots: list[tuple[float, int]] = []
        self._rate_limiter = TokenBucket(
            config.max_announcements_per_second,
            config.burst_allowance,
        )

    def _pick_custody(self) -> int:
        cols = self.rng.sample(range(CELLS_PER_BLOB), self.config.custody_columns)
        return columns_to_mask(cols)

    def add_peer(self, peer: PeerState) -> None:
        self.peers[peer.peer_id] = peer

    def disconnect_peer(self, peer_id: str, reason: str, t: float) -> None:
        peer = self.peers.get(peer_id)
        if peer and not peer.disconnected:
            peer.disconnected = True
            peer.disconnect_reason = reason
            peer.disconnect_time = t
            self.log.append({
                "t": t, "event": "disconnect", "peer_id": peer_id,
                "reason": reason, "behavior": peer.behavior,
            })

    def _determine_role(self, tx_hash: str) -> Role:
        h = sha256(f"role:{tx_hash}:{self.rng.random()}".encode()).digest()
        p = int.from_bytes(h[:8], "big") / (2**64)
        return Role.PROVIDER if p < self.config.provider_probability else Role.SAMPLER

    def compute_request_columns(self, *, is_provider: bool) -> list[int]:
        if is_provider:
            return list(range(CELLS_PER_BLOB))
        custody = mask_to_columns(self.custody_mask)
        non_custody = [c for c in range(CELLS_PER_BLOB) if c not in custody]
        c_extra = self.rng.randint(1, self.config.c_extra_max)
        extra = self.rng.sample(non_custody, min(c_extra, len(non_custody)))
        return custody + extra

    def handle_announce(
        self, peer_id: str, tx_hash: str, sender: str, nonce: int,
        fee: float, cell_mask: int, is_provider: bool, exclusive: bool, t: float,
    ) -> list[Event]:
        follow_up: list[Event] = []
        peer = self.peers.get(peer_id)
        if peer is None or peer.disconnected:
            return follow_up

        # Rate limiting: reject if announcement rate too high
        if not self._rate_limiter.consume(t):
            self.log.append({
                "t": t, "event": "reject_rate_limit", "tx_hash": tx_hash,
                "peer_id": peer_id,
            })
            return follow_up

        if is_provider:
            peer.provider_announcements += 1
        else:
            peer.sampler_announcements += 1
        peer.announcements_made += 1
        peer.bytes_in += ANNOUNCE_MSG_BYTES

        # H1: reject txs that can't be included at the current blob base fee
        if fee < self.config.blob_base_fee * self.config.includability_discount:
            self.log.append({
                "t": t, "event": "reject_h1", "tx_hash": tx_hash,
                "peer_id": peer_id, "fee": fee,
            })
            return follow_up

        existing = self.pool.get(tx_hash)
        if existing is not None:
            existing.announcers.add(peer_id)
            return follow_up

        role = self._determine_role(tx_hash)
        tx = TxEntry(
            tx_hash=tx_hash, sender=sender, nonce=nonce, fee=fee,
            first_seen=t, role=role, cell_mask=0, announcers={peer_id},
        )
        evicted = self.pool.add(tx)
        if not self.pool.contains(tx_hash):
            return follow_up

        for ev_hash in evicted:
            self.log.append({"t": t, "event": "evict_capacity", "tx_hash": ev_hash})

        self.pool_snapshots.append((t, self.pool.count))

        # H2: verify the tx is independently announced by enough peers
        follow_up.append(Event(
            t=t + self.config.saturation_timeout,
            kind="saturation_check",
            data={"tx_hash": tx_hash},
        ))

        # H3: request cells with C_extra noise columns to detect withholders
        request_cols = self.compute_request_columns(is_provider=(role == Role.PROVIDER))
        peer.requests_sent_to += 1
        peer.bytes_out += REQUEST_MSG_OVERHEAD + len(request_cols) * 2
        follow_up.append(Event(
            t=t + 0.1,
            kind="request_cells",
            data={
                "peer_id": peer_id, "tx_hash": tx_hash,
                "columns": request_cols,
                "custody_columns": mask_to_columns(self.custody_mask),
            },
        ))

        self.log.append({
            "t": t, "event": "accept", "tx_hash": tx_hash,
            "role": role.name, "peer_id": peer_id,
        })
        return follow_up

    def handle_cells_response(
        self, peer_id: str, tx_hash: str,
        served: list[int], failed: list[int],
        custody_columns: list[int], t: float,
    ) -> list[Event]:
        follow_up: list[Event] = []
        peer = self.peers.get(peer_id)
        if peer is None or peer.disconnected:
            return follow_up

        peer.bytes_in += len(served) * CELL_BYTES

        custody_set = set(custody_columns)
        for col in served:
            if col not in custody_set:
                peer.record_random_column_result(success=True)
            peer.cells_served += 1

        for col in failed:
            if col not in custody_set:
                peer.record_random_column_result(success=False)

        # H4: disconnect peers with excessive random column failure rates
        if (
            len(peer._random_col_results) >= 10
            and peer.random_column_failure_rate() > self.config.max_random_failure_rate
        ):
            self.disconnect_peer(peer_id, "h4_random_col_failure", t)
            return follow_up

        tx = self.pool.get(tx_hash)
        if tx is not None:
            tx.cell_mask |= columns_to_mask(served)

        return follow_up

    def handle_saturation_check(self, tx_hash: str, t: float) -> list[Event]:
        tx = self.pool.get(tx_hash)
        if tx is None:
            return []
        independent = {
            p for p in tx.announcers
            if p in self.peers and not self.peers[p].disconnected
        }
        if len(independent) < self.config.min_independent_peers:
            self.pool.remove(tx_hash)
            self.pool_snapshots.append((t, self.pool.count))
            self.log.append({
                "t": t, "event": "evict_h2_saturation",
                "tx_hash": tx_hash, "announcers": len(independent),
            })
        return []

    def handle_inbound_request(
        self, peer_id: str, columns: list[int], t: float,
    ) -> list[Event]:
        peer = self.peers.get(peer_id)
        if peer is None or peer.disconnected:
            return []

        peer.requests_received += 1
        peer.bytes_in += REQUEST_MSG_OVERHEAD + len(columns) * 2
        peer.bytes_out += len(columns) * CELL_BYTES

        self.log.append({
            "t": t, "event": "inbound_request_tracked",
            "peer_id": peer_id, "n_columns": len(columns),
        })

        # H5: disconnect peers with excessive request-to-announcement ratio
        total_ann = max(peer.announcements_made, 1)
        duration = t - peer.connected_at
        if (
            duration > 60.0
            and peer.requests_received / total_ann > self.config.max_request_to_announce_ratio
        ):
            self.disconnect_peer(peer_id, "h5_request_ratio", t)

        return []

    def handle_block(self, included_txs: list[str], t: float) -> list[Event]:
        for tx_hash in included_txs:
            tx = self.pool.get(tx_hash)
            if tx is not None:
                for peer_id in tx.announcers:
                    peer = self.peers.get(peer_id)
                    if peer:
                        peer.included_contributions += 1
                self.pool.remove(tx_hash)
        self.pool_snapshots.append((t, self.pool.count))
        return []

    def score_peers(self, t: float) -> list[Event]:
        for peer in self.peers.values():
            if peer.disconnected:
                continue
            duration = t - peer.connected_at

            duration_score = min(duration / 300.0, 1.0)
            contribution_score = min(peer.included_contributions / 10.0, 1.0)
            failure_penalty = peer.random_column_failure_rate()
            announcer_penalty = 0.0 if peer.announcements_made > 0 else (0.3 if duration > 60.0 else 0.0)

            total_ann = max(peer.announcements_made, 1)
            request_ratio = peer.requests_received / total_ann
            request_ratio_penalty = min(request_ratio / self.config.max_request_to_announce_ratio, 1.0)

            expected_p = self.config.provider_probability
            actual_p = peer.provider_rate()
            provider_deviation = abs(actual_p - expected_p)
            provider_penalty = max(0.0, provider_deviation - self.config.provider_rate_tolerance)

            inbound_penalty = self.config.inbound_score_discount if peer.is_inbound else 0.0

            peer.score = (
                0.20 * duration_score
                + 0.30 * contribution_score
                - 0.15 * failure_penalty
                - 0.10 * announcer_penalty
                - 0.10 * request_ratio_penalty
                - 0.05 * provider_penalty
                - 0.10 * inbound_penalty
            )
        return []
