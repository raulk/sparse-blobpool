"""Local simulation events (not transmitted over network)."""

from dataclasses import dataclass

from sparse_blobpool.core.actor import Message
from sparse_blobpool.core.types import Address, TxHash


@dataclass
class BroadcastTransaction(Message):
    """Inject a new transaction into a node's pool and announce it.

    This is not a network message but a local event used to inject transactions
    into the simulation. The receiving node will add the tx to its pool and
    announce to all peers as a provider.
    """

    tx_hash: TxHash
    tx_sender: Address
    nonce: int
    gas_fee_cap: int
    gas_tip_cap: int
    blob_gas_price: int
    tx_size: int
    blob_count: int
    cell_mask: int  # Cells the origin has (ALL_ONES for full blob)

    @property
    def size_bytes(self) -> int:
        return 0  # Local event, not transmitted over network


@dataclass
class ProduceBlock(Message):
    """Request a node to produce a block for a given slot.

    Sent by BlockProducer to the selected proposer node. The node will
    select transactions from its pool, create the block, and broadcast
    the BlockAnnouncement to all peers.
    """

    slot: int

    @property
    def size_bytes(self) -> int:
        return 0  # Local event, not transmitted over network
