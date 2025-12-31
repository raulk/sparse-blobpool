"""Commands for local simulation events (not transmitted over network).

Commands are local events that actors send to themselves or receive from
the simulation infrastructure. Unlike Messages, Commands are never transmitted
over the network.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sparse_blobpool.core.events import Command

if TYPE_CHECKING:
    from sparse_blobpool.core.types import Address, RequestId, TxHash

# Re-export Command for convenience
__all__ = [
    "BroadcastTransaction",
    "Command",
    "ProduceBlock",
    "ProviderObservationTimeout",
    "RequestTimeout",
    "SlotTick",
    "TxCleanup",
]


@dataclass
class BroadcastTransaction(Command):
    """Inject a new transaction into a node's pool and announce it."""

    tx_hash: TxHash
    tx_sender: Address
    nonce: int
    gas_fee_cap: int
    gas_tip_cap: int
    blob_gas_price: int
    tx_size: int
    blob_count: int
    cell_mask: int  # Cells the origin has (ALL_ONES for full blob)


@dataclass
class ProduceBlock(Command):
    """Request a node to produce a block for a given slot."""

    slot: int


@dataclass
class SlotTick(Command):
    """Periodic slot boundary tick for block production."""


@dataclass
class RequestTimeout(Command):
    """Timeout for a pending request (tx body or cells)."""

    request_id: RequestId


@dataclass
class ProviderObservationTimeout(Command):
    """Timeout waiting for provider announcements before fetching."""

    tx_hash: TxHash


@dataclass
class TxCleanup(Command):
    """Delayed cleanup of a transaction after block inclusion."""

    tx_hash: TxHash
