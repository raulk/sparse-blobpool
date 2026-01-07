"""Targeted poisoning attack scenario (T4.2).

T4.2: Selective availability signaling - signal availability only to victim,
create nonce chains that fill the victim's per-sender blobpool slots.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import TYPE_CHECKING

from sparse_blobpool.config import SimulationConfig
from sparse_blobpool.core.actor import Actor
from sparse_blobpool.core.events import Command, EventPayload, Message
from sparse_blobpool.core.simulator import Simulator
from sparse_blobpool.core.types import ActorId, Address, TxHash
from sparse_blobpool.protocol.constants import ALL_ONES
from sparse_blobpool.protocol.messages import NewPooledTransactionHashes

if TYPE_CHECKING:
    pass


@dataclass
class InjectNext(Command):
    """Trigger next poison tx injection in a nonce chain."""


@dataclass(frozen=True)
class PoisoningScenarioConfig:
    """Configuration for targeted poisoning attack scenario."""

    num_attacker_connections: int = 4
    nonce_chain_length: int = 16
    injection_interval: float = 0.1
    num_victims: int = 1
    victim_fraction: float | None = None
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
        victim_id: ActorId | None,
        poisoning_config: PoisoningScenarioConfig,
    ) -> None:
        super().__init__(actor_id, simulator)
        self._controlled_nodes = controlled_nodes
        self._victim_id = victim_id
        self._poisoning_config = poisoning_config
        self._current_nonce = 0
        self._sender = Address(f"0xattacker_{actor_id}")
        self._attack_started = False
        self._attack_stopped = False

    @property
    def victim_id(self) -> ActorId | None:
        return self._victim_id

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
            case InjectNext():
                self._inject_next_tx()

    def execute(self) -> None:
        if self._victim_id is None:
            return  # No victim configured

        self._attack_started = True
        self._inject_next_tx()

    def _inject_next_tx(self) -> None:
        if self._attack_stopped:
            return
        if self._current_nonce >= self._poisoning_config.nonce_chain_length:
            return  # Chain complete

        tx_hash = self._create_poison_tx()

        announcement = NewPooledTransactionHashes(
            sender=self.id,
            types=bytes([3]),  # Blob tx type
            sizes=[131072],
            hashes=[tx_hash],
            cell_mask=ALL_ONES,  # Claim to be provider
        )

        if self._victim_id is not None:
            self.send(announcement, to=self._victim_id)

        self._current_nonce += 1

        if self._current_nonce < self._poisoning_config.nonce_chain_length:
            self.schedule_command(
                self._poisoning_config.injection_interval,
                InjectNext(),
            )

    def _create_poison_tx(self) -> TxHash:
        data = f"poison:{self.id}:{self._sender}:{self._current_nonce}".encode()
        return TxHash(sha256(data).hexdigest())

    def get_attack_progress(self) -> dict[str, int | float]:
        return {
            "nonces_injected": self._current_nonce,
            "target_nonces": self._poisoning_config.nonce_chain_length,
            "attacker_nodes": len(
                self._controlled_nodes[: self._poisoning_config.num_attacker_connections]
            ),
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
            victim_id=victim_id,
            poisoning_config=attack_config,
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