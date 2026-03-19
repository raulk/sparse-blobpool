from __future__ import annotations

import random
from collections import deque
from dataclasses import dataclass, field
from hashlib import sha256
from typing import Any

from heuristic_sim.config import ALL_ONES, CELLS_PER_BLOB, columns_to_mask, mask_to_columns
from heuristic_sim.events import Event


@dataclass
class PeerState:
    peer_id: str
    behavior: str
    connected_at: float
    is_inbound: bool = True
    score: float = 0.0
    provider_announcements: int = 0
    sampler_announcements: int = 0
    announcements_made: int = 0
    cells_served: int = 0
    included_contributions: int = 0
    requests_received: int = 0
    requests_sent_to: int = 0
    bytes_in: int = 0
    bytes_out: int = 0
    _random_col_results: deque[bool] = field(default_factory=lambda: deque(maxlen=100))
    disconnected: bool = False
    disconnect_reason: str = ""
    disconnect_time: float = 0.0

    def record_random_column_result(self, success: bool) -> None:
        self._random_col_results.append(success)

    def random_column_failure_rate(self) -> float:
        if not self._random_col_results:
            return 0.0
        failures = sum(1 for r in self._random_col_results if not r)
        return failures / len(self._random_col_results)

    def provider_rate(self) -> float:
        total = self.provider_announcements + self.sampler_announcements
        if total == 0:
            return 0.0
        return self.provider_announcements / total


class PeerBehavior:
    def __init__(self, peer_id: str, rng: random.Random) -> None:
        self.peer_id = peer_id
        self.rng = rng
        self.label = "base"

    def generate_events(self, **kwargs: Any) -> list[Event]:
        raise NotImplementedError

    def respond_to_cell_request(
        self, columns: list[int], requester_custody: int,
    ) -> dict[str, list[int]]:
        raise NotImplementedError

    def _make_tx_hash(self, sender: str, nonce: int) -> str:
        return sha256(f"{sender}:{nonce}:{self.rng.random()}".encode()).hexdigest()[:16]


class HonestBehavior(PeerBehavior):
    def __init__(
        self,
        peer_id: str,
        rng: random.Random,
        *,
        provider_prob: float = 0.15,
        custody_columns: int = 8,
    ) -> None:
        super().__init__(peer_id, rng)
        self.label = "honest"
        self.provider_prob = provider_prob
        self.custody = rng.sample(range(CELLS_PER_BLOB), custody_columns)

    def generate_events(self, **kwargs: Any) -> list[Event]:
        t_start: float = kwargs["t_start"]
        t_end: float = kwargs["t_end"]
        tx_rate: float = kwargs.get("tx_rate", 1.0)
        blob_base_fee: float = kwargs.get("blob_base_fee", 1.0)

        events: list[Event] = []
        t = t_start + self.rng.expovariate(tx_rate)
        while t < t_end:
            sender = f"sender_{self.rng.randint(0, 999)}"
            nonce = self.rng.randint(0, 15)
            fee = blob_base_fee * self.rng.uniform(0.8, 3.0)
            is_provider = self.rng.random() < self.provider_prob
            cell_mask = ALL_ONES if is_provider else columns_to_mask(self.custody)
            events.append(Event(
                t=t,
                kind="announce",
                data={
                    "tx_hash": self._make_tx_hash(sender, nonce),
                    "sender": sender,
                    "nonce": nonce,
                    "fee": fee,
                    "cell_mask": cell_mask,
                    "is_provider": is_provider,
                    "exclusive": False,
                    "peer_id": self.peer_id,
                },
            ))
            n_cols = len(self.custody) + self.rng.randint(1, 4)
            requested_cols = self.rng.sample(range(CELLS_PER_BLOB), min(n_cols, CELLS_PER_BLOB))
            events.append(Event(
                t=t + self.rng.uniform(0.05, 0.2),
                kind="inbound_request",
                data={
                    "columns": requested_cols,
                    "peer_id": self.peer_id,
                },
            ))
            t += self.rng.expovariate(tx_rate)
        return events

    def respond_to_cell_request(
        self, columns: list[int], requester_custody: int,
    ) -> dict[str, list[int]]:
        return {"served": list(columns), "failed": []}


