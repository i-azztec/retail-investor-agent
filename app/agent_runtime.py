"""In-process ADK orchestration. Sync wrapper for FastAPI.

Drives: injection-guard -> recall long-term Memory -> seed Session state ->
router (LLM) -> dispatch (Python tools) -> thread result through Session state ->
analyst‖skeptic -> narrator -> assemble -> disclaimer-guard -> consolidate Memory.

Context flows **through** ADK Session state (the colab pattern), not around it:
a persistent ``DatabaseSessionService`` keyed by ``(user_id, thread_id)`` makes
state accumulate across the turns of a conversation (Sessions & Memory pillar),
and ``StoreMemoryService`` is the long-term, cross-session Memory feeding it.

Any failure is the caller's problem to catch (``query.answer_query_adk`` falls
back to the deterministic legacy path). ADK imports are lazy so this module loads
without ADK; ``run()`` is only called when AGENT_MODE=adk.
"""

import asyncio
import json
import os

from app import assemble
from app import contracts as c
from app import store
from app import tools
from app.agent_tools import RouteIntent, dispatch
from app.security import DISCLAIMER, check_injection, enforce_disclaimer

_APP_NAME = "retail-investor-agent"

# Cached, process-wide services (rebuilt if the DB path changes, e.g. in tests).
_SESSION_SVC = None
_SESSION_SVC_KEY = None
_MEMORY_SVC = None


def run(
    query: str,
    session_id: str | None = None,
    *,
    risk_profile: str | None = None,
    thread_id: str | None = None,
    conversation_context: str | None = None,
    focus_tickers: list[str] | None = None,
) -> c.ResponsePanel:
    """Synchronous entry point. Returns a validated ResponsePanel.

    ``conversation_context`` + ``focus_tickers`` + ``risk_profile`` are seeded into
    ADK Session state so router/analyst/skeptic/narrator read them from ``ctx.state``.
    ``thread_id`` keys the persistent session so state accumulates across turns.
    """
    if check_injection(query):
        return _refusal_panel(query)

    route, extra, narr_state, tool_invoked = asyncio.run(
        _run_async(query, session_id, thread_id, risk_profile, conversation_context, focus_tickers)
    )
    # M6: capture this turn's grounded tool numbers so a follow-up can re-inject the
    # actual figures (parity with the legacy path's _llm_over_tool). Set in the sync
    # context server.main reads at the save point; no-op for intents without figures.
    _capture_tool_context(route.intent, extra)

    state = {
        "query": query,
        **extra,
        "pros": narr_state.get("pros"),
        "cons": narr_state.get("cons"),
        "narr": narr_state.get("narr"),
    }
    panel = assemble.build(state)
    if tool_invoked:  # M9: the agent itself invoked this tool (vs deterministic dispatch)
        panel.meta.tool_invoked = tool_invoked
    panel = _personalize(panel, session_id)
    panel = enforce_disclaimer(panel)
    return panel


def route_only(query: str) -> RouteIntent:
    """Run just the router agent and return its RouteIntent (used by eval)."""
    from google.adk.sessions import InMemorySessionService

    from app.agent import build_agents

    async def _go():
        router, _ = build_agents()
        service = InMemorySessionService()
        session = await service.create_session(app_name=_APP_NAME, user_id="eval", state={"query": query})
        state = await _run_agent(router, query, service, session)
        return _read_route(state, query)

    return asyncio.run(_go())


# --------------------------------------------------------------------------- #
# Services (persistent Session + long-term Memory)
# --------------------------------------------------------------------------- #


