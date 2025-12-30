"""Integration tests for attack scenarios."""

from sparse_blobpool.adversaries.poisoning import TargetedPoisoningConfig
from sparse_blobpool.adversaries.spam import SpamAttackConfig
from sparse_blobpool.config import SimulationConfig
from sparse_blobpool.scenarios.poisoning import run_poisoning_attack
from sparse_blobpool.scenarios.spam_attack import run_spam_attack


class TestSpamAttackScenario:
    def test_spam_attack_runs(self) -> None:
        """Spam attack scenario completes without error."""
        config = SimulationConfig(node_count=20, mesh_degree=4, duration=2.0)
        attack_config = SpamAttackConfig(spam_rate=10.0, start_time=0.5)

        result = run_spam_attack(
            config=config,
            attack_config=attack_config,
            num_honest_transactions=2,
            run_duration=2.0,
        )

        assert result.spam_txs_injected > 0
        assert result.simulator.events_processed > 0

    def test_spam_rate_affects_injection_count(self) -> None:
        """Higher spam rate results in more injected transactions."""
        config = SimulationConfig(node_count=10, mesh_degree=4, duration=2.0)

        # Low rate
        low_config = SpamAttackConfig(spam_rate=5.0, start_time=0.1)
        low_result = run_spam_attack(
            config=config,
            attack_config=low_config,
            num_honest_transactions=1,
        )

        # High rate
        high_config = SpamAttackConfig(spam_rate=20.0, start_time=0.1)
        high_result = run_spam_attack(
            config=config,
            attack_config=high_config,
            num_honest_transactions=1,
        )

        assert high_result.spam_txs_injected > low_result.spam_txs_injected

    def test_spam_generates_network_traffic(self) -> None:
        """Spam attack generates significant network traffic."""
        config = SimulationConfig(node_count=20, mesh_degree=4, duration=3.0)
        attack_config = SpamAttackConfig(spam_rate=20.0, start_time=0.5)

        result = run_spam_attack(
            config=config,
            attack_config=attack_config,
            num_honest_transactions=2,
        )

        # Should generate traffic
        assert result.simulator.network.total_bytes > 0
        assert result.simulator.network.messages_delivered > 0


class TestPoisoningAttackScenario:
    def test_poisoning_attack_runs(self) -> None:
        """Poisoning attack scenario completes without error."""
        config = SimulationConfig(node_count=20, mesh_degree=4, duration=2.0)
        attack_config = TargetedPoisoningConfig(
            num_attacker_connections=2,
            nonce_chain_length=8,
            injection_interval=0.1,
            start_time=0.5,
        )

        result = run_poisoning_attack(
            config=config,
            attack_config=attack_config,
            num_honest_transactions=2,
        )

        assert result.poison_txs_injected > 0
        assert result.victim_node is not None

    def test_nonce_chain_length_affects_injection(self) -> None:
        """Nonce chain length controls number of poison transactions."""
        config = SimulationConfig(node_count=10, mesh_degree=4, duration=3.0)

        # Short chain
        short_config = TargetedPoisoningConfig(
            nonce_chain_length=4,
            injection_interval=0.05,
            start_time=0.1,
        )
        short_result = run_poisoning_attack(
            config=config,
            attack_config=short_config,
            num_honest_transactions=1,
        )

        # Long chain
        long_config = TargetedPoisoningConfig(
            nonce_chain_length=12,
            injection_interval=0.05,
            start_time=0.1,
        )
        long_result = run_poisoning_attack(
            config=config,
            attack_config=long_config,
            num_honest_transactions=1,
        )

        assert short_result.poison_txs_injected <= 4
        assert long_result.poison_txs_injected <= 12
        assert long_result.poison_txs_injected > short_result.poison_txs_injected

    def test_victim_is_selected(self) -> None:
        """Victim node is properly selected and targeted."""
        config = SimulationConfig(node_count=20, mesh_degree=4, duration=2.0)
        attack_config = TargetedPoisoningConfig(
            nonce_chain_length=4,
            start_time=0.1,
        )

        result = run_poisoning_attack(
            config=config,
            attack_config=attack_config,
            num_honest_transactions=1,
        )

        # Victim should be middle node (idx = 10 for 20 nodes)
        assert result.victim_node is not None
        assert result.adversary.victim_id == result.victim_node.id


class TestAttackMetrics:
    def test_metrics_collected_during_spam(self) -> None:
        """Metrics are properly collected during spam attack."""
        config = SimulationConfig(node_count=20, mesh_degree=4, duration=2.0)
        attack_config = SpamAttackConfig(spam_rate=10.0, start_time=0.5)

        result = run_spam_attack(
            config=config,
            attack_config=attack_config,
            num_honest_transactions=2,
        )

        metrics = result.simulator.finalize_metrics()
        assert metrics.total_bandwidth_bytes > 0

    def test_metrics_collected_during_poisoning(self) -> None:
        """Metrics are properly collected during poisoning attack."""
        config = SimulationConfig(node_count=20, mesh_degree=4, duration=2.0)
        attack_config = TargetedPoisoningConfig(
            nonce_chain_length=4,
            start_time=0.1,
        )

        result = run_poisoning_attack(
            config=config,
            attack_config=attack_config,
            num_honest_transactions=2,
        )

        metrics = result.simulator.finalize_metrics()
        assert metrics.total_bandwidth_bytes > 0
