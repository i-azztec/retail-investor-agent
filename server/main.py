"""FastAPI API for the interactive retail-investor research panel."""

import os
import time
from collections import defaultdict, deque

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app import contracts as c
from app import personalize
from app import query as query_service
from app import store
from app import turn_capture
from app.llm_client import LlmUnavailable, is_configured as llm_is_configured


class AskRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2_000)
    session_id: str | None = Field(default=None, max_length=128)  # = user_id (guest UUID)
    risk_profile: str | None = Field(default=None, max_length=32)
    intent: str | None = Field(default=None, max_length=32)
    thread_id: str | None = Field(default=None, max_length=128)  # one conversation
    parent_turn_id: int | None = Field(default=None)  # follow-up parent (topic seq)


app = FastAPI(
    title="Retail Investor Agent",
    version="0.1.0",
    description="Contract-first API for interactive beginner-friendly financial research panels.",
)


# --------------------------------------------------------------------------- #
# In-memory per-IP rate limit (no external dependency). Guards the LLM-backed
# endpoints from abuse; a real deployment would use Redis/Cloud Armor instead.
# --------------------------------------------------------------------------- #
_RATE_LIMIT = int(os.getenv("RATE_LIMIT_PER_MIN", "30"))
_RATE_WINDOW = 60.0
_HITS: dict[str, deque] = defaultdict(deque)


@app.middleware("http")
async def rate_limit(request: Request, call_next):
    if request.url.path.startswith("/api/") and _RATE_LIMIT > 0:
        client = request.client.host if request.client else "unknown"
        now = time.monotonic()
        hits = _HITS[client]
        while hits and now - hits[0] > _RATE_WINDOW:
            hits.popleft()
        if len(hits) >= _RATE_LIMIT:
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many requests — please slow down."},
            )
        hits.append(now)
    return await call_next(request)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


# Intents whose panels fold the LLM narrative in as a leading TextBlock, so a
# missing leading text block means the LLM was unavailable (a silent degrade).
# Used to backfill degrade-detection for turns stored before meta.llm_degraded.
_LLM_NARRATIVE_INTENTS = {"overlap", "forensic", "beginner_fees", "growth", "compare", "ticker_card"}


def _panel_tickers(panel: c.ResponsePanel) -> list[str]:
    """Ticker symbols referenced by the panel, for the durable turn record."""
    seen: list[str] = []
    for entity in panel.entities:
        if entity.kind == "ticker" and entity.ref.upper() not in seen:
            seen.append(entity.ref.upper())
    return seen


def _panel_from_row(row: dict) -> c.ResponsePanel:
    """Rebuild a stored panel and (re)attach its deterministic forum-link meta."""
    panel = c.ResponsePanel.model_validate_json(row["panel_json"])
    panel.meta.turn_seq = int(row["seq"])
    panel.meta.turn_slug = row["slug"]
    panel.meta.parent_seq = row["parent_seq"]
    panel.meta.cached = True
    return panel


def _is_stale_degraded(row: dict) -> bool:
    """A cached turn worth recomputing: its panel was produced without the LLM
    (``meta.llm_degraded``) and an LLM is configured now, so we can upgrade it.

    Without a configured LLM a recompute would only reproduce the same bare
    deterministic panel, so we keep serving the cached copy in that case.
    """
    if not llm_is_configured():
        return False
    try:
        panel = c.ResponsePanel.model_validate_json(row["panel_json"])
    except ValueError:
        return False
    if panel.meta.llm_degraded:
        return True
    # Backfill for turns persisted before the llm_degraded flag existed: an
    # LLM-narrative intent folds the LLM prose in as the leading TextBlock, so one
    # of these panels *without* a leading text block was a silent degrade.
    if panel.intent in _LLM_NARRATIVE_INTENTS:
        return not (panel.blocks and panel.blocks[0].type == "text")
    return False


