#!/usr/bin/env python3
"""Demonstration of the complete attack system with victim selection and tracking."""

import json
from pathlib import Path
from random import Random

from sparse_blobpool.config import SimulationConfig
from sparse_blobpool.fuzzer.config import FuzzerConfig, AttackScenarioConfig, ParameterRanges, AnomalyThresholds
from sparse_blobpool.actors.adversaries.victim_selection import (
    VictimSelectionStrategy,
    VictimSelectionConfig,
    VictimSelector,
)


def demo_victim_selection():
    """Demonstrate the victim selection strategies."""
    print("\n" + "=" * 60)
    print("VICTIM SELECTION STRATEGIES DEMONSTRATION")
    print("=" * 60)

    # Create a mock network topology
    class MockTopology:
        def __init__(self):
            self.graph = {
                "node_0": ["node_1", "node_2", "node_3", "node_4", "node_5"],  # High degree
                "node_1": ["node_0", "node_2"],
                "node_2": ["node_0", "node_1", "node_3"],
                "node_3": ["node_0", "node_2", "node_4"],
                "node_4": ["node_0", "node_3", "node_5"],
                "node_5": ["node_0", "node_4", "node_6"],
                "node_6": ["node_5"],  # Edge node
                "node_7": ["node_8"],  # Isolated pair
                "node_8": ["node_7"],  # Isolated pair
                "node_9": [],  # Completely isolated
            }

        def nodes(self):
            return list(self.graph.keys())

        def degree(self, node):
            return len(self.graph.get(node, []))

        def neighbors(self, node):
            return self.graph.get(node, [])

    class MockSimulator:
        def __init__(self):
            self.rng = Random(42)
            self.topology = MockTopology()
            self.nodes = [{"id": node_id} for node_id in self.topology.nodes()]

    sim = MockSimulator()
    all_node_ids = [node["id"] for node in sim.nodes]

    # Test each strategy
    strategies = [
        VictimSelectionStrategy.RANDOM,
        VictimSelectionStrategy.HIGH_DEGREE,
        VictimSelectionStrategy.LOW_DEGREE,
        VictimSelectionStrategy.EDGE,
        VictimSelectionStrategy.CENTRAL,
    ]

    for strategy in strategies:
        print(f"\n{strategy.value.upper()} Strategy:")
        print("-" * 40)

        config = VictimSelectionConfig(
            strategy=strategy,
            num_victims=3,
        )

        selector = VictimSelector(config, sim, all_node_ids)
        victims = selector.get_victims()
        metadata = {"strategy": strategy.value, "num_victims": len(victims)}

        print(f"Selected victims: {victims}")
        print(f"Metadata: {metadata}")

        # Show node degrees for context
        if victims:
            for victim in victims:
                degree = sim.topology.degree(victim)
                print(f"  - {victim}: degree={degree}")


def demo_attack_configuration():
    """Demonstrate the attack configuration system."""
    print("\n" + "=" * 60)
    print("ATTACK CONFIGURATION DEMONSTRATION")
    print("=" * 60)

    # Create a fuzzer config with attacks enabled
    attack_config = AttackScenarioConfig(
        enable_attacks=True,
        attack_probability=0.7,
        attack_weights={
            "spam_t1_1": 0.3,
            "spam_t1_2": 0.2,
            "withholding": 0.25,
            "poisoning": 0.25,
        }
    )

    print("\nAttack Configuration:")
    print(f"  - Attacks enabled: {attack_config.enable_attacks}")
    print(f"  - Attack probability: {attack_config.attack_probability}")
    print("\nAttack Type Weights:")
    total = sum(attack_config.attack_weights.values())
    for attack_type, weight in attack_config.attack_weights.items():
        normalized = weight / total if total > 0 else 0
        print(f"  - {attack_type}: {weight} ({normalized:.1%})")

    # Simulate attack selection
    rng = Random(42)
    attack_counts = {k: 0 for k in attack_config.attack_weights.keys()}
    baseline_count = 0

    print("\nSimulating 1000 runs:")
    for _ in range(1000):
        if rng.random() < attack_config.attack_probability:
            # Select attack based on weights
            weights = list(attack_config.attack_weights.values())
            types = list(attack_config.attack_weights.keys())
            cumsum = []
            total = 0
            for w in weights:
                total += w
                cumsum.append(total)

            rand = rng.random() * total
            for i, threshold in enumerate(cumsum):
                if rand <= threshold:
                    attack_counts[types[i]] += 1
                    break
        else:
            baseline_count += 1

    print(f"  - Baseline runs: {baseline_count} ({baseline_count/10:.1f}%)")
    for attack_type, count in attack_counts.items():
        print(f"  - {attack_type} runs: {count} ({count/10:.1f}%)")


