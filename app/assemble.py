"""Assemble deterministic tool results into the universal ResponsePanel.

The agent layer owns routing and polished language. This module owns structure:
tool contract in, renderable panel contract out. That lets FastAPI and React be
built against one stable shape before the final LLM orchestration is wired in.
"""

from typing import Any

from app import contracts as c
from app.settings import llm_settings


def _pct(value: float, digits: int = 0) -> str:
    return f"{value * 100:.{digits}f}%"


def _round_pct(value: float, digits: int = 1) -> float:
    return round(value * 100, digits)


def _first_citation_id(citations: list[c.Citation]) -> str | None:
    return citations[0].id if citations else None


def _meta(cached: bool = False, latency_ms: int = 0) -> c.Meta:
    return c.Meta(generated_by=llm_settings().model, cached=cached, latency_ms=latency_ms)


def _entity_once(items: list[c.Entity]) -> list[c.Entity]:
    seen: set[tuple[str, str]] = set()
    out: list[c.Entity] = []
    for item in items:
        key = (item.kind, item.ref.upper() if item.kind == "ticker" else item.ref.lower())
        if key not in seen:
            seen.add(key)
            out.append(item)
    return out


def _with_generic(panel: c.ResponsePanel, generic: c.GenericAnswerResult | None) -> c.ResponsePanel:
    """Fold an LLM narrative (grounded in tool numbers) into a deterministic panel.

    Puts the LLM prose first as a TextBlock, overrides headline/pros/cons when the
    LLM supplied them, tops up followups by kind, and appends LLM limitations. A
    ``None`` or empty narrative leaves the panel untouched.

    When the narrative is missing, this route *wanted* an LLM voice but the LLM
    was unavailable, so we stamp ``meta.llm_degraded`` — the durable cache uses it
    to recompute the turn once an LLM is configured instead of serving this bare
    deterministic panel forever.
    """
    if generic is None or not generic.answer_md.strip():
        panel.meta.llm_degraded = True
        return panel
    llm_fus = generic.followups[:12]
    have = {f.kind for f in llm_fus}
    followups = llm_fus + [f for f in panel.followups if f.kind not in have]
    return panel.model_copy(update={
        "headline": generic.headline or panel.headline,
        "blocks": [c.TextBlock(markdown=generic.answer_md), *panel.blocks],
        "pros": generic.pros or panel.pros,
        "cons": generic.cons or panel.cons,
        "followups": followups,
        "honesty_notes": [*panel.honesty_notes, *generic.limitations],
    })


def _narr_value(narr: c.Narr | dict[str, Any] | None, field: str, default: Any) -> Any:
    if narr is None:
        return default
    if isinstance(narr, c.Narr):
        return getattr(narr, field)
    return narr.get(field, default)


def _pros_value(pros: c.Pros | dict[str, Any] | list[str] | None, default: list[str]) -> list[str]:
    if pros is None:
        return default
    if isinstance(pros, c.Pros):
        return pros.pros
    if isinstance(pros, list):
        return pros
    return list(pros.get("pros", default))


def _cons_value(cons: c.Cons | dict[str, Any] | list[str] | None, default: list[str]) -> list[str]:
    if cons is None:
        return default
    if isinstance(cons, c.Cons):
        return cons.cons
    if isinstance(cons, list):
        return cons
    return list(cons.get("cons", default))


def _comparison_peer(ticker: str) -> str:
    peers = {
        "AAPL": "MSFT",
        "MSFT": "AAPL",
        "NVDA": "AMD",
        "AMD": "NVDA",
        "TSLA": "GM",
        "GM": "TSLA",
        "GOOGL": "META",
        "GOOG": "META",
        "META": "GOOGL",
        "ORCL": "CRM",
        "CRM": "ORCL",
        "VOO": "QQQ",
        "QQQ": "VOO",
        "VGT": "QQQ",
    }
    return peers.get(ticker.upper(), "SPY")


def _generic_term_ref(term: str) -> str | None:
    normalized = term.strip().lower()
    mapping = {
        "dividend": "dividend",
        "dividends": "dividend",
        "expense ratio": "expense-ratio",
        "etf": "exchange-traded-fund-etf",
        "index fund": "index-fund",
        "compound interest": "compound-interest",
        "diversification": "diversification",
        "overlap": "portfolio-overlap",
        "concentration": "concentration",
        "valuation": "pe-ratio",
        "valuation multiple": "pe-ratio",
        "earnings multiple": "pe-ratio",
        "p/e": "pe-ratio",
        "p/e ratio": "pe-ratio",
        "pe ratio": "pe-ratio",
        "dividend safety": "dividend-safety",
        "form 4": "form-4",
        "market movers": "market-movers",
    }
    return mapping.get(normalized)


def _format_score_inputs(inputs: dict[str, float], limit: int = 5) -> str:
    if not inputs:
        return "n/a"
    parts: list[str] = []
    for key, value in list(inputs.items())[:limit]:
        label = key.replace("_", " ")
        parts.append(f"{label}: {value:g}")
    remaining = len(inputs) - len(parts)
    if remaining > 0:
        parts.append(f"+{remaining} more")
    return "; ".join(parts)


def _overlap_matrix(result: c.OverlapResult) -> tuple[list[str], list[list[float]]]:
    labels = [f.ticker for f in result.funds]
    matrix: list[list[float]] = []
    for row in labels:
        values: list[float] = []
        for col in labels:
            if row == col:
                values.append(1.0)
            else:
                values.append(
                    result.pairwise_overlap_pct.get(f"{row}|{col}")
                    or result.pairwise_overlap_pct.get(f"{col}|{row}")
                    or 0.0
                )
        matrix.append(values)
    return labels, matrix


