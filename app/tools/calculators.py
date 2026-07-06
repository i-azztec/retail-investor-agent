"""Calculator tools (plan §3).

Fee drag and Rule-of-72 are pure formula tools. Growth-of-$X can optionally use
yfinance live history, but defaults to deterministic fallback/cache so tests and
demos do not depend on network availability.
"""

import hashlib
import json
import os
import pathlib
import time

from app import contracts as c
from app.tools.forensic import validate_ticker

# Fixed anchor so the fallback growth axis is deterministic (no Date.now()).
_GROWTH_ANCHOR = (2026, 6)  # (year, month) of the most-recent point


def _months_before_anchor(months_back: int) -> str:
    """ISO 'YYYY-MM-01' string for `months_back` months before the anchor."""
    index = _GROWTH_ANCHOR[0] * 12 + (_GROWTH_ANCHOR[1] - 1) - months_back
    year, month = divmod(index, 12)
    return f"{year:04d}-{month + 1:02d}-01"

# Standard rate ladder shown in the Rule-of-72 table.
_RULE72_LADDER = [2, 4, 6, 8, 10, 12]
_GROWTH_CACHE_DIR = pathlib.Path(__file__).parent.parent / "data" / ".cache" / "growth"
_GROWTH_CACHE_TTL_SECONDS = 12 * 60 * 60


def _validate_positive(name: str, value: float) -> None:
    if value is None or value <= 0:
        raise ValueError(f"{name} must be a positive number, got {value!r}")


def fee_drag(
    amount: float,
    years: int,
    expense_ratio: float,
    gross_return: float = 0.07,
) -> c.FeeDragResult:
    """How much a fund's annual fee quietly costs over time.

    Compares two compounding paths on the same gross return:
      - without fee: balance grows at ``gross_return``
      - with fee:    balance grows at ``gross_return - expense_ratio``

    Assumptions are explicit and returned to the user (named-assumptions principle).
    """
    _validate_positive("amount", amount)
    if not (1 <= years <= 60):
        raise ValueError(f"years must be between 1 and 60, got {years!r}")
    if not (0 <= expense_ratio < 1):
        raise ValueError(f"expense_ratio must be in [0, 1), got {expense_ratio!r}")
    if not (-1 < gross_return < 1):
        raise ValueError(f"gross_return must be in (-1, 1), got {gross_return!r}")

    net_return = gross_return - expense_ratio
    series: list[c.FeePoint] = []
    for year in range(years + 1):
        with_fee = amount * (1 + net_return) ** year
        without_fee = amount * (1 + gross_return) ** year
        series.append(
            c.FeePoint(
                year=year,
                with_fee=round(with_fee, 2),
                without_fee=round(without_fee, 2),
            )
        )

    end_with = series[-1].with_fee
    end_without = series[-1].without_fee
    total_lost = round(end_without - end_with, 2)

    takeaway = (
        f"A {expense_ratio:.2%} fee costs about ${total_lost:,.0f} over {years} years "
        f"on a ${amount:,.0f} investment."
    )

    return c.FeeDragResult(
        inputs=c.FeeInputs(
            amount=amount,
            years=years,
            expense_ratio=expense_ratio,
            gross_return=gross_return,
        ),
        series=series,
        total_lost=total_lost,
        end_with_fee=end_with,
        end_without_fee=end_without,
        assumptions=[
            f"constant {gross_return:.0%}/year gross return",
            "dividends reinvested",
            "no taxes or trading costs",
            "expense ratio charged annually on the balance",
        ],
        takeaway=takeaway,
    )


def rule72(rate_pct: float) -> c.TableBlock:
    """Rule of 72: ~years to double = 72 / annual return (%).

    Returns a ready TableBlock (this tool's output is inherently one small table),
    with the caller's rate highlighted in the takeaway.
    """
    _validate_positive("rate_pct", rate_pct)
    if rate_pct > 100:
        raise ValueError(f"rate_pct must be <= 100, got {rate_pct!r}")

    rates = sorted({*_RULE72_LADDER, round(rate_pct, 2)})
    rows = [[f"{r:g}%", f"{72 / r:.1f}"] for r in rates]

    return c.TableBlock(
        title="Rule of 72 — years to double your money",
        columns=["Annual return", "Years to double"],
        rows=rows,
        takeaway=(
            f"At {rate_pct:g}%, your money roughly doubles in "
            f"{72 / rate_pct:.1f} years."
        ),
    )


class GrowthDataError(RuntimeError):
    """Raised when live growth history cannot be fetched or normalized."""


def _growth_cache_path(symbol: str, years: int, amount: float) -> pathlib.Path:
    amount_key = str(int(amount)) if amount == int(amount) else str(amount).replace(".", "_")
    return _GROWTH_CACHE_DIR / f"{symbol}_{years}y_{amount_key}.json"


def _read_growth_cache(symbol: str, years: int, amount: float, *, require_fresh: bool) -> c.GrowthResult | None:
    path = _growth_cache_path(symbol, years, amount)
    if not path.exists():
        return None
    if require_fresh and time.time() - path.stat().st_mtime > _GROWTH_CACHE_TTL_SECONDS:
        return None
    return c.GrowthResult.model_validate(json.loads(path.read_text(encoding="utf-8")))


def _write_growth_cache(result: c.GrowthResult) -> None:
    _GROWTH_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _growth_cache_path(result.inputs.symbol, result.inputs.years, result.inputs.amount).write_text(
        json.dumps(result.model_dump(mode="json"), indent=2),
        encoding="utf-8",
    )


