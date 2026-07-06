"""Forensic tool — live yfinance fundamentals → 3 screening scores (plan §3).

Fetches current + prior fiscal-year statements from yfinance, normalizes them
into flat `Period` dicts (field mapping adapted from Ragesh-Thangaraj/
Multiagent-Stock-Analytics-System, MIT), then computes Altman Z / Beneish M /
Piotroski F via the pure functions in forensic_scores.py.

DATA_MODE (env) controls live vs cache:
  - "live"  : always hit yfinance (raise on failure)
  - "cache" : always use the bundled fixture
  - "auto"  : try live, fall back to fixture + honesty note (default; robust for demo)
"""

import json
import os
import pathlib
import re

from app import contracts as c
from app.tools import forensic_scores as fs

_TICKER_RE = re.compile(r"^[A-Z][A-Z.\-]{0,9}$")
_FIXTURE = pathlib.Path(__file__).parent.parent / "fixtures" / "tool_forensic.json"

# yfinance balance-sheet/income row label -> our normalized key.
_BALANCE_MAP = {
    "total_assets": ["Total Assets"],
    "current_assets": ["Current Assets", "Total Current Assets"],
    "current_liabilities": ["Current Liabilities", "Total Current Liabilities"],
    "total_liabilities": ["Total Liabilities Net Minority Interest", "Total Liabilities"],
    "retained_earnings": ["Retained Earnings"],
    "total_debt": ["Total Debt"],
    "long_term_debt": ["Long Term Debt"],
    "receivables": ["Receivables", "Accounts Receivable", "Net Receivables"],
    "ppe": ["Net PPE", "Net Property Plant And Equipment"],
}
_INCOME_MAP = {
    "revenue": ["Total Revenue"],
    "cogs": ["Cost Of Revenue"],
    "gross_profit": ["Gross Profit"],
    "operating_income": ["Operating Income"],
    "ebit": ["EBIT"],
    "net_income": ["Net Income"],
    "sga": ["Selling General And Administration", "Selling General And Administrative"],
    "depreciation": ["Reconciled Depreciation", "Depreciation And Amortization"],
}
_CASHFLOW_MAP = {
    "operating_cashflow": ["Operating Cash Flow", "Total Cash From Operating Activities"],
}


def validate_ticker(ticker: str) -> str:
    """Uppercase + validate ticker shape (plan §7 input validation)."""
    if not ticker or not ticker.strip():
        raise ValueError("ticker must be a non-empty string")
    t = ticker.strip().upper()
    if not _TICKER_RE.match(t):
        raise ValueError(f"invalid ticker format: {ticker!r}")
    return t


def _col(df, col_idx: int, mapping: dict) -> dict:
    """Extract one statement column (fiscal period) into a normalized dict."""
    out: dict[str, float] = {}
    if df is None or getattr(df, "empty", True) or df.shape[1] <= col_idx:
        return out
    series = df.iloc[:, col_idx]
    for key, labels in mapping.items():
        for label in labels:
            if label in series.index:
                val = series.get(label)
                if val is not None and val == val:  # not NaN
                    out[key] = float(val)
                    break
    return out


def _build_periods(tk) -> tuple[dict, dict, dict]:
    """Return (info, latest_period, prior_period) from a yfinance Ticker."""
    info = tk.info or {}
    balance = tk.balance_sheet
    income = tk.income_stmt
    cashflow = tk.cashflow

    def period(idx: int) -> dict:
        p: dict = {}
        p.update(_col(balance, idx, _BALANCE_MAP))
        p.update(_col(income, idx, _INCOME_MAP))
        p.update(_col(cashflow, idx, _CASHFLOW_MAP))
        return p

    latest = period(0)
    prior = period(1)
    if info.get("sharesOutstanding"):
        latest.setdefault("shares_outstanding", float(info["sharesOutstanding"]))
    if info.get("marketCap"):
        latest.setdefault("market_cap", float(info["marketCap"]))
    return info, latest, prior


def _edgar_citation(ticker: str) -> c.Citation:
    return c.Citation(
        id="c1",
        label=f"{ticker} filings — SEC EDGAR",
        source="SEC EDGAR",
        url=f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={ticker}&type=10-K",
    )


def _from_fixture(ticker: str = "NVDA", note: str | None = None) -> c.ForensicResult:
    data = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    result = c.ForensicResult(**data)
    ticker = validate_ticker(ticker)
    if ticker != result.ticker:
        result.ticker = ticker
        result.name = f"{ticker} cached forensic demo"
        result.citations = [
            c.Citation(
                id="c1",
                label=f"{ticker} cached forensic demo",
                source="cached data",
                url=f"https://finance.yahoo.com/quote/{ticker}",
                as_of_date=result.as_of,
                note="Forensic formulas shown with cached demo inputs until live filings are enabled.",
            )
        ]
        for score in result.scores:
            score.source_line = "cached demo financial statement inputs"
            score.citation_id = "c1"
    if note:
        result.citations.append(
            c.Citation(id="_note", label=note, source="cached data", url="")
        )
    return result


def _compute_live(ticker: str) -> c.ForensicResult:
    import yfinance as yf

    tk = yf.Ticker(ticker)
    info, latest, prior = _build_periods(tk)
    if not latest.get("total_assets"):
        raise fs.ForensicDataError(f"no fundamentals returned for {ticker}")

    market_cap = latest.get("market_cap")
    citation = _edgar_citation(ticker)
    scores: list[c.ForensicScore] = []
    for fn in (
        lambda: fs.altman_z(latest, market_cap),
        lambda: fs.beneish_m(latest, prior),
        lambda: fs.piotroski_f(latest, prior),
    ):
        try:
            s = fn()
            s.citation_id = citation.id
            scores.append(s)
        except fs.ForensicDataError:
            continue  # skip scores we can't compute; others still returned

    if not scores:
        raise fs.ForensicDataError(f"could not compute any score for {ticker}")

    as_of = ""
    bs = tk.balance_sheet
    if bs is not None and not getattr(bs, "empty", True):
        as_of = str(bs.columns[0].date()) if hasattr(bs.columns[0], "date") else str(bs.columns[0])

    return c.ForensicResult(
        ticker=ticker,
        name=info.get("longName") or info.get("shortName") or ticker,
        as_of=as_of,
        scores=scores,
        citations=[citation],
    )


def forensic(ticker: str, data_mode: str | None = None) -> c.ForensicResult:
    """Compute forensic screening scores for a ticker. See module docstring."""
    ticker = validate_ticker(ticker)
    mode = (data_mode or os.getenv("DATA_MODE", "auto")).lower()

    if mode == "cache":
        return _from_fixture(ticker)
    if mode == "live":
        return _compute_live(ticker)
    # auto
    try:
        return _compute_live(ticker)
    except Exception:
        result = _from_fixture(ticker)
        result.citations.append(
            c.Citation(id="_note", label="live data unavailable — showing cached example",
                       source="yfinance", url="")
        )
        return result
