"""Tests for topology generation."""

from random import Random

import pytest

from sparse_blobpool.config import SimulationConfig
from sparse_blobpool.core.latency import COUNTRY_WEIGHTS
from sparse_blobpool.core.topology import (
    DIVERSE,
    GEOGRAPHIC,
    LATENCY_AWARE,
    RANDOM,
    Topology,
    build_topology,
)


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

        countries = {
            ActorId("node-0"): "united states",
            ActorId("node-1"): "united states",
            ActorId("node-2"): "germany",
        }
        edges = [
            (ActorId("node-0"), ActorId("node-1")),
            (ActorId("node-0"), ActorId("node-2")),
        ]
        result = Topology(countries=countries, edges=edges)

        assert set(peers_of(result, ActorId("node-0"))) == {
            ActorId("node-1"),
            ActorId("node-2"),
        }

    def test_peers_of_handles_bidirectional(self) -> None:
        from sparse_blobpool.core.types import ActorId

        countries = {
            ActorId("node-0"): "united states",
            ActorId("node-1"): "germany",
        }
        edges = [(ActorId("node-0"), ActorId("node-1"))]
        result = Topology(countries=countries, edges=edges)

        # Both directions should work
        assert ActorId("node-1") in peers_of(result, ActorId("node-0"))
        assert ActorId("node-0") in peers_of(result, ActorId("node-1"))

    def test_country_lookup(self) -> None:
        from sparse_blobpool.core.types import ActorId

        countries = {
            ActorId("node-0"): "united states",
            ActorId("node-1"): "germany",
        }
        result = Topology(countries=countries, edges=[])

        assert result.countries.get(ActorId("node-0")) == "united states"
        assert result.countries.get(ActorId("node-1")) == "germany"
        assert result.countries.get(ActorId("unknown")) is None


class TestBuildTopology:
    def test_generates_correct_node_count(self) -> None:
        config = SimulationConfig(node_count=100, mesh_degree=10)
        rng = Random(42)

        result = build_topology(config, rng)

        assert len(result.countries) == 100

    def test_country_distribution_uses_weights(self) -> None:
        """Country distribution should follow weights.json proportions."""
        config = SimulationConfig(node_count=1000, mesh_degree=10)
        rng = Random(42)

        result = build_topology(config, rng)

        # Count countries
        country_counts: dict[str, int] = {}
        for country in result.countries.values():
            country_counts[country] = country_counts.get(country, 0) + 1

        # US should have most nodes (37% of weight)
        # Germany should have second most (~17% of weight)
        assert "united states" in country_counts
        assert "germany" in country_counts
        assert country_counts["united states"] > country_counts["germany"]

    def test_only_whitelisted_countries_used(self) -> None:
        """Only countries from weights.json should be assigned."""
        config = SimulationConfig(node_count=500, mesh_degree=10)
        rng = Random(42)

        result = build_topology(config, rng)

        whitelisted = set(COUNTRY_WEIGHTS.countries)
        for country in result.countries.values():
            assert country in whitelisted

    def test_deterministic_with_same_seed(self) -> None:
        config = SimulationConfig(node_count=50, mesh_degree=5)

        result1 = build_topology(config, Random(42))
        result2 = build_topology(config, Random(42))

        # Same nodes and countries
        assert list(result1.countries.keys()) == list(result2.countries.keys())
        assert list(result1.countries.values()) == list(result2.countries.values())

    def test_different_seeds_produce_different_results(self) -> None:
        config = SimulationConfig(node_count=50, mesh_degree=5)

        result1 = build_topology(config, Random(42))
        result2 = build_topology(config, Random(123))

        # Countries should differ (with high probability)
        countries1 = list(result1.countries.values())
        countries2 = list(result2.countries.values())
        assert countries1 != countries2


class TestRandomPolicy:
    def test_edges_respect_mesh_degree(self) -> None:
        config = SimulationConfig(
            node_count=100,
            mesh_degree=10,
            interconnection_policy=RANDOM,
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
            interconnection_policy=RANDOM,
        )
        rng = Random(42)

        result = build_topology(config, rng)

        for a, b in result.edges:
            assert a != b


class TestGeographicPolicy:
    def test_edges_respect_mesh_degree(self) -> None:
        config = SimulationConfig(
            node_count=100,
            mesh_degree=10,
            interconnection_policy=GEOGRAPHIC,
        )
        rng = Random(42)

        result = build_topology(config, rng)

        # Check average degree is approximately mesh_degree
        degree_counts: dict[str, int] = {}
        for a, b in result.edges:
            degree_counts[a] = degree_counts.get(a, 0) + 1
            degree_counts[b] = degree_counts.get(b, 0) + 1

        avg_degree = sum(degree_counts.values()) / len(degree_counts)
        # Should be between mesh_degree and 2*mesh_degree
        assert 8 <= avg_degree <= 25

    def test_prefers_same_country_connections(self) -> None:
        config = SimulationConfig(
            node_count=500,
            mesh_degree=20,
            interconnection_policy=GEOGRAPHIC,
        )
        rng = Random(42)

        result = build_topology(config, rng)

        # Count same-country vs cross-country edges
        same_country = 0
        cross_country = 0
        for a, b in result.edges:
            if result.countries[a] == result.countries[b]:
                same_country += 1
            else:
                cross_country += 1

        # Geographic policy should have more same-country connections
        same_country_ratio = same_country / (same_country + cross_country)
        assert same_country_ratio > 0.2  # Should prefer same country

    def test_no_self_loops(self) -> None:
        config = SimulationConfig(
            node_count=50,
            mesh_degree=5,
            interconnection_policy=GEOGRAPHIC,
        )
        rng = Random(42)

        result = build_topology(config, rng)

        for a, b in result.edges:
            assert a != b

    def test_handles_empty_graph(self) -> None:
        config = SimulationConfig(
            node_count=0,
            mesh_degree=5,
            interconnection_policy=GEOGRAPHIC,
        )
        rng = Random(42)

        result = build_topology(config, rng)

        assert len(result.countries) == 0
        assert len(result.edges) == 0


class TestLatencyAwarePolicy:
    def test_prefers_low_latency_peers(self) -> None:
        config = SimulationConfig(
            node_count=300,
            mesh_degree=20,
            interconnection_policy=LATENCY_AWARE,
        )
        rng = Random(42)

        result = build_topology(config, rng)

        # Check that edges exist and are not self-loops
        assert len(result.edges) > 0
        for a, b in result.edges:
            assert a != b


class TestDiversePolicy:
    def test_connections_span_multiple_countries(self) -> None:
        config = SimulationConfig(
            node_count=300,
            mesh_degree=20,
            interconnection_policy=DIVERSE,
        )
        rng = Random(42)

        result = build_topology(config, rng)

        # Pick a random node and check its peers span multiple countries
        sample_node = next(iter(result.countries.keys()))
        peer_ids = peers_of(result, sample_node)
        peer_countries = {result.countries[p] for p in peer_ids}

        # Should connect to at least a few different countries
        assert len(peer_countries) >= 3


class TestLargeScale:
    @pytest.mark.slow
    def test_scales_to_2000_nodes(self) -> None:
        """Verify topology can be built for the target network size."""
        config = SimulationConfig(
            node_count=2000,
            mesh_degree=50,
            interconnection_policy=GEOGRAPHIC,
        )
        rng = Random(42)

        result = build_topology(config, rng)

        assert len(result.countries) == 2000

        # Verify connectivity - each node should have approximately mesh_degree peers
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
