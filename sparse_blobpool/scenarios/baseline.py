"""Baseline honest network scenario."""

from __future__ import annotations

from sparse_blobpool.config import SimulationConfig
from sparse_blobpool.core.simulator import Simulator


def run_baseline_scenario(
    config: SimulationConfig | None = None,
    num_transactions: int = 10,
    run_duration: float | None = None,
) -> Simulator:
    """Run a baseline honest network scenario."""
    if config is None:
        config = SimulationConfig()

    if run_duration is None:
        run_duration = config.duration

    sim = Simulator.build(config)

    for _ in range(num_transactions):
        origin_idx = sim.rng.randint(0, len(sim.nodes) - 1)
        sim.broadcast_transaction(sim.nodes[origin_idx])

    sim.block_producer.start()
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
        duration=60.0,
    )

    start = time.time()
    sim = Simulator.build(config)
    build_time = time.time() - start
    print(f"Build completed in {build_time:.2f}s")

    min_peers = min(len(node.peers) for node in sim.nodes)
    max_peers = max(len(node.peers) for node in sim.nodes)
    avg_peers = sum(len(node.peers) for node in sim.nodes) / len(sim.nodes)
    print(f"Peer connections: min={min_peers}, avg={avg_peers:.1f}, max={max_peers}")
    print(f"Total edges in topology: {len(sim.topology.edges)}")

    print("\nBroadcasting 10 transactions...")
    tx_hashes = []
    for _ in range(10):
        origin_idx = sim.rng.randint(0, len(sim.nodes) - 1)
        tx_hash = sim.broadcast_transaction(sim.nodes[origin_idx])
        tx_hashes.append(tx_hash)

    sim.block_producer.start()

    print(f"\nRunning simulation for {config.duration}s of simulated time...")
    start = time.time()
    sim.run(config.duration)
    run_time = time.time() - start
    print(f"Simulation completed in {run_time:.2f}s (wall clock)")

    print("\n=== Simulation Statistics ===")
    print(f"Simulated time: {sim.current_time:.1f}s")
    print(f"Events processed: {sim.events_processed}")
    print(f"Messages delivered: {sim.network.messages_delivered}")
    print(f"Total bytes transmitted: {sim.network.total_bytes / 1024 / 1024:.1f} MB")
    print(f"Blocks produced: {sim.block_producer.blocks_produced}")
    print(f"Blobs included: {sim.block_producer.total_blobs_included}")

    print("\n=== Transaction Propagation ===")
    for tx_hash in tx_hashes[:3]:
        nodes_with_tx = sum(1 for node in sim.nodes if node.pool.contains(tx_hash))
        pct = 100 * nodes_with_tx / len(sim.nodes)
        print(f"{tx_hash[:16]}...: {nodes_with_tx}/{len(sim.nodes)} nodes ({pct:.1f}%)")

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

    print("\n=== Exporting to JSON ===")
    json_output = json.dumps(metrics_results.to_dict(), indent=2)
    print(json_output)


if __name__ == "__main__":
    main()
