"""Deterministic pre-ADK query orchestration."""

import pytest

from app import contracts as c
from app import query


def test_followup_rebuilds_conversation_context_from_store(monkeypatch):
    """M2: a follow-up (parent_seq set) feeds the prior turn + tickers + profile
    back into the LLM as conversation_context — the lost-context regression fix."""
    from app import store

    parent_seq, _ = store.save_turn(
        query="Tell me about NVDA",
        panel_json='{"headline":"NVIDIA designs AI GPUs"}',
        headline="NVIDIA designs AI GPUs",
        intent="generic",
        tickers=["NVDA"],
    )
    store.update_profile("user-1", tickers=["AMD"], intent="forensic")

    captured = {}

    def fake_generic(_query, **kwargs):
        captured["conversation_context"] = kwargs.get("conversation_context")
        return c.GenericAnswerResult(headline="h", answer_md="a", tickers=[])

    monkeypatch.setattr(query.llm_client, "generic_answer", fake_generic)

    query.answer_query_adk("is it a safe buy?", session_id="user-1", intent="generic", parent_seq=parent_seq)

    ctx = captured["conversation_context"]
    assert ctx is not None
    assert "NVIDIA designs AI GPUs" in ctx  # prior answer headline
    assert "NVDA" in ctx  # thread tickers
    assert "AMD" in ctx  # interest profile


def test_followup_reinjects_prior_tool_facts(monkeypatch):
    """M6: a follow-up on a forensic turn gets the prior turn's exact tool numbers
    back in conversation_context, not just the ticker symbol."""
    from app import store

    parent_seq, _ = store.save_turn(
        query="Is NVDA a safe buy?",
        panel_json='{"headline":"NVDA screen"}',
        headline="NVDA screen",
        intent="forensic",
        tickers=["NVDA"],
        tool_result_json='{"altman_z": 9.4, "beneish_m": -2.1}',
    )

    captured = {}

    def fake_generic(_query, **kwargs):
        captured["conversation_context"] = kwargs.get("conversation_context")
        return c.GenericAnswerResult(headline="h", answer_md="a", tickers=[])

    monkeypatch.setattr(query.llm_client, "generic_answer", fake_generic)
    query.answer_query_adk("what does that score mean?", intent="generic", parent_seq=parent_seq)

    ctx = captured["conversation_context"]
    assert "altman_z" in ctx and "9.4" in ctx  # exact prior tool numbers re-injected


def test_followup_seeds_focus_tickers_into_cards(monkeypatch):
    """M3: a follow-up that names no ticker still shows the thread's tickers as cards."""
    from app import store

    parent_seq, _ = store.save_turn(
        query="Tell me about NVDA",
        panel_json='{"headline":"NVDA overview"}',
        headline="NVDA overview",
        intent="generic",
        tickers=["NVDA"],
    )
    monkeypatch.setattr(
        query.llm_client,
        "generic_answer",
        lambda _q, **_k: c.GenericAnswerResult(headline="h", answer_md="a", tickers=[]),
    )
    monkeypatch.setattr(
        query, "ticker_card", lambda sym: c.TickerCard(ticker=sym.upper(), name=sym, price=1.0, change_pct=0.0)
    )

    panel = query.answer_query_adk("what about its fees?", intent="generic", parent_seq=parent_seq)
    card_syms = [e.ref.upper() for e in panel.entities if e.kind == "ticker"]
    assert "NVDA" in card_syms  # focus ticker carried into the follow-up's cards


def test_answer_routes_overlap_question():
    panel = query.answer_query("I hold VOO, QQQ and VGT. How much overlap?")
    assert isinstance(panel, c.ResponsePanel)
    assert panel.intent == "overlap"
    assert panel.blocks[0].value == "46%"


def test_answer_routes_fee_question():
    panel = query.answer_query("I have $10k. Am I overpaying in fund fees?")
    assert panel.intent == "beginner_fees"
    assert [block.type for block in panel.blocks] == ["chart.line", "kpi", "table"]


def test_fee_question_uses_amount_years_fee_and_return():
    panel = query.answer_query(
        "I have $50000 over 30 years with expense ratio 0.25% and return 6% - am I overpaying in fund fees?"
    )
    assert panel.intent == "beginner_fees"
    assert "30 years" in panel.headline
    assert "$50,000" in panel.headline
    assert "0.25%" in panel.headline


def test_answer_routes_growth_question():
    panel = query.answer_query("What if I invested $10k in TSLA 5 years ago?")
    assert panel.intent == "growth"
    assert "$10,000" in panel.headline
    assert "TSLA" in panel.headline
    assert [block.type for block in panel.blocks] == ["chart.line", "kpi", "kpi"]


