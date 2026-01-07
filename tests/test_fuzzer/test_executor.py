from sparse_blobpool.config import SimulationConfig
from sparse_blobpool.fuzzer.config import AnomalyThresholds
from sparse_blobpool.fuzzer.executor import (
    detect_anomalies,
    determine_status,
    execute_baseline,
)
from sparse_blobpool.metrics.results import SimulationResults


def test_execute_baseline_returns_results() -> None:
    config = SimulationConfig(node_count=10, mesh_degree=5, seed=42)
    results, error = execute_baseline(config, num_transactions=2, duration=5.0)
    assert error is None
    assert results is not None
    assert isinstance(results, SimulationResults)


def test_execute_baseline_catches_exceptions() -> None:
    config = SimulationConfig(node_count=0, mesh_degree=5, seed=42)
    results, error = execute_baseline(config, num_transactions=1, duration=5.0)
    assert error is not None
    assert results is None


def _make_good_results() -> SimulationResults:
    return SimulationResults(
        total_bandwidth_bytes=1000,
        bandwidth_per_blob=100.0,
        bandwidth_reduction_vs_full=0.5,
        median_propagation_time=0.1,
        p99_propagation_time=1.0,
        propagation_success_rate=0.99,
        observed_provider_ratio=0.15,
        reconstruction_success_rate=0.99,
        false_availability_rate=0.01,
        provider_coverage=0.15,
        expected_provider_coverage=0.15,
        local_availability_met=0.95,
    )


def test_detect_anomalies_empty_for_good_metrics() -> None:
    thresholds = AnomalyThresholds()
    good = _make_good_results()
    anomalies = detect_anomalies(good, thresholds)
    assert anomalies == []


def test_detect_anomalies_p99_propagation_time() -> None:
    thresholds = AnomalyThresholds()
    bad = SimulationResults(
        total_bandwidth_bytes=1000,
        bandwidth_per_blob=100.0,
        bandwidth_reduction_vs_full=0.5,
        median_propagation_time=0.1,
        p99_propagation_time=50.0,
        propagation_success_rate=0.99,
        observed_provider_ratio=0.15,
        reconstruction_success_rate=0.99,
        false_availability_rate=0.01,
        provider_coverage=0.15,
        expected_provider_coverage=0.15,
        local_availability_met=0.95,
    )
    anomalies = detect_anomalies(bad, thresholds)
    assert len(anomalies) == 1
    marker, msg = anomalies[0]
    assert marker == "high_latency"
    assert "p99_propagation_time" in msg


def test_detect_anomalies_reconstruction_success_rate() -> None:
    thresholds = AnomalyThresholds()
    bad = SimulationResults(
        total_bandwidth_bytes=1000,
        bandwidth_per_blob=100.0,
        bandwidth_reduction_vs_full=0.5,
        median_propagation_time=0.1,
        p99_propagation_time=1.0,
        propagation_success_rate=0.99,
        observed_provider_ratio=0.15,
        reconstruction_success_rate=0.8,
        false_availability_rate=0.01,
        provider_coverage=0.15,
        expected_provider_coverage=0.15,
        local_availability_met=0.95,
    )
    anomalies = detect_anomalies(bad, thresholds)
    assert len(anomalies) == 1
    marker, msg = anomalies[0]
    assert marker == "low_reconstruction"
    assert "reconstruction_success_rate" in msg


def test_detect_anomalies_false_availability_rate() -> None:
    thresholds = AnomalyThresholds()
    bad = SimulationResults(
        total_bandwidth_bytes=1000,
        bandwidth_per_blob=100.0,
        bandwidth_reduction_vs_full=0.5,
        median_propagation_time=0.1,
        p99_propagation_time=1.0,
        propagation_success_rate=0.99,
        observed_provider_ratio=0.15,
        reconstruction_success_rate=0.99,
        false_availability_rate=0.1,
        provider_coverage=0.15,
        expected_provider_coverage=0.15,
        local_availability_met=0.95,
    )
    anomalies = detect_anomalies(bad, thresholds)
    assert len(anomalies) == 1
    marker, msg = anomalies[0]
    assert marker == "high_false_availability"
    assert "false_availability_rate" in msg


def test_detect_anomalies_provider_coverage() -> None:
    thresholds = AnomalyThresholds()
    bad = SimulationResults(
        total_bandwidth_bytes=1000,
        bandwidth_per_blob=100.0,
        bandwidth_reduction_vs_full=0.5,
        median_propagation_time=0.1,
        p99_propagation_time=1.0,
        propagation_success_rate=0.99,
        observed_provider_ratio=0.02,
        reconstruction_success_rate=0.99,
        false_availability_rate=0.01,
        provider_coverage=0.02,
        expected_provider_coverage=0.15,  # 0.02 < 0.15 * 0.5 = 0.075
        local_availability_met=0.95,
    )
    anomalies = detect_anomalies(bad, thresholds)
    assert len(anomalies) == 1
    marker, msg = anomalies[0]
    assert marker == "low_provider_coverage"
    assert "provider_coverage" in msg


def test_detect_anomalies_local_availability_met() -> None:
    thresholds = AnomalyThresholds()
    bad = SimulationResults(
        total_bandwidth_bytes=1000,
        bandwidth_per_blob=100.0,
        bandwidth_reduction_vs_full=0.5,
        median_propagation_time=0.1,
        p99_propagation_time=1.0,
        propagation_success_rate=0.99,
        observed_provider_ratio=0.15,
        reconstruction_success_rate=0.99,
        false_availability_rate=0.01,
        provider_coverage=0.15,
        expected_provider_coverage=0.15,
        local_availability_met=0.5,
    )
    anomalies = detect_anomalies(bad, thresholds)
    assert len(anomalies) == 1
    marker, msg = anomalies[0]
    assert marker == "low_local_availability"
    assert "local_availability_met" in msg


def test_detect_anomalies_all_violations() -> None:
    thresholds = AnomalyThresholds()
    bad = SimulationResults(
        total_bandwidth_bytes=1000,
        bandwidth_per_blob=100.0,
        bandwidth_reduction_vs_full=0.5,
        median_propagation_time=0.1,
        p99_propagation_time=50.0,
        propagation_success_rate=0.5,
        observed_provider_ratio=0.02,
        reconstruction_success_rate=0.8,
        false_availability_rate=0.1,
        provider_coverage=0.02,
        expected_provider_coverage=0.15,
        local_availability_met=0.5,
    )
    anomalies = detect_anomalies(bad, thresholds)
    assert len(anomalies) == 5


def test_determine_status_success() -> None:
    assert determine_status([], None) == "success"


def test_determine_status_attention() -> None:
    assert (
        determine_status([("low_provider_coverage", "some anomaly")], None)
        == "ATTENTION(low_provider_coverage)"
    )


def test_determine_status_attention_multiple() -> None:
    anomalies = [("low_provider_coverage", "msg1"), ("high_latency", "msg2")]
    assert determine_status(anomalies, None) == "ATTENTION(low_provider_coverage,high_latency)"


def test_determine_status_error() -> None:
    assert determine_status([], ValueError("test")) == "error"
    assert determine_status([("marker", "anomaly")], ValueError("test")) == "error"
