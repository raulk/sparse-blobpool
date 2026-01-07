"""Targeted poisoning attack scenario (T4.2).

T4.2: Selective availability signaling - signal availability only to victim,
create nonce chains that fill the victim's per-sender blobpool slots.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sparse_blobpool.actors.adversaries import (
    TargetedPoisoningAdversary,
    TargetedPoisoningConfig,
)
from sparse_blobpool.config import SimulationConfig
from sparse_blobpool.core.simulator import Simulator
from sparse_blobpool.core.types import ActorId, Address

if TYPE_CHECKING:
    pass


@dataclass(frozen=True)
class PoisoningScenarioConfig:
    """Configuration for targeted poisoning attack scenario."""

    num_attacker_connections: int = 4
    nonce_chain_length: int = 16
    injection_interval: float = 0.1
    num_victims: int = 1
    victim_fraction: float | None = None
    attack_start_time: float = 0.0


def run_poisoning_scenario(
    config: SimulationConfig | None = None,
    attack_config: PoisoningScenarioConfig | None = None,
    num_transactions: int = 10,
    run_duration: float | None = None,
) -> Simulator:
    """Run a targeted poisoning attack scenario.

    Sets up a network with honest nodes and adversaries that target specific
    victims with private availability signals. Each adversary creates nonce
    chains that fill the victim's per-sender blobpool slots.

    Args:
        config: Simulation configuration for the network.
        attack_config: Configuration for the poisoning attack behavior.
        num_transactions: Number of legitimate transactions to broadcast.
        run_duration: Duration to run the simulation.

    Returns:
        Simulator instance with attack results for metrics analysis.
    """
    if config is None:
        config = SimulationConfig()

    if attack_config is None:
        attack_config = PoisoningScenarioConfig()

    if run_duration is None:
        run_duration = config.duration

    sim = Simulator.build(config)

    all_node_ids = [node.id for node in sim.nodes]
    victims = _select_victims(sim, attack_config, all_node_ids)

    adversaries: list[TargetedPoisoningAdversary] = []
    for i, victim_id in enumerate(victims):
        controlled_nodes = _select_attacker_nodes(
            sim, attack_config.num_attacker_connections, all_node_ids, victim_id
        )

        adversary_id = ActorId(f"poisoning_adversary_{i}")
        adversary = TargetedPoisoningAdversary(
            actor_id=adversary_id,
            simulator=sim,
            controlled_nodes=controlled_nodes,
            attack_config=TargetedPoisoningConfig(
                start_time=attack_config.attack_start_time,
                victim_id=victim_id,
                num_attacker_connections=attack_config.num_attacker_connections,
                nonce_chain_length=attack_config.nonce_chain_length,
                injection_interval=attack_config.injection_interval,
                sender_address=Address(f"0xattacker_{i}"),
            ),
        )
        sim.register_actor(adversary)
        adversaries.append(adversary)

    for _ in range(num_transactions):
        origin_idx = sim.rng.randint(0, len(sim.nodes) - 1)
        sim.broadcast_transaction(sim.nodes[origin_idx])

    for adversary in adversaries:
        adversary.execute()

    sim.block_producer.start()
    sim.run(run_duration)

    return sim


def _select_victims(
    sim: Simulator,
    attack_config: PoisoningScenarioConfig,
    all_node_ids: list[ActorId],
) -> list[ActorId]:
    """Select victim nodes to target."""
    if attack_config.victim_fraction is not None:
        num_victims = max(1, int(len(all_node_ids) * attack_config.victim_fraction))
    else:
        num_victims = attack_config.num_victims

    if num_victims >= len(all_node_ids):
        return list(all_node_ids)

    indices = sim.rng.sample(range(len(all_node_ids)), num_victims)
    return [all_node_ids[i] for i in indices]


def _select_attacker_nodes(
    sim: Simulator,
    num_connections: int,
    all_node_ids: list[ActorId],
    exclude_victim: ActorId,
) -> list[ActorId]:
    """Select nodes to use as attacker connections (excluding the victim)."""
    available = [nid for nid in all_node_ids if nid != exclude_victim]

    if num_connections >= len(available):
        return available

    indices = sim.rng.sample(range(len(available)), num_connections)
    return [available[i] for i in indices]
