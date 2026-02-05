from enum import Enum, auto


class AvailabilityMode(Enum):
    INSTANT = auto()
    SIMULATED_PARTIAL = auto()
    TRACE_DRIVEN = auto()
