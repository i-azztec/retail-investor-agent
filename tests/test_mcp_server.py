"""MCP server: module imports and tool wrappers return valid dicts."""

from app import mcp_server


def _call(fn, *args, **kwargs):
    # FastMCP wraps functions in a FunctionTool; fall back to the raw fn if so.
    target = getattr(fn, "fn", fn)
    return target(*args, **kwargs)


def test_module_imports():
    assert mcp_server.mcp is not None


def test_overlap_wrapper():
    out = _call(mcp_server.overlap, ["VOO", "QQQ"])
    assert isinstance(out, dict)
    assert "combined_overlap_pct" in out


def test_ticker_card_wrapper():
    out = _call(mcp_server.ticker_card, "AAPL")
    assert isinstance(out, dict)
    assert out["ticker"] == "AAPL"
    assert out["price_series"]


def test_glossary_wrapper():
    out = _call(mcp_server.glossary, "expense ratio")
    assert isinstance(out, dict)
    assert "eli5" in out


def test_fee_drag_wrapper():
    out = _call(mcp_server.fee_drag, 10000, 20)
    assert isinstance(out, dict)
    assert out["total_lost"] > 0
