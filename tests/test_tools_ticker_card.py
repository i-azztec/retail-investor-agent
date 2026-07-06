"""Ticker-card tool: live/cache/fallback policy without network calls."""

import importlib

from app import contracts as c
from app.tools import ticker_card as ticker_tool

ticker_module = importlib.import_module("app.tools.ticker_card")


def _card(ticker: str = "MSFT", price: float = 321.0) -> c.TickerCard:
    return c.TickerCard(
        ticker=ticker,
        name=f"{ticker} live mock",
        price=price,
        currency="USD",
        change_pct=0.012,
        price_series=[
            c.PricePoint(date="2026-07-01", close=price - 2),
            c.PricePoint(date="2026-07-02", close=price),
        ],
        fundamentals=[c.FundamentalRow(year=2026, revenue=1000.0, net_income=220.0, margin=0.22, debt=100.0)],
        snowflake=[c.SnowflakeAxis(axis="value", value=3.0)],
        traffic=[c.TrafficRating(label="Quality", status="green")],
        percentiles=[c.Percentile(metric="P/E", percentile=55, context="mock")],
        news=[c.NewsItem(title="Mock headline", url="https://example.com", published="2026-07-02", source="mock")],
        analyst=c.AnalystBand(low=250.0, mean=330.0, high=410.0),
        citations=[c.Citation(id="tc1", label="mock live card", source="yfinance", url="https://finance.yahoo.com/quote/MSFT")],
    )


def test_ticker_card_cache_mode_returns_graceful_fallback(monkeypatch, tmp_path):
    monkeypatch.setattr(ticker_module, "_CACHE_DIR", tmp_path)
    monkeypatch.setattr(ticker_module, "_SEED_DIR", tmp_path / "no_seed")

    card = ticker_tool("TSLA", data_mode="cache")

    assert card.ticker == "TSLA"
    assert card.price_series
    assert card.citations[0].source == "cached data"
    assert "fallback" in (card.citations[0].note or "").lower()


def test_ticker_card_cache_mode_returns_specialized_etf_card(monkeypatch, tmp_path):
    monkeypatch.setattr(ticker_module, "_CACHE_DIR", tmp_path)

    card = ticker_tool("VOO", data_mode="cache")

    assert card.asset_type == "etf"
    assert card.expense_ratio == 0.0003
    assert card.holdings_as_of == "2026-06-30"
    assert card.top_holdings[0].ticker == "AAPL"
    assert card.sector_exposure[0].sector == "Technology"
    assert card.fundamentals == []
    assert card.analyst is None


def test_ticker_card_auto_refreshes_and_writes_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(ticker_module, "_CACHE_DIR", tmp_path)
    monkeypatch.setattr(ticker_module, "_compute_live", lambda ticker: _card(ticker))

    card = ticker_tool("MSFT", data_mode="auto")
    cached = ticker_tool("MSFT", data_mode="cache")

    assert card.citations[0].source == "yfinance"
    assert cached.name == "MSFT live mock"


def test_ticker_card_auto_falls_back_when_live_unavailable(monkeypatch, tmp_path):
    monkeypatch.setattr(ticker_module, "_CACHE_DIR", tmp_path)

    def fail(_ticker: str) -> c.TickerCard:
        raise ticker_module.TickerCardDataError("no network")

    monkeypatch.setattr(ticker_module, "_compute_live", fail)

    card = ticker_tool("ORCL", data_mode="auto")

    assert card.ticker == "ORCL"
    assert card.citations[0].source == "cached data"
    assert "unavailable" in (card.citations[0].note or "").lower()


def test_ticker_card_cache_mode_prefers_dense_seed(monkeypatch, tmp_path):
    monkeypatch.setattr(ticker_module, "_CACHE_DIR", tmp_path / "cache")
    seed_dir = tmp_path / "seed"
    seed_dir.mkdir()
    monkeypatch.setattr(ticker_module, "_SEED_DIR", seed_dir)

    dense = _card("NVDA", price=120.0)
    dense.price_series = [c.PricePoint(date=f"2026-01-{d:02d}", close=100.0 + d) for d in range(1, 28)]
    (seed_dir / "NVDA.json").write_text(dense.model_dump_json(), encoding="utf-8")

    card = ticker_tool("NVDA", data_mode="cache")

    assert card.name == "NVDA live mock"
    assert len(card.price_series) == 27


def test_ticker_card_real_seed_is_dense_if_present():
    seed = ticker_module._read_seed("AAPL")
    if seed is None:
        import pytest

        pytest.skip("no committed AAPL seed (CI without prefetched catalog)")
    card = ticker_tool("AAPL", data_mode="cache")
    assert len(card.price_series) >= 120


def test_fallback_card_is_dense_not_three_points():
    # Any ticker outside the seed catalog used to render as a flat 3-point chart.
    card = ticker_tool("ZZZZ", data_mode="cache")
    assert len(card.price_series) >= 120
    assert card.price_series[-1].close == card.price  # path ends at the quoted price


def test_fallback_fixture_ticker_is_densified():
    # NVDA matches the bundled 3-point fixture; the fallback must densify it.
    card = ticker_module._fallback_ticker_card("NVDA")
    assert len(card.price_series) >= 120


def test_ticker_card_enriched_with_seed_news():
    # NVDA/TSLA/AAPL carry demo headlines from app/data/news_seed.json.
    card = ticker_tool("NVDA", data_mode="cache")
    assert len(card.news) >= 3
    assert all(n.title for n in card.news)


def test_fallback_unknown_tickers_are_distinct():
    # VTI/VXUS/BND used to share the flat 100.0/0.0 profile; now distinct.
    prices = {
        ticker_module._fallback_ticker_card(t).price for t in ("VTI", "VXUS", "BND")
    }
    assert len(prices) == 3


def test_ticker_card_rejects_invalid_symbol():
    try:
        ticker_tool("bad ticker", data_mode="cache")
    except ValueError as exc:
        assert "invalid ticker" in str(exc)
    else:
        raise AssertionError("invalid ticker should fail")
