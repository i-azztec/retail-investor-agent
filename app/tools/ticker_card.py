"""Ticker-card tool: yfinance live path + disk cache + graceful fallback.

Default mode is intentionally `cache` so tests and demos remain deterministic.
Set `TICKER_DATA_MODE=auto` to use cached live cards when fresh and refresh from
yfinance when possible; set `TICKER_DATA_MODE=live` to require live data.
"""

import json
import os
import pathlib
import time
from typing import Any

from app import contracts as c
from app.tools.forensic import validate_ticker
from app.tools.overlap import available_etfs, load_cached_etf

_FIXTURE = pathlib.Path(__file__).parent.parent / "fixtures" / "tool_ticker_card.json"
_CACHE_DIR = pathlib.Path(__file__).parent.parent / "data" / ".cache" / "ticker_cards"
# Committed seed catalog with dense (prefetched) demo data — survives Docker/Cloud
# Run because it is NOT under app/data/.cache/ (see .gitignore). Populate via
# scripts/prefetch_ticker_cards.py.
_SEED_DIR = pathlib.Path(__file__).parent.parent / "data" / "ticker_cards_seed"
_CACHE_TTL_SECONDS = 12 * 60 * 60


class TickerCardDataError(RuntimeError):
    """Raised when live ticker-card data is unavailable or incomplete."""


def _fixture_card() -> c.TickerCard:
    return c.TickerCard.model_validate(json.loads(_FIXTURE.read_text(encoding="utf-8")))


_NEWS_SEED = pathlib.Path(__file__).parent.parent / "data" / "news_seed.json"
_NEWS_CACHE: dict[str, Any] | None = None


