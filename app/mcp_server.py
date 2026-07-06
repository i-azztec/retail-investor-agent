"""External MCP interface to the deterministic finance tools.

Run (stdio):  python -m app.mcp_server

This is an *external* interface to our forensic/overlap engine — Claude Desktop,
Antigravity, or a third-party ADK agent can call overlap/ticker_card/glossary/
fee_drag over MCP. It is intentionally separate from the in-process agent flow
(which calls tools directly); the main app does not depend on this module.
"""

from mcp.server.fastmcp import FastMCP

from app import tools

mcp = FastMCP("retail-investor-tools")


@mcp.tool()
def overlap(tickers: list[str]) -> dict:
    """Portfolio overlap between ETFs. Research, not advice."""
    return tools.overlap(tickers).model_dump(mode="json")


@mcp.tool()
def ticker_card(ticker: str) -> dict:
    """Ticker/ETF card: price, fundamentals, signals, citations."""
    return tools.ticker_card(ticker).model_dump(mode="json")


@mcp.tool()
def glossary(term: str) -> dict:
    """Plain-language finance glossary term with citation."""
    return tools.glossary(term).model_dump(mode="json")


@mcp.tool()
def fee_drag(amount: float, years: int, expense_ratio: float = 0.0075, gross_return: float = 0.07) -> dict:
    """Fee-drag calculator over time. Educational, not advice."""
    return tools.fee_drag(
        amount=amount, years=years, expense_ratio=expense_ratio, gross_return=gross_return
    ).model_dump(mode="json")


if __name__ == "__main__":
    mcp.run()
