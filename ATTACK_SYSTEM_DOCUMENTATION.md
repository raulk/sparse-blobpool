# Comprehensive Attacker System Documentation

## Overview

This document describes the comprehensive attacker system implemented for the sparse blobpool simulator. The system provides topology-aware victim selection, weighted attack scenario execution, victim-specific impact tracking, and UI visualization capabilities.

## Architecture

### 1. Victim Selection Strategies (`sparse_blobpool/actors/adversaries/victim_selection.py`)

The system implements multiple victim selection strategies based on network topology characteristics:

- **RANDOM**: Randomly select victims from all nodes
- **HIGH_DEGREE**: Target well-connected nodes (hubs) with many peers
- **LOW_DEGREE**: Target poorly-connected nodes with few peers
- **CENTRAL**: Target nodes with high betweenness centrality (critical for routing)
- **EDGE**: Target leaf nodes or nodes with minimal connectivity
- **GEOGRAPHIC_CLUSTER**: Target nodes clustered in specific geographic regions
- **ROLE_BASED**: Target nodes based on their likely role (provider vs sampler)

Each strategy returns a `VictimProfile` containing:
- List of selected victim IDs
- Strategy used for selection
- Metadata about the selection (e.g., average degree, centrality scores)

### 2. Attack Scenario Registry (`sparse_blobpool/scenarios/attacks/registry.py`)

The registry manages weighted attack scenario selection:

- **Attack Types**:
  - `NONE`: Baseline scenario with no attacks (30% default weight)
  - `SPAM_T1_1`: Valid headers, unavailable data (20% default weight)
  - `SPAM_T1_2`: Invalid/nonsense data (15% default weight)
  - `WITHHOLDING_T2_1`: Selective column withholding (20% default weight)
  - `POISONING_T4_2`: Targeted availability signaling (15% default weight)

- **Attack Configuration**:
  - Each attack type has configurable parameters (rates, durations, targets)
  - Parameters can be specified as ranges for randomization
  - Victim and attacker counts are determined per scenario

- **Weighted Selection**:
  - Attacks are selected probabilistically based on weights
  - Weights are normalized to sum to 1.0
  - Can be updated dynamically during fuzzing

### 3. Victim Metrics Collection (`sparse_blobpool/metrics/victim_metrics.py`)

The system tracks detailed per-victim impacts:

- **Bandwidth Metrics**:
  - Bandwidth amplification (attack/normal ratio)
  - Total excess bandwidth consumed
  - Separate tracking for control vs data traffic

- **Blobpool Impact**:
  - Spam transactions accepted/rejected
  - Pollution rate (spam/total ratio)
  - Valid transactions dropped due to attack

- **Network Health**:
  - Peer connections lost
  - Connectivity degradation percentage
  - Isolated victims (>50% peers lost)

- **Attack Effectiveness**:
  - Victim coverage (% of intended victims impacted)
  - Collateral damage (impact on non-victim nodes)
  - Attack amplification factor

### 4. Fuzzer Integration (`sparse_blobpool/fuzzer/autopilot_with_attacks.py`)

Enhanced fuzzer with attack support:

- **Attack Execution**:
  - Selects attack scenarios based on registry weights
  - Configures attackers and selects victims
  - Tracks attack distribution across runs

- **Metrics Integration**:
  - Extends base metrics with victim-specific data
  - Records attack parameters in output traces
  - Enables anomaly detection for attack impacts

- **Output Format**:
  - Attack information in config.json
  - Victim metrics in metrics.json
  - Attack weights summary in attack_weights.json

### 5. UI Visualization (`web/src/VictimVisualizer.tsx`)

React component for visualizing attack impacts:

- **Attack Overview**:
  - Attack type with color coding
  - Attacker and victim counts
  - Selection strategy used
  - Coverage percentage

- **Impact Summary**:
  - Bandwidth amplification metrics
  - Blobpool pollution rates
  - Connectivity loss statistics
  - Collateral damage indicators

- **Visualizations**:
  - Radar chart showing multi-dimensional impact
  - Bar charts for per-victim metrics
  - Tables with detailed victim data
  - Color-coded severity indicators

## Usage Examples

### Basic Attack Execution

```python
from sparse_blobpool.scenarios.attacks.registry import AttackRegistry
from sparse_blobpool.config import SimulationConfig
from sparse_blobpool.core.simulator import Simulator

# Build simulator
config = SimulationConfig(node_count=1000, mesh_degree=50)
sim = Simulator.build(config)

# Create attack registry
registry = AttackRegistry()

# Select and execute attack
attack = registry.select_attack(sim)
if attack.attack_type != AttackType.NONE:
    executor = create_attack_executor(attack, config)
    executor(sim)
```

