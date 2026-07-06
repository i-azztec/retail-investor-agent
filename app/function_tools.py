"""ADK FunctionTools — the agent itself decides which tool to call (M9).

The deterministic ``agent_tools.dispatch`` stays the grounding fallback. These
thin wrappers expose the same finance tools to the LLM as *callable* ADK
FunctionTools, so the model issues a real function call instead of Python routing
for it — the "meaningful use of agents … clever usage of existing toolsets" the
rubric asks for. ``dispatch`` still runs whenever the agent skips, picks nothing
usable, or errors, so grounding never depends on the model choosing correctly.

ADK auto-wraps a plain Python callable passed in ``tools=[...]`` as a
``FunctionTool`` from its signature + docstring, so the docstrings below ARE the
tool schemas the model reads. Each returns a plain ``dict`` — that same dict is
what the agent sees and what ``agent_runtime`` reads back off the event stream to
reuse the deterministic assemble path on the tool the *agent* chose.
"""

from app import tools


def forensic_screen(ticker: str) -> dict:
    """Run a forensic red-flag screen on ONE company stock ticker.

    Returns Altman Z-Score, Beneish M-Score and Piotroski F-Score with
    plain-language flags. Use for questions like "is NVDA risky", "any red flags
    in TSLA", "should I worry about this company". Educational screen, not advice.

    Args:
        ticker: A single stock symbol, uppercase (e.g. "NVDA").
    """
    return tools.forensic(ticker, data_mode="cache").model_dump(mode="json")


def holdings_overlap(tickers: list[str]) -> dict:
    """Compute holdings overlap / duplication between TWO OR MORE ETF tickers.

    Use for "how much do VOO and QQQ overlap", "am I doubling up holding both".
    Research, not advice.

    Args:
        tickers: Two or more ETF symbols, uppercase (e.g. ["VOO", "QQQ"]).
    """
    return tools.overlap([t.upper() for t in tickers]).model_dump(mode="json")


def ticker_overview(ticker: str) -> dict:
    """Price, fundamentals, signals and citations for ONE ticker or ETF.

    Use for "price of AAPL", "tell me about MSFT", "what is VOO trading at".

    Args:
        ticker: A single symbol, uppercase (e.g. "AAPL").
    """
    return tools.ticker_card(ticker).model_dump(mode="json")


def fee_drag(amount: float, years: int, expense_ratio: float = 0.0075, gross_return: float = 0.07) -> dict:
    """Project how much an ETF expense ratio costs over time (fee drag).

    Use for "how much do fees cost me", "impact of a 0.75% expense ratio".
    Educational.

    Args:
        amount: Initial investment in dollars.
        years: Holding period in years.
        expense_ratio: Annual expense ratio as a fraction (0.0075 = 0.75%).
        gross_return: Assumed annual gross return as a fraction (0.07 = 7%).
    """
    return tools.fee_drag(
        amount=amount, years=years, expense_ratio=expense_ratio, gross_return=gross_return
    ).model_dump(mode="json")


def define_term(term: str) -> dict:
    """Plain-language definition of a finance term, with a citation.

    Use for "what is an expense ratio", "define P/E ratio". Returns
    ``{"error": ...}`` for an unknown term so the caller degrades gracefully.

    Args:
        term: The finance term or its slug (e.g. "expense ratio").
    """
    try:
        return tools.glossary(term).model_dump(mode="json")
    except KeyError:
        return {"error": f"unknown term: {term}"}


# Function-tool name -> the intent its result assembles as, so the runtime can
# reuse the existing deterministic ResponsePanel builders on whatever tool the
# *agent* chose to call. Includes the ``mcp_server`` tool names too (they differ
# from the in-process ones) so the same mapping works when the agent consumes the
# tools over MCP (AGENT_MCP_TOOLS=1) instead of in-process.
TOOL_INTENT = {
    # in-process FunctionTools
    "forensic_screen": "forensic",
    "holdings_overlap": "overlap",
    "ticker_overview": "ticker_card",
    "fee_drag": "beginner_fees",
    "define_term": "term",
    # app/mcp_server.py tool names (agent-consumed over MCP)
    "overlap": "overlap",
    "ticker_card": "ticker_card",
    "glossary": "term",
}

# Passed straight to ``LlmAgent(tools=…)``.
ALL_TOOLS = [forensic_screen, holdings_overlap, ticker_overview, fee_drag, define_term]
