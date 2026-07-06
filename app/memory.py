"""Tiny in-memory session interest store — the 'concierge' memory.

Tracks which tickers/intents/terms a session has looked at so followups can be
personalized ("You recently looked at NVDA — compare it with AAPL?"). In-process
only; a real deployment would back this with ADK sessions / a datastore.
"""

from collections import defaultdict
from typing import Any

_CAP = 20
_SESSIONS: dict[str, dict[str, list]] = defaultdict(lambda: {"tickers": [], "intents": [], "terms": []})


def _push(seq: list, value: Any) -> None:
    if not value:
        return
    if value in seq:
        seq.remove(value)
    seq.append(value)
    del seq[:-_CAP]  # keep only the most-recent _CAP


def update(session_id: str | None, route) -> None:
    """Record the tickers/intent/term from a routed query for this session."""
    if not session_id or route is None:
        return
    bucket = _SESSIONS[session_id]
    for ticker in getattr(route, "tickers", []) or []:
        _push(bucket["tickers"], str(ticker).upper())
    _push(bucket["intents"], getattr(route, "intent", None))
    _push(bucket["terms"], getattr(route, "term", None))


def profile(session_id: str | None) -> dict[str, list]:
    """Return a copy of the accumulated interests for a session."""
    if not session_id or session_id not in _SESSIONS:
        return {"tickers": [], "intents": [], "terms": []}
    return {k: list(v) for k, v in _SESSIONS[session_id].items()}


def recent_tickers(session_id: str | None, n: int = 5) -> list[str]:
    """Most-recently-seen tickers for a session (newest last -> return newest first)."""
    if not session_id or session_id not in _SESSIONS:
        return []
    return list(reversed(_SESSIONS[session_id]["tickers"]))[:n]


def reset(session_id: str | None = None) -> None:
    """Clear one session (or all). Used by tests."""
    if session_id is None:
        _SESSIONS.clear()
    else:
        _SESSIONS.pop(session_id, None)
