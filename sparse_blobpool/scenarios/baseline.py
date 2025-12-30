"""Baseline honest network scenario.

This module provides the `build_simulation()` factory for creating a fully
configured simulation with:
- Network actor for message delivery
- Node actors with P2P connections
- BlockProducer for slot-based block production
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..config import SimulationConfig
from ..core.block_producer import BlockProducer, SlotConfig
from ..core.network import Network
from ..core.simulator import Simulator
from ..core.types import Address, TxHash
from ..p2p.node import Node
from ..p2p.topology import build_topology
from ..pool.blobpool import BlobTxEntry
from ..protocol.constants import ALL_ONES
from ..protocol.messages import NewPooledTransactionHashes

if TYPE_CHECKING:
    from ..p2p.topology import TopologyResult


@dataclass
class SimulationResult:
    """Results from running the simulation."""

    simulator: Simulator
    nodes: list[Node]
    network: Network
    block_producer: BlockProducer
    topology: TopologyResult


def build_simulation(config: SimulationConfig | None = None) -> SimulationResult:
    """Build a fully configured simulation.

    Creates all actors (Network, Nodes, BlockProducer), establishes peer
    connections based on the configured topology strategy, and registers
    everything with the simulator.

    Args:
        config: Simulation configuration. Uses defaults if not provided.

    Returns:
        SimulationResult containing the simulator and all actors.
    """
    if config is None:
        config = SimulationConfig()

    # Create simulator with seeded RNG
    simulator = Simulator(seed=config.seed)

    # Create and register Network actor
    network = Network(
        simulator=simulator,
        default_bandwidth=config.default_bandwidth,
    )
    simulator.register_actor(network)

    # Build topology
    topology = build_topology(config, simulator.rng)

    # Create and register Node actors
    nodes: list[Node] = []
    for node_info in topology.nodes:
        node = Node(
            actor_id=node_info.actor_id,
            simulator=simulator,
            config=config,
            custody_columns=config.custody_columns,
        )
        simulator.register_actor(node)
        nodes.append(node)

        # Register node with network for latency calculations
        network.register_node(node_info.actor_id, node_info.region)

    # Establish peer connections
    for node_a_id, node_b_id in topology.edges:
        node_a = simulator.actors[node_a_id]
        node_b = simulator.actors[node_b_id]

        if isinstance(node_a, Node) and isinstance(node_b, Node):
            node_a.add_peer(node_b_id)
            node_b.add_peer(node_a_id)

    # Create and register BlockProducer
    block_producer = BlockProducer(
        simulator=simulator,
        slot_config=SlotConfig(slot_duration=12.0, max_blobs_per_block=6),
    )
    simulator.register_actor(block_producer)

    # Register all nodes with BlockProducer for proposer selection
    block_producer.register_nodes([node.id for node in nodes])

    return SimulationResult(
        simulator=simulator,
        nodes=nodes,
        network=network,
        block_producer=block_producer,
        topology=topology,
    )


def inject_transaction(
    result: SimulationResult,
    origin_node: Node | None = None,
    tx_hash: TxHash | None = None,
) -> TxHash:
    """Inject a transaction into the network via a node.

    The transaction is first added to the origin node's pool, then
    announced to all peers. This allows peers to request the tx back.

    Args:
        result: The simulation result containing all actors.
        origin_node: Node to inject from. Uses first node if not specified.
        tx_hash: Transaction hash. Generates random if not specified.

    Returns:
        The transaction hash that was injected.
    """
    if origin_node is None:
        origin_node = result.nodes[0]

    if tx_hash is None:
        # Generate a random tx hash
        rand_bytes = result.simulator.rng.randbytes(32)
        tx_hash = TxHash(rand_bytes.hex())

    # Create and add transaction to origin node's pool
    entry = BlobTxEntry(
        tx_hash=tx_hash,
        sender=Address(f"0x{tx_hash[:40]}"),  # Derive fake sender from hash
        nonce=0,
        gas_fee_cap=1000000000,  # 1 Gwei
        gas_tip_cap=100000000,  # 0.1 Gwei
        blob_gas_price=1000000,  # 1 wei
        tx_size=131072,  # Standard blob tx size
        blob_count=1,
        cell_mask=ALL_ONES,  # Origin has full blob
        received_at=result.simulator.current_time,
    )
    origin_node.pool.add(entry)

    # Announce to all peers as a provider (ALL_ONES cell mask)
    for peer_id in origin_node.peers:
        msg = NewPooledTransactionHashes(
            sender=origin_node.id,
            types=bytes([3]),  # Type 3 = blob transaction
            sizes=[entry.tx_size],
            hashes=[tx_hash],
            cell_mask=ALL_ONES,
        )
        origin_node.send(msg, peer_id)
        entry.announced_to.add(peer_id)

    return tx_hash


def run_baseline_scenario(
    config: SimulationConfig | None = None,
    num_transactions: int = 10,
    run_duration: float | None = None,
) -> SimulationResult:
    """Run a baseline honest network scenario.

    Creates the simulation, injects transactions, starts block production,
    and runs for the specified duration.

    Args:
        config: Simulation configuration. Uses defaults if not provided.
        num_transactions: Number of transactions to inject initially.
        run_duration: How long to run. Uses config.duration if not specified.

    Returns:
        SimulationResult after running the simulation.
    """
    if config is None:
        config = SimulationConfig()

    if run_duration is None:
        run_duration = config.duration

    result = build_simulation(config)

    # Inject initial transactions from random nodes
    for _ in range(num_transactions):
        origin_idx = result.simulator.rng.randint(0, len(result.nodes) - 1)
        origin_node = result.nodes[origin_idx]
        inject_transaction(result, origin_node)

    # Start block production
    result.block_producer.start()

    # Run simulation
    result.simulator.run(run_duration)

    return result


def main() -> None:
    """Run baseline scenario and print summary statistics."""
    import time

    print("Building simulation with 2000 nodes...")
    config = SimulationConfig(
        node_count=2000,
        mesh_degree=50,
        duration=60.0,  # Run for 60 seconds of simulated time
    )

    start = time.time()
    result = build_simulation(config)
    build_time = time.time() - start
    print(f"Build completed in {build_time:.2f}s")

    # Check connectivity
    min_peers = min(len(node.peers) for node in result.nodes)
    max_peers = max(len(node.peers) for node in result.nodes)
    avg_peers = sum(len(node.peers) for node in result.nodes) / len(result.nodes)
    print(f"Peer connections: min={min_peers}, avg={avg_peers:.1f}, max={max_peers}")

    # Count edges
    print(f"Total edges in topology: {len(result.topology.edges)}")

    # Inject 10 transactions
    print("\nInjecting 10 transactions...")
    tx_hashes = []
    for _ in range(10):
        origin_idx = result.simulator.rng.randint(0, len(result.nodes) - 1)
        tx_hash = inject_transaction(result, result.nodes[origin_idx])
        tx_hashes.append(tx_hash)

    # Start block production
    result.block_producer.start()

    # Run simulation
    print(f"\nRunning simulation for {config.duration}s of simulated time...")
    start = time.time()
    result.simulator.run(config.duration)
    run_time = time.time() - start
    print(f"Simulation completed in {run_time:.2f}s (wall clock)")

    # Print statistics
    print("\n=== Simulation Statistics ===")
    print(f"Simulated time: {result.simulator.current_time:.1f}s")
    print(f"Events processed: {result.simulator.events_processed}")
    print(f"Messages delivered: {result.network.messages_delivered}")
    print(f"Total bytes transmitted: {result.network.total_bytes / 1024 / 1024:.1f} MB")
    print(f"Blocks produced: {result.block_producer.blocks_produced}")
    print(f"Blobs included: {result.block_producer.total_blobs_included}")

    # Check propagation - count how many nodes have each tx in their pool
    print("\n=== Transaction Propagation ===")
    for tx_hash in tx_hashes[:3]:  # Just show first 3
        nodes_with_tx = sum(1 for node in result.nodes if node.pool.contains(tx_hash))
        pct = 100 * nodes_with_tx / len(result.nodes)
        print(f"{tx_hash[:16]}...: {nodes_with_tx}/{len(result.nodes)} nodes ({pct:.1f}%)")


if __name__ == "__main__":
    main()
