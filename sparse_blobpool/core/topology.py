"""Network topology generation with country-based latency model."""

from __future__ import annotations

from collections.abc import Callable
from hashlib import sha256
from typing import TYPE_CHECKING, NamedTuple

import networkx as nx

from sparse_blobpool.core.latency import COUNTRY_WEIGHTS, LATENCY_MODEL, Country, CountryWeights

if TYPE_CHECKING:
    from random import Random

    from sparse_blobpool.config import SimulationConfig
    from sparse_blobpool.core.types import ActorId


type InterconnectionPolicy = Callable[
    [dict[ActorId, Country], int, Random], list[tuple[ActorId, ActorId]]
]


class Topology(NamedTuple):
    """Network topology: country assignments and peer connections."""

    countries: dict[ActorId, Country]
    edges: list[tuple[ActorId, ActorId]]


def build_topology(config: SimulationConfig, rng: Random) -> Topology:
    """Build network topology with country assignments and peer connections."""
    countries = _assign_countries(config.node_count, COUNTRY_WEIGHTS, rng)
    edges = config.interconnection_policy(countries, config.mesh_degree, rng)
    return Topology(countries=countries, edges=edges)


def _assign_countries(
    node_count: int,
    weights: CountryWeights,
    rng: Random,
) -> dict[ActorId, Country]:
    """Assign countries to nodes based on weighted distribution."""
    from sparse_blobpool.core.types import ActorId

    country_list = weights.countries
    probs = weights.normalized()

    # Build cumulative distribution
    cumulative: list[tuple[float, Country]] = []
    running = 0.0
    for country in country_list:
        running += probs[country]
        cumulative.append((running, country))

    assignments: dict[ActorId, Country] = {}
    for i in range(node_count):
        actor_id = ActorId(f"node-{i:04d}")
        r = rng.random()
        for threshold, country in cumulative:
            if r < threshold:
                assignments[actor_id] = country
                break
        else:
            assignments[actor_id] = country_list[-1]

    return assignments


def random_policy(
    assignments: dict[ActorId, Country],
    mesh_degree: int,
    rng: Random,
) -> list[tuple[ActorId, ActorId]]:
    """Each node picks mesh_degree random peers."""
    node_ids = list(assignments.keys())
    n = len(node_ids)

    if (n * mesh_degree) % 2 == 0 and mesh_degree < n:
        try:
            G = nx.random_regular_graph(mesh_degree, n, seed=rng.randint(0, 2**32 - 1))
            return [(node_ids[u], node_ids[v]) for u, v in G.edges()]
        except nx.NetworkXError:
            pass

    edges: set[tuple[ActorId, ActorId]] = set()
    for i, node_id in enumerate(node_ids):
        candidates = [j for j in range(n) if j != i]
        targets = rng.sample(candidates, min(mesh_degree, len(candidates)))
        for j in targets:
            edge = _normalize_edge(node_id, node_ids[j])
            edges.add(edge)

    return list(edges)


def geographic_policy(
    assignments: dict[ActorId, Country],
    mesh_degree: int,
    rng: Random,
) -> list[tuple[ActorId, ActorId]]:
    """Prefer same-country peers, then nearby countries by latency."""
    node_ids = list(assignments.keys())
    n = len(node_ids)
    if n == 0:
        return []

    # Compute Kademlia IDs for bucket distribution
    kad_ids = [_kademlia_id(nid) for nid in node_ids]

    # Group by country
    country_indices: dict[Country, list[int]] = {}
    for i, nid in enumerate(node_ids):
        country_indices.setdefault(assignments[nid], []).append(i)

    edges: set[tuple[ActorId, ActorId]] = set()

    for i, node_id in enumerate(node_ids):
        my_kad = kad_ids[i]
        my_country = assignments[node_id]

        # Calculate XOR distances with latency tiebreaker
        distances: list[tuple[int, float, int]] = []
        for j in range(n):
            if j == i:
                continue
            xor_dist = my_kad ^ kad_ids[j]
            other_country = assignments[node_ids[j]]
            latency = LATENCY_MODEL.get_latency(my_country, other_country).base_ms
            distances.append((xor_dist, latency, j))

        distances.sort()

        selected: set[int] = set()
        buckets_filled: set[int] = set()

        # Phase 1: Fill Kademlia buckets (prefer same country)
        bucket_candidates: dict[int, list[tuple[float, int]]] = {}
        for xor_dist, latency, j in distances:
            bucket = xor_dist.bit_length() - 1 if xor_dist > 0 else 0
            bucket_candidates.setdefault(bucket, []).append((latency, j))

        for bucket in sorted(bucket_candidates.keys()):
            if len(selected) >= mesh_degree:
                break

            candidates = bucket_candidates[bucket]
            same_country = [
                (lat, j) for lat, j in candidates if assignments[node_ids[j]] == my_country
            ]
            other_country = [
                (lat, j) for lat, j in candidates if assignments[node_ids[j]] != my_country
            ]

            if same_country and bucket not in buckets_filled:
                same_country.sort()
                selected.add(same_country[0][1])
                buckets_filled.add(bucket)
            elif other_country and bucket not in buckets_filled:
                other_country.sort()
                selected.add(other_country[0][1])
                buckets_filled.add(bucket)

        # Phase 2: Fill with same-country peers
        same_country_candidates = [
            j for j in country_indices.get(my_country, []) if j != i and j not in selected
        ]
        rng.shuffle(same_country_candidates)

        for j in same_country_candidates:
            if len(selected) >= mesh_degree:
                break
            selected.add(j)

        # Phase 3: Cross-country by latency
        if len(selected) < mesh_degree:
            other_candidates: list[tuple[float, int]] = []
            for j in range(n):
                if j == i or j in selected:
                    continue
                other_country = assignments[node_ids[j]]
                if other_country != my_country:
                    latency = LATENCY_MODEL.get_latency(my_country, other_country).base_ms
                    other_candidates.append((latency, j))

            other_candidates.sort()
            for _, j in other_candidates:
                if len(selected) >= mesh_degree:
                    break
                selected.add(j)

        for j in selected:
            edge = _normalize_edge(node_id, node_ids[j])
            edges.add(edge)

    return list(edges)