### Custom Victim Selection

```python
from sparse_blobpool.actors.adversaries.victim_selection import (
    create_victim_selector,
    VictimSelectionStrategy
)

# Select high-degree victims
selector = create_victim_selector(VictimSelectionStrategy.HIGH_DEGREE)
victim_profile = selector.select(simulator, count=10)

# Select victims in geographic cluster
geo_selector = create_victim_selector(VictimSelectionStrategy.GEOGRAPHIC_CLUSTER)
geo_victims = geo_selector.select(simulator, count=5)
```

### Weighted Attack Distribution

```python
from sparse_blobpool.scenarios.attacks.registry import AttackRegistry, AttackType

# Create registry with custom weights
registry = AttackRegistry()
registry.update_weights({
    AttackType.NONE: 0.1,          # 10% baseline
    AttackType.SPAM_T1_1: 0.4,     # 40% spam attacks
    AttackType.SPAM_T1_2: 0.2,     # 20% invalid spam
    AttackType.WITHHOLDING_T2_1: 0.2,  # 20% withholding
    AttackType.POISONING_T4_2: 0.1,    # 10% poisoning
})
```

### Running Fuzzer with Attacks

```python
from sparse_blobpool.fuzzer.autopilot_with_attacks import run_fuzzer_with_attacks
from sparse_blobpool.fuzzer.config import FuzzerConfig
from pathlib import Path

# Configure fuzzer
config = FuzzerConfig(
    output_dir=Path("./fuzzer_output"),
    max_runs=1000,
    simulation_duration=60.0
)

# Run with attack scenarios
registry = AttackRegistry()
run_fuzzer_with_attacks(config, registry)
```

## Attack Impact Analysis

### Metrics Hierarchy

1. **Global Metrics**: Overall network health and performance
2. **Attack Metrics**: Attack-specific success indicators
3. **Victim Metrics**: Per-victim impact measurements
4. **Collateral Metrics**: Impact on non-targeted nodes

### Anomaly Detection

The system can detect anomalies indicating successful attacks:

- Bandwidth amplification > 2x normal
- Blobpool pollution > 50%
- Network partitioning (isolated victims)
- Significant valid transaction drops

### Result Interpretation

Attack effectiveness is measured by:

- **Direct Impact**: How severely victims are affected
- **Coverage**: What percentage of intended victims were impacted
- **Efficiency**: Impact achieved per attacker resource
- **Persistence**: How long impacts last after attack stops

## Testing

Run the comprehensive test suite:

```bash
uv run python scripts/test_attack_system.py
```

This tests:
1. All victim selection strategies
2. Attack registry and weighted selection
3. Attack execution with victim tracking
4. Fuzzer integration with attacks
5. Metrics collection and aggregation

## Future Enhancements

Potential improvements to the system:

1. **Advanced Victim Selection**:
   - Machine learning-based victim prediction
   - Time-varying victim selection
   - Multi-criteria victim optimization

2. **Attack Coordination**:
   - Multi-phase attack campaigns
   - Adaptive attack parameter tuning
   - Distributed attacker coordination

3. **Defense Simulation**:
   - Detection mechanisms
   - Mitigation strategies
   - Recovery protocols

4. **Analysis Tools**:
   - Attack impact prediction models
   - Vulnerability assessment
   - Network resilience scoring

## Configuration Files

### fuzzer.toml
```toml
[attack_weights]
none = 0.3
spam_t1_1 = 0.2
spam_t1_2 = 0.15
withholding_t2_1 = 0.2
poisoning_t4_2 = 0.15

[victim_selection]
default_strategy = "high_degree"
victim_count_range = [5, 20]
```

### Attack Parameters
Attack parameters can be configured per scenario:

- `spam_rate`: Messages per second for spam attacks
- `withhold_columns`: Number of columns to withhold
- `poison_rate`: Rate of poisoned transactions
- `attack_duration`: How long attack runs
- `target_fraction`: Fraction of network to target

## Conclusion

The comprehensive attacker system provides a flexible, extensible framework for simulating various attack scenarios against the sparse blobpool protocol. By combining topology-aware victim selection, weighted scenario execution, and detailed impact tracking, researchers can thoroughly evaluate the protocol's resilience to different threat models.