def build_overlap_panel(
    query: str,
    result: c.OverlapResult,
    *,
    narr: c.Narr | dict[str, Any] | None = None,
    pros: c.Pros | dict[str, Any] | list[str] | None = None,
    cons: c.Cons | dict[str, Any] | list[str] | None = None,
    cached: bool = False,
    latency_ms: int = 0,
) -> c.ResponsePanel:
    labels, matrix = _overlap_matrix(result)
    citation_id = _first_citation_id(result.citations)
    top_shared = sorted(result.shared_holdings, key=lambda h: h.combined_weight, reverse=True)[:10]
    top_lookthrough = sorted(result.look_through, key=lambda h: h.combined_weight, reverse=True)[:12]
    sectors = sorted(result.sector_breakdown, key=lambda s: s.weight, reverse=True)[:7]
    fund_names = ", ".join(labels)

    default_followups = [
        c.FollowUp(
            text="Which fund could I remove to reduce duplication?",
            kind="deeper",
            prefill_query=f"If I want less overlap, which one of {fund_names} should I keep?",
        ),
        c.FollowUp(
            text="Show fee drag for this portfolio",
            kind="deeper",
            prefill_query="I have $50,000 over 30 years with expense ratio 0.25% and return 6% - am I overpaying in fund fees?",
        ),
        c.FollowUp(
            text="What would add real diversification?",
            kind="wider",
            prefill_query=f"What bond or international ETF would diversify a {fund_names} portfolio?",
        ),
        c.FollowUp(
            text="Build a starter portfolio",
            kind="wider",
            prefill_query="What is a good starter portfolio for a beginner?",
        ),
        c.FollowUp(
            text="Explain fund overlap simply",
            kind="simpler",
            prefill_query="What does fund overlap mean in simple terms?",
        ),
        c.FollowUp(
            text="What is diversification?",
            kind="simpler",
            prefill_query="What is diversification? Explain simply.",
        ),
    ]

    entities = _entity_once(
        [c.Entity(text=t, kind="ticker", ref=t) for t in labels]
        + [c.Entity(text=h.ticker, kind="ticker", ref=h.ticker) for h in top_lookthrough if h.ticker]
        + [
            c.Entity(text="overlap", kind="term", ref="portfolio-overlap"),
            c.Entity(text="concentration", kind="term", ref="concentration"),
        ]
    )

    blocks: list[c.Block] = [
        c.KpiBlock(
            label="Combined overlap",
            value=_pct(result.combined_overlap_pct),
            takeaway=f"About {_pct(result.combined_overlap_pct)} of the combined portfolio is duplicated.",
            citation_id=citation_id,
        ),
        c.HeatmapBlock(
            title="Pairwise overlap by weight",
            x_labels=labels,
            y_labels=labels,
            matrix=matrix,
            unit="%",
            takeaway="The darkest cells show funds leaning on the same holdings.",
            citation_id=citation_id,
        ),
        c.TreemapBlock(
            title="Where the money really goes",
            items=[
                c.TreemapItem(
                    label=item.name,
                    value=_round_pct(item.combined_weight),
                    group=item.sector,
                    entity_kind="ticker" if item.ticker else None,
                    entity_ref=item.ticker or None,
                )
                for item in top_lookthrough
            ],
            takeaway="Look-through view turns fund labels into the companies underneath.",
            citation_id=citation_id,
        ),
        c.BarBlock(
            title="Top shared holdings",
            orientation="h",
            items=[
                c.BarItem(
                    label=item.name,
                    value=_round_pct(item.combined_weight),
                    unit="%",
                    entity_kind="ticker" if item.ticker else None,
                    entity_ref=item.ticker or None,
                )
                for item in top_shared
            ],
            takeaway="These names are the clearest duplicated bets.",
            citation_id=citation_id,
        ),
        c.DonutBlock(
            title="Sector breakdown",
            items=[c.DonutItem(label=s.sector, value=_round_pct(s.weight)) for s in sectors],
            takeaway="A sector-heavy donut is the quick check for hidden concentration.",
            citation_id=citation_id,
        ),
        c.KpiBlock(
            label="Top-10 concentration",
            value=_pct(result.top10_concentration_pct),
            takeaway=f"The ten largest look-through positions are {_pct(result.top10_concentration_pct)} of the portfolio.",
            citation_id=citation_id,
        ),
    ]

    return c.ResponsePanel(
        query=query,
        intent="overlap",
        headline=_narr_value(
            narr,
            "headline",
            f"{fund_names} are not independent bets: combined overlap is about {_pct(result.combined_overlap_pct)}.",
        ),
        eli5=_narr_value(
            narr,
            "eli5",
            "Funds can have different names but still own many of the same companies. "
            "This panel looks through the wrappers and shows where the dollars really land.",
        ),
        blocks=blocks,
        pros=_pros_value(
            pros,
            [
                "You still get broad, low-cost exposure to large US companies.",
                "Overlap can be acceptable when you intentionally want extra weight in a theme.",
            ],
        ),
        cons=_cons_value(
            cons,
            [
                "Diversification may be weaker than it looks because the same companies repeat.",
                "A sector shock can hit all overlapping funds at the same time.",
            ],
        ),
        assumptions=["Fund weights use the latest available holdings and may lag live composition."],
        citations=result.citations,
        entities=entities,
        followups=_narr_value(narr, "followups", default_followups),
        honesty_notes=["ETF holdings can be cached or quarterly, so exact weights may lag today."],
        meta=_meta(cached=cached, latency_ms=latency_ms),
    )


def build_forensic_panel(
    query: str,
    result: c.ForensicResult,
    *,
    ticker_card: c.TickerCard | dict[str, Any] | None = None,
    narr: c.Narr | dict[str, Any] | None = None,
    pros: c.Pros | dict[str, Any] | list[str] | None = None,
    cons: c.Cons | dict[str, Any] | list[str] | None = None,
    cached: bool = False,
    latency_ms: int = 0,
) -> c.ResponsePanel:
    safe = sum(1 for score in result.scores if score.band == "safe")
    citation_id = _first_citation_id(result.citations)
    status = {"safe": "green", "grey": "yellow", "distress": "red"}
    radar_value = {"safe": 4.5, "grey": 2.8, "distress": 1.0}
    card = c.TickerCard.model_validate(ticker_card) if ticker_card is not None else None

    blocks: list[c.Block] = []

    if card is not None:
        card_citation_id = _first_citation_id(card.citations)
        blocks.extend(
            [
                c.KpiBlock(
                    label=f"{card.ticker} price",
                    value=f"{card.currency} {card.price:,.2f}",
                    takeaway=f"Latest cached move: {_pct(card.change_pct, 1)}.",
                    citation_id=card_citation_id,
                ),
                _price_line_block(
                    card,
                    takeaway="Price context sits next to the red-flag screen.",
                    citation_id=card_citation_id,
                ),
            ]
        )
        if card.percentiles:
            p = card.percentiles[0]
            blocks.append(
                c.PercentileBarBlock(
                    title="Valuation context",
                    label=p.metric,
                    percentile=p.percentile,
                    context=p.context,
                    takeaway=f"{p.metric} is in the {p.percentile}th percentile in this demo context.",
                    citation_id=card_citation_id,
                )
            )

    blocks.extend([
        c.RadarBlock(
            title="Forensic score snapshot",
            axes=[
                c.RadarAxis(name=score.name, value=radar_value[score.band], max=5)
                for score in result.scores
            ],
            takeaway=f"{safe}/{len(result.scores)} screens are in the safer band.",
            citation_id=citation_id,
        ),
        c.TrafficLightBlock(
            title="Red-flag screen",
            items=[
                c.TrafficItem(
                    label=score.name,
                    status=status[score.band],  # type: ignore[arg-type]
                    note=score.interpretation,
                )
                for score in result.scores
            ],
            takeaway="Green means no obvious accounting or distress flag in that screen.",
            citation_id=citation_id,
        ),
        c.ScorecardBlock(
            title="Score details",
            items=[
                c.ScoreItem(
                    label=f"{score.name}: {score.value:g}",
                    passed=score.band == "safe",
                    detail=f"{score.formula} | source: {score.source_line or 'latest available statements'}",
                )
                for score in result.scores
            ],
            takeaway="Each number is a screening signal, not an investment verdict.",
            citation_id=citation_id,
        ),
        c.TableBlock(
            title="Formula inputs and source lines",
            columns=["Screen", "Formula", "Key inputs", "Source line"],
            rows=[
                [
                    f"{score.name}: {score.value:g}",
                    score.formula,
                    _format_score_inputs(score.inputs),
                    score.source_line or "latest available statements",
                ]
                for score in result.scores
            ],
            takeaway="This is the audit trail: formula, inputs used, and where the data came from.",
            citation_id=citation_id,
        ),
    ])

    entities = _entity_once(
        [
            c.Entity(text=result.ticker, kind="ticker", ref=result.ticker),
            c.Entity(text="Altman Z", kind="term", ref="altman-z-score"),
            c.Entity(text="Beneish M", kind="term", ref="beneish-m-score"),
            c.Entity(text="Piotroski F", kind="term", ref="piotroski-f-score"),
        ]
    )

    default_followups = [
        c.FollowUp(
            text="Compare with a competitor",
            kind="deeper",
            prefill_query=f"Compare {result.ticker} vs {_comparison_peer(result.ticker)} side by side.",
        ),
        c.FollowUp(
            text="Compare vs S&P 500",
            kind="deeper",
            prefill_query=f"Compare {result.ticker} vs SPY side by side.",
        ),
        c.FollowUp(
            text=f"Tell me about {result.ticker}",
            kind="wider",
            prefill_query=f"Tell me about {result.ticker}.",
        ),
        c.FollowUp(
            text="What if I invested here?",
            kind="wider",
            prefill_query=f"What if I invested $10,000 in {result.ticker} 5 years ago?",
        ),
        c.FollowUp(
            text="Explain Altman Z simply",
            kind="simpler",
            prefill_query="Explain Altman Z-Score in simple terms.",
        ),
        c.FollowUp(
            text="Explain Beneish M simply",
            kind="simpler",
            prefill_query="Explain Beneish M-Score in simple terms.",
        ),
    ]

    return c.ResponsePanel(
        query=query,
        intent="forensic",
        headline=_narr_value(
            narr,
            "headline",
            f"{result.ticker} has {safe}/{len(result.scores)} safer forensic screens.",
        ),
        eli5=_narr_value(
            narr,
            "eli5",
            "These scores are like smoke detectors for financial statements. "
            "They do not say whether to buy, but they help spot distress or accounting red flags.",
        ),
        blocks=blocks,
        pros=_pros_value(pros, ["The available forensic screens do not show an obvious broad red flag."]),
        cons=_cons_value(
            cons,
            ["Forensic scores are backward-looking screens and can miss fast-changing business risks."],
        ),
        assumptions=["Scores use the latest available annual financial statements."],
        citations=(card.citations if card is not None else []) + result.citations,
        entities=entities,
        followups=_narr_value(narr, "followups", default_followups),
        honesty_notes=[
            "This is an educational screen, not investment advice.",
            "Forensic cache mode may use cached demo inputs when live filings are unavailable.",
        ],
        meta=_meta(cached=cached, latency_ms=latency_ms),
    )


