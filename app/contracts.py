"""Data contracts — the skeleton of the whole project.

Every tool returns a typed *Result; the assembler maps results + LLM texts into a
universal `ResponsePanel`; the frontend renders a panel purely by block `type`.
Presentation is therefore swappable without touching the core — see plan §2.

Pydantic v2. No `from __future__ import annotations` here on purpose: it keeps the
discriminated `Block` union and the `pass` alias resolving predictably.
"""

from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

# --------------------------------------------------------------------------- #
# Shared primitives
# --------------------------------------------------------------------------- #


class Citation(BaseModel):
    """Source for a number/claim. Regulator > Wikipedia (see plan §2.3)."""

    id: str
    label: str
    source: str  # "SEC EDGAR" | "yfinance" | "investor.gov" | "FINRA" | "issuer"
    url: str
    as_of_date: Optional[str] = None
    note: Optional[str] = None


class Entity(BaseModel):
    """Clickable ticker/term found in an answer -> lazy card via /api/entity."""

    text: str
    kind: Literal["ticker", "term"]
    ref: str  # ticker symbol or term slug


class FollowUp(BaseModel):
    """One of the 3 'learn more ->' questions. Rules in plan §2.5."""

    text: str
    kind: Literal["deeper", "wider", "simpler"]
    prefill_query: str


# --------------------------------------------------------------------------- #
# Visual blocks (discriminated union on `type`). Each carries a one-line
# `takeaway`. Anti-overload rules: <= ~6 blocks/answer (plan §2.2).
# --------------------------------------------------------------------------- #


class KpiBlock(BaseModel):
    type: Literal["kpi"] = "kpi"
    label: str
    value: str
    takeaway: str
    citation_id: Optional[str] = None


class HeatmapBlock(BaseModel):
    type: Literal["chart.heatmap"] = "chart.heatmap"
    title: str
    x_labels: list[str]
    y_labels: list[str]
    matrix: list[list[float]]
    unit: str = "%"
    takeaway: str
    citation_id: Optional[str] = None


class TreemapItem(BaseModel):
    label: str
    value: float
    group: Optional[str] = None
    entity_kind: Optional[Literal["ticker", "term"]] = None
    entity_ref: Optional[str] = None
    color_value: Optional[float] = None  # e.g. latest % move, for red/green tiles


class TreemapBlock(BaseModel):
    type: Literal["chart.treemap"] = "chart.treemap"
    title: str
    items: list[TreemapItem]
    takeaway: str
    citation_id: Optional[str] = None


class BarItem(BaseModel):
    label: str
    value: float
    unit: Optional[str] = None
    entity_kind: Optional[Literal["ticker", "term"]] = None
    entity_ref: Optional[str] = None


class BarBlock(BaseModel):
    type: Literal["chart.bar"] = "chart.bar"
    title: str
    orientation: Literal["h", "v"] = "v"
    items: list[BarItem]
    takeaway: str
    citation_id: Optional[str] = None


class Point(BaseModel):
    x: Union[str, float]
    y: float


class LineSeries(BaseModel):
    name: str
    points: list[Point]
    axis: Literal["left", "right"] = "left"


class LineBlock(BaseModel):
    type: Literal["chart.line"] = "chart.line"
    title: str
    series: list[LineSeries]
    x_type: Literal["date", "num"] = "date"
    takeaway: str
    citation_id: Optional[str] = None


class DonutItem(BaseModel):
    label: str
    value: float


class DonutBlock(BaseModel):
    type: Literal["chart.donut"] = "chart.donut"
    title: str
    items: list[DonutItem]
    takeaway: str
    citation_id: Optional[str] = None


class RadarAxis(BaseModel):
    name: str
    value: float
    max: float = 5


class RadarBlock(BaseModel):
    """Simply-Wall-St-style snowflake."""

    type: Literal["radar"] = "radar"
    title: str
    axes: list[RadarAxis]
    takeaway: str
    citation_id: Optional[str] = None


class TrafficItem(BaseModel):
    label: str
    status: Literal["green", "yellow", "red"]
    note: Optional[str] = None


class TrafficLightBlock(BaseModel):
    type: Literal["traffic_light"] = "traffic_light"
    title: str
    items: list[TrafficItem]
    takeaway: str
    citation_id: Optional[str] = None


class PercentileBarBlock(BaseModel):
    type: Literal["percentile_bar"] = "percentile_bar"
    title: str
    label: str
    percentile: int
    context: str
    takeaway: str
    citation_id: Optional[str] = None


class ScoreItem(BaseModel):
    # `pass` is a Python keyword -> stored as `passed`, serialized as "pass".
    model_config = ConfigDict(populate_by_name=True)

    label: str
    passed: bool = Field(alias="pass")
    detail: str = ""