def test_growth_question_without_amount_defaults_to_10000_not_year_count():
    panel = query.answer_query("What if I invested in TSLA 5 years ago?")
    assert panel.intent == "growth"
    assert "$10,000" in panel.headline


def test_answer_routes_compare_question():
    panel = query.answer_query("Compare NVDA vs AMD")
    assert panel.intent == "compare"
    assert "NVDA vs AMD" in panel.headline
    types = [block.type for block in panel.blocks]
    assert types[:3] == ["chart.line", "table", "chart.bar"]
    assert types.count("traffic_light") == 2  # one per ticker (F2)
    assert any(entity.ref == "NVDA" for entity in panel.entities)
    assert any(entity.ref == "AMD" for entity in panel.entities)


def test_answer_routes_n_way_compare_question():
    panel = query.answer_query("Compare NVDA vs AMD vs MSFT")
    assert panel.intent == "compare"
    assert "NVDA vs AMD vs MSFT" in panel.headline
    assert panel.blocks[1].columns == ["Metric", "NVDA", "AMD", "MSFT"]
    assert any(entity.ref == "MSFT" for entity in panel.entities)


def test_answer_routes_compare_with_and_connector():
    panel = query.answer_query("Compare TSLA and ORCL side by side")
    assert panel.intent == "compare"
    assert "TSLA vs ORCL" in panel.headline


def test_compare_ignores_side_by_side_filler_words():
    # "side by side" must not leak SIDE / BY as tickers (strict allowlist).
    panel = query.answer_query("Compare NVDA vs AMD side by side.")
    assert panel.intent == "compare"
    tickers = {e.ref for e in panel.entities if e.kind == "ticker"}
    assert tickers == {"NVDA", "AMD"}
    assert "SIDE" not in panel.headline and "BY" not in panel.headline


def test_growth_sp500_resolves_to_spy_not_letter_s():
    assert query._extract_growth_symbol("What if I invested $10,000 in the S&P 500 5 years ago?") == "SPY"


def test_generic_answer_does_not_mark_random_uppercase_words_as_tickers(monkeypatch):
    monkeypatch.setattr(
        query.llm_client,
        "generic_answer",
        lambda _query, **k: c.GenericAnswerResult(
            headline="Nvidia vs Apple",
            answer_md="NVDA leads on GPU demand while AAPL relies on its ecosystem; a P/E gap remains.",
            tickers=["NVDA", "AAPL", "GPU"],
        ),
    )
    panel = query.answer_query("Is Nvidia better than Apple?")
    tickers = {e.ref for e in panel.entities if e.kind == "ticker"}
    assert "GPU" not in tickers
    assert {"NVDA", "AAPL"} <= tickers


def test_answer_routes_term_question():
    panel = query.answer_query("What is an ETF? Explain simply.")
    assert panel.intent == "term"
    assert panel.citations[0].source == "investor.gov"


def test_explain_expense_ratio_routes_to_term_not_fee_calculator():
    panel = query.answer_query("Explain expense ratio simply.")
    assert panel.intent == "term"
    assert panel.headline.startswith("Expense ratio")


def test_answer_routes_generated_term_question():
    panel = query.answer_query("What is concentration? Explain simply.")
    assert panel.intent == "term"
    assert panel.headline.startswith("Concentration")


def test_answer_routes_forensic_question_to_cached_screen():
    panel = query.answer_query("Should I buy NVDA? Show red flags.")
    assert panel.intent == "forensic"
    assert any(entity.ref == "NVDA" for entity in panel.entities)
    types = [b.type for b in panel.blocks]
    assert "kpi" in types
    assert "chart.line" in types
    assert any(block.type == "scorecard" for block in panel.blocks)
    assert any(getattr(block, "title", "") == "Formula inputs and source lines" for block in panel.blocks)
    assert any(f.kind == "deeper" for f in panel.followups)


def test_forensic_question_keeps_requested_ticker_in_cache_mode():
    # LLM is off in tests, so the panel is fully deterministic.
    panel = query.answer_query("Should I buy TSLA? Show forensic red flags.")
    assert panel.intent == "forensic"
    assert panel.headline.startswith("TSLA")
    assert panel.blocks[0].type == "kpi"  # no LLM TextBlock prepended
    assert any(entity.ref == "TSLA" for entity in panel.entities)


def test_forensic_question_prepends_llm_text_when_available(monkeypatch):
    fake = c.GenericAnswerResult(
        headline="NVDA looks financially stable on the screens.",
        answer_md="Altman Z of 8.9 is deep in the safe band, so no distress signal.",
        pros=["Strong balance sheet signals."],
        cons=["Screens are backward-looking."],
        followups=[],
        limitations=["Not investment advice."],
    )
    monkeypatch.setattr(query.llm_client, "generic_answer", lambda q, **k: fake)
    panel = query.answer_query("Should I buy NVDA? Show red flags.")
    assert panel.intent == "forensic"
    assert panel.blocks[0].type == "text"
    assert "Altman Z" in panel.blocks[0].markdown
    assert panel.headline.startswith("NVDA looks")
    assert "Not investment advice." in panel.honesty_notes


