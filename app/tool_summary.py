"""Serialize deterministic tool results into short, human-readable text.

The router computes exact numbers (overlap %, forensic scores, CAGR, fee drag…)
with the tools, then hands this text to the LLM so its narrative is grounded in
our data instead of invented. One dispatcher + one private helper per result
type keeps the serialization in a single, easily-testable place.
"""

from typing import Any

from app import contracts as c


def summarize(intent: str, result: Any, *, ticker_card: c.TickerCard | None = None) -> str:
    """Return a compact plain-text summary of a tool result for LLM grounding."""
    if intent == "overlap":
        return _overlap(c.OverlapResult.model_validate(result))
    if intent == "forensic":
        return _forensic(c.ForensicResult.model_validate(result), ticker_card)
    if intent == "beginner_fees":
        return _fees(c.FeeDragResult.model_validate(result))
    if intent == "growth":
        return _growth(c.GrowthResult.model_validate(result))
    if intent == "compare":
        return _compare(c.CompareResult.model_validate(result))
    if intent == "ticker_card":
        return _ticker(c.TickerCard.model_validate(result))
    raise ValueError(f"tool_summary: unsupported intent {intent!r}")


def _pct(fraction: float, digits: int = 1) -> str:
    return f"{fraction * 100:.{digits}f}%"


def _overlap(r: c.OverlapResult) -> str:
    funds = ", ".join(f.ticker for f in r.funds)
    lines = [
        f"ETF overlap analysis for: {funds}.",
        f"Combined portfolio overlap: {_pct(r.combined_overlap_pct)}.",
        f"Top-10 look-through concentration: {_pct(r.top10_concentration_pct)}.",
    ]
    pairs = list(r.pairwise_overlap_pct.items())
    if pairs:
        pair_text = "; ".join(f"{k.replace('|', '×')} {_pct(v)}" for k, v in pairs[:6])
        lines.append(f"Pairwise overlap by weight: {pair_text}.")
    top_shared = sorted(r.shared_holdings, key=lambda h: h.combined_weight, reverse=True)[:5]
    if top_shared:
        shared_text = "; ".join(f"{h.name} {_pct(h.combined_weight)}" for h in top_shared)
        lines.append(f"Largest shared holdings (combined weight): {shared_text}.")
    top_sectors = sorted(r.sector_breakdown, key=lambda s: s.weight, reverse=True)[:5]
    if top_sectors:
        sector_text = "; ".join(f"{s.sector} {_pct(s.weight)}" for s in top_sectors)
        lines.append(f"Top sectors: {sector_text}.")
    return "\n".join(lines)


def _forensic(r: c.ForensicResult, card: c.TickerCard | None) -> str:
    safe = sum(1 for s in r.scores if s.band == "safe")
    lines = [
        f"Forensic accounting screen for {r.ticker} ({r.name}), as of {r.as_of}.",
        f"{safe}/{len(r.scores)} screens are in the safer band.",
    ]
    for s in r.scores:
        lines.append(f"- {s.name}: {s.value:g} — band {s.band}. {s.interpretation}")
    if card is not None:
        lines.append(f"Latest price: {card.currency} {card.price:,.2f} (move {_pct(card.change_pct)}).")
        if card.percentiles:
            p = card.percentiles[0]
            lines.append(f"{p.metric} valuation percentile: {p.percentile}th ({p.context}).")
    return "\n".join(lines)


def _fees(r: c.FeeDragResult) -> str:
    i = r.inputs
    return "\n".join([
        "Fund fee drag calculation.",
        f"Inputs: ${i.amount:,.0f} invested for {i.years} years, "
        f"expense ratio {_pct(i.expense_ratio, 2)}, gross return {_pct(i.gross_return)}.",
        f"Ending value with fees: ${r.end_with_fee:,.0f}; without fees: ${r.end_without_fee:,.0f}.",
        f"Total lost to fees over the horizon: ${r.total_lost:,.0f}.",
    ])


def _growth(r: c.GrowthResult) -> str:
    i = r.inputs
    lines = [
        "Historical growth-of-money scenario.",
        f"Inputs: ${i.amount:,.0f} in {i.symbol} over {i.years} years.",
        f"Ending value: ${r.end_value:,.0f}; approximate CAGR: {_pct(r.cagr)} per year.",
    ]
    if r.note_dividends:
        lines.append("Note: dividends/splits approximated via adjusted history where available.")
    return "\n".join(lines)


def _compare(r: c.CompareResult) -> str:
    lines = [f"Side-by-side comparison of {', '.join(card.ticker for card in r.cards)}."]
    for card in r.cards:
        traffic = ", ".join(f"{t.label} {t.status}" for t in card.traffic) or "n/a"
        pct = f"{card.percentiles[0].percentile}th ({card.percentiles[0].metric})" if card.percentiles else "n/a"
        analyst = f"{card.analyst.currency} {card.analyst.mean:,.0f}" if card.analyst else "n/a"
        lines.append(
            f"- {card.ticker}: {card.currency} {card.price:,.2f} (move {_pct(card.change_pct)}); "
            f"signals {traffic}; valuation {pct}; analyst mean target {analyst}."
        )
    return "\n".join(lines)


def _ticker(card: c.TickerCard) -> str:
    lines = [
        f"Ticker card for {card.ticker} ({card.name}).",
        f"Price: {card.currency} {card.price:,.2f} (move {_pct(card.change_pct)}).",
    ]
    if card.percentiles:
        p = card.percentiles[0]
        lines.append(f"{p.metric} valuation percentile: {p.percentile}th ({p.context}).")
    if card.traffic:
        lines.append("Signals: " + ", ".join(f"{t.label} {t.status}" for t in card.traffic) + ".")
    if card.fundamentals:
        last = card.fundamentals[-1]
        if last.margin is not None:
            lines.append(f"Latest net margin ({last.year}): {_pct(last.margin)}.")
    if card.analyst:
        lines.append(f"Analyst mean target: {card.analyst.currency} {card.analyst.mean:,.0f}.")
    return "\n".join(lines)