def _recompute_from_row(row: dict) -> c.ResponsePanel:
    """Recompute a stored turn from its persisted params and overwrite it in place.

    Used to upgrade a previously LLM-degraded turn: the seq/slug (and shared link)
    stay stable while the content is refreshed. Raises ``LlmUnavailable`` if the
    recompute can't reach the LLM after all — callers fall back to the stored copy.
    """
    panel = query_service.answer_query_adk(
        row["query"],
        row["user_id"],
        row["risk_profile"],
        intent=row["intent"],
        parent_seq=row["parent_seq"],
        thread_id=row["thread_id"],
    )
    panel = personalize.apply_risk_profile(panel, row["risk_profile"])
    tickers = _panel_tickers(panel)
    cap = turn_capture.get()
    context_prompt = "\n\n".join(
        p for p in (cap.get("conversation_context"), cap.get("tool_context")) if p
    ) or None
    seq, slug = store.update_turn(
        int(row["seq"]),
        panel_json=panel.model_dump_json(),
        tickers=tickers,
        tool_result_json=cap.get("tool_context"),
        context_prompt=context_prompt,
    )
    panel.meta.turn_seq = seq
    panel.meta.turn_slug = slug
    panel.meta.parent_seq = row["parent_seq"]
    return panel


@app.post("/api/ask", response_model=c.ResponsePanel)
def ask(payload: AskRequest) -> c.ResponsePanel:
    # Durable cache = the turn store itself. Same question in the same context
    # (query|risk|intent|parent) returns the stored panel with no LLM recompute,
    # and it survives restarts / is shareable via #/t/<seq>.
    #
    # Exception: a turn that was answered while the LLM was down got persisted as
    # a bare deterministic panel (meta.llm_degraded). Once an LLM is configured we
    # recompute it and overwrite in place — the #/t/<seq> link keeps its number
    # but now serves the real LLM answer instead of the degraded one forever.
    cached = store.get_by_content_key(payload.query, payload.risk_profile, payload.intent, payload.parent_turn_id)
    if cached is not None and not _is_stale_degraded(cached):
        return _panel_from_row(cached)
    try:
        panel = query_service.answer_query_adk(
            payload.query,
            payload.session_id,
            payload.risk_profile,
            intent=payload.intent,
            parent_seq=payload.parent_turn_id,
            thread_id=payload.thread_id,
        )
        panel = personalize.apply_risk_profile(panel, payload.risk_profile)
    except LlmUnavailable as exc:
        # A degraded cached copy still beats a hard error when the recompute we
        # just attempted couldn't reach the LLM after all — serve it instead of 503.
        if cached is not None:
            return _panel_from_row(cached)
        # LLM-first routes surface this instead of degrading to a fallback panel;
        # the frontend pops a dialog naming the error. 503 = upstream dependency down.
        raise HTTPException(status_code=503, detail=f"LLM unavailable: {exc}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    tickers = _panel_tickers(panel)
    # M6: persist the grounded tool numbers + the exact assembled context this
    # turn fed the LLM, so a follow-up can re-inject the real figures (not just
    # the ticker) and the turn is auditable ("почему такой ответ").
    cap = turn_capture.get()
    context_prompt = "\n\n".join(
        p for p in (cap.get("conversation_context"), cap.get("tool_context")) if p
    ) or None
    if cached is not None:
        # Upgrading a previously LLM-degraded turn: overwrite in place so the
        # existing seq/slug (and any shared link) now shows the recomputed answer.
        seq, slug = store.update_turn(
            int(cached["seq"]),
            panel_json=panel.model_dump_json(),
            tickers=tickers,
            tool_result_json=cap.get("tool_context"),
            context_prompt=context_prompt,
        )
    else:
        seq, slug = store.save_turn(
            query=payload.query,
            panel_json=panel.model_dump_json(),
            headline=panel.headline,
            intent=payload.intent,
            risk_profile=payload.risk_profile,
            user_id=payload.session_id,
            thread_id=payload.thread_id,
            parent_seq=payload.parent_turn_id,
            tickers=tickers,
            tool_result_json=cap.get("tool_context"),
            context_prompt=context_prompt,
        )
    # Accumulate the durable interest profile on EVERY path (the default/legacy one
    # too — this is what the dead in-memory memory.py never did). Feeds the next
    # turn's conversation_context so answers stay personalized across the session.
    store.update_profile(payload.session_id, tickers=tickers, intent=panel.intent)
    panel.meta.turn_seq = seq
    panel.meta.turn_slug = slug
    panel.meta.parent_seq = payload.parent_turn_id
    return panel


@app.get("/api/turn/{seq}", response_model=c.ResponsePanel)
def get_turn(seq: int) -> c.ResponsePanel:
    """Return a stored turn's panel — normally verbatim (instant, no LLM).

    If the stored panel was a bare LLM-degraded fallback and an LLM is now
    configured, recompute it once and overwrite in place, so opening a shared
    #/t/<seq> link upgrades the stale fallback instead of showing it forever.
    """
    row = store.get_turn(seq)
    if row is None:
        raise HTTPException(status_code=404, detail=f"No stored turn #{seq}")
    if _is_stale_degraded(row):
        try:
            return _recompute_from_row(row)
        except LlmUnavailable:
            pass  # LLM went away between the check and the call — serve the stored copy
    return _panel_from_row(row)


@app.delete("/api/me/{user_id}")
def forget_me(user_id: str) -> dict:
    """Privacy 'clear my data': delete all turns + profile for a (guest) user."""
    return {"removed": store.forget(user_id)}


class ClaimRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=128)  # the guest UUID to bind


