"""Deterministic query orchestration used before the ADK workflow is wired in.

This is intentionally small and replaceable. FastAPI calls `answer_query()`
today; later M2 can swap the inside for router -> tool node -> analyst/skeptic
-> narrator -> assembler while keeping the same ResponsePanel contract.
"""

import json
import os
import pathlib
import re

from app import assemble
from app import contracts as c
from app import llm_client
from app import store
from app import tool_summary
from app import tools
from app import turn_capture

_FIXTURES = pathlib.Path(__file__).parent / "fixtures"
_DOLLAR_RE = re.compile(r"\$?\s*([0-9][0-9,]*(?:\.\d+)?)\s*(k|m)?", re.IGNORECASE)
_INVESTMENT_AMOUNT_RE = re.compile(r"(?:\$\s*([0-9][0-9,]*(?:\.\d+)?)\s*(k|m)?|\b([0-9][0-9,]*(?:\.\d+)?)\s*(k|m)\b)", re.IGNORECASE)
_YEARS_RE = re.compile(r"\b(?:over|for)?\s*(\d{1,2})\s*(?:years?|yrs?)\b", re.IGNORECASE)
_EXPENSE_RE = re.compile(r"(?:expense\s*ratio|fee|fees?)\D{0,20}([0-9]+(?:\.\d+)?)\s*%", re.IGNORECASE)
_RETURN_RE = re.compile(r"(?:return|growth|gross)\D{0,20}([0-9]+(?:\.\d+)?)\s*%", re.IGNORECASE)
_TICKER_RE = re.compile(r"\b[A-Z]{1,5}(?:\.[A-Z])?\b")
_PRICE_RE = re.compile(r"(?:price|quote|cost|сколько стоит|цена|котировк)", re.IGNORECASE)

def _ticker_data_cached() -> bool:
    """Whether ticker cards are served from cache (vs a live/auto yfinance path).

    The demo defaults to ``cache`` for determinism, so the badge reads "cached".
    Set ``TICKER_DATA_MODE=auto`` (or ``live``) to attempt real yfinance data;
    the panel badge then honestly reads "live".
    """
    return (os.getenv("TICKER_DATA_MODE") or os.getenv("DATA_MODE", "cache")).lower() == "cache"


_ETF_HINTS = {"VOO", "QQQ", "VGT", "SPY", "SCHD"}
# Index / colloquial aliases → a symbol we can actually chart. Applied before
# ticker extraction so "S&P 500" resolves to SPY instead of leaking the letter
# "S". Keys are matched case-insensitively as substrings.
_INDEX_ALIASES = {
    "s&p 500": "SPY",
    "s&p500": "SPY",
    "s & p 500": "SPY",
    "sp500": "SPY",
    "s&p": "SPY",
    "nasdaq 100": "QQQ",
    "nasdaq": "QQQ",
    "dow jones": "DIA",
    "dow": "DIA",
}
_COMPANY_ALIASES = {
    "apple": "AAPL",
    "microsoft": "MSFT",
    "nvidia": "NVDA",
    "tesla": "TSLA",
    "alphabet": "GOOGL",
    "google": "GOOGL",
    "amazon": "AMZN",
    "meta": "META",
    "oracle": "ORCL",
    "salesforce": "CRM",
}
_TICKER_WORD_STOPLIST = {
    "A",
    "AN",
    "AND",
    "BEAR",
    "BEST",
    "BUY",
    "CARD",
    "CASE",
    "CHEAP",
    "ETF",
    "ETFS",
    "FOR",
    "FROM",
    "HOW",
    "I",
    "IS",
    "ME",
    "NOW",
    "PE",
    "PORTFOLIO",
    "RED",
    "RISK",
    "SHOW",
    "SHOULD",
    "THINK",
    "THE",
    "WHAT",
    "WHEN",
    "WHY",
    "VS",
    "WITH",
}
_TERM_ALIASES = {
    "expense ratio": "expense ratio",
    "fund fee": "expense ratio",
    "etf": "etf",
    "dividend": "dividend",
    "compound interest": "compound interest",
    "compounding": "compound interest",
    "diversification": "diversification",
    "overlap": "portfolio-overlap",
    "concentration": "concentration",
    "concentrated": "concentration",
    "altman z": "altman-z-score",
    "altman z-score": "altman-z-score",
    "beneish m": "beneish-m-score",
    "beneish m-score": "beneish-m-score",
    "piotroski f": "piotroski-f-score",
    "piotroski f-score": "piotroski-f-score",
    "p/e": "pe-ratio",
    "pe ratio": "pe-ratio",
    "p/e ratio": "pe-ratio",
    "p/e percentile": "pe-ratio",
    "form 4": "form-4",
    "insider filing": "form-4",
    "insider activity": "form-4",
    "dividend safety": "dividend-safety",
    "safe dividend": "dividend-safety",
    "market movers": "market-movers",
    "market mover": "market-movers",
}


