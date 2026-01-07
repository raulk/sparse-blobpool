"""Tests for attack scenarios."""

from sparse_blobpool.actors.adversaries import (
    SpamAdversary,
    TargetedPoisoningAdversary,
    WithholdingAdversary,
)
from sparse_blobpool.config import SimulationConfig
from sparse_blobpool.scenarios import (
    PoisoningScenarioConfig,
    SpamScenarioConfig,
    WithholdingScenarioConfig,
    run_poisoning_scenario,
    run_spam_scenario,
    run_withholding_scenario,
)


class TestSpamScenario:
    def test_creates_spam_adversary(self) -> None:
        config = SimulationConfig(node_count=10, duration=1.0)
        attack_config = SpamScenarioConfig(spam_rate=5.0, num_attacker_nodes=2)

        sim = run_spam_scenario(
            config=config,
            attack_config=attack_config,
            num_transactions=2,
            run_duration=0.5,
        )

        adversaries = sim.actors_by_type(SpamAdversary)
        assert len(adversaries) == 1

        adversary = adversaries[0]
        assert len(adversary.controlled_nodes) == 2

    def test_runs_with_default_config(self) -> None:
        config = SimulationConfig(node_count=10, duration=1.0)

        sim = run_spam_scenario(
            config=config,
            num_transactions=1,
            run_duration=0.2,
        )

        assert sim.events_processed > 0

    def test_t1_1_valid_headers(self) -> None:
        config = SimulationConfig(node_count=10, duration=1.0)
        attack_config = SpamScenarioConfig(
            spam_rate=5.0,
            valid_headers=True,
            provide_data=False,
        )

        sim = run_spam_scenario(
            config=config,
            attack_config=attack_config,
            num_transactions=1,
            run_duration=0.3,
        )

        adversary = sim.actors_by_type(SpamAdversary)[0]
        assert adversary._spam_config.valid_headers is True

    def test_t1_2_invalid_headers(self) -> None:
        config = SimulationConfig(node_count=10, duration=1.0)
        attack_config = SpamScenarioConfig(
            spam_rate=5.0,
            valid_headers=False,
        )

        sim = run_spam_scenario(
            config=config,
            attack_config=attack_config,
            num_transactions=1,
            run_duration=0.3,
        )

        adversary = sim.actors_by_type(SpamAdversary)[0]
        assert adversary._spam_config.valid_headers is False

    def test_targeted_spam(self) -> None:
        config = SimulationConfig(node_count=20, duration=1.0)
        attack_config = SpamScenarioConfig(
            spam_rate=5.0,
            target_fraction=0.25,
        )

        sim = run_spam_scenario(
            config=config,
            attack_config=attack_config,
            num_transactions=1,
            run_duration=0.3,
        )

        adversary = sim.actors_by_type(SpamAdversary)[0]
        assert adversary._spam_config.target_nodes is not None
        assert len(adversary._spam_config.target_nodes) == 5


class TestWithholdingScenario:
    def test_creates_withholding_adversary(self) -> None:
        config = SimulationConfig(node_count=10, duration=1.0)
        attack_config = WithholdingScenarioConfig(
            columns_to_serve=frozenset(range(32)),
            num_attacker_nodes=3,
        )

        sim = run_withholding_scenario(
            config=config,
            attack_config=attack_config,
            num_transactions=2,
            run_duration=0.5,
        )

        adversaries = sim.actors_by_type(WithholdingAdversary)
        assert len(adversaries) == 1

        adversary = adversaries[0]
        assert len(adversary.controlled_nodes) == 3

    def test_runs_with_default_config(self) -> None:
        config = SimulationConfig(node_count=10, duration=1.0)

        sim = run_withholding_scenario(
            config=config,
            num_transactions=1,
            run_duration=0.2,
        )

        assert sim.events_processed > 0

    def test_partial_column_serving(self) -> None:
        config = SimulationConfig(node_count=10, duration=1.0)
        attack_config = WithholdingScenarioConfig(
            columns_to_serve=frozenset(range(16)),
        )

        sim = run_withholding_scenario(
            config=config,
            attack_config=attack_config,
            num_transactions=1,
            run_duration=0.3,
        )

        adversary = sim.actors_by_type(WithholdingAdversary)[0]
        withheld = adversary.get_withheld_columns(0xFFFFFFFFFFFFFFFF)
        assert len(withheld) == 48

    def test_attacker_fraction(self) -> None:
        config = SimulationConfig(node_count=20, duration=1.0)
        attack_config = WithholdingScenarioConfig(
            attacker_fraction=0.1,
        )

        sim = run_withholding_scenario(
            config=config,
            attack_config=attack_config,
            num_transactions=1,
            run_duration=0.2,
        )

        adversary = sim.actors_by_type(WithholdingAdversary)[0]
        assert len(adversary.controlled_nodes) == 2


class TestPoisoningScenario:
    def test_creates_poisoning_adversary(self) -> None:
        config = SimulationConfig(node_count=10, duration=1.0)
        attack_config = PoisoningScenarioConfig(
            num_victims=2,
            nonce_chain_length=8,
        )

        sim = run_poisoning_scenario(
            config=config,
            attack_config=attack_config,
            num_transactions=2,
            run_duration=1.0,
        )

        adversaries = sim.actors_by_type(TargetedPoisoningAdversary)
        assert len(adversaries) == 2

    def test_runs_with_default_config(self) -> None:
        config = SimulationConfig(node_count=10, duration=1.0)

        sim = run_poisoning_scenario(
            config=config,
            num_transactions=1,
            run_duration=0.5,
        )

        assert sim.events_processed > 0

    def test_attack_progress(self) -> None:
        config = SimulationConfig(node_count=10, duration=5.0)
        attack_config = PoisoningScenarioConfig(
            num_victims=1,
            nonce_chain_length=16,
            injection_interval=0.05,
        )

        sim = run_poisoning_scenario(
            config=config,
            attack_config=attack_config,
            num_transactions=1,
            run_duration=2.0,
        )

        adversary = sim.actors_by_type(TargetedPoisoningAdversary)[0]
        progress = adversary.get_attack_progress()
        assert progress["nonces_injected"] == 16
        assert progress["target_nonces"] == 16

    def test_victim_fraction(self) -> None:
        config = SimulationConfig(node_count=20, duration=1.0)
        attack_config = PoisoningScenarioConfig(
            victim_fraction=0.1,
            nonce_chain_length=4,
        )

        sim = run_poisoning_scenario(
            config=config,
            attack_config=attack_config,
            num_transactions=1,
            run_duration=1.0,
        )

        adversaries = sim.actors_by_type(TargetedPoisoningAdversary)
        assert len(adversaries) == 2

    def test_each_adversary_has_unique_victim(self) -> None:
        config = SimulationConfig(node_count=10, duration=1.0)
        attack_config = PoisoningScenarioConfig(
            num_victims=3,
            nonce_chain_length=4,
        )

        sim = run_poisoning_scenario(
            config=config,
            attack_config=attack_config,
            num_transactions=1,
            run_duration=1.0,
        )

        adversaries = sim.actors_by_type(TargetedPoisoningAdversary)
        victims = {a.victim_id for a in adversaries}
        assert len(victims) == 3
