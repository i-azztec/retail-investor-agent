"""Course-canonical Memory layer (whitepaper: Session ≠ Memory) over our store.

The *Context Engineering: Sessions & Memory* whitepaper splits two things the
base plan conflated:

* **Session** — short-term, one conversation. In this app that is the ADK
  ``DatabaseSessionService`` (see ``agent_runtime``): state that accumulates
  across the turns of a single thread.
* **Memory** — long-term, cross-session "card file" of what the user cares about,
  consolidated between sessions. In this app that is the durable
  ``store.profiles`` table.

This adapter gives that profiles table the ADK ``BaseMemoryService`` shape, so
the split is *code-true* (``add_session_to_memory`` at turn end, ``search_memory``
at turn start feeding the session) rather than only asserted in the write-up —
without standing up a second storage system.

ADK imports are top-level here: this module is only imported on the ADK path,
which already requires ADK. The FastAPI product path never imports it.
"""

from __future__ import annotations

import json

from google.adk.memory import BaseMemoryService
from google.adk.memory.base_memory_service import SearchMemoryResponse
from google.adk.memory.memory_entry import MemoryEntry
from google.genai import types

from app import store


class StoreMemoryService(BaseMemoryService):
    """Long-term Memory backed by ``store.profiles`` (zero PII, per user_id)."""

    async def add_session_to_memory(self, session) -> None:
        """Consolidate the just-finished session into durable cross-session memory.

        Captures both the focus tickers seeded into state and the tickers the
        router actually extracted this turn, plus the intent — so the long-term
        interest profile reflects what the user really engaged with.
        """
        state = dict(getattr(session, "state", None) or {})
        route = state.get("route")
        if isinstance(route, str):
            try:
                route = json.loads(route)
            except (ValueError, TypeError):
                route = None

        tickers = list(state.get("focus_tickers") or [])
        intent = None
        if isinstance(route, dict):
            intent = route.get("intent")
            for t in route.get("tickers") or []:
                if t not in tickers:
                    tickers.append(t)
        if not isinstance(intent, str):
            intent = state.get("intent") if isinstance(state.get("intent"), str) else None

        store.update_profile(
            getattr(session, "user_id", None),
            tickers=[str(t) for t in tickers],
            intent=intent,
        )

    async def search_memory(self, *, app_name: str, user_id: str, query: str) -> SearchMemoryResponse:
        """Return the user's long-term interests as a memory the session can read."""
        prof = store.get_profile(user_id)
        bits: list[str] = []
        if prof["tickers"]:
            bits.append("Tickers of interest: " + ", ".join(prof["tickers"][:8]))
        if prof["intents"]:
            bits.append("Recent question types: " + ", ".join(prof["intents"][:5]))
        if not bits:
            return SearchMemoryResponse(memories=[])
        entry = MemoryEntry(
            author="user",
            content=types.Content(parts=[types.Part(text="; ".join(bits))]),
        )
        return SearchMemoryResponse(memories=[entry])