def landing() -> c.Landing:
    """Return the current landing payload.

    Live market shelves can replace this after the frontend is in place. The
    fixture already validates as a Landing contract and is enough for M3/M4.
    """
    return c.Landing.model_validate(json.loads((_FIXTURES / "tool_landing.json").read_text(encoding="utf-8")))


def ticker_card(ticker: str) -> c.TickerCard:
    """Return a ticker card via the ticker-card tool.

    The tool owns live/cache/fallback data policy; the query layer only routes.
    """
    return tools.ticker_card(ticker)


def term_card(term: str) -> c.GlossaryTerm:
    return tools.glossary(term)


_ALLOWED: set[str] | None = None


def _allowed_symbols() -> set[str]:
    """Strict ticker allowlist: seed cards ∪ cached ETFs ∪ index proxies.

    Anything not in this set is not a real ticker for our purposes, so noise
    like SIDE / BY / S / GPU never leaks into panels. Index proxies (SPY/DIA/
    VTI) resolve via ``_fallback_ticker_card`` even without a seed file.
    """
    global _ALLOWED
    if _ALLOWED is None:
        _ALLOWED = set(tools.known_tickers()) | {e.upper() for e in tools.available_etfs()} | {"SPY", "DIA", "VTI"}
    return _ALLOWED


def _is_ticker(symbol: str) -> bool:
    return symbol.upper() in _allowed_symbols()


def _resolve_index_aliases(query: str) -> str:
    """Rewrite index phrases (S&P 500 → SPY) so extraction hits a real symbol."""
    resolved = query
    lowered = query.lower()
    for phrase, symbol in _INDEX_ALIASES.items():
        if phrase in lowered:
            resolved = re.sub(re.escape(phrase), f" {symbol} ", resolved, flags=re.IGNORECASE)
            lowered = resolved.lower()
    return resolved


def _extract_etfs(query: str) -> list[str]:
    tickers = [m.group(0).upper() for m in _TICKER_RE.finditer(query.upper())]
    return [t for t in dict.fromkeys(tickers) if t in tools.available_etfs() or t in _ETF_HINTS]


def _extract_ticker(query: str, default: str | None = "NVDA") -> str | None:
    for match in _TICKER_RE.finditer(query):
        ticker = match.group(0).upper()
        if ticker in _TICKER_WORD_STOPLIST or ticker in _ETF_HINTS:
            continue
        if _is_ticker(ticker):
            return ticker
    lowered = query.lower()
    for name, ticker in _COMPANY_ALIASES.items():
        if re.search(rf"\b{re.escape(name)}\b", lowered):
            return ticker
    return default


def _extract_generic_tickers(query: str, llm_tickers: list[str] | None = None) -> list[str]:
    tickers: list[str] = []
    lowered = query.lower()
    for raw_ticker in llm_tickers or []:
        raw = raw_ticker.strip()
        normalized = _COMPANY_ALIASES.get(raw.lower(), raw.upper())
        if normalized and _is_ticker(normalized) and normalized not in _TICKER_WORD_STOPLIST and normalized not in tickers:
            tickers.append(normalized)
    for name, ticker in _COMPANY_ALIASES.items():
        if re.search(rf"\b{re.escape(name)}\b", lowered) and ticker not in tickers:
            tickers.append(ticker)
    for match in _TICKER_RE.finditer(query):
        ticker = match.group(0).upper()
        raw = match.group(0)
        if raw != raw.upper() and ticker not in _ETF_HINTS:
            continue
        if _is_ticker(ticker) and ticker not in _TICKER_WORD_STOPLIST and ticker not in tickers:
            tickers.append(ticker)
    return tickers[:3]


