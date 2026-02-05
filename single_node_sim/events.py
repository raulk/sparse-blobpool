from dataclasses import dataclass
from typing import Any

from sparse_blobpool.protocol.constants import ALL_ONES


@dataclass(frozen=True)
class TxAnnouncement:
    timestamp: float
    tx_hash: str
    sender: str
    nonce: int
    gas_fee_cap: int
    gas_tip_cap: int
    tx_size: int
    blob_count: int
    cell_mask: int = ALL_ONES


@dataclass(frozen=True)
class CellsReceived:
    timestamp: float
    tx_hash: str
    cell_mask: int


@dataclass(frozen=True)
class BlockIncluded:
    timestamp: float
    tx_hashes: list[str]


type TraceEvent = TxAnnouncement | CellsReceived | BlockIncluded


def normalize_event(event: TraceEvent | dict[str, Any]) -> TraceEvent:
    if isinstance(event, (TxAnnouncement, CellsReceived, BlockIncluded)):
        return event

    if "tx_hashes" in event:
        return BlockIncluded(
            timestamp=event["timestamp"],
            tx_hashes=event["tx_hashes"],
        )

    if "sender" in event:
        return TxAnnouncement(
            timestamp=event["timestamp"],
            tx_hash=event["tx_hash"],
            sender=event["sender"],
            nonce=event["nonce"],
            gas_fee_cap=event["gas_fee_cap"],
            gas_tip_cap=event["gas_tip_cap"],
            tx_size=event["tx_size"],
            blob_count=event["blob_count"],
            cell_mask=event.get("cell_mask", ALL_ONES),
        )

    return CellsReceived(
        timestamp=event["timestamp"],
        tx_hash=event["tx_hash"],
        cell_mask=event["cell_mask"],
    )
