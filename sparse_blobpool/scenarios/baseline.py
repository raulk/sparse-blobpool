"""Baseline honest network scenario.

This module provides the `build_simulator()` factory for creating a fully
configured simulator with:
- Network component for message delivery
- Node actors with P2P connections
- BlockProducer for slot-based block production
"""

from __future__ import annotations

from sparse_blobpool.actors.block_producer import BlockProducer
from sparse_blobpool.config import SimulationConfig
from sparse_blobpool.core.network import Network
from sparse_blobpool.core.simulator import Event, Simulator
from sparse_blobpool.core.types import Address, TxHash
from sparse_blobpool.metrics.collector import MetricsCollector
from sparse_blobpool.p2p.node import Node
from sparse_blobpool.p2p.topology import build_topology
from sparse_blobpool.protocol.constants import ALL_ONES
from sparse_blobpool.protocol.messages import BroadcastTransaction


def build_simulator(config: SimulationConfig | None = None) -> Simulator:
    """Build a fully configured simulator.

    Creates all components (Network, Nodes, BlockProducer), establishes peer
    connections based on the configured topology strategy, and registers
    everything with the simulator.

    Args:
        config: Simulation configuration. Uses defaults if not provided.

    Returns:
        Configured Simulator with all actors registered.
    """
    if config is None:
        config = SimulationConfig()

    # Create simulator with seeded RNG
    simulator = Simulator(seed=config.seed)

    # Create metrics collector
    metrics = MetricsCollector(simulator=simulator)

    # Create Network component (not an actor - set on simulator later)
    network = Network(
        simulator=simulator,
        default_bandwidth=config.default_bandwidth,
        metrics=metrics,
    )

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
            metrics=metrics,
        )
        simulator.register_actor(node)
        nodes.append(node)

        # Register node with network and metrics for region tracking
        network.register_node(node_info.actor_id, node_info.region)
        metrics.register_node(node_info.actor_id, node_info.region)

    # Build node lookup for peer connections
    node_lookup = {node.id: node for node in nodes}

    # Establish peer connections
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
    sim: Simulator,
    origin_node: Node | None = None,
    tx_hash: TxHash | None = None,
) -> TxHash:
    """Broadcast a transaction into the network via a node.

    Schedules a BroadcastTransaction event to the origin node, which will
    add the tx to its pool and announce to all peers.

    Args:
        sim: The configured simulator.
        origin_node: Node to broadcast from. Uses first node if not specified.
        tx_hash: Transaction hash. Generates random if not specified.

    Returns:
        The transaction hash that was broadcast.
    """
    if origin_node is None:
        origin_node = sim.nodes[0]

    if tx_hash is None:
        rand_bytes = sim.rng.randbytes(32)
        tx_hash = TxHash(rand_bytes.hex())

    # Schedule immediate event to the origin node
    event = Event(
        timestamp=sim.current_time,
        target_id=origin_node.id,
        payload=BroadcastTransaction(
            sender=origin_node.id,
            tx_hash=tx_hash,
            tx_sender=Address(f"0x{tx_hash[:40]}"),  # Derive fake sender from hash
            nonce=0,
            gas_fee_cap=1000000000,  # 1 Gwei
            gas_tip_cap=100000000,  # 0.1 Gwei
            blob_gas_price=1000000,  # 1 wei
            tx_size=131072,  # Standard blob tx size
            blob_count=1,
            cell_mask=ALL_ONES,  # Origin has full blob
        ),
    )
    sim.schedule(event)

    return tx_hash


def run_baseline_scenario(
    config: SimulationConfig | None = None,
    num_transactions: int = 10,
    run_duration: float | None = None,
) -> Simulator:
    """Run a baseline honest network scenario.

    Creates the simulation, injects transactions, starts block production,
    and runs for the specified duration.

    Args:
        config: Simulation configuration. Uses defaults if not provided.
        num_transactions: Number of transactions to inject initially.
        run_duration: How long to run. Uses config.duration if not specified.

    Returns:
        Simulator after running.
    """
    if config is None:
        config = SimulationConfig()

    if run_duration is None:
        run_duration = config.duration

    sim = build_simulator(config)

    # Broadcast initial transactions from random nodes
    for _ in range(num_transactions):
        origin_idx = sim.rng.randint(0, len(sim.nodes) - 1)
        origin_node = sim.nodes[origin_idx]
        broadcast_transaction(sim, origin_node)

    # Start block production
    sim.block_producer.start()

    # Run simulation
    sim.run(run_duration)

    return sim


