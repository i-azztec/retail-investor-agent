"""M1: deterministic calculator tools — outcomes + input guards."""

import pytest

from app import contracts as c
from app.tools import calculators as calc


def test_fee_drag_shapes_and_outcome():
    r = calc.fee_drag(amount=10_000, years=20, expense_ratio=0.0075, gross_return=0.07)
    assert isinstance(r, c.FeeDragResult)
    assert len(r.series) == 21  # years 0..20 inclusive
    # year 0 = principal, untouched by either path
    assert r.series[0].with_fee == 10_000 and r.series[0].without_fee == 10_000
    # fee always drags: with_fee <= without_fee, gap grows
    assert all(p.with_fee <= p.without_fee for p in r.series)
    assert r.total_lost > 0
    assert r.end_without_fee > r.end_with_fee
    # sanity vs closed form: 10000 * 1.07^20 ~= 38,697
    assert abs(r.end_without_fee - 10_000 * 1.07**20) < 1.0
    assert r.assumptions  # named assumptions present


def test_fee_drag_zero_fee_means_no_loss():
    r = calc.fee_drag(amount=5_000, years=10, expense_ratio=0.0)
    assert r.total_lost == 0
    assert r.end_with_fee == r.end_without_fee


@pytest.mark.parametrize(
    "kwargs",
    [
        {"amount": 0, "years": 20, "expense_ratio": 0.01},
        {"amount": -100, "years": 20, "expense_ratio": 0.01},
        {"amount": 1000, "years": 0, "expense_ratio": 0.01},
        {"amount": 1000, "years": 61, "expense_ratio": 0.01},
        {"amount": 1000, "years": 20, "expense_ratio": 1.5},
        {"amount": 1000, "years": 20, "expense_ratio": -0.01},
    ],
)
def test_fee_drag_rejects_bad_input(kwargs):
    with pytest.raises(ValueError):
        calc.fee_drag(**kwargs)


def test_rule72_basic():
    b = calc.rule72(6)
    assert isinstance(b, c.TableBlock)
    assert b.columns == ["Annual return", "Years to double"]
    # 72/6 = 12 years, present in a row and the takeaway
    assert any(row[0] == "6%" and row[1] == "12.0" for row in b.rows)
    assert "12.0 years" in b.takeaway


def test_rule72_injects_custom_rate_into_ladder():
    b = calc.rule72(6)
    b2 = calc.rule72(5)  # 5 is not in the standard ladder
    assert any(row[0] == "5%" for row in b2.rows)
    assert len(b2.rows) == len(b.rows) + 1  # one extra rate row


@pytest.mark.parametrize("rate", [0, -3, 150])
def test_rule72_rejects_bad_rate(rate):
    with pytest.raises(ValueError):
        calc.rule72(rate)


def test_growth_cache_mode_returns_fallback_scenario(monkeypatch, tmp_path):
    monkeypatch.setattr(calc, "_GROWTH_CACHE_DIR", tmp_path)

    result = calc.growth(amount=10_000, symbol="TSLA", years=5, data_mode="cache")

    assert isinstance(result, c.GrowthResult)
    assert result.inputs.symbol == "TSLA"
    assert result.inputs.amount == 10_000
    assert len(result.series) == 61  # monthly points: years*12 + 1
    assert result.end_value > 10_000
    assert result.citations[0].source == "cached data"


def test_growth_auto_refreshes_and_writes_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(calc, "_GROWTH_CACHE_DIR", tmp_path)

    def fake_live(amount: float, symbol: str, years: int) -> c.GrowthResult:
        return c.GrowthResult(
            inputs=c.GrowthInputs(amount=amount, symbol=symbol, years=years),
            series=[
                c.GrowthPoint(date="2021-01-01", value=amount),
                c.GrowthPoint(date="2026-01-01", value=amount * 2),
            ],
            end_value=amount * 2,
            cagr=0.149,
            assumptions=["mock live"],
            note_dividends=True,
            citations=[c.Citation(id="g1", label="mock", source="yfinance", url="https://example.com")],
        )

    monkeypatch.setattr(calc, "_compute_live_growth", fake_live)

    result = calc.growth(amount=5_000, symbol="SPY", years=5, data_mode="auto")
    cached = calc.growth(amount=5_000, symbol="SPY", years=5, data_mode="cache")

    assert result.citations[0].source == "yfinance"
    assert cached.end_value == 10_000


def test_growth_rejects_bad_inputs():
    with pytest.raises(ValueError):
        calc.growth(amount=0, symbol="SPY", years=5)
    with pytest.raises(ValueError):
        calc.growth(amount=1000, symbol="bad ticker", years=5)
    with pytest.raises(ValueError):
        calc.growth(amount=1000, symbol="SPY", years=0)
