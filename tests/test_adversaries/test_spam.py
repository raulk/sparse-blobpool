"""Tests for the SpamAdversary."""

from sparse_blobpool.adversaries.spam import SpamAdversary, SpamAttackConfig
from sparse_blobpool.core.simulator import Simulator
from sparse_blobpool.core.types import ActorId


class TestSpamAdversary:
    def test_initialization(self) -> None:
        sim = Simulator()
        config = SpamAttackConfig(spam_rate=50.0)
        all_nodes = [ActorId(f"node{i}") for i in range(10)]

        adversary = SpamAdversary(
            actor_id=ActorId("spammer"),
            simulator=sim,
            controlled_nodes=[ActorId("fake_node")],
            attack_config=config,
            all_nodes=all_nodes,
        )

        assert adversary._spam_config.spam_rate == 50.0
        assert len(adversary._all_nodes) == 10
        assert adversary._spam_counter == 0

    def test_generate_unique_hashes(self) -> None:
        sim = Simulator()
        config = SpamAttackConfig()
        adversary = SpamAdversary(
            actor_id=ActorId("spammer"),
            simulator=sim,
            controlled_nodes=[ActorId("fake")],
            attack_config=config,
            all_nodes=[],
        )

        hashes = set()
        for _ in range(100):
            hash_val = adversary._generate_spam_tx_hash()
            adversary._spam_counter += 1
            hashes.add(hash_val)

        # All hashes should be unique
        assert len(hashes) == 100

    def test_select_targets_broadcast(self) -> None:
        sim = Simulator()
        config = SpamAttackConfig(target_nodes=None)  # Broadcast to all
        all_nodes = [ActorId(f"node{i}") for i in range(5)]

        adversary = SpamAdversary(
            actor_id=ActorId("spammer"),
            simulator=sim,
            controlled_nodes=[ActorId("fake")],
            attack_config=config,
            all_nodes=all_nodes,
        )

        targets = adversary._select_targets()
        assert targets == all_nodes

    def test_select_targets_targeted(self) -> None:
        sim = Simulator()
        target_list = [ActorId("victim1"), ActorId("victim2")]
        config = SpamAttackConfig(target_nodes=target_list)
        all_nodes = [ActorId(f"node{i}") for i in range(10)]

        adversary = SpamAdversary(
            actor_id=ActorId("spammer"),
            simulator=sim,
            controlled_nodes=[ActorId("fake")],
            attack_config=config,
            all_nodes=all_nodes,
        )

        targets = adversary._select_targets()
        assert targets == target_list


class TestSpamAttackConfig:
    def test_default_values(self) -> None:
        config = SpamAttackConfig()
        assert config.spam_rate == 10.0
        assert config.valid_headers is True
        assert config.provide_data is False
        assert config.target_nodes is None

    def test_custom_values(self) -> None:
        targets = [ActorId("node1")]
        config = SpamAttackConfig(
            spam_rate=100.0,
            valid_headers=False,
            provide_data=True,
            target_nodes=targets,
        )
        assert config.spam_rate == 100.0
        assert config.valid_headers is False
        assert config.provide_data is True
        assert config.target_nodes == targets