class SpammerBehavior(PeerBehavior):
    def __init__(
        self,
        peer_id: str,
        rng: random.Random,
        *,
        rate: float = 10.0,
        below_includability: bool = True,
    ) -> None:
        super().__init__(peer_id, rng)
        self.label = "spammer"
        self.rate = rate
        self.below_includability = below_includability

    def generate_events(self, **kwargs: Any) -> list[Event]:
        t_start: float = kwargs["t_start"]
        t_end: float = kwargs["t_end"]
        blob_base_fee: float = kwargs.get("blob_base_fee", 1.0)
        includability_discount: float = kwargs.get("includability_discount", 0.7)

        events: list[Event] = []
        t = t_start + self.rng.expovariate(self.rate)
        sender_counter = 0
        while t < t_end:
            sender = f"spam_{self.peer_id}_{sender_counter}"
            sender_counter += 1
            nonce = 0
            if self.below_includability:
                fee = blob_base_fee * includability_discount * self.rng.uniform(0.1, 0.99)
            else:
                fee = blob_base_fee * self.rng.uniform(0.8, 1.5)
            events.append(Event(
                t=t,
                kind="announce",
                data={
                    "tx_hash": self._make_tx_hash(sender, nonce),
                    "sender": sender,
                    "nonce": nonce,
                    "fee": fee,
                    "cell_mask": ALL_ONES,
                    "is_provider": True,
                    "exclusive": False,
                    "peer_id": self.peer_id,
                },
            ))
            t += self.rng.expovariate(self.rate)
        return events

    def respond_to_cell_request(
        self, columns: list[int], requester_custody: int,
    ) -> dict[str, list[int]]:
        return {"served": [], "failed": list(columns)}


class WithholderBehavior(PeerBehavior):
    """Claims provider but withholds columns outside requester's custody."""

    def __init__(
        self,
        peer_id: str,
        rng: random.Random,
        *,
        random_fail_rate: float = 1.0,
        provider_prob: float = 0.15,
        custody_columns: int = 8,
    ) -> None:
        super().__init__(peer_id, rng)
        self.label = "withholder"
        self.random_fail_rate = random_fail_rate
        self.provider_prob = provider_prob
        self.custody = rng.sample(range(CELLS_PER_BLOB), custody_columns)

    def generate_events(self, **kwargs: Any) -> list[Event]:
        t_start: float = kwargs["t_start"]
        t_end: float = kwargs["t_end"]
        tx_rate: float = kwargs.get("tx_rate", 1.0)
        blob_base_fee: float = kwargs.get("blob_base_fee", 1.0)

        events: list[Event] = []
        t = t_start + self.rng.expovariate(tx_rate)
        while t < t_end:
            sender = f"sender_{self.rng.randint(0, 999)}"
            nonce = self.rng.randint(0, 15)
            fee = blob_base_fee * self.rng.uniform(0.8, 3.0)
            events.append(Event(
                t=t,
                kind="announce",
                data={
                    "tx_hash": self._make_tx_hash(sender, nonce),
                    "sender": sender,
                    "nonce": nonce,
                    "fee": fee,
                    "cell_mask": ALL_ONES,
                    "is_provider": True,
                    "exclusive": False,
                    "peer_id": self.peer_id,
                },
            ))
            t += self.rng.expovariate(tx_rate)
        return events

    def respond_to_cell_request(
        self, columns: list[int], requester_custody: int,
    ) -> dict[str, list[int]]:
        custody_cols = mask_to_columns(requester_custody)
        custody_set = set(custody_cols)
        served: list[int] = []
        failed: list[int] = []
        for col in columns:
            if col in custody_set:
                served.append(col)
            elif self.rng.random() < self.random_fail_rate:
                failed.append(col)
            else:
                served.append(col)
        return {"served": served, "failed": failed}


class SpooferBehavior(PeerBehavior):
    """Claims provider but has no real data at all."""

    def __init__(
        self,
        peer_id: str,
        rng: random.Random,
        *,
        provider_prob: float = 0.15,
        custody_columns: int = 8,
    ) -> None:
        super().__init__(peer_id, rng)
        self.label = "spoofer"
        self.provider_prob = provider_prob
        self.custody = rng.sample(range(CELLS_PER_BLOB), custody_columns)

    def generate_events(self, **kwargs: Any) -> list[Event]:
        t_start: float = kwargs["t_start"]
        t_end: float = kwargs["t_end"]
        tx_rate: float = kwargs.get("tx_rate", 1.0)
        blob_base_fee: float = kwargs.get("blob_base_fee", 1.0)

        events: list[Event] = []
        t = t_start + self.rng.expovariate(tx_rate)
        while t < t_end:
            sender = f"sender_{self.rng.randint(0, 999)}"
            nonce = self.rng.randint(0, 15)
            fee = blob_base_fee * self.rng.uniform(0.8, 3.0)
            events.append(Event(
                t=t,
                kind="announce",
                data={
                    "tx_hash": self._make_tx_hash(sender, nonce),
                    "sender": sender,
                    "nonce": nonce,
                    "fee": fee,
                    "cell_mask": ALL_ONES,
                    "is_provider": True,
                    "exclusive": False,
                    "peer_id": self.peer_id,
                },
            ))
            t += self.rng.expovariate(tx_rate)
        return events

    def respond_to_cell_request(
        self, columns: list[int], requester_custody: int,
    ) -> dict[str, list[int]]:
        return {"served": [], "failed": list(columns)}


