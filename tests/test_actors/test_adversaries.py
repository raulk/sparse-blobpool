"""Tests for adversary actors."""

import pytest

from sparse_blobpool.actors.adversaries import (
    AttackConfig,
    SpamAdversary,
    SpamAttackConfig,
    TargetedPoisoningAdversary,
    TargetedPoisoningConfig,
    WithholdingAdversary,
    WithholdingConfig,
)
from sparse_blobpool.core.simulator import Simulator
from sparse_blobpool.core.types import ActorId


@pytest.fixture
def simulator() -> Simulator:
    return Simulator(seed=42)


class TestSpamAdversary:
    def test_spam_adversary_creation(self, simulator: Simulator) -> None:
        config = SpamAttackConfig(spam_rate=10.0, valid_headers=True)
        adversary = SpamAdversary(
            actor_id=ActorId("spam_attacker"),
            simulator=simulator,
            controlled_nodes=[ActorId("malicious_1")],
            attack_config=config,
            all_nodes=[ActorId("node_1"), ActorId("node_2")],
        )

        assert adversary.id == ActorId("spam_attacker")
        assert adversary.controlled_nodes == [ActorId("malicious_1")]
        assert not adversary._attack_started
        assert not adversary._attack_stopped

    def test_spam_adversary_execute_schedules_spam(self, simulator: Simulator) -> None:
        config = SpamAttackConfig(spam_rate=10.0)
        adversary = SpamAdversary(
            actor_id=ActorId("spam_attacker"),
            simulator=simulator,
            controlled_nodes=[],
            attack_config=config,
            all_nodes=[ActorId("target")],
        )

        initial_event_count = len(simulator._event_queue)
        adversary.execute()
        assert adversary._attack_started
        assert len(simulator._event_queue) > initial_event_count


class TestTargetedPoisoningAdversary:
    def test_poisoning_adversary_creation(self, simulator: Simulator) -> None:
        config = TargetedPoisoningConfig(
            victim_id=ActorId("victim"),
            nonce_chain_length=16,
        )
        adversary = TargetedPoisoningAdversary(
            actor_id=ActorId("poisoner"),
            simulator=simulator,
            controlled_nodes=[ActorId("attacker_1"), ActorId("attacker_2")],
            attack_config=config,
        )

        assert adversary.id == ActorId("poisoner")
        assert adversary.victim_id == ActorId("victim")
        assert adversary._current_nonce == 0

    def test_poisoning_adversary_no_victim_no_start(self, simulator: Simulator) -> None:
        config = TargetedPoisoningConfig(victim_id=None)
        adversary = TargetedPoisoningAdversary(
            actor_id=ActorId("poisoner"),
            simulator=simulator,
            controlled_nodes=[],
            attack_config=config,
        )

        adversary.execute()
        assert not adversary._attack_started

    def test_poisoning_get_attack_progress(self, simulator: Simulator) -> None:
        config = TargetedPoisoningConfig(
            victim_id=ActorId("victim"),
            num_attacker_connections=4,
            nonce_chain_length=16,
        )
        adversary = TargetedPoisoningAdversary(
            actor_id=ActorId("poisoner"),
            simulator=simulator,
            controlled_nodes=[ActorId(f"attacker_{i}") for i in range(6)],
            attack_config=config,
        )

        progress = adversary.get_attack_progress()
        assert progress["nonces_injected"] == 0
        assert progress["target_nonces"] == 16
        assert progress["attacker_nodes"] == 4


class TestWithholdingAdversary:
    def test_withholding_adversary_creation(self, simulator: Simulator) -> None:
        config = WithholdingConfig(columns_to_serve={0, 1, 2, 3})
        adversary = WithholdingAdversary(
            actor_id=ActorId("withholder"),
            simulator=simulator,
            controlled_nodes=[ActorId("malicious")],
            attack_config=config,
        )

        assert adversary.id == ActorId("withholder")
        assert adversary._allowed_mask == 0b1111

    def test_withholding_adversary_get_withheld_columns(self, simulator: Simulator) -> None:
        config = WithholdingConfig(columns_to_serve={0, 2, 4})
        adversary = WithholdingAdversary(
            actor_id=ActorId("withholder"),
            simulator=simulator,
            controlled_nodes=[],
            attack_config=config,
        )

        request_mask = 0b11111  # Columns 0-4
        withheld = adversary.get_withheld_columns(request_mask)
        assert withheld == {1, 3}  # Columns 1 and 3 are withheld


class TestAttackConfig:
    def test_attack_config_defaults(self) -> None:
        config = AttackConfig()
        assert config.start_time == 0.0
        assert config.duration is None

    def test_attack_config_custom_values(self) -> None:
        config = AttackConfig(start_time=10.0, duration=60.0)
        assert config.start_time == 10.0
        assert config.duration == 60.0
