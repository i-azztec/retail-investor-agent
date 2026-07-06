"""tool_summary: deterministic tool results -> grounding text for the LLM."""

import json
import pathlib

import pytest

from app import contracts as c
from app import tool_summary

FIX = pathlib.Path(__file__).parent.parent / "app" / "fixtures"


def _fixture(name: str) -> dict:
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def _card(ticker: str, price: float, change: float) -> c.TickerCard:
    return c.TickerCard(
        ticker=ticker,
        name=f"{ticker} Inc",
        price=price,
        change_pct=change,
        traffic=[
            c.TrafficRating(label="Quality", status="green"),
            c.TrafficRating(label="Value", status="red"),
        ],
        percentiles=[c.Percentile(metric="P/E", percentile=80, context="vs peers")],
        analyst=c.AnalystBand(low=price * 0.8, mean=price * 1.1, high=price * 1.4),
    )


def test_overlap_summary_includes_key_numbers():
    text = tool_summary.summarize("overlap", _fixture("tool_overlap.json"))
    assert "Combined portfolio overlap: 45.7%" in text
    assert "concentration" in text.lower()


def test_forensic_summary_includes_scores_and_price():
    card = _card("NVDA", 172.4, 0.018)
    text = tool_summary.summarize("forensic", _fixture("tool_forensic.json"), ticker_card=card)
    assert "NVDA" in text
    assert "safer band" in text
    assert "172.40" in text


def test_fees_summary_includes_total_lost():
    text = tool_summary.summarize("beginner_fees", _fixture("tool_fee_drag.json"))
    assert "Total lost to fees" in text
    assert "$" in text


def test_growth_summary_includes_cagr():
    result = c.GrowthResult(
        inputs=c.GrowthInputs(amount=10_000, symbol="TSLA", years=5),
        series=[c.GrowthPoint(date="Y0", value=10_000), c.GrowthPoint(date="Y5", value=22_877.58)],
        end_value=22_877.58,
        cagr=0.18,
    )
    text = tool_summary.summarize("growth", result)
    assert "22,878" in text
    assert "18.0%" in text


def test_compare_summary_lists_each_ticker():
    result = c.CompareResult(cards=[_card("NVDA", 172.4, 0.018), _card("AMD", 159.6, 0.003)])
    text = tool_summary.summarize("compare", result)
    assert "NVDA" in text and "AMD" in text
    assert "analyst mean target" in text.lower()


def test_ticker_summary_includes_price_and_signals():
    text = tool_summary.summarize("ticker_card", _card("AAPL", 210.0, -0.004))
    assert "AAPL" in text
    assert "Quality green" in text


def test_unsupported_intent_raises():
    with pytest.raises(ValueError):
        tool_summary.summarize("term", {})