def demo_metrics_structure():
    """Demonstrate the metrics structure for victim tracking."""
    print("\n" + "=" * 60)
    print("VICTIM METRICS STRUCTURE DEMONSTRATION")
    print("=" * 60)

    # Example metrics that would be collected
    victim_metrics = {
        "victims": ["node_15", "node_42", "node_73"],
        "attack_type": "spam_t1_1",
        "victim_strategy": "HIGH_DEGREE",
        "impacts": {
            "node_15": {
                "spam_txs_received": 156,
                "bandwidth_bytes": 128500,
                "blobpool_pollution": 0.85,
                "connectivity_lost": False,
            },
            "node_42": {
                "spam_txs_received": 143,
                "bandwidth_bytes": 115000,
                "blobpool_pollution": 0.78,
                "connectivity_lost": False,
            },
            "node_73": {
                "spam_txs_received": 189,
                "bandwidth_bytes": 156000,
                "blobpool_pollution": 0.92,
                "connectivity_lost": True,
            },
        },
        "aggregate_metrics": {
            "total_spam_txs": 488,
            "total_bandwidth_impact": 399500,
            "avg_blobpool_pollution": 0.85,
            "nodes_disconnected": 1,
            "collateral_damage": 0.12,  # Impact on non-targeted nodes
        }
    }

    print("\nExample Victim Metrics Structure:")
    print(json.dumps(victim_metrics, indent=2))

    print("\nKey Features:")
    print("  ✓ Individual victim impact tracking")
    print("  ✓ Per-victim bandwidth and pollution metrics")
    print("  ✓ Aggregate attack effectiveness scores")
    print("  ✓ Collateral damage measurement")
    print("  ✓ Attack type and strategy recording")


def demo_fuzzer_output_format():
    """Demonstrate the enhanced fuzzer output format."""
    print("\n" + "=" * 60)
    print("FUZZER OUTPUT FORMAT DEMONSTRATION")
    print("=" * 60)

    # Example of what the enhanced runs.ndjson would contain
    example_run = {
        "run_id": "eagle-tiger-panda",
        "seed": 12345,
        "scenario": "SPAM_T1_1",
        "status": "success_with_anomalies",
        "attack": {
            "type": "spam_t1_1",
            "victim_strategy": "HIGH_DEGREE",
            "victims": ["node_15", "node_42", "node_73"],
            "num_victims": 3,
            "config": {
                "spam_rate": 10.0,
                "valid_headers": True,
                "provide_data": False,
            }
        },
        "metrics": {
            "bandwidth_total_bytes": 512000000,
            "propagation_median_ms": 850,
            "propagation_p99_ms": 2100,
            "reconstruction_success_rate": 0.98,
            "spam_amplification_factor": 2.3,
            "victim_blobpool_pollution": 0.85,
            "withholding_detection_rate": 0.0,
        },
        "anomalies": [
            "High victim blobpool pollution: 0.85 (threshold: 0.5)",
            "Elevated propagation p99: 2100ms (threshold: 1000ms)"
        ],
        "wall_clock_seconds": 4.2,
        "simulated_seconds": 60.0,
        "timestamp_start": "2024-01-15T10:30:00Z",
        "timestamp_end": "2024-01-15T10:30:04Z",
    }

    print("\nExample Fuzzer Output Entry:")
    print(json.dumps(example_run, indent=2))

    print("\nEnhanced Fields for Attack Runs:")
    print("  • attack.type - The type of attack executed")
    print("  • attack.victim_strategy - How victims were selected")
    print("  • attack.victims - List of victim node IDs")
    print("  • attack.config - Attack-specific parameters")
    print("  • metrics.spam_amplification_factor - Attack effectiveness")
    print("  • metrics.victim_blobpool_pollution - Victim impact score")


def main():
    """Run all demonstrations."""
    print("\n" + "=" * 60)
    print("COMPLETE ATTACK SYSTEM DEMONSTRATION")
    print("=" * 60)
    print("\nThis demo showcases the architecture and capabilities")
    print("of the implemented attack system, including:")
    print("  1. Topology-aware victim selection strategies")
    print("  2. Weighted attack scenario configuration")
    print("  3. Per-victim impact metrics")
    print("  4. Enhanced fuzzer output format")

    demo_victim_selection()
    demo_attack_configuration()
    demo_metrics_structure()
    demo_fuzzer_output_format()

    print("\n" + "=" * 60)
    print("KEY CAPABILITIES SUMMARY")
    print("=" * 60)
    print("\n✓ Multiple victim selection strategies (random, degree-based, etc.)")
    print("✓ Configurable attack probabilities and weights")
    print("✓ Per-victim impact tracking and metrics")
    print("✓ Attack scenario registry for easy extension")
    print("✓ Integration with fuzzer for automated testing")
    print("✓ UI visualization of victims and their metrics")
    print("✓ Reproducible attacks via seeded RNG")
    print("\n" + "=" * 60)
    print("DEMONSTRATION COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    main()