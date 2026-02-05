"""Attack scenario registry with weighted selection.

This module provides a registry for attack scenarios with configurable probabilities,
allowing the fuzzer to execute different attack types based on weights.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from random import Random
from typing import TYPE_CHECKING, Callable

from sparse_blobpool.actors.adversaries.victim_selection import (
    VictimSelectionConfig,
    VictimSelectionStrategy,
    create_victim_selector,
)

if TYPE_CHECKING:
    from sparse_blobpool.actors.adversaries.victim_selection import VictimProfile
    from sparse_blobpool.config import SimulationConfig
    from sparse_blobpool.core.simulator import Simulator


class AttackType(str, Enum):
    """Available attack types."""

    NONE = "none"  # No attack (baseline)
    SPAM_T1_1 = "spam_t1_1"  # Valid headers, unavailable data
    SPAM_T1_2 = "spam_t1_2"  # Invalid/nonsense data
    WITHHOLDING_T2_1 = "withholding_t2_1"  # Selective column withholding
    POISONING_T4_2 = "poisoning_t4_2"  # Targeted availability signaling


@dataclass
class AttackScenario:
    """Configuration for an attack scenario."""

    attack_type: AttackType
    weight: float  # Probability weight for selection
    description: str
    victim_strategy: VictimSelectionStrategy
    victim_count_range: tuple[int, int]  # (min, max) victims
    attacker_count_range: tuple[int, int]  # (min, max) attackers
    attack_params: dict[str, object]  # Attack-specific parameters


@dataclass
class AttackSelection:
    """Selected attack configuration for a simulation run."""

    attack_type: AttackType
    victim_profile: VictimProfile | None
    attacker_count: int
    attack_params: dict[str, object]
    metadata: dict[str, object]


class AttackRegistry:
    """Registry for weighted attack scenario selection."""

    def __init__(self, scenarios: list[AttackScenario] | None = None) -> None:
        """Initialize the registry with attack scenarios.

        Args:
            scenarios: List of attack scenarios with weights. If None, uses defaults.
        """
        self.scenarios = scenarios or self._default_scenarios()
        self._validate_scenarios()

    def _default_scenarios(self) -> list[AttackScenario]:
        """Default attack scenario configuration."""
        return [
            AttackScenario(
                attack_type=AttackType.NONE,
                weight=0.3,  # 30% baseline (no attack)
                description="Baseline scenario with no attacks",
                victim_strategy=VictimSelectionStrategy.RANDOM,
                victim_count_range=(0, 0),
                attacker_count_range=(0, 0),
                attack_params={},
            ),
            AttackScenario(
                attack_type=AttackType.SPAM_T1_1,
                weight=0.2,  # 20% spam with valid headers
                description="Spam attack with valid headers but unavailable data",
                victim_strategy=VictimSelectionStrategy.HIGH_DEGREE,
                victim_count_range=(5, 20),
                attacker_count_range=(1, 3),
                attack_params={
                    "spam_rate": (5.0, 50.0),  # Range for random selection
                    "valid_headers": True,
                    "provide_data": False,
                    "attack_duration": (30.0, 120.0),
                },
            ),
            AttackScenario(
                attack_type=AttackType.SPAM_T1_2,
                weight=0.15,  # 15% spam with invalid data
                description="Spam attack with invalid/nonsense data",
                victim_strategy=VictimSelectionStrategy.RANDOM,
                victim_count_range=(10, 30),
                attacker_count_range=(1, 5),
                attack_params={
                    "spam_rate": (10.0, 100.0),
                    "valid_headers": False,
                    "provide_data": True,
                    "attack_duration": (20.0, 60.0),
                },
            ),
            AttackScenario(
                attack_type=AttackType.WITHHOLDING_T2_1,
                weight=0.2,  # 20% withholding attack
                description="Selective column withholding attack",
                victim_strategy=VictimSelectionStrategy.CENTRAL,
                victim_count_range=(5, 15),
                attacker_count_range=(1, 2),
                attack_params={
                    "withhold_columns": (1, 64),  # Number of columns to withhold
                },
            ),
            AttackScenario(
                attack_type=AttackType.POISONING_T4_2,
                weight=0.15,  # 15% poisoning attack
                description="Targeted availability signaling attack",
                victim_strategy=VictimSelectionStrategy.ROLE_BASED,
                victim_count_range=(3, 10),
                attacker_count_range=(2, 4),
                attack_params={
                    "nonce_chain_length": (8, 32),
                    "injection_interval": (0.05, 0.2),
                },
            ),
        ]

    def _validate_scenarios(self) -> None:
        """Validate that scenario weights sum to approximately 1.0."""
        total_weight = sum(s.weight for s in self.scenarios)
        if abs(total_weight - 1.0) > 0.001:
            # Normalize weights
            for scenario in self.scenarios:
                scenario.weight /= total_weight

    def select_attack(
        self,
        simulator: Simulator | None = None,
        rng: Random | None = None,
    ) -> AttackSelection:
        """Select an attack scenario based on weights.

        Args:
            simulator: Optional simulator for victim selection.
            rng: Random number generator.

        Returns:
            Selected attack configuration.
        """
        rng = rng or Random()

        # Build cumulative distribution
        cumulative = []
        running = 0.0
        for scenario in self.scenarios:
            running += scenario.weight
            cumulative.append((running, scenario))

        # Select scenario based on weight
        r = rng.random()
        selected_scenario = None
        for threshold, scenario in cumulative:
            if r < threshold:
                selected_scenario = scenario
                break

        if selected_scenario is None:
            selected_scenario = self.scenarios[-1]  # Fallback to last scenario

        # Generate specific parameters within ranges
        victim_count = rng.randint(*selected_scenario.victim_count_range) if selected_scenario.victim_count_range[1] > 0 else 0
        attacker_count = rng.randint(*selected_scenario.attacker_count_range) if selected_scenario.attacker_count_range[1] > 0 else 0

        # Select victims if needed
        victim_profile = None
        if victim_count > 0 and simulator is not None:
            selector = create_victim_selector(selected_scenario.victim_strategy, rng)
            try:
                victim_profile = selector.select(simulator, victim_count)
            except ValueError:
                # Not enough candidates, reduce victim count
                victim_count = min(victim_count, len(simulator.nodes))
                if victim_count > 0:
                    victim_profile = selector.select(simulator, victim_count)

        # Generate specific attack parameters from ranges
        attack_params = {}
        for key, value in selected_scenario.attack_params.items():
            if isinstance(value, tuple) and len(value) == 2:
                # It's a range, select a value
                if isinstance(value[0], float):
                    attack_params[key] = rng.uniform(value[0], value[1])
                elif isinstance(value[0], int):
                    attack_params[key] = rng.randint(value[0], value[1])
                else:
                    attack_params[key] = value
            else:
                attack_params[key] = value

        return AttackSelection(
            attack_type=selected_scenario.attack_type,
            victim_profile=victim_profile,
            attacker_count=attacker_count,
            attack_params=attack_params,
            metadata={
                "scenario_weight": selected_scenario.weight,
                "description": selected_scenario.description,
            },
        )

    def get_weights_summary(self) -> dict[str, float]:
        """Get a summary of attack type weights."""
        return {scenario.attack_type: scenario.weight for scenario in self.scenarios}

    def update_weights(self, weights: dict[AttackType, float]) -> None:
        """Update attack scenario weights.

        Args:
            weights: Dictionary mapping attack types to new weights.
        """
        for scenario in self.scenarios:
            if scenario.attack_type in weights:
                scenario.weight = weights[scenario.attack_type]
        self._validate_scenarios()

    def add_scenario(self, scenario: AttackScenario) -> None:
        """Add a new attack scenario to the registry.

        Args:
            scenario: Attack scenario to add.
        """
        self.scenarios.append(scenario)
        self._validate_scenarios()

    def remove_scenario(self, attack_type: AttackType) -> None:
        """Remove an attack scenario from the registry.

        Args:
            attack_type: Type of attack to remove.
        """
        self.scenarios = [s for s in self.scenarios if s.attack_type != attack_type]
        self._validate_scenarios()


def create_attack_executor(
    attack_selection: AttackSelection,
    config: SimulationConfig,
) -> Callable[[Simulator], None]:
    """Create an executor function for the selected attack.

    Args:
        attack_selection: Selected attack configuration.
        config: Simulation configuration.

    Returns:
        Function that executes the attack on a simulator.
    """
    def executor(sim: Simulator) -> None:
        match attack_selection.attack_type:
            case AttackType.NONE:
                # No attack, just baseline
                pass

            case AttackType.SPAM_T1_1 | AttackType.SPAM_T1_2:
                from sparse_blobpool.scenarios.attacks.spam import SpamAdversary, SpamScenarioConfig

                # Select attacker nodes
                attacker_nodes = sim.rng.sample(
                    [n.id for n in sim.nodes],
                    min(attack_selection.attacker_count, len(sim.nodes))
                )

                victim_config = None
                if attack_selection.victim_profile:
                    victim_config = VictimSelectionConfig(
                        strategy=attack_selection.victim_profile.strategy,
                        num_victims=len(attack_selection.victim_profile.victims),
                        explicit_victims=attack_selection.victim_profile.victims,
                    )

                spam_config = SpamScenarioConfig(
                    spam_rate=attack_selection.attack_params.get("spam_rate", 10.0),  # type: ignore
                    valid_headers=attack_selection.attack_params.get("valid_headers", True),  # type: ignore
                    provide_data=attack_selection.attack_params.get("provide_data", False),  # type: ignore
                    attack_start_time=0.0,  # Start attacks immediately
                    attack_duration=attack_selection.attack_params.get("attack_duration", None),  # type: ignore
                    victim_selection_config=victim_config,
                )

                adversary = SpamAdversary(
                    actor_id="spam-adversary",  # type: ignore
                    simulator=sim,
                    controlled_nodes=attacker_nodes,
                    spam_config=spam_config,
                    all_nodes=[n.id for n in sim.nodes],
                )

                sim.register_actor(adversary)
                adversary.execute()  # Start the attack

            case AttackType.WITHHOLDING_T2_1:
                from sparse_blobpool.scenarios.attacks.withholding import (
                    WithholdingAdversary,
                    WithholdingScenarioConfig,
                )

                attacker_nodes = sim.rng.sample(
                    [n.id for n in sim.nodes],
                    min(attack_selection.attacker_count, len(sim.nodes))
                )

                victim_config = None
                if attack_selection.victim_profile:
                    victim_config = VictimSelectionConfig(
                        strategy=attack_selection.victim_profile.strategy,
                        num_victims=len(attack_selection.victim_profile.victims),
                        explicit_victims=attack_selection.victim_profile.victims,
                    )

                withhold_columns = attack_selection.attack_params.get("withhold_columns")
                if isinstance(withhold_columns, int) and withhold_columns > 0:
                    withhold_columns = min(withhold_columns, 128)
                    withhold_set = set(sim.rng.sample(range(128), withhold_columns))
                    columns_to_serve = frozenset(i for i in range(128) if i not in withhold_set)
                else:
                    columns_to_serve = frozenset(range(64))

                withholding_config = WithholdingScenarioConfig(
                    columns_to_serve=columns_to_serve,
                    attack_start_time=0.0,  # Start attacks immediately
                    victim_selection_config=victim_config,
                )

                adversary = WithholdingAdversary(
                    actor_id="withholding-adversary",  # type: ignore
                    simulator=sim,
                    controlled_nodes=attacker_nodes,
                    withholding_config=withholding_config,
                    all_nodes=[n.id for n in sim.nodes],
                )

                sim.register_actor(adversary)
                adversary.execute()  # Start the attack

            case AttackType.POISONING_T4_2:
                from sparse_blobpool.scenarios.attacks.poisoning import (
                    TargetedPoisoningAdversary,
                    PoisoningScenarioConfig,
                )

                attacker_nodes = sim.rng.sample(
                    [n.id for n in sim.nodes],
                    min(attack_selection.attacker_count, len(sim.nodes))
                )

                victim_config = None
                if attack_selection.victim_profile:
                    victim_config = VictimSelectionConfig(
                        strategy=attack_selection.victim_profile.strategy,
                        num_victims=len(attack_selection.victim_profile.victims),
                        explicit_victims=attack_selection.victim_profile.victims,
                    )

                poisoning_config = PoisoningScenarioConfig(
                    nonce_chain_length=attack_selection.attack_params.get("nonce_chain_length", 16),  # type: ignore
                    injection_interval=attack_selection.attack_params.get("injection_interval", 0.1),  # type: ignore
                    attack_start_time=0.0,  # Start attacks immediately
                    victim_selection_config=victim_config,
                )

                adversary = TargetedPoisoningAdversary(
                    actor_id="poisoning-adversary",  # type: ignore
                    simulator=sim,
                    controlled_nodes=attacker_nodes,
                    poisoning_config=poisoning_config,
                    all_nodes=[n.id for n in sim.nodes],
                )

                sim.register_actor(adversary)
                adversary.execute()  # Start the attack

    return executor