def main() -> None:
    """Run baseline scenario and print summary statistics."""
    import json
    import time

    print("Building simulation with 2000 nodes...")
    config = SimulationConfig(
        node_count=2000,
        mesh_degree=50,
        duration=60.0,  # Run for 60 seconds of simulated time
    )

    start = time.time()
    sim = build_simulator(config)
    build_time = time.time() - start
    print(f"Build completed in {build_time:.2f}s")

    # Check connectivity
    min_peers = min(len(node.peers) for node in sim.nodes)
    max_peers = max(len(node.peers) for node in sim.nodes)
    avg_peers = sum(len(node.peers) for node in sim.nodes) / len(sim.nodes)
    print(f"Peer connections: min={min_peers}, avg={avg_peers:.1f}, max={max_peers}")

    # Count edges
    print(f"Total edges in topology: {len(sim.topology.edges)}")

    # Broadcast 10 transactions
    print("\nBroadcasting 10 transactions...")
    tx_hashes = []
    for _ in range(10):
        origin_idx = sim.rng.randint(0, len(sim.nodes) - 1)
        tx_hash = broadcast_transaction(sim, sim.nodes[origin_idx])
        tx_hashes.append(tx_hash)

    # Start block production
    sim.block_producer.start()

    # Run simulation
    print(f"\nRunning simulation for {config.duration}s of simulated time...")
    start = time.time()
    sim.run(config.duration)
    run_time = time.time() - start
    print(f"Simulation completed in {run_time:.2f}s (wall clock)")

    # Print statistics
    print("\n=== Simulation Statistics ===")
    print(f"Simulated time: {sim.current_time:.1f}s")
    print(f"Events processed: {sim.events_processed}")
    print(f"Messages delivered: {sim.network.messages_delivered}")
    print(f"Total bytes transmitted: {sim.network.total_bytes / 1024 / 1024:.1f} MB")
    print(f"Blocks produced: {sim.block_producer.blocks_produced}")
    print(f"Blobs included: {sim.block_producer.total_blobs_included}")

    # Check propagation - count how many nodes have each tx in their pool
    print("\n=== Transaction Propagation ===")
    for tx_hash in tx_hashes[:3]:  # Just show first 3
        nodes_with_tx = sum(1 for node in sim.nodes if node.pool.contains(tx_hash))
        pct = 100 * nodes_with_tx / len(sim.nodes)
        print(f"{tx_hash[:16]}...: {nodes_with_tx}/{len(sim.nodes)} nodes ({pct:.1f}%)")

    # Finalize and print metrics
    print("\n=== Metrics Analysis ===")
    metrics_results = sim.finalize_metrics()
    print(f"Total bandwidth: {metrics_results.total_bandwidth_bytes / 1024 / 1024:.1f} MB")
    print(f"Bandwidth per blob: {metrics_results.bandwidth_per_blob / 1024:.1f} KB")
    print(f"Bandwidth reduction vs full: {metrics_results.bandwidth_reduction_vs_full:.2f}x")
    print(f"Median propagation time: {metrics_results.median_propagation_time:.3f}s")
    print(f"P99 propagation time: {metrics_results.p99_propagation_time:.3f}s")
    print(f"Propagation success rate: {metrics_results.propagation_success_rate * 100:.1f}%")
    print(f"Observed provider ratio: {metrics_results.observed_provider_ratio:.3f}")
    print(f"Reconstruction success rate: {metrics_results.reconstruction_success_rate * 100:.1f}%")

    # Export to JSON
    print("\n=== Exporting to JSON ===")
    json_output = json.dumps(metrics_results.to_dict(), indent=2)
    print(json_output)


if __name__ == "__main__":
    main()
