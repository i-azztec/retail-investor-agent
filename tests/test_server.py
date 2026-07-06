"""M3: FastAPI endpoints expose the contract-first backend."""

from fastapi.testclient import TestClient

from app import contracts as c
from server.main import app

client = TestClient(app)


def test_health():
    assert client.get("/api/health").json() == {"status": "ok"}


def test_ask_overlap_returns_response_panel():
    response = client.post(
        "/api/ask",
        json={"query": "I hold VOO, QQQ and VGT. How much overlap?"},
    )
    assert response.status_code == 200
    panel = c.ResponsePanel.model_validate(response.json())
    assert panel.intent == "overlap"
    assert panel.blocks[0].value == "46%"


def test_ask_validates_empty_query():
    response = client.post("/api/ask", json={"query": ""})
    assert response.status_code == 422


def test_market_map_returns_treemap():
    response = client.get("/api/market-map")
    assert response.status_code == 200
    block = response.json()
    assert block["type"] == "chart.treemap"
    assert len(block["items"]) >= 30  # curated mega-cap universe (~40)
    for item in block["items"]:
        assert item["entity_ref"]
        assert item["color_value"] is not None
    # Several tiles carry a real (non-zero) cached move from the seed cards.
    assert sum(1 for item in block["items"] if item["color_value"]) >= 5


def test_ask_caches_repeated_query(monkeypatch):
    import server.main as main

    # Durable turn store is the cache now (isolated per-test via conftest).
    calls = {"n": 0}
    real = main.query_service.answer_query_adk

    def counting(query, session_id, risk_profile, **kwargs):
        calls["n"] += 1
        return real(query, session_id, risk_profile, **kwargs)

    monkeypatch.setattr(main.query_service, "answer_query_adk", counting)
    # "Tell me about X" routes through the LLM (P10); return a canned answer so
    # this cache test stays offline, deterministic, and gets a cacheable 200.
    fake = c.GenericAnswerResult(
        headline="NVDA overview",
        answer_md="NVIDIA designs AI GPUs.",
        pros=[], cons=[], tickers=["NVDA"], terms=[], followups=[], limitations=[],
    )
    monkeypatch.setattr(main.query_service.llm_client, "generic_answer", lambda *a, **k: fake)

    payload = {"query": "Tell me about NVDA."}
    first = client.post("/api/ask", json=payload)
    second = client.post("/api/ask", json=payload)

    assert first.status_code == 200 and second.status_code == 200
    assert calls["n"] == 1  # second request served from the durable store, no recompute
    assert second.json()["meta"]["cached"] is True  # hit is flagged
    # Same content aside from the cached flag (the store marks retrievals cached).
    first_body, second_body = first.json(), second.json()
    first_body["meta"]["cached"] = second_body["meta"]["cached"]
    assert first_body == second_body


def test_ask_persists_tool_context(monkeypatch):
    """M6: a deterministic tool turn stores its grounded numbers (tool_result_json)
    so a later follow-up can re-inject the exact figures, and context is auditable."""
    import server.main as main

    # Overlap is a deterministic route: no LLM needed, tool numbers are computed
    # and captured even with the LLM off. Persisted turn must carry them.
    resp = client.post("/api/ask", json={"query": "I hold VOO, QQQ and VGT. How much overlap?"})
    assert resp.status_code == 200
    seq = resp.json()["meta"]["turn_seq"]
    row = main.store.get_turn(seq)
    assert row["tool_result_json"]  # grounded overlap numbers were captured + stored
    assert row["context_prompt"]    # assembled context is auditable


def test_ask_forced_generic_intent_bypasses_regex(monkeypatch):
    """A button-supplied intent="generic" routes to the LLM path, not glossary."""
    import server.main as main

    fake = c.GenericAnswerResult(
        headline="Reading META's numbers",
        answer_md="Here is what those figures mean in plain English.",
        pros=["Strong margins."],
        cons=["Rich valuation."],
        tickers=["META"],
        terms=[],
        limitations=[],
        followups=[],
    )
    monkeypatch.setattr(main.query_service.llm_client, "generic_answer", lambda *a, **k: fake)

    # Without intent this exact wording ("Explain ... P/E ...") hits the glossary.
    response = client.post(
        "/api/ask",
        json={"query": "Explain these numbers for META: P/E at the 46th percentile.", "intent": "generic"},
    )
    assert response.status_code == 200
    panel = c.ResponsePanel.model_validate(response.json())
    assert panel.intent == "generic"


