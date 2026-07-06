"""Assembler: tool contracts -> renderable ResponsePanel."""

import json
import pathlib

from app import assemble
from app import contracts as c
from app.tools import calculators

FIX = pathlib.Path(__file__).parent.parent / "app" / "fixtures"


def _fixture(name: str) -> dict:
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def _ticker_card(ticker: str, price: float, change: float, quality: str = "green") -> c.TickerCard:
    return c.TickerCard(
        ticker=ticker,
        name=f"{ticker} test card",
        price=price,
        currency="USD",
        change_pct=change,
        price_series=[
            c.PricePoint(date="2026-06-28", close=price * 0.95),
            c.PricePoint(date="2026-06-30", close=price),
        ],
        snowflake=[
            c.SnowflakeAxis(axis="value", value=3.0),
            c.SnowflakeAxis(axis="growth", value=4.0),
            c.SnowflakeAxis(axis="health", value=3.5),
        ],
        traffic=[
            c.TrafficRating(label="Quality", status=quality),
            c.TrafficRating(label="Value", status="yellow"),
            c.TrafficRating(label="Momentum", status="green"),
        ],
        percentiles=[c.Percentile(metric="P/E", percentile=70, context="test")],
        analyst=c.AnalystBand(low=price * 0.8, mean=price * 1.1, high=price * 1.4),
        citations=[c.Citation(id=f"{ticker}_c1", label=f"{ticker} test", source="demo cache", url="https://example.com")],
    )


def test_build_overlap_panel_from_dict_fixture(monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "gpt-5.5")
    panel = assemble.build(
        {
            "query": "I hold VOO, QQQ and VGT. How much do they overlap?",
            "intent": "overlap",
            "result": _fixture("tool_overlap.json"),
            "cached": True,
        }
    )

    assert isinstance(panel, c.ResponsePanel)
    assert panel.intent == "overlap"
    assert panel.meta.generated_by == "gpt-5.5"
    assert panel.meta.cached is True
    assert [block.type for block in panel.blocks] == [
        "kpi",
        "chart.heatmap",
        "chart.treemap",
        "chart.bar",
        "chart.donut",
        "kpi",
    ]
    assert panel.blocks[0].value == "46%"
    assert any(entity.text == "VOO" for entity in panel.entities)
    treemap = panel.blocks[2]
    bars = panel.blocks[3]
    assert treemap.items[0].entity_ref == "AAPL"
    assert bars.items[0].entity_ref == "AAPL"
    kinds = {f.kind for f in panel.followups}
    assert kinds >= {"deeper", "wider", "simpler"}
    assert sum(1 for f in panel.followups if f.kind == "deeper") >= 1


def test_build_overlap_panel_uses_narrator_overrides():
    narr = c.Narr(
        headline="Custom headline",
        eli5="Custom simple explanation.",
        followups=[
            c.FollowUp(text="A", kind="deeper", prefill_query="A?"),
            c.FollowUp(text="B", kind="wider", prefill_query="B?"),
            c.FollowUp(text="C", kind="simpler", prefill_query="C?"),
        ],
    )
    panel = assemble.build_overlap_panel(
        "q",
        c.OverlapResult.model_validate(_fixture("tool_overlap.json")),
        narr=narr,
        pros=["custom pro"],
        cons=["custom con"],
    )

    assert panel.headline == "Custom headline"
    assert panel.eli5 == "Custom simple explanation."
    assert panel.pros == ["custom pro"]
    assert panel.cons == ["custom con"]
    assert panel.followups[0].text == "A"


def test_build_forensic_panel_has_screening_blocks():
    panel = assemble.build(
        {
            "query": "Should I buy NVDA? Show red flags.",
            "intent": "forensic",
            "result": _fixture("tool_forensic.json"),
        }
    )

    assert panel.intent == "forensic"
    assert [block.type for block in panel.blocks] == [
        "radar",
        "traffic_light",
        "scorecard",
        "table",
    ]
    assert "NVDA" in panel.headline
    assert any(entity.ref == "altman-z-score" for entity in panel.entities)
    assert panel.citations
    assert panel.blocks[-1].title == "Formula inputs and source lines"
    assert "working capital" in panel.blocks[-1].rows[0][2]


def test_build_fee_panel_can_include_rule72_table():
    result = c.FeeDragResult.model_validate(_fixture("tool_fee_drag.json"))
    panel = assemble.build_fee_panel(
        "Do fees matter?",
        result,
        calculators.rule72(6),
    )

    assert panel.intent == "beginner_fees"
    assert [block.type for block in panel.blocks] == ["chart.line", "kpi", "table"]
    assert panel.blocks[0].x_type == "num"
    assert panel.assumptions == result.assumptions
    assert any(entity.ref == "expense-ratio" for entity in panel.entities)


def test_build_growth_panel_has_backtest_blocks():
    result = c.GrowthResult(
        inputs=c.GrowthInputs(amount=10_000, symbol="TSLA", years=5),
        series=[
            c.GrowthPoint(date="Year 0", value=10_000),
            c.GrowthPoint(date="Year 5", value=22_877.58),
        ],
        end_value=22_877.58,
        cagr=0.18,
        assumptions=["fallback annualized return estimate"],
        note_dividends=True,
        citations=[c.Citation(id="g1", label="TSLA fallback", source="demo cache", url="https://example.com")],
    )

    panel = assemble.build({"query": "what if", "intent": "growth", "result": result, "cached": True})

    assert panel.intent == "growth"
    assert [block.type for block in panel.blocks] == ["chart.line", "kpi", "kpi"]
    assert panel.blocks[1].value == "$22,878"
    assert any(entity.ref == "TSLA" for entity in panel.entities)
    assert panel.meta.cached is True


