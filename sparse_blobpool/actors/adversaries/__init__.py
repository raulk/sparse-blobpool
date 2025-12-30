"""Adversary implementations for attack scenarios."""

from .base import Adversary, AttackConfig
from .poisoning import TargetedPoisoningAdversary, TargetedPoisoningConfig
from .spam import SpamAdversary, SpamAttackConfig
from .withholding import WithholdingAdversary, WithholdingConfig

__all__ = [
    "Adversary",
    "AttackConfig",
    "SpamAdversary",
    "SpamAttackConfig",
    "TargetedPoisoningAdversary",
    "TargetedPoisoningConfig",
    "WithholdingAdversary",
    "WithholdingConfig",
]
