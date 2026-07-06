"""M4/M7: persistent ADK Session state + course-canonical Memory adapter + App form.

These exercise the *mechanisms* (Sessions & Memory pillar) offline — no LLM/Gemini
call. The full router→analysis orchestration stays behind AGENT_MODE=adk with a
legacy fallback and is not run here.
"""

import asyncio
from types import SimpleNamespace

import pytest


def test_store_memory_service_roundtrip():
    """add_session_to_memory consolidates focus tickers into the durable profile;
    search_memory returns them as a Memory the next session can read."""
    from app.memory_service import StoreMemoryService

    svc = StoreMemoryService()
    session = SimpleNamespace(
        user_id="u-mem",
        state={"focus_tickers": ["NVDA", "AMD"], "route": {"intent": "forensic"}},
    )
    asyncio.run(svc.add_session_to_memory(session))

    resp = asyncio.run(svc.search_memory(app_name="a", user_id="u-mem", query="anything"))
    text = " ".join(p.text for m in resp.memories for p in m.content.parts)
    assert "NVDA" in text and "AMD" in text  # cross-session recall of interests
    assert "forensic" in text  # recent question type recalled

    # Unknown user → empty memory, never raises.
    empty = asyncio.run(svc.search_memory(app_name="a", user_id="nobody", query="q"))
    assert empty.memories == []


def test_database_session_state_persists_across_restart(tmp_path, monkeypatch):
    """A persistent DatabaseSessionService keeps session state across a fresh
    service instance (= across a process restart) — the Sessions pillar, code-true."""
    pytest.importorskip("sqlalchemy")
    from google.adk.sessions import DatabaseSessionService

    from app import agent_runtime as rt

    db = str(tmp_path / "sessions.db").replace("\\", "/")
    monkeypatch.setenv("ADK_SESSION_DB_URL", f"sqlite+aiosqlite:///{db}")
    rt._SESSION_SVC = None  # force rebuild against the tmp url
    rt._SESSION_SVC_KEY = None

    async def _first():
        svc = rt._session_service()
        assert isinstance(svc, DatabaseSessionService)
        session = await svc.create_session(app_name=rt._APP_NAME, user_id="u1", state={"query": "q1"}, session_id="thread-1")
        await rt._put_state(svc, session, {"result": "grounded-numbers", "intent": "forensic"})

    asyncio.run(_first())

    # Simulate a restart: brand-new service instance on the same DB url.
    rt._SESSION_SVC = None
    rt._SESSION_SVC_KEY = None

    async def _second():
        svc = rt._session_service()
        got = await svc.get_session(app_name=rt._APP_NAME, user_id="u1", session_id="thread-1")
        return got

    got = asyncio.run(_second())
    assert got is not None
    assert got.state.get("result") == "grounded-numbers"  # state survived the "restart"
    assert got.state.get("intent") == "forensic"


def test_put_state_survives_stale_session(tmp_path, monkeypatch):
    """Regression: after a Runner run advances the stored session revision, the
    caller's handle is stale. `_put_state` must reload before appending, or
    DatabaseSessionService raises "session has been modified in storage since it
    was loaded" — which the ADK path silently swallowed into a legacy fallback."""
    pytest.importorskip("sqlalchemy")
    from google.adk.events import Event, EventActions

    from app import agent_runtime as rt

    db = str(tmp_path / "stale.db").replace("\\", "/")
    monkeypatch.setenv("ADK_SESSION_DB_URL", f"sqlite+aiosqlite:///{db}")
    rt._SESSION_SVC = None
    rt._SESSION_SVC_KEY = None

    async def _go():
        svc = rt._session_service()
        stale = await svc.create_session(app_name=rt._APP_NAME, user_id="u", state={"query": "q"}, session_id="th")
        # Simulate what Runner.run does: append an event via a freshly-loaded
        # handle, advancing the stored revision so `stale` is now out of date.
        fresh = await svc.get_session(app_name=rt._APP_NAME, user_id="u", session_id="th")
        await svc.append_event(fresh, Event(author="system", actions=EventActions(state_delta={"intent": "overlap"})))
        # The old code did append_event(stale, ...) here → ValueError. The fix
        # reloads inside _put_state, so this must succeed and apply the delta.
        await rt._put_state(svc, stale, {"result": "grounded"})
        return await svc.get_session(app_name=rt._APP_NAME, user_id="u", session_id="th")

    got = asyncio.run(_go())
    assert got.state.get("intent") == "overlap"   # earlier event preserved
    assert got.state.get("result") == "grounded"  # stale-handle delta still applied


def test_adk_run_threads_state_and_consolidates_memory(monkeypatch):
    """End-to-end ADK run with the LLM agent calls faked: proves the session is
    seeded, tool result is threaded through state, and the session consolidates
    into durable cross-session Memory — the M7 wiring, offline."""
    from app import agent_runtime as rt
    from app import contracts as c
    from app import store

    calls = {"n": 0}

    async def fake_run_agent(agent, message, service, session):
        calls["n"] += 1
        if calls["n"] == 1:  # router
            return {"route": {"intent": "forensic", "tickers": ["NVDA"]}}
        return {"pros": None, "cons": None, "narr": None}  # analysis

    monkeypatch.setattr(rt, "_run_agent", fake_run_agent)
    monkeypatch.setattr(rt, "dispatch", lambda route, q, **k: {"query": q, "intent": "forensic", "result": {"altman_z": 3.1}, "cached": True})
    monkeypatch.setattr(rt.assemble, "build", lambda state: c.ResponsePanel(query=state["query"], intent="forensic", headline="h", eli5="e"))
    monkeypatch.setattr("app.agent.build_agents", lambda: (object(), object()))

    panel = rt.run("Is NVDA a safe buy?", session_id="u-run", thread_id="th-1", focus_tickers=["NVDA"], risk_profile="cautious")
    assert panel.intent == "forensic"
    assert calls["n"] == 2  # router + analysis both ran against the shared session
    assert "NVDA" in store.get_profile("u-run")["tickers"]  # Session consolidated into Memory


def test_capture_tool_context_populates_turn_capture():
    """M6 parity on the ADK path: dispatched tool numbers are stashed for a
    follow-up to re-inject. Regression — this capture existed only on the legacy
    path, so ADK turns stored an empty tool_result_json."""
    from app import agent_runtime as rt
    from app import tools, turn_capture

    turn_capture.reset()
    extra = {"intent": "overlap", "result": tools.overlap(["VOO", "QQQ"]).model_dump()}
    rt._capture_tool_context("overlap", extra)

    captured = turn_capture.get()["tool_context"]
    assert captured and "VOO" in captured and "%" in captured  # grounded overlap numbers

    # Intents without numeric figures must not raise and leave capture empty.
    turn_capture.reset()
    rt._capture_tool_context("generic", {"intent": "generic"})
    assert turn_capture.get()["tool_context"] is None


def test_adk_app_form_is_discoverable():
    """App(root_agent=…) builds without a live key so agents-cli can discover it."""
    monkey = pytest.MonkeyPatch()
    monkey.setenv("AGENT_PROVIDER", "gemini")  # string model ids, no key needed
    try:
        from app.agent import build_app

        app = build_app()
        assert app.name == "retail-investor-agent"
        assert app.root_agent.name == "retail_investor_flow"
        assert len(app.root_agent.sub_agents) == 2  # router + analysis
    finally:
        monkey.undo()
