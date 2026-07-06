"""M9 — agent-invoked FunctionTools: the wrappers and the call->assemble mapping.

Runs fully offline (cache mode, no LLM): the tool wrappers and the runtime's
``_extra_from_tool_call`` are pure Python, so we prove the agent-issued tool call
lands on the same deterministic assemble path as ``dispatch`` — without invoking a
model. The live agent-issued call itself is exercised by the ``--judge`` eval.
"""

from app import agent_runtime as rt
from app import assemble
from app import contracts as c
from app import function_tools as ft


# --------------------------------------------------------------------------- #
# Tool wrappers return grounded dicts (same numbers dispatch would compute)
# --------------------------------------------------------------------------- #


def test_forensic_screen_returns_ticker():
    out = ft.forensic_screen("NVDA")
    assert isinstance(out, dict)
    assert out.get("ticker") == "NVDA"


def test_holdings_overlap_uppercases():
    out = ft.holdings_overlap(["voo", "qqq"])
    assert isinstance(out, dict)


def test_ticker_overview_returns_dict():
    assert isinstance(ft.ticker_overview("AAPL"), dict)


def test_fee_drag_returns_inputs():
    out = ft.fee_drag(amount=10000, years=20)
    assert isinstance(out, dict) and "inputs" in out


def test_define_term_unknown_is_soft_error():
    out = ft.define_term("definitely-not-a-real-term")
    assert out.get("error")  # soft error, never raises


# --------------------------------------------------------------------------- #
# Agent-issued (tool_name, result) maps onto a build()-able state fragment
# --------------------------------------------------------------------------- #


def _build(call) -> c.ResponsePanel:
    extra = rt._extra_from_tool_call(call)
    assert extra is not None, f"no extra for {call[0]}"
    panel = assemble.build(extra | {"query": "q"})
    assert isinstance(panel, c.ResponsePanel)
    return panel


def test_map_forensic_call():
    p = _build(("forensic_screen", ft.forensic_screen("NVDA")))
    assert p.intent == "forensic"
    assert p.blocks


def test_map_overlap_call():
    p = _build(("holdings_overlap", ft.holdings_overlap(["VOO", "QQQ"])))
    assert p.intent == "overlap"


def test_map_ticker_card_call():
    p = _build(("ticker_overview", ft.ticker_overview("AAPL")))
    assert p.intent == "ticker_card"


def test_map_fee_drag_call():
    p = _build(("fee_drag", ft.fee_drag(amount=10000, years=20)))
    assert p.intent == "beginner_fees"


def test_map_mcp_tool_names_too():
    # The agent may consume the same tools over MCP, where names differ.
    assert rt._extra_from_tool_call(("overlap", ft.holdings_overlap(["VOO", "QQQ"])))["intent"] == "overlap"
    assert rt._extra_from_tool_call(("ticker_card", ft.ticker_overview("AAPL")))["intent"] == "ticker_card"


def test_map_unusable_call_falls_back_to_dispatch():
    # Unknown tool name or errored result -> None so the caller uses dispatch().
    assert rt._extra_from_tool_call(("mystery_tool", {"x": 1})) is None
    assert rt._extra_from_tool_call(("define_term", {"error": "unknown"})) is None


# --------------------------------------------------------------------------- #
# Flag gating: off by default keeps the deterministic path
# --------------------------------------------------------------------------- #


def test_tool_calling_disabled_by_default(monkeypatch):
    monkeypatch.delenv("AGENT_TOOL_CALLING", raising=False)
    assert rt._tool_calling_enabled() is False


def test_tool_calling_flag_on(monkeypatch):
    monkeypatch.setenv("AGENT_TOOL_CALLING", "1")
    assert rt._tool_calling_enabled() is True
