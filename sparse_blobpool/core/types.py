"""Core type aliases for the simulation."""

from typing import NewType

# Actor identification - unique string identifier for each actor in the simulation
ActorId = NewType("ActorId", str)

# Transaction hash - 32-byte hash represented as hex string
TxHash = NewType("TxHash", str)

# Ethereum address - 20-byte address represented as hex string
Address = NewType("Address", str)

# Request ID for matching request/response pairs
RequestId = NewType("RequestId", int)