def _extract_tickers_from_text(text: str) -> list[str]:
    return _extract_generic_tickers(text, [])


def _is_price_question(query: str) -> bool:
    return bool(_PRICE_RE.search(query))


def _extract_growth_symbol(query: str, default: str = "SPY") -> str:
    resolved = _resolve_index_aliases(query)
    for match in _TICKER_RE.finditer(resolved):
        ticker = match.group(0).upper()
        if ticker in _TICKER_WORD_STOPLIST:
            continue
        if _is_ticker(ticker):
            return ticker
    lowered = query.lower()
    for name, ticker in _COMPANY_ALIASES.items():
        if re.search(rf"\b{re.escape(name)}\b", lowered):
            return ticker
    return default


def _extract_compare_tickers(query: str) -> list[str]:
    tickers: list[str] = []
    resolved = _resolve_index_aliases(query)
    for match in _TICKER_RE.finditer(resolved.upper()):
        ticker = match.group(0).upper()
        if ticker in _TICKER_WORD_STOPLIST or not _is_ticker(ticker):
            continue
        if ticker not in tickers:
            tickers.append(ticker)
    lowered = query.lower()
    for name, ticker in _COMPANY_ALIASES.items():
        if re.search(rf"\b{re.escape(name)}\b", lowered) and ticker not in tickers:
            tickers.append(ticker)
    return tickers[:6]


def _extract_amount(query: str, default: float = 10_000) -> float:
    match = _DOLLAR_RE.search(query)
    if match is None:
        return default
    value = float(match.group(1).replace(",", ""))
    suffix = (match.group(2) or "").lower()
    if suffix == "k":
        value *= 1_000
    elif suffix == "m":
        value *= 1_000_000
    return value


def _extract_investment_amount(query: str, default: float = 10_000) -> float:
    match = _INVESTMENT_AMOUNT_RE.search(query)
    if match is None:
        return default
    raw = match.group(1) or match.group(3)
    suffix = (match.group(2) or match.group(4) or "").lower()
    value = float(raw.replace(",", ""))
    if suffix == "k":
        value *= 1_000
    elif suffix == "m":
        value *= 1_000_000
    return value


def _extract_years(query: str, default: int = 20) -> int:
    match = _YEARS_RE.search(query)
    if match is None:
        return default
    return max(1, min(60, int(match.group(1))))


def _extract_ratio(pattern: re.Pattern, query: str, default: float) -> float:
    match = pattern.search(query)
    if match is None:
        return default
    return max(0.0, min(0.99, float(match.group(1)) / 100))


def _extract_term(query: str) -> str | None:
    q = query.lower()
    for needle, term in _TERM_ALIASES.items():
        if needle in q:
            return term
    return None


def _planned_workflow(query: str) -> str | None:
    q = query.lower()
    if any(phrase in q for phrase in ("insider", "form 4", "bought or sold", "bought shares", "sold shares")):
        return "insider_activity"
    if any(phrase in q for phrase in ("dividend safety", "safe dividend", "dividend safe", "payout ratio", "dividend coverage")):
        return "dividend_safety"
    if any(phrase in q for phrase in ("market today", "today's market", "what moved the market", "why did the market", "market movers")):
        return "market_today"
    if any(phrase in q for phrase in ("which fund", "which etf", "remove to reduce", "fund should i remove", "etf should i remove")):
        return "etf_replacement"
    return None


def _is_portfolio_question(query: str) -> bool:
    """Detect 'what/which portfolio should I build' style questions.

    These are routed to a grounded educational allocation panel instead of
    letting the LLM enumerate arbitrary 'best' stocks.
    """
    q = query.lower()
    portfolio_words = ("portfolio", "allocation", "asset allocation", "diversif", "портфел", "распредел")
    intent_words = (
        "best", "optimal", "build", "start", "starter", "should i", "what to",
        "how to invest", "how should i invest", "лучш", "оптималь", "собрать", "во что",
        "какие акции", "какой портфель",
    )
    if any(word in q for word in portfolio_words) and any(word in q for word in intent_words):
        return True
    if any(phrase in q for phrase in ("what stocks should i buy", "which stocks should i buy", "best stocks to buy", "what should i invest in")):
        return True
    return False


