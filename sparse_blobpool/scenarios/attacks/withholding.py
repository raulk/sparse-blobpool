"""Withholding attack scenario (T2.1).

T2.1: Selective withholding - serve custody cells but withhold reconstruction data.
Detection relies on C_extra sampling (honest nodes sample extra columns beyond custody).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from sparse_blobpool.actors.adversaries import WithholdingAdversary, WithholdingConfig
from sparse_blobpool.config import SimulationConfig
from sparse_blobpool.core.simulator import Simulator
from sparse_blobpool.core.types import ActorId

if TYPE_CHECKING:
    pass


@dataclass(frozen=True)
class WithholdingScenarioConfig:
    """Configuration for withholding attack scenario."""

    columns_to_serve: frozenset[int] = field(
        default_factory=lambda: frozenset(range(64))
    )
    delay_other_columns: float | None = None
    num_attacker_nodes: int = 1
    attacker_fraction: float | None = None
    attack_start_time: float = 0.0


def run_withholding_scenario(
    config: SimulationConfig | None = None,
    attack_config: WithholdingScenarioConfig | None = None,
    num_transactions: int = 10,
    run_duration: float | None = None,
) -> Simulator:
    """Run a withholding attack scenario.

    Sets up a network with honest nodes and adversary nodes that selectively
    withhold columns. Adversary nodes act as providers but only serve a subset
    of columns, attempting to prevent full reconstruction.

    Args:
        config: Simulation configuration for the network.
        attack_config: Configuration for the withholding attack behavior.
        num_transactions: Number of legitimate transactions to broadcast.
        run_duration: Duration to run the simulation.

    Returns:
        Simulator instance with attack results for metrics analysis.
    """
    if config is None:
        config = SimulationConfig()

    if attack_config is None:
        attack_config = WithholdingScenarioConfig()

    if run_duration is None:
        run_duration = config.duration

    sim = Simulator.build(config)

    all_node_ids = [node.id for node in sim.nodes]
    controlled_nodes = _select_attacker_nodes(sim, attack_config, all_node_ids)

    adversary_id = ActorId("withholding_adversary")
    adversary = WithholdingAdversary(
        actor_id=adversary_id,
        simulator=sim,
        controlled_nodes=controlled_nodes,
        attack_config=WithholdingConfig(
            start_time=attack_config.attack_start_time,
            columns_to_serve=set(attack_config.columns_to_serve),
            delay_other_columns=attack_config.delay_other_columns,
        ),
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
    attack_config: WithholdingScenarioConfig,
    all_node_ids: list[ActorId],
) -> list[ActorId]:
    """Select nodes to be controlled by the adversary."""
    if attack_config.attacker_fraction is not None:
        num_nodes = max(1, int(len(all_node_ids) * attack_config.attacker_fraction))
    else:
        num_nodes = attack_config.num_attacker_nodes

    if num_nodes >= len(all_node_ids):
        return list(all_node_ids)

    indices = sim.rng.sample(range(len(all_node_ids)), num_nodes)
    return [all_node_ids[i] for i in indices]