def build_fee_panel(
    query: str,
    result: c.FeeDragResult,
    rule72_block: c.TableBlock | None = None,
    *,
    narr: c.Narr | dict[str, Any] | None = None,
    pros: c.Pros | dict[str, Any] | list[str] | None = None,
    cons: c.Cons | dict[str, Any] | list[str] | None = None,
    cached: bool = False,
    latency_ms: int = 0,
) -> c.ResponsePanel:
    points = [
        c.Point(x=point.year, y=point.with_fee)
        for point in result.series
    ]
    no_fee_points = [
        c.Point(x=point.year, y=point.without_fee)
        for point in result.series
    ]
    blocks: list[c.Block] = [
        c.LineBlock(
            title="Fee drag over time",
            series=[
                c.LineSeries(name="With fee", points=points),
                c.LineSeries(name="Without fee", points=no_fee_points),
            ],
            x_type="num",
            takeaway=result.takeaway,
        ),
        c.KpiBlock(
            label="Estimated fee drag",
            value=f"${result.total_lost:,.0f}",
            takeaway=f"Fees reduce the ending value by about ${result.total_lost:,.0f}.",
        ),
    ]
    if rule72_block is not None:
        blocks.append(rule72_block)

    default_followups = [
        c.FollowUp(
            text="Try a larger balance",
            kind="deeper",
            prefill_query="Show the same fee drag for $50,000 over 30 years.",
        ),
        c.FollowUp(
            text="Try a higher fee (1%)",
            kind="deeper",
            prefill_query="Show fee drag for $50,000 over 30 years with expense ratio 1% and return 7%.",
        ),
        c.FollowUp(
            text="Compare ETF and mutual fund fees",
            kind="wider",
            prefill_query="What is the difference between ETF and mutual fund fees?",
        ),
        c.FollowUp(
            text="What ETFs have the lowest fees?",
            kind="wider",
            prefill_query="Which ETFs have the lowest expense ratios?",
        ),
        c.FollowUp(
            text="Explain expense ratio simply",
            kind="simpler",
            prefill_query="What is an expense ratio in simple terms?",
        ),
        c.FollowUp(
            text="Explain compound interest simply",
            kind="simpler",
            prefill_query="Explain compound interest in simple terms.",
        ),
    ]

    return c.ResponsePanel(
        query=query,
        intent="beginner_fees",
        headline=_narr_value(narr, "headline", result.takeaway),
        eli5=_narr_value(
            narr,
            "eli5",
            "A fund fee looks tiny because it is shown as a percentage. "
            "Over many years, that small annual drag compounds into real money.",
        ),
        blocks=blocks,
        pros=_pros_value(
            pros,
            ["Lower fees leave more of the compounding return in your account."],
        ),
        cons=_cons_value(
            cons,
            ["Low fees do not remove market risk, and the return assumption is simplified."],
        ),
        assumptions=result.assumptions,
        citations=[],
        entities=[
            c.Entity(text="expense ratio", kind="term", ref="expense-ratio"),
            c.Entity(text="compound interest", kind="term", ref="compound-interest"),
        ],
        followups=_narr_value(narr, "followups", default_followups),
        honesty_notes=["Calculator assumes a constant annual return and ignores taxes."],
        meta=_meta(cached=cached, latency_ms=latency_ms),
    )


def build_growth_panel(
    query: str,
    result: c.GrowthResult,
    *,
    cached: bool = False,
    latency_ms: int = 0,
) -> c.ResponsePanel:
    citation_id = _first_citation_id(result.citations)
    amount = result.inputs.amount
    gain = result.end_value - amount
    gain_pct = gain / amount if amount else 0.0
    points = [c.Point(x=point.date, y=point.value) for point in result.series]

    return c.ResponsePanel(
        query=query,
        intent="growth",
        headline=(
            f"${amount:,.0f} in {result.inputs.symbol} for {result.inputs.years} years "
            f"would be about ${result.end_value:,.0f} in this scenario."
        ),
        eli5=(
            "This rewinds the clock and scales the investment by the ticker's price path. "
            "It is useful for intuition, but past returns do not promise future returns."
        ),
        blocks=[
            c.LineBlock(
                title=f"Growth of ${amount:,.0f} in {result.inputs.symbol}",
                series=[c.LineSeries(name=result.inputs.symbol, points=points)],
                x_type="date",
                takeaway=f"The ending value is about ${result.end_value:,.0f}.",
                citation_id=citation_id,
            ),
            c.KpiBlock(
                label="Ending value",
                value=f"${result.end_value:,.0f}",
                takeaway=f"That is the simulated account value after {result.inputs.years} years.",
                citation_id=citation_id,
            ),
            c.KpiBlock(
                label="Total gain",
                value=f"{_pct(gain_pct, 1)}",
                takeaway=f"Approximate CAGR: {_pct(result.cagr, 1)} per year.",
                citation_id=citation_id,
            ),
        ],
        pros=[
            "Growth-of-money charts make compounding and volatility easier to see than a table.",
            "Using adjusted history can roughly account for splits and dividends when live data is available.",
        ],
        cons=[
            "Backtests are backward-looking and can overstate confidence.",
            "Taxes, fees, timing, and behavior are ignored in this simple prototype calculation.",
        ],
        assumptions=result.assumptions,
        citations=result.citations,
        entities=[
            c.Entity(text=result.inputs.symbol, kind="ticker", ref=result.inputs.symbol),
            c.Entity(text="compound interest", kind="term", ref="compound-interest"),
            c.Entity(text="dividend reinvestment", kind="term", ref="compound-interest"),
        ],
        followups=[
            c.FollowUp(
                text="Compare with an index ETF",
                kind="deeper",
                prefill_query=f"What if I invested ${amount:,.0f} in SPY {result.inputs.years} years ago?",
            ),
            c.FollowUp(
                text="Show forensic red flags",
                kind="deeper",
                prefill_query=f"Should I buy {result.inputs.symbol}? Show forensic red flags and the bear case.",
            ),
            c.FollowUp(
                text="Check the ticker card",
                kind="wider",
                prefill_query=f"Tell me about {result.inputs.symbol}.",
            ),
            c.FollowUp(
                text="Compare with a peer",
                kind="wider",
                prefill_query=f"Compare {result.inputs.symbol} vs {_comparison_peer(result.inputs.symbol)} side by side.",
            ),
            c.FollowUp(
                text="Explain compounding",
                kind="simpler",
                prefill_query="Explain compound interest simply.",
            ),
            c.FollowUp(
                text="Explain what past returns mean",
                kind="simpler",
                prefill_query="What does historical return mean for future investing?",
            ),
        ],
        honesty_notes=[
            "This is an educational historical scenario, not investment advice.",
            "Fallback mode uses estimated returns; live mode uses yfinance adjusted history.",
        ],
        meta=_meta(cached=cached, latency_ms=latency_ms),
    )


def _traffic_status(card: c.TickerCard, label: str) -> str:
    for item in card.traffic:
        if item.label.lower() == label.lower():
            return item.status
    return "yellow"


def _percentile_text(card: c.TickerCard) -> str:
    if not card.percentiles:
        return "n/a"
    p = card.percentiles[0]
    return f"{p.percentile}th ({p.metric})"


def _analyst_mean_text(card: c.TickerCard) -> str:
    if not card.analyst:
        return "n/a"
    return f"{card.analyst.currency} {card.analyst.mean:,.0f}"


def _average_snowflake(card: c.TickerCard) -> float:
    if not card.snowflake:
        return 0.0
    return round(sum(axis.value for axis in card.snowflake) / len(card.snowflake), 1)


