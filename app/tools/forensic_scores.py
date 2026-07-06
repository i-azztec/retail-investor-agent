"""Pure forensic-score functions — no network, fully deterministic (plan §3, §7).

Three classic screening scores computed by formula from normalized financials:
  - Altman Z   (bankruptcy risk)        — 1 period + market cap
  - Beneish M  (earnings manipulation)  — needs current + prior period
  - Piotroski F(financial strength)     — needs current + prior period

Each returns a contracts.ForensicScore {value, formula, inputs, interpretation,
band}. Input is a `Financials` dict (see forensic.py for how it's built from
yfinance) so these are unit-testable on hand-made numbers without any API.

Altman Z formula + yfinance field mapping + interpretation thresholds adapted
from Ragesh-Thangaraj/Multiagent-Stock-Analytics-System (MIT). Beneish M and
Piotroski F are our own implementation.
"""

from typing import Optional

from app import contracts as c


class ForensicDataError(ValueError):
    """Raised when required fundamentals are missing to compute a score."""


# A period is a flat dict of line items (floats or None). See forensic.py.
Period = dict[str, Optional[float]]


def _req(period: Period, *keys: str) -> float:
    """Fetch a required numeric field; raise if missing/None."""
    for key in keys:
        v = period.get(key)
        if v is not None:
            return float(v)
    raise ForensicDataError(f"missing required field: {' / '.join(keys)}")


def _opt(period: Period, *keys: str) -> Optional[float]:
    for key in keys:
        v = period.get(key)
        if v is not None:
            return float(v)
    return None


# --------------------------------------------------------------------------- #
# Altman Z-Score
# --------------------------------------------------------------------------- #
def altman_z(latest: Period, market_cap: Optional[float]) -> c.ForensicScore:
    """Z = 1.2·A + 1.4·B + 3.3·C + 0.6·D + 1.0·E.

    A=WC/TA, B=RE/TA, C=EBIT/TA, D=MktCap/TotalLiab, E=Sales/TA.
    Bands (classic manufacturing model): >2.99 safe, 1.81–2.99 grey, <1.81 distress.
    """
    total_assets = _req(latest, "total_assets")
    if total_assets <= 0:
        raise ForensicDataError("total_assets must be positive")
    total_liabilities = _req(latest, "total_liabilities")
    ebit = _req(latest, "ebit", "operating_income")
    revenue = _req(latest, "revenue")

    current_assets = _opt(latest, "current_assets")
    current_liabilities = _opt(latest, "current_liabilities")
    working_capital = (
        (current_assets - current_liabilities)
        if (current_assets is not None and current_liabilities is not None)
        else _req(latest, "working_capital")
    )
    retained_earnings = _opt(latest, "retained_earnings") or 0.0
    mcap = market_cap if (market_cap and market_cap > 0) else _opt(latest, "market_cap")
    if not mcap:
        raise ForensicDataError("market_cap required for Altman Z (component D)")

    A = working_capital / total_assets
    B = retained_earnings / total_assets
    C = ebit / total_assets
    D = mcap / total_liabilities if total_liabilities else 0.0
    E = revenue / total_assets
    z = 1.2 * A + 1.4 * B + 3.3 * C + 0.6 * D + 1.0 * E

    if z > 2.99:
        band, interp = "safe", "Above 2.99 — low bankruptcy risk."
    elif z >= 1.81:
        band, interp = "grey", "Between 1.81 and 2.99 — grey zone, monitor."
    else:
        band, interp = "distress", "Below 1.81 — distress zone, elevated bankruptcy risk."

    return c.ForensicScore(
        name="Altman Z",
        value=round(z, 2),
        formula="1.2·A + 1.4·B + 3.3·C + 0.6·D + 1.0·E",
        inputs={
            "working_capital_to_assets": round(A, 3),
            "retained_earnings_to_assets": round(B, 3),
            "ebit_to_assets": round(C, 3),
            "mktcap_to_liabilities": round(D, 3),
            "sales_to_assets": round(E, 3),
        },
        interpretation=interp,
        band=band,
    )


