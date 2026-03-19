#!/usr/bin/env python3
"""Print a reference guide for the blobpool heuristic simulator."""

from __future__ import annotations

from heuristic_sim.config import HeuristicConfig
from heuristic_sim.sim import DEFAULT_SCENARIO

DESCRIPTION = """\
EIP-8070 Sparse Blobpool Heuristic Simulator
=============================================

Simulates a single node running EIP-8070 blobpool heuristics against
6 attack profiles. The node maintains a peer mesh, receives tx
announcements, requests cells, and applies detection heuristics.

ATTACKS
-------

  Attacks describe WHAT an adversary is trying to achieve. Each attack
  has a goal and a mechanism; roles (below) implement the behavior.

  A.1  Pool spam              Goal: exhaust pool capacity with junk txs,
                               crowding out legitimate transactions.
                               Mechanism: flood announcements at high rate
                               with fees below the includability threshold.
                               Uses unique senders to bypass per-sender
                               nonce limits.

  A.2  Data withholding       Goal: degrade data availability by claiming
                               to hold cells but refusing to serve them.
                               Mechanism: announce as provider, then fail
                               GetCells requests for columns outside the
                               requester's known custody set. Custody
                               columns are served honestly to avoid trivial
                               detection.

  A.3  Data spoofing          Goal: occupy peer slots while providing zero
                               data. Mechanism: announce as provider but
                               fail 100% of cell requests. A degenerate
                               form of A.2 where the attacker has no data
                               at all.

  A.4  Bandwidth leeching     Goal: consume the victim's outbound bandwidth
                               without contributing. Mechanism: request
                               cells at normal rate but never announce txs
                               or serve as provider. The victim wastes
                               bandwidth serving cells to a peer that gives
                               nothing back.

  A.5  Availability starvation
                               Goal: reduce the victim's effective peer
                               mesh quality. Mechanism: connect as inbound
                               peers to occupy slots, then contribute
                               minimally (sampler-only, no provider
                               contribution). The victim wastes slots on
                               low-value peers.

  A.6  Selective signaling     Goal: monopolize the victim's view of
                               specific senders to control which txs get
                               included. Mechanism: flood exclusive txs
                               from target senders, filling all 16 nonce
                               slots per sender. No other peer corroborates
                               these txs.

ROLES
-----

  Roles describe HOW an adversary behaves in the simulation. Each role
  implements one or more attacks.

  R.1  spammer               Implements A.1 (pool spam).
                              Announces below-fee txs at configurable rate.
                              Claims provider but fails all cell requests.
                              Parameters: rate, below_includability.
                              Detected by: H1.

  R.2  withholder            Implements A.2 (data withholding).
                              Claims provider, serves custody columns
                              honestly, fails random probe columns at a
                              configurable rate.
                              Parameters: random_fail_rate.
                              Detected by: H4.

  R.3  spoofer               Implements A.3 (data spoofing).
                              Claims provider, fails 100% of cell requests
                              including custody columns.
                              Detected by: H4.

  R.4  free_rider            Implements A.4 (bandwidth leeching) + A.5
                              (availability starvation). Announces as
                              sampler only, serves custody columns, never
                              provides. Requests cells at honest rate.
                              Parameters: custody_columns.
                              Detected by: H5, scoring.

  R.5  non_announcer         Implements A.4 (bandwidth leeching).
                              Never announces txs. Only sends GetCells
                              requests, consuming victim outbound bandwidth
                              with zero contribution.
                              Detected by: H5.

  R.6  selective_signaler    Implements A.6 (selective signaling).
                              Floods exclusive txs from target senders,
                              each filling all 16 nonce slots.
                              Parameters: n_senders, txs_per_sender.
                              Detected by: H2.

DETECTION HEURISTICS
--------------------

  H1  Includability check    Mitigates: A.1 (pool spam).
                             Catches: R.1 (spammer).
                             How: reject txs with fee < blob_base_fee *
                             includability_discount. Applied at announcement
                             time; below-fee txs never enter the pool.

  H2  Saturation check       Mitigates: A.6 (selective signaling).
                             Catches: R.6 (selective_signaler).
                             How: after saturation_timeout seconds, evict
                             txs with fewer than min_independent_peers
                             unique announcers. Txs only announced by one
                             peer are likely fabricated to monopolize a
                             sender's nonce slots.

  H3  C_extra random cols    Mitigates: A.2 (data withholding), A.3 (data
                             spoofing).
                             Catches: feeds data to H4.
                             How: when requesting cells, add c_extra_max
                             random columns beyond custody to probe the
                             announcer. The announcer cannot know which
                             columns are probes vs. custody, so it must
                             either serve honestly or risk detection.

  H4  Random column failure  Mitigates: A.2 (data withholding), A.3 (data
                             spoofing).
                             Catches: R.2 (withholder), R.3 (spoofer).
                             How: disconnect peers whose random column
                             failure rate exceeds max_random_failure_rate
                             over a sliding window of tracking_window
                             requests. Probed by H3's extra columns.

  H5  Request ratio          Mitigates: A.4 (bandwidth leeching), A.5
                             (availability starvation).
                             Catches: R.4 (free_rider), R.5 (non_announcer).
                             How: disconnect peers whose inbound request
                             count divided by announcements exceeds
                             max_request_to_announce_ratio. Applied after
                             60s warmup to allow honest peers to ramp up.
                             Peers that request without contributing are
                             consuming outbound bandwidth for free.

  Scoring  Peer scoring      Mitigates: A.4, A.5 (low-value peers).
                             Catches: R.4 (free_rider) via low score.
                             How: combines duration, contributions, failure
                             rate, announcer activity, request ratio,
                             provider rate deviation, and inbound/outbound
                             status into a composite score. Peers below
                             score_threshold are candidates for eviction
                             when better peers are available.

PEER CONNECTION MODEL
---------------------

  Geth defaults: 50 peers total, 34 inbound (68%), 16 outbound (32%).
  Attackers occupy inbound slots (they connect to the victim).
  Inbound peers start with a score discount (inbound_score_discount)
  and must earn trust through contributions.

BANDWIDTH TRACKING
------------------

  Per-peer bytes_in/bytes_out track bandwidth from the target node's
  perspective. Useful for measuring attacker overhead in starvation
  scenarios. Cell size: 2 KiB. Announce message: 200 bytes.
  Request overhead: 64 bytes + 2 bytes per column index.

"""


def main() -> None:
    print(DESCRIPTION)

    cfg = HeuristicConfig()
    print("DEFAULT CONFIG")
    print("--------------\n")
    for name in sorted(cfg.__dataclass_fields__):
        print(f"  {name:<35} {getattr(cfg, name)}")

    s = DEFAULT_SCENARIO
    print("\nDEFAULT SCENARIO")
    print("----------------\n")
    print(f"  Honest peers:      {s.n_honest}")
    print(
        f"  Inbound ratio:     {s.inbound_ratio} ({round(s.n_honest * s.inbound_ratio)} inbound, {round(s.n_honest * (1 - s.inbound_ratio))} outbound)"
    )
    print(f"  Tx arrival rate:   {s.tx_arrival_rate}/s per peer")
    print(f"  Duration:          {s.t_end}s")
    print(f"  Block interval:    {s.block_interval}s")
    print(f"  Blob base fee:     {s.blob_base_fee}")
    print("\n  Attackers:")
    for count, btype, params in s.attackers:
        param_str = ", ".join(f"{k}={v}" for k, v in params.items()) if params else "defaults"
        print(f"    {count}x {btype:<25} {param_str}")
    print()


if __name__ == "__main__":
    main()
