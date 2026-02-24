#!/usr/bin/env python3
"""Parameter sweep for blobpool heuristic tuning.

Usage:
    uv run python -m heuristic_sim.sweep
    uv run python -m heuristic_sim.sweep --param saturation_timeout --range 10,20,30,45,60
"""

from __future__ import annotations

import argparse
import sys

from heuristic_sim.blobpool_sim import HeuristicConfig, Scenario, run_simulation

DEFAULT_SCENARIO = Scenario(
    n_honest=30,
    attackers=[
        (5, "withholder", {"random_fail_rate": 0.5}),
        (3, "selective_signaler", {"n_senders": 5, "txs_per_sender": 16}),
        (3, "spammer", {"rate": 5.0, "below_includability": True}),
        (2, "spoofer", {}),
        (2, "free_rider", {}),
        (2, "non_announcer", {}),
    ],
    tx_arrival_rate=2.0,
    t_end=120.0,
)

SWEEP_RANGES: dict[str, list[float]] = {
    "includability_discount": [0.5, 0.6, 0.7, 0.8, 0.9],
    "saturation_timeout": [10.0, 20.0, 30.0, 45.0, 60.0],
    "c_extra_max": [1, 2, 3, 4, 6],
    "max_random_failure_rate": [0.05, 0.1, 0.15, 0.2, 0.3],
    "k_high": [1, 2, 3],
    "k_low": [2, 3, 4, 6],
}


def run_sweep(
    param: str,
    values: list[float],
    scenario: Scenario,
    seed: int = 42,
) -> list[tuple[float, object]]:
    results = []
    for val in values:
        overrides = {param: type(getattr(HeuristicConfig(), param))(val)}
        config = HeuristicConfig(**overrides)
        result = run_simulation(config, scenario, seed=seed)
        results.append((val, result))
    return results


def print_sweep_table(param: str, results: list[tuple[float, object]]) -> None:
    print(f"\n{'=' * 80}")
    print(f"Sweep: {param}")
    print(f"{'=' * 80}")
    header = f"{'Value':<12} {'Accepted':<10} {'H1 Rej':<8} {'H2 Evict':<10} {'H4 Disc':<8} {'FP':<5}"
    print(header)
    print("-" * len(header))
    for val, result in results:
        print(
            f"{val:<12} {result.total_accepted:<10} {result.h1_rejections:<8} "
            f"{result.h2_evictions:<10} {result.h4_disconnects:<8} "
            f"{result.false_positives:<5}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Blobpool heuristic parameter sweep")
    parser.add_argument("--param", type=str, default=None)
    parser.add_argument("--range", type=str, default=None)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    if args.param:
        values = (
            [float(v) for v in args.range.split(",")]
            if args.range
            else SWEEP_RANGES.get(args.param, [])
        )
        if not values:
            print(f"No range defined for {args.param}", file=sys.stderr)
            sys.exit(1)
        results = run_sweep(args.param, values, DEFAULT_SCENARIO, args.seed)
        print_sweep_table(args.param, results)
    else:
        for param, values in SWEEP_RANGES.items():
            results = run_sweep(param, values, DEFAULT_SCENARIO, args.seed)
            print_sweep_table(param, results)


if __name__ == "__main__":
    main()
