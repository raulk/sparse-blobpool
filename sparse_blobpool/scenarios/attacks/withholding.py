"""Withholding attack scenario (T2.1).

T2.1: Selective withholding - serve custody cells but withhold reconstruction data.
Detection relies on C_extra sampling (honest nodes sample extra columns beyond custody).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sparse_blobpool.actors.adversaries.victim_selection import (
    VictimSelectionConfig,
    VictimSelectionStrategy,
    VictimSelector,
)
from sparse_blobpool.config import SimulationConfig
from sparse_blobpool.core.actor import Actor
from sparse_blobpool.core.events import Command, EventPayload, Message
from sparse_blobpool.core.simulator import Simulator
from sparse_blobpool.core.types import ActorId
from sparse_blobpool.protocol.messages import Cells, GetCells


@dataclass(frozen=True)
class WithholdingScenarioConfig:
    """Configuration for withholding attack scenario."""

    columns_to_serve: frozenset[int] = field(default_factory=lambda: frozenset(range(64)))
    delay_other_columns: float | None = None
    num_attacker_nodes: int = 1
    victim_selection_config: VictimSelectionConfig | None = None
    attack_start_time: float = 0.0


class WithholdingAdversary(Actor):
    """Serve custody cells but withhold reconstruction data.

    This adversary intercepts GetCells requests to controlled nodes and
    only serves columns in the allowed set. This simulates a provider
    that serves custody samples but withholds data needed for reconstruction.

    Detection relies on C_extra sampling: honest nodes sample extra columns
    beyond custody, which reveals withholding with high probability.
    """

    def __init__(
        self,
        actor_id: ActorId,
        simulator: Simulator,
        controlled_nodes: list[ActorId],
        withholding_config: WithholdingScenarioConfig,
        all_nodes: list[ActorId],
    ) -> None:
        super().__init__(actor_id, simulator)
        self._controlled_nodes = controlled_nodes
        self._withholding_config = withholding_config
        self._allowed_mask = self._compute_allowed_mask()
        self._attack_started = False
        self._attack_stopped = False

        # Initialize victim selector - withholding targets specific nodes
        victim_config = withholding_config.victim_selection_config or VictimSelectionConfig(
            strategy=VictimSelectionStrategy.ALL_NODES  # By default withhold from everyone
        )
        self._victim_selector = VictimSelector(
            victim_config,
            simulator,
            all_nodes,
            controlled_nodes=controlled_nodes,
        )
        self._affected_victims: set[ActorId] = set()

    def _compute_allowed_mask(self) -> int:
        mask = 0
        for col in self._withholding_config.columns_to_serve:
            mask |= 1 << col
        return mask

    def on_event(self, payload: EventPayload) -> None:
        match payload:
            case Message() as msg:
                self._on_message(msg)
            case Command() as cmd:
                self._on_command(cmd)

    def _on_message(self, msg: Message) -> None:
        match msg:
            case GetCells() as req:
                self._handle_get_cells(req)

    def _on_command(self, cmd: Command) -> None:
        pass

    def execute(self) -> None:
        self._attack_started = True

    def _handle_get_cells(self, req: GetCells) -> None:
        # Check if requester is a victim we should withhold from
        if req.sender not in self._victim_selector.get_victims():
            # Not a victim, serve normally
            response = Cells(
                sender=self.id,
                tx_hashes=req.tx_hashes,
                cells=[[] for _ in req.tx_hashes],  # Simplified - no actual cell data
                cell_mask=req.cell_mask,
            )
            self.send(response, to=req.sender)
            return

        # This is a victim - withhold data
        allowed = req.cell_mask & self._allowed_mask
        if allowed != req.cell_mask:
            # Track that this victim was affected
            self._affected_victims.add(req.sender)

            # Record withholding in metrics
            for tx_hash in req.tx_hashes:
                self.simulator.metrics.record_victim_targeted(
                    req.sender, "withholding", tx_hash
                )

            if self._withholding_config.delay_other_columns is not None:
                # Delay response for non-served columns
                pass
            else:
                # Drop the request entirely (timeout on requester side)
                pass

        if allowed:
            response = Cells(
                sender=self.id,
                tx_hashes=req.tx_hashes,
                cells=[[] for _ in req.tx_hashes],  # Simplified - no actual cell data
                cell_mask=allowed,
            )
            self.send(response, to=req.sender)

    def get_withheld_columns(self, request_mask: int) -> set[int]:
        withheld = request_mask & ~self._allowed_mask
        columns = set()
        for i in range(128):
            if withheld & (1 << i):
                columns.add(i)
        return columns

    @property
    def controlled_nodes(self) -> list[ActorId]:
        return self._controlled_nodes

    @property
    def victims(self) -> list[ActorId]:
        """Get list of victim nodes."""
        return self._victim_selector.get_victims()

    @property
    def affected_victims(self) -> set[ActorId]:
        """Get set of victims that were actually affected by withholding."""
        return self._affected_victims


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
        withholding_config=attack_config,
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
    attack_config: WithholdingScenarioConfig,
    all_node_ids: list[ActorId],
) -> list[ActorId]:
    """Select nodes to be controlled by the adversary."""
    num_nodes = attack_config.num_attacker_nodes

    if num_nodes >= len(all_node_ids):
        return list(all_node_ids)

    indices = sim.rng.sample(range(len(all_node_ids)), num_nodes)
    return [all_node_ids[i] for i in indices]
