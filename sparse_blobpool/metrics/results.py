"""Simulation results and snapshot data structures."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sparse_blobpool.core.latency import Country
    from sparse_blobpool.core.types import ActorId, TxHash


@dataclass
class BandwidthSnapshot:
    timestamp: float
    total_bytes: int
    control_bytes: int
    data_bytes: int
    per_country: dict[Country, int] = field(default_factory=dict)


@dataclass
class PropagationSnapshot:
    timestamp: float
    tx_hash: TxHash
    nodes_seen: int
    nodes_with_full: int  # Nodes with ALL_ONES cell_mask
    nodes_with_sample: int  # Nodes with partial cell_mask
    reconstruction_possible: bool  # >= 64 distinct columns exist


@dataclass
class SimulationResults:
    # Bandwidth efficiency
    total_bandwidth_bytes: int
    bandwidth_per_blob: float
    bandwidth_reduction_vs_full: float  # Ratio vs naive full propagation

    # Propagation performance
    median_propagation_time: float
    p99_propagation_time: float
    propagation_success_rate: float  # Fraction reaching 99% of network

    # Protocol reliability
    observed_provider_ratio: float  # Actual provider fraction (~0.15 target)
    reconstruction_success_rate: float  # Fraction of txs reconstructible
    false_availability_rate: float  # Appeared available but wasn't

    # Sparse protocol metrics
    provider_coverage: float  # Fraction of nodes that became providers per tx
    expected_provider_coverage: float  # Expected provider probability from config
    local_availability_met: float  # Fraction of nodes meeting local availability

    # DA check metrics (per block)
    da_checks_passed_rate: float  # Fraction of nodes passing DA checks across all blocks

    # Attack outcomes (populated when adversaries present)
    spam_amplification_factor: float = 0.0
    victim_blobpool_pollution: float = 0.0
    withholding_detection_rate: float = 0.0

    # Raw data for further analysis
    bandwidth_timeseries: list[BandwidthSnapshot] = field(default_factory=list)
    propagation_timeseries: list[PropagationSnapshot] = field(default_factory=list)

    # Per-node bandwidth breakdown
    bytes_sent_per_node: dict[ActorId, int] = field(default_factory=dict)
    bytes_received_per_node: dict[ActorId, int] = field(default_factory=dict)

    # Column coverage: number of nodes custodying each column (128 values)
    column_coverage: list[int] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "total_bandwidth_bytes": self.total_bandwidth_bytes,
            "bandwidth_per_blob": self.bandwidth_per_blob,
            "bandwidth_reduction_vs_full": self.bandwidth_reduction_vs_full,
            "median_propagation_time": self.median_propagation_time,
            "p99_propagation_time": self.p99_propagation_time,
            "propagation_success_rate": self.propagation_success_rate,
            "observed_provider_ratio": self.observed_provider_ratio,
            "reconstruction_success_rate": self.reconstruction_success_rate,
            "false_availability_rate": self.false_availability_rate,
            "provider_coverage": self.provider_coverage,
            "expected_provider_coverage": self.expected_provider_coverage,
            "local_availability_met": self.local_availability_met,
            "da_checks_passed_rate": self.da_checks_passed_rate,
            "spam_amplification_factor": self.spam_amplification_factor,
            "victim_blobpool_pollution": self.victim_blobpool_pollution,
            "withholding_detection_rate": self.withholding_detection_rate,
            "column_coverage": self.column_coverage,
        }
