"""M1: pure forensic-score functions — formulas + bands, no network.

Financials are hand-made dicts so every assertion is deterministic.
"""

import pytest

from app import contracts as c
from app.tools import forensic_scores as fs


# A comfortably healthy company (all components strong).
HEALTHY = {
    "total_assets": 1000.0, "current_assets": 600.0, "current_liabilities": 200.0,
    "total_liabilities": 300.0, "retained_earnings": 450.0, "ebit": 380.0,
    "revenue": 720.0, "net_income": 300.0, "operating_cashflow": 340.0,
    "gross_profit": 500.0, "long_term_debt": 100.0, "shares_outstanding": 1000.0,
    "ppe": 250.0,
}
HEALTHY_PRIOR = {
    "total_assets": 900.0, "current_assets": 500.0, "current_liabilities": 220.0,
    "total_liabilities": 320.0, "retained_earnings": 300.0, "ebit": 300.0,
    "revenue": 600.0, "net_income": 220.0, "operating_cashflow": 250.0,
    "gross_profit": 400.0, "long_term_debt": 130.0, "shares_outstanding": 1000.0,
    "ppe": 240.0,
}


def test_altman_z_healthy_is_safe_and_formula_matches():
    s = fs.altman_z(HEALTHY, market_cap=5000.0)
    assert isinstance(s, c.ForensicScore) and s.name == "Altman Z"
    assert s.band == "safe" and s.value > 2.99
    # recompute by hand
    A = (600 - 200) / 1000; B = 450 / 1000; C = 380 / 1000
    D = 5000 / 300; E = 720 / 1000
    expected = 1.2*A + 1.4*B + 3.3*C + 0.6*D + 1.0*E
    assert s.value == pytest.approx(round(expected, 2))


def test_altman_z_distressed_is_distress_band():
    weak = {"total_assets": 1000.0, "current_assets": 100.0, "current_liabilities": 400.0,
            "total_liabilities": 950.0, "retained_earnings": -200.0, "ebit": -50.0,
            "revenue": 100.0}
    s = fs.altman_z(weak, market_cap=50.0)
    assert s.band == "distress" and s.value < 1.81


def test_altman_z_requires_market_cap():
    with pytest.raises(fs.ForensicDataError):
        fs.altman_z(HEALTHY, market_cap=None)


def test_altman_z_missing_core_field_raises():
    with pytest.raises(fs.ForensicDataError):
        fs.altman_z({"total_assets": 1000.0}, market_cap=1000.0)


def test_beneish_m_stable_company_is_safe():
    s = fs.beneish_m(HEALTHY, HEALTHY_PRIOR)
    assert s.name == "Beneish M"
    assert set(["DSRI", "GMI", "AQI", "SGI", "DEPI", "SGAI", "TATA", "LVGI"]).issubset(s.inputs)
    assert s.band in {"safe", "grey", "distress"}
    # SGI must equal revenue growth exactly
    assert s.inputs["SGI"] == pytest.approx(round(720 / 600, 3))


def test_beneish_m_defaults_missing_indices_to_neutral():
    # only revenue + assets present -> most indices default to 1.0
    latest = {"revenue": 120.0, "total_assets": 1000.0}
    prior = {"revenue": 100.0, "total_assets": 900.0}
    s = fs.beneish_m(latest, prior)
    assert s.inputs["DSRI"] == 1.0 and s.inputs["GMI"] == 1.0
    assert s.inputs["SGI"] == pytest.approx(1.2)


def test_beneish_m_requires_positive_revenue_both_periods():
    with pytest.raises(fs.ForensicDataError):
        fs.beneish_m({"revenue": 0.0, "total_assets": 1.0}, HEALTHY_PRIOR)


def test_piotroski_healthy_scores_high():
    s = fs.piotroski_f(HEALTHY, HEALTHY_PRIOR)
    assert s.name == "Piotroski F"
    assert 0 <= s.value <= 9
    assert s.value >= 7 and s.band == "safe"
    # spot-check a couple of individual tests
    assert s.inputs["positive_net_income"] == 1.0
    assert s.inputs["cfo_gt_ni"] == 1.0  # 340 > 300


def test_piotroski_missing_data_counts_as_fail_and_notes_coverage():
    latest = {"total_assets": 1000.0, "net_income": 100.0, "operating_cashflow": 120.0}
    prior = {"total_assets": 900.0}
    s = fs.piotroski_f(latest, prior)
    assert s.value <= 4
    assert "tests had data" in s.interpretation


def test_piotroski_weak_company_is_distress():
    weak = {"total_assets": 1000.0, "net_income": -50.0, "operating_cashflow": -30.0,
            "revenue": 100.0, "current_assets": 50.0, "current_liabilities": 200.0,
            "gross_profit": 10.0, "long_term_debt": 500.0, "shares_outstanding": 1200.0}
    weak_prior = {"total_assets": 900.0, "net_income": 20.0, "operating_cashflow": 30.0,
                  "revenue": 120.0, "current_assets": 80.0, "current_liabilities": 150.0,
                  "gross_profit": 40.0, "long_term_debt": 300.0, "shares_outstanding": 1000.0}
    s = fs.piotroski_f(weak, weak_prior)
    assert s.band == "distress" and s.value <= 3
