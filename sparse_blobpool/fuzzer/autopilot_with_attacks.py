"""Fuzzer autopilot with integrated attack scenario support.

This enhanced version of the fuzzer autopilot incorporates weighted attack scenarios,
allowing for probabilistic execution of different attack types during fuzzing runs.
"""

from __future__ import annotations

import json
import signal
import time
from datetime import UTC, datetime
from random import Random
from typing import TYPE_CHECKING

from sparse_blobpool.fuzzer.database import RunsDatabase
from sparse_blobpool.fuzzer.executor import (
    Anomaly,
    detect_anomalies,
    determine_status,
)
from sparse_blobpool.fuzzer.generator import (
    config_to_dict,
    generate_mempool_saturation_target,
    generate_run_id,
    generate_simulation_config,
    validate_config,
)
from sparse_blobpool.metrics.victim_metrics import (
    VictimMetricsCollector,
    extend_metrics_with_victims,
)
from sparse_blobpool.scenarios.attacks.registry import (
    AttackRegistry,
    AttackType,
    create_attack_executor,
)

if TYPE_CHECKING:
    from pathlib import Path

    from sparse_blobpool.fuzzer.config import FuzzerConfig

from sparse_blobpool.core.simulator import Simulator

_running = True


def _handle_sigint(signum: int, frame: object) -> None:
    global _running
    _running = False


def save_run(db: RunsDatabase, summary: dict[str, object]) -> None:
    """Save run to SQLite database."""
    db.insert_run(summary)  # type: ignore[arg-type]


