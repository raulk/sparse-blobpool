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

## Requirements

- Python 3.14+
- [uv](https://docs.astral.sh/uv/) package manager

## Installation

```bash
# Clone the repository
git clone https://github.com/raulk/sparse-blobpool.git
cd sparse-blobpool

# Install dependencies
uv sync
```

## Quick Start

### Run Fuzzer Autopilot

```bash
# Run 100 randomized simulations
uv run fuzz --max-runs 100 --duration-slots 5 --seed 42

# Replay a specific run by seed
uv run fuzz --replay 478163327

# Use TOML configuration
uv run fuzz --config fuzzer.toml
```

The fuzzer continuously generates randomized configs, runs baseline scenarios, and detects anomalies. Output is logged to `fuzzer_output/runs.ndjson` with trace directories for anomalous runs.

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
from sparse_blobpool.core.simulator import Simulator

# Configure and build simulation
config = SimulationConfig(
    node_count=500,
    mesh_degree=30,
    provider_probability=0.15,
    duration=30.0,
)
sim = Simulator.build(config)

# Inject transactions
for _ in range(10):
    sim.broadcast_transaction()

# Start block production and run
sim.block_producer.start()
sim.run(30.0)

# Get metrics
metrics = sim.finalize_metrics()
print(f"Bandwidth per blob: {metrics.bandwidth_per_blob / 1024:.1f} KB")
print(f"Provider ratio: {metrics.observed_provider_ratio:.3f}")
print(f"Propagation success: {metrics.propagation_success_rate * 100:.1f}%")
```

## Attack Scenarios

Self-contained attack scenarios with adversary logic included:

### Spam Attack (T1.1/T1.2)

Flood the network with garbage transactions:

```python
from sparse_blobpool.scenarios import run_spam_scenario, SpamScenarioConfig

attack_config = SpamScenarioConfig(
    spam_rate=50.0,           # 50 txs/second
    valid_headers=True,       # T1.1: valid structure, unavailable data
    num_attacker_nodes=2,
    target_fraction=0.5,      # Target 50% of nodes
)

sim = run_spam_scenario(attack_config=attack_config, run_duration=30.0)
metrics = sim.finalize_metrics()
```

### Withholding Attack (T2.1)

Serve custody cells but withhold reconstruction data:

```python
from sparse_blobpool.scenarios import run_withholding_scenario, WithholdingScenarioConfig

attack_config = WithholdingScenarioConfig(
    columns_to_serve=frozenset(range(32)),  # Only serve first 32 columns
    attacker_fraction=0.1,                   # 10% of nodes are adversaries
)

sim = run_withholding_scenario(attack_config=attack_config, run_duration=30.0)
metrics = sim.finalize_metrics()
```

### Targeted Poisoning Attack (T4.2)

Signal transaction availability only to victim nodes:

```python
from sparse_blobpool.scenarios import run_poisoning_scenario, PoisoningScenarioConfig

attack_config = PoisoningScenarioConfig(
    num_victims=3,
    nonce_chain_length=16,
    injection_interval=0.1,
)

sim = run_poisoning_scenario(attack_config=attack_config, run_duration=30.0)
metrics = sim.finalize_metrics()
```

## Fuzzer Autopilot

The fuzzer runs continuous randomized testing with configurable parameter ranges and anomaly detection.

### CLI Options

| Option | Description |
|--------|-------------|
| `--max-runs N` | Maximum runs (default: unlimited) |
| `--duration-secs N` | Duration in seconds |
| `--duration-slots N` | Duration in slots (1 slot = 12s) |
| `--duration-epochs N` | Duration in epochs (1 epoch = 32 slots) |
| `--seed N` | Master seed for reproducibility |
| `--replay SEED` | Replay a specific run |
| `--config FILE` | TOML configuration file |
| `--trace-all` | Save traces for all runs, not just anomalies |
| `--serve` | Start the monitoring dashboard server |
| `--port N` | Port for the monitoring server (default: 8000) |

### Anomaly Detection

The fuzzer flags runs where metrics fall outside expected ranges:

| Threshold | Default | Description |
|-----------|---------|-------------|
| `max_p99_propagation_time` | 30.0s | Maximum p99 latency |
| `min_reconstruction_success_rate` | 0.95 | Minimum reconstruction rate |
| `max_false_availability_rate` | 0.05 | Maximum false availability |
| `min_provider_coverage_ratio` | 0.5 | Minimum ratio vs expected p |
| `min_local_availability_met` | 0.90 | Minimum local availability |

### Output Format

```
[memorable-run-id] BASELINE seed=12345 ... OK (1.2s)
[another-run-id] BASELINE seed=67890 ... ATTENTION(low_local_availability) (2.3s)
```

Anomalous runs save `config.json` and `metrics.json` to `fuzzer_output/<run-id>/`.

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

## Fuzzer Web UI

A real-time monitoring dashboard for continuous fuzzer runs.

### Quick start

```bash
# Install with serve dependencies
uv sync --extra serve

# Run fuzzer with live monitoring dashboard
uv run fuzz --serve --max-runs 100

# Server stays alive after fuzzing for result inspection
# Press Ctrl+C to exit
```

Or run server-only mode:

```bash
uv run fuzz --serve  # Just the dashboard, no fuzzing
```

Access the dashboard at http://localhost:8000 (requires frontend build) or run the frontend dev server:

```bash
# Terminal 3: Frontend development
cd web && pnpm install && pnpm dev
```

Access at http://localhost:5173 (proxies API to backend)

**Features:**
- Live run status with WebSocket updates
- Success/flagged/error rate distribution
- Anomaly frequency charts
- Click any run to view details in slide-out drawer:
  - **Parameters**: Network, protocol, timing, blobpool config
  - **Metrics**: Bandwidth, propagation, availability, attack resilience
  - **Logs**: Trace file location for flagged runs

**Stack:**
- Backend: FastAPI + WebSockets (integrated in `sparse_blobpool.fuzzer.server`)
- Frontend: React + TypeScript + Vite + TailwindCSS (in `web/`)
- Charts: Recharts

## Architecture

```
sparse_blobpool/
├── core/           # Simulator, Actor, Network, BlockProducer
├── actors/         # Node (honest.py), BlockProducer
├── protocol/       # eth/71 messages, blobpool state
├── p2p/            # Topology generation
├── metrics/        # MetricsCollector, SimulationResults
├── scenarios/      # Runnable scenarios
│   ├── baseline.py
│   └── attacks/    # Attack scenarios with adversary logic
│       ├── spam.py
│       ├── withholding.py
│       └── poisoning.py
└── fuzzer/         # Fuzzer autopilot + monitoring server
tests/              # 230+ tests with hypothesis
web/                # React frontend for fuzzer monitoring
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