def test_ticker_card_falls_back_for_demo_symbols():
    card = query.ticker_card("TSLA")
    assert card.ticker == "TSLA"
    assert card.citations


def test_tell_me_about_propagates_when_llm_unavailable(monkeypatch):
    # "Tell me about X" is an LLM-first route: when the LLM is down we no longer
    # degrade to a bare ticker card — we propagate so the API returns 503 and the
    # UI pops a dialog.
    def unavailable(_query, **k):
        raise query.llm_client.LlmUnavailable("offline")

    monkeypatch.setattr(query.llm_client, "generic_answer", unavailable)
    with pytest.raises(query.llm_client.LlmUnavailable):
        query.answer_query("Tell me about TSLA.")


def test_tell_me_about_routes_to_llm_when_available(monkeypatch):
    fake = c.GenericAnswerResult(
        headline="NVDA: the AI accelerator leader",
        answer_md="NVIDIA designs the GPUs powering modern AI training.",
        pros=["Dominant in AI accelerators."],
        cons=["Valuation prices in a lot of growth."],
        tickers=["NVDA"],
        terms=[],
        followups=[],
        limitations=[],
    )
    monkeypatch.setattr(query.llm_client, "generic_answer", lambda _q, **k: fake)
    panel = query.answer_query("Tell me about NVDA.")
    assert panel.intent == "generic"
    # Enriched with the deterministic ticker card's visual blocks.
    assert any(block.type in ("kpi", "chart.line") for block in panel.blocks)
    assert any(entity.ref == "NVDA" for entity in panel.entities)


def test_price_question_routes_to_ticker_card_without_llm():
    panel = query.answer_query("Сколько стоит Apple?")
    assert panel.intent == "ticker_card"
    assert panel.headline.startswith("AAPL price:")
    assert [block.type for block in panel.blocks[:2]] == ["kpi", "chart.line"]
    assert any(entity.ref == "AAPL" for entity in panel.entities)


def test_intent_classifier_flag_routes_ambiguous_query(monkeypatch):
    fake = c.GenericAnswerResult(
        headline="Plain-English answer",
        answer_md="Here is a grounded explanation.",
        pros=[], cons=[], tickers=[], terms=[], followups=[], limitations=[],
    )
    monkeypatch.setenv("INTENT_CLASSIFIER", "llm")
    monkeypatch.setattr(query.llm_client, "classify_intent", lambda _q: "generic")
    monkeypatch.setattr(query.llm_client, "generic_answer", lambda _q, **k: fake)

    panel = query.answer_query("Some ambiguous hand-typed question the regexes miss")
    assert panel.intent == "generic"


def test_intent_classifier_off_by_default_does_not_call_llm(monkeypatch):
    # Flag unset: classifier must NOT be consulted (would raise if called).
    def boom(_q):
        raise AssertionError("classify_intent should not run without the flag")

    fake = c.GenericAnswerResult(
        headline="Emergency fund basics",
        answer_md="Keep 3-6 months of expenses in cash.",
        pros=[], cons=[], tickers=[], terms=[], followups=[], limitations=[],
    )
    monkeypatch.delenv("INTENT_CLASSIFIER", raising=False)
    monkeypatch.setattr(query.llm_client, "classify_intent", boom)
    monkeypatch.setattr(query.llm_client, "generic_answer", lambda _q, **k: fake)

    panel = query.answer_query("How should I think about my emergency fund?")
    assert panel.intent == "generic"


def test_generic_route_propagates_when_llm_unavailable(monkeypatch):
    # LLM-first generic route no longer degrades to an honest empty panel; it
    # propagates so the API can turn it into a 503 and the UI pops a dialog.
    def unavailable(_query, **k):
        raise query.llm_client.LlmUnavailable("offline")

    monkeypatch.setattr(query.llm_client, "generic_answer", unavailable)

    with pytest.raises(query.llm_client.LlmUnavailable):
        query.answer_query("How should I think about my emergency fund?")


