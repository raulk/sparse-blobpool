"""Targeted poisoning attack scenario (T4.2).

This scenario simulates a targeted poisoning attack where an adversary
signals transaction availability only to a victim node, filling their
blobpool with transactions the rest of the network doesn't have.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..adversaries.poisoning import TargetedPoisoningAdversary, TargetedPoisoningConfig
from ..config import SimulationConfig
from ..core.simulator import Event, Simulator
from ..core.types import ActorId
from .baseline import broadcast_transaction, build_simulator

if TYPE_CHECKING:
    from ..p2p.node import Node


@dataclass
class PoisoningAttackResult:
    """Results from targeted poisoning attack scenario."""

    simulator: Simulator
    adversary: TargetedPoisoningAdversary
    victim_node: Node
    poison_txs_injected: int
    victim_pool_size: int
    victim_pool_poison_count: int


def run_poisoning_attack(
    config: SimulationConfig | None = None,
    attack_config: TargetedPoisoningConfig | None = None,
    num_honest_transactions: int = 5,
    run_duration: float | None = None,
) -> PoisoningAttackResult:
    """Run a targeted poisoning attack scenario.

    Creates a simulation with honest nodes, selects a victim, then injects
    an adversary that signals transactions only to the victim.

    Args:
        config: Simulation configuration. Uses defaults if not provided.
        attack_config: Poisoning attack configuration. Uses defaults if not provided.
        num_honest_transactions: Number of honest transactions to inject first.
        run_duration: How long to run. Uses config.duration if not specified.

    Returns:
        PoisoningAttackResult containing metrics about the attack.
    """
    if config is None:
        config = SimulationConfig()

    if run_duration is None:
        run_duration = config.duration

    # Build base simulation
    sim = build_simulator(config)

    # Select victim (middle node for reproducibility)
    victim_idx = len(sim.nodes) // 2
    victim_node = sim.nodes[victim_idx]

    # Set up attack config with victim
    if attack_config is None:
        attack_config = TargetedPoisoningConfig(
            victim_id=victim_node.id,
            num_attacker_connections=4,
            nonce_chain_length=16,
            injection_interval=0.1,
            start_time=1.0,
        )
    else:
        # Override victim_id if not set
        if attack_config.victim_id is None:
            attack_config = TargetedPoisoningConfig(
                victim_id=victim_node.id,
                num_attacker_connections=attack_config.num_attacker_connections,
                nonce_chain_length=attack_config.nonce_chain_length,
                injection_interval=attack_config.injection_interval,
                start_time=attack_config.start_time,
                duration=attack_config.duration,
            )

    # Inject honest transactions first
    for _ in range(num_honest_transactions):
        origin_idx = sim.rng.randint(0, len(sim.nodes) - 1)
        broadcast_transaction(sim, sim.nodes[origin_idx])

    # Create controlled nodes (fake attacker nodes)
    controlled_nodes = [
        ActorId(f"attacker_node_{i}") for i in range(attack_config.num_attacker_connections)
    ]

    # Create and register poisoning adversary
    adversary_id = ActorId("poisoning_adversary")
    adversary = TargetedPoisoningAdversary(
        actor_id=adversary_id,
        simulator=sim,
        controlled_nodes=controlled_nodes,
        attack_config=attack_config,
    )
    sim.register_actor(adversary)

    # Start block production
    sim.block_producer.start()

    # Schedule attack start
    start_event = Event(
        timestamp=attack_config.start_time,
        target_id=adversary_id,
        payload=_AttackStartPayload(),
    )
    sim.schedule(start_event)

    # Override adversary's on_event to handle start
    original_on_event = adversary.on_event

    def _patched_on_event(payload: object) -> None:
        if isinstance(payload, _AttackStartPayload):
            adversary.execute()
        else:
            original_on_event(payload)  # type: ignore[arg-type]

    adversary.on_event = _patched_on_event  # type: ignore[method-assign]

    # Run simulation
    sim.run(run_duration)

    # Analyze victim's pool
    victim_pool_size = victim_node.pool.tx_count
    # Count poison transactions (those with our adversary's sender prefix)
    poison_count = sum(
        1
        for entry in [victim_node.pool.get(h) for h in victim_node.pool._txs]
        if entry is not None and "adversary" in str(entry.sender)
    )

    return PoisoningAttackResult(
        simulator=sim,
        adversary=adversary,
        victim_node=victim_node,
        poison_txs_injected=adversary._current_nonce,
        victim_pool_size=victim_pool_size,
        victim_pool_poison_count=poison_count,
    )


class _AttackStartPayload:
    """Internal payload for triggering attack start."""


def main() -> None:
    """Run poisoning attack scenario and print analysis."""
    import json
    import time

    print("Building poisoning attack simulation with 50 nodes...")
    config = SimulationConfig(
        node_count=50,
        mesh_degree=8,
        duration=10.0,  # Short run for testing
    )

    attack_config = TargetedPoisoningConfig(
        num_attacker_connections=4,
        nonce_chain_length=16,
        injection_interval=0.1,
        start_time=0.5,
    )

    start = time.time()
    result = run_poisoning_attack(
        config=config,
        attack_config=attack_config,
        num_honest_transactions=3,
    )
    run_time = time.time() - start
    print(f"Completed in {run_time:.2f}s")

    print("\n=== Targeted Poisoning Attack Results ===")
    print(f"Victim node: {result.victim_node.id}")
    print(f"Poison txs injected: {result.poison_txs_injected}")
    print(f"Victim pool size: {result.victim_pool_size}")
    print(f"Poison txs in victim pool: {result.victim_pool_poison_count}")

    # Check other nodes for comparison
    other_pools = [n.pool.tx_count for n in result.simulator.nodes if n != result.victim_node]
    avg_other_pool = sum(other_pools) / len(other_pools) if other_pools else 0
    print(f"Average pool size (other nodes): {avg_other_pool:.1f}")

    print(f"\nEvents processed: {result.simulator.events_processed}")
    print(f"Messages delivered: {result.simulator.network.messages_delivered}")

    # Attack effectiveness
    if result.victim_pool_size > 0:
        poison_ratio = result.victim_pool_poison_count / result.victim_pool_size
        print(f"\nPoison ratio in victim pool: {poison_ratio * 100:.1f}%")

    # Finalize metrics
    print("\n=== Metrics Analysis ===")
    metrics = result.simulator.finalize_metrics()
    print(f"Total bandwidth: {metrics.total_bandwidth_bytes / 1024:.1f} KB")
    print(f"Propagation success rate: {metrics.propagation_success_rate * 100:.1f}%")

    # Export to JSON
    print("\n=== JSON Export ===")
    output = {
        "scenario": "targeted_poisoning",
        "config": {
            "node_count": config.node_count,
            "nonce_chain_length": attack_config.nonce_chain_length,
            "num_attacker_connections": attack_config.num_attacker_connections,
            "duration": config.duration,
        },
        "results": {
            "poison_txs_injected": result.poison_txs_injected,
            "victim_pool_size": result.victim_pool_size,
            "victim_pool_poison_count": result.victim_pool_poison_count,
            "messages_delivered": result.simulator.network.messages_delivered,
        },
        "metrics": metrics.to_dict(),
    }
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
