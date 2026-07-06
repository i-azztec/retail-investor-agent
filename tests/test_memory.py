"""Session interest memory: accumulation, recency, cap, personalization."""

from app import contracts as c
from app import memory
from app.agent_tools import RouteIntent


def test_update_accumulates_across_queries():
    memory.reset("s")
    memory.update("s", RouteIntent(intent="forensic", tickers=["NVDA"]))
    memory.update("s", RouteIntent(intent="ticker_card", tickers=["AAPL"]))
    prof = memory.profile("s")
    assert "NVDA" in prof["tickers"] and "AAPL" in prof["tickers"]
    assert "forensic" in prof["intents"] and "ticker_card" in prof["intents"]


def test_recent_tickers_newest_first():
    memory.reset("s2")
    memory.update("s2", RouteIntent(intent="ticker_card", tickers=["AAPL"]))
    memory.update("s2", RouteIntent(intent="ticker_card", tickers=["MSFT"]))
    assert memory.recent_tickers("s2", n=2) == ["MSFT", "AAPL"]


def test_cap_bounds_growth():
    memory.reset("s3")
    for i in range(40):
        memory.update("s3", RouteIntent(intent="ticker_card", tickers=[f"T{i}"]))
    assert len(memory.profile("s3")["tickers"]) <= 20


def test_no_session_id_is_noop():
    memory.update(None, RouteIntent(intent="forensic", tickers=["NVDA"]))
    assert memory.profile(None) == {"tickers": [], "intents": [], "terms": []}
    assert memory.recent_tickers(None) == []


def test_personalized_followup_uses_prior_ticker():
    from app import agent_runtime as rt
    from app import store

    # _personalize now reads the durable store.profiles Memory (not in-memory
    # memory.py), so seed the prior-seen ticker there.
    store.update_profile("s4", tickers=["NVDA"], intent="ticker_card")
    panel = c.ResponsePanel(
        query="tell me about AAPL",
        intent="ticker_card",
        headline="h",
        eli5="e",
        followups=[c.FollowUp(text="orig", kind="deeper", prefill_query="x")],
    )
    out = rt._personalize(panel, "s4")
    assert any("NVDA" in f.text for f in out.followups)