# --------------------------------------------------------------------------- #
# Beneish M-Score
# --------------------------------------------------------------------------- #
def beneish_m(latest: Period, prior: Period) -> c.ForensicScore:
    """8-variable Beneish M-Score for earnings-manipulation likelihood.

    M = -4.84 + 0.92·DSRI + 0.528·GMI + 0.404·AQI + 0.892·SGI
        + 0.115·DEPI - 0.172·SGAI + 4.679·TATA - 0.327·LVGI
    Threshold: M > -1.78 suggests likely manipulation.
    Indices default to 1.0 (neutral) when a component's inputs are unavailable.
    """
    rev_t = _req(latest, "revenue")
    rev_p = _req(prior, "revenue")
    if rev_p <= 0 or rev_t <= 0:
        raise ForensicDataError("revenue must be positive in both periods")
    ta_t = _req(latest, "total_assets")
    ta_p = _req(prior, "total_assets")

    # SGI — Sales Growth Index
    sgi = rev_t / rev_p

    # DSRI — Days Sales in Receivables Index
    rec_t = _opt(latest, "receivables")
    rec_p = _opt(prior, "receivables")
    dsri = ((rec_t / rev_t) / (rec_p / rev_p)) if (rec_t and rec_p) else 1.0

    # GMI — Gross Margin Index (prior GM / current GM)
    def _gm(period: Period, rev: float) -> Optional[float]:
        gp = _opt(period, "gross_profit")
        if gp is None:
            cogs = _opt(period, "cogs")
            gp = (rev - cogs) if cogs is not None else None
        return (gp / rev) if gp is not None else None

    gm_t = _gm(latest, rev_t)
    gm_p = _gm(prior, rev_p)
    gmi = (gm_p / gm_t) if (gm_t and gm_p and gm_t != 0) else 1.0

    # AQI — Asset Quality Index
    def _non_quality_ratio(period: Period, ta: float) -> Optional[float]:
        ca = _opt(period, "current_assets")
        ppe = _opt(period, "ppe", "net_ppe")
        if ca is None or ppe is None or ta == 0:
            return None
        return 1.0 - (ca + ppe) / ta

    aq_t = _non_quality_ratio(latest, ta_t)
    aq_p = _non_quality_ratio(prior, ta_p)
    aqi = (aq_t / aq_p) if (aq_t and aq_p and aq_p != 0) else 1.0

    # DEPI — Depreciation Index
    def _dep_rate(period: Period) -> Optional[float]:
        dep = _opt(period, "depreciation")
        ppe = _opt(period, "ppe", "net_ppe")
        if dep is None or ppe is None or (dep + ppe) == 0:
            return None
        return dep / (dep + ppe)

    dep_t = _dep_rate(latest)
    dep_p = _dep_rate(prior)
    depi = (dep_p / dep_t) if (dep_t and dep_p and dep_t != 0) else 1.0

    # SGAI — SG&A Index
    def _sga_ratio(period: Period, rev: float) -> Optional[float]:
        sga = _opt(period, "sga")
        return (sga / rev) if (sga is not None and rev) else None

    sga_t = _sga_ratio(latest, rev_t)
    sga_p = _sga_ratio(prior, rev_p)
    sgai = (sga_t / sga_p) if (sga_t and sga_p and sga_p != 0) else 1.0

    # LVGI — Leverage Index
    def _lev(period: Period, ta: float) -> Optional[float]:
        tl = _opt(period, "total_liabilities")
        return (tl / ta) if (tl is not None and ta) else None

    lev_t = _lev(latest, ta_t)
    lev_p = _lev(prior, ta_p)
    lvgi = (lev_t / lev_p) if (lev_t and lev_p and lev_p != 0) else 1.0

    # TATA — Total Accruals to Total Assets
    ni = _opt(latest, "net_income")
    cfo = _opt(latest, "operating_cashflow")
    tata = ((ni - cfo) / ta_t) if (ni is not None and cfo is not None and ta_t) else 0.0

    m = (
        -4.84
        + 0.92 * dsri
        + 0.528 * gmi
        + 0.404 * aqi
        + 0.892 * sgi
        + 0.115 * depi
        - 0.172 * sgai
        + 4.679 * tata
        - 0.327 * lvgi
    )

    if m > -1.78:
        band, interp = "distress", "Above -1.78 — possible earnings manipulation (screen, not proof)."
    elif m > -2.22:
        band, interp = "grey", "Between -2.22 and -1.78 — borderline, worth a closer look."
    else:
        band, interp = "safe", "Below -1.78 — no strong signal of earnings manipulation."

    return c.ForensicScore(
        name="Beneish M",
        value=round(m, 2),
        formula=(
            "-4.84 + 0.92·DSRI + 0.528·GMI + 0.404·AQI + 0.892·SGI "
            "+ 0.115·DEPI - 0.172·SGAI + 4.679·TATA - 0.327·LVGI"
        ),
        inputs={
            "DSRI": round(dsri, 3), "GMI": round(gmi, 3), "AQI": round(aqi, 3),
            "SGI": round(sgi, 3), "DEPI": round(depi, 3), "SGAI": round(sgai, 3),
            "TATA": round(tata, 3), "LVGI": round(lvgi, 3),
        },
        interpretation=interp,
        band=band,
    )


