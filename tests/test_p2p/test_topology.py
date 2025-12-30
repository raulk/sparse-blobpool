"""Tests for topology generation."""

from random import Random

import pytest

from sparse_blobpool.config import Region, SimulationConfig, TopologyStrategy
from sparse_blobpool.core.topology import Topology, build_topology


def peers_of(topology: Topology, node_id: str) -> list[str]:
    """Get peers for a node from edges list."""
    peers = []
    for a, b in topology.edges:
        if a == node_id:
            peers.append(b)
        elif b == node_id:
            peers.append(a)
    return peers


class TestTopology:
    def test_peers_of_returns_connected_nodes(self) -> None:
        from sparse_blobpool.core.types import ActorId

        regions = {
            ActorId("node-0"): Region.NA,
            ActorId("node-1"): Region.NA,
            ActorId("node-2"): Region.NA,
        }
        edges = [
            (ActorId("node-0"), ActorId("node-1")),
            (ActorId("node-0"), ActorId("node-2")),
        ]
        result = Topology(regions=regions, edges=edges)

        assert set(peers_of(result, ActorId("node-0"))) == {
            ActorId("node-1"),
            ActorId("node-2"),
        }

    def test_peers_of_handles_bidirectional(self) -> None:
        from sparse_blobpool.core.types import ActorId

        regions = {
            ActorId("node-0"): Region.NA,
            ActorId("node-1"): Region.NA,
        }
        edges = [(ActorId("node-0"), ActorId("node-1"))]
        result = Topology(regions=regions, edges=edges)

        # Both directions should work
        assert ActorId("node-1") in peers_of(result, ActorId("node-0"))
        assert ActorId("node-0") in peers_of(result, ActorId("node-1"))

    def test_region_lookup(self) -> None:
        from sparse_blobpool.core.types import ActorId

        regions = {
            ActorId("node-0"): Region.NA,
            ActorId("node-1"): Region.EU,
        }
        result = Topology(regions=regions, edges=[])

        assert result.regions.get(ActorId("node-0")) == Region.NA
        assert result.regions.get(ActorId("node-1")) == Region.EU
        assert result.regions.get(ActorId("unknown")) is None


class TestBuildTopology:
    def test_generates_correct_node_count(self) -> None:
        config = SimulationConfig(node_count=100, mesh_degree=10)
        rng = Random(42)

        result = build_topology(config, rng)

        assert len(result.regions) == 100

    def test_region_distribution_approximately_matches_config(self) -> None:
        config = SimulationConfig(
            node_count=1000,
            mesh_degree=10,
            region_distribution={
                Region.NA: 0.4,
                Region.EU: 0.4,
                Region.AS: 0.2,
            },
        )
        rng = Random(42)

        result = build_topology(config, rng)

        # Count regions
        region_counts = {Region.NA: 0, Region.EU: 0, Region.AS: 0}
        for region in result.regions.values():
            region_counts[region] += 1

        # Check within reasonable tolerance (±5%)
        assert 350 <= region_counts[Region.NA] <= 450
        assert 350 <= region_counts[Region.EU] <= 450
        assert 150 <= region_counts[Region.AS] <= 250

    def test_deterministic_with_same_seed(self) -> None:
        config = SimulationConfig(node_count=50, mesh_degree=5)

        result1 = build_topology(config, Random(42))
        result2 = build_topology(config, Random(42))

        # Same nodes and regions
        assert list(result1.regions.keys()) == list(result2.regions.keys())
        assert list(result1.regions.values()) == list(result2.regions.values())

    def test_different_seeds_produce_different_results(self) -> None:
        config = SimulationConfig(node_count=50, mesh_degree=5)

        result1 = build_topology(config, Random(42))
        result2 = build_topology(config, Random(123))

        # Regions should differ (with high probability)
        regions1 = list(result1.regions.values())
        regions2 = list(result2.regions.values())
        assert regions1 != regions2