def _raw_price_series(card: c.TickerCard, axis: str = "left") -> c.LineSeries:
    """Real (non-indexed) price series for single-ticker vs S&P charts."""
    points = card.price_series or [c.PricePoint(date="today", close=card.price)]
    return c.LineSeries(
        name=card.ticker,
        points=[c.Point(x=p.date, y=round(p.close, 4)) for p in points],
        axis=axis,
    )


def _price_line_block(
    card: c.TickerCard,
    *,
    takeaway: str,
    citation_id: str | None = None,
    title: str | None = None,
) -> c.LineBlock:
    """Single source of truth for the "recent price" line block.

    For single-ticker panels: real $ prices, ticker on left axis, S&P 500 (VOO)
    on right axis, both for the same date range from the seed. Compare panels
    continue to use normalised-to-100 series (see _normalized_price_series).
    """
    series: list[c.LineSeries] = [_raw_price_series(card, "left")]
    if card.ticker.upper() not in {"SPY", "VOO", "^GSPC"}:
        baseline = _sp500_baseline_series()
        if baseline is not None:
            series.append(baseline)
    return c.LineBlock(
        title=title or f"{card.ticker} recent price vs S&P 500",
        series=series,
        x_type="date",
        takeaway=takeaway,
        citation_id=citation_id,
    )


def _sp500_baseline_series() -> c.LineSeries | None:
    """S&P 500 real price series on the right axis — uses VOO seed (251 pts, same period)."""
    from app import tools

    try:
        voo = tools.ticker_card("VOO")
        return _raw_price_series(voo, "right").model_copy(update={"name": "S&P 500 (VOO)"})
    except Exception:  # noqa: BLE001 — baseline is best-effort context only
        return None


def _normalized_price_series(card: c.TickerCard) -> c.LineSeries:
    points = card.price_series or [c.PricePoint(date="today", close=card.price)]
    start = points[0].close or 1
    return c.LineSeries(
        name=card.ticker,
        points=[
            c.Point(x=point.date, y=round((point.close / start) * 100, 2))
            for point in points
        ],
    )


def build_compare_panel(
    query: str,
    result: c.CompareResult,
    *,
    cached: bool = False,
    latency_ms: int = 0,
) -> c.ResponsePanel:
    cards = result.cards
    tickers = [card.ticker for card in cards]
    label = " vs ".join(tickers)
    citations = [citation for card in cards for citation in card.citations]
    citation_id = _first_citation_id(citations)
    scores = [(card, _average_snowflake(card)) for card in cards]
    ranked = sorted(scores, key=lambda item: item[1], reverse=True)
    edge = "mixed"
    if len(ranked) >= 2 and ranked[0][1] - ranked[1][1] >= 0.3:
        edge = ranked[0][0].ticker

    # Data-driven pros/cons: talk about the tickers and their signals, not the UI.
    green = lambda signal: [card.ticker for card in cards if _traffic_status(card, signal) == "green"]  # noqa: E731
    red = lambda signal: [card.ticker for card in cards if _traffic_status(card, signal) == "red"]  # noqa: E731
    pros: list[str] = []
    if edge != "mixed":
        pros.append(f"{edge} leads the combined snapshot score ({ranked[0][1]:.1f}/5).")
    else:
        pros.append("Scores are close — no single ticker clearly leads the combined snapshot.")
    if green("Value"):
        pros.append(f"Cheaper on valuation signals: {', '.join(green('Value'))} (green Value light).")
    if green("Momentum"):
        pros.append(f"Stronger recent momentum: {', '.join(green('Momentum'))}.")
    if green("Quality"):
        pros.append(f"Better quality signals: {', '.join(green('Quality'))}.")
    cons: list[str] = []
    if red("Value"):
        cons.append(f"Looks expensive on valuation: {', '.join(red('Value'))} (red Value light).")
    if red("Momentum"):
        cons.append(f"Weak recent momentum: {', '.join(red('Momentum'))}.")
    cons.append("Snapshot signals are cached/fallback and skip sector peers, valuation history, and full forensic sources.")

    return c.ResponsePanel(
        query=query,
        intent="compare",
        headline=f"{label}: a side-by-side snapshot, not a buy/sell verdict.",
        eli5=(
            "This compares the same simple signals for each ticker: price path, valuation context, "
            "quality/value/momentum lights, and a compact score. It is a first screen, not a full thesis."
        ),
        blocks=[
            c.LineBlock(
                title="Normalized recent price path",
                series=[_normalized_price_series(card) for card in cards],
                x_type="date",
                takeaway="All lines start at 100 so the shape is easier to compare.",
                citation_id=citation_id,
            ),
            c.TableBlock(
                title="Side-by-side quick metrics",
                columns=["Metric", *tickers],
                rows=[
                    ["Price", *[f"{card.currency} {card.price:,.2f}" for card in cards]],
                    ["Latest move", *[_pct(card.change_pct, 1) for card in cards]],
                    ["Valuation context", *[_percentile_text(card) for card in cards]],
                    ["Analyst mean target", *[_analyst_mean_text(card) for card in cards]],
                    ["Quality", *[_traffic_status(card, "Quality") for card in cards]],
                    ["Value", *[_traffic_status(card, "Value") for card in cards]],
                    ["Momentum", *[_traffic_status(card, "Momentum") for card in cards]],
                ],
                takeaway="Same rows, same units: this is the fastest way to spot the trade-offs.",
                citation_id=citation_id,
            ),
            c.BarBlock(
                title="Compact snapshot score",
                orientation="h",
                items=[
                    c.BarItem(
                        label=card.ticker,
                        value=score,
                        unit="/5",
                        entity_kind="ticker",
                        entity_ref=card.ticker,
                    )
                    for card, score in scores
                ],
                takeaway=f"Quick edge: {edge}, but the score is only a prototype summary.",
                citation_id=citation_id,
            ),
            *[
                c.TrafficLightBlock(
                    title=f"{card.ticker} — Quality / Value / Momentum",
                    items=[
                        c.TrafficItem(label=signal, status=_traffic_status(card, signal))
                        for signal in ("Quality", "Value", "Momentum")
                    ],
                    takeaway="Three signals for one ticker: green is a plus, red is caution.",
                    citation_id=citation_id,
                )
                for card in cards
            ],
        ],
        pros=pros,
        cons=cons,
        assumptions=["Ticker cards may use cache/fallback data depending on TICKER_DATA_MODE."],
        citations=citations,
        entities=[
            *[c.Entity(text=card.ticker, kind="ticker", ref=card.ticker) for card in cards],
            c.Entity(text="P/E percentile", kind="term", ref="pe-ratio"),
        ],
        followups=[
            c.FollowUp(
                text=f"Run forensic screen on {cards[0].ticker}",
                kind="deeper",
                prefill_query=f"Should I buy {cards[0].ticker}? Show forensic red flags and the bear case.",
            ),
            c.FollowUp(
                text=f"Run forensic screen on {cards[1].ticker}",
                kind="deeper",
                prefill_query=f"Should I buy {cards[1].ticker}? Show forensic red flags and the bear case.",
            ),
            c.FollowUp(
                text=f"What if I invested in {cards[0].ticker}?",
                kind="wider",
                prefill_query=f"What if I invested $10,000 in {cards[0].ticker} 5 years ago?",
            ),
            c.FollowUp(
                text=f"What if I invested in {cards[1].ticker}?",
                kind="wider",
                prefill_query=f"What if I invested $10,000 in {cards[1].ticker} 5 years ago?",
            ),
            c.FollowUp(
                text="Explain valuation percentile",
                kind="simpler",
                prefill_query="Explain P/E percentile in simple terms.",
            ),
            c.FollowUp(
                text="Explain Quality/Value/Momentum",
                kind="simpler",
                prefill_query="Explain Quality, Value, and Momentum signals in simple terms.",
            ),
        ],
        honesty_notes=["This comparison is educational and not investment advice."],
        meta=_meta(cached=cached, latency_ms=latency_ms),
    )


