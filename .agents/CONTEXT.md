# Project context for coding agents

Retail-investor research agent (Kaggle AI Agents capstone). ADK multi-agent core
over deterministic finance tools, FastAPI + contract-first React panel.

## Architecture in one line

`POST /api/ask -> answer_query_adk -> agent_runtime.run (injection-guard -> router
LlmAgent -> Python tool dispatch -> analyst‖skeptic -> narrator -> assemble ->
disclaimer-guard -> memory)`, with a deterministic legacy fallback behind
`AGENT_MODE`.

## Non-negotiables

1. **Numbers come from tools, not LLMs.** LLMs only route and write language.
   Every number is citable and unit-tested.
2. **Contract stays stable.** `ResponsePanel`/`Block` and endpoints don't change
   shape; the frontend renders by block `type`.
3. **Everything new is behind `AGENT_MODE`**, with a fallback to the legacy path.
   The 116 baseline tests run in legacy mode and must stay green.
4. **Lazy imports** for ADK/LiteLlm/mcp so the app imports and tests run without
   those packages or an API key.

## Secure coding standard

- Validate & bound all tool inputs; reject bad input, never guess.
- No `shell=True`, `eval`, `exec`, or string-built SQL.
- Secrets only from env/.env (`.env` is gitignored). semgrep blocks hardcoded
  keys; pre-commit runs it. Remediate findings before commit.
- Two LLM guardrails: injection-guard (in) + disclaimer-guard (out).
- Rate-limit is enforced at the API middleware.

## Where things live

- Agents: `app/agent.py` (declarations), `app/agent_runtime.py` (orchestration).
- Router↔tools: `app/agent_tools.py`. Model factory: `app/models.py`.
- Tools: `app/tools/*`. Contracts: `app/contracts.py`. Assembler: `app/assemble.py`.
- Security: `app/security.py`, `.semgrep/`, `threat_model.md`.
- MCP: `app/mcp_server.py`. Memory: `app/memory.py`. Eval: `eval/`.
