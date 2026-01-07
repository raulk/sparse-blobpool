# Sparse Blobpool Simulator

A discrete event simulator for [EIP-8070](https://github.com/ethereum/EIPs/pull/8070) sparse blobpool protocol, modeling blob transaction propagation in Ethereum's peer-to-peer network.

## Overview

The sparse blobpool protocol reduces bandwidth requirements for blob propagation by having nodes probabilistically act as either **providers** (storing full blobs) or **samplers** (storing only custody-aligned cells). This simulator validates protocol correctness and measures performance under various network conditions and attack scenarios.

**Key features:**

- Discrete event simulation with deterministic replay
- Realistic network latency with CoDel queue modeling
- Geographic region-based peer connections (NA, EU, AS)
- Attack scenario modeling (spam, withholding, targeted poisoning)
- Continuous fuzzing with anomaly detection
- Real-time monitoring dashboard

## Requirements

- Python 3.14+
- [uv](https://docs.astral.sh/uv/) package manager

## Installation

```bash
git clone https://github.com/raulk/sparse-blobpool.git
cd sparse-blobpool
uv sync
```

## Quick start

### Run the fuzzer

```bash
# Run 100 randomized simulations
uv run fuzz --max-runs 100 --duration-slots 5

# With live monitoring dashboard
uv run fuzz --serve --max-runs 100

# Replay a specific run by seed
uv run fuzz --replay 478163327
```

The fuzzer generates randomized configurations, runs simulations, and flags anomalies. Results are logged to `fuzzer_output/runs.ndjson` with detailed traces for flagged runs.

### Run a baseline scenario

```bash
uv run python -m sparse_blobpool.scenarios.baseline
```

Runs a 60-second simulation with 2000 nodes and reports bandwidth usage, propagation times, and provider ratios.

### Python API

```python
from sparse_blobpool.config import SimulationConfig
from sparse_blobpool.core.simulator import Simulator

config = SimulationConfig(
    node_count=500,
    mesh_degree=30,
    provider_probability=0.15,
    duration=30.0,
)
sim = Simulator.build(config)

for _ in range(10):
    sim.broadcast_transaction()

sim.block_producer.start()
sim.run(30.0)

metrics = sim.finalize_metrics()
print(f"Bandwidth per blob: {metrics.bandwidth_per_blob / 1024:.1f} KB")
print(f"Provider ratio: {metrics.observed_provider_ratio:.3f}")
```

## Attack scenarios

The simulator includes adversary implementations for protocol security analysis:

### Spam attack (T1.1/T1.2)

Flood the network with garbage transactions:

```python
from sparse_blobpool.scenarios import run_spam_scenario, SpamScenarioConfig

config = SpamScenarioConfig(
    spam_rate=50.0,           # 50 txs/second
    valid_headers=True,       # Valid structure, unavailable data
    num_attacker_nodes=2,
    target_fraction=0.5,
)
sim = run_spam_scenario(attack_config=config, run_duration=30.0)
```

### Withholding attack (T2.1)

Serve custody cells but withhold reconstruction data:

```python
from sparse_blobpool.scenarios import run_withholding_scenario, WithholdingScenarioConfig

config = WithholdingScenarioConfig(
    columns_to_serve=frozenset(range(32)),  # Only first 32 columns
    attacker_fraction=0.1,
)
sim = run_withholding_scenario(attack_config=config, run_duration=30.0)
```

### Targeted poisoning attack (T4.2)

Signal transaction availability only to victim nodes:

```python
from sparse_blobpool.scenarios import run_poisoning_scenario, PoisoningScenarioConfig

config = PoisoningScenarioConfig(
    num_victims=3,
    nonce_chain_length=16,
    injection_interval=0.1,
)
sim = run_poisoning_scenario(attack_config=config, run_duration=30.0)
```

## Fuzzer

The fuzzer runs continuous randomized testing with configurable parameter ranges and anomaly detection.

### CLI options

| Option | Description |
|--------|-------------|
| `--max-runs N` | Maximum runs (default: unlimited) |
| `--duration-slots N` | Duration in slots (1 slot = 12s) |
| `--seed N` | Master seed for reproducibility |
| `--replay SEED` | Replay a specific run |
| `--config FILE` | TOML configuration file |
| `--trace-all` | Save traces for all runs |
| `--serve` | Enable monitoring dashboard |
| `--port N` | Dashboard port (default: 8000) |

### Anomaly detection

The fuzzer flags runs where metrics fall outside expected ranges:

| Threshold | Default | Description |
|-----------|---------|-------------|
| `max_p99_propagation_time` | 30.0s | Maximum p99 latency |
| `min_reconstruction_success_rate` | 0.95 | Minimum reconstruction rate |
| `max_false_availability_rate` | 0.05 | Maximum false availability |
| `min_local_availability_met` | 0.90 | Minimum local availability |

### Output

```
[memorable-run-id] BASELINE seed=12345 ... OK (1.2s)
[another-run-id] BASELINE seed=67890 ... ATTENTION(low_local_availability) (2.3s)
```

Flagged runs save `config.json` and `metrics.json` to `fuzzer_output/<run-id>/`.

## Monitoring dashboard

Real-time web UI for monitoring fuzzer progress.

```bash
# Install serve dependencies
uv sync --extra serve

# Run with dashboard
uv run fuzz --serve --max-runs 100
```

Access at http://localhost:8000

**Features:**
- Live run status via WebSocket
- Success/flagged/error distribution charts
- Anomaly frequency breakdown
- Run detail drawer with parameters, metrics, and trace data

For frontend development:

```bash
cd web && pnpm install && pnpm dev
```

## Configuration

### Simulation parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `node_count` | 2000 | Number of nodes |
| `mesh_degree` | 50 | Peer connections per node |
| `provider_probability` | 0.15 | Provider role probability |
| `custody_columns` | 8 | Columns per node for custody |
| `blobpool_max_bytes` | 256MB | Maximum blobpool size |
| `max_txs_per_sender` | 16 | Per-sender transaction limit |
| `duration` | 60.0 | Simulation duration (seconds) |

### Network latency

| Route | Base latency | Jitter |
|-------|--------------|--------|
| NA ↔ NA | 20ms | 10% |
| EU ↔ EU | 15ms | 10% |
| AS ↔ AS | 25ms | 10% |
| NA ↔ EU | 45ms | 15% |
| NA ↔ AS | 90ms | 20% |
| EU ↔ AS | 75ms | 15% |

## Metrics

The simulator collects:

- **Bandwidth**: Total bytes, per-blob average, reduction vs full propagation
- **Propagation**: Time to network coverage, success rate
- **Roles**: Provider vs sampler distribution
- **Reconstruction**: Success rate for blob reconstruction
- **Attack metrics**: Spam amplification, victim pollution

```python
metrics = sim.finalize_metrics()
print(json.dumps(metrics.to_dict(), indent=2))
```

## Architecture

```
sparse_blobpool/
├── core/           # Simulator, Actor, Network, BlockProducer
├── actors/         # Node implementation
├── protocol/       # eth/71 messages, blobpool state
├── p2p/            # Topology generation
├── metrics/        # MetricsCollector, SimulationResults
├── scenarios/      # Runnable scenarios
│   ├── baseline.py
│   └── attacks/    # Spam, withholding, poisoning
└── fuzzer/         # Autopilot + monitoring server
tests/              # 230+ tests with hypothesis
web/                # React frontend
```

The simulator uses an actor model where all components communicate via messages routed through a Network actor that adds realistic latency. Execution is single-threaded and deterministic using a min-heap priority queue.

## Development

```bash
uv run pytest                           # Run tests
uv run pytest --cov=sparse_blobpool     # With coverage
uv run ruff format .                    # Format
uv run ruff check . --fix               # Lint
```

## License

MIT