def build_ticker_panel(
    query: str,
    result: c.TickerCard,
    *,
    cached: bool = False,
    latency_ms: int = 0,
) -> c.ResponsePanel:
    """Build a compact ticker overview panel from a TickerCard."""
    citation_id = _first_citation_id(result.citations)
    blocks: list[c.Block] = [
        c.KpiBlock(
            label=f"{result.ticker} price",
            value=f"{result.currency} {result.price:,.2f}",
            takeaway=f"Latest cached move: {_pct(result.change_pct, 1)}.",
            citation_id=citation_id,
        ),
        _price_line_block(
            result,
            takeaway="Short cached price path for quick orientation.",
            citation_id=citation_id,
        ),
    ]
    if result.snowflake:
        blocks.append(
            c.RadarBlock(
                title="Snowflake snapshot",
                axes=[
                    c.RadarAxis(name=axis.axis, value=axis.value, max=axis.max)
                    for axis in result.snowflake
                ],
                takeaway="A fast visual check across value, growth, health, past, and dividends.",
                citation_id=citation_id,
            )
        )
    if result.traffic:
        blocks.append(
            c.TrafficLightBlock(
                title="Quality / Value / Momentum",
                items=[
                    c.TrafficItem(label=item.label, status=item.status)
                    for item in result.traffic
                ],
                takeaway="Traffic lights make the first read scannable.",
                citation_id=citation_id,
            )
        )
    if result.percentiles:
        p = result.percentiles[0]
        blocks.append(
            c.PercentileBarBlock(
                title="Valuation context",
                label=p.metric,
                percentile=p.percentile,
                context=p.context,
                takeaway=f"{p.metric} sits around the {p.percentile}th percentile in this demo context.",
                citation_id=citation_id,
            )
        )
    if result.news:
        blocks.append(
            c.TableBlock(
                title="Recent headlines",
                columns=["Headline", "Source", "Date"],
                rows=[[item.title, item.source, item.published] for item in result.news[:5]],
                takeaway="Headlines are a quick starting point, not a full news feed.",
                citation_id=citation_id,
            )
        )

    return c.ResponsePanel(
        query=query,
        intent="ticker_card",
        headline=f"{result.ticker} price: {result.currency} {result.price:,.2f} in the current card data.",
        eli5="This panel gives the basic ticker card: price, simple quality signals, valuation context, and source links. For a red-flag screen, ask whether the ticker is worth buying and request forensic risks.",
        blocks=blocks[:6],
        pros=[f"{result.ticker} shows {result.currency} {result.price:,.2f} with the latest cached signals below."],
        cons=["Live data is unavailable right now, so this is a cached snapshot — check the sources before acting."],
        assumptions=["Ticker card values may be cached and simplified for the prototype."],
        citations=result.citations,
        entities=[c.Entity(text=result.ticker, kind="ticker", ref=result.ticker)],
        followups=[
            c.FollowUp(
                text="Show forensic red flags",
                kind="deeper",
                prefill_query=f"Should I buy {result.ticker}? Show forensic red flags and the bear case.",
            ),
            c.FollowUp(
                text="What if I invested here?",
                kind="deeper",
                prefill_query=f"What if I invested $10,000 in {result.ticker} 5 years ago?",
            ),
            c.FollowUp(
                text="Compare with another ticker",
                kind="wider",
                prefill_query=f"Compare {result.ticker} vs {_comparison_peer(result.ticker)} side by side.",
            ),
            c.FollowUp(
                text="Compare vs S&P 500",
                kind="wider",
                prefill_query=f"Compare {result.ticker} vs SPY side by side.",
            ),
            c.FollowUp(
                text="Explain valuation simply",
                kind="simpler",
                prefill_query="Explain P/E percentile in simple terms.",
            ),
            c.FollowUp(
                text="Explain Quality signal simply",
                kind="simpler",
                prefill_query="Explain what Quality signal means for stocks in simple terms.",
            ),
        ],
        honesty_notes=["Ticker card is educational and may use cached data."],
        meta=_meta(cached=cached, latency_ms=latency_ms),
    )


def build_generic_llm_panel(
    query: str,
    result: c.GenericAnswerResult,
    *,
    ticker_cards: list[c.TickerCard] | None = None,
    cached: bool = False,
    latency_ms: int = 0,
) -> c.ResponsePanel:
    """Build a real LLM generic answer, enriched with grounded visual blocks."""
    cards = ticker_cards or []
    blocks: list[c.Block] = [c.TextBlock(markdown=result.answer_md)]
    citations: list[c.Citation] = []
    entities: list[c.Entity] = []

    for card in cards[:6]:
        citations.extend(card.citations)
        entities.append(c.Entity(text=card.ticker, kind="ticker", ref=card.ticker))

    if len(cards) >= 2:
        citation_id = _first_citation_id(citations)
        blocks.append(
            c.TableBlock(
                title="Mentioned tickers snapshot",
                columns=["Ticker", "Price", "Move", "Quality", "Value", "Momentum", "Valuation"],
                rows=[
                    [
                        card.ticker,
                        f"{card.currency} {card.price:,.2f}",
                        _pct(card.change_pct, 1),
                        _traffic_status(card, "Quality"),
                        _traffic_status(card, "Value"),
                        _traffic_status(card, "Momentum"),
                        _percentile_text(card),
                    ]
                    for card in cards[:6]
                ],
                takeaway="The LLM answer mentioned these tickers; this table grounds them with ticker-card data.",
                citation_id=citation_id,
            )
        )
        blocks.append(
            c.LineBlock(
                title="Mentioned tickers normalized price path",
                series=[_normalized_price_series(card) for card in cards[:4]],
                x_type="date",
                takeaway="All lines start at 100 so recent moves are comparable.",
                citation_id=citation_id,
            )
        )
        blocks.append(
            c.BarBlock(
                title="Compact tool score",
                orientation="h",
                items=[
                    c.BarItem(
                        label=card.ticker,
                        value=_average_snowflake(card),
                        unit="/5",
                        entity_kind="ticker",
                        entity_ref=card.ticker,
                    )
                    for card in cards[:6]
                ],
                takeaway="A rough tool snapshot for triage, not a recommendation.",
                citation_id=citation_id,
            )
        )
    elif cards:
        card = cards[0]
        citation_id = _first_citation_id(card.citations)
        blocks.append(
            c.KpiBlock(
                label=f"{card.ticker} price",
                value=f"{card.currency} {card.price:,.2f}",
                takeaway=f"Latest cached move: {_pct(card.change_pct, 1)}.",
                citation_id=citation_id,
            )
        )
        if card.price_series:
            blocks.append(
                _price_line_block(
                    card,
                    takeaway="Grounded price context from the ticker-card tool.",
                    citation_id=citation_id,
                )
            )
        if card.traffic:
            blocks.append(
                c.TrafficLightBlock(
                    title=f"{card.ticker} quick signals",
                    items=[c.TrafficItem(label=item.label, status=item.status) for item in card.traffic],
                    takeaway="These are tool-provided screening signals, not LLM guesses.",
                    citation_id=citation_id,
                )
            )

    for term in result.terms[:5]:
        ref = _generic_term_ref(term)
        if ref is not None:
            entities.append(c.Entity(text=term, kind="term", ref=ref))
    # Keep every kind the LLM returned (up to 12 so "More" can rotate variants),
    # then top up any missing kind so all three slots (deeper/wider/simpler)
    # always render — the LLM often returns only "deeper".
    llm_fus = result.followups[:12]
    have = {f.kind for f in llm_fus}
    defaults = {
        "deeper": c.FollowUp(text="Show a supported visual workflow", kind="deeper", prefill_query="Compare NVDA vs AMD side by side."),
        "wider": c.FollowUp(text="Try the overlap demo", kind="wider", prefill_query="I hold VOO, QQQ and VGT - how much do they really overlap?"),
        "simpler": c.FollowUp(text="Explain a term simply", kind="simpler", prefill_query="What is an ETF? Explain simply."),
    }
    followups = llm_fus + [d for k, d in defaults.items() if k not in have]

    return c.ResponsePanel(
        query=query,
        intent="generic",
        headline=result.headline,
        eli5="This answer is generated by the configured LLM and enriched with deterministic visual tools when tickers are detected.",
        blocks=blocks[:7],
        pros=result.pros,
        cons=result.cons,
        assumptions=["Generic LLM answers are educational and should be checked against cited data."],
        citations=citations,
        entities=_entity_once(entities),
        followups=followups,
        honesty_notes=[
            "This is not investment advice.",
            "The text is LLM-generated; ticker visuals come from deterministic ticker-card tools.",
            *result.limitations,
        ],
        meta=_meta(cached=cached, latency_ms=latency_ms),
    )


