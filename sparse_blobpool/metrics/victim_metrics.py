"""Metrics extensions for tracking victim-specific impacts during attacks."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from statistics import mean, median
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sparse_blobpool.actors.adversaries.victim_selection import VictimProfile
    from sparse_blobpool.core.simulator import Simulator
    from sparse_blobpool.core.types import ActorId, TxHash
    from sparse_blobpool.metrics.collector import MetricsCollector


@dataclass
class VictimMetrics:
    """Per-victim impact metrics during attack scenarios."""

    victim_id: ActorId

    # Bandwidth impact
    bytes_received_normal: int = 0  # Before attack
    bytes_received_attack: int = 0  # During attack
    bytes_sent_normal: int = 0
    bytes_sent_attack: int = 0
    bandwidth_amplification: float = 0.0  # Attack/normal ratio

    # Blobpool pollution
    spam_txs_accepted: int = 0
    spam_txs_rejected: int = 0
    blobpool_pollution_rate: float = 0.0  # Spam/total ratio
    blobpool_size_normal: int = 0
    blobpool_size_attack: int = 0

    # Transaction processing
    valid_txs_dropped: int = 0  # Valid txs dropped due to attack
    processing_latency_normal: float = 0.0
    processing_latency_attack: float = 0.0

    # Network connectivity
    peers_lost: int = 0  # Peers disconnected during attack
    connectivity_degradation: float = 0.0  # % of peers lost

    # Resource utilization
    cpu_usage_normal: float = 0.0  # Simulated CPU usage
    cpu_usage_attack: float = 0.0
    memory_usage_normal: float = 0.0  # Simulated memory usage
    memory_usage_attack: float = 0.0

    # DA-specific impacts (for withholding attacks)
    da_checks_failed: int = 0
    reconstruction_failures: int = 0
    false_availability_signals: int = 0

    # Poisoning-specific impacts
    poisoned_txs_received: int = 0
    poisoned_propagations: int = 0


@dataclass
class AggregatedVictimMetrics:
    """Aggregated metrics across all victims."""

    total_victims: int
    victim_profiles: list[VictimProfile]

    # Aggregate bandwidth impact
    avg_bandwidth_amplification: float
    max_bandwidth_amplification: float
    total_excess_bandwidth: int  # Total extra bytes due to attack

    # Aggregate blobpool impact
    avg_pollution_rate: float
    max_pollution_rate: float
    total_spam_accepted: int

    # Aggregate processing impact
    avg_latency_increase: float
    max_latency_increase: float
    total_valid_txs_dropped: int

    # Network health
    avg_connectivity_loss: float
    total_peers_lost: int
    isolated_victims: int  # Victims that lost >50% peers

    # Resource impact
    avg_cpu_increase: float
    avg_memory_increase: float

    # Attack effectiveness
    victim_coverage: float  # % of intended victims actually impacted
    collateral_damage: float  # Impact on non-victim nodes
    attack_amplification: float  # Total impact / attacker resources

    # Per-victim details
    victim_metrics: dict[ActorId, VictimMetrics] = field(default_factory=dict)


class VictimMetricsCollector:
    """Collects and analyzes victim-specific metrics during attacks."""

    def __init__(self, metrics_collector: MetricsCollector) -> None:
        self.metrics_collector = metrics_collector
        self.victim_metrics: dict[ActorId, VictimMetrics] = {}
        self.victim_profile: VictimProfile | None = None
        self.attack_start_time: float | None = None
        self.non_victim_impacts: dict[ActorId, dict[str, float]] = defaultdict(dict)

    def set_victim_profile(self, profile: VictimProfile) -> None:
        """Set the victim profile for this attack scenario."""
        self.victim_profile = profile
        # Initialize metrics for each victim
        for victim_id in profile.victims:
            self.victim_metrics[victim_id] = VictimMetrics(victim_id=victim_id)

    def mark_attack_start(self, simulator: Simulator) -> None:
        """Mark the start of an attack for baseline comparison."""
        self.attack_start_time = simulator.current_time

        # Capture baseline metrics for victims
        for victim_id, metrics in self.victim_metrics.items():
            if victim_id in self.metrics_collector.bytes_sent:
                metrics.bytes_sent_normal = self.metrics_collector.bytes_sent[victim_id]
            if victim_id in self.metrics_collector.bytes_received:
                metrics.bytes_received_normal = self.metrics_collector.bytes_received[victim_id]

    def record_spam_acceptance(self, node_id: ActorId, tx_hash: TxHash, accepted: bool) -> None:
        """Record spam transaction acceptance/rejection at a victim node."""
        if node_id in self.victim_metrics:
            if accepted:
                self.victim_metrics[node_id].spam_txs_accepted += 1
            else:
                self.victim_metrics[node_id].spam_txs_rejected += 1
        elif node_id not in self.victim_profile.victims if self.victim_profile else []:
            # Track collateral damage on non-victims
            if "spam_accepted" not in self.non_victim_impacts[node_id]:
                self.non_victim_impacts[node_id]["spam_accepted"] = 0
            if accepted:
                self.non_victim_impacts[node_id]["spam_accepted"] += 1

    def record_valid_tx_dropped(self, node_id: ActorId, tx_hash: TxHash) -> None:
        """Record when a valid transaction is dropped due to attack impact."""
        if node_id in self.victim_metrics:
            self.victim_metrics[node_id].valid_txs_dropped += 1

    def record_da_failure(self, node_id: ActorId, failure_type: str) -> None:
        """Record DA-related failures at victim nodes."""
        if node_id in self.victim_metrics:
            metrics = self.victim_metrics[node_id]
            match failure_type:
                case "da_check":
                    metrics.da_checks_failed += 1
                case "reconstruction":
                    metrics.reconstruction_failures += 1
                case "false_availability":
                    metrics.false_availability_signals += 1

    def record_poisoning(self, node_id: ActorId, tx_hash: TxHash) -> None:
        """Record poisoned transaction reception at victim nodes."""
        if node_id in self.victim_metrics:
            self.victim_metrics[node_id].poisoned_txs_received += 1

    def record_connectivity_loss(self, node_id: ActorId, peer_id: ActorId) -> None:
        """Record when a victim loses connectivity to a peer."""
        if node_id in self.victim_metrics:
            self.victim_metrics[node_id].peers_lost += 1

    def finalize(self, simulator: Simulator) -> AggregatedVictimMetrics:
        """Finalize and aggregate victim metrics."""
        if not self.victim_profile or not self.victim_metrics:
            return AggregatedVictimMetrics(
                total_victims=0,
                victim_profiles=[],
                avg_bandwidth_amplification=0.0,
                max_bandwidth_amplification=0.0,
                total_excess_bandwidth=0,
                avg_pollution_rate=0.0,
                max_pollution_rate=0.0,
                total_spam_accepted=0,
                avg_latency_increase=0.0,
                max_latency_increase=0.0,
                total_valid_txs_dropped=0,
                avg_connectivity_loss=0.0,
                total_peers_lost=0,
                isolated_victims=0,
                avg_cpu_increase=0.0,
                avg_memory_increase=0.0,
                victim_coverage=0.0,
                collateral_damage=0.0,
                attack_amplification=0.0,
            )

        # Calculate per-victim metrics
        for victim_id, metrics in self.victim_metrics.items():
            # Bandwidth impact
            metrics.bytes_received_attack = self.metrics_collector.bytes_received.get(
                victim_id, 0
            ) - metrics.bytes_received_normal
            metrics.bytes_sent_attack = self.metrics_collector.bytes_sent.get(
                victim_id, 0
            ) - metrics.bytes_sent_normal

            if metrics.bytes_received_normal > 0:
                metrics.bandwidth_amplification = (
                    metrics.bytes_received_attack / metrics.bytes_received_normal
                )

            # Blobpool pollution
            total_txs = metrics.spam_txs_accepted + metrics.spam_txs_rejected
            if total_txs > 0:
                metrics.blobpool_pollution_rate = metrics.spam_txs_accepted / total_txs

            # Connectivity
            from sparse_blobpool.actors.honest import Node
            if victim_id in simulator.actors:
                node = simulator.actors[victim_id]
                if isinstance(node, Node):
                    total_peers = len(node.peers)
                    if total_peers > 0:
                        metrics.connectivity_degradation = metrics.peers_lost / total_peers

        # Aggregate metrics
        bandwidth_amplifications = [
            m.bandwidth_amplification for m in self.victim_metrics.values()
        ]
        pollution_rates = [m.blobpool_pollution_rate for m in self.victim_metrics.values()]
        connectivity_losses = [m.connectivity_degradation for m in self.victim_metrics.values()]

        # Calculate collateral damage
        total_non_victim_impact = sum(
            impacts.get("spam_accepted", 0) for impacts in self.non_victim_impacts.values()
        )
        total_victim_impact = sum(m.spam_txs_accepted for m in self.victim_metrics.values())
        collateral_ratio = (
            total_non_victim_impact / (total_victim_impact + total_non_victim_impact)
            if total_victim_impact + total_non_victim_impact > 0
            else 0.0
        )

        return AggregatedVictimMetrics(
            total_victims=len(self.victim_metrics),
            victim_profiles=[self.victim_profile],
            avg_bandwidth_amplification=mean(bandwidth_amplifications) if bandwidth_amplifications else 0.0,
            max_bandwidth_amplification=max(bandwidth_amplifications) if bandwidth_amplifications else 0.0,
            total_excess_bandwidth=sum(m.bytes_received_attack for m in self.victim_metrics.values()),
            avg_pollution_rate=mean(pollution_rates) if pollution_rates else 0.0,
            max_pollution_rate=max(pollution_rates) if pollution_rates else 0.0,
            total_spam_accepted=sum(m.spam_txs_accepted for m in self.victim_metrics.values()),
            avg_latency_increase=0.0,  # Would need timing data
            max_latency_increase=0.0,
            total_valid_txs_dropped=sum(m.valid_txs_dropped for m in self.victim_metrics.values()),
            avg_connectivity_loss=mean(connectivity_losses) if connectivity_losses else 0.0,
            total_peers_lost=sum(m.peers_lost for m in self.victim_metrics.values()),
            isolated_victims=sum(1 for m in self.victim_metrics.values() if m.connectivity_degradation > 0.5),
            avg_cpu_increase=0.0,  # Would need resource monitoring
            avg_memory_increase=0.0,
            victim_coverage=len(self.victim_metrics) / len(self.victim_profile.victims),
            collateral_damage=collateral_ratio,
            attack_amplification=1.0,  # Would need attacker resource tracking
            victim_metrics=self.victim_metrics,
        )


def extend_metrics_with_victims(
    results: object,
    victim_metrics: AggregatedVictimMetrics,
) -> dict[str, object]:
    """Extend simulation results with victim-specific metrics.

    Args:
        results: Base simulation results.
        victim_metrics: Aggregated victim metrics.

    Returns:
        Extended metrics dictionary.
    """
    base_metrics = results.to_dict() if hasattr(results, "to_dict") else {}

    victim_data = {
        "victim_count": victim_metrics.total_victims,
        "victim_coverage": victim_metrics.victim_coverage,
        "avg_bandwidth_amplification": victim_metrics.avg_bandwidth_amplification,
        "max_bandwidth_amplification": victim_metrics.max_bandwidth_amplification,
        "total_excess_bandwidth": victim_metrics.total_excess_bandwidth,
        "avg_pollution_rate": victim_metrics.avg_pollution_rate,
        "max_pollution_rate": victim_metrics.max_pollution_rate,
        "total_spam_accepted": victim_metrics.total_spam_accepted,
        "total_valid_txs_dropped": victim_metrics.total_valid_txs_dropped,
        "avg_connectivity_loss": victim_metrics.avg_connectivity_loss,
        "isolated_victims": victim_metrics.isolated_victims,
        "collateral_damage": victim_metrics.collateral_damage,
        "per_victim": {
            vid: {
                "bandwidth_amplification": m.bandwidth_amplification,
                "pollution_rate": m.blobpool_pollution_rate,
                "spam_accepted": m.spam_txs_accepted,
                "valid_dropped": m.valid_txs_dropped,
                "peers_lost": m.peers_lost,
            }
            for vid, m in victim_metrics.victim_metrics.items()
        },
    }

    return {**base_metrics, "victim_metrics": victim_data}