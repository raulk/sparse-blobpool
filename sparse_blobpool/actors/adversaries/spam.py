"""SpamAdversary for T1.1/T1.2 spam attack scenarios."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import TYPE_CHECKING

from ...core.actor import TimerKind, TimerPayload
from ...core.types import ActorId, TxHash
from ...protocol.constants import ALL_ONES
from ...protocol.messages import NewPooledTransactionHashes
from .base import Adversary, AttackConfig

if TYPE_CHECKING:
    from ...core.simulator import Simulator


@dataclass
class SpamAttackConfig(AttackConfig):
    spam_rate: float = 10.0
    valid_headers: bool = True
    provide_data: bool = False
    target_nodes: list[ActorId] | None = None


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

    def execute(self) -> None:
        self._attack_started = True
        self._schedule_next_spam()

    def _schedule_next_spam(self) -> None:
        if self._attack_stopped:
            return

        delay = 1.0 / self._spam_config.spam_rate
        self.schedule_timer(delay, TimerKind.SPAM_NEXT)

    def _on_timer(self, timer: TimerPayload) -> None:
        match timer.kind:
            case TimerKind.SPAM_NEXT:
                self._inject_spam()
                self._schedule_next_spam()

    def _inject_spam(self) -> None:
        tx_hash = self._generate_spam_tx_hash()
        self._spam_counter += 1

        # Create announcement with claimed cell availability
        # Use adversary's own ID as sender (adversary is registered with simulator)
        cell_mask = ALL_ONES if self._spam_config.valid_headers else 0
        announcement = NewPooledTransactionHashes(
            sender=self.id,
            types=bytes([3]),  # Blob tx type
            sizes=[131072],  # ~128 KB tx size
            hashes=[tx_hash],
            cell_mask=cell_mask,
        )

        # Send to targets
        targets = self._select_targets()
        for target in targets:
            self.send(announcement, to=target)

    def _generate_spam_tx_hash(self) -> TxHash:
        data = f"spam:{self.id}:{self._spam_counter}".encode()
        return TxHash(sha256(data).hexdigest())

    def _select_targets(self) -> list[ActorId]:
        if self._spam_config.target_nodes:
            return self._spam_config.target_nodes
        return self._all_nodes