_PORTFOLIO_MODELS = {
    "conservative": {"stocks": 40, "bonds": 50, "cash": 10, "horizon": "0-3 years", "risk": "Lower swings"},
    "balanced": {"stocks": 60, "bonds": 35, "cash": 5, "horizon": "3-10 years", "risk": "Moderate swings"},
    "aggressive": {"stocks": 85, "bonds": 12, "cash": 3, "horizon": "10+ years", "risk": "Large swings"},
}

_PORTFOLIO_INSTRUMENTS = [
    ["US broad market", "VOO / VTI / SPY", "Low-cost core equity exposure"],
    ["International", "VXUS / VEA", "Diversify outside the US"],
    ["Bonds", "BND / AGG", "Dampen volatility, add income"],
    ["Cash / short term", "money-market / T-bills", "Liquidity and dry powder"],
]


def build_portfolio_panel(
    query: str,
    *,
    profile: str | None = None,
    cached: bool = True,
    latency_ms: int = 0,
) -> c.ResponsePanel:
    """Educational 'what portfolio should I build' panel.

    There is no single 'best' portfolio, so instead of letting the LLM list
    random stocks this returns a grounded, deterministic panel: model
    allocations, an allocation donut for the chosen risk profile, example
    instruments (not recommendations), and a beginner risk checklist.
    """
    chosen = (profile or "balanced").lower()
    if chosen not in _PORTFOLIO_MODELS:
        chosen = "balanced"
    model = _PORTFOLIO_MODELS[chosen]

    allocation_rows = [
        [name.capitalize(), f"{m['stocks']}%", f"{m['bonds']}%", f"{m['cash']}%", m["horizon"], m["risk"]]
        for name, m in _PORTFOLIO_MODELS.items()
    ]

    return c.ResponsePanel(
        query=query,
        intent="generic",
        headline="There is no single best portfolio - start from your risk profile and diversify.",
        eli5=(
            "Instead of guessing one 'best' stock, most beginners do better with a mix: a broad-market core, "
            "some bonds for stability, and a little cash. How much of each depends on your time horizon and how "
            "much of a drop you can stomach. Below are three model mixes and example low-cost funds to research."
        ),
        blocks=[
            c.TableBlock(
                title="Model allocations by risk profile",
                columns=["Profile", "Stocks", "Bonds", "Cash", "Horizon", "Volatility"],
                rows=allocation_rows,
                takeaway=f"Showing the {chosen} mix highlighted below; pick the row that matches your horizon.",
            ),
            c.DonutBlock(
                title=f"Example allocation - {chosen} profile",
                items=[
                    c.DonutItem(label="Stocks", value=float(model["stocks"])),
                    c.DonutItem(label="Bonds", value=float(model["bonds"])),
                    c.DonutItem(label="Cash", value=float(model["cash"])),
                ],
                takeaway="A simple three-bucket split you can rebalance once or twice a year.",
            ),
            c.TableBlock(
                title="Example instruments to research (not recommendations)",
                columns=["Bucket", "Example tickers", "Why"],
                rows=_PORTFOLIO_INSTRUMENTS,
                takeaway="These are common, widely-held funds for learning - compare fees and holdings before buying.",
            ),
            c.TrafficLightBlock(
                title="Beginner readiness checklist",
                items=[
                    c.TrafficItem(label="Emergency fund in place", status="yellow", note="3-6 months of expenses first"),
                    c.TrafficItem(label="Time horizon set", status="green", note="longer horizon allows more stocks"),
                    c.TrafficItem(label="Drawdown tolerance known", status="yellow", note="know your max comfortable drop"),
                    c.TrafficItem(label="High-interest debt cleared", status="red", note="pay down before investing"),
                ],
                takeaway="Green is ready; yellow/red are worth sorting out before committing money.",
            ),
        ],
        pros=[
            "Diversified, low-cost cores historically beat most single-stock guesses for beginners.",
            "A clear allocation makes it easier to stay invested through volatility.",
        ],
        cons=[
            "Model mixes are educational starting points, not personalized advice.",
            "Example tickers are for research - they are not a recommendation to buy.",
        ],
        assumptions=[
            (
                f"Highlighting the {chosen} mix based on your saved investor profile."
                if profile
                else "Set your investor profile on Home to highlight the mix that fits your risk tolerance."
            ),
            "Allocations are illustrative model portfolios, not tuned to your full financial situation.",
        ],
        citations=[
            c.Citation(
                id="pf1",
                label="Investor.gov - asset allocation basics",
                source="investor.gov",
                url="https://www.investor.gov/introduction-investing/investing-basics/how-invest/asset-allocation",
                note="Educational reference for diversification and asset allocation.",
            )
        ],
        entities=_entity_once(
            [
                c.Entity(text="VOO", kind="ticker", ref="VOO"),
                c.Entity(text="VXUS", kind="ticker", ref="VXUS"),
                c.Entity(text="BND", kind="ticker", ref="BND"),
                c.Entity(text="diversification", kind="term", ref="diversification"),
            ]
        ),
        followups=[
            c.FollowUp(
                text="Tune this to my risk tolerance",
                kind="deeper",
                prefill_query="What is a good starter portfolio for a conservative investor?",
            ),
            c.FollowUp(
                text="What will fees cost this portfolio?",
                kind="deeper",
                prefill_query="I have $50,000 over 30 years with expense ratio 0.25% and return 6% - am I overpaying in fund fees?",
            ),
            c.FollowUp(
                text="Project growth of a starting amount",
                kind="deeper",
                prefill_query="What if I invested $10,000 in the S&P 500 5 years ago?",
            ),
            c.FollowUp(
                text="Check overlap if I hold several ETFs",
                kind="wider",
                prefill_query="I hold VOO, QQQ and VGT - how much do they really overlap?",
            ),
            c.FollowUp(
                text="Compare VOO vs QQQ",
                kind="wider",
                prefill_query="Compare VOO vs QQQ side by side.",
            ),
            c.FollowUp(
                text="Explain diversification simply",
                kind="simpler",
                prefill_query="What is diversification? Explain simply.",
            ),
            c.FollowUp(
                text="What is an index fund?",
                kind="simpler",
                prefill_query="What is an index fund? Explain in simple terms.",
            ),
        ],
        honesty_notes=[
            "This is educational information, not financial advice.",
            "Model allocations are illustrative and not tailored to your personal situation.",
        ],
        meta=_meta(cached=cached, latency_ms=latency_ms),
    )


