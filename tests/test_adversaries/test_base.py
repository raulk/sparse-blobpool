"""Tests for the Adversary base class."""

from sparse_blobpool.adversaries.base import Adversary, AttackConfig
from sparse_blobpool.core.simulator import Simulator
from sparse_blobpool.core.types import ActorId


class ConcreteAdversary(Adversary):
    """Concrete implementation for testing."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.execute_called = False

    def execute(self) -> None:
        self.execute_called = True


class TestAdversaryBase:
    def test_initialization(self) -> None:
        sim = Simulator()
        config = AttackConfig(start_time=1.0, duration=10.0)
        controlled = [ActorId("node1"), ActorId("node2")]

        adversary = ConcreteAdversary(
            actor_id=ActorId("adversary"),
            simulator=sim,
            controlled_nodes=controlled,
            attack_config=config,
        )

        assert adversary.id == ActorId("adversary")
        assert adversary.controlled_nodes == controlled
        assert adversary.attack_config.start_time == 1.0
        assert adversary.attack_config.duration == 10.0

    def test_execute_is_abstract(self) -> None:
        # Verify execute can be called on concrete implementation
        sim = Simulator()
        config = AttackConfig()
        adversary = ConcreteAdversary(
            actor_id=ActorId("adversary"),
            simulator=sim,
            controlled_nodes=[],
            attack_config=config,
        )

        adversary.execute()
        assert adversary.execute_called

    def test_stop_sets_flag(self) -> None:
        sim = Simulator()
        config = AttackConfig()
        adversary = ConcreteAdversary(
            actor_id=ActorId("adversary"),
            simulator=sim,
            controlled_nodes=[],
            attack_config=config,
        )

        assert not adversary._attack_stopped
        adversary.stop()
        assert adversary._attack_stopped


class TestAttackConfig:
    def test_default_values(self) -> None:
        config = AttackConfig()
        assert config.start_time == 0.0
        assert config.duration is None

    def test_custom_values(self) -> None:
        config = AttackConfig(start_time=5.0, duration=30.0)
        assert config.start_time == 5.0
        assert config.duration == 30.0
