"""Tests for the WithholdingAdversary."""

from sparse_blobpool.adversaries.withholding import WithholdingAdversary, WithholdingConfig
from sparse_blobpool.core.simulator import Simulator
from sparse_blobpool.core.types import ActorId


class TestWithholdingAdversary:
    def test_initialization(self) -> None:
        sim = Simulator()
        config = WithholdingConfig(columns_to_serve={0, 1, 2, 3})

        adversary = WithholdingAdversary(
            actor_id=ActorId("withholder"),
            simulator=sim,
            controlled_nodes=[ActorId("node1")],
            attack_config=config,
        )

        assert adversary._withholding_config == config
        # Mask should have bits 0-3 set
        assert adversary._allowed_mask == 0b1111

    def test_compute_allowed_mask(self) -> None:
        sim = Simulator()
        # Columns 0, 5, 10 only
        config = WithholdingConfig(columns_to_serve={0, 5, 10})

        adversary = WithholdingAdversary(
            actor_id=ActorId("withholder"),
            simulator=sim,
            controlled_nodes=[],
            attack_config=config,
        )

        expected_mask = (1 << 0) | (1 << 5) | (1 << 10)
        assert adversary._allowed_mask == expected_mask

    def test_get_withheld_columns(self) -> None:
        sim = Simulator()
        # Only serve columns 0-7
        config = WithholdingConfig(columns_to_serve=set(range(8)))

        adversary = WithholdingAdversary(
            actor_id=ActorId("withholder"),
            simulator=sim,
            controlled_nodes=[],
            attack_config=config,
        )

        # Request columns 0-15
        request_mask = (1 << 16) - 1  # All 16 columns

        withheld = adversary.get_withheld_columns(request_mask)
        expected = set(range(8, 16))  # Columns 8-15 are withheld
        assert withheld == expected

    def test_get_withheld_columns_all_served(self) -> None:
        sim = Simulator()
        config = WithholdingConfig(columns_to_serve=set(range(64)))

        adversary = WithholdingAdversary(
            actor_id=ActorId("withholder"),
            simulator=sim,
            controlled_nodes=[],
            attack_config=config,
        )

        # Request columns 0-31
        request_mask = (1 << 32) - 1

        withheld = adversary.get_withheld_columns(request_mask)
        assert withheld == set()  # Nothing withheld


class TestWithholdingConfig:
    def test_default_values(self) -> None:
        config = WithholdingConfig()
        assert config.columns_to_serve == set(range(64))
        assert config.delay_other_columns is None

    def test_custom_values(self) -> None:
        config = WithholdingConfig(
            columns_to_serve={0, 1, 2},
            delay_other_columns=5.0,
        )
        assert config.columns_to_serve == {0, 1, 2}
        assert config.delay_other_columns == 5.0
