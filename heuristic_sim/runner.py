from __future__ import annotations

import random
from typing import Any

from heuristic_sim.config import ALL_ONES, HeuristicConfig, Scenario
from heuristic_sim.events import Event, EventLoop
from heuristic_sim.metrics import SimulationResult
from heuristic_sim.node import Node
from heuristic_sim.peers import (
    BEHAVIOR_CLASSES,
    HonestBehavior,
    PeerBehavior,
    PeerState,
)


def _create_peers_and_events(
    scenario: Scenario,
    config: HeuristicConfig,
    node: Node,
    loop: EventLoop,
    rng: random.Random,
) -> dict[str, PeerBehavior]:
    """Wire up honest + attacker peers and schedule their initial events."""
    behaviors: dict[str, PeerBehavior] = {}
    gen_kwargs: dict[str, Any] = {
        "t_start": 0.0,
        "t_end": scenario.t_end,
        "tx_rate": scenario.tx_arrival_rate,
        "blob_base_fee": scenario.blob_base_fee,
        "includability_discount": config.includability_discount,
    }

    n_outbound = round(scenario.n_honest * (1 - scenario.inbound_ratio))
    for i in range(scenario.n_honest):
        pid = f"honest_{i}"
        behavior = HonestBehavior(pid, random.Random(rng.randint(0, 2**32)))
        behaviors[pid] = behavior
        is_inbound = i >= n_outbound
        node.add_peer(PeerState(pid, "honest", 0.0, is_inbound=is_inbound))
        for ev in behavior.generate_events(**gen_kwargs):
            loop.schedule(ev)

    for count, btype, bkwargs in scenario.attackers:
        cls = BEHAVIOR_CLASSES[btype]
        for i in range(count):
            pid = f"{btype}_{i}"
            behavior = cls(pid, random.Random(rng.randint(0, 2**32)), **bkwargs)
            behaviors[pid] = behavior
            node.add_peer(PeerState(pid, btype, 0.0, is_inbound=True))
            for ev in behavior.generate_events(**gen_kwargs):
                loop.schedule(ev)

    return behaviors


def _schedule_periodic_events(scenario: Scenario, loop: EventLoop) -> None:
    """Schedule block production and peer scoring ticks."""
    t = scenario.block_interval
    while t < scenario.t_end:
        loop.schedule(Event(t=t, kind="block"))
        t += scenario.block_interval

    t = 30.0
    while t < scenario.t_end:
        loop.schedule(Event(t=t, kind="score_peers"))
        t += 30.0


def _dispatch_event(
    event: Event,
    node: Node,
    behaviors: dict[str, PeerBehavior],
    loop: EventLoop,
) -> None:
    """Route a single event to the appropriate Node handler and reschedule follow-ups."""
    if event.kind == "announce":
        d = event.data
        follow_ups = node.handle_announce(
            peer_id=d["peer_id"],
            tx_hash=d["tx_hash"],
            sender=d["sender"],
            nonce=d["nonce"],
            fee=d["fee"],
            cell_mask=d["cell_mask"],
            is_provider=d["is_provider"],
            exclusive=d["exclusive"],
            t=event.t,
        )
        for fu in follow_ups:
            loop.schedule(fu)

    elif event.kind == "request_cells":
        d = event.data
        peer_id = d["peer_id"]
        behavior = behaviors.get(peer_id)
        if behavior is None:
            return
        result = behavior.respond_to_cell_request(
            d["columns"],
            node.custody_mask,
        )
        follow_ups = node.handle_cells_response(
            peer_id=peer_id,
            tx_hash=d["tx_hash"],
            served=result["served"],
            failed=result["failed"],
            custody_columns=d["custody_columns"],
            t=event.t,
        )
        for fu in follow_ups:
            loop.schedule(fu)

    elif event.kind == "saturation_check":
        node.handle_saturation_check(event.data["tx_hash"], event.t)

    elif event.kind == "inbound_request":
        node.handle_inbound_request(
            event.data["peer_id"],
            event.data.get("columns", []),
            event.t,
        )

    elif event.kind == "block":
        includable = [tx.tx_hash for tx in node.pool.iter_all() if tx.cell_mask == ALL_ONES]
        selected = includable[:6]
        node.handle_block(selected, event.t)

    elif event.kind == "score_peers":
        node.score_peers(event.t)


def _compile_results(node: Node) -> SimulationResult:
    """Aggregate the node's event log into a SimulationResult."""
    result = SimulationResult(log=list(node.log))
    for entry in node.log:
        ev = entry["event"]
        if ev == "accept":
            result.total_accepted += 1
        elif ev == "reject_h1":
            result.total_rejected += 1
            result.h1_rejections += 1
        elif ev == "reject_rate_limit":
            result.total_rejected += 1
            result.rate_limit_rejections += 1
        elif ev == "evict_h2_saturation":
            result.h2_evictions += 1
        elif ev == "disconnect":
            behavior = entry["behavior"]
            result.disconnects_by_behavior[behavior] = (
                result.disconnects_by_behavior.get(behavior, 0) + 1
            )
            if entry["reason"] == "h4_random_col_failure":
                result.h4_disconnects += 1
            elif entry["reason"] == "h5_request_ratio":
                result.h5_disconnects += 1
            if behavior == "honest":
                result.false_positives += 1

    for peer in node.peers.values():
        beh = peer.behavior
        result.peer_counts[beh] = result.peer_counts.get(beh, 0) + 1
        bw = result.bandwidth_by_behavior.setdefault(beh, {"in": 0, "out": 0})
        bw["in"] += peer.bytes_in
        bw["out"] += peer.bytes_out

    result.pool_occupancy = list(node.pool_snapshots)
    if not result.pool_occupancy:
        result.pool_occupancy.append((0.0, node.pool.count))
    return result


def run_simulation(
    config: HeuristicConfig,
    scenario: Scenario,
    seed: int = 42,
) -> SimulationResult:
    rng = random.Random(seed)
    node = Node(config, seed=rng.randint(0, 2**32))
    loop = EventLoop()

    behaviors = _create_peers_and_events(scenario, config, node, loop, rng)
    _schedule_periodic_events(scenario, loop)

    for event in loop.run():
        _dispatch_event(event, node, behaviors, loop)

    return _compile_results(node)
