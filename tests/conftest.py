"""Shared test fixtures."""

import pytest


@pytest.fixture(autouse=True)
def _llm_off(monkeypatch):
    """Disable the real LLM by default so tests stay offline and deterministic.

    With no API key, `_api_key()` returns None and `generic_answer` raises
    `LlmUnavailable`, which every router branch degrades to a deterministic
    panel. Tests that want an LLM answer monkeypatch `generic_answer` directly,
    which replaces the function and bypasses this key check.
    """
    monkeypatch.setenv("LLM_LOAD_DOTENV", "0")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("LLM_API_KEY", "")


@pytest.fixture(autouse=True)
def _isolated_store(tmp_path, monkeypatch):
    """Give every test a throwaway SQLite store so the durable turn/profile cache
    never leaks across tests or runs (the real ``app/data/app.db`` stays clean)."""
    from app import store

    monkeypatch.setenv("APP_DB_PATH", str(tmp_path / "store.db"))
    store._CONN = None
    store._CONN_PATH = None
    yield
    if store._CONN is not None:
        store._CONN.close()
    store._CONN = None
    store._CONN_PATH = None


@pytest.fixture(autouse=True)
def _reset_rate_limit():
    """Clear the in-memory per-IP rate-limit window before each test.

    The FastAPI app rate-limits by client IP, and every TestClient request
    shares one IP — a full test run would otherwise trip the 30/min limit.
    """
    try:
        from server import main

        main._HITS.clear()
    except Exception:  # noqa: BLE001 — server package not needed by all tests
        pass
