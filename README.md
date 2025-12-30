# Sparse Blobpool Simulator

A discrete event simulator for EIP-8070 sparse blobpool protocol, modeling blob transaction propagation in Ethereum's peer-to-peer network.

## Overview

This simulator models the sparse blobpool protocol where nodes probabilistically act as either **providers** (storing full blobs) or **samplers** (storing only custody-aligned cells). The simulation includes:

- Realistic network latency with CoDel queue modeling
- Geographic region-based peer connections (NA, EU, AS)
- Hash-based role determination (p=0.15 provider probability)
- Block production with blob inclusion
- Attack scenarios (spam, withholding, targeted poisoning)
- Comprehensive metrics collection

## Installation

```bash
# Clone the repository
git clone https://github.com/raulk/sparse-blobpool-sim.git
cd sparse-blobpool-sim

# Install with uv
uv sync
```

## Quick Start

### Run Baseline Scenario

```bash
uv run python -m sparse_blobpool.scenarios.baseline
```

This runs a 60-second simulation with 2000 nodes and outputs statistics including:
- Bandwidth usage and reduction vs full propagation
- Transaction propagation times
- Provider ratio verification

### Basic Usage in Python

```python
from sparse_blobpool.config import SimulationConfig
from sparse_blobpool.scenarios.baseline import build_simulation, broadcast_transaction

# Configure simulation
config = SimulationConfig(
    node_count=500,
    mesh_degree=30,
    provider_probability=0.15,
    duration=30.0,
)

# Build simulation
result = build_simulation(config)

# Inject transactions
for _ in range(10):
    broadcast_transaction(result)

# Start block production
result.block_producer.start()

# Run simulation
result.simulator.run(30.0)

# Get metrics
metrics = result.finalize_metrics()
print(f"Bandwidth per blob: {metrics.bandwidth_per_blob / 1024:.1f} KB")
print(f"Provider ratio: {metrics.observed_provider_ratio:.3f}")
print(f"Propagation success: {metrics.propagation_success_rate * 100:.1f}%")
```

## Attack Scenarios

### Spam Attack (T1.1/T1.2)

Flood the network with garbage transactions:

```bash
uv run python -m sparse_blobpool.scenarios.spam_attack
```

```python
from sparse_blobpool.adversaries.spam import SpamAttackConfig
from sparse_blobpool.scenarios.spam_attack import run_spam_attack

attack_config = SpamAttackConfig(
    spam_rate=50.0,      # 50 txs/second
    valid_headers=True,   # Valid tx structure
    provide_data=False,   # But no actual data
    start_time=1.0,
)

result = run_spam_attack(attack_config=attack_config)
print(f"Spam txs injected: {result.spam_txs_injected}")
```

### Targeted Poisoning Attack (T4.2)

Signal transaction availability only to a victim:

```bash
uv run python -m sparse_blobpool.scenarios.poisoning
```

```python
from sparse_blobpool.adversaries.poisoning import TargetedPoisoningConfig
from sparse_blobpool.scenarios.poisoning import run_poisoning_attack

attack_config = TargetedPoisoningConfig(
    num_attacker_connections=4,
    nonce_chain_length=16,
    injection_interval=0.1,
)

result = run_poisoning_attack(attack_config=attack_config)
print(f"Poison txs injected: {result.poison_txs_injected}")
print(f"Victim pool size: {result.victim_pool_size}")
```

## Configuration

### SimulationConfig

| Parameter | Default | Description |
|-----------|---------|-------------|
| `node_count` | 2000 | Number of nodes in the network |
| `mesh_degree` | 50 | Target peer connections per node |
| `provider_probability` | 0.15 | Probability of acting as provider |
| `custody_columns` | 8 | Columns per node for custody sampling |
| `blobpool_max_bytes` | 256MB | Maximum blobpool size |
| `max_txs_per_sender` | 16 | Per-sender transaction limit |
| `duration` | 60.0 | Simulation duration in seconds |
| `seed` | None | Random seed for reproducibility |

### Network Regions

Latency between regions (one-way):

| Route | Base Latency | Jitter |
|-------|--------------|--------|
| NA ↔ NA | 20ms | 10% |
| EU ↔ EU | 15ms | 10% |
| AS ↔ AS | 25ms | 10% |
| NA ↔ EU | 45ms | 15% |
| NA ↔ AS | 90ms | 20% |
| EU ↔ AS | 75ms | 15% |

## Metrics

The simulator collects:

- **Bandwidth**: Total bytes, per-blob average, control vs data split
- **Propagation**: Time to 99% network coverage, success rate
- **Roles**: Provider vs sampler ratio
- **Reconstruction**: Success rate for blob reconstruction
- **Attack metrics**: Spam amplification, victim pollution

Export to JSON:

```python
metrics = result.finalize_metrics()
import json
print(json.dumps(metrics.to_dict(), indent=2))
```

## Architecture

```
sparse_blobpool/
├── core/           # Simulator, Actor, Network, BlockProducer
├── protocol/       # Messages, Blobpool, constants
├── p2p/            # Node actor, topology generation
├── metrics/        # MetricsCollector, SimulationResults
├── adversaries/    # Attack implementations
└── scenarios/      # Runnable scenarios
```

### Actor Model

Everything is an Actor with a single `on_event()` entrypoint. Actors communicate via messages routed through the Network actor, which adds realistic latency including CoDel queue delays.

### Event Loop

Single-threaded deterministic execution using a min-heap priority queue. Events are ordered by (timestamp, priority).

## Testing

```bash
# Run all tests
uv run pytest

# Run with coverage
uv run pytest --cov=sparse_blobpool

# Run specific test file
uv run pytest tests/test_core/test_network.py -v
```

## Development

```bash
# Format code
uv run ruff format .

# Lint code
uv run ruff check . --fix

# Type check
uv run ty check
```

## License

MIT