def _session_service():
    """Persistent ADK SessionService over the same SQLite file the store uses.

    Same file as the product store by default (the "two decoupled stores in one
    file" design), overridable via ``ADK_SESSION_DB_URL``. Falls back to an
    in-memory service if sqlalchemy/DB is unavailable — the graph still runs, it
    just stops persisting sessions across restarts.
    """
    global _SESSION_SVC, _SESSION_SVC_KEY
    path = store._db_path()
    key = os.getenv("ADK_SESSION_DB_URL") or path
    if _SESSION_SVC is not None and _SESSION_SVC_KEY == key:
        return _SESSION_SVC
    try:
        from google.adk.sessions import DatabaseSessionService

        # ADK 2.x uses SQLAlchemy's ASYNC engine, so the driver must be aiosqlite
        # and the file path forward-slashed (Windows-safe).
        url = os.getenv("ADK_SESSION_DB_URL") or (
            "sqlite+aiosqlite://"
            if path == ":memory:"
            else "sqlite+aiosqlite:///" + path.replace("\\", "/")
        )
        svc = DatabaseSessionService(db_url=url)
    except Exception:  # noqa: BLE001 — no sqlalchemy/DB → still run, just non-persistent
        from google.adk.sessions import InMemorySessionService

        svc = InMemorySessionService()
    _SESSION_SVC, _SESSION_SVC_KEY = svc, key
    return svc


def _memory_service():
    global _MEMORY_SVC
    if _MEMORY_SVC is None:
        from app.memory_service import StoreMemoryService

        _MEMORY_SVC = StoreMemoryService()
    return _MEMORY_SVC


async def _run_async(
    query: str,
    session_id: str | None,
    thread_id: str | None,
    risk_profile: str | None,
    conversation_context: str | None,
    focus_tickers: list[str] | None,
):
    from app.agent import build_agents

    router, analysis = build_agents()
    user_id = session_id or "web"
    sid = thread_id or session_id  # stable per-conversation key (None → ephemeral)
    service = _session_service()
    memory_service = _memory_service()

    # Long-term Memory (cross-session) feeds the short-term Session — colab pattern.
    memory_text = await _recall(memory_service, user_id, query)

    seed = {
        "query": query,
        "focus_tickers": list(focus_tickers or []),
        "risk_profile": risk_profile or "",
        "conversation_context": conversation_context or "",
        "memory": memory_text or "",
    }
    session = await _get_or_create_session(service, user_id, sid, seed)

    # 1. Router: classify intent + extract fields.
    router_state = await _run_agent(router, query, service, session)
    route = _read_route(router_state, query)

    # 2. Tool call. When AGENT_TOOL_CALLING is on, the AGENT itself picks and
    #    invokes an ADK FunctionTool (M9 — the 50-pt "meaningful tool use" pillar);
    #    we reuse its grounded result on the deterministic assemble path. The Python
    #    ``dispatch()`` stays the fallback and the default, so grounding never
    #    depends on the model choosing the right tool.
    extra: dict | None = None
    tool_invoked: str | None = None
    if _tool_calling_enabled():
        extra, tool_invoked = await _agent_tool_dispatch(query, service, session)
    if extra is None:
        extra = dispatch(route, query, conversation_context=conversation_context)

    # 3. Thread the tool result THROUGH session state so analyst/skeptic/narrator
    #    read it (plus focus_tickers/risk) from ctx.state — context flows through
    #    ADK, not around it.
    result_json = json.dumps(extra.get("result", {}), default=str)
    session = await _put_state(service, session, {"result": result_json, "intent": route.intent})

    # 4. Analyst‖Skeptic -> Narrator. Language only; if a model wobbles on
    #    structured output we still return the grounded router+tool panel.
    narr_state: dict = {}
    try:
        analysis_state = await _run_agent(analysis, query, service, session)
        narr_state = {
            "pros": analysis_state.get("pros"),
            "cons": analysis_state.get("cons"),
            "narr": analysis_state.get("narr"),
        }
    except Exception:  # noqa: BLE001 — language layer is best-effort, tools are the truth
        narr_state = {}

    # 5. Consolidate this session into long-term Memory (Session -> Memory).
    try:
        final = await service.get_session(app_name=_APP_NAME, user_id=user_id, session_id=session.id)
        await memory_service.add_session_to_memory(final or session)
    except Exception:  # noqa: BLE001 — memory write is best-effort
        pass

    return route, extra, narr_state, tool_invoked


# --------------------------------------------------------------------------- #
# M9 — agent-invoked tools (function calling)
# --------------------------------------------------------------------------- #