# --------------------------------------------------------------------------- #
# Piotroski F-Score
# --------------------------------------------------------------------------- #
def piotroski_f(latest: Period, prior: Period) -> c.ForensicScore:
    """9 binary financial-health tests; score 0–9 (higher = stronger).

    Missing inputs count as a failed (0) test — we note how many were computable.
    Bands: >=7 safe, 4–6 grey, <=3 distress.
    """
    ta_t = _req(latest, "total_assets")
    ta_p = _opt(prior, "total_assets") or ta_t
    avg_assets_t = (ta_t + (ta_p or ta_t)) / 2

    ni = _opt(latest, "net_income")
    cfo = _opt(latest, "operating_cashflow")
    ni_p = _opt(prior, "net_income")

    tests: dict[str, int] = {}
    computable = 0

    def record(name: str, ok: Optional[bool]) -> None:
        nonlocal computable
        if ok is None:
            tests[name] = 0
        else:
            tests[name] = 1 if ok else 0
            computable += 1

    # Profitability
    record("positive_net_income", (ni > 0) if ni is not None else None)
    record("positive_cfo", (cfo > 0) if cfo is not None else None)
    roa_t = (ni / avg_assets_t) if (ni is not None and avg_assets_t) else None
    roa_p = (ni_p / ta_p) if (ni_p is not None and ta_p) else None
    record("improving_roa", (roa_t > roa_p) if (roa_t is not None and roa_p is not None) else None)
    record("cfo_gt_ni", (cfo > ni) if (cfo is not None and ni is not None) else None)

    # Leverage / liquidity
    def _lev(period: Period, ta: float) -> Optional[float]:
        ltd = _opt(period, "long_term_debt", "total_debt")
        return (ltd / ta) if (ltd is not None and ta) else None

    lev_t = _lev(latest, ta_t)
    lev_p = _lev(prior, ta_p or ta_t)
    record("lower_leverage", (lev_t < lev_p) if (lev_t is not None and lev_p is not None) else None)

    def _current_ratio(period: Period) -> Optional[float]:
        ca = _opt(period, "current_assets")
        cl = _opt(period, "current_liabilities")
        return (ca / cl) if (ca is not None and cl) else None

    cr_t = _current_ratio(latest)
    cr_p = _current_ratio(prior)
    record("higher_current_ratio", (cr_t > cr_p) if (cr_t is not None and cr_p is not None) else None)

    shares_t = _opt(latest, "shares_outstanding")
    shares_p = _opt(prior, "shares_outstanding")
    record("no_dilution", (shares_t <= shares_p * 1.01) if (shares_t and shares_p) else None)

    # Efficiency
    def _gm(period: Period) -> Optional[float]:
        rev = _opt(period, "revenue")
        gp = _opt(period, "gross_profit")
        if gp is None:
            cogs = _opt(period, "cogs")
            gp = (rev - cogs) if (rev is not None and cogs is not None) else None
        return (gp / rev) if (gp is not None and rev) else None

    record("improving_margin",
           (_gm(latest) > _gm(prior)) if (_gm(latest) is not None and _gm(prior) is not None) else None)

    rev_t = _opt(latest, "revenue")
    rev_p = _opt(prior, "revenue")
    at_t = (rev_t / avg_assets_t) if (rev_t and avg_assets_t) else None
    at_p = (rev_p / ta_p) if (rev_p and ta_p) else None
    record("higher_asset_turnover", (at_t > at_p) if (at_t is not None and at_p is not None) else None)

    score = sum(tests.values())
    if score >= 7:
        band, interp = "safe", f"{score}/9 — financially strong."
    elif score >= 4:
        band, interp = "grey", f"{score}/9 — mixed financial health."
    else:
        band, interp = "distress", f"{score}/9 — financially weak."
    if computable < 9:
        interp += f" ({computable}/9 tests had data; missing counted as fail.)"

    return c.ForensicScore(
        name="Piotroski F",
        value=float(score),
        formula="sum of 9 binary financial-health tests",
        inputs={k: float(v) for k, v in tests.items()},
        interpretation=interp,
        band=band,
    )
