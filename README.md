# Retail Investor Agent

**A read-only second opinion for beginner retail investors — grounded, cited, and
built needs-first.**

Turn a finance question into an interactive **`ResponsePanel`**: charts,
citations, assumptions, a balanced *for / against*, ELI5 framing, and clickable
ticker/term drill-downs. The reasoning is a real **ADK multi-agent** graph; the
**numbers are computed by deterministic tools**, so every value stays citable and
unit-tested — the LLM only produces language.

> Educational capstone prototype — **not investment advice**. Read-only: it
> informs, it never trades.

---

## Problem & solution

Beginner investors keep asking for the same thing: a **free, no-login, honest**
second opinion they can actually read — and they're scared of AI getting numbers
wrong (*"prison time if there are errors"*, *"IRS audit due to a hallucination"*).
We read ~350 real Reddit posts/comments and built the agent around those needs:
**verifiable numbers, plain-language ELI5, an always-on bear case, and clickable
proof on every figure.** It targets the **Concierge** criteria — a personal, safe
assistant that analyses *your* holdings from public data only, with no broker
login and no PII. Full story: [`docs/PRODUCT.md`](docs/PRODUCT.md).

## What works now

- **ETF overlap** — `I hold VOO, QQQ and VGT — how much do they really overlap?`
- **Forensic red-flag screen** — `Should I buy NVDA? Show forensic red flags and the bear case.`
- **Fee calculator** — `I have $50,000 over 30 years at 0.25% expense ratio and 6% return — am I overpaying?`
- **Ticker cards** — `Tell me about TSLA.`
- **Glossary cards** — `Explain expense ratio simply.`
- **Landing page** — market-desk shelves, live/seed news, and generated demo questions.

Some data (ETF holdings, forensic inputs, dense charts) is cached for demo
reliability; the UI surfaces this through honesty notes and citations.

## Screenshots

<!-- SCREENSHOT GROUP: product overview — same files as docs/PRODUCT.md galleries -->
<p>
  <a href="docs/img/landing-full.png"><img src="docs/img/landing-thumb.png" width="240" alt="Landing page"></a>
  <a href="docs/img/overlap-heatmap-full.png"><img src="docs/img/overlap-heatmap-thumb.png" width="240" alt="ETF overlap"></a>
  <a href="docs/img/forensic-scores-full.png"><img src="docs/img/forensic-scores-thumb.png" width="240" alt="Forensic screen"></a>
  <a href="docs/img/ticker-card-full.png"><img src="docs/img/ticker-card-thumb.png" width="240" alt="Ticker card"></a>
</p>