def _tool_calling_enabled() -> bool:
    """Runtime flag (env, off by default) — same pattern as AGENT_MODE.

    Off keeps the 220-test suite on the deterministic ``dispatch`` path; on lets
    the agent issue a real function call (set in .env/Dockerfile for the demo).
    """
    return os.getenv("AGENT_TOOL_CALLING", "0").strip().lower() in {"1", "true", "yes", "on"}


async def _agent_tool_dispatch(query: str, service, session):
    """Let the tool-calling agent pick+invoke ONE FunctionTool; map its result
    onto the deterministic assemble path.

    Returns ``(extra, tool_name)`` when the agent invoked a usable tool, else
    ``(None, None)`` so the caller falls back to ``dispatch()``. Best-effort: any
    ADK/model failure degrades to the fallback, so grounding is never at risk.
    """
    from app.agent import build_tool_agent

    try:
        agent = build_tool_agent()
        call = await _run_tool_agent(agent, query, service, session)
    except Exception:  # noqa: BLE001 — provider may not support function calling
        return None, None
    if call is None:
        return None, None
    extra = _extra_from_tool_call(call)
    return (extra, call[0]) if extra is not None else (None, None)


async def _run_tool_agent(agent, message_text: str, service, session):
    """Run the tool-calling agent and return the last ``(tool_name, result)`` it
    invoked off the event stream, or ``None`` if it called no tool."""
    from google.adk.runners import Runner
    from google.genai import types

    runner = Runner(app_name=_APP_NAME, agent=agent, session_service=service)
    message = types.Content(role="user", parts=[types.Part(text=message_text)])
    calls: list[tuple[str, object]] = []
    async for event in runner.run_async(
        user_id=session.user_id, session_id=session.id, new_message=message
    ):
        parts = getattr(getattr(event, "content", None), "parts", None) or []
        for part in parts:
            fr = getattr(part, "function_response", None)
            if fr is not None and getattr(fr, "name", None):
                resp = fr.response
                # ADK wraps a non-dict return as {"result": …}; our tools return
                # dicts, but unwrap that shape defensively.
                if isinstance(resp, dict) and set(resp.keys()) == {"result"}:
                    resp = resp["result"]
                calls.append((fr.name, resp))
    return calls[-1] if calls else None


def _extra_from_tool_call(call) -> dict | None:
    """Map an agent-issued ``(tool_name, result)`` onto the state fragment
    ``assemble.build`` expects — reusing the deterministic panel builders on the
    tool the *agent* chose. Returns ``None`` for anything unusable → dispatch."""
    from app import function_tools

    name, response = call
    intent = function_tools.TOOL_INTENT.get(name)
    if intent is None or not isinstance(response, dict) or response.get("error"):
        return None

    if intent == "forensic":
        extra = {"intent": "forensic", "result": response, "cached": True}
        try:
            extra["ticker_card"] = tools.ticker_card(response.get("ticker") or "").model_dump()
        except Exception:  # noqa: BLE001 — missing/unknown ticker card is non-fatal
            pass
        return extra
    if intent == "beginner_fees":
        extra = {"intent": "beginner_fees", "result": response, "cached": True}
        try:
            gross = float((response.get("inputs") or {}).get("gross_return", 0.07))
            extra["rule72_block"] = tools.rule72(gross * 100)
        except Exception:  # noqa: BLE001
            pass
        return extra
    return {"intent": intent, "result": response, "cached": True}


async def _get_or_create_session(service, user_id: str, sid: str | None, seed: dict):
    """Fetch the persistent session for this thread (accumulating state across
    turns) or create it; refresh this turn's seed either way."""
    if sid:
        try:
            existing = await service.get_session(app_name=_APP_NAME, user_id=user_id, session_id=sid)
        except Exception:  # noqa: BLE001
            existing = None
        if existing is not None:
            return await _put_state(service, existing, seed)
    return await service.create_session(app_name=_APP_NAME, user_id=user_id, state=seed, session_id=sid)


