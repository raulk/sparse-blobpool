from __future__ import annotations

import json
import signal
import time
from datetime import UTC, datetime
from random import Random
from typing import TYPE_CHECKING

from sparse_blobpool.fuzzer.executor import (
    Anomaly,
    detect_anomalies,
    determine_status,
    execute_baseline,
)
from sparse_blobpool.fuzzer.generator import (
    config_to_dict,
    generate_num_transactions,
    generate_run_id,
    generate_simulation_config,
    validate_config,
)

if TYPE_CHECKING:
    from pathlib import Path

    from sparse_blobpool.fuzzer.config import FuzzerConfig

from sparse_blobpool.fuzzer.config import (
    DEFAULT_DURATION_SLOTS,
    SLOT_DURATION_SECS,
    SLOTS_PER_EPOCH,
)

_running = True


def _handle_sigint(signum: int, frame: object) -> None:
    global _running
    _running = False


def append_summary(path: Path, summary: dict[str, object]) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(summary) + "\n")


def write_trace(
    output_dir: Path,
    run_id: str,
    config: dict[str, object],
    metrics: dict[str, object],
    seed: int,
) -> None:
    trace_dir = output_dir / run_id
    trace_dir.mkdir(parents=True, exist_ok=True)

    config_with_seed = {**config, "seed": seed}
    (trace_dir / "config.json").write_text(json.dumps(config_with_seed, indent=2), encoding="utf-8")

    (trace_dir / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")


def run_fuzzer(config: FuzzerConfig) -> None:
    global _running
    _running = True

    signal.signal(signal.SIGINT, _handle_sigint)

    rng = Random(config.master_seed) if config.master_seed is not None else Random()

    config.output_dir.mkdir(parents=True, exist_ok=True)
    ndjson_path = config.output_dir / config.overview_file

    run_count = 0
    while _running:
        if config.max_runs is not None and run_count >= config.max_runs:
            break

        run_seed = rng.randint(0, 2**31 - 1)
        run_rng = Random(run_seed)

        run_id = generate_run_id(run_rng)
        num_transactions = generate_num_transactions(
            run_rng, config.parameter_ranges.num_transactions
        )

        sim_config = generate_simulation_config(
            run_rng,
            config.parameter_ranges,
            config.simulation_duration,
        )

        is_valid, _validation_errors = validate_config(sim_config)
        if not is_valid:
            continue

        start_time = datetime.now(UTC)
        wall_start = time.monotonic()

        results, error = execute_baseline(sim_config, num_transactions, config.simulation_duration)

        wall_end = time.monotonic()
        end_time = datetime.now(UTC)
        wall_clock = wall_end - wall_start

        anomalies: list[Anomaly] = []
        metrics_dict: dict[str, object] = {}
        if results is not None:
            anomalies = detect_anomalies(results, config.anomaly_thresholds)
            metrics_dict = results.to_dict()

        status = determine_status(anomalies, error)

        summary = {
            "run_id": run_id,
            "seed": run_seed,
            "scenario": "BASELINE",
            "status": status,
            "anomalies": [msg for _, msg in anomalies],
            "metrics": metrics_dict,
            "config": config_to_dict(sim_config),
            "wall_clock_seconds": round(wall_clock, 2),
            "simulated_seconds": config.simulation_duration,
            "timestamp_start": start_time.isoformat(),
            "timestamp_end": end_time.isoformat(),
        }

        if error is not None:
            summary["error"] = str(error)

        append_summary(ndjson_path, summary)

        status_display = "OK" if status == "success" else status
        print(f"[{run_id}] BASELINE seed={run_seed} ... {status_display} ({wall_clock:.1f}s)")

        should_trace = not config.trace_on_anomaly_only or not status.startswith("success")
        if should_trace:
            write_trace(
                config.output_dir, run_id, config_to_dict(sim_config), metrics_dict, run_seed
            )

        run_count += 1


def replay_run(seed: int, config: FuzzerConfig) -> None:
    run_rng = Random(seed)

    run_id = generate_run_id(run_rng)
    num_transactions = generate_num_transactions(run_rng, config.parameter_ranges.num_transactions)

    sim_config = generate_simulation_config(
        run_rng,
        config.parameter_ranges,
        config.simulation_duration,
    )

    is_valid, _validation_errors = validate_config(sim_config)
    if not is_valid:
        print(f"[{run_id}] BASELINE seed={seed} ... INVALID (config failed validation)")
        return

    start_time = datetime.now(UTC)
    wall_start = time.monotonic()

    results, error = execute_baseline(sim_config, num_transactions, config.simulation_duration)

    wall_end = time.monotonic()
    end_time = datetime.now(UTC)
    wall_clock = wall_end - wall_start

    anomalies: list[Anomaly] = []
    metrics_dict: dict[str, object] = {}
    if results is not None:
        anomalies = detect_anomalies(results, config.anomaly_thresholds)
        metrics_dict = results.to_dict()

    status = determine_status(anomalies, error)

    config.output_dir.mkdir(parents=True, exist_ok=True)
    ndjson_path = config.output_dir / config.overview_file

    summary = {
        "run_id": run_id,
        "seed": seed,
        "scenario": "BASELINE",
        "status": status,
        "anomalies": [msg for _, msg in anomalies],
        "metrics": metrics_dict,
        "config": config_to_dict(sim_config),
        "wall_clock_seconds": round(wall_clock, 2),
        "simulated_seconds": config.simulation_duration,
        "timestamp_start": start_time.isoformat(),
        "timestamp_end": end_time.isoformat(),
        "replay": True,
    }

    if error is not None:
        summary["error"] = str(error)

    append_summary(ndjson_path, summary)

    status_display = "OK" if status == "success" else status
    print(f"[{run_id}] BASELINE seed={seed} ... {status_display} ({wall_clock:.1f}s) [REPLAY]")

    write_trace(config.output_dir, run_id, config_to_dict(sim_config), metrics_dict, seed)


def main() -> None:
    import argparse
    from pathlib import Path

    from sparse_blobpool.fuzzer.config import (
        AnomalyThresholds,
        FuzzerConfig,
        ParameterRanges,
    )

    parser = argparse.ArgumentParser(description="Fuzzer autopilot for sparse blobpool simulation")
    parser.add_argument(
        "--config",
        type=Path,
        help="Path to TOML configuration file",
    )
    parser.add_argument(
        "--max-runs",
        type=int,
        help="Maximum number of runs (default: unlimited)",
    )

    duration_group = parser.add_mutually_exclusive_group()
    duration_group.add_argument(
        "--duration-secs",
        type=float,
        help="Simulation duration in seconds",
    )
    duration_group.add_argument(
        "--duration-slots",
        type=int,
        help="Simulation duration in slots (1 slot = 12s)",
    )
    duration_group.add_argument(
        "--duration-epochs",
        type=int,
        help="Simulation duration in epochs (1 epoch = 32 slots = 384s)",
    )

    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("fuzzer_output"),
        help="Output directory (default: fuzzer_output)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        help="Master seed for reproducibility",
    )
    parser.add_argument(
        "--trace-all",
        action="store_true",
        help="Write traces for all runs, not just anomalies",
    )
    parser.add_argument(
        "--replay",
        type=int,
        metavar="SEED",
        help="Replay a single run with the given seed",
    )
    parser.add_argument(
        "--serve",
        action="store_true",
        help="Start the monitoring dashboard server",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port for the monitoring server (default: 8000)",
    )

    args = parser.parse_args()

    slot_tail_buffer = SLOT_DURATION_SECS - 0.0001

    if args.duration_secs is not None:
        duration = args.duration_secs
    elif args.duration_slots is not None:
        duration = args.duration_slots * SLOT_DURATION_SECS + slot_tail_buffer
    elif args.duration_epochs is not None:
        duration = args.duration_epochs * SLOTS_PER_EPOCH * SLOT_DURATION_SECS + slot_tail_buffer
    else:
        duration = DEFAULT_DURATION_SLOTS * SLOT_DURATION_SECS + slot_tail_buffer

    if args.config is not None:
        fuzzer_config = FuzzerConfig.from_toml(args.config)
        if args.max_runs is not None:
            fuzzer_config.max_runs = args.max_runs
        if args.seed is not None:
            fuzzer_config.master_seed = args.seed
        if args.trace_all:
            fuzzer_config.trace_on_anomaly_only = False
        fuzzer_config.simulation_duration = duration
        fuzzer_config.output_dir = args.output_dir
    else:
        fuzzer_config = FuzzerConfig(
            max_runs=args.max_runs,
            simulation_duration=duration,
            parameter_ranges=ParameterRanges(),
            anomaly_thresholds=AnomalyThresholds(),
            output_dir=args.output_dir,
            trace_on_anomaly_only=not args.trace_all,
            master_seed=args.seed,
        )

    serve_only = args.serve and args.replay is None and args.max_runs is None

    if serve_only:
        from sparse_blobpool.fuzzer.server import run_server

        run_server(args.output_dir, port=args.port)
    elif args.serve:
        from sparse_blobpool.fuzzer.server import start_server_background

        start_server_background(args.output_dir, port=args.port)

        if args.replay is not None:
            replay_run(args.replay, fuzzer_config)
        else:
            run_fuzzer(fuzzer_config)

        print(f"\nFuzzing complete. Server still running at http://localhost:{args.port}")
        print("Press Ctrl+C to exit.")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
    elif args.replay is not None:
        replay_run(args.replay, fuzzer_config)
    else:
        run_fuzzer(fuzzer_config)


if __name__ == "__main__":
    main()