*(Thumbnails open full-size. See [`docs/PRODUCT.md`](docs/PRODUCT.md) for the
full gallery and [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for backend
screenshots — API docs, database viewer, eval run, Cloud Run.)*

---

## Architecture at a glance

```text
React/Vite static shell
  -> FastAPI (/api/ask, rate-limited, durable turn store)
  -> answer_query_adk  (AGENT_MODE flag; legacy deterministic path is the fallback)
  -> ADK multi-agent:
       injection-guard
         -> router (LlmAgent, output_schema)                 # replaces a regex router
         -> tool dispatch  (deterministic Python  OR  agent-invoked FunctionTool)
         -> analyst ‖ skeptic  (ParallelAgent)  -> narrator
       assembler -> disclaimer-guard -> universal ResponsePanel
  Context flows THROUGH persistent ADK Session state + long-term Memory.
```

The agent layer is **real, not decorative**: an ADK `LlmAgent` router replaces the
brittle regex router, an honest `ParallelAgent` runs analyst‖skeptic, a narrator
writes the beginner headline/ELI5/follow-ups, and (behind a flag) the agent
**itself invokes** an ADK `FunctionTool` — optionally over **MCP**. Numbers are
still computed by deterministic tools, so grounding never depends on the model.

Deep dive, diagrams, and the **course-concept → file mapping**:
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

### Course concepts demonstrated (rubric needs ≥ 3; this project has ~7)

| Concept | Where |
|---|---|
| **Multi-agent (ADK)** | `app/agent.py` — router → analyst‖skeptic → narrator, each with `output_schema` |
| **Agent tool use (function calling)** | `app/function_tools.py`, `agent.build_tool_agent` — the agent invokes a `FunctionTool` |
| **MCP** | `app/mcp_server.py` (FastMCP server) + `MCPToolset` consumption |
| **Sessions & Memory** | persistent `DatabaseSessionService` + `app/memory_service.py` (long-term) |
| **Security** | `app/security.py`, `.semgrep/`, `threat_model.md`, rate-limit in `server/main.py` |
| **Deployability** | `Dockerfile` + Cloud Run (below) |
| **Agent skills** | `.agents/skills/*/SKILL.md`, `.agents/CONTEXT.md` |
| **Evaluation** | `eval/run_eval.py` — router accuracy + LLM-as-judge + trajectory |

Core source files:

- `app/contracts.py` — pydantic contracts for panels, blocks, tool results, agent schemas.
- `app/tools/` — deterministic tools (overlap, forensic scores, calculators, glossary, ticker cards).
- `app/agent.py` / `app/agent_runtime.py` — ADK agent declarations + in-process orchestration.
- `app/agent_tools.py` — `RouteIntent` schema + deterministic router→tool dispatch (grounding fallback).
- `app/function_tools.py` — ADK `FunctionTool`s the agent can invoke itself.
- `app/models.py` — provider factory (Gemini native, or an OpenAI-compatible model via LiteLlm).
- `app/security.py` — injection-guard + disclaimer-guard.
- `app/store.py` — durable SQLite turn store (forum-style shareable links) + interest profiles.
- `app/memory_service.py` / `app/personalize.py` — long-term Memory + risk-profile framing.
- `app/mcp_server.py` — external MCP interface to the tools.
- `server/main.py` — FastAPI API, rate-limit, durable cache, static frontend serving.
- `eval/` — evaluation set + runner. `.agents/` — project skills.

---

## Local run

```powershell
uv sync
uv run pytest            # 243 tests

# Deterministic legacy path (no API key needed):
uv run uvicorn server.main:app --host 127.0.0.1 --port 8000

# ADK multi-agent path (needs a provider — set in .env, see .env.example):
#   AGENT_MODE=adk
#   AGENT_PROVIDER=gemini   # requires GEMINI_API_KEY   (Cloud Run default)
#   AGENT_PROVIDER=openai   # any OpenAI-compatible endpoint via LiteLlm (dev)
#   AGENT_TOOL_CALLING=1    # let the agent invoke tools itself (function calling)
uv run uvicorn server.main:app --host 127.0.0.1 --port 8000
```

If `AGENT_MODE=adk` and the provider/key is missing or the LLM errors, the app
falls back to the deterministic path — a robustness feature (the legacy suite
still runs there). Secrets live in `.env` only (gitignored); never commit keys.

Open:

- App: `http://127.0.0.1:8000`
- API docs (Swagger): `http://127.0.0.1:8000/docs`
- Health: `http://127.0.0.1:8000/api/health`

To refresh the committed dense chart data (`app/data/ticker_cards_seed/`):

```powershell
$env:TICKER_HISTORY_PERIOD="1y"; $env:TICKER_HISTORY_POINTS="400"
uv run python scripts/prefetch_ticker_cards.py
```

## Docker

```powershell
docker build -t retail-investor-agent .
docker run --rm -p 8080:8080 retail-investor-agent      # open http://127.0.0.1:8080
```

## Cloud Run

```powershell
# Deterministic path (no key needed):
gcloud run deploy retail-investor-agent `
  --source . --allow-unauthenticated --region us-central1

# ADK/Gemini path (key via Secret Manager, never in the command or repo):
gcloud run deploy retail-investor-agent `
  --source . --allow-unauthenticated --region us-central1 `
  --set-env-vars AGENT_MODE=adk,AGENT_PROVIDER=gemini,AGENT_TOOL_CALLING=1,TICKER_DATA_MODE=cache `
  --update-secrets GEMINI_API_KEY=GEMINI_API_KEY:latest
```

Secrets go through Secret Manager only. The dense chart data ships in the image
via the committed `app/data/ticker_cards_seed/` catalog (the runtime `.cache/` is
gitignored and would not survive the build). If the key or LLM is unavailable at
runtime, the app falls back to the deterministic path.

---

## API

Interactive docs at `/docs`. Main endpoints:

| Method & path | Purpose |
|---|---|
| `POST /api/ask` | question → `ResponsePanel` (durably cached, shareable) |
| `GET /api/turn/{seq}` | fetch a stored turn (forum-style deterministic link) |
| `DELETE /api/me/{user_id}` | privacy: clear all of a guest's turns + profile |
| `POST /api/claim` · `POST /api/claim/redeem` | multi-device recovery code (no PII) |
| `GET /api/entity/ticker/{symbol}` | `TickerCard` |
| `GET /api/entity/term/{slug}` | `GlossaryTerm` |
| `GET /api/landing` | landing market-desk payload |
| `GET /api/market-map` · `GET /api/news` | landing heatmap + headlines |
| `GET /api/tickers` · `GET /api/overlap-funds` · `GET /api/glossary` | catalogs for the UI |
| `GET /api/health` | `{ "status": "ok" }` |

## Security & privacy

- Tool inputs are validated before filesystem or market-data access.
- Injection-guard on input; disclaimer + honesty notes on output.
- No secrets committed; `.env` stays local. Guests are anonymous; recovery codes
  are stored only as SHA-256 hashes (zero PII).
- STRIDE pass in [`threat_model.md`](threat_model.md); semgrep rules in `.semgrep/`.
- Optional: `pre-commit run --all-files`.

## Evaluation

```powershell
uv run python eval/run_eval.py            # router accuracy over the intent set
uv run python eval/run_eval.py --judge    # + LLM-as-judge (helpfulness/groundedness/safety) + trajectory
```

## Documentation

- [`docs/PRODUCT.md`](docs/PRODUCT.md) — needs → accents → features, evidence, demo path.
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — diagrams, concept→file mapping, design decisions, eval results.
- [`docs/VIDEO_SCRIPT.md`](docs/VIDEO_SCRIPT.md) — 5-minute video storyboard + narration.
