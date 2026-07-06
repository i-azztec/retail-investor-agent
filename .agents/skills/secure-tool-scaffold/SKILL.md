---
name: secure-tool-scaffold
description: Scaffold a new deterministic tool with input validation, citations, and honesty notes to the project's secure standard.
---

# Secure tool scaffold

Every tool in `app/tools/*` is a pure, testable function returning a typed
contract. Follow the secure-coding standard (see `.agents/CONTEXT.md`).

## Steps

1. Validate inputs first: reuse `validate_ticker` / `validate_etf_ticker`; coerce
   and bound numeric ranges (amount, years, ratios). Reject rather than guess.
2. No shell/`eval`/`exec`; no f-string SQL; no network unless the tool is the
   live-data owner (then add cache + fallback like `ticker_card`).
3. Return a typed `*Result` from `app/contracts.py`. Attach a `Citation` for
   every externally-sourced number (regulator > issuer > Wikipedia).
4. Data policy: default to deterministic `cache` mode so tests/demos are stable;
   gate live fetching behind an env flag.
5. Keys only from env/.env — never hardcode (semgrep rule enforces this).

## Acceptance

- Unit test covers happy path + invalid input rejection.
- `semgrep --error --config .semgrep/rules.yaml` is clean.
