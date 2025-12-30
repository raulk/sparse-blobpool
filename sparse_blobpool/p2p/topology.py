"""Network topology generation strategies."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import TYPE_CHECKING

import networkx as nx

if TYPE_CHECKING:
    from random import Random

    from ..config import Region, SimulationConfig
    from ..core.types import ActorId


@dataclass
class NodeInfo:
    """Information about a node in the topology."""

    actor_id: ActorId
    region: Region


@dataclass
class TopologyResult:
    """Result of topology generation."""

    nodes: list[NodeInfo]
    edges: list[tuple[ActorId, ActorId]]

    def peers_of(self, node_id: ActorId) -> list[ActorId]:
        """Get the peers of a node."""
        peers = []
        for a, b in self.edges:
            if a == node_id:
                peers.append(b)
            elif b == node_id:
                peers.append(a)
        return peers


def build_topology(config: SimulationConfig, rng: Random) -> TopologyResult:
    """Build a network topology based on configuration.

    Args:
        config: Simulation configuration with topology strategy and parameters.
        rng: Random number generator for reproducibility.

    Returns:
        TopologyResult with nodes and their connections.
    """
    from ..config import TopologyStrategy

    # Generate node IDs and assign regions
    nodes = _generate_nodes(config, rng)

    # Generate edges based on strategy
    match config.topology:
        case TopologyStrategy.RANDOM_GRAPH:
            edges = _build_random_graph(nodes, config.mesh_degree, rng)
        case TopologyStrategy.GEOGRAPHIC_KADEMLIA:
            edges = _build_geographic_kademlia(nodes, config.mesh_degree, rng)

    return TopologyResult(nodes=nodes, edges=edges)


def _generate_nodes(config: SimulationConfig, rng: Random) -> list[NodeInfo]:
    """Generate node IDs and assign regions based on distribution."""
    from ..config import Region
    from ..core.types import ActorId

    nodes: list[NodeInfo] = []

    # Build region assignment based on distribution
    regions = list(config.region_distribution.keys())
    weights = list(config.region_distribution.values())

    # Normalize weights
    total = sum(weights)
    cumulative = []
    acc = 0.0
    for w in weights:
        acc += w / total
        cumulative.append(acc)

    for i in range(config.node_count):
        actor_id = ActorId(f"node-{i:04d}")

        # Assign region based on weighted random selection
        r = rng.random()
        region = Region.NA  # Default
        for j, threshold in enumerate(cumulative):
            if r <= threshold:
                region = regions[j]
                break

        nodes.append(NodeInfo(actor_id=actor_id, region=region))

    return nodes


def _build_random_graph(
    nodes: list[NodeInfo],
    mesh_degree: int,
    rng: Random,
) -> list[tuple[ActorId, ActorId]]:
    """Build a random graph with approximately mesh_degree edges per node.

    Uses networkx random_regular_graph if possible, otherwise falls back
    to a random connection approach.
    """
    n = len(nodes)

    # For random regular graph, n*d must be even
    if (n * mesh_degree) % 2 == 0 and mesh_degree < n:
        try:
            G = nx.random_regular_graph(mesh_degree, n, seed=rng.randint(0, 2**32 - 1))
            return [(nodes[u].actor_id, nodes[v].actor_id) for u, v in G.edges()]
        except nx.NetworkXError:
            pass  # Fall back to approximate approach

    # Fallback: create approximate random graph
    edges: set[tuple[ActorId, ActorId]] = set()
    node_ids = [node.actor_id for node in nodes]

    for i, node in enumerate(nodes):
        # Connect to mesh_degree random nodes
        candidates = [j for j in range(n) if j != i]
        targets = rng.sample(candidates, min(mesh_degree, len(candidates)))

        for j in targets:
            a, b = node.actor_id, node_ids[j]
            # Normalize edge direction for deduplication
            edge = (a, b) if a < b else (b, a)
            edges.add(edge)

    return list(edges)


def _build_geographic_kademlia(
    nodes: list[NodeInfo],
    mesh_degree: int,
    rng: Random,
) -> list[tuple[ActorId, ActorId]]:
    """Build a Kademlia-like topology with geographic affinity.

    Nodes prefer connections to nodes in the same region, while maintaining
    some cross-region connections for global connectivity.

    The algorithm:
    1. Assign each node a Kademlia-style ID (hash of actor_id)
    2. Each node connects to log2(n) nodes in different distance buckets
    3. Prefer same-region peers when multiple candidates exist
    4. Fill remaining slots with random same-region peers
    """
    n = len(nodes)
    if n == 0:
        return []

    # Compute Kademlia IDs for all nodes
    node_kad_ids = [_kademlia_id(node.actor_id) for node in nodes]

    # Group nodes by region
    region_indices: dict[Region, list[int]] = {}
    for i, node in enumerate(nodes):
        region_indices.setdefault(node.region, []).append(i)

    # Build adjacency for each node
    edges: set[tuple[ActorId, ActorId]] = set()

    for i, node in enumerate(nodes):
        my_kad = node_kad_ids[i]
        my_region = node.region

        # Calculate XOR distances to all other nodes
        distances: list[tuple[int, int, int]] = []  # (distance, bucket, node_index)
        for j in range(n):
            if j == i:
                continue
            xor_dist = my_kad ^ node_kad_ids[j]
            bucket = xor_dist.bit_length() - 1 if xor_dist > 0 else 0
            distances.append((xor_dist, bucket, j))

        # Sort by distance
        distances.sort()

        # Select peers using Kademlia buckets + geographic preference
        selected: set[int] = set()
        buckets_filled: set[int] = set()

        # Phase 1: Fill Kademlia buckets (one peer per bucket, prefer same region)
        bucket_candidates: dict[int, list[int]] = {}
        for _dist, bucket, j in distances:
            bucket_candidates.setdefault(bucket, []).append(j)

        for bucket in sorted(bucket_candidates.keys()):
            if len(selected) >= mesh_degree:
                break

            candidates = bucket_candidates[bucket]
            # Sort candidates: same region first
            same_region = [j for j in candidates if nodes[j].region == my_region]
            other_region = [j for j in candidates if nodes[j].region != my_region]

            # Pick one from same region if available, otherwise from other
            if same_region and bucket not in buckets_filled:
                selected.add(same_region[0])
                buckets_filled.add(bucket)
            elif other_region and bucket not in buckets_filled:
                selected.add(other_region[0])
                buckets_filled.add(bucket)

        # Phase 2: Fill remaining slots with same-region peers
        same_region_candidates = [
            j for j in region_indices.get(my_region, []) if j != i and j not in selected
        ]
        rng.shuffle(same_region_candidates)

        for j in same_region_candidates:
            if len(selected) >= mesh_degree:
                break
            selected.add(j)

        # Phase 3: If still not enough, add cross-region peers
        if len(selected) < mesh_degree:
            other_candidates = [
                j for j in range(n) if j != i and j not in selected and nodes[j].region != my_region
            ]
            rng.shuffle(other_candidates)

            for j in other_candidates:
                if len(selected) >= mesh_degree:
                    break
                selected.add(j)

        # Add edges
        for j in selected:
            a, b = node.actor_id, nodes[j].actor_id
            edge = (a, b) if a < b else (b, a)
            edges.add(edge)

    return list(edges)


def _kademlia_id(actor_id: ActorId) -> int:
    """Compute a Kademlia-style 256-bit ID from actor ID."""
    hash_bytes = sha256(actor_id.encode()).digest()
    return int.from_bytes(hash_bytes, "big")