def _news_store() -> dict[str, Any]:
    """Load and memoize the committed demo-news seed."""
    global _NEWS_CACHE
    if _NEWS_CACHE is None:
        try:
            _NEWS_CACHE = json.loads(_NEWS_SEED.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _NEWS_CACHE = {}
    return _NEWS_CACHE


_LIVE_NEWS_CACHE: dict[str, list[dict]] = {}


def _fetch_live_market_news() -> list[dict] | None:
    """Best-effort live market headlines, cached per calendar day.

    Only attempts a live fetch when NEWS_MODE=="live"; otherwise returns None so
    callers fall back to the committed seed pool. Any failure (import, network,
    empty response) also returns None. Tests run with NEWS_MODE=cache, so this
    never touches the network there and stays deterministic.
    """
    if os.getenv("NEWS_MODE", "cache") != "live":
        return None
    import datetime

    day = datetime.date.today().isoformat()
    if day in _LIVE_NEWS_CACHE:
        return _LIVE_NEWS_CACHE[day] or None
    try:
        import yfinance as yf  # type: ignore

        symbols = ["^GSPC", "NVDA", "AAPL", "MSFT", "AMZN"]
        collected: list[dict] = []
        for sym in symbols:
            try:
                raw = yf.Ticker(sym).news or []
            except Exception:  # noqa: BLE001 — per-symbol best effort
                continue
            for item in raw:
                content = item.get("content", item)
                title = content.get("title") or item.get("title")
                if not title:
                    continue
                link = (
                    (content.get("canonicalUrl") or {}).get("url")
                    or item.get("link")
                    or f"https://finance.yahoo.com/quote/{sym}"
                )
                published = (
                    content.get("pubDate")
                    or content.get("displayTime")
                    or item.get("providerPublishTime")
                    or ""
                )
                collected.append(
                    {
                        "title": title,
                        "url": link,
                        "published": str(published)[:10],
                        "source": "yfinance",
                        "ticker": None if sym.startswith("^") else sym,
                    }
                )
        collected.sort(key=lambda n: n.get("published", ""), reverse=True)
        result = collected[:12]
        _LIVE_NEWS_CACHE[day] = result
        return result or None
    except Exception:  # noqa: BLE001 — live news is best-effort
        return None


def _read_news(ticker: str) -> list[c.NewsItem]:
    """Demo headlines for a ticker from the committed seed.

    TODO live: swap this body for a live provider (with cache + rate-limit).
    The NewsItem contract and every caller stay unchanged.
    """
    raw = _news_store().get(ticker.upper()) or []
    return [c.NewsItem.model_validate(item) for item in raw]


def _with_news(card: c.TickerCard) -> c.TickerCard:
    """Attach seed headlines when the card has none (cache/fallback paths)."""
    if card.news:
        return card
    news = _read_news(card.ticker)
    return card.model_copy(update={"news": news}) if news else card


def _cache_path(ticker: str) -> pathlib.Path:
    return _CACHE_DIR / f"{ticker}.json"


def _read_cached(ticker: str, *, require_fresh: bool) -> c.TickerCard | None:
    path = _cache_path(ticker)
    if not path.exists():
        return None
    if require_fresh and time.time() - path.stat().st_mtime > _CACHE_TTL_SECONDS:
        return None
    return c.TickerCard.model_validate(json.loads(path.read_text(encoding="utf-8")))


_KNOWN_TICKERS: set[str] | None = None


def known_tickers() -> set[str]:
    """Return the uppercase symbols with a committed seed card (allowlist).

    Mirrors ``overlap.available_etfs()`` but over the ticker-card seed catalog.
    Memoized: the seed directory is committed and does not change at runtime.
    """
    global _KNOWN_TICKERS
    if _KNOWN_TICKERS is None:
        if not _SEED_DIR.exists():
            _KNOWN_TICKERS = set()
        else:
            _KNOWN_TICKERS = {path.stem.upper() for path in _SEED_DIR.glob("*.json")}
    return _KNOWN_TICKERS


def _seed_path(ticker: str) -> pathlib.Path:
    return _SEED_DIR / f"{ticker}.json"


def _read_seed(ticker: str) -> c.TickerCard | None:
    """Read a committed dense demo card from the seed catalog, if present."""
    path = _seed_path(ticker)
    if not path.exists():
        return None
    try:
        return c.TickerCard.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except (ValueError, OSError):
        return None


def _write_cached(card: c.TickerCard) -> None:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _cache_path(card.ticker).write_text(
        json.dumps(card.model_dump(mode="json"), indent=2),
        encoding="utf-8",
    )


def _etf_sector_exposure(holdings: list[dict[str, Any]]) -> list[c.SectorWeight]:
    totals: dict[str, float] = {}
    for holding in holdings:
        sector = holding.get("sector") or "Unknown"
        totals[sector] = totals.get(sector, 0.0) + float(holding["weight"])
    return [
        c.SectorWeight(sector=sector, weight=round(weight, 6))
        for sector, weight in sorted(totals.items(), key=lambda row: row[1], reverse=True)
    ]


def _etf_card_from_cache(ticker: str, base: c.TickerCard | None = None, note: str | None = None) -> c.TickerCard:
    fund = load_cached_etf(ticker)
    holdings = sorted(fund["holdings"], key=lambda row: float(row["weight"]), reverse=True)
    top_holdings = [
        c.HoldingPreview(
            ticker=str(holding.get("ticker", "")).upper(),
            name=holding["name"],
            weight=round(float(holding["weight"]), 6),
            sector=holding.get("sector") or "Unknown",
        )
        for holding in holdings[:10]
    ]
    sector_exposure = _etf_sector_exposure(holdings)
    note = note or fund.get("note", "Bundled prototype holdings cache.")
    citation = c.Citation(
        id="etf1",
        label=f"{ticker} holdings and expense ratio",
        source=fund.get("source", "issuer"),
        url=fund.get("source_url", f"https://finance.yahoo.com/quote/{ticker}"),
        as_of_date=fund.get("as_of"),
        note=note,
    )

    if base is not None:
        return base.model_copy(
            update={
                "asset_type": "etf",
                "name": fund.get("name", base.name),
                "expense_ratio": float(fund.get("expense_ratio", 0.0)),
                "holdings_as_of": fund.get("as_of"),
                "top_holdings": top_holdings,
                "sector_exposure": sector_exposure,
                "fundamentals": [],
                "snowflake": [
                    c.SnowflakeAxis(axis="cost", value=5.0 if float(fund.get("expense_ratio", 0.0)) <= 0.001 else 3.8),
                    c.SnowflakeAxis(axis="breadth", value=min(5.0, 2.5 + len(holdings) / 6)),
                    c.SnowflakeAxis(axis="concentration", value=max(1.0, 5.0 - sum(h.weight for h in top_holdings[:5]) * 10)),
                    c.SnowflakeAxis(axis="liquidity", value=4.2),
                    c.SnowflakeAxis(axis="transparency", value=4.4),
                ],
                "traffic": [
                    c.TrafficRating(label="Cost", status="green" if float(fund.get("expense_ratio", 0.0)) <= 0.001 else "yellow"),
                    c.TrafficRating(label="Concentration", status="red" if sum(h.weight for h in top_holdings[:5]) > 0.35 else "yellow"),
                    c.TrafficRating(label="Holdings cache", status="yellow"),
                ],
                "percentiles": [],
                "analyst": None,
                "citations": [citation, *base.citations],
            }
        )

    profiles = {
        "VOO": 551.2,
        "QQQ": 487.6,
        "VGT": 603.4,
        "SPY": 548.9,
        "SCHD": 81.4,
    }
    price = profiles.get(ticker, 100.0)
    concentration = sum(h.weight for h in top_holdings[:5])
    return c.TickerCard(
        asset_type="etf",
        ticker=ticker,
        name=fund["name"],
        price=price,
        currency="USD",
        change_pct=0.0,
        expense_ratio=float(fund.get("expense_ratio", 0.0)),
        holdings_as_of=fund.get("as_of"),
        top_holdings=top_holdings,
        sector_exposure=sector_exposure,
        price_series=[
            c.PricePoint(date="2026-06-26", close=round(price * 0.985, 2)),
            c.PricePoint(date="2026-06-29", close=round(price * 0.994, 2)),
            c.PricePoint(date="2026-06-30", close=price),
        ],
        snowflake=[
            c.SnowflakeAxis(axis="cost", value=5.0 if float(fund.get("expense_ratio", 0.0)) <= 0.001 else 3.8),
            c.SnowflakeAxis(axis="breadth", value=min(5.0, 2.5 + len(holdings) / 6)),
            c.SnowflakeAxis(axis="concentration", value=max(1.0, 5.0 - concentration * 10)),
            c.SnowflakeAxis(axis="liquidity", value=4.2),
            c.SnowflakeAxis(axis="transparency", value=4.4),
        ],
        traffic=[
            c.TrafficRating(label="Cost", status="green" if float(fund.get("expense_ratio", 0.0)) <= 0.001 else "yellow"),
            c.TrafficRating(label="Concentration", status="red" if concentration > 0.35 else "yellow"),
            c.TrafficRating(label="Holdings cache", status="yellow"),
        ],
        news=[
            c.NewsItem(
                title=f"{ticker} card is using bundled holdings from the ETF cache",
                url=fund.get("source_url", f"https://finance.yahoo.com/quote/{ticker}"),
                published=fund.get("as_of", "2026-06-30"),
                source=fund.get("source", "issuer"),
            )
        ],
        citations=[citation],
    )


def _num(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None or value != value:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _first_info(info: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        value = info.get(key)
        if value is not None:
            return value
    return default


def _history_points(history, limit: int | None = None) -> list[c.PricePoint]:
    if history is None or getattr(history, "empty", True):
        return []
    limit = limit or int(os.getenv("TICKER_HISTORY_POINTS", "30"))
    rows = history.tail(limit)
    points: list[c.PricePoint] = []
    for idx, row in rows.iterrows():
        close = _num(row.get("Close"))
        if close is None:
            continue
        date = idx.date().isoformat() if hasattr(idx, "date") else str(idx)[:10]
        points.append(c.PricePoint(date=date, close=round(close, 2)))
    return points


def _series_value(series, labels: list[str]) -> float | None:
    if series is None:
        return None
    for label in labels:
        if label in series.index:
            value = _num(series.get(label))
            if value is not None:
                return value
    return None


def _fundamentals(tk, info: dict[str, Any]) -> list[c.FundamentalRow]:
    income = tk.income_stmt
    balance = tk.balance_sheet
    if income is None or getattr(income, "empty", True):
        return []

    rows: list[c.FundamentalRow] = []
    for idx, col in enumerate(income.columns[:3]):
        income_col = income.iloc[:, idx]
        balance_col = None
        if balance is not None and not getattr(balance, "empty", True) and balance.shape[1] > idx:
            balance_col = balance.iloc[:, idx]
        revenue = _series_value(income_col, ["Total Revenue"])
        net_income = _series_value(income_col, ["Net Income"])
        debt = _series_value(balance_col, ["Total Debt", "Long Term Debt"])
        year = col.year if hasattr(col, "year") else int(str(col)[:4])
        margin = (net_income / revenue) if revenue and net_income is not None else None
        rows.append(
            c.FundamentalRow(
                year=year,
                revenue=revenue,
                net_income=net_income,
                margin=margin,
                debt=debt,
                dividend=_num(info.get("dividendRate"), 0.0),
            )
        )
    return sorted(rows, key=lambda row: row.year)


def _rating(value: float, yellow: float, green: float) -> c.TrafficRating:
    status = "green" if value >= green else "yellow" if value >= yellow else "red"
    return c.TrafficRating(label="", status=status)  # label is filled by caller


def _scores(info: dict[str, Any], history_points: list[c.PricePoint], fundamentals: list[c.FundamentalRow]) -> tuple[list[c.SnowflakeAxis], list[c.TrafficRating], list[c.Percentile]]:
    pe = _num(_first_info(info, "trailingPE", "forwardPE"))
    profit_margin = _num(info.get("profitMargins"), 0.0) or 0.0
    revenue_growth = _num(info.get("revenueGrowth"), 0.0) or 0.0
    debt_to_equity = _num(info.get("debtToEquity"))
    dividend_yield = _num(info.get("dividendYield"), 0.0) or 0.0

    momentum = 0.0
    if len(history_points) >= 2 and history_points[0].close:
        momentum = (history_points[-1].close / history_points[0].close) - 1

    value_score = 4.2 if pe and pe < 18 else 3.0 if pe and pe < 35 else 1.8
    growth_score = max(1.0, min(5.0, 2.5 + revenue_growth * 10))
    health_score = 4.2 if debt_to_equity is not None and debt_to_equity < 80 else 3.3 if debt_to_equity is not None and debt_to_equity < 160 else 2.4
    past_score = max(1.0, min(5.0, 3.0 + momentum * 20))
    dividend_score = max(0.5, min(5.0, dividend_yield * 100))

    quality = _rating(profit_margin, 0.08, 0.18)
    quality.label = "Quality"
    value = c.TrafficRating(label="Value", status="green" if value_score >= 4 else "yellow" if value_score >= 2.5 else "red")
    momentum_rating = c.TrafficRating(label="Momentum", status="green" if momentum > 0.04 else "yellow" if momentum > -0.04 else "red")

    percentile = 50
    if pe:
        percentile = min(95, max(5, int(pe * 2.2)))

    return (
        [
            c.SnowflakeAxis(axis="value", value=round(value_score, 1)),
            c.SnowflakeAxis(axis="growth", value=round(growth_score, 1)),
            c.SnowflakeAxis(axis="health", value=round(health_score, 1)),
            c.SnowflakeAxis(axis="past", value=round(past_score, 1)),
            c.SnowflakeAxis(axis="dividend", value=round(dividend_score, 1)),
        ],
        [quality, value, momentum_rating],
        [
            c.Percentile(
                metric="P/E",
                percentile=percentile,
                context="rough live heuristic from current yfinance valuation fields",
            )
        ],
    )


def _news(tk) -> list[c.NewsItem]:
    out: list[c.NewsItem] = []
    for item in (getattr(tk, "news", None) or [])[:5]:
        title = item.get("title")
        url = item.get("link") or item.get("url")
        if not title or not url:
            continue
        published = item.get("providerPublishTime") or item.get("pubDate") or ""
        if isinstance(published, (int, float)):
            published = time.strftime("%Y-%m-%d", time.gmtime(published))
        out.append(
            c.NewsItem(
                title=title,
                url=url,
                published=str(published)[:10],
                source=item.get("publisher") or item.get("source") or "Yahoo Finance",
            )
        )
    return out


def _compute_live(ticker: str, period: str | None = None) -> c.TickerCard:
    import yfinance as yf

    period = period or os.getenv("TICKER_HISTORY_PERIOD", "1mo")
    tk = yf.Ticker(ticker)
    info = tk.info or {}
    history = tk.history(period=period, interval="1d", auto_adjust=False)
    points = _history_points(history)
    if not points:
        raise TickerCardDataError(f"no price history returned for {ticker}")

    price = _num(_first_info(info, "regularMarketPrice", "currentPrice"), points[-1].close) or points[-1].close
    previous = points[-2].close if len(points) >= 2 else _num(info.get("regularMarketPreviousClose"), price)
    change_pct = ((price / previous) - 1) if previous else 0.0
    fundamentals = _fundamentals(tk, info)
    snowflake, traffic, percentiles = _scores(info, points, fundamentals)

    currency = _first_info(info, "currency", "financialCurrency", default="USD") or "USD"
    analyst_mean = _num(info.get("targetMeanPrice"))
    analyst = None
    if analyst_mean is not None:
        analyst = c.AnalystBand(
            low=_num(info.get("targetLowPrice"), analyst_mean) or analyst_mean,
            mean=analyst_mean,
            high=_num(info.get("targetHighPrice"), analyst_mean) or analyst_mean,
            currency=currency,
        )

    as_of = points[-1].date
    return c.TickerCard(
        ticker=ticker,
        name=_first_info(info, "longName", "shortName", default=ticker) or ticker,
        price=round(price, 2),
        currency=currency,
        change_pct=round(change_pct, 4),
        price_series=points,
        fundamentals=fundamentals,
        snowflake=snowflake,
        traffic=traffic,
        percentiles=percentiles,
        news=_news(tk),
        analyst=analyst,
        citations=[
            c.Citation(
                id="tc1",
                label=f"{ticker} live price, profile, fundamentals",
                source="yfinance",
                url=f"https://finance.yahoo.com/quote/{ticker}",
                as_of_date=as_of,
                note="Fetched via yfinance; Yahoo Finance data can lag or be incomplete.",
            )
        ],
    )


def _synth_price_series(ticker: str, price: float, change: float, points: int = 180) -> list[c.PricePoint]:
    """Deterministic dense daily price path ending at ``price``.

    Fallback cards used to ship only 3 points, which rendered as flat 3-dot
    charts for any ticker outside the seed catalog. This generates a seeded
    pseudo-random walk (business days, ending 2026-06-30) so every card has a
    realistic dense chart without any network call.
    """
    import datetime as _dt
    import random as _random

    rng = _random.Random(f"{ticker}:{price}")
    # Build daily log-returns, then a normalized path, then scale so it ends at `price`.
    drift = (change or 0.0) / max(points, 1) * 0.5
    closes: list[float] = [1.0]
    for _ in range(points - 1):
        step = rng.gauss(drift, 0.012)
        closes.append(closes[-1] * (1.0 + step))
    scale = price / closes[-1]
    closes = [round(v * scale, 2) for v in closes]

    end = _dt.date(2026, 6, 30)
    dates: list[_dt.date] = []
    cursor = end
    while len(dates) < points:
        if cursor.weekday() < 5:  # skip weekends
            dates.append(cursor)
        cursor -= _dt.timedelta(days=1)
    dates.reverse()
    return [c.PricePoint(date=d.isoformat(), close=v) for d, v in zip(dates, closes)]


def _fallback_ticker_card(ticker: str, note: str | None = None) -> c.TickerCard:
    fixture = _fixture_card()
    if ticker == fixture.ticker:
        # The bundled fixture ships only 3 price points, which render as a flat
        # 3-dot chart. Densify before returning so no code path can emit 3 points.
        if len(fixture.price_series) < 30:
            dense = _synth_price_series(ticker, fixture.price, fixture.change_pct)
            fixture = fixture.model_copy(update={"price_series": dense})
        return fixture

    profiles = {
        "VOO": ("Vanguard S&P 500 ETF", 551.2, 0.004),
        "QQQ": ("Invesco QQQ Trust", 487.6, 0.007),
        "VGT": ("Vanguard Information Technology ETF", 603.4, 0.009),
        "SPY": ("SPDR S&P 500 ETF Trust", 548.9, 0.004),
        "SCHD": ("Schwab U.S. Dividend Equity ETF", 81.4, 0.002),
        "AAPL": ("Apple Inc.", 214.3, 0.006),
        "MSFT": ("Microsoft Corporation", 448.7, 0.005),
        "GOOGL": ("Alphabet Inc. Class A", 178.1, 0.004),
        "GOOG": ("Alphabet Inc. Class C", 179.4, 0.004),
        "AMZN": ("Amazon.com, Inc.", 186.3, 0.005),
        "META": ("Meta Platforms, Inc.", 514.2, 0.007),
        "AVGO": ("Broadcom Inc.", 161.8, 0.008),
        "AMD": ("Advanced Micro Devices, Inc.", 159.6, 0.003),
        "TSLA": ("Tesla, Inc.", 244.0, -0.032),
        "CRM": ("Salesforce, Inc.", 253.7, 0.002),
        "ORCL": ("Oracle Corporation", 141.5, 0.006),
    }
    if ticker in profiles:
        name, price, change = profiles[ticker]
    else:
        # Deterministic per-ticker price/drift from a stable hash so unknown
        # tickers (e.g. VTI/VXUS/BND) get distinct, non-flat charts instead of
        # an identical 100.0 / 0.0 profile.
        import hashlib

        digest = int(hashlib.sha256(ticker.encode()).hexdigest(), 16)
        name = f"{ticker} fallback card"
        price = round(40.0 + (digest % 400), 2)
        change = round(((digest // 400) % 120 - 60) / 1000.0, 4)  # ~ -0.06..0.06
    revenue_base = price * 420
    margin = 0.18 if change < 0 else 0.24
    note = note or "Fallback card; set TICKER_DATA_MODE=auto or live to refresh from yfinance."
    return c.TickerCard(
        ticker=ticker,
        name=name,
        price=price,
        currency="USD",
        change_pct=change,
        price_series=_synth_price_series(ticker, price, change),
        fundamentals=[
            c.FundamentalRow(year=2024, revenue=round(revenue_base * 0.82, 1), net_income=round(revenue_base * 0.82 * (margin - 0.03), 1), margin=round(margin - 0.03, 3), debt=round(revenue_base * 0.18, 1), dividend=0.0),
            c.FundamentalRow(year=2025, revenue=round(revenue_base * 0.93, 1), net_income=round(revenue_base * 0.93 * (margin - 0.01), 1), margin=round(margin - 0.01, 3), debt=round(revenue_base * 0.16, 1), dividend=0.0),
            c.FundamentalRow(year=2026, revenue=round(revenue_base, 1), net_income=round(revenue_base * margin, 1), margin=round(margin, 3), debt=round(revenue_base * 0.14, 1), dividend=0.0),
        ],
        snowflake=[
            c.SnowflakeAxis(axis="value", value=3.0),
            c.SnowflakeAxis(axis="growth", value=3.4),
            c.SnowflakeAxis(axis="health", value=3.6),
            c.SnowflakeAxis(axis="past", value=3.2),
            c.SnowflakeAxis(axis="dividend", value=2.0),
        ],
        traffic=[
            c.TrafficRating(label="Quality", status="green"),
            c.TrafficRating(label="Value", status="yellow"),
            c.TrafficRating(label="Momentum", status="yellow" if change >= 0 else "red"),
        ],
        percentiles=[
            c.Percentile(metric="P/E", percentile=64 if change >= 0 else 82, context="fallback estimate until live yfinance data is available")
        ],
        # Left empty so ticker_card()'s _with_news enriches from the seed when
        # real demo headlines exist for this ticker (NVDA/TSLA/AAPL/...).
        news=[],
        analyst=c.AnalystBand(low=round(price * 0.78, 2), mean=round(price * 1.08, 2), high=round(price * 1.34, 2), currency="USD"),
        citations=[
            c.Citation(
                id="tc1",
                label=f"{ticker} fallback ticker card",
                source="cached data",
                url=f"https://finance.yahoo.com/quote/{ticker}",
                as_of_date="2026-06-30",
                note=note,
            )
        ],
    )


def ticker_card(ticker: str, data_mode: str | None = None) -> c.TickerCard:
    """Return a TickerCard, enriched with demo headlines when it ships none."""
    return _with_news(_ticker_card_impl(ticker, data_mode))


def _ticker_card_impl(ticker: str, data_mode: str | None = None) -> c.TickerCard:
    """Return a TickerCard from live yfinance, disk cache, or deterministic fallback."""
    ticker = validate_ticker(ticker)
    mode = (data_mode or os.getenv("TICKER_DATA_MODE") or os.getenv("DATA_MODE", "cache")).lower()
    is_cached_etf = ticker in available_etfs()

    if mode == "cache":
        if is_cached_etf:
            card = _etf_card_from_cache(ticker)
            # Enrich with dense seed price history so ETF charts aren't 3 points.
            seed = _read_seed(ticker)
            if seed is not None and len(seed.price_series) > len(card.price_series):
                card = card.model_copy(update={"price_series": seed.price_series})
            return card
        cached = _read_cached(ticker, require_fresh=False)
        return cached or _read_seed(ticker) or _fallback_ticker_card(ticker)
    if mode == "live":
        card = _compute_live(ticker)
        if is_cached_etf:
            card = _etf_card_from_cache(ticker, base=card, note="Live yfinance price enriched with bundled ETF holdings cache.")
        _write_cached(card)
        return card
    if mode == "auto":
        cached = _read_cached(ticker, require_fresh=True)
        if cached is not None:
            return cached
        try:
            card = _compute_live(ticker)
            if is_cached_etf:
                card = _etf_card_from_cache(ticker, base=card, note="Live yfinance price enriched with bundled ETF holdings cache.")
            _write_cached(card)
            return card
        except Exception as exc:
            if is_cached_etf:
                return _etf_card_from_cache(ticker, note=f"Live yfinance unavailable ({type(exc).__name__}); showing cached ETF holdings.")
            return _fallback_ticker_card(ticker, note=f"Live yfinance unavailable ({type(exc).__name__}); showing fallback data.")
    raise ValueError(f"unsupported ticker data mode: {mode!r}")
