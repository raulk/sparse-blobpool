#!/usr/bin/env python3
"""Test script to run fuzzer with attack scenarios."""

from pathlib import Path

from sparse_blobpool.fuzzer.autopilot_with_attacks import run_fuzzer_with_attacks
from sparse_blobpool.fuzzer.config import FuzzerConfig
from sparse_blobpool.scenarios.attacks.registry import AttackRegistry, AttackScenario, AttackType
from sparse_blobpool.actors.adversaries.victim_selection import VictimSelectionStrategy


def create_test_registry() -> AttackRegistry:
    """Create a test registry with higher attack probabilities."""
    scenarios = [
        AttackScenario(
            attack_type=AttackType.NONE,
            weight=0.2,  # 20% baseline
            description="Baseline scenario with no attacks",
            victim_strategy=VictimSelectionStrategy.RANDOM,
            victim_count_range=(0, 0),
            attacker_count_range=(0, 0),
            attack_params={},
        ),
        AttackScenario(
            attack_type=AttackType.SPAM_T1_1,
            weight=0.3,  # 30% spam with valid headers
            description="Spam attack with valid headers but unavailable data",
            victim_strategy=VictimSelectionStrategy.HIGH_DEGREE,
            victim_count_range=(3, 10),
            attacker_count_range=(1, 2),
            attack_params={
                "spam_rate": (10.0, 30.0),
                "valid_headers": True,
                "provide_data": False,
                "attack_duration": (30.0, 60.0),
            },
        ),
        AttackScenario(
            attack_type=AttackType.SPAM_T1_2,
            weight=0.2,  # 20% spam with invalid data
            description="Spam attack with invalid/nonsense data",
            victim_strategy=VictimSelectionStrategy.RANDOM,
            victim_count_range=(3, 8),
            attacker_count_range=(1, 2),
            attack_params={
                "spam_rate": (5.0, 20.0),
                "valid_headers": False,
                "provide_data": True,
                "attack_duration": (30.0, 60.0),
            },
        ),
        AttackScenario(
            attack_type=AttackType.WITHHOLDING_T2_1,
            weight=0.2,  # 20% column withholding
            description="Selective column withholding attack",
            victim_strategy=VictimSelectionStrategy.EDGE,
            victim_count_range=(2, 6),
            attacker_count_range=(1, 1),
            attack_params={
                "withhold_columns": (2, 8),
            },
        ),
        AttackScenario(
            attack_type=AttackType.POISONING_T4_2,
            weight=0.1,  # 10% availability poisoning
            description="Targeted availability signaling attack",
            victim_strategy=VictimSelectionStrategy.ROLE_BASED,
            victim_count_range=(2, 5),
            attacker_count_range=(1, 2),
            attack_params={
                "nonce_chain_length": (8, 16),
                "injection_interval": (0.05, 0.2),
            },
        ),
    ]
    return AttackRegistry(scenarios)


def main() -> None:
    # Set up fuzzer config for testing
    config = FuzzerConfig(
        output_dir=Path("fuzzer_output"),
        max_runs=20,  # Run just 20 tests
        simulation_duration=60.0,  # Shorter simulations for testing
        trace_on_anomaly_only=False,  # Trace all runs for testing
        master_seed=42,  # Fixed seed for reproducibility
    )

    # Create attack registry with test weights
    registry = create_test_registry()

    print("Starting fuzzer with attack scenarios...")
    print("Attack probability distribution:")
    for weight_type, weight in registry.get_weights_summary().items():
        print(f"  {weight_type.value}: {weight * 100:.0f}%")
    print()

    # Run the fuzzer
    run_fuzzer_with_attacks(config, registry)


if __name__ == "__main__":
    main()
