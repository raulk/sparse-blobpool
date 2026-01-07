# AGENTS.md

Guidelines for AI agents working on the sparse blobpool simulator.

## Project overview

This is a discrete event simulator for EIP-8070 sparse blobpool protocol. Key components:

- `sparse_blobpool/core/` - Simulator engine, Actor base, Network with CoDel
- `sparse_blobpool/actors/` - Actor implementations (Node in `honest.py`, BlockProducer)
- `sparse_blobpool/p2p/` - Topology generation
- `sparse_blobpool/protocol/` - eth/71 messages, blobpool state
- `sparse_blobpool/scenarios/` - Runnable simulation scenarios
  - `baseline.py` - Honest network scenario
  - `attacks/` - Attack scenarios with self-contained adversary logic
    - `spam.py` - T1.1/T1.2 spam flood attack
    - `withholding.py` - T2.1 selective column withholding
    - `poisoning.py` - T4.2 targeted availability signaling
- `sparse_blobpool/fuzzer/` - Fuzzer autopilot for continuous randomized testing
- `fuzzer_ui/` - Web monitoring dashboard
  - `backend/` - FastAPI + WebSockets (Python, uv)
  - `frontend/` - React + TypeScript + Vite + TailwindCSS (pnpm)
- `tests/` - 210+ tests with hypothesis property-based testing

## Project-specific overrides

**Python 3.14+** required (overrides global 3.12+ default).

**Property-based tests** live in `tests/test_role_distribution.py`.

## Change scope

Adapt to the task:

- **Bug fixes**: Minimal, focused diffs. Don't refactor unrelated code.
- **Refactoring**: Broader changes acceptable. Maintain behavior, improve structure.
- **New features**: Follow existing patterns. Propose new patterns only with justification.
