#!/usr/bin/env python3
"""Run the blobpool heuristic simulator and print a summary table.

Usage:
    uv run python -m heuristic_sim.sim
    uv run python -m heuristic_sim.sim --seed 99 --t-end 600
    just sim
"""

from __future__ import annotations

import argparse

from heuristic_sim.config import HeuristicConfig, Scenario
from heuristic_sim.runner import run_simulation

DEFAULT_SCENARIO = Scenario(
    n_honest=30,
    attackers=[
        (3, "spammer", {"rate": 5.0, "below_includability": True}),
        (3, "withholder", {"random_fail_rate": 1.0}),
        (2, "spoofer", {}),
        (2, "free_rider", {}),
        (2, "non_announcer", {}),
        (3, "selective_signaler", {"n_senders": 5, "txs_per_sender": 16}),
    ],
    tx_arrival_rate=2.0,
    t_end=300.0,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Blobpool heuristic simulator")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--t-end", type=float, default=None)
    args = parser.parse_args()

    scenario = DEFAULT_SCENARIO
    if args.t_end is not None:
        scenario = Scenario(
            n_honest=scenario.n_honest,
            attackers=scenario.attackers,
            tx_arrival_rate=scenario.tx_arrival_rate,
            t_end=args.t_end,
            blob_base_fee=scenario.blob_base_fee,
            block_interval=scenario.block_interval,
            inbound_ratio=scenario.inbound_ratio,
        )

    result = run_simulation(HeuristicConfig(), scenario, seed=args.seed)
    print(result.summary_table())


if __name__ == "__main__":
    main()
