"""Spam attack scenario (T1.1/T1.2).

This scenario simulates a spam attack where an adversary floods the network
with garbage blob transactions to fill blobpools and waste bandwidth.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..adversaries.spam import SpamAdversary, SpamAttackConfig
from ..config import SimulationConfig
from ..core.simulator import Event, Simulator
from ..core.types import ActorId
from .baseline import broadcast_transaction, build_simulator


@dataclass
class SpamAttackResult:
    """Results from spam attack scenario."""

    simulator: Simulator
    adversary: SpamAdversary
    spam_txs_injected: int
    spam_txs_propagated: int
    honest_txs_evicted: int


def run_spam_attack(
    config: SimulationConfig | None = None,
    attack_config: SpamAttackConfig | None = None,
    num_honest_transactions: int = 10,
    run_duration: float | None = None,
) -> SpamAttackResult:
    """Run a spam attack scenario.

    Creates a simulation with honest nodes, then injects a spam adversary
    that floods the network with garbage transactions.

    Args:
        config: Simulation configuration. Uses defaults if not provided.
        attack_config: Spam attack configuration. Uses defaults if not provided.
        num_honest_transactions: Number of honest transactions to inject first.
        run_duration: How long to run. Uses config.duration if not specified.

    Returns:
        SpamAttackResult containing metrics about the attack.
    """
    if config is None:
        config = SimulationConfig()

    if attack_config is None:
        attack_config = SpamAttackConfig(
            spam_rate=50.0,  # 50 spam txs per second
            valid_headers=True,
            provide_data=False,
        )

    if run_duration is None:
        run_duration = config.duration

    # Build base simulation
    sim = build_simulator(config)

    # Inject honest transactions first
    for _ in range(num_honest_transactions):
        origin_idx = sim.rng.randint(0, len(sim.nodes) - 1)
        broadcast_transaction(sim, sim.nodes[origin_idx])

    # Create and register spam adversary
    adversary_id = ActorId("spam_adversary")
    all_node_ids = [node.id for node in sim.nodes]

    adversary = SpamAdversary(
        actor_id=adversary_id,
        simulator=sim,
        controlled_nodes=[ActorId("fake_node_0")],  # Single fake node
        attack_config=attack_config,
        all_nodes=all_node_ids,
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

    # Gather results
    spam_txs_injected = adversary._spam_counter
    spam_txs_propagated = 0
    honest_txs_evicted = 0  # Would need tracking in blobpool

    return SpamAttackResult(
        simulator=sim,
        adversary=adversary,
        spam_txs_injected=spam_txs_injected,
        spam_txs_propagated=spam_txs_propagated,
        honest_txs_evicted=honest_txs_evicted,
    )


class _AttackStartPayload:
    """Internal payload for triggering attack start."""


def main() -> None:
    """Run spam attack scenario and print analysis."""
    import json
    import time

    print("Building spam attack simulation with 100 nodes...")
    config = SimulationConfig(
        node_count=100,
        mesh_degree=10,
        duration=10.0,  # Short run for testing
    )

    attack_config = SpamAttackConfig(
        spam_rate=20.0,  # 20 spam txs per second
        valid_headers=True,
        provide_data=False,
        start_time=1.0,  # Start after 1 second
    )

    start = time.time()
    result = run_spam_attack(
        config=config,
        attack_config=attack_config,
        num_honest_transactions=5,
    )
    run_time = time.time() - start
    print(f"Completed in {run_time:.2f}s")

    print("\n=== Spam Attack Results ===")
    print(f"Spam txs injected: {result.spam_txs_injected}")
    print(f"Spam txs propagated: {result.spam_txs_propagated}")
    print(f"Honest txs evicted: {result.honest_txs_evicted}")
    print(f"Events processed: {result.simulator.events_processed}")
    print(f"Messages delivered: {result.simulator.network.messages_delivered}")
    print(f"Total bytes: {result.simulator.network.total_bytes / 1024:.1f} KB")

    # Finalize metrics
    print("\n=== Metrics Analysis ===")
    metrics = result.simulator.finalize_metrics()
    print(f"Total bandwidth: {metrics.total_bandwidth_bytes / 1024:.1f} KB")
    print(f"Bandwidth per blob: {metrics.bandwidth_per_blob / 1024:.1f} KB")

    # Export to JSON
    print("\n=== JSON Export ===")
    output = {
        "scenario": "spam_attack",
        "config": {
            "node_count": config.node_count,
            "spam_rate": attack_config.spam_rate,
            "duration": config.duration,
        },
        "results": {
            "spam_txs_injected": result.spam_txs_injected,
            "messages_delivered": result.simulator.network.messages_delivered,
            "total_bytes": result.simulator.network.total_bytes,
        },
        "metrics": metrics.to_dict(),
    }
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