def write_trace(
    output_dir: Path,
    run_id: str,
    config: dict[str, object],
    metrics: dict[str, object],
    seed: int,
    attack_info: dict[str, object] | None = None,
) -> None:
    trace_dir = output_dir / run_id
    trace_dir.mkdir(parents=True, exist_ok=True)

    config_with_seed = {**config, "seed": seed}
    if attack_info:
        config_with_seed["attack"] = attack_info

    (trace_dir / "config.json").write_text(json.dumps(config_with_seed, indent=2), encoding="utf-8")
    (trace_dir / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")


def execute_scenario_with_attack(
    sim_config: object,
    num_transactions: int,
    run_duration: float,
    attack_registry: AttackRegistry,
    run_rng: Random,
) -> tuple[object | None, Exception | None, dict[str, object], object | None]:
    """Execute a simulation scenario with potential attacks.

    Returns:
        Tuple of (results, error, attack_info)
    """
    # Build the simulator first
    sim = Simulator.build(sim_config)  # type: ignore

    # Select and configure attack
    attack_selection = attack_registry.select_attack(sim, run_rng)

    # Store attack info for metrics
    attack_info = {
        "type": attack_selection.attack_type.value,
        "attacker_count": attack_selection.attacker_count,
        "victim_count": len(attack_selection.victim_profile.victims)
        if attack_selection.victim_profile
        else 0,
        "victim_strategy": attack_selection.victim_profile.strategy.value
        if attack_selection.victim_profile
        else None,
        "victims": attack_selection.victim_profile.victims
        if attack_selection.victim_profile
        else [],
        "params": attack_selection.attack_params,
        "metadata": attack_selection.metadata,
    }

    victim_metrics_collector = None
    if attack_selection.victim_profile:
        victim_metrics_collector = VictimMetricsCollector(sim.metrics)
        victim_metrics_collector.set_victim_profile(attack_selection.victim_profile)

    # Execute the attack if not baseline
    if attack_selection.attack_type != AttackType.NONE:
        executor = create_attack_executor(attack_selection, sim_config)  # type: ignore
        executor(sim)

    # Run the simulation
    try:
        # Broadcast transactions
        for _ in range(num_transactions):
            origin_idx = sim.rng.randint(0, len(sim.nodes) - 1)
            sim.broadcast_transaction(sim.nodes[origin_idx])

        sim.block_producer.start()
        sim.run(run_duration)

        results = sim.finalize_metrics()
        victim_metrics = (
            victim_metrics_collector.finalize(sim) if victim_metrics_collector else None
        )
        return results, None, attack_info, victim_metrics
    except Exception as e:
        return None, e, attack_info, None


def run_fuzzer_with_attacks(
    config: FuzzerConfig,
    attack_registry: AttackRegistry | None = None,
) -> None:
    """Run the fuzzer with attack scenario support.

    Args:
        config: Fuzzer configuration.
        attack_registry: Optional attack registry with weighted scenarios.
    """
    global _running
    _running = True

    signal.signal(signal.SIGINT, _handle_sigint)

    rng = Random(config.master_seed) if config.master_seed is not None else Random()

    if attack_registry is None:
        attack_registry = AttackRegistry()

    config.output_dir.mkdir(parents=True, exist_ok=True)

    # Initialize SQLite database
    db = RunsDatabase(config.output_dir / "runs.db")

    # Write attack weights summary
    weights_file = config.output_dir / "attack_weights.json"
    weights_file.write_text(
        json.dumps(
            {
                "weights": {k.value: v for k, v in attack_registry.get_weights_summary().items()},
                "timestamp": datetime.now(UTC).isoformat(),
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    run_count = 0
    attack_counts = dict.fromkeys(AttackType, 0)

    while _running:
        if config.max_runs is not None and run_count >= config.max_runs:
            break

        run_seed = rng.randint(0, 2**31 - 1)
        run_rng = Random(run_seed)

        run_id = generate_run_id(run_rng)
        saturation_target = generate_mempool_saturation_target(
            run_rng, config.parameter_ranges.mempool_saturation_target
        )

        sim_config = generate_simulation_config(
            run_rng,
            config.parameter_ranges,
            config.simulation_duration,
        )

        # Calculate num_transactions from saturation target
        num_slots = int(config.simulation_duration / sim_config.slot_duration)
        num_transactions = max(
            1, int(saturation_target * sim_config.max_blobs_per_block * num_slots)
        )

        is_valid, _validation_errors = validate_config(sim_config)
        if not is_valid:
            continue

        start_time = datetime.now(UTC)
        wall_start = time.monotonic()

        results, error, attack_info, victim_metrics = execute_scenario_with_attack(
            sim_config, num_transactions, config.simulation_duration, attack_registry, run_rng
        )

        wall_end = time.monotonic()
        end_time = datetime.now(UTC)
        wall_clock = wall_end - wall_start

        anomalies: list[Anomaly] = []
        metrics_dict: dict[str, object] = {}
        if results is not None:
            anomalies = detect_anomalies(results, config.anomaly_thresholds)  # type: ignore
            if victim_metrics is not None:
                metrics_dict = extend_metrics_with_victims(results, victim_metrics)  # type: ignore
            else:
                metrics_dict = results.to_dict()  # type: ignore

        status = determine_status(anomalies, error)

        # Update attack counts
        attack_counts[AttackType(attack_info["type"])] += 1

        scenario_name = f"{attack_info['type']}"
        summary = {
            "run_id": run_id,
            "seed": run_seed,
            "scenario": scenario_name,
            "attack": attack_info,
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

        save_run(db, summary)

        status_display = "OK" if status == "success" else status
        print(
            f"[{run_id}] {scenario_name} seed={run_seed} "
            f"victims={len(attack_info['victims'])} ... {status_display} ({wall_clock:.1f}s)"
        )

        should_trace = not config.trace_on_anomaly_only or not status.startswith("success")
        if should_trace:
            write_trace(
                config.output_dir,
                run_id,
                config_to_dict(sim_config),
                metrics_dict,
                run_seed,
                attack_info,
            )

        run_count += 1

        # Print attack distribution every 100 runs
        if run_count % 100 == 0:
            print(f"\nAttack distribution after {run_count} runs:")
            for attack_type, count in attack_counts.items():
                percentage = (count / run_count) * 100
                print(f"  {attack_type.value}: {count} ({percentage:.1f}%)")
            print()


def replay_run_with_attack(
    seed: int,
    config: FuzzerConfig,
    attack_registry: AttackRegistry | None = None,
) -> None:
    """Replay a specific run with attack support.

    Args:
        seed: Random seed for the run.
        config: Fuzzer configuration.
        attack_registry: Optional attack registry with weighted scenarios.
    """
    run_rng = Random(seed)

    if attack_registry is None:
        attack_registry = AttackRegistry()

    run_id = generate_run_id(run_rng)
    saturation_target = generate_mempool_saturation_target(
        run_rng, config.parameter_ranges.mempool_saturation_target
    )

    sim_config = generate_simulation_config(
        run_rng,
        config.parameter_ranges,
        config.simulation_duration,
    )

    # Calculate num_transactions from saturation target
    num_slots = int(config.simulation_duration / sim_config.slot_duration)
    num_transactions = max(1, int(saturation_target * sim_config.max_blobs_per_block * num_slots))

    is_valid, _validation_errors = validate_config(sim_config)
    if not is_valid:
        print(f"[{run_id}] seed={seed} ... INVALID (config failed validation)")
        return

    start_time = datetime.now(UTC)
    wall_start = time.monotonic()

    results, error, attack_info, victim_metrics = execute_scenario_with_attack(
        sim_config, num_transactions, config.simulation_duration, attack_registry, run_rng
    )

    wall_end = time.monotonic()
    end_time = datetime.now(UTC)
    wall_clock = wall_end - wall_start

    anomalies: list[Anomaly] = []
    metrics_dict: dict[str, object] = {}
    if results is not None:
        anomalies = detect_anomalies(results, config.anomaly_thresholds)  # type: ignore
        if victim_metrics is not None:
            metrics_dict = extend_metrics_with_victims(results, victim_metrics)  # type: ignore
        else:
            metrics_dict = results.to_dict()  # type: ignore

    status = determine_status(anomalies, error)

    config.output_dir.mkdir(parents=True, exist_ok=True)

    # Initialize SQLite database
    db = RunsDatabase(config.output_dir / "runs.db")

    scenario_name = f"{attack_info['type']}"
    summary = {
        "run_id": run_id,
        "seed": seed,
        "scenario": scenario_name,
        "attack": attack_info,
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

    save_run(db, summary)
    write_trace(
        config.output_dir, run_id, config_to_dict(sim_config), metrics_dict, seed, attack_info
    )

    print(json.dumps(summary, indent=2))
