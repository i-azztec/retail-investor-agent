"""ETF overlap tool — cached holdings -> deterministic look-through panel data.

The hard part of ETF overlap is not the math, it is reliable holdings refresh.
For the prototype we keep a small normalized holdings cache in
app/data/etf_holdings/*.json and make the calculation fully deterministic.
Later, a refresh script can replace those JSON files without changing this API.
"""

import json
import pathlib
import re
from collections import defaultdict
from itertools import combinations
from typing import Any

from app import contracts as c

_DATA_DIR = pathlib.Path(__file__).parent.parent / "data" / "etf_holdings"
_TICKER_RE = re.compile(r"^[A-Z][A-Z.\-]{0,9}$")


def validate_etf_ticker(ticker: str) -> str:
    """Uppercase + validate an ETF ticker before touching the filesystem."""
    if not ticker or not ticker.strip():
        raise ValueError("ticker must be a non-empty string")
    t = ticker.strip().upper()
    if not _TICKER_RE.match(t):
        raise ValueError(f"invalid ETF ticker format: {ticker!r}")
    return t


def _load_fund(ticker: str) -> dict[str, Any]:
    path = _DATA_DIR / f"{ticker}.json"
    if not path.exists():
        available = ", ".join(available_etfs())
        raise FileNotFoundError(f"no cached holdings for {ticker}; available: {available}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("ticker", "").upper() != ticker:
        raise ValueError(f"holdings file {path.name} has mismatched ticker")
    if not data.get("holdings"):
        raise ValueError(f"holdings file {path.name} has no holdings")
    return data


def load_cached_etf(ticker: str) -> dict[str, Any]:
    """Return the normalized cached ETF holdings payload for one fund."""
    return _load_fund(validate_etf_ticker(ticker))


def _holding_key(holding: dict[str, Any]) -> str:
    return str(holding.get("ticker") or holding.get("name") or "").upper()


def _fund_info(data: dict[str, Any]) -> c.FundInfo:
    return c.FundInfo(
        ticker=data["ticker"].upper(),
        name=data["name"],
        expense_ratio=float(data.get("expense_ratio", 0.0)),
        as_of=data["as_of"],
    )


def _citations(funds: list[dict[str, Any]]) -> list[c.Citation]:
    citations: list[c.Citation] = []
    for idx, fund in enumerate(funds, start=1):
        citations.append(
            c.Citation(
                id=f"c{idx}",
                label=f"{fund['ticker'].upper()} holdings",
                source=fund.get("source", "issuer"),
                url=fund.get("source_url", ""),
                as_of_date=fund.get("as_of"),
                note=fund.get("note", "cached holdings"),
            )
        )
    return citations


def _normalized_input(tickers: list[str]) -> list[str]:
    normalized = [validate_etf_ticker(t) for t in tickers]
    deduped = list(dict.fromkeys(normalized))
    if len(deduped) < 2:
        raise ValueError("overlap requires at least two distinct ETF tickers")
    if len(deduped) > 5:
        raise ValueError("overlap supports up to 5 ETFs in the prototype")
    return deduped


def _weights_by_fund(funds: list[dict[str, Any]]) -> dict[str, dict[str, dict[str, Any]]]:
    by_fund: dict[str, dict[str, dict[str, Any]]] = {}
    for fund in funds:
        ticker = fund["ticker"].upper()
        holdings: dict[str, dict[str, Any]] = {}
        for raw in fund["holdings"]:
            key = _holding_key(raw)
            if not key:
                continue
            holdings[key] = {
                "name": raw["name"],
                "ticker": raw.get("ticker", key).upper(),
                "sector": raw.get("sector") or "Unknown",
                "weight": float(raw["weight"]),
            }
        by_fund[ticker] = holdings
    return by_fund


def overlap(tickers: list[str]) -> c.OverlapResult:
    """Compute pairwise overlap and equal-weight look-through exposure.

    Pairwise overlap is the usual ETF-overlap formula:
    ``sum(min(weight_in_a, weight_in_b))`` over shared holdings.

    Combined portfolio views assume equal dollars in each ETF, matching the
    flagship demo question ($10k in VOO, QQQ, and VGT).
    """
    normalized = _normalized_input(tickers)
    raw_funds = [_load_fund(t) for t in normalized]
    weights = _weights_by_fund(raw_funds)
    fund_count = len(raw_funds)
    allocation = 1.0 / fund_count

    pairwise: dict[str, float] = {}
    for left, right in combinations(normalized, 2):
        left_weights = weights[left]
        right_weights = weights[right]
        shared_keys = set(left_weights) & set(right_weights)
        pairwise[f"{left}|{right}"] = round(
            sum(
                min(left_weights[key]["weight"], right_weights[key]["weight"])
                for key in shared_keys
            ),
            6,
        )

    lookthrough_by_key: dict[str, dict[str, Any]] = {}
    sectors: defaultdict[str, float] = defaultdict(float)
    for fund_ticker, holdings in weights.items():
        for key, holding in holdings.items():
            weighted = holding["weight"] * allocation
            item = lookthrough_by_key.setdefault(
                key,
                {
                    "name": holding["name"],
                    "ticker": holding["ticker"],
                    "sector": holding["sector"],
                    "combined_weight": 0.0,
                    "fund_count": 0,
                    "weight_by_fund": {},
                },
            )
            item["combined_weight"] += weighted
            item["fund_count"] += 1
            item["weight_by_fund"][fund_ticker] = holding["weight"]
            sectors[holding["sector"]] += weighted

    lookthrough_rows = sorted(
        lookthrough_by_key.values(),
        key=lambda item: item["combined_weight"],
        reverse=True,
    )
    shared_rows = [item for item in lookthrough_rows if item["fund_count"] >= 2]

    # Equal-weight portfolio dollars invested in repeated names.
    combined_overlap_pct = sum(item["combined_weight"] for item in shared_rows)
    top10_concentration_pct = sum(item["combined_weight"] for item in lookthrough_rows[:10])

    return c.OverlapResult(
        funds=[_fund_info(fund) for fund in raw_funds],
        pairwise_overlap_pct=pairwise,
        combined_overlap_pct=round(combined_overlap_pct, 6),
        shared_holdings=[
            c.SharedHolding(
                name=item["name"],
                ticker=item["ticker"],
                weight_by_fund={
                    ticker: round(float(value), 6)
                    for ticker, value in item["weight_by_fund"].items()
                },
                combined_weight=round(float(item["combined_weight"]), 6),
            )
            for item in shared_rows
        ],
        look_through=[
            c.LookThroughItem(
                name=item["name"],
                ticker=item["ticker"],
                combined_weight=round(float(item["combined_weight"]), 6),
                sector=item["sector"],
            )
            for item in lookthrough_rows
        ],
        sector_breakdown=[
            c.SectorWeight(sector=sector, weight=round(weight, 6))
            for sector, weight in sorted(sectors.items(), key=lambda row: row[1], reverse=True)
        ],
        top10_concentration_pct=round(top10_concentration_pct, 6),
        citations=_citations(raw_funds),
    )


def available_etfs() -> list[str]:
    """Return tickers with bundled holdings cache."""
    if not _DATA_DIR.exists():
        return []
    return sorted(path.stem.upper() for path in _DATA_DIR.glob("*.json"))
