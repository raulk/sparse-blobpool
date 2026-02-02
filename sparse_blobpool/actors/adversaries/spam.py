"""SpamAdversary for T1.1/T1.2 spam attack scenarios."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import TYPE_CHECKING

from sparse_blobpool.actors.adversaries.base import Adversary, AttackConfig
from sparse_blobpool.actors.adversaries.commands import SpamNext
from sparse_blobpool.actors.adversaries.victim_selection import (
    VictimSelectionConfig,
    VictimSelectionStrategy,
    VictimSelector,
)
from sparse_blobpool.core.types import TxHash
from sparse_blobpool.protocol.constants import ALL_ONES
from sparse_blobpool.protocol.messages import NewPooledTransactionHashes

if TYPE_CHECKING:
    from sparse_blobpool.core.events import Command
    from sparse_blobpool.core.simulator import Simulator
    from sparse_blobpool.core.types import ActorId


@dataclass
class SpamAttackConfig(AttackConfig):
    spam_rate: float = 10.0
    valid_headers: bool = True
    provide_data: bool = False
    victim_selection_config: VictimSelectionConfig | None = None


class SpamAdversary(Adversary):
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
        attack_config: SpamAttackConfig,
        all_nodes: list[ActorId],
    ) -> None:
        super().__init__(actor_id, simulator, controlled_nodes, attack_config)
        self._spam_config = attack_config
        self._all_nodes = all_nodes
        self._spam_counter = 0

        # Initialize victim selector
        victim_config = attack_config.victim_selection_config or VictimSelectionConfig(
            strategy=VictimSelectionStrategy.ALL_NODES
        )
        self._victim_selector = VictimSelector(
            victim_config,
            simulator,
            all_nodes,
            controlled_nodes=controlled_nodes,
        )

    def execute(self) -> None:
        self._attack_started = True
        self._schedule_next_spam()

    def _schedule_next_spam(self) -> None:
        if self._attack_stopped:
            return

        delay = 1.0 / self._spam_config.spam_rate
        self.schedule_command(delay, SpamNext())

    def _on_command(self, cmd: Command) -> None:
        match cmd:
            case SpamNext():
                self._inject_spam()
                self._schedule_next_spam()

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

        # Use victim selector to determine targets
        targets = self._victim_selector.get_victims()
        for target in targets:
            self.send(announcement, to=target)

        # Record spam sent to victims in metrics
        for victim_id in targets:
            self.simulator.metrics.record_victim_targeted(victim_id, "spam", tx_hash)

    def _generate_spam_tx_hash(self) -> TxHash:
        data = f"spam:{self.id}:{self._spam_counter}".encode()
        return TxHash(sha256(data).hexdigest())

    @property
    def victims(self) -> list[ActorId]:
        """Get list of victim nodes."""
        return self._victim_selector.get_victims()
