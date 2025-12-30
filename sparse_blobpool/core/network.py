"""Network component for message delivery with latency modeling."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sparse_blobpool.config import Region
from sparse_blobpool.core.simulator import Event

if TYPE_CHECKING:
    from sparse_blobpool.core.actor import Message
    from sparse_blobpool.core.simulator import Simulator
    from sparse_blobpool.core.types import ActorId
    from sparse_blobpool.metrics.collector import MetricsCollector


@dataclass(frozen=True)
class LatencyParams:
    """Parameters for modeling network latency between regions."""

    base_ms: float  # Base one-way delay in milliseconds
    jitter_ratio: float  # Standard deviation as fraction of base


@dataclass
class CoDelState:
    """Per-link CoDel queue state for congestion modeling.

    This is a delay-only CoDel variant optimized for discrete event simulation.
    Unlike RFC 8289 CoDel which drops packets, this implementation adds latency
    proportional to congestion level. This design choice is intentional:

    1. **Delay-only suffices for blob propagation analysis**: We care about
       message arrival times, not packet loss rates. Adding delay captures
       the performance impact of congestion without complicating the protocol
       simulation with retransmission logic.

    2. **Virtual queue avoids packet buffering**: Rather than maintaining actual
       packet queues, we track a virtual byte counter that drains at the link's
       drain rate. This is sufficient because the simulator schedules discrete
       events—we only need to compute the delay at send time, not manage a
       real queue.

    3. **Per-link state models point-to-point congestion**: Each (sender, receiver)
       pair maintains independent state. This captures link-level congestion
       without the complexity of fair queuing across flows, which isn't needed
       when simulating a small number of peers with distinct message patterns.

    4. **Sqrt backoff preserves CoDel's key insight**: Under sustained congestion,
       delay increases with sqrt(drop_count), preventing both queue explosion
       and oscillation—the core benefit of CoDel's control law.
    """

    queue_bytes: float = 0.0
    queue_start_time: float = 0.0
    drop_count: int = 0
    last_drop_time: float = 0.0


@dataclass
class CoDelConfig:
    """Configuration for CoDel queue modeling.

    Defaults match RFC 8289 where applicable (target=5ms, interval=100ms).
    """

    target_delay: float = 0.005  # 5ms - sojourn time threshold for "good" queue
    interval: float = 0.100  # 100ms - sustained bad queue triggers backoff
    max_queue_bytes: int = 10 * 1024 * 1024  # 10 MB cap (tail drop)
    drain_rate: float = 100 * 1024 * 1024  # 100 MB/s virtual drain


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


class Network:
    """Network component that handles message delivery with realistic latency.

    Actors call network.deliver() to send messages. Delay is calculated based on:
    - Base latency between regions
    - Random jitter
    - Transmission time based on message size and bandwidth limits
    - CoDel queue delay during congestion
    """

    def __init__(
        self,
        simulator: Simulator,
        metrics: MetricsCollector,
        latency_matrix: dict[tuple[Region, Region], LatencyParams] | None = None,
        default_bandwidth: float = 100 * 1024 * 1024,  # 100 MB/s
        codel_config: CoDelConfig | None = None,
    ) -> None:
        self._simulator = simulator
        self._latency_matrix = latency_matrix or LATENCY_DEFAULTS
        self._default_bandwidth = default_bandwidth
        self._metrics = metrics
        self._codel_config = codel_config or CoDelConfig()

        # Actor metadata
        self._actor_regions: dict[ActorId, Region] = {}
        self._actor_bandwidth: dict[ActorId, float] = {}

        # Per-link CoDel state
        self._codel_state: dict[tuple[ActorId, ActorId], CoDelState] = {}

        # Statistics
        self._messages_delivered: int = 0
        self._total_bytes: int = 0

    def register_node(
        self,
        actor_id: ActorId,
        region: Region,
        bandwidth: float | None = None,
    ) -> None:
        self._actor_regions[actor_id] = region
        self._actor_bandwidth[actor_id] = bandwidth or self._default_bandwidth

    def deliver(self, msg: Message, from_: ActorId, to: ActorId) -> None:
        """Schedule message delivery with calculated delay."""
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

        # Record to metrics collector
        is_control = self._is_control_message(msg)
        self._metrics.record_bandwidth(from_, to, msg.size_bytes, is_control)

    def _is_control_message(self, msg: Message) -> bool:
        from sparse_blobpool.protocol.messages import Cells, GetCells, PooledTransactions

        # Data messages: actual cell/blob content
        # Control messages: announcements, requests, other protocol overhead
        return not isinstance(msg, Cells | PooledTransactions | GetCells)

    def _calculate_delay(self, from_: ActorId, to: ActorId, size_bytes: int) -> float:
        """Delay = base latency + jitter + transmission time + CoDel queue delay."""
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

        # CoDel queue delay
        codel = self._codel_delay(from_, to, size_bytes)

        return max(0, base + jitter + transmission + codel)

    def _get_codel_state(self, from_: ActorId, to: ActorId) -> CoDelState:
        link = (from_, to)
        if link not in self._codel_state:
            self._codel_state[link] = CoDelState()
        return self._codel_state[link]

    def _codel_delay(self, from_: ActorId, to: ActorId, size_bytes: int) -> float:
        """Compute additional delay from virtual queue congestion.

        Algorithm:
        1. Drain queue bytes based on elapsed time since last message
        2. Add new message bytes to queue (capped at max_queue_bytes)
        3. Compute sojourn time = queue_bytes / drain_rate
        4. If sojourn > target for sustained period, increment drop_count
        5. Return sojourn scaled by sqrt(drop_count) to model CoDel backoff
        """
        current_time = self._simulator.current_time
        config = self._codel_config
        state = self._get_codel_state(from_, to)

        # Drain queue based on elapsed time since last update
        if state.queue_bytes > 0 and state.queue_start_time >= 0:
            elapsed = current_time - state.queue_start_time
            if elapsed > 0:
                drained = elapsed * config.drain_rate
                state.queue_bytes = max(0, state.queue_bytes - drained)
                if state.queue_bytes == 0:
                    state.drop_count = 0  # Reset drop count when queue empties

        # Add new bytes to queue
        state.queue_bytes += size_bytes
        state.queue_start_time = current_time

        # Cap at max queue size (tail drop)
        if state.queue_bytes > config.max_queue_bytes:
            state.queue_bytes = float(config.max_queue_bytes)

        # Calculate sojourn time (time packet would spend in queue)
        sojourn = state.queue_bytes / config.drain_rate

        # If sojourn exceeds target for an interval, increase delay
        if sojourn > config.target_delay:
            time_since_drop = current_time - state.last_drop_time

            if time_since_drop > config.interval / math.sqrt(max(1, state.drop_count)):
                state.drop_count += 1
                state.last_drop_time = current_time

            # Delay scales with sqrt of consecutive delays (CoDel backoff)
            delay_factor = math.sqrt(state.drop_count) if state.drop_count > 0 else 0
            return sojourn * (1 + delay_factor * 0.5)

        # Queue under target - reset drop count gradually
        if state.drop_count > 0 and sojourn < config.target_delay * 0.5:
            state.drop_count = max(0, state.drop_count - 1)

        return sojourn

    @property
    def messages_delivered(self) -> int:
        return self._messages_delivered

    @property
    def total_bytes(self) -> int:
        return self._total_bytes
