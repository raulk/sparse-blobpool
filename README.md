# Sparse blobpool simulator

EIP-8070 replaces full-blob propagation with a sparse protocol: 15% of nodes store full blobs (providers), while the rest store only their custody columns plus noise-sampled extras. This dramatically cuts bandwidth, but introduces new failure modes. A withholding provider can degrade data availability. A spam flood can pollute mempools. A selective signaler can monopolize a victim's view of specific senders.

This simulator exists to find those failure modes before mainnet does. It operates at two levels: a full network simulation with thousands of nodes, realistic latency, and CoDel queuing; and a single-node heuristic tuner that isolates detection logic against six adversary profiles.

## Requirements

- Python 3.14+
- [uv](https://docs.astral.sh/uv/) package manager

```bash
git clone https://github.com/raulk/sparse-blobpool.git
cd sparse-blobpool
uv sync
```

## Two simulators, one protocol

### Network simulator (`sparse_blobpool/`)

The full network simulator models thousands of nodes communicating via eth/71 messages over a topology with geographic latency and CoDel queue management. Execution is single-threaded, deterministic, and reproducible via seeded RNG.

Nodes probabilistically adopt provider or sampler roles per transaction. Providers fetch the full blob; samplers fetch custody columns plus random extras. The simulator tracks bandwidth, propagation latency, provider ratios, reconstruction success rates, and false availability.

Three attack scenarios run adversary actors within the network: spam floods (T1.1/T1.2), selective column withholding (T2.1), and targeted availability poisoning (T4.2). A continuous fuzzer generates randomized configurations and flags anomalies across thousands of runs.

```bash
# Run a baseline scenario (2000 nodes, 60s)
uv run python -m sparse_blobpool.scenarios.baseline

# Run 100 randomized fuzzer simulations
uv run fuzz --max-runs 100 --duration-slots 5

# With live monitoring dashboard
uv run fuzz --serve --max-runs 100
```

### Heuristic simulator (`heuristic_sim/`)

The heuristic simulator isolates a single node's decision-making against a configurable peer mesh. Instead of modeling network propagation, it models what the node sees: announcement streams from honest and adversarial peers, cell request/response cycles, and block inclusion events.

Seven peer behavior generators drive the simulation. Honest peers announce transactions at realistic rates and serve all requested cells. Six adversary types implement distinct attack strategies: pool spam (A.1), data withholding (A.2), data spoofing (A.3), bandwidth leeching (A.4), availability starvation (A.5), and selective signaling (A.6).

**Five detection heuristics defend the node.** H1 rejects transactions below the includability fee threshold. H2 evicts transactions that lack independent corroboration after a timeout. H3 adds random probe columns to cell requests, feeding data to H4. H4 disconnects peers whose random column failure rate exceeds a threshold. H5 disconnects peers whose inbound request rate far exceeds their announcement contribution. A composite peer scoring system synthesizes all signals.

The simulator has 22 tunable parameters. A parameter sweep tool tests sensitivity across any of them; a CLI runner exercises all six attacks simultaneously; a Jupyter notebook provides interactive exploration with matplotlib visualizations.

```bash
# Run all 6 attacks, print summary table
just sim

# Sweep a single parameter
just sweep-param saturation_timeout

# Sweep all 10 default parameter ranges
just sweep

# Print the full attack/role/heuristic reference guide
just describe
```

## Fuzzer

The fuzzer runs continuous randomized testing. Each run generates a random configuration within defined parameter ranges (node count 8,000-15,000, provider observation timeout 12-36s, pool size 512MiB-1GiB, and others), executes a simulation, and checks results against anomaly thresholds.

| Threshold | Default | Flags when |
|-----------|---------|------------|
| `max_p99_propagation_time` | 30.0s | p99 latency exceeds limit |
| `min_reconstruction_success_rate` | 0.95 | Reconstruction drops below 95% |
| `max_false_availability_rate` | 0.05 | False availability exceeds 5% |
| `min_local_availability_met` | 0.90 | Local availability drops below 90% |

Flagged runs save full config and metrics to `fuzzer_output/<run-id>/`. Run names are memorable (generated via coolname) for easy reference.

## Monitoring dashboard

A React + TypeScript dashboard streams fuzzer progress over WebSocket.

```bash
uv sync --extra serve
uv run fuzz --serve --max-runs 100
# Access at http://localhost:8000
```

The dashboard shows live run status, success/flagged/error distribution, anomaly frequency breakdown, and per-run detail drawers with parameters, metrics, and attack impact visualization.

## Architecture

```
sparse_blobpool/
├── core/           # Simulator engine, Actor base, Network with CoDel
├── actors/         # Node (eth/71), BlockProducer, adversaries
├── protocol/       # Messages, commands, constants
├── pool/           # Blobpool with RBF, eviction, per-sender limits
├── metrics/        # Bandwidth, propagation, reconstruction, victim tracking
├── scenarios/      # Baseline + attack scenarios (spam, withholding, poisoning)
└── fuzzer/         # Autopilot, config generation, anomaly detection, server

heuristic_sim/
├── config.py       # 22 tunable parameters, presets, scenario definition
├── events.py       # Discrete event loop (min-heap)
├── peers.py        # PeerState + 7 behavior generators
├── node.py         # H1-H5 heuristics, TokenBucket rate limiter, peer scoring
├── pool.py         # TxStore with fee/age/hybrid eviction
├── metrics.py      # SimulationResult with summary table
├── runner.py       # Simulation wiring and event dispatch
├── sim.py          # CLI runner
├── sweep.py        # Parameter sweep tool
└── describe.py     # Reference guide

tests/              # 278 tests with hypothesis property-based testing
web/                # React + TypeScript monitoring dashboard
```

The network simulator uses an actor model where components communicate via messages routed through a Network actor that adds geographic latency, transmission delay, and CoDel backoff. The heuristic simulator is self-contained: its own event loop, its own pool, no dependency on the network simulator's infrastructure. Both are single-threaded and deterministic.

## Development

```bash
just test              # Run all tests
just test-heuristic    # Run heuristic sim tests only
just lint              # Format and lint
just sim               # Run heuristic sim with all 6 attacks
just sweep             # Parameter sweep (all params)
just describe          # Print attack/heuristic reference
```

## License

MIT