class FreeRiderBehavior(PeerBehavior):
    """Only serves custody columns, never claims provider."""

    def __init__(
        self,
        peer_id: str,
        rng: random.Random,
        *,
        custody_columns: int = 8,
    ) -> None:
        super().__init__(peer_id, rng)
        self.label = "free_rider"
        self.custody = rng.sample(range(CELLS_PER_BLOB), custody_columns)

    def generate_events(self, **kwargs: Any) -> list[Event]:
        t_start: float = kwargs["t_start"]
        t_end: float = kwargs["t_end"]
        tx_rate: float = kwargs.get("tx_rate", 1.0)
        blob_base_fee: float = kwargs.get("blob_base_fee", 1.0)

        events: list[Event] = []
        t = t_start + self.rng.expovariate(tx_rate)
        while t < t_end:
            sender = f"sender_{self.rng.randint(0, 999)}"
            nonce = self.rng.randint(0, 15)
            fee = blob_base_fee * self.rng.uniform(0.8, 3.0)
            events.append(Event(
                t=t,
                kind="announce",
                data={
                    "tx_hash": self._make_tx_hash(sender, nonce),
                    "sender": sender,
                    "nonce": nonce,
                    "fee": fee,
                    "cell_mask": columns_to_mask(self.custody),
                    "is_provider": False,
                    "exclusive": False,
                    "peer_id": self.peer_id,
                },
            ))
            t += self.rng.expovariate(tx_rate)
        return events

    def respond_to_cell_request(
        self, columns: list[int], requester_custody: int,
    ) -> dict[str, list[int]]:
        custody_set = set(self.custody)
        served = [c for c in columns if c in custody_set]
        failed = [c for c in columns if c not in custody_set]
        return {"served": served, "failed": failed}


class NonAnnouncerBehavior(PeerBehavior):
    """Never announces txs, only requests cells."""

    def __init__(self, peer_id: str, rng: random.Random) -> None:
        super().__init__(peer_id, rng)
        self.label = "non_announcer"

    def generate_events(self, **kwargs: Any) -> list[Event]:
        t_start: float = kwargs["t_start"]
        t_end: float = kwargs["t_end"]
        tx_rate: float = kwargs.get("tx_rate", 1.0)

        events: list[Event] = []
        t = t_start + self.rng.expovariate(tx_rate)
        while t < t_end:
            requested_cols = self.rng.sample(
                range(CELLS_PER_BLOB), self.rng.randint(1, 8),
            )
            events.append(Event(
                t=t,
                kind="inbound_request",
                data={
                    "columns": requested_cols,
                    "peer_id": self.peer_id,
                },
            ))
            t += self.rng.expovariate(tx_rate)
        return events

    def respond_to_cell_request(
        self, columns: list[int], requester_custody: int,
    ) -> dict[str, list[int]]:
        return {"served": [], "failed": list(columns)}


class SelectiveSignalerBehavior(PeerBehavior):
    """Floods exclusive txs to monopolize victim's view of senders."""

    def __init__(
        self,
        peer_id: str,
        rng: random.Random,
        *,
        n_senders: int = 10,
        txs_per_sender: int = 16,
    ) -> None:
        super().__init__(peer_id, rng)
        self.label = "selective_signaler"
        self.n_senders = n_senders
        self.txs_per_sender = txs_per_sender

    def generate_events(self, **kwargs: Any) -> list[Event]:
        t_start: float = kwargs["t_start"]
        t_end: float = kwargs["t_end"]

        total_txs = self.n_senders * self.txs_per_sender
        duration = t_end - t_start
        interval = duration if total_txs <= 1 else duration / total_txs

        events: list[Event] = []
        t = t_start
        for s in range(self.n_senders):
            sender = f"target_sender_{s}"
            for nonce in range(self.txs_per_sender):
                events.append(Event(
                    t=t,
                    kind="announce",
                    data={
                        "tx_hash": self._make_tx_hash(sender, nonce),
                        "sender": sender,
                        "nonce": nonce,
                        "fee": 2.0,
                        "cell_mask": ALL_ONES,
                        "is_provider": True,
                        "exclusive": True,
                        "peer_id": self.peer_id,
                    },
                ))
                t += interval
        return events

    def respond_to_cell_request(
        self, columns: list[int], requester_custody: int,
    ) -> dict[str, list[int]]:
        return {"served": list(columns), "failed": []}


BEHAVIOR_CLASSES: dict[str, type[PeerBehavior]] = {
    "spammer": SpammerBehavior,
    "withholder": WithholderBehavior,
    "spoofer": SpooferBehavior,
    "free_rider": FreeRiderBehavior,
    "non_announcer": NonAnnouncerBehavior,
    "selective_signaler": SelectiveSignalerBehavior,
}
