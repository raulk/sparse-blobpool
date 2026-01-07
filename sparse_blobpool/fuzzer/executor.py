from __future__ import annotations

from typing import TYPE_CHECKING

from sparse_blobpool.scenarios.baseline import run_baseline_scenario

if TYPE_CHECKING:
    from sparse_blobpool.config import SimulationConfig
    from sparse_blobpool.fuzzer.config import AnomalyThresholds
    from sparse_blobpool.metrics.results import SimulationResults


def execute_baseline(
    config: SimulationConfig,
    num_transactions: int,
    duration: float,
) -> tuple[SimulationResults | None, Exception | None]:
    try:
        sim = run_baseline_scenario(
            config=config,
            num_transactions=num_transactions,
            run_duration=duration,
        )
        results = sim.finalize_metrics()
        return (results, None)
    except Exception as e:
        return (None, e)


type Anomaly = tuple[str, str]  # (marker, message)


def detect_anomalies(
    metrics: SimulationResults,
    thresholds: AnomalyThresholds,
) -> list[Anomaly]:
    anomalies: list[Anomaly] = []

    if metrics.p99_propagation_time > thresholds.max_p99_propagation_time:
        anomalies.append((
            "high_latency",
            f"p99_propagation_time={metrics.p99_propagation_time:.3f} "
            f"> {thresholds.max_p99_propagation_time}",
        ))

    if metrics.reconstruction_success_rate < thresholds.min_reconstruction_success_rate:
        anomalies.append((
            "low_reconstruction",
            f"reconstruction_success_rate={metrics.reconstruction_success_rate:.3f} "
            f"< {thresholds.min_reconstruction_success_rate}",
        ))

    if metrics.false_availability_rate > thresholds.max_false_availability_rate:
        anomalies.append((
            "high_false_availability",
            f"false_availability_rate={metrics.false_availability_rate:.3f} "
            f"> {thresholds.max_false_availability_rate}",
        ))

    min_expected = metrics.expected_provider_coverage * thresholds.min_provider_coverage_ratio
    if metrics.provider_coverage < min_expected:
        anomalies.append((
            "low_provider_coverage",
            f"provider_coverage={metrics.provider_coverage:.3f} "
            f"< {min_expected:.3f} (expected={metrics.expected_provider_coverage:.3f})",
        ))

    if metrics.local_availability_met < thresholds.min_local_availability_met:
        anomalies.append((
            "low_local_availability",
            f"local_availability_met={metrics.local_availability_met:.3f} "
            f"< {thresholds.min_local_availability_met}",
        ))

    return anomalies


def determine_status(anomalies: list[Anomaly], error: Exception | None) -> str:
    if error is not None:
        return "error"
    if anomalies:
        markers = ",".join(marker for marker, _ in anomalies)
        return f"ATTENTION({markers})"
    return "success"