class ScorecardBlock(BaseModel):
    type: Literal["scorecard"] = "scorecard"
    title: str
    items: list[ScoreItem]
    takeaway: str
    citation_id: Optional[str] = None


class TableBlock(BaseModel):
    type: Literal["table"] = "table"
    title: str
    columns: list[str]
    rows: list[list[str]]
    takeaway: str
    citation_id: Optional[str] = None


class TextBlock(BaseModel):
    type: Literal["text"] = "text"
    markdown: str


Block = Annotated[
    Union[
        KpiBlock,
        HeatmapBlock,
        TreemapBlock,
        BarBlock,
        LineBlock,
        DonutBlock,
        RadarBlock,
        TrafficLightBlock,
        PercentileBarBlock,
        ScorecardBlock,
        TableBlock,
        TextBlock,
    ],
    Field(discriminator="type"),
]

Intent = Literal[
    "overlap",
    "forensic",
    "beginner_fees",
    "growth",
    "compare",
    "ticker_card",
    "term",
    "market_today",
    "generic",
]


# --------------------------------------------------------------------------- #
# Universal response envelope
# --------------------------------------------------------------------------- #


class Meta(BaseModel):
    generated_by: str = "configured-llm"
    cached: bool = False
    latency_ms: int = 0
    # Forum-style deterministic link `#/t/<turn_seq>/<turn_slug>` (store.py).
    # None until a turn has been persisted (e.g. bare deterministic panels in tests).
    turn_seq: Optional[int] = None
    turn_slug: Optional[str] = None
    parent_seq: Optional[int] = None
    # M9: name of the FunctionTool the agent *itself* chose to invoke this turn
    # (None when the deterministic dispatch produced the numbers instead).
    tool_invoked: Optional[str] = None
    # True when a route that *expects* an LLM narrative had to fall back to the
    # bare deterministic panel because the LLM was unavailable. Persisted with the
    # turn so the durable cache can recompute it once the LLM is configured again
    # (instead of serving the degraded answer forever).
    llm_degraded: bool = False


class ResponsePanel(BaseModel):
    query: str
    intent: Intent
    headline: str  # one plain-language sentence
    eli5: str  # 2-3 simple sentences
    blocks: list[Block] = Field(default_factory=list)
    pros: list[str] = Field(default_factory=list)  # Analyst
    cons: list[str] = Field(default_factory=list)  # Skeptic
    assumptions: list[str] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    entities: list[Entity] = Field(default_factory=list)
    followups: list[FollowUp] = Field(default_factory=list)
    honesty_notes: list[str] = Field(default_factory=list)
    meta: Meta = Field(default_factory=Meta)


# --------------------------------------------------------------------------- #
# LLM-agent output schemas (structured output for LlmAgent nodes — plan §4)
# --------------------------------------------------------------------------- #


class Pros(BaseModel):
    pros: list[str]


class Cons(BaseModel):
    cons: list[str]


class Narr(BaseModel):
    headline: str
    eli5: str
    followups: list[FollowUp]


class GenericAnswerResult(BaseModel):
    headline: str
    answer_md: str
    pros: list[str] = Field(default_factory=list)
    cons: list[str] = Field(default_factory=list)
    tickers: list[str] = Field(default_factory=list)
    terms: list[str] = Field(default_factory=list)
    followups: list[FollowUp] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class JudgeVerdict(BaseModel):
    """LLM-as-judge score for one answer (Agent-Quality eval, `--judge` mode).

    Scores are 1-5. ``groundedness`` asks whether every figure in the answer is
    backed by a tool number; ``safety`` penalizes personalized buy/sell advice.
    """

    helpfulness: int
    groundedness: int
    safety: int
    rationale: str = ""


# --------------------------------------------------------------------------- #
# Tool result contracts (what functions in app.tools return — plan §2.6)
# --------------------------------------------------------------------------- #


# ----- overlap -----
class FundInfo(BaseModel):
    ticker: str
    name: str
    expense_ratio: float
    as_of: str


class SharedHolding(BaseModel):
    name: str
    ticker: str
    weight_by_fund: dict[str, float]
    combined_weight: float


class LookThroughItem(BaseModel):
    name: str
    ticker: str
    combined_weight: float
    sector: Optional[str] = None


class SectorWeight(BaseModel):
    sector: str
    weight: float


class OverlapResult(BaseModel):
    funds: list[FundInfo]
    pairwise_overlap_pct: dict[str, float]  # key "VOO|QQQ" -> shared weight fraction
    combined_overlap_pct: float
    shared_holdings: list[SharedHolding]
    look_through: list[LookThroughItem]
    sector_breakdown: list[SectorWeight]
    top10_concentration_pct: float
    citations: list[Citation] = Field(default_factory=list)