def _build_conversation_context(
    parent_seq: int | None, user_id: str | None, risk_profile: str | None
) -> tuple[str | None, list[str]]:
    """Reassemble the follow-up context the LLM lost: prior turns + tickers +
    prior tool numbers (M6) + risk/interest profile — from the durable store.

    Built server-side from the parent chain so a follow-up is self-contained
    WITHOUT folding text into the query string (the single follow-up mechanism).

    Returns ``(context_string, focus_tickers)`` where ``context_string`` is None
    when there is nothing useful to add (a fresh, profile-less turn), and
    ``focus_tickers`` (M3) is the thread's + profile's tickers, newest-first, so
    a follow-up that names no ticker still shows/answers about the ones in play.
    """
    ctx = store.thread_context(parent_seq) if parent_seq is not None else {"summary": [], "tickers": [], "tool_facts": []}
    profile = store.get_profile(user_id)
    parts: list[str] = []
    if ctx["summary"]:
        lines = [f"- Q: {s['query']} → {s['headline']}" for s in ctx["summary"]]
        parts.append("Earlier in this conversation (oldest first):\n" + "\n".join(lines))
    if ctx.get("tickers"):
        parts.append("Tickers already in play: " + ", ".join(ctx["tickers"]))
    if ctx.get("tool_facts"):  # M6: the exact numbers the user was shown before
        facts = "; ".join(f"[{f['intent']}] {f['facts']}" for f in ctx["tool_facts"])
        parts.append("Prior tool results already shown (reuse these exact numbers): " + facts)
    if risk_profile:
        parts.append(f"User risk profile: {risk_profile} (frame the answer for this tolerance).")
    interests = profile.get("tickers") or []
    if interests:
        parts.append("User has recently looked at: " + ", ".join(interests[:8]))

    # M3 focus tickers: thread tickers first (most on-topic), then profile fills.
    focus: list[str] = []
    for t in list(ctx.get("tickers") or []) + interests:
        if t and t not in focus:
            focus.append(t)
    return ("\n".join(parts) or None), focus


def answer_query_adk(
    query: str,
    session_id: str | None = None,
    risk_profile: str | None = None,
    *,
    intent: str | None = None,
    parent_seq: int | None = None,
    thread_id: str | None = None,
) -> c.ResponsePanel:
    """ADK multi-agent entry point, behind AGENT_MODE with a legacy fallback.

    AGENT_MODE != 'adk'  -> deterministic legacy path (default; 116 tests run here).
    AGENT_MODE == 'adk'  -> ADK router/analyst/skeptic/narrator; on ANY error (no
    key, ADK missing, LLM failure) silently fall back to answer_query(). The
    fallback is also the robustness argument for the writeup.

    ``parent_seq``/``session_id`` let us rebuild the follow-up conversation
    context from the store and feed it back to the LLM (the lost-context fix).
    """
    if not query or not query.strip():
        raise ValueError("query must be a non-empty string")
    turn_capture.reset()  # M6: fresh per-turn capture of the context/tool facts fed to the LLM
    conversation_context, focus_tickers = _build_conversation_context(parent_seq, session_id, risk_profile)
    turn_capture.set_conversation_context(conversation_context)
    if os.getenv("AGENT_MODE", "legacy").lower() != "adk":
        return answer_query(
            query, risk_profile=risk_profile, intent=intent,
            conversation_context=conversation_context, focus_tickers=focus_tickers,
        )
    try:
        from app import agent_runtime

        return agent_runtime.run(
            query, session_id, risk_profile=risk_profile, thread_id=thread_id,
            conversation_context=conversation_context, focus_tickers=focus_tickers,
        )
    except llm_client.LlmUnavailable:
        # LLM-first routes want this surfaced to the UI, not hidden behind a
        # legacy panel — re-run legacy so a deterministic route still answers,
        # but LLM-first routes there will re-raise and reach the API as a 503.
        return answer_query(
            query, risk_profile=risk_profile, intent=intent,
            conversation_context=conversation_context, focus_tickers=focus_tickers,
        )
    except Exception:  # noqa: BLE001 — any other ADK failure degrades to legacy
        return answer_query(
            query, risk_profile=risk_profile, intent=intent,
            conversation_context=conversation_context, focus_tickers=focus_tickers,
        )


