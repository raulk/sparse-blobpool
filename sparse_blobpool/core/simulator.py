"""Discrete event simulation engine."""

from __future__ import annotations

import heapq
from random import Random
from typing import TYPE_CHECKING, TypeVar

from sparse_blobpool.core.events import Event

if TYPE_CHECKING:
    from sparse_blobpool.actors.block_producer import BlockProducer
    from sparse_blobpool.actors.honest import Node
    from sparse_blobpool.config import SimulationConfig
    from sparse_blobpool.core.actor import Actor
    from sparse_blobpool.core.network import Network
    from sparse_blobpool.core.topology import Topology
    from sparse_blobpool.core.types import ActorId, TxHash
    from sparse_blobpool.metrics.collector import MetricsCollector
    from sparse_blobpool.metrics.results import SimulationResults
    from sparse_blobpool.protocol.commands import Command

ActorT = TypeVar("ActorT", bound="Actor")


class Simulator:
    """Single-threaded, deterministic discrete event simulator.

    Uses a min-heap priority queue for event scheduling and processing.
    All randomness is derived from a seeded RNG for reproducibility.
    """

    def __init__(self, seed: int = 42) -> None:
        self._current_time: float = 0.0
        self._event_queue: list[Event] = []
        self._actors: dict[ActorId, Actor] = {}
        self._rng = Random(seed)
        self._events_processed: int = 0

        self._network: Network | None = None
        self._block_producer: BlockProducer | None = None
        self._topology: Topology | None = None
        self._metrics: MetricsCollector | None = None

    @property
    def current_time(self) -> float:
        return self._current_time

    @property
    def rng(self) -> Random:
        return self._rng

    @property
    def actors(self) -> dict[ActorId, Actor]:
        return self._actors

    def actors_by_type(self, actor_type: type[ActorT]) -> list[ActorT]:
        return [actor for actor in self._actors.values() if isinstance(actor, actor_type)]

    @property
    def events_processed(self) -> int:
        return self._events_processed

    @property
    def nodes(self) -> list[Node]:
        from sparse_blobpool.actors.honest import Node

        return [actor for actor in self._actors.values() if isinstance(actor, Node)]

    @property
    def network(self) -> Network:
        if self._network is None:
            raise RuntimeError("Simulator not configured with network")
        return self._network

    @property
    def block_producer(self) -> BlockProducer:
        if self._block_producer is None:
            raise RuntimeError("Simulator not configured with block_producer")
        return self._block_producer

    @property
    def topology(self) -> Topology:
        if self._topology is None:
            raise RuntimeError("Simulator not configured with topology")
        return self._topology

    @property
    def metrics(self) -> MetricsCollector:
        if self._metrics is None:
            raise RuntimeError("Simulator not configured with metrics")
        return self._metrics

    def finalize_metrics(self) -> SimulationResults:
        return self.metrics.finalize()

    def register_actor(self, actor: Actor) -> None:
        if actor.id in self._actors:
            raise ValueError(f"Actor {actor.id} already registered")
        self._actors[actor.id] = actor

    def schedule(self, event: Event) -> None:
        if event.timestamp < self._current_time:
            raise ValueError(
                f"Cannot schedule event in the past: {event.timestamp} < {self._current_time}"
            )
        heapq.heappush(self._event_queue, event)

    def deliver_command(self, command: Command, target_id: ActorId) -> None:
        """Deliver a command immediately to a target actor."""
        self.schedule(
            Event(
                timestamp=self._current_time,
                priority=0,
                target_id=target_id,
                payload=command,
            )
        )

    def run(self, until: float) -> None:
        while self._event_queue and self._current_time < until:
            event = heapq.heappop(self._event_queue)

            # Don't process events beyond our target time
            if event.timestamp > until:
                # Put it back and stop
                heapq.heappush(self._event_queue, event)
                break

            self._current_time = event.timestamp
            self._dispatch_event(event)
            self._events_processed += 1

    def run_until_empty(self) -> None:
        while self._event_queue:
            event = heapq.heappop(self._event_queue)
            self._current_time = event.timestamp
            self._dispatch_event(event)
            self._events_processed += 1

    def _dispatch_event(self, event: Event) -> None:
        if event.target_id not in self._actors:
            raise RuntimeError(f"Event targeted unknown actor: {event.target_id}")
        actor = self._actors[event.target_id]
        actor.on_event(event.payload)

    def pending_event_count(self) -> int:
        return len(self._event_queue)

    @classmethod
    def build(cls, config: SimulationConfig | None = None) -> Simulator:
        """Build a fully configured simulator.

        Creates all components (Network, Nodes, BlockProducer), establishes peer
        connections based on the configured topology strategy, and registers
        everything with the simulator.
        """
        from sparse_blobpool.actors.block_producer import BlockProducer
        from sparse_blobpool.actors.honest import Node
        from sparse_blobpool.config import SimulationConfig
        from sparse_blobpool.core.network import Network
        from sparse_blobpool.core.topology import build_topology
        from sparse_blobpool.metrics.collector import MetricsCollector

        if config is None:
            config = SimulationConfig()

        simulator = cls(seed=config.seed)
        metrics = MetricsCollector(simulator=simulator)

        network = Network(
            simulator=simulator,
            default_bandwidth=config.default_bandwidth,
            metrics=metrics,
        )

        topology = build_topology(config, simulator.rng)

        nodes: list[Node] = []
        for actor_id, region in topology.regions.items():
            node = Node(
                actor_id=actor_id,
                simulator=simulator,
                config=config,
                custody_columns=config.custody_columns,
                metrics=metrics,
            )
            simulator.register_actor(node)
            nodes.append(node)

            network.register_node(actor_id, region)
            metrics.register_node(actor_id, region)

        node_lookup = {node.id: node for node in nodes}

        for node_a_id, node_b_id in topology.edges:
            node_a = node_lookup.get(node_a_id)
            node_b = node_lookup.get(node_b_id)

            if node_a is not None and node_b is not None:
                node_a.add_peer(node_b_id)
                node_b.add_peer(node_a_id)

        block_producer = BlockProducer(simulator=simulator, config=config)
        simulator.register_actor(block_producer)

        simulator._network = network
        simulator._block_producer = block_producer
        simulator._topology = topology
        simulator._metrics = metrics

        return simulator

    def broadcast_transaction(
        self,
        origin_node: Node | None = None,
        tx_hash: TxHash | None = None,
    ) -> TxHash:
        """Broadcast a transaction into the network via a node."""
        from sparse_blobpool.core.types import Address, TxHash
        from sparse_blobpool.protocol.commands import BroadcastTransaction
        from sparse_blobpool.protocol.constants import ALL_ONES

        if origin_node is None:
            origin_node = self.nodes[0]

        if tx_hash is None:
            rand_bytes = self.rng.randbytes(32)
            tx_hash = TxHash(rand_bytes.hex())

        self.deliver_command(
            BroadcastTransaction(
                tx_hash=tx_hash,
                tx_sender=Address(f"0x{tx_hash[:40]}"),
                nonce=0,
                gas_fee_cap=1000000000,
                gas_tip_cap=100000000,
                blob_gas_price=1000000,
                tx_size=131072,
                blob_count=1,
                cell_mask=ALL_ONES,
            ),
            origin_node.id,
        )

        return tx_hash