def test_ask_returns_503_when_llm_unavailable(monkeypatch):
    """LLM-first route no longer degrades to a fallback panel; it surfaces 503."""
    import server.main as main

    monkeypatch.setattr(
        main.query_service.llm_client,
        "generic_answer",
        lambda *a, **k: (_ for _ in ()).throw(main.query_service.llm_client.LlmUnavailable("test")),
    )
    response = client.post("/api/ask", json={"query": "Tell me about NVDA.", "intent": "generic"})
    assert response.status_code == 503
    assert "LLM unavailable" in response.json()["detail"]


def test_ask_assigns_forum_seq_and_slug():
    response = client.post("/api/ask", json={"query": "I hold VOO, QQQ and VGT. How much overlap?"})
    panel = c.ResponsePanel.model_validate(response.json())
    assert panel.meta.turn_seq is not None
    assert panel.meta.turn_slug  # readable slug for #/t/<seq>/<slug>


def test_ask_recomputes_llm_degraded_cache_once_llm_available(monkeypatch):
    """A turn answered while the LLM was down is stored as a bare deterministic
    panel (llm_degraded). Once an LLM is configured, re-asking the same question
    recomputes it and overwrites the SAME seq — the #/t/<seq> link keeps its
    number but now serves the real LLM answer instead of the degraded fallback."""
    import server.main as main

    payload = {"query": "Should I buy NVDA? Show red flags."}

    # Phase 1: LLM down (conftest clears the key) → forensic route degrades.
    first = client.post("/api/ask", json=payload)
    assert first.status_code == 200
    seq = first.json()["meta"]["turn_seq"]
    assert first.json()["meta"]["llm_degraded"] is True
    assert main.store.get_turn(seq)["panel_json"]  # persisted degraded

    # Phase 2: LLM now available → same question recomputes in place.
    fake = c.GenericAnswerResult(
        headline="NVDA red-flag read",
        answer_md="Here is the grounded forensic narrative.",
        pros=[], cons=[], tickers=["NVDA"], terms=[], followups=[], limitations=[],
    )
    monkeypatch.setattr(main.query_service.llm_client, "generic_answer", lambda *a, **k: fake)
    monkeypatch.setattr(main, "llm_is_configured", lambda: True)

    second = client.post("/api/ask", json=payload)
    assert second.status_code == 200
    body = second.json()
    assert body["meta"]["turn_seq"] == seq  # same topic number, upgraded in place
    assert body["meta"]["llm_degraded"] is False
    assert any(b.get("type") == "text" for b in body["blocks"])  # LLM prose folded in
    # A third identical ask is now a plain cache hit (no longer stale/degraded).
    third = client.post("/api/ask", json=payload)
    assert third.json()["meta"]["cached"] is True
    assert third.json()["meta"]["turn_seq"] == seq


def test_recompute_backfills_legacy_degraded_turn(monkeypatch):
    """Turns persisted before the llm_degraded flag existed still self-heal: an
    LLM-narrative intent with no leading text block is detected as a degrade."""
    import json as _json

    import server.main as main

    first = client.post("/api/ask", json={"query": "I hold VOO, QQQ and VGT. How much overlap?"})
    seq = first.json()["meta"]["turn_seq"]
    row = main.store.get_turn(seq)
    assert c.ResponsePanel.model_validate_json(row["panel_json"]).blocks[0].type != "text"
    # Strip the flag entirely to mimic a pre-flag persisted panel.
    raw = _json.loads(row["panel_json"])
    raw["meta"].pop("llm_degraded", None)
    main.store.update_turn(seq, panel_json=_json.dumps(raw))

    # With no flag but a configured LLM, the heuristic still recomputes in place.
    monkeypatch.setattr(main, "llm_is_configured", lambda: True)
    fake = c.GenericAnswerResult(
        headline="VOO/QQQ/VGT overlap read", answer_md="Grounded overlap narrative.",
        pros=[], cons=[], tickers=[], terms=[], followups=[], limitations=[],
    )
    monkeypatch.setattr(main.query_service.llm_client, "generic_answer", lambda *a, **k: fake)

    second = client.post("/api/ask", json={"query": "I hold VOO, QQQ and VGT. How much overlap?"})
    assert second.json()["meta"]["turn_seq"] == seq
    assert second.json()["blocks"][0]["type"] == "text"  # upgraded in place


def test_get_turn_returns_stored_panel_without_recompute():
    posted = client.post("/api/ask", json={"query": "I hold VOO, QQQ and VGT. How much overlap?"})
    seq = posted.json()["meta"]["turn_seq"]
    got = client.get(f"/api/turn/{seq}")
    assert got.status_code == 200
    panel = c.ResponsePanel.model_validate(got.json())
    assert panel.intent == "overlap"
    assert panel.meta.turn_seq == seq
    assert panel.meta.cached is True
    assert client.get("/api/turn/999999").status_code == 404


