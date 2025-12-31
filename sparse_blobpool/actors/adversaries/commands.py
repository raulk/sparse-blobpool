"""Commands for adversary local events."""

from dataclasses import dataclass

from sparse_blobpool.core.events import Command


@dataclass
class InjectNext(Command):
    """Trigger next poison tx injection in a nonce chain."""


@dataclass
class SpamNext(Command):
    """Trigger next spam tx injection."""
