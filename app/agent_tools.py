"""Deterministic layer between the router LLM and our tools.

The router LLM only *classifies* intent + extracts fields into a `RouteIntent`.
The actual tool *call* stays here in Python — reliable, testable, grounded.
`dispatch()` maps a RouteIntent to a state-dict fragment that `assemble.build`
consumes to produce a ResponsePanel. Existing `query._extract_*` helpers are the
fallback when the LLM misses a field, so behavior degrades gracefully.
"""

from pydantic import BaseModel, Field

from app import contracts as c
from app import llm_client
from app import query as q
from app import tools


class RouteIntent(BaseModel):
    """Structured router output. `intent` must be a `contracts.Intent` literal."""

    intent: str = Field(
        description="one of: overlap|forensic|beginner_fees|growth|compare|ticker_card|term|market_today|generic"
    )
    tickers: list[str] = Field(default_factory=list)
    term: str | None = None
    amount: float | None = None
    years: int | None = None
    expense_ratio: float | None = None
    gross_return: float | None = None
    is_price_question: bool = False


def _first(seq: list[str]) -> str | None:
    return seq[0] if seq else None


def dispatch(route: "RouteIntent", query: str, *, conversation_context: str | None = None) -> dict:
    """Map a RouteIntent to a state fragment for assemble.build()."""
    intent = route.intent
    tickers = [t.upper() for t in route.tickers]

    if intent == "overlap":
        etfs = tickers or q._extract_etfs(query)
        if len(etfs) >= 2:
            return {"intent": "overlap", "result": tools.overlap(etfs).model_dump(), "cached": True}
        return _generic(query, conversation_context)

    if intent == "forensic":
        t = _first(tickers) or q._extract_ticker(query)
        return {
            "intent": "forensic",
            "result": tools.forensic(t, data_mode="cache").model_dump(),
            "ticker_card": tools.ticker_card(t).model_dump(),
            "cached": True,
        }

    if intent == "beginner_fees":
        r = tools.fee_drag(
            amount=route.amount or q._extract_amount(query),
            years=route.years or q._extract_years(query),
            expense_ratio=route.expense_ratio or 0.0075,
            gross_return=route.gross_return or 0.07,
        )
        return {
            "intent": "beginner_fees",
            "result": r.model_dump(),
            "rule72_block": tools.rule72(r.inputs.gross_return * 100),
            "cached": True,
        }

    if intent == "growth":
        return {
            "intent": "growth",
            "result": tools.growth(
                amount=route.amount or q._extract_investment_amount(query),
                symbol=_first(tickers) or q._extract_growth_symbol(query),
                years=route.years or q._extract_years(query, default=10),
            ).model_dump(),
            "cached": True,
        }

    if intent == "compare":
        ts = (tickers or q._extract_compare_tickers(query))[:6]
        if len(ts) >= 2:
            return {
                "intent": "compare",
                "result": c.CompareResult(
                    cards=[tools.ticker_card(ticker) for ticker in ts]
                ).model_dump(),
                "cached": True,
            }
        return _generic(query, conversation_context)

    if intent == "ticker_card":
        t = _first(tickers) or q._extract_ticker(query)
        return {"intent": "ticker_card", "result": tools.ticker_card(t).model_dump(), "cached": True}

    if intent == "term":
        term = route.term or q._extract_term(query)
        if term:
            try:
                return {"intent": "term", "result": tools.glossary(term).model_dump(), "cached": True}
            except KeyError:
                pass  # unknown glossary term -> educational generic answer instead
        return _generic(query, conversation_context)

    # market_today has no dedicated assemble path -> treat as generic (safe).
    return _generic(query, conversation_context)


def _generic(query: str, conversation_context: str | None = None) -> dict:
    """Generic educational answer + enrichment, reusing the existing LLM path."""
    try:
        g = llm_client.generic_answer(query, conversation_context=conversation_context)
        tickers = q._extract_generic_tickers(query, g.tickers)[:6]
        return {
            "intent": "generic",
            "result": g.model_dump(),
            "ticker_cards": [tools.ticker_card(t).model_dump() for t in tickers],
            "cached": False,
        }
    except llm_client.LlmUnavailable:
        return {"intent": "generic", "result": {}, "cached": True}