async def _put_state(service, session, delta: dict):
    """Append a state-only event so ``session.state`` carries ``delta`` forward.

    Reload the session first: a prior ``Runner.run`` advances the stored session
    revision, and ``DatabaseSessionService`` rejects ``append_event`` on a stale
    handle ("session has been modified in storage since it was loaded"). Returns
    the up-to-date session so callers keep a fresh handle.
    """
    from google.adk.events import Event, EventActions

    fresh = await service.get_session(
        app_name=_APP_NAME, user_id=session.user_id, session_id=session.id
    ) or session
    event = Event(author="system", actions=EventActions(state_delta=dict(delta)))
    await service.append_event(fresh, event)
    return fresh


async def _recall(memory_service, user_id: str, query: str) -> str | None:
    try:
        resp = await memory_service.search_memory(app_name=_APP_NAME, user_id=user_id, query=query)
    except Exception:  # noqa: BLE001
        return None
    texts: list[str] = []
    for mem in getattr(resp, "memories", None) or []:
        parts = getattr(getattr(mem, "content", None), "parts", None) or []
        for part in parts:
            if getattr(part, "text", None):
                texts.append(part.text)
    return " | ".join(texts) or None


async def _run_agent(agent, message_text: str, service, session) -> dict:
    """Run one ADK agent to completion against a shared session; return its state."""
    from google.adk.runners import Runner
    from google.genai import types

    runner = Runner(app_name=_APP_NAME, agent=agent, session_service=service)
    message = types.Content(role="user", parts=[types.Part(text=message_text)])
    async for _event in runner.run_async(
        user_id=session.user_id, session_id=session.id, new_message=message
    ):
        pass  # drain events; results land in session state via output_key

    final = await service.get_session(
        app_name=_APP_NAME, user_id=session.user_id, session_id=session.id
    )
    return dict((final.state if final else session.state) or {})


def _capture_tool_context(intent: str, extra: dict) -> None:
    """Stash the compact tool-number summary for M6 follow-up re-injection.

    Mirrors what the legacy ``_llm_over_tool`` does, but for the ADK path where
    the numbers come from ``dispatch()``. Silently skips intents that have no
    numeric tool figures (term/market_today/generic).
    """
    result = extra.get("result")
    if result is None:
        return
    from app import tool_summary, turn_capture

    try:
        card = extra.get("ticker_card")
        card_obj = c.TickerCard.model_validate(card) if card else None
        turn_capture.set_tool_context(tool_summary.summarize(intent, result, ticker_card=card_obj))
    except Exception:  # noqa: BLE001 — unsupported intent / unexpected shape → no tool facts
        pass


def _read_route(state: dict, query: str) -> RouteIntent:
    raw = state.get("route")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            raw = None
    if isinstance(raw, dict):
        try:
            return RouteIntent(**raw)
        except Exception:  # noqa: BLE001 — malformed router output -> safe generic
            pass
    return RouteIntent(intent="generic")


def _personalize(panel: c.ResponsePanel, session_id: str | None) -> c.ResponsePanel:
    """Turn one followup personal using previously-seen tickers (concierge touch).

    Backed by the durable ``store.profiles`` Memory (not the old in-memory
    ``memory.py``), so personalization survives restarts.
    """
    if not session_id:
        return panel
    seen = store.get_profile(session_id).get("tickers") or []
    prior = [t for t in reversed(seen) if t not in panel.query.upper()]  # most-recent first
    if not prior:
        return panel
    ticker = prior[0]
    personal = c.FollowUp(
        text=f"How does this compare to {ticker}, which you looked at earlier?",
        kind="wider",
        prefill_query=f"compare {ticker} with this",
    )
    followups = list(panel.followups)
    if followups:
        followups[-1] = personal
    else:
        followups = [personal]
    return panel.model_copy(update={"followups": followups})


def _refusal_panel(query: str) -> c.ResponsePanel:
    """Minimal, valid ResponsePanel returned when an injection attempt is detected."""
    return c.ResponsePanel(
        query=query,
        intent="generic",
        headline="I can't help with that request.",
        eli5=(
            "That request looked like an attempt to change my instructions or pull out "
            "hidden data, so I stopped. Ask me a plain investing question instead."
        ),
        honesty_notes=[
            "Request blocked by the injection guard.",
            DISCLAIMER,
        ],
    )
