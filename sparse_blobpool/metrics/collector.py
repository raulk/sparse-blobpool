"""Metrics collection for simulation analysis."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from statistics import median
from typing import TYPE_CHECKING

from sparse_blobpool.metrics.results import (
    BandwidthSnapshot,
    PropagationSnapshot,
    SimulationResults,
)
from sparse_blobpool.protocol.constants import ALL_ONES

if TYPE_CHECKING:
    from sparse_blobpool.actors.honest import Role
    from sparse_blobpool.core.latency import Country
    from sparse_blobpool.core.simulator import Simulator
    from sparse_blobpool.core.types import ActorId, TxHash


# Estimated size of a full blob transaction for bandwidth reduction calculations
# 128 cells * 2048 bytes/cell + overhead
FULL_BLOB_SIZE = 128 * 2048 + 1024


@dataclass
class TxMetrics:
    """Per-transaction metrics."""

    first_seen_time: float
    first_seen_node: ActorId
    propagation_complete_time: float | None = None  # When 99% of nodes saw it
    provider_count: int = 0
    sampler_count: int = 0
    nodes_seen: set[ActorId] = field(default_factory=set)
    cell_masks: dict[ActorId, int] = field(default_factory=dict)  # Node -> cell_mask
    included_at_slot: int | None = None


@dataclass
class MetricsCollector:
    """Collects and aggregates simulation metrics.

    Tracks bandwidth usage, transaction propagation, and protocol behavior
    for analysis after simulation completes.
    """

    simulator: Simulator
    sample_interval: float = 1.0
    node_count: int = 0  # Set during initialization
    expected_provider_probability: float = 0.15  # From config

    # Bandwidth tracking (cumulative)
    bytes_sent: dict[ActorId, int] = field(default_factory=lambda: defaultdict(int))
    bytes_received: dict[ActorId, int] = field(default_factory=lambda: defaultdict(int))
    bytes_sent_control: dict[ActorId, int] = field(default_factory=lambda: defaultdict(int))
    bytes_sent_data: dict[ActorId, int] = field(default_factory=lambda: defaultdict(int))

    # Country tracking
    node_countries: dict[ActorId, Country] = field(default_factory=dict)

    # Custody mask tracking (for local availability calculation)
    node_custody_masks: dict[ActorId, int] = field(default_factory=dict)

    # Timeseries
    bandwidth_timeseries: list[BandwidthSnapshot] = field(default_factory=list)
    propagation_timeseries: list[PropagationSnapshot] = field(default_factory=list)

    # Per-transaction tracking
    tx_metrics: dict[TxHash, TxMetrics] = field(default_factory=dict)

    # Attack tracking
    spam_accepted: int = 0
    spam_rejected: int = 0
    poisoned_txs: dict[ActorId, int] = field(default_factory=lambda: defaultdict(int))
    withholding_detected: int = 0

    # Internal state
    _last_snapshot_time: float = 0.0
    _total_bytes: int = 0
    _control_bytes: int = 0
    _data_bytes: int = 0

    def register_node(self, node_id: ActorId, country: Country, custody_mask: int) -> None:
        self.node_countries[node_id] = country
        self.node_custody_masks[node_id] = custody_mask
        self.node_count += 1

    def record_bandwidth(
        self,
        from_: ActorId,
        to: ActorId,
        size: int,
        is_control: bool = False,
    ) -> None:
        self.bytes_sent[from_] += size
        self.bytes_received[to] += size
        self._total_bytes += size

        if is_control:
            self.bytes_sent_control[from_] += size
            self._control_bytes += size
        else:
            self.bytes_sent_data[from_] += size
            self._data_bytes += size

    def record_tx_seen(
        self,
        node_id: ActorId,
        tx_hash: TxHash,
        role: Role,
        cell_mask: int,
    ) -> None:
        current_time = self.simulator.current_time

        if tx_hash not in self.tx_metrics:
            self.tx_metrics[tx_hash] = TxMetrics(
                first_seen_time=current_time,
                first_seen_node=node_id,
            )

        metrics = self.tx_metrics[tx_hash]
        metrics.nodes_seen.add(node_id)
        metrics.cell_masks[node_id] = cell_mask

        # Track role distribution
        if cell_mask == ALL_ONES:
            metrics.provider_count += 1
        else:
            metrics.sampler_count += 1

        # Check if propagation is complete (99% of nodes)
        if (
            metrics.propagation_complete_time is None
            and len(metrics.nodes_seen) >= self.node_count * 0.99
        ):
            metrics.propagation_complete_time = current_time

    def record_inclusion(self, tx_hash: TxHash, slot: int) -> None:
        if tx_hash in self.tx_metrics:
            self.tx_metrics[tx_hash].included_at_slot = slot

    def record_spam(self, tx_hash: TxHash, accepted: bool) -> None:
        if accepted:
            self.spam_accepted += 1
        else:
            self.spam_rejected += 1

    def record_poisoning(self, victim_id: ActorId, tx_hash: TxHash) -> None:
        self.poisoned_txs[victim_id] += 1

    def record_withholding_detected(self) -> None:
        self.withholding_detected += 1

    def snapshot(self) -> None:
        """Called periodically to build bandwidth/propagation timeseries."""
        current_time = self.simulator.current_time

        # Skip if we recently took a snapshot
        if current_time - self._last_snapshot_time < self.sample_interval:
            return

        self._last_snapshot_time = current_time

        # Bandwidth snapshot
        per_country: dict[Country, int] = defaultdict(int)
        for node_id, bytes_sent in self.bytes_sent.items():
            country = self.node_countries.get(node_id)
            if country:
                per_country[country] += bytes_sent

        self.bandwidth_timeseries.append(
            BandwidthSnapshot(
                timestamp=current_time,
                total_bytes=self._total_bytes,
                control_bytes=self._control_bytes,
                data_bytes=self._data_bytes,
                per_country=dict(per_country),
            )
        )

        # Propagation snapshots for active transactions
        for tx_hash, metrics in self.tx_metrics.items():
            if metrics.propagation_complete_time is None:
                # Still propagating - record snapshot
                full_count = sum(1 for mask in metrics.cell_masks.values() if mask == ALL_ONES)
                sample_count = len(metrics.nodes_seen) - full_count

                # Check if reconstruction is possible (64+ distinct columns)
                all_columns = 0
                for mask in metrics.cell_masks.values():
                    all_columns |= mask
                distinct_columns = bin(all_columns).count("1")

                self.propagation_timeseries.append(
                    PropagationSnapshot(
                        timestamp=current_time,
                        tx_hash=tx_hash,
                        nodes_seen=len(metrics.nodes_seen),
                        nodes_with_full=full_count,
                        nodes_with_sample=sample_count,
                        reconstruction_possible=distinct_columns >= 64,
                    )
                )

    def finalize(self) -> SimulationResults:
        # Take final snapshot
        self.snapshot()

        # Calculate propagation times
        propagation_times = []
        reconstruction_successes = 0
        total_txs = len(self.tx_metrics)

        for metrics in self.tx_metrics.values():
            if metrics.propagation_complete_time is not None:
                prop_time = metrics.propagation_complete_time - metrics.first_seen_time
                propagation_times.append(prop_time)

            # Check reconstruction possibility
            all_columns = 0
            for mask in metrics.cell_masks.values():
                all_columns |= mask
            if bin(all_columns).count("1") >= 64:
                reconstruction_successes += 1

        # Compute derived metrics
        total_providers = sum(m.provider_count for m in self.tx_metrics.values())
        total_roles = sum(m.provider_count + m.sampler_count for m in self.tx_metrics.values())

        # Bandwidth per blob (average)
        bandwidth_per_blob = self._total_bytes / total_txs if total_txs > 0 else 0.0

        # Bandwidth reduction vs full propagation
        # Full propagation would send full blob to every node for every tx
        naive_bandwidth = FULL_BLOB_SIZE * self.node_count * total_txs
        bandwidth_reduction = naive_bandwidth / self._total_bytes if self._total_bytes > 0 else 0.0

        # Provider coverage: average fraction of nodes that became providers per tx
        # (among nodes that saw each tx)
        provider_coverages = []
        for metrics in self.tx_metrics.values():
            nodes_seen = len(metrics.nodes_seen)
            if nodes_seen > 0:
                provider_coverages.append(metrics.provider_count / nodes_seen)
        provider_coverage = (
            sum(provider_coverages) / len(provider_coverages) if provider_coverages else 0.0
        )

        # Local availability met: fraction of nodes meeting local availability
        # Providers need full blob (ALL_ONES), samplers need custody columns
        local_availability_count = 0
        total_node_tx_pairs = 0

        for metrics in self.tx_metrics.values():
            for node_id, cell_mask in metrics.cell_masks.items():
                total_node_tx_pairs += 1
                if cell_mask == ALL_ONES:
                    local_availability_count += 1
                else:
                    custody_mask = self.node_custody_masks.get(node_id, 0)
                    if (cell_mask & custody_mask) == custody_mask:
                        local_availability_count += 1

        local_availability_met = (
            local_availability_count / total_node_tx_pairs if total_node_tx_pairs > 0 else 0.0
        )

        return SimulationResults(
            # Bandwidth
            total_bandwidth_bytes=self._total_bytes,
            bandwidth_per_blob=bandwidth_per_blob,
            bandwidth_reduction_vs_full=bandwidth_reduction,
            # Propagation
            median_propagation_time=median(propagation_times) if propagation_times else 0.0,
            p99_propagation_time=(
                sorted(propagation_times)[int(len(propagation_times) * 0.99)]
                if propagation_times
                else 0.0
            ),
            propagation_success_rate=(len(propagation_times) / total_txs if total_txs > 0 else 0.0),
            # Reliability
            observed_provider_ratio=(total_providers / total_roles if total_roles > 0 else 0.0),
            reconstruction_success_rate=(
                reconstruction_successes / total_txs if total_txs > 0 else 0.0
            ),
            false_availability_rate=0.0,  # Requires adversary scenario to measure
            # Sparse protocol metrics
            provider_coverage=provider_coverage,
            expected_provider_coverage=self.expected_provider_probability,
            local_availability_met=local_availability_met,
            # Attack outcomes
            spam_amplification_factor=(
                self.spam_accepted / (self.spam_accepted + self.spam_rejected)
                if (self.spam_accepted + self.spam_rejected) > 0
                else 0.0
            ),
            victim_blobpool_pollution=0.0,  # Requires adversary scenario
            withholding_detection_rate=0.0,  # Requires adversary scenario
            # Raw data
            bandwidth_timeseries=self.bandwidth_timeseries,
            propagation_timeseries=self.propagation_timeseries,
            bytes_sent_per_node=dict(self.bytes_sent),
            bytes_received_per_node=dict(self.bytes_received),
        )
