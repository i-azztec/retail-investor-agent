"""agent_tools.dispatch: every intent maps to a build()-able state fragment.

Runs fully offline (cache mode, no LLM key): the generic branch degrades to an
empty result, which assemble.build still renders.
"""

import pytest

from app import agent_tools
from app import assemble
from app import contracts as c
from app.agent_tools import RouteIntent, dispatch


@pytest.fixture
def offline_llm(monkeypatch):
    """Force the generic branch to degrade (no network), regardless of .env key."""

    def unavailable(*_a, **_k):
        raise agent_tools.llm_client.LlmUnavailable("offline test")

    monkeypatch.setattr(agent_tools.llm_client, "generic_answer", unavailable)


def _panel(route: RouteIntent, query: str) -> c.ResponsePanel:
    state = dispatch(route, query) | {"query": query}
    panel = assemble.build(state)
    assert isinstance(panel, c.ResponsePanel)
    return panel


def test_dispatch_overlap():
    p = _panel(RouteIntent(intent="overlap", tickers=["VOO", "QQQ"]), "overlap of VOO and QQQ")
    assert p.intent == "overlap"


def test_dispatch_forensic():
    p = _panel(RouteIntent(intent="forensic", tickers=["NVDA"]), "is NVDA risky")
    assert p.intent == "forensic"
    assert p.blocks


def test_dispatch_beginner_fees():
    p = _panel(RouteIntent(intent="beginner_fees", amount=10000, years=20), "fee drag on 10000 over 20 years")
    assert p.intent == "beginner_fees"


def test_dispatch_growth():
    p = _panel(RouteIntent(intent="growth", tickers=["SPY"], amount=5000, years=10), "what if I invested 5000 in SPY")
    assert p.intent == "growth"


def test_dispatch_compare():
    p = _panel(RouteIntent(intent="compare", tickers=["AAPL", "MSFT"]), "compare AAPL vs MSFT")
    assert p.intent == "compare"


def test_dispatch_ticker_card():
    p = _panel(RouteIntent(intent="ticker_card", tickers=["AAPL"], is_price_question=True), "AAPL price")
    assert p.intent == "ticker_card"


def test_dispatch_term():
    p = _panel(RouteIntent(intent="term", term="expense ratio"), "what is an expense ratio")
    assert p.intent == "term"


def test_dispatch_market_today_falls_back_to_generic(offline_llm):
    p = _panel(RouteIntent(intent="market_today"), "what moved the market today")
    assert p.intent == "generic"


def test_dispatch_generic_without_key(offline_llm):
    p = _panel(RouteIntent(intent="generic"), "explain dollar cost averaging")
    assert p.intent == "generic"


def test_dispatch_overlap_missing_tickers_degrades(offline_llm):
    # Router said overlap but gave no valid ETF pair -> safe generic fallback.
    p = _panel(RouteIntent(intent="overlap"), "tell me about overlap concept")
    assert p.intent == "generic"
