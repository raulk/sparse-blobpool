"""Adversary implementations for attack scenarios."""

from sparse_blobpool.actors.adversaries.base import Adversary, AttackConfig
from sparse_blobpool.actors.adversaries.poisoning import (
    TargetedPoisoningAdversary,
    TargetedPoisoningConfig,
)
from sparse_blobpool.actors.adversaries.spam import SpamAdversary, SpamAttackConfig
from sparse_blobpool.actors.adversaries.withholding import (
    WithholdingAdversary,
    WithholdingConfig,
)

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
