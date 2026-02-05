"""Targeted poisoning attack scenario (T4.2).

T4.2: Selective availability signaling - signal availability only to victim,
create nonce chains that fill the victim's per-sender blobpool slots.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256

from sparse_blobpool.actors.adversaries.victim_selection import (
    VictimSelectionConfig,
    VictimSelectionStrategy,
    VictimSelector,
)
from sparse_blobpool.config import SimulationConfig
from sparse_blobpool.core.actor import Actor
from sparse_blobpool.core.events import Command, EventPayload, Message
from sparse_blobpool.core.simulator import Simulator
from sparse_blobpool.core.types import ActorId, Address, TxHash
from sparse_blobpool.protocol.constants import ALL_ONES
from sparse_blobpool.protocol.messages import NewPooledTransactionHashes


@dataclass
class InjectNext(Command):
    """Trigger next poison tx injection in a nonce chain."""
    victim_id: ActorId


@dataclass(frozen=True)
class PoisoningScenarioConfig:
    """Configuration for targeted poisoning attack scenario."""

    num_attacker_connections: int = 4
    nonce_chain_length: int = 16
    injection_interval: float = 0.1
    victim_selection_config: VictimSelectionConfig | None = None
    attack_start_time: float = 0.0


class TargetedPoisoningAdversary(Actor):
    """Signal availability only to victim, create nonce gaps.

    This adversary:
    1. Connects k controlled nodes to a victim node
    2. Announces transactions ONLY to the victim (not rest of network)
    3. Creates nonce chains that fill the victim's per-sender blobpool slots
    4. Victim cannot evict these txs because they have the lowest nonces

    The attack exploits:
    - 16 tx per sender limit in blobpool
    - Nonce ordering requirements (can't evict low-nonce tx)
    - Private signaling (only victim sees announcements)
    """

    def __init__(
        self,
        actor_id: ActorId,
        simulator: Simulator,
        controlled_nodes: list[ActorId],
        poisoning_config: PoisoningScenarioConfig,
        all_nodes: list[ActorId],
    ) -> None:
        super().__init__(actor_id, simulator)
        self._controlled_nodes = controlled_nodes
        self._poisoning_config = poisoning_config
        self._sender = Address(f"0xattacker_{actor_id}")
        self._attack_started = False
        self._attack_stopped = False

        # Initialize victim selector
        victim_config = poisoning_config.victim_selection_config or VictimSelectionConfig(
            strategy=VictimSelectionStrategy.RANDOM,
            num_victims=1
        )
        self._victim_selector = VictimSelector(
            victim_config,
            simulator,
            all_nodes,
            controlled_nodes=controlled_nodes,
        )
        self._victim_nonces: dict[ActorId, int] = {}

    @property
    def victims(self) -> list[ActorId]:
        """Get list of victim nodes."""
        return self._victim_selector.get_victims()

    @property
    def controlled_nodes(self) -> list[ActorId]:
        return self._controlled_nodes

    def on_event(self, payload: EventPayload) -> None:
        match payload:
            case Message() as msg:
                self._on_message(msg)
            case Command() as cmd:
                self._on_command(cmd)

    def _on_message(self, msg: Message) -> None:
        pass

    def _on_command(self, cmd: Command) -> None:
        match cmd:
            case InjectNext(victim_id=victim_id):
                self._inject_next_tx(victim_id)

    def execute(self) -> None:
        self._attack_started = True
        # Start injection for each victim
        for victim_id in self._victim_selector.get_victims():
            self._victim_nonces[victim_id] = 0
            self._inject_next_tx(victim_id)

    def _inject_next_tx(self, victim_id: ActorId) -> None:
        if self._attack_stopped:
            return

        nonce = self._victim_nonces.get(victim_id, 0)
        if nonce >= self._poisoning_config.nonce_chain_length:
            return  # Chain complete for this victim

        tx_hash = self._create_poison_tx(victim_id, nonce)

        announcement = NewPooledTransactionHashes(
            sender=self.id,
            types=bytes([3]),  # Blob tx type
            sizes=[131072],
            hashes=[tx_hash],
            cell_mask=ALL_ONES,  # Claim to be provider
        )

        self.send(announcement, to=victim_id)

        # Record poisoning in metrics
        self.simulator.metrics.record_victim_targeted(victim_id, "poisoning", tx_hash)
        self.simulator.metrics.record_poisoning(victim_id, tx_hash)

        self._victim_nonces[victim_id] = nonce + 1

        if nonce + 1 < self._poisoning_config.nonce_chain_length:
            self.schedule_command(
                self._poisoning_config.injection_interval,
                InjectNext(victim_id=victim_id),
            )

    def _create_poison_tx(self, victim_id: ActorId, nonce: int) -> TxHash:
        data = f"poison:{self.id}:{victim_id}:{self._sender}:{nonce}".encode()
        return TxHash(sha256(data).hexdigest())

    def get_attack_progress(self) -> dict[str, int | float]:
        total_nonces = sum(self._victim_nonces.values())
        return {
            "nonces_injected": total_nonces,
            "target_nonces": self._poisoning_config.nonce_chain_length * len(self.victims),
            "attacker_nodes": len(
                self._controlled_nodes[: self._poisoning_config.num_attacker_connections]
            ),
            "victim_count": len(self.victims),
        }


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

    # Select controlled nodes
    controlled_nodes = _select_attacker_nodes(
        sim, attack_config.num_attacker_connections, all_node_ids
    )

    adversary_id = ActorId("poisoning_adversary")
    adversary = TargetedPoisoningAdversary(
        actor_id=adversary_id,
        simulator=sim,
        controlled_nodes=controlled_nodes,
        poisoning_config=attack_config,
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
    num_connections: int,
    all_node_ids: list[ActorId],
) -> list[ActorId]:
    """Select nodes to use as attacker connections."""
    if num_connections >= len(all_node_ids):
        return all_node_ids

    indices = sim.rng.sample(range(len(all_node_ids)), num_connections)
    return [all_node_ids[i] for i in indices]