def _fallback_growth(amount: float, symbol: str, years: int, note: str | None = None) -> c.GrowthResult:
    symbol = validate_ticker(symbol)
    _validate_positive("amount", amount)
    if not (1 <= years <= 60):
        raise ValueError(f"years must be between 1 and 60, got {years!r}")

    annual_returns = {
        "SPY": 0.095,
        "VOO": 0.095,
        "QQQ": 0.125,
        "VGT": 0.145,
        "AAPL": 0.17,
        "MSFT": 0.16,
        "NVDA": 0.28,
        "TSLA": 0.18,
    }
    rate = annual_returns.get(symbol, 0.08)
    # Monthly points so the line reads as a real path, not 6 straight segments.
    # Endpoints stay clean (start = amount, end = pure compound) so the headline
    # matches; interior months get a tiny deterministic wiggle for realism.
    months = years * 12
    series: list[c.GrowthPoint] = []
    for m in range(months + 1):
        value = amount * (1 + rate) ** (m / 12)
        if 0 < m < months:
            seed = int(hashlib.md5(f"{symbol}:{m}".encode()).hexdigest(), 16)
            value *= 1 + ((seed % 300) - 150) / 10_000.0  # ±1.5%
        series.append(c.GrowthPoint(date=_months_before_anchor(months - m), value=round(value, 2)))
    end_value = series[-1].value
    return c.GrowthResult(
        inputs=c.GrowthInputs(amount=amount, symbol=symbol, years=years),
        series=series,
        end_value=end_value,
        cagr=round((end_value / amount) ** (1 / years) - 1, 4),
        assumptions=[
            "fallback annualized return estimate, not actual history",
            "dividends approximated as reinvested",
            "no taxes, fees, or trading costs",
        ],
        note_dividends=True,
        citations=[
            c.Citation(
                id="g1",
                label=f"{symbol} fallback growth scenario",
                source="cached data",
                url=f"https://finance.yahoo.com/quote/{symbol}",
                as_of_date="2026-06-30",
                note=note or "Set GROWTH_DATA_MODE=auto or live to refresh from yfinance history.",
            )
        ],
    )


def _compute_live_growth(amount: float, symbol: str, years: int) -> c.GrowthResult:
    import yfinance as yf

    tk = yf.Ticker(symbol)
    history = tk.history(period=f"{years + 1}y", interval="1mo", auto_adjust=True)
    if history is None or getattr(history, "empty", True):
        raise GrowthDataError(f"no price history returned for {symbol}")

    closes = history["Close"].dropna()
    if len(closes) < 2:
        raise GrowthDataError(f"not enough price history returned for {symbol}")

    start = float(closes.iloc[0])
    if start <= 0:
        raise GrowthDataError(f"invalid starting price for {symbol}")

    points: list[c.GrowthPoint] = []
    for idx, close in closes.items():
        date = idx.date().isoformat() if hasattr(idx, "date") else str(idx)[:10]
        points.append(c.GrowthPoint(date=date, value=round(amount * (float(close) / start), 2)))

    # Keep the UI readable: about monthly points are already compact, but cap
    # very long histories by thinning evenly.
    if len(points) > 80:
        step = max(1, len(points) // 80)
        points = points[::step]
        if points[-1].date != (closes.index[-1].date().isoformat() if hasattr(closes.index[-1], "date") else str(closes.index[-1])[:10]):
            last_idx = closes.index[-1]
            last_date = last_idx.date().isoformat() if hasattr(last_idx, "date") else str(last_idx)[:10]
            points.append(c.GrowthPoint(date=last_date, value=round(amount * (float(closes.iloc[-1]) / start), 2)))

    end_value = points[-1].value
    cagr = (end_value / amount) ** (1 / years) - 1
    return c.GrowthResult(
        inputs=c.GrowthInputs(amount=amount, symbol=symbol, years=years),
        series=points,
        end_value=end_value,
        cagr=round(cagr, 4),
        assumptions=[
            "uses adjusted monthly close history from yfinance",
            "adjusted prices approximate splits and dividends",
            "no taxes, fees, or trading costs",
        ],
        note_dividends=True,
        citations=[
            c.Citation(
                id="g1",
                label=f"{symbol} adjusted price history",
                source="yfinance",
                url=f"https://finance.yahoo.com/quote/{symbol}/history",
                as_of_date=points[-1].date,
                note="Yahoo Finance data can lag or be incomplete.",
            )
        ],
    )


def growth(amount: float, symbol: str = "SPY", years: int = 10, data_mode: str | None = None) -> c.GrowthResult:
    """Growth-of-$X scenario for a ticker or index proxy."""
    symbol = validate_ticker(symbol)
    _validate_positive("amount", amount)
    if not (1 <= years <= 60):
        raise ValueError(f"years must be between 1 and 60, got {years!r}")

    mode = (data_mode or os.getenv("GROWTH_DATA_MODE") or os.getenv("DATA_MODE", "cache")).lower()
    if mode == "cache":
        cached = _read_growth_cache(symbol, years, amount, require_fresh=False)
        return cached or _fallback_growth(amount, symbol, years)
    if mode == "live":
        result = _compute_live_growth(amount, symbol, years)
        _write_growth_cache(result)
        return result
    if mode == "auto":
        cached = _read_growth_cache(symbol, years, amount, require_fresh=True)
        if cached is not None:
            return cached
        try:
            result = _compute_live_growth(amount, symbol, years)
            _write_growth_cache(result)
            return result
        except Exception as exc:
            return _fallback_growth(
                amount,
                symbol,
                years,
                note=f"Live yfinance unavailable ({type(exc).__name__}); showing fallback scenario.",
            )
    raise ValueError(f"unsupported growth data mode: {mode!r}")
