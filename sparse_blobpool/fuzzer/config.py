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
class ParameterRanges:
    node_count: IntRange = (50, 2000)
    mesh_degree: IntRange = (5, 100)

    provider_probability: FloatRange = (0.05, 0.50)
    min_providers_before_sample: IntRange = (1, 5)
    extra_random_columns: IntRange = (0, 4)
    max_columns_per_request: IntRange = (4, 16)
    custody_columns: IntRange = (4, 16)

    provider_observation_timeout: FloatRange = (0.5, 5.0)
    request_timeout: FloatRange = (1.0, 10.0)
    tx_expiration: FloatRange = (60.0, 600.0)

    blobpool_max_bytes: IntRange = (512 * 1024**2, 4 * 1024**3)
    max_txs_per_sender: IntRange = (4, 32)
    default_bandwidth: FloatRange = (10 * 1024**2, 200 * 1024**2)

    num_transactions: IntRange = (1, 20)


@dataclass(frozen=True)
class AnomalyThresholds:
    max_p99_propagation_time: float = 30.0
    min_reconstruction_success_rate: float = 0.95
    max_false_availability_rate: float = 0.05
    min_provider_coverage_ratio: float = 0.5  # Flag if < 50% of expected
    min_local_availability_met: float = 0.90  # Flag if < 90% nodes met local availability


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

        ranges_kwargs: dict[str, IntRange | FloatRange] = {}
        for section in ["network", "protocol", "timeouts", "limits", "scenario"]:
            section_data = ranges_data.get(section, {})
            for key, value in section_data.items():
                if isinstance(value, dict) and "min" in value and "max" in value:
                    ranges_kwargs[key] = (value["min"], value["max"])

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