# ----- forensic -----
class ForensicScore(BaseModel):
    name: str  # "Altman Z" | "Beneish M" | "Piotroski F"
    value: float
    formula: str
    inputs: dict[str, float] = Field(default_factory=dict)
    interpretation: str
    band: Literal["safe", "grey", "distress"]
    source_line: Optional[str] = None
    citation_id: Optional[str] = None


class ForensicResult(BaseModel):
    ticker: str
    name: str
    as_of: str
    scores: list[ForensicScore]
    citations: list[Citation] = Field(default_factory=list)


# ----- ticker card -----
class PricePoint(BaseModel):
    date: str
    close: float


class FundamentalRow(BaseModel):
    year: int
    revenue: Optional[float] = None
    net_income: Optional[float] = None
    margin: Optional[float] = None
    debt: Optional[float] = None
    dividend: Optional[float] = None


class SnowflakeAxis(BaseModel):
    axis: str  # value | growth | health | past | dividend
    value: float
    max: float = 5


class TrafficRating(BaseModel):
    label: str  # Quality | Value | Momentum
    status: Literal["green", "yellow", "red"]


class Percentile(BaseModel):
    metric: str
    percentile: int
    context: str


class NewsItem(BaseModel):
    title: str
    url: str
    published: str
    source: str


class AnalystBand(BaseModel):
    low: float
    mean: float
    high: float
    currency: str = "USD"


class HoldingPreview(BaseModel):
    ticker: str
    name: str
    weight: float
    sector: Optional[str] = None


class TickerCard(BaseModel):
    asset_type: Literal["stock", "etf"] = "stock"
    ticker: str
    name: str
    price: float
    currency: str = "USD"
    change_pct: float
    expense_ratio: Optional[float] = None
    holdings_as_of: Optional[str] = None
    top_holdings: list[HoldingPreview] = Field(default_factory=list)
    sector_exposure: list[SectorWeight] = Field(default_factory=list)
    price_series: list[PricePoint] = Field(default_factory=list)
    fundamentals: list[FundamentalRow] = Field(default_factory=list)
    snowflake: list[SnowflakeAxis] = Field(default_factory=list)
    traffic: list[TrafficRating] = Field(default_factory=list)
    percentiles: list[Percentile] = Field(default_factory=list)
    news: list[NewsItem] = Field(default_factory=list)
    analyst: Optional[AnalystBand] = None
    citations: list[Citation] = Field(default_factory=list)


class CompareResult(BaseModel):
    cards: list[TickerCard] = Field(min_length=2)

    @model_validator(mode="before")
    @classmethod
    def _accept_legacy_pair(cls, data):
        if isinstance(data, dict) and "cards" not in data and "left" in data and "right" in data:
            return {**data, "cards": [data["left"], data["right"]]}
        return data

    @property
    def left(self) -> TickerCard:
        return self.cards[0]

    @property
    def right(self) -> TickerCard:
        return self.cards[1]


# ----- calculators -----
class FeeInputs(BaseModel):
    amount: float
    years: int
    expense_ratio: float
    gross_return: float = 0.07


class FeePoint(BaseModel):
    year: int
    with_fee: float
    without_fee: float


class FeeDragResult(BaseModel):
    inputs: FeeInputs
    series: list[FeePoint]
    total_lost: float
    end_with_fee: float
    end_without_fee: float
    assumptions: list[str] = Field(default_factory=list)
    takeaway: str


class GrowthInputs(BaseModel):
    amount: float
    symbol: str
    years: int


class GrowthPoint(BaseModel):
    date: str
    value: float


class GrowthResult(BaseModel):
    inputs: GrowthInputs
    series: list[GrowthPoint]
    end_value: float
    cagr: float
    assumptions: list[str] = Field(default_factory=list)
    note_dividends: bool = False
    citations: list[Citation] = Field(default_factory=list)


# ----- glossary -----
class GlossaryTerm(BaseModel):
    term: str
    eli5: str
    example: str
    detail_md: str
    citation: Citation


# ----- market / landing -----
class IndexQuote(BaseModel):
    name: str
    value: float
    change_pct: float


class Mover(BaseModel):
    ticker: str
    name: str
    change_pct: float
    reason: str
    spark: list[float] = Field(default_factory=list)


class Movers(BaseModel):
    as_of: str
    indices: list[IndexQuote]
    movers: list[Mover]
    fear_greed: Optional[int] = None
    citations: list[Citation] = Field(default_factory=list)


class CuriosityItem(BaseModel):
    kind: Literal["insider", "congress", "history"]
    text: str
    note: str


class GeneratedQuestion(BaseModel):
    text: str
    feature: str  # which agent feature this question showcases
    prefill_query: str


class Landing(BaseModel):
    market: Movers
    chart_of_day: Block
    term_of_day: GlossaryTerm
    curiosity: list[CuriosityItem] = Field(default_factory=list)
    generated_questions: list[GeneratedQuestion] = Field(default_factory=list)
