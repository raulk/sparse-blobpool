from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

type IntRange = tuple[int, int]
type FloatRange = tuple[float, float]

SLOT_DURATION_SECS = 12.0
SLOTS_PER_EPOCH = 32
DEFAULT_DURATION_SLOTS = 5


@dataclass(frozen=True)
class NodeTypeConfig:
    """Configuration for a node type with ranges for fuzzing.

    Bandwidth is specified in Mbps for readability.
    Custody columns and proportion are ranges to allow randomization per run.
    Proportions are normalized at runtime to sum to 1.
    """

    name: str
    download_mbps: float
    upload_mbps: float
    custody_columns: IntRange  # (min, max) columns
    proportion: FloatRange  # (min, max) weight, normalized at runtime

    @property
    def download_bps(self) -> int:
        """Download bandwidth in bytes per second."""
        return int(self.download_mbps * 1_000_000 / 8)

    @property
    def upload_bps(self) -> int:
        """Upload bandwidth in bytes per second."""
        return int(self.upload_mbps * 1_000_000 / 8)


# Default node type configurations per EIP-7870
DEFAULT_NODE_TYPES: list[NodeTypeConfig] = [
    NodeTypeConfig(
        name="full_node",
        download_mbps=50,
        upload_mbps=15,
        custody_columns=(4, 4),  # fixed at 4
        proportion=(0.60, 0.80),
    ),
    NodeTypeConfig(
        name="attester",
        download_mbps=50,
        upload_mbps=25,
        custody_columns=(8, 128),
        proportion=(0.10, 0.25),
    ),
    NodeTypeConfig(
        name="local_block_builder",
        download_mbps=100,
        upload_mbps=50,
        custody_columns=(8, 128),
        proportion=(0.05, 0.10),
    ),
    NodeTypeConfig(
        name="supernode",
        download_mbps=1000,
        upload_mbps=1000,
        custody_columns=(128, 128),  # fixed at 128
        proportion=(0.01, 0.05),
    ),
]


@dataclass(frozen=True)
class ParameterRanges:
    node_count: IntRange = (8000, 15000)
    mesh_degree: IntRange = (50, 50)  # fixed at 50

    provider_probability: FloatRange = (0.15, 0.15)  # fixed at 0.15
    min_providers_before_sample: IntRange = (2, 2)  # fixed at 2
    extra_random_columns: IntRange = (1, 2)
    max_columns_per_request: IntRange = (16, 16)  # fixed at 16

    provider_observation_timeout: FloatRange = (12.0, 36.0)  # 1-3 slots
    request_timeout: FloatRange = (5.0, 5.0)  # fixed at 5s
    tx_expiration: FloatRange = (300.0, 1800.0)  # 5-30 minutes

    blobpool_max_bytes: IntRange = (512 * 1024**2, 1024**3)  # 512MiB to 1GiB
    max_txs_per_sender: IntRange = (16, 16)  # fixed at 16

    # Mempool saturation target as multiplier of max_blobs_per_block per slot
    # e.g., (0.5, 1.5) means produce 0.5x to 1.5x max capacity per slot
    mempool_saturation_target: FloatRange = (0.5, 1.5)

    # Node type configurations (custody columns, bandwidth, proportions)
    node_types: tuple[NodeTypeConfig, ...] = tuple(DEFAULT_NODE_TYPES)


@dataclass(frozen=True)
class AnomalyThresholds:
    max_p99_propagation_time: float = 10.0
    min_reconstruction_success_rate: float = 0.95
    max_false_availability_rate: float = 0.05
    min_provider_coverage_ratio: float = 0.8  # Flag if < 80% of expected
    min_local_availability_met: float = 0.99  # Flag if < 99% nodes met local availability
    min_da_checks_passed_rate: float = 0.99  # Flag if < 99% DA checks pass


@dataclass
class FuzzerConfig:
    output_dir: Path
    max_runs: int | None = None
    simulation_duration: float = 60.0
    parameter_ranges: ParameterRanges = field(default_factory=ParameterRanges)
    anomaly_thresholds: AnomalyThresholds = field(default_factory=AnomalyThresholds)
    overview_file: str = "runs.ndjson"
    trace_on_anomaly_only: bool = True
    master_seed: int | None = None

    @classmethod
    def from_toml(cls, path: Path) -> FuzzerConfig:
        import tomllib

        with path.open("rb") as f:
            data = tomllib.load(f)

        execution = data.get("execution", {})
        output = data.get("output", {})
        ranges_data = data.get("ranges", {})
        thresholds_data = data.get("thresholds", {})
        node_types_data = data.get("node_types", [])

        ranges_kwargs: dict[str, IntRange | FloatRange | tuple[NodeTypeConfig, ...]] = {}
        for section in ["network", "protocol", "timeouts", "limits", "scenario"]:
            section_data = ranges_data.get(section, {})
            for key, value in section_data.items():
                if isinstance(value, dict) and "min" in value and "max" in value:
                    ranges_kwargs[key] = (value["min"], value["max"])

        # Parse node types if provided
        if node_types_data:
            node_types = []
            for nt in node_types_data:
                custody = nt.get("custody_columns", {})
                proportion = nt.get("proportion", {})
                node_types.append(
                    NodeTypeConfig(
                        name=nt["name"],
                        download_mbps=nt["download_mbps"],
                        upload_mbps=nt["upload_mbps"],
                        custody_columns=(custody.get("min", 8), custody.get("max", 8)),
                        proportion=(proportion.get("min", 0.25), proportion.get("max", 0.25)),
                    )
                )
            ranges_kwargs["node_types"] = tuple(node_types)

        parameter_ranges = ParameterRanges(**ranges_kwargs) if ranges_kwargs else ParameterRanges()

        thresholds_kwargs = {}
        for key, value in thresholds_data.items():
            thresholds_kwargs[key] = value

        anomaly_thresholds = (
            AnomalyThresholds(**thresholds_kwargs) if thresholds_kwargs else AnomalyThresholds()
        )

        from pathlib import Path as PathClass

        slot_tail_buffer = SLOT_DURATION_SECS - 0.0001

        if "duration_secs" in execution:
            duration = execution["duration_secs"]
        elif "duration_slots" in execution:
            duration = execution["duration_slots"] * SLOT_DURATION_SECS + slot_tail_buffer
        elif "duration_epochs" in execution:
            duration = (
                execution["duration_epochs"] * SLOTS_PER_EPOCH * SLOT_DURATION_SECS
                + slot_tail_buffer
            )
        else:
            duration = DEFAULT_DURATION_SLOTS * SLOT_DURATION_SECS + slot_tail_buffer

        return cls(
            output_dir=PathClass(output.get("dir", "fuzzer_output")),
            max_runs=execution.get("max_runs"),
            simulation_duration=duration,
            parameter_ranges=parameter_ranges,
            anomaly_thresholds=anomaly_thresholds,
            overview_file=output.get("overview_file", "runs.ndjson"),
            trace_on_anomaly_only=execution.get("trace_on_anomaly_only", True),
            master_seed=execution.get("master_seed"),
        )
