#!/usr/bin/env python3
"""Test the complete attack integration with the fuzzer."""

from pathlib import Path
from random import Random

from sparse_blobpool.config import SimulationConfig
from sparse_blobpool.fuzzer.config import FuzzerConfig, AttackScenarioConfig
from sparse_blobpool.fuzzer.autopilot_with_attacks import run_fuzzer_with_attacks
from sparse_blobpool.fuzzer.generator import generate_simulation_config
from sparse_blobpool.scenarios.attacks.spam import run_spam_scenario, SpamScenarioConfig
from sparse_blobpool.scenarios.attacks.poisoning import run_poisoning_scenario, PoisoningScenarioConfig
from sparse_blobpool.scenarios.attacks.withholding import run_withholding_scenario, WithholdingScenarioConfig
from sparse_blobpool.actors.adversaries.victim_selection import VictimSelectionStrategy, VictimSelectionConfig


def test_spam_with_victim_selection():
    """Test spam attack with different victim selection strategies."""
    print("\n=== Testing Spam Attack with Victim Selection ===")

    config = SimulationConfig(seed=12345, node_count=100)

    # Test high degree victim selection
    spam_config = SpamScenarioConfig(
        spam_rate=10.0,
        valid_headers=True,
        provide_data=False,
        num_attacker_nodes=1,
        victim_selection_config=VictimSelectionConfig(
            strategy=VictimSelectionStrategy.HIGH_DEGREE,
            num_victims=10,
        )
    )

    print(f"Running spam attack targeting high-degree nodes...")
    sim = run_spam_scenario(config, spam_config, num_transactions=50, run_duration=30.0)
    results = sim.finalize_metrics()

    # Check if victims were tracked
    victim_attacks = sim._metrics.victim_attacks if sim._metrics else {}
    if victim_attacks:
        print(f"✓ Victims tracked: {len(victim_attacks)} nodes targeted")
        for victim_id, attacks in list(victim_attacks.items())[:5]:
            print(f"  - Node {victim_id}: {len(attacks)} attack transactions")
    else:
        print("✗ No victim tracking found")

    print(f"Spam amplification factor: {results.spam_amplification_factor:.2f}")
    print(f"Victim blobpool pollution: {results.victim_blobpool_pollution:.2f}")


def test_poisoning_with_victim_selection():
    """Test poisoning attack with different victim selection strategies."""
    print("\n=== Testing Poisoning Attack with Victim Selection ===")

    config = SimulationConfig(seed=54321, node_count=100)

    # Test central node victim selection
    poison_config = PoisoningScenarioConfig(
        num_attacker_connections=4,
        nonce_chain_length=16,
        injection_interval=0.1,
        victim_selection_config=VictimSelectionConfig(
            strategy=VictimSelectionStrategy.CENTRAL,
            num_victims=5,
        )
    )

    print(f"Running poisoning attack targeting central nodes...")
    sim = run_poisoning_scenario(config, poison_config, num_transactions=50, run_duration=30.0)
    results = sim.finalize_metrics()

    # Check victim tracking
    victim_attacks = sim._metrics.victim_attacks if sim._metrics else {}
    if victim_attacks:
        print(f"✓ Victims tracked: {len(victim_attacks)} nodes poisoned")
        for victim_id, attacks in victim_attacks.items():
            print(f"  - Node {victim_id}: {len(attacks)} poison transactions")
    else:
        print("✗ No victim tracking found")

    print(f"Victim blobpool pollution: {results.victim_blobpool_pollution:.2f}")


def test_withholding_with_victim_selection():
    """Test withholding attack with victim tracking."""
    print("\n=== Testing Withholding Attack with Victim Selection ===")

    config = SimulationConfig(seed=99999, node_count=100)

    # Test edge node victim selection
    withholding_config = WithholdingScenarioConfig(
        columns_to_serve=frozenset(range(64)),  # Only serve first 64 columns
        num_attacker_nodes=10,
        victim_selection_config=VictimSelectionConfig(
            strategy=VictimSelectionStrategy.EDGE,
            num_victims=10,
        )
    )

    print(f"Running withholding attack with edge node victims...")
    sim = run_withholding_scenario(config, withholding_config, num_transactions=50, run_duration=30.0)
    results = sim.finalize_metrics()

    # Check withholding detection
    print(f"Withholding detection rate: {results.withholding_detection_rate:.2f}")

    # Check victim tracking
    victim_attacks = sim._metrics.victim_attacks if sim._metrics else {}
    if victim_attacks:
        print(f"✓ Victims tracked: {len(victim_attacks)} nodes affected by withholding")
    else:
        print("✗ No victim tracking found")


def test_fuzzer_with_attacks():
    """Test the fuzzer with attack integration."""
    print("\n=== Testing Fuzzer with Attack Integration ===")

    output_dir = Path("test_fuzzer_output")
    output_dir.mkdir(exist_ok=True)

    # Configure fuzzer with attacks
    attack_config = AttackScenarioConfig(
        enable_attacks=True,
        attack_probability=0.8,  # High probability for testing
        attack_weights={
            "spam_t1_1": 0.3,
            "spam_t1_2": 0.2,
            "withholding": 0.25,
            "poisoning": 0.25,
        }
    )

    config = FuzzerConfig(
        output_dir=output_dir,
        max_runs=5,  # Just a few runs for testing
        simulation_duration=30.0,
        attack_config=attack_config,
        trace_on_anomaly_only=False,  # Save all traces for inspection
    )

    print("Running fuzzer with attack scenarios...")
    print(f"Attack probability: {attack_config.attack_probability}")
    print(f"Attack weights: {attack_config.attack_weights}")

    # Run the fuzzer
    try:
        run_fuzzer_with_attacks(config)
        print("✓ Fuzzer completed successfully")

        # Check output
        runs_file = output_dir / "runs.ndjson"
        if runs_file.exists():
            import json
            with open(runs_file) as f:
                runs = [json.loads(line) for line in f]

            attack_runs = [r for r in runs if r.get("attack")]
            baseline_runs = [r for r in runs if not r.get("attack")]

            print(f"✓ Total runs: {len(runs)}")
            print(f"  - Attack runs: {len(attack_runs)}")
            print(f"  - Baseline runs: {len(baseline_runs)}")

            # Show attack details
            for run in attack_runs:
                attack = run["attack"]
                print(f"  - {run['run_id']}: {attack['type']} with {len(attack.get('victims', []))} victims")

    except Exception as e:
        print(f"✗ Fuzzer failed: {e}")
        import traceback
        traceback.print_exc()


def main():
    """Run all tests."""
    print("=" * 60)
    print("TESTING COMPLETE ATTACK INTEGRATION")
    print("=" * 60)

    # Test individual attacks with victim selection
    test_spam_with_victim_selection()
    test_poisoning_with_victim_selection()
    test_withholding_with_victim_selection()

    # Test fuzzer integration
    test_fuzzer_with_attacks()

    print("\n" + "=" * 60)
    print("ALL TESTS COMPLETED")
    print("=" * 60)


if __name__ == "__main__":
    main()