def test_build_compare_panel_has_side_by_side_blocks():
    result = c.CompareResult(
        left=_ticker_card("NVDA", 172.4, 0.018),
        right=_ticker_card("AMD", 159.6, 0.003, quality="yellow"),
    )

    panel = assemble.build({"query": "compare", "intent": "compare", "result": result, "cached": True})

    assert panel.intent == "compare"
    types = [block.type for block in panel.blocks]
    assert types[:3] == ["chart.line", "table", "chart.bar"]
    # One traffic_light block per ticker (F2: separate blocks per ticker)
    traffic_blocks = [b for b in panel.blocks if b.type == "traffic_light"]
    assert len(traffic_blocks) == 2
    assert "NVDA" in traffic_blocks[0].title
    assert "AMD" in traffic_blocks[1].title
    assert panel.blocks[1].columns == ["Metric", "NVDA", "AMD"]
    assert any(entity.ref == "NVDA" for entity in panel.entities)
    assert any(entity.ref == "pe-ratio" for entity in panel.entities)


def test_build_compare_panel_supports_n_way_cards():
    result = c.CompareResult(
        cards=[
            _ticker_card("NVDA", 172.4, 0.018),
            _ticker_card("AMD", 159.6, 0.003, quality="yellow"),
            _ticker_card("MSFT", 503.1, -0.002, quality="green"),
        ]
    )

    panel = assemble.build({"query": "compare", "intent": "compare", "result": result, "cached": True})

    assert "NVDA vs AMD vs MSFT" in panel.headline
    assert panel.blocks[0].series[2].name == "MSFT"
    assert panel.blocks[1].columns == ["Metric", "NVDA", "AMD", "MSFT"]
    assert [item.label for item in panel.blocks[2].items] == ["NVDA", "AMD", "MSFT"]
    assert any(entity.ref == "MSFT" for entity in panel.entities)


def test_build_term_panel_cites_glossary_source():
    panel = assemble.build(
        {
            "query": "What is expense ratio?",
            "intent": "term",
            "result": _fixture("tool_glossary.json"),
        }
    )

    assert panel.intent == "term"
    assert panel.blocks[0].type == "text"
    assert panel.citations[0].source == "investor.gov"
    kinds = {f.kind for f in panel.followups}
    assert kinds >= {"deeper", "wider", "simpler"}


def test_build_planned_workflow_panel_is_specific_placeholder():
    panel = assemble.build_planned_workflow_panel(
        "Who recently bought or sold NVDA insider shares?",
        "insider_activity",
        ticker="NVDA",
        cached=True,
    )

    assert panel.intent == "generic"
    assert "Insider activity" in panel.headline
    assert [block.type for block in panel.blocks] == ["kpi", "traffic_light", "table"]
    assert panel.blocks[0].value == "Planned"
    assert any(entity.ref == "NVDA" for entity in panel.entities)
    assert any(entity.ref == "form-4" for entity in panel.entities)
    assert panel.citations[0].source == "SEC EDGAR"


def test_with_generic_merges_llm_narrative_into_panel():
    base = assemble.build(
        {
            "query": "compare",
            "intent": "compare",
            "result": c.CompareResult(
                left=_ticker_card("NVDA", 172.4, 0.018),
                right=_ticker_card("AMD", 159.6, 0.003),
            ),
        }
    )
    generic = c.GenericAnswerResult(
        headline="NVDA edges AMD on quality signals.",
        answer_md="Both trade near fair value, but NVDA's momentum is stronger.",
        pros=["NVDA leads on quality."],
        cons=["Both look expensive on valuation."],
        followups=[c.FollowUp(text="Explain momentum", kind="simpler", prefill_query="What is momentum?")],
        limitations=["Educational only."],
    )

    merged = assemble._with_generic(base, generic)

    assert merged.blocks[0].type == "text"
    assert merged.blocks[0].markdown.startswith("Both trade")
    assert merged.headline == "NVDA edges AMD on quality signals."
    assert merged.pros == ["NVDA leads on quality."]
    assert merged.cons == ["Both look expensive on valuation."]
    # LLM 'simpler' followup wins its slot; base deeper/wider are kept.
    assert merged.followups[0].kind == "simpler"
    assert {f.kind for f in merged.followups} >= {"deeper", "wider", "simpler"}
    assert "Educational only." in merged.honesty_notes


def test_with_generic_none_leaves_panel_untouched():
    base = assemble.build(
        {"query": "what if", "intent": "growth",
         "result": c.GrowthResult(
             inputs=c.GrowthInputs(amount=10_000, symbol="TSLA", years=5),
             series=[c.GrowthPoint(date="Y0", value=10_000)],
             end_value=10_000, cagr=0.0)},
    )
    assert assemble._with_generic(base, None) is base
    # A missing LLM narrative flags the panel so the durable cache can recompute
    # it once an LLM is configured (instead of serving the bare panel forever).
    assert base.meta.llm_degraded is True


def test_build_rejects_unknown_intent():
    try:
        assemble.build({"query": "q", "intent": "market_today", "result": {}})
    except ValueError as exc:
        assert "unsupported intent" in str(exc)
    else:
        raise AssertionError("unknown assembler intent should fail loudly")