class TestRandomGraph:
    def test_edges_respect_mesh_degree(self) -> None:
        config = SimulationConfig(
            node_count=100,
            mesh_degree=10,
            topology=TopologyStrategy.RANDOM_GRAPH,
        )
        rng = Random(42)

        result = build_topology(config, rng)

        # Check average degree is approximately mesh_degree
        degree_counts: dict[str, int] = {}
        for a, b in result.edges:
            degree_counts[a] = degree_counts.get(a, 0) + 1
            degree_counts[b] = degree_counts.get(b, 0) + 1

        avg_degree = sum(degree_counts.values()) / len(degree_counts)
        # Random regular graph should have exactly mesh_degree
        # Allow some tolerance for the approximate fallback
        assert 8 <= avg_degree <= 12

    def test_no_self_loops(self) -> None:
        config = SimulationConfig(
            node_count=50,
            mesh_degree=5,
            topology=TopologyStrategy.RANDOM_GRAPH,
        )
        rng = Random(42)

        result = build_topology(config, rng)

        for a, b in result.edges:
            assert a != b


class TestGeographicKademlia:
    def test_edges_respect_mesh_degree(self) -> None:
        config = SimulationConfig(
            node_count=100,
            mesh_degree=10,
            topology=TopologyStrategy.GEOGRAPHIC_KADEMLIA,
        )
        rng = Random(42)

        result = build_topology(config, rng)

        # Check average degree is approximately mesh_degree
        # In Kademlia, edges are created bidirectionally (A selects B, B selects A)
        # so the actual degree can be up to 2x mesh_degree
        degree_counts: dict[str, int] = {}
        for a, b in result.edges:
            degree_counts[a] = degree_counts.get(a, 0) + 1
            degree_counts[b] = degree_counts.get(b, 0) + 1

        avg_degree = sum(degree_counts.values()) / len(degree_counts)
        # Should be between mesh_degree and 2*mesh_degree
        assert 8 <= avg_degree <= 25

    def test_prefers_same_region_connections(self) -> None:
        config = SimulationConfig(
            node_count=300,
            mesh_degree=20,
            topology=TopologyStrategy.GEOGRAPHIC_KADEMLIA,
            region_distribution={
                Region.NA: 0.34,
                Region.EU: 0.33,
                Region.AS: 0.33,
            },
        )
        rng = Random(42)

        result = build_topology(config, rng)

        # Count same-region vs cross-region edges
        same_region = 0
        cross_region = 0
        for a, b in result.edges:
            if result.regions[a] == result.regions[b]:
                same_region += 1
            else:
                cross_region += 1

        # Geographic Kademlia should have more same-region connections
        # than pure random (which would be ~33% same-region for 3 equal regions)
        same_region_ratio = same_region / (same_region + cross_region)
        assert same_region_ratio > 0.4  # Should prefer same region

    def test_no_self_loops(self) -> None:
        config = SimulationConfig(
            node_count=50,
            mesh_degree=5,
            topology=TopologyStrategy.GEOGRAPHIC_KADEMLIA,
        )
        rng = Random(42)

        result = build_topology(config, rng)

        for a, b in result.edges:
            assert a != b

    def test_handles_empty_graph(self) -> None:
        config = SimulationConfig(
            node_count=0,
            mesh_degree=5,
            topology=TopologyStrategy.GEOGRAPHIC_KADEMLIA,
        )
        rng = Random(42)

        result = build_topology(config, rng)

        assert len(result.regions) == 0
        assert len(result.edges) == 0


class TestLargeScale:
    @pytest.mark.slow
    def test_scales_to_2000_nodes(self) -> None:
        """Verify topology can be built for the target network size."""
        config = SimulationConfig(
            node_count=2000,
            mesh_degree=50,
            topology=TopologyStrategy.GEOGRAPHIC_KADEMLIA,
        )
        rng = Random(42)

        result = build_topology(config, rng)

        assert len(result.regions) == 2000

        # Verify connectivity - each node should have approximately mesh_degree peers
        # In Kademlia, edges are bidirectional so degree can be up to 2x mesh_degree
        degree_counts: dict[str, int] = {}
        for a, b in result.edges:
            degree_counts[a] = degree_counts.get(a, 0) + 1
            degree_counts[b] = degree_counts.get(b, 0) + 1

        min_degree = min(degree_counts.values())
        avg_degree = sum(degree_counts.values()) / len(degree_counts)

        # All nodes should have some connections
        assert min_degree >= 1
        # Average should be between mesh_degree and 2*mesh_degree
        assert 40 <= avg_degree <= 110
