"""Runner for single-node blobpool simulation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from single_node_sim.events import TraceEvent, normalize_event
from single_node_sim.metrics import SingleNodeMetrics
from single_node_sim.node import SingleNode
from single_node_sim.params import PRESETS, HeuristicParams
from sparse_blobpool.core.events import Event
from sparse_blobpool.core.simulator import Simulator
from sparse_blobpool.core.types import ActorId


@dataclass
class SimulationResult:
    """Result of a single-node simulation run."""

    node: SingleNode
    metrics: SingleNodeMetrics
    final_time: float


def normalize_events(events: list[TraceEvent | dict[str, Any]]) -> list[TraceEvent]:
    """Convert mixed events to TraceEvent objects, sorted by timestamp."""
    normalized = [normalize_event(e) for e in events]
    return sorted(normalized, key=lambda e: e.timestamp)


def run(
    events: list[TraceEvent | dict[str, Any]],
    params: HeuristicParams | None = None,
    preset: str | None = None,
) -> SimulationResult:
    """Run a single-node simulation with the given events and parameters.

    Args:
        events: List of trace events (TxAnnouncement, CellsReceived, BlockIncluded)
            or dicts that will be converted to events.
        params: Simulation parameters. If None, uses preset or defaults.
        preset: Name of a preset configuration from PRESETS.

    Returns:
        SimulationResult with the node, metrics, and final simulation time.
    """
    if preset is not None:
        params = PRESETS[preset]
    if params is None:
        params = HeuristicParams()

    sim = Simulator(seed=params.seed)
    metrics = SingleNodeMetrics(sim)
    node = SingleNode(ActorId("node"), sim, params, metrics)
    sim.register_actor(node)

    for event in normalize_events(events):
        sim.schedule(Event(timestamp=event.timestamp, target_id=node.id, payload=event))

    sim.run_until_empty()

    return SimulationResult(node=node, metrics=metrics, final_time=sim.current_time)
