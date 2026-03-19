"""Victim selection strategies for adversaries."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from random import Random

    from sparse_blobpool.core.simulator import Simulator
    from sparse_blobpool.core.types import ActorId


class VictimSelectionStrategy(str, Enum):
    """Available victim selection strategies."""

    RANDOM = "random"
    HIGH_DEGREE = "high_degree"
    LOW_DEGREE = "low_degree"
    CENTRAL = "central"
    EDGE = "edge"
    GEOGRAPHIC_CLUSTER = "geographic_cluster"
    ROLE_BASED = "role_based"
    ALL_NODES = "all_nodes"  # Target all nodes


@dataclass
class VictimProfile:
    """Selected victim set with strategy metadata."""

    victims: list[ActorId]
    strategy: VictimSelectionStrategy
    metadata: dict[str, object]


@dataclass
class VictimSelectionConfig:
    """Configuration for victim selection."""

    strategy: VictimSelectionStrategy = VictimSelectionStrategy.RANDOM
    num_victims: int | None = None  # Number of victims to select
    victim_fraction: float | None = None  # Fraction of nodes to select as victims
    exclude_controlled: bool = True  # Exclude adversary's controlled nodes
    explicit_victims: list[ActorId] | None = None  # Use provided victims as-is
    target_providers: bool | None = (
        None  # For ROLE_BASED: target providers (True) or samplers (False)
    )
    edge_threshold: int = 3  # For EDGE: max degree to be considered edge node
    target_country: str | None = None  # For GEOGRAPHIC_CLUSTER: specific country to target


class VictimSelector:
    """Selects victims based on configured strategy."""

    def __init__(
        self,
        config: VictimSelectionConfig,
        simulator: Simulator,
        all_nodes: list[ActorId],
        controlled_nodes: list[ActorId] | None = None,
        rng: Random | None = None,
    ) -> None:
        self.config = config
        self.simulator = simulator
        self.all_nodes = all_nodes
        self.controlled_nodes = controlled_nodes or []
        self.rng = rng or simulator.rng
        self._selected_victims: list[ActorId] | None = None

    def get_victims(self) -> list[ActorId]:
        """Get the list of victim nodes based on the selection strategy."""
        if self._selected_victims is not None:
            return self._selected_victims

        if self.config.explicit_victims is not None:
            victims = list(self.config.explicit_victims)
            if self.config.exclude_controlled:
                victims = [n for n in victims if n not in self.controlled_nodes]
            self._selected_victims = victims
            return self._selected_victims

        # Determine number of victims
        num_victims = self._determine_count()

        # Filter candidates
        candidates = self.all_nodes
        if self.config.exclude_controlled:
            candidates = [n for n in candidates if n not in self.controlled_nodes]

        # Ensure we don't select more than available
        num_victims = min(num_victims, len(candidates))

        # Select based on strategy
        match self.config.strategy:
            case VictimSelectionStrategy.ALL_NODES:
                self._selected_victims = candidates

            case VictimSelectionStrategy.RANDOM:
                if num_victims >= len(candidates):
                    self._selected_victims = candidates
                else:
                    indices = self.simulator.rng.sample(range(len(candidates)), num_victims)
                    self._selected_victims = [candidates[i] for i in indices]

            case VictimSelectionStrategy.HIGH_DEGREE:
                self._selected_victims = self._select_by_degree(candidates, num_victims, high=True)

            case VictimSelectionStrategy.LOW_DEGREE:
                self._selected_victims = self._select_by_degree(candidates, num_victims, high=False)

            case VictimSelectionStrategy.CENTRAL:
                self._selected_victims = self._select_by_centrality(candidates, num_victims)

            case VictimSelectionStrategy.EDGE:
                self._selected_victims = self._select_edge_nodes(candidates, num_victims)

            case VictimSelectionStrategy.GEOGRAPHIC_CLUSTER:
                self._selected_victims = self._select_geographic_cluster(candidates, num_victims)

            case VictimSelectionStrategy.ROLE_BASED:
                self._selected_victims = self._select_by_role(candidates, num_victims)

            case _:
                # Fallback to random
                self._selected_victims = self._select_random(candidates, num_victims)

        return self._selected_victims

    def select(self, count: int | None = None) -> VictimProfile:
        """Select victims and return a profile with metadata."""
        victims = self._select_victims(count=count)
        metadata = {
            "requested_count": count,
            "selected_count": len(victims),
        }
        return VictimProfile(victims=victims, strategy=self.config.strategy, metadata=metadata)

    def _select_victims(self, count: int | None = None) -> list[ActorId]:
        """Select victims without caching, optionally overriding count."""
        if self.config.explicit_victims is not None:
            victims = list(self.config.explicit_victims)
            if self.config.exclude_controlled:
                victims = [n for n in victims if n not in self.controlled_nodes]
            return victims

        num_victims = self._determine_count(count=count)

        candidates = self.all_nodes
        if self.config.exclude_controlled:
            candidates = [n for n in candidates if n not in self.controlled_nodes]

        num_victims = min(num_victims, len(candidates))

        match self.config.strategy:
            case VictimSelectionStrategy.ALL_NODES:
                return candidates
            case VictimSelectionStrategy.RANDOM:
                return self._select_random(candidates, num_victims)
            case VictimSelectionStrategy.HIGH_DEGREE:
                return self._select_by_degree(candidates, num_victims, high=True)
            case VictimSelectionStrategy.LOW_DEGREE:
                return self._select_by_degree(candidates, num_victims, high=False)
            case VictimSelectionStrategy.CENTRAL:
                return self._select_by_centrality(candidates, num_victims)
            case VictimSelectionStrategy.EDGE:
                return self._select_edge_nodes(candidates, num_victims)
            case VictimSelectionStrategy.GEOGRAPHIC_CLUSTER:
                return self._select_geographic_cluster(candidates, num_victims)
            case VictimSelectionStrategy.ROLE_BASED:
                return self._select_by_role(candidates, num_victims)
            case _:
                return self._select_random(candidates, num_victims)

    def _determine_count(self, count: int | None = None) -> int:
        if self.config.explicit_victims is not None:
            return len(self.config.explicit_victims)
        if self.config.strategy == VictimSelectionStrategy.ALL_NODES:
            return len(self.all_nodes)
        if count is not None:
            return count
        if self.config.num_victims is not None:
            return self.config.num_victims
        if self.config.victim_fraction is not None:
            return max(1, int(len(self.all_nodes) * self.config.victim_fraction))
        return 1

    def _select_random(self, candidates: list[ActorId], count: int) -> list[ActorId]:
        """Random selection fallback."""
        if count >= len(candidates):
            return candidates
        indices = self.rng.sample(range(len(candidates)), count)
        return [candidates[i] for i in indices]

    def _select_by_degree(self, candidates: list[ActorId], count: int, high: bool) -> list[ActorId]:
        """Select nodes by degree (connectivity)."""
        try:
            import networkx as nx

            # Build graph from topology
            G = nx.Graph()
            if hasattr(self.simulator, "topology") and hasattr(self.simulator.topology, "edges"):
                G.add_edges_from(self.simulator.topology.edges)
            else:
                # Fallback if topology not available
                return self._select_random(candidates, count)

            # Calculate degrees for candidates
            degrees = []
            for node_id in candidates:
                if node_id in G:
                    degrees.append((node_id, G.degree(node_id)))
                else:
                    degrees.append((node_id, 0))

            # Sort by degree
            degrees.sort(key=lambda x: x[1], reverse=high)

            # Select top count
            return [node_id for node_id, _ in degrees[:count]]
        except ImportError:
            # NetworkX not available, fallback to random
            return self._select_random(candidates, count)

    def _select_by_centrality(self, candidates: list[ActorId], count: int) -> list[ActorId]:
        """Select nodes by betweenness centrality."""
        try:
            import networkx as nx

            # Build graph from topology
            G = nx.Graph()
            if hasattr(self.simulator, "topology") and hasattr(self.simulator.topology, "edges"):
                G.add_edges_from(self.simulator.topology.edges)
            else:
                return self._select_random(candidates, count)

            # Calculate centrality for subgraph of candidates
            subgraph_nodes = [n for n in candidates if n in G]
            if len(subgraph_nodes) < count:
                return self._select_random(candidates, count)

            S = G.subgraph(subgraph_nodes)
            centrality = nx.betweenness_centrality(S, k=min(100, len(S)))

            # Sort by centrality
            sorted_nodes = sorted(centrality.items(), key=lambda x: x[1], reverse=True)

            # Select top count
            return [node_id for node_id, _ in sorted_nodes[:count]]
        except ImportError:
            return self._select_random(candidates, count)

    def _select_edge_nodes(self, candidates: list[ActorId], count: int) -> list[ActorId]:
        """Select nodes on network edge (low connectivity)."""
        try:
            import networkx as nx

            G = nx.Graph()
            if hasattr(self.simulator, "topology") and hasattr(self.simulator.topology, "edges"):
                G.add_edges_from(self.simulator.topology.edges)
            else:
                return self._select_random(candidates, count)

            # Find edge nodes (degree <= threshold)
            edge_nodes = []
            for node_id in candidates:
                if node_id in G:
                    degree = G.degree(node_id)
                    if degree <= self.config.edge_threshold:
                        edge_nodes.append((node_id, degree))

            # Sort by degree (prefer leaf nodes)
            edge_nodes.sort(key=lambda x: x[1])

            if len(edge_nodes) < count:
                # Not enough edge nodes, include some low-degree nodes
                return self._select_by_degree(candidates, count, high=False)

            return [node_id for node_id, _ in edge_nodes[:count]]
        except ImportError:
            return self._select_random(candidates, count)

    def _select_geographic_cluster(self, candidates: list[ActorId], count: int) -> list[ActorId]:
        """Select victims clustered in a geographic region."""
        if not hasattr(self.simulator, "topology") or not hasattr(
            self.simulator.topology, "countries"
        ):
            return self._select_random(candidates, count)

        # Group candidates by country
        country_nodes: dict[str, list[ActorId]] = {}
        for node_id in candidates:
            country = self.simulator.topology.countries.get(node_id)
            if country:
                country_nodes.setdefault(country, []).append(node_id)

        # If specific country requested
        if self.config.target_country and self.config.target_country in country_nodes:
            country_candidates = country_nodes[self.config.target_country]
            if len(country_candidates) >= count:
                return self._select_random(country_candidates, count)

        # Find countries with enough nodes
        valid_countries = [c for c, nodes in country_nodes.items() if len(nodes) >= count]

        if not valid_countries:
            # No single country has enough nodes, use random
            return self._select_random(candidates, count)

            # Select a random country
            target_country = self.rng.choice(valid_countries)
        return self._select_random(country_nodes[target_country], count)

    def _select_by_role(self, candidates: list[ActorId], count: int) -> list[ActorId]:
        """Select victims based on likely role (provider vs sampler)."""
        # Use degree as proxy for role likelihood
        # High-degree nodes more likely to be providers
        try:
            import networkx as nx

            G = nx.Graph()
            if hasattr(self.simulator, "topology") and hasattr(self.simulator.topology, "edges"):
                G.add_edges_from(self.simulator.topology.edges)
            else:
                return self._select_random(candidates, count)

            role_candidates = []
            for node_id in candidates:
                if node_id in G:
                    degree = G.degree(node_id)
                    # Providers: high degree (>= 20 peers)
                    # Samplers: low degree (< 20 peers)
                    if (self.config.target_providers and degree >= 20) or (
                        not self.config.target_providers and degree < 20
                    ):
                        role_candidates.append(node_id)

            if len(role_candidates) < count:
                # Not enough of target role, use random
                return self._select_random(candidates, count)

            return self._select_random(role_candidates, count)
        except ImportError:
            return self._select_random(candidates, count)


class _VictimSelectorFactory:
    def __init__(self, strategy: VictimSelectionStrategy, rng: Random | None) -> None:
        self._strategy = strategy
        self._rng = rng

    def select(self, simulator: Simulator, count: int) -> VictimProfile:
        all_nodes = [node.id for node in simulator.nodes]
        config = VictimSelectionConfig(strategy=self._strategy, num_victims=count)
        selector = VictimSelector(
            config=config,
            simulator=simulator,
            all_nodes=all_nodes,
            rng=self._rng,
        )
        return selector.select(count=count)


def create_victim_selector(
    strategy: VictimSelectionStrategy,
    rng: Random | None = None,
) -> _VictimSelectorFactory:
    """Create a selector factory for the given strategy."""
    return _VictimSelectorFactory(strategy=strategy, rng=rng)
