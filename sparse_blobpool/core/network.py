"""Network actor for message delivery with latency modeling."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..config import Region
from .actor import Actor, EventPayload, Message, SendRequest, TimerPayload
from .simulator import Event
from .types import NETWORK_ACTOR_ID, ActorId

if TYPE_CHECKING:
    from ..metrics.collector import MetricsCollector
    from .simulator import Simulator


@dataclass(frozen=True)
class LatencyParams:
    """Parameters for modeling network latency between regions."""

    base_ms: float  # Base one-way delay in milliseconds
    jitter_ratio: float  # Standard deviation as fraction of base


# Default latency matrix (one-way delay)
LATENCY_DEFAULTS: dict[tuple[Region, Region], LatencyParams] = {
    # Same region
    (Region.NA, Region.NA): LatencyParams(20, 0.1),
    (Region.EU, Region.EU): LatencyParams(15, 0.1),
    (Region.AS, Region.AS): LatencyParams(25, 0.1),
    # Cross-region (symmetric)
    (Region.NA, Region.EU): LatencyParams(45, 0.15),
    (Region.EU, Region.NA): LatencyParams(45, 0.15),
    (Region.NA, Region.AS): LatencyParams(90, 0.2),
    (Region.AS, Region.NA): LatencyParams(90, 0.2),
    (Region.EU, Region.AS): LatencyParams(75, 0.15),
    (Region.AS, Region.EU): LatencyParams(75, 0.15),
}


class Network(Actor):
    """Network actor that handles message delivery with realistic latency.

    The Network is a special actor that receives SendRequest events and
    schedules delayed Message delivery to the target actor. Delay is
    calculated based on:
    - Base latency between regions
    - Random jitter
    - Transmission time based on message size and bandwidth limits
    """

    def __init__(
        self,
        simulator: Simulator,
        latency_matrix: dict[tuple[Region, Region], LatencyParams] | None = None,
        default_bandwidth: float = 100 * 1024 * 1024,  # 100 MB/s
        metrics: MetricsCollector | None = None,
    ) -> None:
        super().__init__(NETWORK_ACTOR_ID, simulator)
        self._latency_matrix = latency_matrix or LATENCY_DEFAULTS
        self._default_bandwidth = default_bandwidth
        self._metrics = metrics

        # Actor metadata
        self._actor_regions: dict[ActorId, Region] = {}
        self._actor_bandwidth: dict[ActorId, float] = {}

        # Statistics
        self._messages_delivered: int = 0
        self._total_bytes: int = 0

    def register_node(
        self,
        actor_id: ActorId,
        region: Region,
        bandwidth: float | None = None,
    ) -> None:
        """Register a node's network properties."""
        self._actor_regions[actor_id] = region
        self._actor_bandwidth[actor_id] = bandwidth or self._default_bandwidth

    def on_event(self, payload: EventPayload) -> None:
        """Handle SendRequest events by scheduling delayed delivery."""
        match payload:
            case SendRequest(msg=msg, from_=from_, to=to):
                self._deliver(msg, from_, to)
            case TimerPayload():
                pass  # No timer handling needed for basic network
            case Message():
                pass  # Network doesn't receive regular messages

    def _deliver(self, msg: Message, from_: ActorId, to: ActorId) -> None:
        """Calculate delay and schedule message delivery."""
        delay = self._calculate_delay(from_, to, msg.size_bytes)

        self._simulator.schedule(
            Event(
                timestamp=self._simulator.current_time + delay,
                priority=0,
                target_id=to,
                payload=msg,
            )
        )

        self._messages_delivered += 1
        self._total_bytes += msg.size_bytes

        # Record to metrics collector if available
        if self._metrics is not None:
            is_control = self._is_control_message(msg)
            self._metrics.record_bandwidth(from_, to, msg.size_bytes, is_control)

    def _is_control_message(self, msg: Message) -> bool:
        """Determine if a message is control (announcements) vs data (cells)."""
        # Import here to avoid circular dependencies
        from ..protocol.messages import Cells, GetCells, PooledTransactions

        # Data messages: actual cell/blob content
        # Control messages: announcements, requests, other protocol overhead
        return not isinstance(msg, Cells | PooledTransactions | GetCells)

    def _calculate_delay(self, from_: ActorId, to: ActorId, size_bytes: int) -> float:
        """Calculate total delay for a message.

        Components:
        - Base latency between regions
        - Gaussian jitter
        - Transmission time (size / bandwidth)
        """
        # Get regions (default to NA if not registered)
        from_region = self._actor_regions.get(from_, Region.NA)
        to_region = self._actor_regions.get(to, Region.NA)

        # Get latency parameters
        params = self._latency_matrix.get(
            (from_region, to_region),
            LatencyParams(50, 0.15),  # Default fallback
        )

        # Base delay (convert ms to seconds)
        base = params.base_ms / 1000.0

        # Jitter (Gaussian, clamped to non-negative)
        jitter = self._simulator.rng.gauss(0, base * params.jitter_ratio)

        # Transmission time
        from_bw = self._actor_bandwidth.get(from_, self._default_bandwidth)
        to_bw = self._actor_bandwidth.get(to, self._default_bandwidth)
        transmission = size_bytes / min(from_bw, to_bw)

        return max(0, base + jitter + transmission)

    @property
    def messages_delivered(self) -> int:
        return self._messages_delivered

    @property
    def total_bytes(self) -> int:
        return self._total_bytes
