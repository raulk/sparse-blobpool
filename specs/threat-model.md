# Sparse blobpool threat model

> **Document Status:** Living document for security analysis  
> **Last Updated:** 2025-12-29  
> **Scope:** EIP-8070 Sparse Blobpool and related mechanisms  
> **Threat Model Approach:** Attacker-goal-oriented, working backwards from undesirable outcomes

---

## Executive summary

The sparse blobpool introduces probabilistic data availability into Ethereum's execution layer, reducing bandwidth ~4x by having nodes fetch full blobs only 15% of the time (provider role) while sampling custody-aligned cells 85% of the time (sampler role). This design creates novel attack surfaces not present in the current full-replication blobpool.

**Critical assets at risk:**

- Network bandwidth and node resources
- Blob transaction propagation and inclusion
- Block validity and attestation correctness
- Proposer privacy and anonymity
- Economic guarantees (fee payment ↔ service delivery)

---

## Table of contents

1. [Threat categories](#threat-categories)
2. [Attack vector inventory](#attack-vector-inventory)
   - [T1: Denial of service](#t1-denial-of-service)
   - [T2: Data availability manipulation](#t2-data-availability-manipulation)
   - [T3: Protocol gaming](#t3-protocol-gaming)
   - [T4: Network-level attacks](#t4-network-level-attacks)
   - [T5: Proposer-targeted attacks](#t5-proposer-targeted-attacks)
   - [T6: Economic attacks](#t6-economic-attacks)
   - [T7: Implementation-specific attacks](#t7-implementation-specific-attacks)
3. [Attack feasibility assessment](#attack-feasibility-assessment)
4. [Cross-cutting concerns](#cross-cutting-concerns)
5. [Open questions & research gaps](#open-questions--research-gaps)

---

## Threat categories

| Category              | Primary impact                                  | Affected parties          |
| --------------------- | ----------------------------------------------- | ------------------------- |
| **DoS**               | Resource exhaustion, service degradation        | All nodes, network        |
| **Data availability** | Invalid blocks, failed attestations             | Proposers, attesters      |
| **Protocol gaming**   | Unfair resource usage, model violations         | Honest nodes              |
| **Network-level**     | Isolation, partitioning, targeted attacks       | Individual nodes, regions |
| **Proposer-targeted** | Deanonymization, manipulation, missed slots     | Proposers                 |
| **Economic**          | Fee extraction, censorship, market manipulation | Blob submitters, L2s      |
| **Implementation**    | Client-specific exploits, state corruption      | Specific client users     |

---

## Attack vector inventory

### T1: Denial of service

#### T1.1: Blobpool spam (single node)

**Description:** Attacker floods a target node's blobpool with garbage transactions containing unavailable blob data, consuming memory and processing resources.

**Attack flow:**

1. Attacker creates many valid-looking type 3 transactions with blob sidecars
2. Attacker propagates transactions through network normally
3. Target node, as sampler (85% probability), stores transaction metadata + partial cells
4. Attacker never provides full data; blob is ultimately unavailable
5. Target's blobpool fills with garbage, displacing legitimate transactions

**Prerequisites:**

- Attacker can submit type 3 transactions (requires valid signatures, gas payment)
- Target accepts transactions from attacker (not disconnected)

**Baseline feasibility (no tickets):** HIGH

- 2GB blobpool capacity = ~15,000 max-size blob transactions
- Cost: only gas fees for transaction portion (blob never included, no blob fee paid)
- No Sybil limit on blob submission—unlimited submission capacity
- 16 tx/address limit bypassed via many addresses

**Impact:** MEDIUM

- Single node degradation
- Legitimate transactions evicted
- Node resource exhaustion

**Existing mitigations (baseline):**

- 16 pending transaction limit per address (bypassed by Sybil addresses)
- Transaction eviction policies (age, fee priority)
- `C_req = 8` max columns per request limits per-request bandwidth

**Gaps:**

- No mechanism to detect "stale" transactions with insufficient network saturation
- Sampler cannot independently verify full data availability
- Attack cost scales linearly with attack surface, not quadratically

**Recommendations:**

1. Implement time-based transaction dropping based on network observation count
2. Track ratio of successfully-resolved vs. failed blob fetches per peer

**Blob tickets mitigation:**

| Aspect                       | Effect                                                         |
| ---------------------------- | -------------------------------------------------------------- |
| **Mechanism**                | Attacker must purchase tickets before propagating blobs        |
| **Sybil Cost**               | Each blob requires a ticket; cannot spam unlimited blobs       |
| **Hard Cap**                 | At most `k × Δ × MAX_BLOBS` concurrent blobs in blobpool       |
| **Feasibility with Tickets** | **LOW** — attack cost now proportional to ticket auction price |
| **Residual Risk**            | Rich attacker could still purchase tickets at cost             |

---

#### T1.2: Network-wide blobpool spam

**Description:** Coordinated attack to pollute the entire network's blobpool with unavailable blob transactions, degrading global blob propagation and inclusion.

**Attack flow:**

1. Attacker creates N unavailable blob transactions
2. Transactions propagate via normal gossip (providers see 15%, samplers 85%)
3. Providers attempt to fetch full data, fail or receive partial data
4. Samplers successfully sample custody cells (attack provides those)
5. Network fills with transactions that cannot be included

**Prerequisites:**

- Significant Sybil capacity (many EOAs)
- Ability to selectively provide custody cells while withholding reconstruction threshold

**Baseline feasibility (no tickets):** MEDIUM

- Network-wide requires overcoming provider backbone (15% fetch full data independently)
- Providers will detect unavailability and eventually drop
- 2-provider observation requirement helps
- No hard limit on blob submissions—attack is sustainable

**Impact:** HIGH

- Global blob inclusion degradation
- L2s forced to private channels or calldata fallback
- Public blobpool reputation damage

**Existing Mitigations (Baseline):**

- Provider backbone (15%) independently verifies full availability
- 2+ provider announcement requirement before sampler action
- Transaction age-based eviction

**Gaps:**

- No strong incentive for providers to report unavailability
- Sampler "announces" after fetching custody cells, potentially amplifying attack
- Attack can be sustained by slowly rotating transactions

**Blob tickets mitigation:**

| Aspect                       | Effect                                                                      |
| ---------------------------- | --------------------------------------------------------------------------- |
| **Mechanism**                | Attackers must purchase tickets for each blob; hard cap on concurrent blobs |
| **Sybil Cost**               | Network-wide spam requires purchasing k × N tickets                         |
| **Economic Barrier**         | Attack cost scales with ticket auction clearing price                       |
| **Feasibility with Tickets** | **LOW** — economic barrier makes sustained spam expensive                   |
| **Residual Risk**            | Well-funded attacker could still spam during low-demand periods             |

---

#### T1.3: Bandwidth exhaustion via request amplification

**Description:** Attacker exploits the request/response asymmetry to exhaust victim's upload bandwidth.

**Attack flow:**

1. Attacker peers with victim node
2. Attacker repeatedly requests cells/blobs from victim
3. Attacker varies `cell_mask` to maximize response sizes
4. Attacker never shares received data, continuously re-requests
5. Victim's upload bandwidth saturated, affecting all network participation

**Prerequisites:**

- Direct peering with victim
- Ability to maintain connection despite abuse

**Baseline feasibility (no tickets):** MEDIUM

- `C_req = 8` limits single request to 8 cells × 6 blobs × 2048 bytes ≈ 98 KB
- Repeated requests detectable via frequency monitoring
- Existing devp2p rate limiting applies

**Impact:** MEDIUM

- Individual node degradation
- Cascading effects if targeting multiple nodes

**Existing mitigations (baseline):**

- `C_req = 8` per-request column limit
- Local fairness heuristics (MAY disconnect abusive peers)
- devp2p connection limits

**Gaps:**

- No normative specification for fairness thresholds
- Attacker can maintain multiple connections via Sybil
- Fairness detection requires historical tracking (state overhead)

**Recommendations:**

1. Recommended (not normative) fairness heuristics in spec
2. Exponential backoff on repeated identical requests
3. Request-to-announcement ratio tracking

**Blob tickets mitigation:**

| Aspect                       | Effect                                                               |
| ---------------------------- | -------------------------------------------------------------------- |
| **Mechanism**                | Tickets gate blob propagation, not cell requests                     |
| **Direct Effect**            | Minimal—this attack doesn't require submitting blobs                 |
| **Feasibility with Tickets** | **MEDIUM** — unchanged; attack is about request abuse, not blob spam |
| **Residual Risk**            | Tickets do not address this attack vector                            |

---

#### T1.4: Memory exhaustion via announcement flood

**Description:** Attacker floods victim with `NewPooledTransactionHashes` announcements for non-existent or invalid transactions.

**Attack flow:**

1. Attacker sends massive volume of transaction hash announcements
2. Victim queues announcements for processing
3. Victim attempts to fetch transactions, all fail or timeout
4. Victim's announcement queue / pending request state exhausted

**Prerequisites:**

- Peering with victim
- Ability to generate valid-looking announcement messages

**Baseline feasibility (no tickets):** MEDIUM

- Existing devp2p has announcement rate limiting
- eth/71 adds `cell_mask` (16 bytes) per announcement message
- Not per-transaction, limiting announcement size growth

**Impact:** LOW-MEDIUM

- Memory pressure
- CPU cycles wasted on timeout handling

**Existing Mitigations (Baseline):**

- devp2p announcement rate limiting
- Request timeout handling
- Peer disconnection on abuse

**Blob tickets mitigation:**

| Aspect                       | Effect                                                             |
| ---------------------------- | ------------------------------------------------------------------ |
| **Mechanism**                | Nodes can check if announced tx has valid ticket before fetching   |
| **Pre-fetch Validation**     | Reject announcements for txs from addresses without active tickets |
| **Feasibility with Tickets** | **LOW** — announcements for ticketless blobs can be ignored        |
| **Residual Risk**            | Attacker could buy tickets then flood announcements                |

---

### T2: Data availability manipulation

#### T2.1: Selective withholding (strong variant)

**Description:** Attacker holds complete blob data but selectively withholds cells to prevent reconstruction while appearing legitimate to samplers.

**Attack flow:**

1. Attacker generates valid blob with proper KZG commitments
2. Attacker becomes provider (or fakes provider status)
3. Attacker serves custody-aligned cells to samplers correctly
4. Attacker refuses/timeouts on cells needed for 64-cell reconstruction
5. Blob appears "available" to samplers, but cannot be reconstructed or included

**Prerequisites:**

- Attacker controls provider status announcement
- Knowledge of victim custody sets (predictable from peer data)
- Attacker can selectively respond to cell requests

**Baseline feasibility (no tickets):** MEDIUM

- Sampling noise (C_extra = 1 random column) makes this harder
- Attacker must serve custody cells + random column
- Detection: failure rate on random columns reveals withholder

**Impact:** HIGH

- Blob cannot be included despite appearing available
- Proposer may build invalid block
- Network confidence in availability diminished

**Existing mitigations (baseline):**

- Sampling noise: 1 random column per request catches fake providers
- Multiple provider requirement before sampler commits
- Reconstruction from 47+ samplers (124 expected distinct columns)

**Gaps:**

- Sampling noise currently catches only ~1/128 of selective withholding per request
- Sophisticated attacker can track which random columns each peer requests
- No punishment mechanism for detected withholders beyond disconnection

**Recommendations:**

1. Increase C_extra or randomize C_extra ∈ [1, 4]
2. Track per-peer random column failure rate
3. Consider cryptographic fraud proofs for withholding (future work)

**Blob tickets mitigation:**

| Aspect                       | Effect                                                              |
| ---------------------------- | ------------------------------------------------------------------- |
| **Mechanism**                | Attacker must hold valid ticket to propagate blob                   |
| **Economic Cost**            | Attacker pays ticket price for withholding attack                   |
| **Sybil Limit**              | Cannot spam withheld blobs beyond ticket capacity                   |
| **Feasibility with Tickets** | **MEDIUM** — reduced scale, but core attack still possible per-blob |
| **Residual Risk**            | Each ticket still enables one withholding attack instance           |

---

#### T2.2: Provider spoofing (weak variant)

**Description:** Attacker announces as provider (all-ones `cell_mask`) without holding full blob data.

**Attack flow:**

1. Attacker observes transaction announcement
2. Attacker immediately rebroadcasts with all-ones `cell_mask` (fake provider claim)
3. Samplers count this as valid provider observation
4. When samplers request data, attacker fails/timeouts
5. Samplers may have already committed based on fake provider count

**Prerequisites:**

- Low latency network position to front-run legitimate announcements
- Willingness to accept disconnection when exposed

**Baseline feasibility (no tickets):** HIGH (easy to attempt), LOW (to sustain)

- Easy to claim provider status
- Immediately exposed when cells requested
- Sampling noise guarantees detection

**Impact:** LOW (if mitigations work)

- Temporary confusion about provider count
- Quickly corrected as requests fail

**Existing mitigations (baseline):**

- Sampling noise immediately exposes fake providers
- Request failure triggers peer reassessment
- 2-provider minimum provides redundancy

**Gaps:**

- Brief window where fake provider influences decisions
- Attackers can rotate identities (Sybil)

**Blob tickets mitigation:**

| Aspect                       | Effect                                                         |
| ---------------------------- | -------------------------------------------------------------- |
| **Mechanism**                | Only blobs with valid tickets are propagated                   |
| **Spoofing Cost**            | Spoofing requires ticketed blob to exist first                 |
| **Feasibility with Tickets** | **LOW** — spoofing a non-existent ticketless blob is pointless |
| **Residual Risk**            | Can still spoof ticketed blobs; core behavior unchanged        |

---

#### T2.3: Custody set prediction attack

**Description:** Attacker predicts victim's custody set and provides only those columns, avoiding sampling noise detection.

**Attack flow:**

1. Attacker observes victim's historical cell requests
2. Attacker infers custody set from request patterns
3. Attacker pretends to be provider but only pre-computes custody columns
4. Attacker hopes random column request falls within pre-computed set (1/128 chance per request)
5. If random column isn't available, attacker timeouts

**Prerequisites:**

- Historical observation of victim
- Custody stability (no frequent changes)

**Baseline feasibility (no tickets):** LOW

- C_extra is RANDOM, not custody-aligned
- Probability of guessing C_extra column: 1/128 per transaction
- Detection rate: 127/128 ≈ 99.2% per transaction

**Impact:** LOW

- Sampling noise specifically designed for this

**Existing mitigations (baseline):**

- Random column selection for noise
- Custody set unknown to peers (only custody-aligned requests reveal it)
- CL custody set changes propagate via `engine_blobCustodyUpdatedV1`

**Blob tickets mitigation:**

| Aspect                       | Effect                                                           |
| ---------------------------- | ---------------------------------------------------------------- |
| **Mechanism**                | Not directly applicable—attack targets sampling, not propagation |
| **Feasibility with Tickets** | **LOW** — unchanged; tickets don't affect custody prediction     |
| **Residual Risk**            | Attack inherently limited by sampling noise design               |

---

#### T2.4: Reconstruction threshold attack

**Description:** Attacker ensures exactly 63 or fewer columns are available network-wide, preventing Reed-Solomon reconstruction.

**Attack flow:**

1. Attacker controls blob submission
2. Attacker publishes blob to network via blobpool
3. Attacker selectively serves columns to ensure <64 distinct columns exist
4. No single entity can reconstruct; blob is "phantom available"

**Prerequisites:**

- Eclipse-like control over initial propagation
- Ability to prevent any 64+ column collection

**Baseline feasibility (no tickets):** VERY LOW

- With D=50 mesh, samplers provide ~125 expected distinct columns
- Attacker would need to eclipse majority of initial receivers
- Provider backbone (15%) independently fetches full data

**Impact:** HIGH (if successful)

- Blob cannot be included
- Cascading impact on dependent transactions

**Existing mitigations (baseline):**

- Provider backbone guarantees some nodes have full data
- Redundancy from multiple provider observations
- Supernode behavior specification

**Blob tickets mitigation:**

| Aspect                       | Effect                                                                         |
| ---------------------------- | ------------------------------------------------------------------------------ |
| **Mechanism**                | Ticket limits how many blobs attacker can target                               |
| **Feasibility with Tickets** | **VERY LOW** — unchanged; attack already requires eclipse-level control        |
| **Residual Risk**            | Core attack is already impractical; tickets add cost but don't change dynamics |

---

### T3: Protocol gaming

#### T3.1: Free-riding on samples

**Description:** Node always chooses sampler role to minimize bandwidth while benefiting from network.

**Attack flow:**

1. Node manipulates RNG or ignores probabilistic role selection
2. Node always samples (85% bandwidth reduction)
3. Node never serves full blobs, only custody cells
4. Network providers subsidize free-rider

**Prerequisites:**

- Malicious client modification
- Ability to evade detection

**Baseline feasibility (no tickets):** HIGH (easy to implement), MEDIUM (detection)

- No cryptographic commitment to role
- Statistically detectable over time
- Per-node role is deterministic per transaction (hash-based)

**Impact:** MEDIUM (individual), HIGH (if widespread)

- Single free-rider: minor impact
- Widespread: provider backbone collapses, p effectively drops below 0.15

**Existing mitigations (baseline):**

- Local fairness heuristics (request-to-announcement ratio)
- Statistical detection possible
- Spec recommends disconnect for excessive sampling

**Gaps:**

- No normative enforcement
- Detection requires long observation window
- Implementation diversity makes detection harder

**Recommendations:**

1. Hash-based role determination provides verifiability:
   `role = H(node_id || tx_hash || epoch) < p × 2^256`
2. Peers could challenge role claims
3. Consider reputation/scoring despite current spec avoiding this

**Blob tickets mitigation:**

| Aspect                       | Effect                                                                      |
| ---------------------------- | --------------------------------------------------------------------------- |
| **Mechanism**                | Tickets don't affect role selection behavior                                |
| **Feasibility with Tickets** | **HIGH** — unchanged; free-riding is about role gaming, not blob submission |
| **Residual Risk**            | Tickets do not address this attack vector                                   |

---

#### T3.2: Announcement manipulation

**Description:** Node manipulates `cell_mask` announcements to gain advantage.

**Scenarios:**

- **Over-announcing:** Claim more columns than held → exposed on request, disconnected
- **Under-announcing:** Claim fewer columns than held → reduces own value to peers, self-harm
- **Stale announcements:** Announce old availability → time-based staleness detection

**Baseline feasibility (no tickets):** LOW (self-defeating or easily caught)

**Impact:** LOW

**Existing mitigations (baseline):**

- Request verification immediately exposes over-claiming
- Under-announcing is self-harm

**Blob tickets mitigation:**

| Aspect                       | Effect                                     |
| ---------------------------- | ------------------------------------------ |
| **Mechanism**                | Tickets don't affect announcement behavior |
| **Feasibility with Tickets** | **LOW** — unchanged                        |
| **Residual Risk**            | Not applicable                             |

---

#### T3.3: Role timing manipulation

**Description:** Sampler delays commitment until observing sufficient providers, then never contributes.

**Attack flow:**

1. Sampler waits for exactly 2 provider announcements
2. Sampler fetches custody cells
3. Sampler never reannounces (violating MUST)
4. Sampler consumes bandwidth without contributing to propagation

**Prerequisites:**

- Protocol violation (ignoring reannouncement MUST)

**Feasibility:** HIGH (easy to violate)

**Impact:** LOW (individual), MEDIUM (widespread)

- Reduces network saturation speed
- Increases propagation latency

**Existing Mitigations:**

- Spec uses MUST for reannouncement
- Peer tracking could detect non-announcers
- Natural detection: peer that requests but never announces

**Gaps:**

- No enforcement mechanism beyond disconnection
- Tracking adds state overhead

---

### T4: Network-level attacks

#### T4.1: Eclipse attack on sparse blobpool

**Description:** Attacker isolates victim node from honest network, controlling all peer connections.

**Attack flow:**

1. Attacker Sybils victim's peer table
2. Attacker controls all D=50 connections
3. Attacker feeds victim manipulated blobpool state
4. Victim's view diverges from honest network

**Sparse-specific implications:**

- Attacker can provide false provider counts
- Attacker can selectively provide/withhold cells
- Attacker can force victim into always-sampler role view

**Prerequisites:**

- Significant Sybil capacity (50+ controlled nodes)
- Ability to eclipse despite existing protections

**Feasibility:** LOW (existing eclipse protections)

**Impact:** CRITICAL (for victim)

**Existing mitigations:**

- Standard eclipse attack mitigations (connection diversity, peer table protection)
- Sparse blobpool inherits all devp2p protections
- Multiple provider observation requirement provides some redundancy

**Gaps:**

- Sparse blobpool adds no NEW eclipse protections
- More valuable attack target (can manipulate availability perception)

---

#### T4.2: Selective availability signaling attack (nonce gap variant)

> **Source:** Analysis refined from [adversarial-peers.md](file:///Users/raul/W/ethereum/sparse-blobpool-sim/specs/adversarial-peers.md)

**Description:** Attacker connects k nodes to victim, signals availability **exclusively to the victim** while withholding from the rest of the network. The attacker then chains sequential transactions (A0, A1, A2...) using the same sender address, poisoning the victim's blobpool with transactions that will never be included.

**Detailed attack flow:**

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ PHASE 1: Connection Establishment                                           │
├─────────────────────────────────────────────────────────────────────────────┤
│ 1. Attacker connects k nodes to victim (where k = minimum provider signals) │
│    - Geth typical: 34 inbound / 16 outbound connections                     │
│    - Connection churn: 1 random drop every 3-7 minutes                      │
│    - Attacker must maintain k connections; feasibility TBD                  │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ PHASE 2: Initial Transaction Injection (A0)                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│ 2. Attacker creates blob tx A0: {address: A, nonce: 0}                      │
│ 3. Attacker announces A0 to victim with k availability signals              │
│    ⚠️ KEY: Attacker does NOT signal availability to rest of network        │
│                                                                             │
│ 4. PROBABILITY BRANCH:                                                      │
│    ┌─────────────────────────────┬────────────────────────────────────────┐ │
│    │ WITH PROB p (15%)           │ WITH PROB 1-p (85%)                    │ │
│    │ Victim requests FULL FETCH  │ Victim requests PARTIAL FETCH          │ │
│    ├─────────────────────────────┼────────────────────────────────────────┤ │
│    │ Attacker options:           │ Attacker nodes respond with cells      │ │
│    │ a) Abort, find new victim   │                                        │ │
│    │ b) Respond (pay cost),      │ Victim stores A0 in blobpool           │ │
│    │    continue attack          │ Victim announces A0 to neighbors       │ │
│    │                             │                                        │ │
│    │ If (a): Return to Phase 1   │ But neighbors lack k signals           │ │
│    │ If (b): Attack succeeds     │ → A0 FAILS to propagate beyond victim  │ │
│    │         with 100% cost      │                                        │ │
│    └─────────────────────────────┴────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼ (Attack proceeds if 85% branch or b)
┌─────────────────────────────────────────────────────────────────────────────┐
│ PHASE 3: Transaction Chaining (A1, A2, ...)                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│ 5. Attacker creates A1: {address: A, nonce: 1}, announces to victim        │
│                                                                             │
│ 6. REGARDLESS of victim's fetch decision:                                   │
│    - If FULL FETCH (15%): Attacker responds, victim announces              │
│      BUT neighbors reject A1 as "gapped tx" (they don't have A0)           │
│    - If PARTIAL FETCH (85%): Same outcome as Phase 2                        │
│                                                                             │
│ 7. Result: A1 stored ONLY in victim's blobpool, not propagated             │
│ 8. Repeat for A2, A3, ... up to 16-tx limit per address                    │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ OUTCOME                                                                     │
├─────────────────────────────────────────────────────────────────────────────┤
│ • Victim's blobpool contains up to 16 txs from address A                   │
│ • These txs will NEVER be included (rest of network doesn't have them)     │
│ • Victim CANNOT identify attacker nodes as malicious:                      │
│   - Attacker nodes responded correctly to all requests                      │
│   - No detectable protocol violation from victim's local view              │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Prerequisites:**

- Attacker can establish k peer connections with victim
- k = minimum availability signals required (likely 2-4)
- Attacker controls transaction sender address

**Connection establishment feasibility analysis:**

| Factor                 | Analysis                                                        |
| ---------------------- | --------------------------------------------------------------- |
| **Inbound slots**      | Geth: 34 inbound typical (2/3 of MaxPeers=50)                   |
| **Connection churn**   | 1 random connection dropped every 3-7 minutes                   |
| **Attack window**      | Attacker needs to maintain k connections for attack duration    |
| **Difficulty for k=2** | LOW - occupying 2 of 34 inbound slots is straightforward        |
| **Difficulty for k=4** | MEDIUM - requires more Sybil nodes, still achievable            |
| **Trade-off**          | Increasing k hardens attack but may hurt propagation or raise p |

**Attack success probability:**

- Per-attempt success rate: **85%** (probability victim is sampler for A0)
- If attacker willing to pay full blob cost: **100%** (serve full data when requested)
- Once A0 succeeds, all subsequent A1, A2, ... succeed regardless of p

**Attacker indistinguishability (critical observation):**

> From the victim's perspective, the attacker nodes have **followed protocol correctly**:
>
> - They announced availability
> - They responded to data requests
> - They served requested cells
>
> There is **no local signal** that distinguishes malicious peers post-attack. The victim cannot identify which transactions are attack transactions vs. legitimate transactions that failed to propagate for other reasons.

**Attack repeatability:**

| Question                                    | Analysis                                                 |
| ------------------------------------------- | -------------------------------------------------------- |
| **Can attacker repeat with new address B?** | Yes, if k connections maintained                         |
| **Rate limiting factor**                    | Connection churn (3-7 min) may disrupt sustained attacks |
| **Maximum damage per attack**               | 16 txs × ~128KB = ~2MB per sender address                |
| **Blobpool capacity**                       | 2GB = ~15,000 attack transactions before full            |
| **Attack duration for full DoS**            | ~940 sender addresses needed (with 16 txs each)          |
| **Sybil address cost**                      | Only gas for transactions, blobs never included          |

**Feasibility:** HIGH for targeted attacks, MEDIUM for full blobpool DoS

- 85% success rate per attempt
- Low cost (gas for tx portion only)
- Principal limitation: maintaining k connections over time

**Impact:** MEDIUM-HIGH

- Victim's blobpool service degraded
- blob building affected
- getBlobs API serving impacted
- Does NOT affect chain finality or liveness
- May require operator intervention to recover (restart, clear blobpool)

**Existing Mitigations:**

- 16 pending transaction limit per address
- Transaction age eviction (eventually cleans old txs)
- 2GB blobpool total limit

**Gaps:**

- No mechanism to detect "selectively available" transactions
- No proactive eviction for transactions with low network saturation
- Attacker indistinguishability post-attack makes cleanup hard
- Connection establishment too easy for small k values

**Recommendations:**

1. **Time-based saturation eviction:** Drop sampled txs if not observed from multiple independent peers after timeout
2. **Contribution-based peer scoring (from adversarial-peers.md):**
   - Prioritize availability signals from high-score peers
   - Score accrues via: connection stability + contribution of includable blobs
   - New peers/low-score peers require longer observation or higher k
3. **Lengthen attacker cycle time:**
   - Combine peer scoring with eviction and 16-tx cap
   - Make repeated attacks require waiting periods between attempts
4. **Specify 16-tx cap in EIP:** This implementation detail is critical for DoS resistance but not currently in spec
5. **Track per-sender propagation success:** If A0 from sender A never observed elsewhere, flag as suspicious

---

#### T4.3: Geographic/network partitioning

**Description:** Exploit network topology to create regions with different blobpool views.

**Attack flow:**

1. Attacker positions nodes at network partition boundaries
2. Attacker selectively propagates blobs to some regions
3. Different regions have different availability views
4. Proposers in different regions build different blocks

**Prerequisites:**

- Knowledge of network topology
- Positioned nodes at chokepoints

**Feasibility:** LOW

- Internet topology is resilient
- Ethereum network is well-connected
- Sparse blobpool doesn't change this substantially

**Impact:** MEDIUM

- Temporary divergence
- Eventually reconciled

---

### T5: Proposer-targeted attacks

#### T5.1: Proposer deanonymization via fetching patterns

**Description:** Upcoming proposer reveals identity through eager blob fetching behavior.

**Attack flow:**

1. Attacker monitors network for anomalous fetching patterns
2. Upcoming proposer deviates from p=0.15 (fetches more to ensure availability)
3. Attacker identifies statistical anomaly
4. Attacker targets proposer (DoS, front-running, etc.)

**Prerequisites:**

- Network-wide observation capability
- Statistical analysis infrastructure

**Feasibility:** MEDIUM

- Proposer "proactive" policy explicitly fetches more
- Anomaly detectable: node suddenly fetching 100% vs. 15%
- Slot-correlated pattern analysis

**Impact:** MEDIUM-HIGH

- Proposer privacy violated
- Enables targeted attacks timing to slot

**Existing Mitigations:**

- Conservative policy: include only fully-available (same as today)
- Local builder flag hides proposer behavior behind builder

**Gaps:**

- Proactive policy explicitly creates this risk
- ePBS doesn't fully solve (proposer still receives block from builder)
- Optimistic policy creates intermediate risk

**Recommendations:**

1. Avoid proactive policy in default configurations
2. If proactive needed, use privacy-preserving fetch patterns
3. Document risk in EIP security considerations

---

#### T5.2: Force unavailable blob inclusion

**Description:** Trick proposer into including blob that will fail CL data availability check.

**Attack flow:**

1. Attacker submits blob to blobpool
2. Attacker ensures proposer has sampled successfully
3. Attacker withholds full data from broader network
4. Proposer includes blob (optimistic policy)
5. Attesters fail DA check, block orphaned
6. Proposer loses slot reward

**Prerequisites:**

- Proposer using optimistic or proactive policy
- Attacker can selectively withhold without detection

**Feasibility:** MEDIUM

- Conservative policy immune
- Optimistic policy vulnerable
- Sampling noise provides some protection

**Impact:** HIGH

- Missed slot
- Proposer economic loss
- Network liveness impact

**Existing mitigations:**

- Conservative policy: only include fully-available
- Proactive resampling before proposal
- Multiple provider confirmation

**Gaps:**

- Optimistic policy explicitly accepts this risk
- Trade-off between inclusion rate and validity risk
- No punishment for attackers

**Recommendations:**

1. Default to conservative policy
2. Implement proactive resampling with strong confidence thresholds
3. Document policy risks in client documentation

---

#### T5.3: Builder-proposer collusion via private blobs

**Description:** Builder submits private blobs, proposer gains unfair timing advantage.

**Attack flow:**

1. Builder receives blobs directly (not via blobpool)
2. Builder provides blobs to proposer privately
3. Proposer blocks competing builders from accessing blobs
4. Market distorted

**Prerequisites:**

- ePBS or PBS environment
- Builder with private blob access

**Feasibility:** Already occurring (80% public, 20% private blobs)

**Impact:** MEDIUM (market efficiency)

**Existing mitigations:**

- Public blobpool provides "blob distribution service" benefiting builders
- Private blobs require builder to handle propagation timing

**Gaps:**

- Sparse blobpool doesn't directly address this
- May exacerbate if public blobpool degrades

---

### T6: Economic attacks

#### T6.1: Ticket hoarding (with blob tickets)

**Description:** Attacker buys all available tickets to censor blob submitters.

**Attack flow:**

1. Attacker monitors ticket contract
2. Attacker bids high priority fees to acquire all k tickets
3. Legitimate blob submitters locked out
4. Attacker wastes or doesn't use tickets

**Prerequisites:**

- Blob ticket mechanism deployed
- Significant capital for priority fees

**Feasibility:** LOW

- First-price auction makes hoarding expensive
- Proposer opportunity cost to exclude
- k tickets × Δ slots = limited window

**Impact:** HIGH (if successful)

- Complete blob censorship
- L2s forced to calldata

**Existing mitigations:**

- Auction mechanism creates cost
- Proposer loses revenue if colluding
- Short validity window (Δ = 2-3 slots)

**Gaps:**

- Rich attacker could absorb costs
- Need robust reserve price mechanism
- Proposer could be the attacker

**Recommendations:**

1. Reserve price tied to blob base fee (EIP-7918)
2. Consider anti-hoarding mechanisms (max tickets per address)
3. Analyze game theory for various k and Δ

---

#### T6.2: RBF exploitation

**Description:** Exploit replace-by-fee semantics in sparse blobpool context.

**Attack flow:**

1. Attacker submits blob tx B1
2. Network propagates; samplers store B1
3. Attacker RBFs with B2 (higher fee, different blob)
4. B1 blob data becomes orphaned but may persist in some nodes
5. Nodes waste resources on obsolete blob data

**Prerequisites:**

- RBF enabled for blob transactions
- Attacker willing to pay higher fees

**Feasibility:** MEDIUM

- Natural RBF behavior
- Sparse exacerbates: samplers hold partial data for B1 that's now worthless

**Impact:** LOW-MEDIUM

- Resource waste
- Potential for targeted attacks (force specific node state)

**Existing mitigations:**

- Standard RBF semantics apply
- Eviction eventually cleans up

**Gaps:**

- No specification for RBF in EIP-8070
- Ticket consumption: should B1 and B2 use same ticket?
- Partial blob data cleanup undefined

**Recommendations:**

1. Define RBF behavior explicitly in spec
2. Same ticket should cover RBF replacements
3. Define cleanup semantics for replaced blob data

---

#### T6.3: Fee manipulation via fake demand

**Description:** Attacker submits unavailable blobs to inflate apparent demand, manipulating base fee.

**Attack flow:**

1. Attacker creates unavailable high-priority blob transactions
2. Transactions enter blobpool, appear as demand
3. Blob base fee mechanism responds to apparent demand
4. Legitimate users pay inflated fees
5. Attacker's blobs never included (unavailable)

**Prerequisites:**

- Fee mechanism responsive to blobpool state
- Ability to create unavailable blobs cheaply

**Feasibility:** LOW

- Base fee responds to actual inclusion, not blobpool state
- Unavailable blobs cannot be included
- 1559 mechanism resilient

**Impact:** LOW

**Existing mitigations:**

- EIP-1559 mechanism updates based on actual block contents
- Blob base fee responds to included blobs, not pending

---

### T7: Implementation-specific attacks

#### T7.1: Inconsistent client behavior

**Description:** Different client implementations handle edge cases differently, creating attack surface.

**Scenarios:**

- Client A considers 2 providers sufficient; Client B requires 3
- Client A has stricter timeout; Client B is lenient
- Client A implements sampling noise; Client B doesn't

**Prerequisites:**

- Client diversity (exists naturally)
- Ambiguous or SHOULD/MAY clauses in spec

**Feasibility:** MEDIUM

- eth/71 is new, implementations will vary
- RECOMMENDED (not MUST) clauses create flexibility

**Impact:** HIGH

- Network fragmentation along client lines
- Targeted attacks on specific clients

**Existing Mitigations:**

- Clear MUST requirements in spec
- Test vectors (TODO in spec)

**Gaps:**

- Several SHOULD/MAY clauses
- No formal test suite yet
- Fairness heuristics left to implementation

**Recommendations:**

1. Develop comprehensive test vectors
2. Minimize SHOULD/MAY where possible
3. Cross-client testing infrastructure

---

#### T7.2: State bloat via long-lived transactions

**Description:** Attacker creates transactions that persist in blobpool indefinitely.

**Attack flow:**

1. Attacker creates valid blob transaction with low fee
2. Transaction is sampled by nodes but never included (fee too low)
3. Transaction persists, consuming memory
4. Repeat to fill available space

**Prerequisites:**

- Low minimum fee threshold
- Weak eviction policies

**Feasibility:** MEDIUM

- Existing eviction based on age and fee
- 2GB cap provides hard limit
- But attack is cheap

**Impact:** LOW-MEDIUM

- Memory pressure
- Degraded blobpool quality

**Existing mitigations:**

- Age-based eviction
- Fee-priority eviction
- 2GB total cap

**Gaps:**

- Optimal eviction policy not specified
- Trade-off: aggressive eviction drops legitimate low-fee txs

---

#### T7.3: KZG/proof verification exploits

**Description:** Attacker crafts malformed KZG commitments or cell proofs to crash or slowloris nodes.

**Attack flow:**

1. Attacker crafts blob with valid-looking but malicious KZG proof
2. Proof triggers edge case in verification library
3. Node crashes, hangs, or wastes excessive CPU

**Prerequisites:**

- Vulnerability in KZG verification implementation
- Ability to bypass initial checks

**Feasibility:** LOW (if implementations are correct)

- KZG libraries heavily audited
- EIP-4844 already deployed, battle-tested

**Impact:** CRITICAL (if exploitable)

- Network-wide crash
- Client diversity provides resilience

**Existing mitigations:**

- Existing EIP-4844/7594 proof verification
- Audited libraries (c-kzg, go-kzg)
- Proof verification before accepting

---

## Attack feasibility assessment

### Baseline assessment (no blob tickets)

| Attack                                | Baseline feasibility           | Impact      | Baseline risk | Baseline priority |
| ------------------------------------- | ------------------------------ | ----------- | ------------- | ----------------- |
| T1.1 Blobpool spam (single)           | HIGH                           | MEDIUM      | HIGH          | **CRITICAL**      |
| T1.2 Network-wide spam                | MEDIUM                         | HIGH        | HIGH          | **CRITICAL**      |
| T1.3 Bandwidth exhaustion             | MEDIUM                         | MEDIUM      | MEDIUM        | MEDIUM            |
| T1.4 Announcement flood               | MEDIUM                         | LOW         | LOW           | LOW               |
| T2.1 Selective withholding            | MEDIUM                         | HIGH        | HIGH          | **CRITICAL**      |
| T2.2 Provider spoofing                | HIGH (attempt) / LOW (sustain) | LOW         | LOW           | LOW               |
| T2.3 Custody prediction               | LOW                            | LOW         | LOW           | LOW               |
| T2.4 Reconstruction threshold         | VERY LOW                       | HIGH        | LOW           | MEDIUM            |
| T3.1 Free-riding                      | HIGH                           | MEDIUM-HIGH | MEDIUM        | MEDIUM            |
| T3.2 Announcement manipulation        | LOW                            | LOW         | LOW           | LOW               |
| T3.3 Role timing                      | HIGH                           | MEDIUM      | MEDIUM        | MEDIUM            |
| T4.1 Eclipse attack                   | LOW                            | CRITICAL    | MEDIUM        | MEDIUM            |
| T4.2 Selective availability signaling | HIGH (targeted)                | MEDIUM-HIGH | **HIGH**      | **CRITICAL**      |
| T4.3 Network partitioning             | LOW                            | MEDIUM      | LOW           | LOW               |
| T5.1 Proposer deanonymization         | MEDIUM                         | MEDIUM-HIGH | **HIGH**      | **HIGH**          |
| T5.2 Force unavailable inclusion      | MEDIUM                         | HIGH        | **HIGH**      | **CRITICAL**      |
| T5.3 Builder collusion                | Already occurs                 | MEDIUM      | MEDIUM        | LOW               |
| T6.1 Ticket hoarding                  | N/A (requires tickets)         | N/A         | N/A           | N/A               |
| T6.2 RBF exploitation                 | MEDIUM                         | LOW         | LOW           | MEDIUM            |
| T6.3 Fee manipulation                 | LOW                            | LOW         | LOW           | LOW               |
| T7.1 Client inconsistency             | MEDIUM                         | HIGH        | **HIGH**      | **HIGH**          |
| T7.2 State bloat                      | MEDIUM                         | LOW         | LOW           | LOW               |
| T7.3 KZG exploits                     | LOW                            | CRITICAL    | MEDIUM        | MEDIUM            |

---

### Comparison: Baseline vs with blob tickets

| Attack                                    | Baseline feasibility | With tickets feasibility | Tickets effect              | Residual risk              |
| ----------------------------------------- | -------------------- | ------------------------ | --------------------------- | -------------------------- |
| **T1.1 Blobpool spam**                    | HIGH                 | **LOW**                  | ✅ Strong mitigation        | Rich attacker              |
| **T1.2 Network-wide spam**                | MEDIUM               | **LOW**                  | ✅ Strong mitigation        | Low-demand periods         |
| T1.3 Bandwidth exhaustion                 | MEDIUM               | MEDIUM                   | ⚪ No effect                | N/A                        |
| T1.4 Announcement flood                   | MEDIUM               | **LOW**                  | ✅ Pre-fetch validation     | Ticketed attackers         |
| **T2.1 Selective withholding**            | MEDIUM               | MEDIUM                   | ⚠️ Limited reduction        | Per-blob attack viable     |
| T2.2 Provider spoofing                    | HIGH/LOW             | LOW                      | ✅ Ticketless blobs ignored | Ticketed blob spoofing     |
| T2.3 Custody prediction                   | LOW                  | LOW                      | ⚪ No effect                | N/A                        |
| T2.4 Reconstruction threshold             | VERY LOW             | VERY LOW                 | ⚪ Minimal effect           | N/A                        |
| T3.1 Free-riding                          | HIGH                 | HIGH                     | ⚪ No effect                | N/A                        |
| T3.2 Announcement manipulation            | LOW                  | LOW                      | ⚪ No effect                | N/A                        |
| T3.3 Role timing                          | HIGH                 | HIGH                     | ⚪ No effect                | N/A                        |
| T4.1 Eclipse attack                       | LOW                  | LOW                      | ⚪ No effect                | N/A                        |
| **T4.2 Selective availability signaling** | HIGH                 | **MEDIUM**               | ✅ Sybil address limit      | Ticket window exploitation |
| T4.3 Network partitioning                 | LOW                  | LOW                      | ⚪ No effect                | N/A                        |
| T5.1 Proposer deanonymization             | MEDIUM               | MEDIUM                   | ⚪ No effect                | N/A                        |
| **T5.2 Force unavailable inclusion**      | MEDIUM               | **LOW**                  | ✅ Ticket cost              | Per-ticket attack viable   |
| T5.3 Builder collusion                    | Already occurs       | Already occurs           | ⚪ No effect                | N/A                        |
| T6.1 Ticket hoarding                      | N/A                  | LOW                      | ⚠️ Introduces new attack    | Auction gaming             |
| T6.2 RBF exploitation                     | MEDIUM               | LOW                      | ⚠️ Same-ticket RBF          | Ticket semantics TBD       |
| T6.3 Fee manipulation                     | LOW                  | LOW                      | ⚪ Minimal effect           | N/A                        |
| T7.1 Client inconsistency                 | MEDIUM               | MEDIUM                   | ⚪ No effect                | N/A                        |
| T7.2 State bloat                          | MEDIUM               | **LOW**                  | ✅ Bounded by tickets       | N/A                        |
| T7.3 KZG exploits                         | LOW                  | LOW                      | ⚪ No effect                | N/A                        |

**Legend:**

- ✅ Strong mitigation — Tickets significantly reduce or eliminate this attack
- ⚠️ Limited/introduces — Tickets provide partial mitigation or introduce new considerations
- ⚪ No effect — Attack vector unaffected by tickets

---

### Priority summary

**CRITICAL priority attacks (baseline, no tickets):**

1. **T1.1 Blobpool Spam** — Mitigated by tickets ✅
2. **T1.2 Network-wide Spam** — Mitigated by tickets ✅
3. **T2.1 Selective Withholding** — Partially mitigated ⚠️
4. **T4.2 Selective Availability Signaling** — Partially mitigated ⚠️
5. **T5.2 Force Unavailable Inclusion** — Mitigated by tickets ✅

**HIGH priority attacks (unchanged by tickets):**

1. **T5.1 Proposer Deanonymization** — Unaffected, requires policy/design changes
2. **T7.1 Client Inconsistency** — Unaffected, requires spec clarity and testing

**New attack introduced by tickets:**

1. **T6.1 Ticket Hoarding** — New censorship vector via ticket acquisition

---

## Tickets: sparse vs full-replication analysis

### Issues in BOTH blobpools (tickets help regardless)

| Issue                 | Full-replication                                                      | Sparse                                   | Tickets fix                        |
| --------------------- | --------------------------------------------------------------------- | ---------------------------------------- | ---------------------------------- |
| **Sybil spam**        | Attacker with many addresses can spam with valid-but-low-priority txs | Same, but cheaper (only partial fetches) | ✅ Hard cap on concurrent blobs    |
| **Nonce gap attacks** | Attacker sends A0, A1... then withholds A0                            | Easier (85% sampler can't verify)        | ✅ Sybil limit on sender addresses |
| **State bloat**       | Low-fee txs persist consuming memory                                  | Same                                     | ✅ Bounded by ticket capacity      |

### Issues CREATED by sparse blobpool (tickets help)

| Issue                                       | Why sparse creates it                                                                | Tickets fix                                                      |
| ------------------------------------------- | ------------------------------------------------------------------------------------ | ---------------------------------------------------------------- |
| **Selective availability signaling (T4.2)** | Sampler (85%) accepts without full verification; can be fed txs that never propagate | ✅ Limits Sybil addresses via ticket requirement                 |
| **Selective withholding (T2.1)**            | Sampler can't detect withheld non-custody cells; must trust provider count           | ⚠️ Partial—limits scale but each ticket still enables one attack |
| **Provider spoofing (T2.2)**                | Fake provider claims matter more when 85% are samplers                               | ✅ Can ignore announcements for ticketless blobs                 |

### Issues CREATED by sparse blobpool (tickets DON'T help)

| Issue                               | Why sparse creates it                                         | Why tickets don't help                     |
| ----------------------------------- | ------------------------------------------------------------- | ------------------------------------------ |
| **Free-riding (T3.1)**              | Always-sampler saves 85% bandwidth                            | Attack is role gaming, not blob submission |
| **Proposer deanonymization (T5.1)** | Proactive policy reveals upcoming proposer via fetch patterns | Attack is observation, not submission      |
| **Client inconsistency (T7.1)**     | New eth/71 has SHOULD/MAY clauses                             | Implementation diversity, not economic     |

### Issues INTRODUCED by tickets

| Issue                      | Description                                                  |
| -------------------------- | ------------------------------------------------------------ |
| **Ticket hoarding (T6.1)** | New attack—buy all tickets to censor blobs                   |
| **RBF semantics**          | Unspecified—should B1→B2 replacement use same or new ticket? |
| **UX degradation**         | Rollups must buy tickets in advance vs current "just submit" |
| **Gas overhead**           | Ticket purchase txs consume gas                              |

### Why tickets are MORE valuable for sparse than full-replication

1. **Samplers (85%) can't independently verify full availability** — in full-replication, every node sees every blob, so unavailable blobs are rejected immediately
2. **Attack surface for spam/poisoning is larger** — most nodes only see partial data
3. **Without tickets, attack cost doesn't scale** — attacker pays gas but never blob fees (blob not included)

In full-replication, the main ticket benefit would be spam reduction, but the attack surface is smaller since detection is instant.

---

## Cross-cutting concerns

### Interaction with ePBS

The sparse blobpool introduces complexity when combined with ePBS:

- Builders hold blobs, not proposers
- Private blob channels bypass sparse blobpool entirely
- Distributed blob custody needs reconsideration
- Major CL refactor required for full integration

**Recommendation:** Document sparse blobpool behavior under ePBS explicitly.

### Supernode behavior

Supernode specification is minimal but critical:

- Must load balance across samplers AND providers
- Should reconstruct from 64 columns when possible
- Need larger peerset for increased needs

**Gaps:**

- No specification for supernode discovery/identification
- Abusive supernodes could violate fairness
- Should supernodes pay premium?

### Backwards compatibility transition

During eth/70 → eth/71 transition:

- Mixed network with full-replication and sparse nodes
- Attack surface during transition period
- Nodes not upgraded may have degraded view

**Recommendation:** Define transition period behavior and monitoring.

### Parameter sensitivity

Key parameters with security implications:

| Parameter                   | Value      | Impact of change                                        |
| --------------------------- | ---------- | ------------------------------------------------------- |
| p (provider probability)    | 0.15       | Lower = more vulnerability to availability attacks      |
| D (mesh degree)             | 50         | Lower = reduced reliability guarantees                  |
| k (tickets per slot)        | ~MAX_BLOBS | Higher = more spam potential                            |
| Δ (ticket validity)         | 2-3 slots  | Longer = more buffered spam                             |
| C_extra (noise columns)     | 1          | Higher = better fake provider detection, more bandwidth |
| C_req (max columns/request) | 8          | Higher = more bandwidth per request, easier DoS         |

---

## Open questions & research gaps

### Specification gaps

1. **RBF Handling:** How should replace-by-fee work with sparse blobpool and tickets?
2. **Eviction Policies:** What are the optimal eviction heuristics for samplers?
3. **Fairness Enforcement:** Should fairness thresholds be normative?
4. **Supernode Discovery:** How should the network identify and treat supernodes?

### Theoretical questions

1. **Provider Backbone Analysis:** What is the minimum viable p for network stability?
2. **Attack Cost Modeling:** What is the economic cost to sustain various attacks?
3. **Game Theoretic Equilibria:** Is p=0.15 incentive-compatible long-term?
4. **Information Theoretic Bounds:** What's the minimum information leakage about custody sets?

### Implementation questions

1. **Cross-Client Testing:** What test vectors are needed for eth/71 compliance?
2. **Performance Bounds:** What are the CPU/memory requirements for cell proof verification?
3. **Monitoring Requirements:** What metrics should nodes expose for operator visibility?

### Future research

1. **Cryptographic Fraud Proofs:** Can we prove withholding without revealing custody?
2. **Decentralized Provider Scoring:** Reputation without gaming?
3. **Adaptive Parameters:** Should p adjust based on network conditions?
4. **Horizontal Sharding Comparison:** Under what conditions is horizontal sharding preferable?

---

## Appendix: Attack trees

### A1: Goal: Prevent blob inclusion

```
Prevent Blob Inclusion
├── DoS attacking blobpool
│   ├── Spam single node (T1.1)
│   └── Network-wide spam (T1.2)
├── Withhold data
│   ├── Selective withholding as provider (T2.1)
│   ├── Provider spoofing (T2.2)
│   └── Reconstruction threshold attack (T2.4)
├── Economic attacks
│   ├── Ticket hoarding (T6.1)
│   └── Ticket auction manipulation
└── Network attacks
    ├── Eclipse victim (T4.1)
    └── Nonce gap attack (T4.2)
```

### A2: Goal: Force invalid block

```
Force Invalid Block Proposal
├── Trick proposer into including unavailable blob
│   ├── Fake provider announcements (T2.2)
│   ├── Selective withholding after sampling (T2.1)
│   └── Exploit optimistic policy (T5.2)
└── Corrupt proposer's blobpool view
    ├── Eclipse attack (T4.1)
    └── Targeted poisoning (T4.2)
```

### A3: Goal: Deanonymize proposer

```
Proposer Deanonymization
├── Observe eager fetching pattern
│   ├── Monitor for 100% vs 15% fetch rate
│   └── Correlate with upcoming slot assignment
├── Exploit proactive policy
│   └── Detect resampling burst before slot
└── Indirect inference
    └── Observe mempool queries, builder connections
```

---

## Version history

| Version | Date       | Changes                                                                                                                                                                |
| ------- | ---------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 0.1     | 2025-12-29 | Initial comprehensive threat model                                                                                                                                     |
| 0.2     | 2025-12-29 | Refined T4.2 with adversarial-peers.md analysis: detailed attack flow, connection feasibility, attacker indistinguishability, repeatability framework                  |
| 0.3     | 2025-12-29 | Restructured for baseline (no tickets) analysis; added Blob Tickets Mitigation section to each attack; split assessment table into baseline vs with-tickets comparison |

---

## References

1. [EIP-8070: Sparse Blobpool](file:///Users/raul/W/ethereum/sparse-blobpool-sim/specs/eip-8070.md)
2. [Sparse Blobpool Meeting Notes](file:///Users/raul/W/ethereum/sparse-blobpool-sim/specs/sparse-blobpool-meeting.md)
3. [Sparse Blobpool Meeting 2 Notes](file:///Users/raul/W/ethereum/sparse-blobpool-sim/specs/sparse-blobpool-meeting-2.md)
4. [Sparse-mempool with Blobpool Tickets](file:///Users/raul/W/ethereum/sparse-blobpool-sim/specs/Sparse-mempool%20with%20Blobpool%20tickets.md)
5. [Blob Ticket FAQ & Resources](file:///Users/raul/W/ethereum/sparse-blobpool-sim/specs/Blob%20Ticket%20FAQ%20%26%20Resources%202d8d9895554181d4b095c772242c7ba8.md)
6. [Variants of Mempool Tickets - Ethereum Research](https://ethresear.ch/t/variants-of-mempool-tickets/23338)
7. [On the Future of the Blob Mempool - Ethereum Research](https://ethresear.ch/t/on-the-future-of-the-blob-mempool/22613)
8. [Sparse Blobpool Adversarial Peers Analysis](file:///Users/raul/W/ethereum/sparse-blobpool-sim/specs/adversarial-peers.md)
