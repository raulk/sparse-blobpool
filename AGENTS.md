# AGENTS.md

Guidelines for AI agents working on the sparse blobpool simulator.

## Project overview

Two simulation systems for EIP-8070 sparse blobpool protocol, targeting different levels of analysis.

### Network simulator (`sparse_blobpool/`)

Full multi-node discrete event simulation with actor model, geographic latency, CoDel queuing.

- `core/` - Simulator engine, Actor base, Network with CoDel, BlockProducer
- `actors/` - Node (eth/71 protocol in `honest.py`), adversaries with victim selection
- `protocol/` - Messages (NewPooledTransactionHashes, GetCells, Cells), commands, constants
- `pool/` - Blobpool with RBF (10% bump), per-sender limits, size-based eviction
- `metrics/` - Bandwidth, propagation, reconstruction, per-victim attack impact
- `scenarios/` - Baseline honest network + attack scenarios
  - `attacks/spam.py` - T1.1/T1.2 spam flood
  - `attacks/withholding.py` - T2.1 selective column withholding
  - `attacks/poisoning.py` - T4.2 targeted availability poisoning
  - `attacks/registry.py` - Weighted attack selection
- `fuzzer/` - Continuous randomized testing with anomaly detection, FastAPI server

### Heuristic simulator (`heuristic_sim/`)

Self-contained single-node simulator for tuning detection heuristics. No dependency on the network simulator.

- `config.py` - Constants, HeuristicConfig (22 params), PRESETS, Scenario, EvictionPolicy
- `events.py` - Event, EventLoop (min-heap discrete event loop)
- `peers.py` - PeerState, 7 peer behavior generators (honest + 6 adversary types)
- `node.py` - Node with H1-H5 detection heuristics, TokenBucket rate limiting, peer scoring
- `pool.py` - TxEntry, TxStore with fee/age/hybrid eviction policies
- `metrics.py` - SimulationResult with summary_table, detection_summary
- `runner.py` - run_simulation, event dispatch, scenario wiring
- `sim.py` - CLI runner (`just sim`)
- `sweep.py` - Parameter sweep tool (`just sweep`)
- `describe.py` - Reference guide for attacks, roles, heuristics (`just describe`)

### Dashboard (`web/`)

React + TypeScript + Vite + TailwindCSS monitoring dashboard for the fuzzer.

### Tests

278 tests across `tests/`. Property-based tests (hypothesis) in `tests/test_role_distribution.py`. Heuristic sim tests in `tests/test_heuristic_sim.py` (51 tests).

## Project-specific overrides

**Python 3.14+** required (overrides global 3.12+ default).

## Common commands

```bash
just test              # Run all tests
just test-heuristic    # Run heuristic sim tests
just lint              # Format and lint
just sim               # Run heuristic sim with all 6 attacks
just sweep             # Parameter sweep (all params)
just describe          # Print attack/heuristic reference
just fuzz              # Run fuzzer with dashboard (100 runs)
```
