"""Tests for the risk-profile personalization layer (STRETCH T13.2)."""

import pytest

from app import contracts as c
from app import personalize


def _panel(intent: str = "overlap") -> c.ResponsePanel:
    return c.ResponsePanel(
        query="q",
        intent=intent,
        headline="h",
        eli5="e",
        assumptions=["existing assumption"],
        honesty_notes=["existing note"],
    )


@pytest.mark.parametrize(
    "score,expected",
    [(6, "conservative"), (10, "conservative"), (11, "balanced"), (14, "balanced"), (15, "aggressive"), (18, "aggressive")],
)
def test_profile_from_score(score, expected):
    assert personalize.risk_profile_from_score(score) == expected


def test_apply_none_is_noop():
    panel = _panel()
    out = personalize.apply_risk_profile(panel, None)
    assert out.assumptions == ["existing assumption"]
    assert out.honesty_notes == ["existing note"]


def test_apply_unknown_profile_is_noop():
    panel = _panel()
    out = personalize.apply_risk_profile(panel, "reckless")
    assert out.assumptions == ["existing assumption"]


def test_apply_prepends_assumption():
    panel = _panel()
    out = personalize.apply_risk_profile(panel, "Conservative")
    assert out.assumptions[0].startswith("Tuned for a conservative risk profile")
    assert "existing assumption" in out.assumptions


def test_apply_adds_intent_specific_note_when_available():
    panel = _panel(intent="overlap")
    out = personalize.apply_risk_profile(panel, "conservative")
    assert len(out.honesty_notes) == 2
    assert "broad-market fund" in out.honesty_notes[-1]


def test_apply_without_intent_note_keeps_notes():
    # balanced has no overlap-specific note -> honesty_notes unchanged
    panel = _panel(intent="overlap")
    out = personalize.apply_risk_profile(panel, "balanced")
    assert out.honesty_notes == ["existing note"]