def latency_aware_policy(
    assignments: dict[ActorId, Country],
    mesh_degree: int,
    rng: Random,
) -> list[tuple[ActorId, ActorId]]:
    """Connect to lowest-latency peers first for fast propagation."""
    node_ids = list(assignments.keys())
    n = len(node_ids)
    if n == 0:
        return []

    edges: set[tuple[ActorId, ActorId]] = set()

    for i, node_id in enumerate(node_ids):
        my_country = assignments[node_id]

        # Sort all peers by latency (with random tiebreaker)
        candidates: list[tuple[float, float, int]] = []
        for j in range(n):
            if j == i:
                continue
            other_country = assignments[node_ids[j]]
            latency = LATENCY_MODEL.get_latency(my_country, other_country).base_ms
            tiebreaker = rng.random()
            candidates.append((latency, tiebreaker, j))

        candidates.sort()

        # Select mesh_degree lowest-latency peers
        for _, _, j in candidates[:mesh_degree]:
            edge = _normalize_edge(node_id, node_ids[j])
            edges.add(edge)

    return list(edges)


def diverse_policy(
    assignments: dict[ActorId, Country],
    mesh_degree: int,
    rng: Random,
) -> list[tuple[ActorId, ActorId]]:
    """Ensure connections span multiple countries to prevent isolation."""
    node_ids = list(assignments.keys())
    n = len(node_ids)
    if n == 0:
        return []

    # Group by country
    country_indices: dict[Country, list[int]] = {}
    for i, nid in enumerate(node_ids):
        country_indices.setdefault(assignments[nid], []).append(i)

    all_countries = list(country_indices.keys())
    min_countries = min(len(all_countries), max(3, mesh_degree // 4))

    edges: set[tuple[ActorId, ActorId]] = set()

    for i, node_id in enumerate(node_ids):
        my_country = assignments[node_id]
        selected: set[int] = set()
        countries_connected: set[Country] = set()

        # Phase 1: Ensure diversity - connect to at least min_countries different countries
        other_countries = [c for c in all_countries if c != my_country]
        rng.shuffle(other_countries)

        for target_country in other_countries[:min_countries]:
            if len(selected) >= mesh_degree:
                break
            candidates = [
                j for j in country_indices[target_country] if j != i and j not in selected
            ]
            if candidates:
                j = rng.choice(candidates)
                selected.add(j)
                countries_connected.add(target_country)

        # Phase 2: Add same-country peers
        same_country_candidates = [
            j for j in country_indices.get(my_country, []) if j != i and j not in selected
        ]
        rng.shuffle(same_country_candidates)

        slots_for_same = mesh_degree // 3
        for j in same_country_candidates[:slots_for_same]:
            if len(selected) >= mesh_degree:
                break
            selected.add(j)
            countries_connected.add(my_country)

        # Phase 3: Fill remaining randomly
        if len(selected) < mesh_degree:
            remaining_candidates = [j for j in range(n) if j != i and j not in selected]
            rng.shuffle(remaining_candidates)

            for j in remaining_candidates:
                if len(selected) >= mesh_degree:
                    break
                selected.add(j)

        for j in selected:
            edge = _normalize_edge(node_id, node_ids[j])
            edges.add(edge)

    return list(edges)


def _normalize_edge(a: ActorId, b: ActorId) -> tuple[ActorId, ActorId]:
    """Normalize edge to avoid duplicates (smaller ID first)."""
    return (a, b) if a < b else (b, a)


def _kademlia_id(actor_id: ActorId) -> int:
    """Compute Kademlia ID from actor ID."""
    return int.from_bytes(sha256(actor_id.encode()).digest(), "big")


# Standard interconnection policies
RANDOM = random_policy
GEOGRAPHIC = geographic_policy
LATENCY_AWARE = latency_aware_policy
DIVERSE = diverse_policy