def test_get_turn_self_heals_degraded_link(monkeypatch):
    """Opening a shared #/t/<seq> link whose stored panel was LLM-degraded
    recomputes it once (when an LLM is configured) and upgrades it in place."""
    import server.main as main

    first = client.post("/api/ask", json={"query": "I hold VOO, QQQ and VGT. How much overlap?"})
    seq = first.json()["meta"]["turn_seq"]
    assert first.json()["meta"]["llm_degraded"] is True

    monkeypatch.setattr(main, "llm_is_configured", lambda: True)
    fake = c.GenericAnswerResult(
        headline="Overlap read", answer_md="Grounded overlap narrative.",
        pros=[], cons=[], tickers=[], terms=[], followups=[], limitations=[],
    )
    monkeypatch.setattr(main.query_service.llm_client, "generic_answer", lambda *a, **k: fake)

    got = client.get(f"/api/turn/{seq}")
    assert got.status_code == 200
    assert got.json()["meta"]["turn_seq"] == seq
    assert got.json()["blocks"][0]["type"] == "text"  # upgraded in place
    # Now stored non-degraded → a subsequent view is the plain verbatim copy.
    assert main.store.get_turn(seq) is not None
    assert client.get(f"/api/turn/{seq}").json()["meta"]["llm_degraded"] is False


def test_forget_me_clears_stored_turns():
    client.post("/api/ask", json={"query": "I hold VOO, QQQ and VGT. How much overlap?", "session_id": "guest-x"})
    resp = client.delete("/api/me/guest-x")
    assert resp.status_code == 200
    assert resp.json()["removed"] >= 1


def test_claim_and_redeem_follows_context_across_devices():
    # Device A mints a recovery code for its guest id.
    minted = client.post("/api/claim", json={"user_id": "guest-A"})
    assert minted.status_code == 200
    code = minted.json()["recovery_code"]
    # Device B redeems it → gets the same canonical user_id to adopt.
    redeemed = client.post("/api/claim/redeem", json={"recovery_code": code})
    assert redeemed.status_code == 200
    assert redeemed.json()["user_id"] == "guest-A"


def test_redeem_unknown_code_is_404():
    resp = client.post("/api/claim/redeem", json={"recovery_code": "ZZZZ-ZZZZ-ZZZZ"})
    assert resp.status_code == 404


def test_entity_term_endpoint():
    response = client.get("/api/entity/term/expense-ratio")
    assert response.status_code == 200
    term = c.GlossaryTerm.model_validate(response.json())
    assert term.term == "Expense ratio"


def test_entity_ticker_endpoint_uses_cached_card():
    response = client.get("/api/entity/ticker/NVDA")
    assert response.status_code == 200
    card = c.TickerCard.model_validate(response.json())
    assert card.ticker == "NVDA"


def test_entity_etf_endpoint_uses_holdings_card():
    response = client.get("/api/entity/ticker/VOO")
    assert response.status_code == 200
    card = c.TickerCard.model_validate(response.json())
    assert card.asset_type == "etf"
    assert card.expense_ratio == 0.0003
    assert card.top_holdings
    assert card.sector_exposure


def test_overlap_entities_all_open_as_cards():
    response = client.post(
        "/api/ask",
        json={"query": "I hold VOO, QQQ and VGT. How much overlap?"},
    )
    panel = c.ResponsePanel.model_validate(response.json())
    assert panel.entities

    for entity in panel.entities:
        path = (
            f"/api/entity/ticker/{entity.ref}"
            if entity.kind == "ticker"
            else f"/api/entity/term/{entity.ref}"
        )
        entity_response = client.get(path)
        assert entity_response.status_code == 200, path


def test_landing_endpoint_validates_contract():
    response = client.get("/api/landing")
    assert response.status_code == 200
    landing = c.Landing.model_validate(response.json())
    assert landing.generated_questions
    # No "planned"/placeholder features surfaced to users anymore.
    assert all(item.feature != "planned" for item in landing.generated_questions)
    # Chart of the day must be a dense line, not the old 3-point placeholder.
    assert sum(len(series.points) for series in landing.chart_of_day.series) >= 120


def test_frontend_static_shell_is_served():
    response = client.get("/")
    assert response.status_code == 200
    assert "Retail Investor Agent" in response.text
    assert "ask-suggestions" in response.text
    assert client.get("/app.js").status_code == 200
    assert client.get("/styles.css").status_code == 200