class RedeemRequest(BaseModel):
    recovery_code: str = Field(min_length=1, max_length=64)


@app.post("/api/claim")
def claim(payload: ClaimRequest) -> dict:
    """M8: mint a recovery code for a guest so their saved context follows them to
    another device. No email/password/PII — just a code bound to the guest id."""
    code = store.create_claim(payload.user_id)
    if code is None:
        raise HTTPException(status_code=422, detail="user_id required")
    return {"recovery_code": code}


@app.post("/api/claim/redeem")
def redeem(payload: RedeemRequest) -> dict:
    """M8: redeem a recovery code → the canonical user_id to adopt on this device."""
    user_id = store.redeem_claim(payload.recovery_code)
    if user_id is None:
        raise HTTPException(status_code=404, detail="Unknown or expired recovery code")
    return {"user_id": user_id}


@app.get("/api/entity/term/{slug}", response_model=c.GlossaryTerm)
def entity_term(slug: str) -> c.GlossaryTerm:
    try:
        return query_service.term_card(slug)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/entity/ticker/{symbol}", response_model=c.TickerCard)
def entity_ticker(symbol: str) -> c.TickerCard:
    try:
        return query_service.ticker_card(symbol)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/landing", response_model=c.Landing)
def api_landing() -> c.Landing:
    return query_service.landing()


@app.get("/api/overlap-funds")
def api_overlap_funds() -> dict[str, list[str]]:
    """ETF tickers with cached look-through holdings (valid Overlap inputs)."""
    from app.tools.overlap import available_etfs

    return {"funds": available_etfs()}


@app.get("/api/glossary")
def api_glossary() -> dict:
    """All glossary terms (term, eli5, slug) for the Learn index screen."""
    from app.tools.glossary import glossary, known_slugs

    terms = []
    for slug in known_slugs():
        card = glossary(slug)
        terms.append({"slug": slug, "term": card.term, "eli5": card.eli5})
    return {"terms": terms}


@app.get("/api/market-map", response_model=c.TreemapBlock)
def api_market_map() -> c.TreemapBlock:
    """Dashboard heatmap of mega-caps (size = S&P weight, colour = latest move)."""
    from app.assemble import build_market_map

    return build_market_map()


@app.get("/api/news")
def api_news() -> dict:
    """News shelf for the landing page: live headlines when NEWS_MODE=live, else seed."""
    from app.tools.ticker_card import _fetch_live_market_news, _news_store

    live = _fetch_live_market_news()
    market = live if live else _news_store().get("_market", [])
    return {"market": market}


@app.get("/api/tickers")
def api_tickers() -> dict:
    """Sorted list of all known ticker symbols (from the seed catalog)."""
    from app.tools.ticker_card import known_tickers

    return {"tickers": sorted(known_tickers())}


@app.get("/api/sp500-baseline")
def api_sp500_baseline() -> dict:
    """VOO real-price series on the right axis, used by the ticker modal chart."""
    from app.assemble import _sp500_baseline_series

    s = _sp500_baseline_series()
    if s is None:
        return {"name": "S&P 500 (VOO)", "points": [], "axis": "right"}
    return s.model_dump()


# Once the React build exists, FastAPI can serve it from frontend/dist in the
# same container. Mounting is conditional so backend tests work before M4.
try:
    app.mount("/", StaticFiles(directory="frontend/dist", html=True), name="frontend")
except RuntimeError:
    pass
