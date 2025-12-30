"""Network topology generation."""

from __future__ import annotations

from hashlib import sha256
from typing import TYPE_CHECKING, NamedTuple

import networkx as nx

if TYPE_CHECKING:
    from random import Random

    from sparse_blobpool.config import Region, SimulationConfig
    from sparse_blobpool.core.types import ActorId


class Topology(NamedTuple):
    """Network topology: region assignments and peer connections."""

    regions: dict[ActorId, Region]
    edges: list[tuple[ActorId, ActorId]]


def build_topology(config: SimulationConfig, rng: Random) -> Topology:
    """Build network topology with region assignments and peer connections."""
    from sparse_blobpool.config import TopologyStrategy

    # Generate node IDs and assign regions
    regions = _assign_regions(config, rng)
    node_ids = list(regions.keys())

    # Generate edges based on strategy
    match config.topology:
        case TopologyStrategy.RANDOM_GRAPH:
            edges = _build_random_graph(node_ids, config.mesh_degree, rng)
        case TopologyStrategy.GEOGRAPHIC_KADEMLIA:
            edges = _build_geographic_kademlia(node_ids, regions, config.mesh_degree, rng)

    return Topology(regions=regions, edges=edges)


def _assign_regions(config: SimulationConfig, rng: Random) -> dict[ActorId, Region]:
    """Assign regions to nodes based on configured distribution."""
    from sparse_blobpool.config import Region
    from sparse_blobpool.core.types import ActorId

    region_list = list(config.region_distribution.keys())
    weights = list(config.region_distribution.values())

    # Normalize weights to cumulative distribution
    total = sum(weights)
    cumulative = []
    acc = 0.0
    for w in weights:
        acc += w / total
        cumulative.append(acc)

    regions: dict[ActorId, Region] = {}
    for i in range(config.node_count):
        actor_id = ActorId(f"node-{i:04d}")
        r = rng.random()
        region = Region.NA  # Default
        for j, threshold in enumerate(cumulative):
            if r <= threshold:
                region = region_list[j]
                break
        regions[actor_id] = region

    return regions


def _build_random_graph(
    node_ids: list[ActorId],
    mesh_degree: int,
    rng: Random,
) -> list[tuple[ActorId, ActorId]]:
    """Build random regular graph using networkx."""
    n = len(node_ids)

    # For random regular graph, n*d must be even
    if (n * mesh_degree) % 2 == 0 and mesh_degree < n:
        try:
            G = nx.random_regular_graph(mesh_degree, n, seed=rng.randint(0, 2**32 - 1))
            return [(node_ids[u], node_ids[v]) for u, v in G.edges()]
        except nx.NetworkXError:
            pass  # Fall back to approximate approach

    # Fallback: create approximate random graph
    edges: set[tuple[ActorId, ActorId]] = set()

    for i, node_id in enumerate(node_ids):
        candidates = [j for j in range(n) if j != i]
        targets = rng.sample(candidates, min(mesh_degree, len(candidates)))

        for j in targets:
            a, b = node_id, node_ids[j]
            edge = (a, b) if a < b else (b, a)
            edges.add(edge)

    return list(edges)


def _build_geographic_kademlia(
    node_ids: list[ActorId],
    regions: dict[ActorId, Region],
    mesh_degree: int,
    rng: Random,
) -> list[tuple[ActorId, ActorId]]:
    """Kademlia-like topology preferring same-region connections."""
    n = len(node_ids)
    if n == 0:
        return []

    # Compute Kademlia IDs
    kad_ids = [_kademlia_id(nid) for nid in node_ids]

    # Group by region
    region_indices: dict[Region, list[int]] = {}
    for i, nid in enumerate(node_ids):
        region_indices.setdefault(regions[nid], []).append(i)

    edges: set[tuple[ActorId, ActorId]] = set()

    for i, node_id in enumerate(node_ids):
        my_kad = kad_ids[i]
        my_region = regions[node_id]

        # Calculate XOR distances
        distances: list[tuple[int, int, int]] = []
        for j in range(n):
            if j == i:
                continue
            xor_dist = my_kad ^ kad_ids[j]
            bucket = xor_dist.bit_length() - 1 if xor_dist > 0 else 0
            distances.append((xor_dist, bucket, j))

        distances.sort()

        selected: set[int] = set()
        buckets_filled: set[int] = set()

        # Phase 1: Fill Kademlia buckets (prefer same region)
        bucket_candidates: dict[int, list[int]] = {}
        for _dist, bucket, j in distances:
            bucket_candidates.setdefault(bucket, []).append(j)

        for bucket in sorted(bucket_candidates.keys()):
            if len(selected) >= mesh_degree:
                break

            candidates = bucket_candidates[bucket]
            same_region = [j for j in candidates if regions[node_ids[j]] == my_region]
            other_region = [j for j in candidates if regions[node_ids[j]] != my_region]

            if same_region and bucket not in buckets_filled:
                selected.add(same_region[0])
                buckets_filled.add(bucket)
            elif other_region and bucket not in buckets_filled:
                selected.add(other_region[0])
                buckets_filled.add(bucket)

        # Phase 2: Fill with same-region peers
        same_region_candidates = [
            j for j in region_indices.get(my_region, []) if j != i and j not in selected
        ]
        rng.shuffle(same_region_candidates)

        for j in same_region_candidates:
            if len(selected) >= mesh_degree:
                break
            selected.add(j)

        # Phase 3: Cross-region if needed
        if len(selected) < mesh_degree:
            other_candidates = [
                j
                for j in range(n)
                if j != i and j not in selected and regions[node_ids[j]] != my_region
            ]
            rng.shuffle(other_candidates)

            for j in other_candidates:
                if len(selected) >= mesh_degree:
                    break
                selected.add(j)

        for j in selected:
            a, b = node_id, node_ids[j]
            edge = (a, b) if a < b else (b, a)
            edges.add(edge)

    return list(edges)


def _kademlia_id(actor_id: ActorId) -> int:
    return int.from_bytes(sha256(actor_id.encode()).digest(), "big")
