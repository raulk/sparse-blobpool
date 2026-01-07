"""Spam attack scenario (T1.1/T1.2).

T1.1: Valid headers, unavailable data - fills blobpools with unfetchable txs
T1.2: Invalid/nonsense data - detected via provider backbone
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sparse_blobpool.actors.adversaries import SpamAdversary, SpamAttackConfig
from sparse_blobpool.config import SimulationConfig
from sparse_blobpool.core.simulator import Simulator
from sparse_blobpool.core.types import ActorId

if TYPE_CHECKING:
    pass


@dataclass(frozen=True)
class SpamScenarioConfig:
    """Configuration for spam attack scenario."""

    spam_rate: float = 10.0
    valid_headers: bool = True
    provide_data: bool = False
    num_attacker_nodes: int = 1
    attack_start_time: float = 0.0
    attack_duration: float | None = None
    target_fraction: float | None = None


def run_spam_scenario(
    config: SimulationConfig | None = None,
    attack_config: SpamScenarioConfig | None = None,
    num_transactions: int = 10,
    run_duration: float | None = None,
) -> Simulator:
    """Run a spam attack scenario.

    Sets up a network with honest nodes and a spam adversary that floods the
    network with garbage blob transactions.

    Args:
        config: Simulation configuration for the network.
        attack_config: Configuration for the spam attack behavior.
        num_transactions: Number of legitimate transactions to broadcast.
        run_duration: Duration to run the simulation.

    Returns:
        Simulator instance with attack results for metrics analysis.
    """
    if config is None:
        config = SimulationConfig()

    if attack_config is None:
        attack_config = SpamScenarioConfig()

    if run_duration is None:
        run_duration = config.duration

    sim = Simulator.build(config)

    all_node_ids = [node.id for node in sim.nodes]
    controlled_nodes = _select_attacker_nodes(
        sim, attack_config.num_attacker_nodes, all_node_ids
    )
    target_nodes = _select_target_nodes(sim, attack_config.target_fraction, all_node_ids)

    adversary_id = ActorId("spam_adversary")
    adversary = SpamAdversary(
        actor_id=adversary_id,
        simulator=sim,
        controlled_nodes=controlled_nodes,
        attack_config=SpamAttackConfig(
            start_time=attack_config.attack_start_time,
            duration=attack_config.attack_duration,
            spam_rate=attack_config.spam_rate,
            valid_headers=attack_config.valid_headers,
            provide_data=attack_config.provide_data,
            target_nodes=target_nodes,
        ),
        all_nodes=all_node_ids,
    )
    sim.register_actor(adversary)

    for _ in range(num_transactions):
        origin_idx = sim.rng.randint(0, len(sim.nodes) - 1)
        sim.broadcast_transaction(sim.nodes[origin_idx])

    adversary.execute()

    sim.block_producer.start()
    sim.run(run_duration)

    return sim


def _select_attacker_nodes(
    sim: Simulator,
    num_nodes: int,
    all_node_ids: list[ActorId],
) -> list[ActorId]:
    """Select nodes to be controlled by the adversary."""
    if num_nodes >= len(all_node_ids):
        return list(all_node_ids)

    indices = sim.rng.sample(range(len(all_node_ids)), num_nodes)
    return [all_node_ids[i] for i in indices]


def _select_target_nodes(
    sim: Simulator,
    target_fraction: float | None,
    all_node_ids: list[ActorId],
) -> list[ActorId] | None:
    """Select subset of nodes to target, or None for all nodes."""
    if target_fraction is None:
        return None

    target_count = max(1, int(len(all_node_ids) * target_fraction))
    if target_count >= len(all_node_ids):
        return None

    indices = sim.rng.sample(range(len(all_node_ids)), target_count)
    return [all_node_ids[i] for i in indices]
