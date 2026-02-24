# Single-node blobpool heuristic tuning simulator

## Purpose

A minimal discrete-event simulator that models one honest EIP-8070 blobpool node connected to D=50 peers. The node receives announcements, makes provider/sampler role decisions, requests cells, runs detection heuristics, and disconnects misbehaving peers. The goal is to fine-tune the 6 heuristic thresholds from the simple mitigations report so they reliably detect all 6 attack profiles while minimizing false positives on honest peers.

## Architecture

Single Python module (`blobpool_sim.py`, ~800-1000 lines) with a priority-queue event loop. A Jupyter notebook imports it for interactive exploration. A CLI script imports it for batch parameter sweeps.

### Core objects

**`Blobpool`** owns the node's state:
- `txs: dict[TxHash, TxState]` with role, cells held, announcement sources, first_seen, saturation count
- `peers: dict[PeerId, PeerState]` with score, random column failure/request counts, announcements made, provider/sampler counts, connected_at
- `config: HeuristicConfig` with all tunable thresholds

**`EventLoop`** processes events ordered by timestamp. Each event handler returns zero or more follow-up events.

### Events (eth/71 message flow from node's perspective)

| Event | Fields | Trigger |
|-------|--------|---------|
| `Announce` | peer_id, tx_hash, cell_mask, fee | Peer sends NewPooledTransactionHashes |
| `TxReceived` | peer_id, tx_hash | Response to GetPooledTransactions |
| `CellsReceived` | peer_id, tx_hash, columns, success_mask | Response to GetCells |
| `CellsTimeout` | peer_id, tx_hash | GetCells timed out |
| `RequestCells` | peer_id, tx_hash, columns | Node sends GetCells |
| `SaturationCheck` | tx_hash | Timer: check tx corroboration |
| `PeerConnect` | peer_id, behavior | New peer joins |
| `PeerDisconnect` | peer_id, reason | Peer removed |
| `BlockProduced` | included_txs | Block arrives, txs removed |

### Peer behaviors (7 profiles)

**Honest:** announces correctly, provider with p=0.15, serves all columns including random, reannounces after fetching.

**T1.1/T1.2 Spammer:** floods announcements from many sender addresses, claims provider. T1.1 variant has fees below includability threshold; T1.2 has fees at/above threshold. Configurable: whether cells are actually served.

**T2.1 Selective withholder:** announces as provider (all-ones cell_mask), serves custody-aligned columns correctly, fails on random columns. Configurable random column failure rate.

**T2.2 Provider spoofer:** announces as provider, fails on all cell requests.

**T3.1 Free-rider:** always sampler (provider rate = 0%), serves custody cells it holds.

**T3.3 Non-announcer:** requests cells from our node, never announces any tx.

**T4.2 Selective signaler:** k attacker nodes announce txs exclusively to our node (no corroboration from honest peers), chains nonce-gapped txs (up to 16 per sender address), serves all cells correctly when asked.

### Heuristic engine (6 mitigations)

**H1 Includability filter** (on Announce): reject txs with `max_fee_per_blob_gas < blob_base_fee * INCLUDABILITY_DISCOUNT`. Default: 0.7.

**H2 Saturation eviction** (on SaturationCheck timer): schedule check at `first_seen + SATURATION_TIMEOUT`. If `independent_announcers < MIN_INDEPENDENT_PEERS`, evict. Defaults: 30s, 2 peers.

**H3 Enhanced sampling noise** (on RequestCells): include random `C_extra` columns from `[1, C_EXTRA_MAX]` when requesting from providers. Default C_EXTRA_MAX: 4.

**H4 Random column failure tracking** (on CellsReceived/CellsTimeout): per-peer sliding window of random column success/failure. Disconnect if failure rate exceeds `MAX_RANDOM_FAILURE_RATE` over `TRACKING_WINDOW` requests. Defaults: 10%, 100 requests.

**H5 Contribution-based peer scoring** (on Announce, CellsReceived, BlockProduced): score = f(connection_duration, included_blob_contributions, random_column_success_rate). Low-score peers need `K_LOW` provider signals; high-score peers need `K_HIGH`. Defaults: K_HIGH=2, K_LOW=4.

**H6 Conservative inclusion policy** (on BlockProduced): only count txs as includable if all blob data is fully available locally.

### Metrics

Per run:
- Detection rate per attack type (fraction of attacker peers disconnected)
- Detection latency (time from first attacker event to disconnect)
- False positive rate (fraction of honest peers incorrectly disconnected)
- Blobpool pollution over time (attack tx fraction)
- Bandwidth waste (cells fetched for evicted txs)
- Per-peer score time series

### File structure

```
single_node_sim/
  blobpool_sim.py       # Event loop, blobpool, peers, heuristics, metrics
  notebook.ipynb        # Interactive: configure, run, plot
  sweep.py              # CLI: parameter sweep, summary table
```

### Example usage

```python
cfg = HeuristicConfig(
    includability_discount=0.7,
    saturation_timeout=30.0,
    c_extra_max=4,
    max_random_failure_rate=0.1,
    tracking_window=100,
    k_high=2,
    k_low=4,
)
scenario = Scenario(
    n_honest=40,
    attackers=[
        (5, WithholderBehavior(random_fail_rate=0.3)),
        (3, SelectiveSignalerBehavior(txs_per_sender=16, n_senders=10)),
        (2, SpammerBehavior(rate=10.0, below_includability=True)),
    ],
    tx_arrival_rate=2.0,
    blob_base_fee=1.0,
    t_end=300.0,
)
results = run_simulation(cfg, scenario)
results.plot_detection_timeline()
results.summary()
```

## Decisions

- Single-file module over multi-file package: faster iteration during threshold tuning.
- Discrete event simulation over round-based or Monte Carlo: realistic timing needed for saturation timeouts and detection latency.
- Node perspective only: we model what one honest node observes and decides, not the full network. Peers are behavior generators, not full protocol participants.
- 6 attack profiles covering T1.1/T1.2, T2.1, T2.2, T3.1, T3.3, T4.2. These are the attacks detectable by the 6 proposed heuristics.
- Honest peers included in every scenario to measure false positive rates.
