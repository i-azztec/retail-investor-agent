---
name: panel-contract-builder
description: Build a new ResponsePanel/Block for an intent without breaking the contract-first frontend.
---

# Panel contract builder

The frontend renders a `ResponsePanel` purely by block `type` (see
`app/contracts.py`). Presentation is swappable; never leak rendering concerns
into tools.

## Steps

1. Pick the intent (extend `contracts.Intent` literal only if truly new).
2. Compute all numbers in a **tool** (`app/tools/*`) that returns a typed
   `*Result` — never let an LLM invent a number.
3. Add a `build_<intent>_panel(query, result, *, narr, pros, cons, cached,
   latency_ms)` in `app/assemble.py`. Use existing blocks (`KpiBlock`,
   `chart.*`, `scorecard`, `traffic_light`, `text`) — keep ≤ ~6 blocks.
4. Wire it into `assemble.build(state)`'s intent dispatch.
5. Every number-bearing block gets a `citation_id` pointing at a `Citation`.
6. Add `honesty_notes`; the disclaimer guard adds the not-advice line.

## Acceptance

- `assemble.build({...})` returns a valid `ResponsePanel`.
- A unit test constructs the tool result and asserts block types + citations.
- 116+ existing tests stay green.
