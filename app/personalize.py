"""Risk-profile personalization — the 'concierge' quiz layer (STRETCH T13.2).

A short 3-question quiz (horizon / risk tolerance / goal) maps to one of three
risk profiles. ``apply_risk_profile`` then annotates an already-built
``ResponsePanel`` so the *same grounded panel* speaks to the user's stated risk
tolerance. This is deliberately framing-only: the numbers, blocks and citations
are untouched — we merely add a personalized assumption/honesty note. That keeps
grounding intact while making the assistant feel like a personal concierge.

Pure and deterministic → trivially testable, no LLM call.
"""

from __future__ import annotations

from app import contracts as c

PROFILES = ("conservative", "balanced", "aggressive")

# Per-profile framing added to every personalized panel's assumptions.
_PROFILE_NOTES = {
    "conservative": (
        "you prefer capital preservation over a shorter horizon, so we flag "
        "concentration and drawdown risk more prominently"
    ),
    "balanced": (
        "you want a mix of growth and stability over a medium horizon, so we "
        "treat single-name concentration as a watch-item, not a veto"
    ),
    "aggressive": (
        "you have a long horizon and high risk tolerance, so higher volatility "
        "and concentration may be acceptable — but stay diversified across themes"
    ),
}

# Optional intent-specific nudge appended to honesty notes.
_INTENT_NOTES: dict[str, dict[str, str]] = {
    "overlap": {
        "conservative": (
            "For a conservative profile, high fund overlap quietly concentrates "
            "risk — trimming to one broad-market fund would reduce it."
        ),
        "aggressive": (
            "For an aggressive profile overlap is less alarming, but note you are "
            "effectively doubling down on the same mega-cap names."
        ),
    },
    "forensic": {
        "conservative": (
            "A conservative profile should weight the bear-case flags heavily "
            "before adding a single volatile name."
        ),
    },
    "growth": {
        "aggressive": (
            "An aggressive profile can tolerate the path volatility this "
            "projection glosses over — the end value is not a straight line."
        ),
    },
}


def risk_profile_from_score(score: int) -> str:
    """Map a summed quiz score (6 questions × 1-3 each → 6..18) to a profile.

    Kept in sync with the frontend profileFromScore in frontend/dist/app.js.
    """
    if score <= 10:
        return "conservative"
    if score <= 14:
        return "balanced"
    return "aggressive"


def apply_risk_profile(panel: c.ResponsePanel, profile: str | None) -> c.ResponsePanel:
    """Annotate a panel with the user's risk profile (framing only, in place)."""
    if not profile:
        return panel
    key = profile.lower().strip()
    if key not in PROFILES:
        return panel
    line = f"Tuned for a {key} risk profile — {_PROFILE_NOTES[key]}."
    panel.assumptions = [line, *panel.assumptions]
    extra = _INTENT_NOTES.get(panel.intent, {}).get(key)
    if extra:
        panel.honesty_notes = [*panel.honesty_notes, extra]
    return panel