def build_planned_workflow_panel(
    query: str,
    workflow: str,
    *,
    ticker: str | None = None,
    cached: bool = False,
    latency_ms: int = 0,
) -> c.ResponsePanel:
    """Purpose-built fallback for high-value workflows not fully wired yet."""
    ticker_text = ticker or "the ticker"
    specs: dict[str, dict[str, Any]] = {
        "insider_activity": {
            "headline": f"Insider activity for {ticker_text} is planned, but live Form 4 parsing is not wired yet.",
            "eli5": (
                "Insider trades can be interesting context, especially clustered buying or selling. "
                "They are not buy/sell signals by themselves, and filings can lag the actual trade."
            ),
            "term": c.Entity(text="Form 4", kind="term", ref="form-4"),
            "rows": [
                ["Recent Form 4 filings", "SEC EDGAR", "planned live fetch + cache"],
                ["Buyer/seller role", "issuer officer/director metadata", "planned parser"],
                ["Cluster signal", "group trades within a short window", "planned calculation"],
                ["Caveat", "filings lag and motives vary", "shown in honesty notes"],
            ],
            "traffic": [
                c.TrafficItem(label="Data source", status="green", note="SEC EDGAR is public"),
                c.TrafficItem(label="Parser", status="yellow", note="planned"),
                c.TrafficItem(label="Investment signal", status="red", note="not standalone advice"),
            ],
            "citations": [
                c.Citation(
                    id="p1",
                    label="SEC EDGAR company filings",
                    source="SEC EDGAR",
                    url="https://www.sec.gov/edgar/search/",
                    note="Planned source for Form 4 insider transaction filings.",
                )
            ],
            "followups": [
                c.FollowUp(
                    text="Run a forensic screen instead",
                    kind="deeper",
                    prefill_query=f"Should I buy {ticker_text}? Show forensic red flags and the bear case.",
                ),
                c.FollowUp(
                    text="Compare with a competitor",
                    kind="wider",
                    prefill_query=f"Compare {ticker_text} vs {_comparison_peer(ticker_text)} side by side.",
                ),
                c.FollowUp(
                    text="Explain why insider trades can mislead",
                    kind="simpler",
                    prefill_query="Explain insider buying and selling in simple terms.",
                ),
            ],
        },
        "dividend_safety": {
            "headline": f"Dividend safety for {ticker_text} is planned, but the payout workflow is not wired yet.",
            "eli5": (
                "A dividend is safer when cash flows comfortably cover the payout and the balance sheet can absorb stress. "
                "This prototype can show the checklist, but not yet a full live payout model."
            ),
            "term": c.Entity(text="dividend safety", kind="term", ref="dividend-safety"),
            "rows": [
                ["Dividend yield", "price + annual dividend", "ticker card/live data"],
                ["Payout ratio", "dividends / earnings", "planned calculation"],
                ["Free-cash-flow cover", "FCF / dividends paid", "planned calculation"],
                ["Debt pressure", "debt and interest burden", "planned forensic input"],
            ],
            "traffic": [
                c.TrafficItem(label="Definition", status="green", note="glossary available"),
                c.TrafficItem(label="Live payout model", status="yellow", note="planned"),
                c.TrafficItem(label="REIT/MLP nuance", status="yellow", note="needs FFO/AFFO handling"),
            ],
            "citations": [
                c.Citation(
                    id="p1",
                    label="Investor.gov dividend definition",
                    source="investor.gov",
                    url="https://www.investor.gov/introduction-investing/investing-basics/glossary/dividend",
                    note="Educational definition; full dividend-safety model is planned.",
                )
            ],
            "followups": [
                c.FollowUp(
                    text="Open the ticker card",
                    kind="deeper",
                    prefill_query=f"Tell me about {ticker_text}.",
                ),
                c.FollowUp(
                    text="Run forensic red flags",
                    kind="wider",
                    prefill_query=f"Should I buy {ticker_text}? Show forensic red flags and the bear case.",
                ),
                c.FollowUp(
                    text="Explain dividends simply",
                    kind="simpler",
                    prefill_query="What is a dividend? Explain simply.",
                ),
            ],
        },
        "market_today": {
            "headline": "A full market-today panel is planned; the landing page currently shows the lightweight market desk.",
            "eli5": (
                "A proper market-today workflow needs live index moves, sector moves, movers, and news reasons. "
                "The prototype has the landing shelf, but not the full explain-the-day route yet."
            ),
            "term": c.Entity(text="market movers", kind="term", ref="market-movers"),
            "rows": [
                ["Index moves", "S&P 500 / Nasdaq / Dow", "landing fixture now; live later"],
                ["Top movers", "yfinance quotes/news", "planned live refresh"],
                ["Why it moved", "headline summarization", "planned narrator"],
                ["Sector map", "sector ETF performance", "planned visual"],
            ],
            "traffic": [
                c.TrafficItem(label="Landing shelf", status="green", note="available"),
                c.TrafficItem(label="Live movers", status="yellow", note="planned"),
                c.TrafficItem(label="News completeness", status="yellow", note="free feeds can be sparse"),
            ],
            "citations": [
                c.Citation(
                    id="p1",
                    label="Yahoo Finance market data",
                    source="yfinance",
                    url="https://finance.yahoo.com/markets/",
                    note="Planned source for live-ish market quotes and headlines.",
                )
            ],
            "followups": [
                c.FollowUp(
                    text="Try a mover forensic screen",
                    kind="deeper",
                    prefill_query="Should I buy NVDA? Show forensic red flags and the bear case.",
                ),
                c.FollowUp(
                    text="Compare two popular tickers",
                    kind="wider",
                    prefill_query="Compare NVDA vs AMD side by side.",
                ),
                c.FollowUp(
                    text="Explain market movers",
                    kind="simpler",
                    prefill_query="What does it mean when a stock is a market mover?",
                ),
            ],
        },
        "etf_replacement": {
            "headline": "ETF replacement advice is planned; today the overlap panel shows the duplication evidence.",
            "eli5": (
                "Choosing which fund to remove depends on goals, taxes, fees, account type, and what exposure you want to keep. "
                "The prototype can reveal overlap, but it should not pretend to prescribe a portfolio trade."
            ),
            "term": c.Entity(text="overlap", kind="term", ref="portfolio-overlap"),
            "rows": [
                ["Overlap evidence", "cached ETF holdings", "available now"],
                ["Expense comparison", "fund metadata", "available in ETF cards"],
                ["Tax/account context", "user-specific input", "not collected yet"],
                ["Replacement candidates", "bond/international ETF universe", "planned"],
            ],
            "traffic": [
                c.TrafficItem(label="Overlap math", status="green", note="available"),
                c.TrafficItem(label="ETF cards", status="green", note="available"),
                c.TrafficItem(label="Personal recommendation", status="red", note="intentionally not faked"),
            ],
            "citations": [
                c.Citation(
                    id="p1",
                    label="Cached ETF holdings",
                    source="issuer",
                    url="https://investor.vanguard.com/investment-products/etfs",
                    note="Overlap and ETF cards use bundled holdings cache for the demo funds.",
                )
            ],
            "followups": [
                c.FollowUp(
                    text="Open the overlap panel",
                    kind="deeper",
                    prefill_query="I hold VOO, QQQ and VGT - how much do they really overlap?",
                ),
                c.FollowUp(
                    text="Compare VOO and QQQ",
                    kind="wider",
                    prefill_query="Compare VOO vs QQQ side by side.",
                ),
                c.FollowUp(
                    text="Explain overlap simply",
                    kind="simpler",
                    prefill_query="What does fund overlap mean in simple terms?",
                ),
            ],
        },
    }
    spec = specs.get(workflow, specs["market_today"])
    entities = [spec["term"]]
    if ticker:
        entities.insert(0, c.Entity(text=ticker, kind="ticker", ref=ticker))

    return c.ResponsePanel(
        query=query,
        intent="generic",
        headline=spec["headline"],
        eli5=spec["eli5"],
        blocks=[
            c.KpiBlock(
                label="Workflow status",
                value="Planned",
                takeaway="This is a product placeholder with the intended data path, not a fabricated result.",
            ),
            c.TrafficLightBlock(
                title="Readiness",
                items=spec["traffic"],
                takeaway="Green is already supported; yellow/red marks what still needs implementation.",
            ),
            c.TableBlock(
                title="What this workflow will check",
                columns=["Check", "Data", "Status"],
                rows=spec["rows"],
                takeaway="The panel shows the promised workflow shape without inventing live data.",
            ),
        ],
        pros=["The prototype is explicit about what is planned instead of returning an unrelated canned answer."],
        cons=["This workflow still needs live data plumbing and tests before it can be treated as implemented."],
        assumptions=["Planned panels are placeholders for demo continuity and product direction."],
        citations=spec["citations"],
        entities=_entity_once(entities),
        followups=spec["followups"],
        honesty_notes=[
            "This is not investment advice.",
            "The workflow is intentionally marked planned until its data source and calculations are implemented.",
        ],
        meta=_meta(cached=cached, latency_ms=latency_ms),
    )


