"""TargetedPoisoningAdversary for T4.2 selective availability signaling attack."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import TYPE_CHECKING

from ...core.actor import TimerKind, TimerPayload
from ...core.types import ActorId, Address, TxHash
from ...protocol.constants import ALL_ONES
from ...protocol.messages import NewPooledTransactionHashes
from .base import Adversary, AttackConfig

if TYPE_CHECKING:
    from ...core.simulator import Simulator


@dataclass
class TargetedPoisoningConfig(AttackConfig):
    victim_id: ActorId | None = None
    num_attacker_connections: int = 4
    nonce_chain_length: int = 16
    injection_interval: float = 0.1
    sender_address: Address | None = None


class TargetedPoisoningAdversary(Adversary):
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
        attack_config: TargetedPoisoningConfig,
    ) -> None:
        super().__init__(actor_id, simulator, controlled_nodes, attack_config)
        self._poisoning_config = attack_config
        self._current_nonce = 0
        self._sender = attack_config.sender_address or Address(f"0xadversary_{actor_id}")

    @property
    def victim_id(self) -> ActorId | None:
        return self._poisoning_config.victim_id

    def execute(self) -> None:
        if self._poisoning_config.victim_id is None:
            return  # No victim configured

        self._attack_started = True
        # Start injection chain
        self._inject_next_tx()

    def _inject_next_tx(self) -> None:
        if self._attack_stopped:
            return
        if self._current_nonce >= self._poisoning_config.nonce_chain_length:
            return  # Chain complete

        tx_hash = self._create_poison_tx()

        # Announce ONLY to victim - not to rest of network
        # Use adversary's own ID as sender (adversary is registered with simulator)
        announcement = NewPooledTransactionHashes(
            sender=self.id,
            types=bytes([3]),  # Blob tx type
            sizes=[131072],
            hashes=[tx_hash],
            cell_mask=ALL_ONES,  # Claim to be provider
        )

        if self._poisoning_config.victim_id is not None:
            self.send(announcement, to=self._poisoning_config.victim_id)

        self._current_nonce += 1

        # Schedule next injection
        if self._current_nonce < self._poisoning_config.nonce_chain_length:
            self.schedule_timer(
                self._poisoning_config.injection_interval,
                TimerKind.INJECT_NEXT,
            )

    def _on_timer(self, timer: TimerPayload) -> None:
        match timer.kind:
            case TimerKind.INJECT_NEXT:
                self._inject_next_tx()

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
