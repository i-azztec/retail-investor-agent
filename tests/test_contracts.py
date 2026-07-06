"""M0 acceptance: contracts validate, fixtures match, discriminated union round-trips."""

import json
import pathlib

import pytest

from app import contracts as c

FIX = pathlib.Path(__file__).parent.parent / "app" / "fixtures"

# fixture file -> model it must validate against
CASES = {
    "response_overlap.json": c.ResponsePanel,
    "tool_overlap.json": c.OverlapResult,
    "tool_forensic.json": c.ForensicResult,
    "tool_ticker_card.json": c.TickerCard,
    "tool_fee_drag.json": c.FeeDragResult,
    "tool_glossary.json": c.GlossaryTerm,
    "tool_landing.json": c.Landing,
}


@pytest.mark.parametrize("fname,model", list(CASES.items()))
def test_fixture_validates_and_roundtrips(fname, model):
    data = json.loads((FIX / fname).read_text(encoding="utf-8"))
    obj = model.model_validate(data)
    # serialize (with aliases, e.g. ScoreItem "pass") and re-validate
    reparsed = json.loads(obj.model_dump_json(by_alias=True))
    model.model_validate(reparsed)


def test_every_fixture_file_is_covered():
    """No fixture should sit untested."""
    on_disk = {p.name for p in FIX.glob("*.json")}
    assert on_disk == set(CASES), f"fixtures without a test case: {on_disk - set(CASES)}"


def _one_of_every_block() -> list:
    return [
        c.KpiBlock(label="Overlap", value="48%", takeaway="t"),
        c.HeatmapBlock(title="h", x_labels=["A"], y_labels=["A"], matrix=[[1.0]], takeaway="t"),
        c.TreemapBlock(title="h", items=[c.TreemapItem(label="A", value=1.0)], takeaway="t"),
        c.BarBlock(title="h", items=[c.BarItem(label="A", value=1.0)], takeaway="t"),
        c.LineBlock(
            title="h",
            series=[c.LineSeries(name="s", points=[c.Point(x="2026-01-01", y=1.0)])],
            takeaway="t",
        ),
        c.DonutBlock(title="h", items=[c.DonutItem(label="A", value=1.0)], takeaway="t"),
        c.RadarBlock(title="h", axes=[c.RadarAxis(name="value", value=3.0)], takeaway="t"),
        c.TrafficLightBlock(
            title="h", items=[c.TrafficItem(label="Quality", status="green")], takeaway="t"
        ),
        c.PercentileBarBlock(title="h", label="P/E", percentile=85, context="ctx", takeaway="t"),
        c.ScorecardBlock(
            title="h", items=[c.ScoreItem(label="FCF>0", passed=True, detail="ok")], takeaway="t"
        ),
        c.TableBlock(title="h", columns=["a"], rows=[["1"]], takeaway="t"),
        c.TextBlock(markdown="**hi**"),
    ]


def test_all_block_types_round_trip_through_union():
    blocks = _one_of_every_block()
    panel = c.ResponsePanel(
        query="q", intent="generic", headline="h", eli5="e", blocks=blocks
    )
    assert len(panel.blocks) == 12

    dumped = json.loads(panel.model_dump_json(by_alias=True))
    restored = c.ResponsePanel.model_validate(dumped)
    # discriminator must reconstruct the exact block classes, in order
    assert [type(b).__name__ for b in restored.blocks] == [
        type(b).__name__ for b in blocks
    ]


def test_scoreitem_accepts_pass_alias_and_field_name():
    # from JSON (alias "pass")
    a = c.ScoreItem.model_validate({"label": "x", "pass": True})
    # from Python (field name)
    b = c.ScoreItem(label="x", passed=True)
    assert a.passed is True and b.passed is True
    assert json.loads(a.model_dump_json(by_alias=True))["pass"] is True