def _llm_over_tool(query, intent, result, *, ticker_card=None, conversation_context=None):
    """Feed deterministic tool numbers to the LLM for a grounded narrative.

    Returns a GenericAnswerResult or None (LLM off/unavailable), so callers put
    it in ``state["generic"]`` and the assembler's `_with_generic` merges it —
    or, when None, renders the deterministic panel unchanged.
    """
    try:
        ctx = tool_summary.summarize(intent, result, ticker_card=ticker_card)
        turn_capture.set_tool_context(ctx)  # M6: persist the exact numbers for follow-up re-injection
        return llm_client.generic_answer(query, tool_context=ctx, conversation_context=conversation_context)
    except llm_client.LlmUnavailable:
        return None


def answer_query(
    query: str,
    risk_profile: str | None = None,
    *,
    intent: str | None = None,
    conversation_context: str | None = None,
    focus_tickers: list[str] | None = None,
) -> c.ResponsePanel:
    """Route a beginner-investor question to the available deterministic tools.

    ``intent`` is an optional caller-supplied hint (from a UI button that knows
    what it wants) that bypasses the regex cascade. ``None`` -> normal cascade.
    ``conversation_context`` (built by ``_build_conversation_context``) is passed
    to every LLM-backed branch so follow-ups keep the prior message + tool context.
    ``focus_tickers`` (M3) are the thread/profile tickers to keep visible in the
    generic routes so a follow-up that names no ticker still surfaces them.
    """
    if not query or not query.strip():
        raise ValueError("query must be a non-empty string")

    # Forced dispatch: a button already knows the intent, so skip the regexes
    # that would otherwise misclassify a hand-built query (e.g. "Explain these
    # numbers for META: P/E ..." would hit the glossary branch).
    # Optional LLM intent classifier for hand-typed queries (hybrid part C).
    # Off by default (INTENT_CLASSIFIER unset) so tests stay deterministic and
    # no latency is added. Only the ambiguous labels are honoured; everything
    # else falls through to the regex cascade below.
    if intent is None and os.getenv("INTENT_CLASSIFIER", "").lower() == "llm":
        label = llm_client.classify_intent(query)
        if label in ("generic", "ticker_detail"):
            intent = "generic"
        elif label == "forensic":
            intent = "forensic"

    if intent == "generic":
        return _generic_route(query, conversation_context=conversation_context, focus_tickers=focus_tickers)
    if intent == "forensic":
        forced = _extract_ticker(query, default="NVDA")
        forensic_result = tools.forensic(forced, data_mode="cache")
        card = ticker_card(forced)
        return assemble.build(
            {
                "query": query,
                "intent": "forensic",
                "result": forensic_result,
                "ticker_card": card,
                "generic": _llm_over_tool(query, "forensic", forensic_result, ticker_card=card, conversation_context=conversation_context),
                "cached": True,
            }
        )

    q = query.lower()
    etfs = _extract_etfs(query)
    if len(etfs) >= 2 and any(word in q for word in ("overlap", "перес", "same", "duplicate")):
        overlap_result = tools.overlap(etfs)
        return assemble.build(
            {
                "query": query,
                "intent": "overlap",
                "result": overlap_result,
                "generic": _llm_over_tool(query, "overlap", overlap_result, conversation_context=conversation_context),
                "cached": True,
            }
        )

    if any(phrase in q for phrase in ("what if", "if i invested", "invested", "years ago", "backtest")):
        growth_result = tools.growth(
            amount=_extract_investment_amount(query),
            symbol=_extract_growth_symbol(query),
            years=_extract_years(query, default=10),
        )
        return assemble.build(
            {
                "query": query,
                "intent": "growth",
                "result": growth_result,
                "generic": _llm_over_tool(query, "growth", growth_result, conversation_context=conversation_context),
                "cached": True,
            }
        )

    if any(word in q for word in ("compare", " vs ", " versus ", "against")):
        compare_tickers = _extract_compare_tickers(query)
        if len(compare_tickers) >= 2:
            compare_result = c.CompareResult(cards=[ticker_card(ticker) for ticker in compare_tickers])
            return assemble.build(
                {
                    "query": query,
                    "intent": "compare",
                    "result": compare_result,
                    "generic": _llm_over_tool(query, "compare", compare_result, conversation_context=conversation_context),
                    "cached": True,
                }
            )

    term = _extract_term(query)
    if term and any(word in q for word in ("what is", "explain", "объяс", "что такое")):
        return assemble.build(
            {
                "query": query,
                "intent": "term",
                "result": tools.glossary(term),
                "cached": True,
            }
        )

    planned = _planned_workflow(query)
    if planned is not None:
        return assemble.build_planned_workflow_panel(
            query,
            planned,
            ticker=_extract_ticker(query, default=None),
            cached=True,
        )

    if any(word in q for word in ("fee", "expense", "commission", "переплач", "комисс")):
        result = tools.fee_drag(
            amount=_extract_amount(query),
            years=_extract_years(query),
            expense_ratio=_extract_ratio(_EXPENSE_RE, query, 0.0075),
            gross_return=_extract_ratio(_RETURN_RE, query, 0.07),
        )
        panel = assemble.build_fee_panel(query, result, tools.rule72(result.inputs.gross_return * 100))
        return assemble._with_generic(panel, _llm_over_tool(query, "beginner_fees", result, conversation_context=conversation_context))

    ticker = _extract_ticker(query, default=None)
    if ticker is not None and _is_price_question(query):
        card = ticker_card(ticker)
        return assemble.build(
            {
                "query": query,
                "intent": "ticker_card",
                "result": card,
                "generic": _llm_over_tool(query, "ticker_card", card, conversation_context=conversation_context),
                "cached": _ticker_data_cached(),
            }
        )

    if any(word in q for word in ("buy", "red flag", "red-flag", "forensic", "risk", "покуп", "риск")):
        if ticker is not None:
            forensic_result = tools.forensic(ticker, data_mode="cache")
            card = ticker_card(ticker)
            return assemble.build(
                {
                    "query": query,
                    "intent": "forensic",
                    "result": forensic_result,
                    "ticker_card": card,
                    "generic": _llm_over_tool(query, "forensic", forensic_result, ticker_card=card, conversation_context=conversation_context),
                    "cached": True,
                }
            )

    # "Tell me about X" wants a write-up about the *company*, so route it to the
    # LLM (enriched with the deterministic ticker card's visuals). Price/quote
    # questions stay deterministic — they are handled by the price branch above.
    if ticker is not None and any(phrase in q for phrase in ("tell me about", "ticker card", "overview")):
        # LLM-first route: no fallback panel. If the LLM is down we let
        # LlmUnavailable propagate so the API returns 503 and the UI can pop a
        # dialog instead of silently degrading to a bare ticker card.
        generic = llm_client.generic_answer(query, conversation_context=conversation_context)
        extra = _extract_generic_tickers(query, generic.tickers)
        seen = list(dict.fromkeys([ticker, *extra, *(focus_tickers or [])]))[:6]
        return assemble.build(
            {
                "query": query,
                "intent": "generic",
                "result": generic,
                "ticker_cards": [ticker_card(t) for t in seen],
                "cached": False,
            }
        )

    if _is_portfolio_question(query):
        return assemble.build_portfolio_panel(query, profile=risk_profile)

    return _generic_route(query, conversation_context=conversation_context, focus_tickers=focus_tickers)


