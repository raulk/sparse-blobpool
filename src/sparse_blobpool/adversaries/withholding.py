"""WithholdingAdversary for T2.1 selective withholding attack."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ..protocol.messages import Cells, GetCells
from .base import Adversary, AttackConfig

if TYPE_CHECKING:
    from ..core.actor import Message
    from ..core.simulator import Simulator
    from ..core.types import ActorId


@dataclass
class WithholdingConfig(AttackConfig):
    """Configuration for selective withholding attack.

    Attributes:
        columns_to_serve: Set of column indices the adversary will serve.
        delay_other_columns: If not None, delay non-served columns by this much.
            If None, drop requests for non-served columns entirely.
    """

    columns_to_serve: set[int] = field(default_factory=lambda: set(range(64)))
    delay_other_columns: float | None = None


class WithholdingAdversary(Adversary):
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
        attack_config: WithholdingConfig,
    ) -> None:
        super().__init__(actor_id, simulator, controlled_nodes, attack_config)
        self._withholding_config = attack_config
        self._allowed_mask = self._compute_allowed_mask()

    def _compute_allowed_mask(self) -> int:
        """Compute bitmask for columns the adversary will serve."""
        mask = 0
        for col in self._withholding_config.columns_to_serve:
            mask |= 1 << col
        return mask

    def execute(self) -> None:
        """Start the withholding attack.

        The attack is passive - it intercepts requests to controlled nodes.
        """
        self._attack_started = True

    def _on_message(self, msg: Message) -> None:
        match msg:
            case GetCells() as req:
                self._handle_get_cells(req)

    def _handle_get_cells(self, req: GetCells) -> None:
        """Handle GetCells request by filtering to allowed columns.

        If request is to a controlled node, we intercept and serve only
        allowed columns.
        """
        # Check if this request is to one of our controlled nodes
        # In a real implementation, we'd need routing info - for now
        # we apply filtering to any GetCells we receive

        allowed = req.cell_mask & self._allowed_mask
        if allowed != req.cell_mask:
            # Requesting columns we don't serve
            if self._withholding_config.delay_other_columns is not None:
                # Delay response for non-served columns
                # In a real implementation, we'd schedule a delayed partial response
                pass
            else:
                # Drop the request entirely (timeout on requester side)
                pass

        # For allowed columns, we respond normally
        # Note: In a full implementation, we'd construct proper Cell responses
        # For simulation purposes, we just track that we served partial data
        if allowed:
            # Construct partial response with only allowed cells
            response = Cells(
                sender=self.id,
                tx_hashes=req.tx_hashes,
                cells=[[] for _ in req.tx_hashes],  # Simplified - no actual cell data
                cell_mask=allowed,
            )
            self.send(response, to=req.sender)

    def get_withheld_columns(self, request_mask: int) -> set[int]:
        """Return the set of columns that would be withheld from a request."""
        withheld = request_mask & ~self._allowed_mask
        columns = set()
        for i in range(128):
            if withheld & (1 << i):
                columns.add(i)
        return columns