def test_generic_question_can_use_llm_answer_with_ticker_blocks(monkeypatch):
    monkeypatch.setattr(
        query.llm_client,
        "generic_answer",
        lambda _query, **k: c.GenericAnswerResult(
            headline="Apple depends on valuation and time horizon.",
            answer_md="AAPL can be evaluated by quality, valuation, and risk tolerance.",
            pros=["Strong business quality."],
            cons=["Valuation can still matter."],
            tickers=["AAPL"],
            terms=["valuation"],
            followups=[
                c.FollowUp(text="Compare with Microsoft", kind="deeper", prefill_query="Compare AAPL vs MSFT side by side."),
                c.FollowUp(text="Run red flags", kind="wider", prefill_query="Should I buy AAPL? Show forensic red flags."),
                c.FollowUp(text="Explain valuation", kind="simpler", prefill_query="Explain valuation simply."),
            ],
            limitations=["No personal recommendation."],
        ),
    )

    panel = query.answer_query("How should I think about Apple now?")

    assert panel.intent == "generic"
    assert panel.headline.startswith("Apple")
    assert panel.blocks[0].type == "text"
    assert any(block.type == "kpi" and block.label == "AAPL price" for block in panel.blocks)
    assert any(entity.ref == "AAPL" for entity in panel.entities)
    assert any(entity.ref == "pe-ratio" for entity in panel.entities)
    assert not any(entity.ref == "ABOUT" for entity in panel.entities)
    assert panel.meta.cached is False


def test_buy_question_without_ticker_does_not_default_to_nvda(monkeypatch):
    monkeypatch.setattr(
        query.llm_client,
        "generic_answer",
        lambda _query, **k: c.GenericAnswerResult(
            headline="Use a checklist before buying.",
            answer_md="Without a ticker, start with goals, risk, valuation, and diversification.",
            pros=[],
            cons=[],
            followups=[],
        ),
    )

    panel = query.answer_query("Should I buy now or wait?")

    assert panel.intent == "generic"
    assert "NVDA" not in panel.headline
    assert not any(entity.ref == "NVDA" for entity in panel.entities)


def test_generic_answer_extracts_tickers_from_llm_text_and_adds_snapshot(monkeypatch):
    monkeypatch.setattr(
        query.llm_client,
        "generic_answer",
        lambda _query, **k: c.GenericAnswerResult(
            headline="Start with diversified research, not a single best stock list.",
            answer_md="For research, compare AAPL, MSFT, NVDA, GOOGL, AMZN and JPM across sectors.",
            pros=["Diversification reduces single-company dependence."],
            cons=["A list of stocks is not a personalized portfolio."],
            tickers=[],
            terms=["diversification"],
            followups=[],
            limitations=["Educational examples only."],
        ),
    )

    panel = query.answer_query("Какой сейчас самый лучший портфолио, из каких акций?")

    assert panel.intent == "generic"
    assert any(entity.ref == "AAPL" for entity in panel.entities)
    assert any(entity.ref == "MSFT" for entity in panel.entities)
    assert any(block.type == "table" and block.title == "Mentioned tickers snapshot" for block in panel.blocks)
    assert any(block.type == "chart.line" and "normalized" in block.title.lower() for block in panel.blocks)
    assert any(block.type == "chart.bar" for block in panel.blocks)


def test_insider_followup_routes_to_planned_panel():
    panel = query.answer_query("Who recently bought or sold NVDA insider shares?")
    assert panel.intent == "generic"
    assert "Insider activity" in panel.headline
    assert any(block.type == "table" and "workflow will check" in block.title for block in panel.blocks)
    assert any(entity.ref == "form-4" for entity in panel.entities)


def test_dividend_safety_routes_to_planned_panel():
    panel = query.answer_query("Is TSLA dividend safety good?")
    assert panel.intent == "generic"
    assert "Dividend safety" in panel.headline
    assert any(entity.ref == "dividend-safety" for entity in panel.entities)


def test_market_today_routes_to_planned_panel():
    panel = query.answer_query("What moved the market today?")
    assert panel.intent == "generic"
    assert "market-today" in panel.headline
    assert any(entity.ref == "market-movers" for entity in panel.entities)


def test_etf_replacement_routes_to_planned_panel():
    panel = query.answer_query("Which fund should I remove to reduce duplication?")
    assert panel.intent == "generic"
    assert "ETF replacement" in panel.headline
    assert any(entity.ref == "portfolio-overlap" for entity in panel.entities)


def test_portfolio_question_routes_to_portfolio_panel():
    panel = query.answer_query("What is a good starter portfolio for a beginner?")
    assert panel.intent == "generic"
    assert "best portfolio" in panel.headline.lower()
    assert any(getattr(block, "type", None) == "chart.donut" for block in panel.blocks)
    assert any("allocation" in (getattr(block, "title", "") or "").lower() for block in panel.blocks)


def test_overlap_question_not_misrouted_to_portfolio():
    panel = query.answer_query("I hold VOO, QQQ and VGT - how much do they really overlap?")
    assert panel.intent == "overlap"


def test_empty_query_rejected():
    try:
        query.answer_query("   ")
    except ValueError as exc:
        assert "non-empty" in str(exc)
    else:
        raise AssertionError("empty query should fail")
