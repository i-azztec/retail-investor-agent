"""M1: deterministic ETF overlap tool — cached holdings + math guards."""

import importlib

import pytest

from app import contracts as c

overlap_tool = importlib.import_module("app.tools.overlap")


def test_available_etfs_includes_flagship_demo_names():
    assert {"VOO", "QQQ", "VGT"}.issubset(set(overlap_tool.available_etfs()))


def test_overlap_shapes_and_core_math():
    result = overlap_tool.overlap(["VOO", "QQQ", "VGT"])

    assert isinstance(result, c.OverlapResult)
    assert [fund.ticker for fund in result.funds] == ["VOO", "QQQ", "VGT"]
    assert set(result.pairwise_overlap_pct) == {"VOO|QQQ", "VOO|VGT", "QQQ|VGT"}

    # Pairwise uses sum(min(weight_a, weight_b)) over shared holdings.
    assert result.pairwise_overlap_pct["VOO|QQQ"] == pytest.approx(
        0.070 + 0.065 + 0.060 + 0.038 + 0.028 + 0.022 + 0.018 + 0.014,
        abs=1e-6,
    )
    assert result.pairwise_overlap_pct["VOO|VGT"] == pytest.approx(
        0.070 + 0.065 + 0.060 + 0.014,
        abs=1e-6,
    )
    assert result.pairwise_overlap_pct["QQQ|VGT"] == pytest.approx(
        0.110 + 0.100 + 0.085 + 0.045 + 0.016,
        abs=1e-6,
    )

    apple = next(item for item in result.shared_holdings if item.ticker == "AAPL")
    assert apple.combined_weight == pytest.approx((0.070 + 0.110 + 0.160) / 3, abs=1e-6)
    assert apple.weight_by_fund == {"VOO": 0.07, "QQQ": 0.11, "VGT": 0.16}

    assert result.combined_overlap_pct > 0
    assert result.top10_concentration_pct >= result.look_through[0].combined_weight
    assert result.citations and all(citation.as_of_date for citation in result.citations)


def test_overlap_dedupes_input_order_preserving():
    result = overlap_tool.overlap(["voo", "QQQ", "VOO"])
    assert [fund.ticker for fund in result.funds] == ["VOO", "QQQ"]


@pytest.mark.parametrize(
    "tickers",
    [
        [],
        ["VOO"],
        ["VOO", "bad ticker"],
        ["VOO", "QQQ", "VGT", "SPY", "SCHD", "IWM"],
    ],
)
def test_overlap_rejects_bad_requests(tickers):
    with pytest.raises(ValueError):
        overlap_tool.overlap(tickers)


def test_overlap_rejects_missing_cache_file():
    with pytest.raises(FileNotFoundError):
        overlap_tool.overlap(["VOO", "IWM"])