def _generic_route(
    query: str, *, conversation_context: str | None = None, focus_tickers: list[str] | None = None
) -> c.ResponsePanel:
    """LLM-backed generic answer, enriched with deterministic ticker cards.

    Shared by the router fallthrough and the forced ``intent="generic"`` path.
    This is an LLM-first route: if the LLM is unavailable we let LlmUnavailable
    propagate (the API turns it into a 503 so the UI can pop an error dialog)
    rather than degrade to an empty deterministic panel.

    ``focus_tickers`` (M3) fill the ticker-card row after this turn's own tickers,
    so a follow-up like "what about its fees?" still shows the thread's tickers.
    """
    generic = llm_client.generic_answer(query, conversation_context=conversation_context)
    tickers = _extract_generic_tickers(query, generic.tickers)
    for ticker in _extract_tickers_from_text(generic.answer_md):
        if ticker not in tickers:
            tickers.append(ticker)
    for ticker in focus_tickers or []:  # M3: keep thread/profile tickers visible on follow-ups
        if ticker not in tickers:
            tickers.append(ticker)
    tickers = tickers[:6]
    return assemble.build(
        {
            "query": query,
            "intent": "generic",
            "result": generic,
            "ticker_cards": [ticker_card(ticker) for ticker in tickers],
            "cached": False,
        }
    )