def build_generic_panel(query: str, *, cached: bool = False, latency_ms: int = 0) -> c.ResponsePanel:
    """Fallback that does not pretend to answer with an unrelated scenario."""
    return c.ResponsePanel(
        query=query,
        intent="generic",
        headline="I don't have that workflow wired yet, so I won't fake a different answer.",
        eli5="This prototype currently has specific tools for ETF overlap, ticker red-flag screens, fee calculators, ticker cards, and glossary explanations. Ask one of those and it will return a visual panel instead of a generic chat paragraph.",
        blocks=[
            c.TextBlock(
                markdown=(
                    "**Implemented prototype workflows:**\n\n"
                    "- ETF overlap: `I hold VOO, QQQ and VGT - how much do they overlap?`\n"
                    "- Forensic screen: `Should I buy NVDA? Show red flags.`\n"
                    "- Fee calculator: `I have $10,000 - am I overpaying in fund fees?`\n"
                    "- Growth scenario: `What if I invested $10,000 in TSLA 5 years ago?`\n"
                    "- Compare: `Compare NVDA vs AMD side by side.`\n"
                    "- Ticker card: `Tell me about TSLA.`\n"
                    "- Glossary: `What is concentration?`"
                )
            )
        ],
        pros=["The fallback is honest about prototype coverage instead of showing an unrelated canned panel."],
        cons=["A full general-purpose ADK/Gemini route is still not wired in this prototype."],
        assumptions=["Generic questions need the M2 ADK workflow to become true open-ended answers."],
        citations=[],
        entities=[],
        followups=[
            c.FollowUp(
                text="Try the overlap demo",
                kind="deeper",
                prefill_query="I hold VOO, QQQ and VGT - how much do they really overlap?",
            ),
            c.FollowUp(
                text="Try a growth scenario",
                kind="wider",
                prefill_query="What if I invested $10,000 in TSLA 5 years ago?",
            ),
            c.FollowUp(
                text="Explain a term",
                kind="simpler",
                prefill_query="What is concentration? Explain simply.",
            ),
        ],
        honesty_notes=["Generic open-ended answering is planned for ADK orchestration, not this deterministic router."],
        meta=_meta(cached=cached, latency_ms=latency_ms).model_copy(update={"llm_degraded": True}),
    )


def build_term_panel(
    query: str,
    result: c.GlossaryTerm,
    *,
    narr: c.Narr | dict[str, Any] | None = None,
    cached: bool = False,
    latency_ms: int = 0,
) -> c.ResponsePanel:
    default_followups = [
        c.FollowUp(
            text="Show a numeric example",
            kind="deeper",
            prefill_query=f"Show a numeric example of {result.term}.",
        ),
        c.FollowUp(
            text="How does this affect stock picks?",
            kind="deeper",
            prefill_query=f"How do investors use {result.term} to evaluate stocks?",
        ),
        c.FollowUp(
            text="Connect this to fund fees",
            kind="wider",
            prefill_query=f"How does {result.term} affect long-term investing costs?",
        ),
        c.FollowUp(
            text="Related concepts",
            kind="wider",
            prefill_query=f"What finance terms are related to {result.term}?",
        ),
        c.FollowUp(
            text="Explain it even simpler",
            kind="simpler",
            prefill_query=f"Explain {result.term} like I am brand new to investing.",
        ),
        c.FollowUp(
            text="Give me an analogy",
            kind="simpler",
            prefill_query=f"Give me a simple everyday analogy for {result.term}.",
        ),
    ]

    return c.ResponsePanel(
        query=query,
        intent="term",
        headline=_narr_value(narr, "headline", f"{result.term}: {result.eli5}"),
        eli5=_narr_value(narr, "eli5", result.eli5),
        blocks=[
            c.TextBlock(markdown=f"**Example:** {result.example}\n\n{result.detail_md}")
        ],
        pros=[],
        cons=[],
        assumptions=[],
        citations=[result.citation],
        entities=[c.Entity(text=result.term, kind="term", ref=result.term.lower().replace(" ", "-"))],
        followups=_narr_value(narr, "followups", default_followups),
        honesty_notes=["Term definitions are educational and cite regulator-oriented sources."],
        meta=_meta(cached=cached, latency_ms=latency_ms),
    )


def build(state: dict[str, Any]) -> c.ResponsePanel:
    """Build a ResponsePanel from an ADK/FastAPI-style state dict.

    Expected keys: query, intent, result. Optional keys: narr, pros, cons,
    cached, latency_ms. `result` may be a pydantic object or a plain dict.
    """
    intent = state["intent"]
    query = state.get("query", "")
    result = state["result"]
    kwargs = {
        "narr": state.get("narr"),
        "pros": state.get("pros"),
        "cons": state.get("cons"),
        "cached": bool(state.get("cached", False)),
        "latency_ms": int(state.get("latency_ms", 0)),
    }

    generic_raw = state.get("generic")
    generic_obj = c.GenericAnswerResult.model_validate(generic_raw) if isinstance(generic_raw, dict) else generic_raw

    if intent == "overlap":
        return _with_generic(build_overlap_panel(query, c.OverlapResult.model_validate(result), **kwargs), generic_obj)
    if intent == "forensic":
        return _with_generic(
            build_forensic_panel(
                query,
                c.ForensicResult.model_validate(result),
                ticker_card=state.get("ticker_card"),
                **kwargs,
            ),
            generic_obj,
        )
    if intent == "beginner_fees":
        return _with_generic(
            build_fee_panel(
                query,
                c.FeeDragResult.model_validate(result),
                state.get("rule72_block"),
                **kwargs,
            ),
            generic_obj,
        )
    if intent == "growth":
        return _with_generic(
            build_growth_panel(
                query,
                c.GrowthResult.model_validate(result),
                cached=bool(state.get("cached", False)),
                latency_ms=int(state.get("latency_ms", 0)),
            ),
            generic_obj,
        )
    if intent == "compare":
        return _with_generic(
            build_compare_panel(
                query,
                c.CompareResult.model_validate(result),
                cached=bool(state.get("cached", False)),
                latency_ms=int(state.get("latency_ms", 0)),
            ),
            generic_obj,
        )
    if intent == "ticker_card":
        return _with_generic(
            build_ticker_panel(
                query,
                c.TickerCard.model_validate(result),
                cached=bool(state.get("cached", False)),
                latency_ms=int(state.get("latency_ms", 0)),
            ),
            generic_obj,
        )
    if intent == "generic":
        if isinstance(result, (c.GenericAnswerResult, dict)) and result:
            return build_generic_llm_panel(
                query,
                c.GenericAnswerResult.model_validate(result),
                ticker_cards=[
                    c.TickerCard.model_validate(card)
                    for card in state.get("ticker_cards", [])
                ],
                cached=bool(state.get("cached", False)),
                latency_ms=int(state.get("latency_ms", 0)),
            )
        return build_generic_panel(
            query,
            cached=bool(state.get("cached", False)),
            latency_ms=int(state.get("latency_ms", 0)),
        )
    if intent == "term":
        return build_term_panel(
            query,
            c.GlossaryTerm.model_validate(result),
            narr=state.get("narr"),
            cached=bool(state.get("cached", False)),
            latency_ms=int(state.get("latency_ms", 0)),
        )
    raise ValueError(f"unsupported intent for assembler: {intent!r}")


def build_market_map() -> c.TreemapBlock:
    """Dashboard heatmap: mega-caps sized by S&P weight, coloured by latest move.

    Deterministic from cache — curated mega-cap weights for size, cached ticker
    change_pct for colour. Grouped by sector, each tile clickable to its card.
    """
    import json
    import pathlib

    from app import tools

    map_path = pathlib.Path(__file__).parent / "data" / "market_map.json"
    holdings = sorted(
        json.loads(map_path.read_text(encoding="utf-8"))["holdings"],
        key=lambda h: h.get("weight", 0.0),
        reverse=True,
    )
    items: list[c.TreemapItem] = []
    for holding in holdings:
        ticker = (holding.get("ticker") or "").upper()
        change = 0.0
        if ticker:
            try:
                change = tools.ticker_card(ticker).change_pct
            except Exception:  # noqa: BLE001 — colour is best-effort; default flat
                change = 0.0
        items.append(
            c.TreemapItem(
                label=holding.get("name") or ticker,
                value=_round_pct(holding.get("weight", 0.0)),
                group=holding.get("sector"),
                entity_kind="ticker" if ticker else None,
                entity_ref=ticker or None,
                color_value=round(change, 4),
            )
        )
    return c.TreemapBlock(
        title="Market map",
        items=items,
        takeaway="Sized by S&P 500 weight · color = latest cached move (cached holdings + cached moves).",
    )
