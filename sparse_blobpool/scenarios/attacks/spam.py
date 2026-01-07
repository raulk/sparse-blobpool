"""Spam attack scenario (T1.1/T1.2).

T1.1: Valid headers, unavailable data - fills blobpools with unfetchable txs
T1.2: Invalid/nonsense data - detected via provider backbone
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256

from sparse_blobpool.config import SimulationConfig
from sparse_blobpool.core.actor import Actor
from sparse_blobpool.core.events import Command, EventPayload, Message
from sparse_blobpool.core.simulator import Simulator
from sparse_blobpool.core.types import ActorId, TxHash
from sparse_blobpool.protocol.constants import ALL_ONES
from sparse_blobpool.protocol.messages import NewPooledTransactionHashes


@dataclass
class SpamNext(Command):
    """Trigger next spam tx injection."""


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


class SpamAdversary(Actor):
    """Flood network with garbage blob transactions.

    This adversary injects spam transactions at a configurable rate. Spam can be:
    - T1.1: Valid headers, unavailable data -> fills blobpools with unfetchable txs
    - T1.2: Invalid/nonsense data -> detected via provider backbone
    """

    def __init__(
        self,
        actor_id: ActorId,
        simulator: Simulator,
        controlled_nodes: list[ActorId],
        spam_config: SpamScenarioConfig,
        all_nodes: list[ActorId],
    ) -> None:
        super().__init__(actor_id, simulator)
        self._controlled_nodes = controlled_nodes
        self._spam_config = spam_config
        self._all_nodes = all_nodes
        self._spam_counter = 0
        self._attack_started = False
        self._attack_stopped = False

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
            case SpamNext():
                self._inject_spam()
                self._schedule_next_spam()

    def execute(self) -> None:
        self._attack_started = True
        self._schedule_next_spam()

    def _schedule_next_spam(self) -> None:
        if self._attack_stopped:
            return

        delay = 1.0 / self._spam_config.spam_rate
        self.schedule_command(delay, SpamNext())

    def _inject_spam(self) -> None:
        tx_hash = self._generate_spam_tx_hash()
        self._spam_counter += 1

        cell_mask = ALL_ONES if self._spam_config.valid_headers else 0
        announcement = NewPooledTransactionHashes(
            sender=self.id,
            types=bytes([3]),  # Blob tx type
            sizes=[131072],  # ~128 KB tx size
            hashes=[tx_hash],
            cell_mask=cell_mask,
        )

        targets = self._select_targets()
        for target in targets:
            self.send(announcement, to=target)

    def _generate_spam_tx_hash(self) -> TxHash:
        data = f"spam:{self.id}:{self._spam_counter}".encode()
        return TxHash(sha256(data).hexdigest())

    def _select_targets(self) -> list[ActorId]:
        if self._spam_config.target_fraction is not None:
            target_count = max(1, int(len(self._all_nodes) * self._spam_config.target_fraction))
            if target_count >= len(self._all_nodes):
                return self._all_nodes
            indices = self.simulator.rng.sample(range(len(self._all_nodes)), target_count)
            return [self._all_nodes[i] for i in indices]
        return self._all_nodes


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
    controlled_nodes = _select_attacker_nodes(sim, attack_config.num_attacker_nodes, all_node_ids)

    adversary_id = ActorId("spam_adversary")
    adversary = SpamAdversary(
        actor_id=adversary_id,
        simulator=sim,
        controlled_nodes=controlled_nodes,
        spam_config=attack_config,
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
