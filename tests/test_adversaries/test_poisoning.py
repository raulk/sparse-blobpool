"""Tests for the TargetedPoisoningAdversary."""

from sparse_blobpool.adversaries.poisoning import (
    TargetedPoisoningAdversary,
    TargetedPoisoningConfig,
)
from sparse_blobpool.core.simulator import Simulator
from sparse_blobpool.core.types import ActorId, Address


class TestTargetedPoisoningAdversary:
    def test_initialization(self) -> None:
        sim = Simulator()
        config = TargetedPoisoningConfig(
            victim_id=ActorId("victim"),
            num_attacker_connections=4,
            nonce_chain_length=16,
        )

        adversary = TargetedPoisoningAdversary(
            actor_id=ActorId("poisoner"),
            simulator=sim,
            controlled_nodes=[ActorId(f"attacker{i}") for i in range(4)],
            attack_config=config,
        )

        assert adversary.victim_id == ActorId("victim")
        assert adversary._current_nonce == 0
        assert len(adversary._controlled_nodes) == 4

    def test_create_unique_poison_hashes(self) -> None:
        sim = Simulator()
        config = TargetedPoisoningConfig(victim_id=ActorId("victim"))

        adversary = TargetedPoisoningAdversary(
            actor_id=ActorId("poisoner"),
            simulator=sim,
            controlled_nodes=[ActorId("attacker")],
            attack_config=config,
        )

        hashes = set()
        for _ in range(50):
            hash_val = adversary._create_poison_tx()
            adversary._current_nonce += 1
            hashes.add(hash_val)

        # All hashes should be unique
        assert len(hashes) == 50

    def test_get_attack_progress(self) -> None:
        sim = Simulator()
        config = TargetedPoisoningConfig(
            victim_id=ActorId("victim"),
            num_attacker_connections=3,
            nonce_chain_length=10,
        )

        adversary = TargetedPoisoningAdversary(
            actor_id=ActorId("poisoner"),
            simulator=sim,
            controlled_nodes=[ActorId(f"attacker{i}") for i in range(5)],
            attack_config=config,
        )

        # Simulate some progress
        adversary._current_nonce = 5

        progress = adversary.get_attack_progress()
        assert progress["nonces_injected"] == 5
        assert progress["target_nonces"] == 10
        assert progress["attacker_nodes"] == 3  # Limited by config

    def test_victim_id_property(self) -> None:
        sim = Simulator()

        # With victim
        config = TargetedPoisoningConfig(victim_id=ActorId("victim"))
        adversary = TargetedPoisoningAdversary(
            actor_id=ActorId("poisoner"),
            simulator=sim,
            controlled_nodes=[],
            attack_config=config,
        )
        assert adversary.victim_id == ActorId("victim")

        # Without victim
        config2 = TargetedPoisoningConfig(victim_id=None)
        adversary2 = TargetedPoisoningAdversary(
            actor_id=ActorId("poisoner2"),
            simulator=sim,
            controlled_nodes=[],
            attack_config=config2,
        )
        assert adversary2.victim_id is None

    def test_sender_address(self) -> None:
        sim = Simulator()

        # Default sender
        config = TargetedPoisoningConfig(victim_id=ActorId("victim"))
        adversary = TargetedPoisoningAdversary(
            actor_id=ActorId("poisoner"),
            simulator=sim,
            controlled_nodes=[],
            attack_config=config,
        )
        assert "adversary" in adversary._sender

        # Custom sender
        custom_address = Address("0xcustom")
        config2 = TargetedPoisoningConfig(
            victim_id=ActorId("victim"),
            sender_address=custom_address,
        )
        adversary2 = TargetedPoisoningAdversary(
            actor_id=ActorId("poisoner2"),
            simulator=sim,
            controlled_nodes=[],
            attack_config=config2,
        )
        assert adversary2._sender == custom_address


class TestTargetedPoisoningConfig:
    def test_default_values(self) -> None:
        config = TargetedPoisoningConfig()
        assert config.victim_id is None
        assert config.num_attacker_connections == 4
        assert config.nonce_chain_length == 16
        assert config.injection_interval == 0.1
        assert config.sender_address is None

    def test_custom_values(self) -> None:
        config = TargetedPoisoningConfig(
            victim_id=ActorId("victim"),
            num_attacker_connections=8,
            nonce_chain_length=32,
            injection_interval=0.5,
            sender_address=Address("0xtest"),
        )
        assert config.victim_id == ActorId("victim")
        assert config.num_attacker_connections == 8
        assert config.nonce_chain_length == 32
        assert config.injection_interval == 0.5
        assert config.sender_address == Address("0xtest")
