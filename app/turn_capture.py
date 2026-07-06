"""Per-request capture of the context/tool facts a turn actually fed the LLM.

M6 needs two things persisted on a turn that the ResponsePanel does not carry:

* ``tool_result_json``  — the compact grounded numbers the LLM saw this turn
  (forensic scores, overlap %, fee_drag …), so a *follow-up* can re-inject the
  exact figures instead of only the ticker symbol.
* ``context_prompt``    — the full assembled context string sent to the LLM, so a
  stored turn is auditable ("почему такой ответ").

Both are produced deep inside the routing branches (``_llm_over_tool`` builds the
tool summary; ``answer_query_adk`` builds the conversation context) but must be
read at the save point in ``server.main.ask``. Threading a return value through
every branch would be invasive, so we stash them in a ``contextvars.ContextVar``.

Why a ContextVar is correct here: FastAPI runs each sync endpoint in a threadpool
worker with its *own* copied context, and ``ask()`` calls the query layer
synchronously within that same context — so a value ``set`` inside the query
layer is visible back in ``ask()`` and never leaks across concurrent requests.
"""

from __future__ import annotations

import contextvars

_CTX: contextvars.ContextVar[dict | None] = contextvars.ContextVar("turn_capture", default=None)


def reset() -> None:
    """Start a fresh capture for this turn (call once at the entry point)."""
    _CTX.set({"tool_context": None, "conversation_context": None})


def set_conversation_context(value: str | None) -> None:
    d = _CTX.get()
    if d is not None:
        d["conversation_context"] = value


def set_tool_context(value: str | None) -> None:
    d = _CTX.get()
    if d is not None:
        d["tool_context"] = value


def get() -> dict:
    """Return {'tool_context', 'conversation_context'} for the current turn."""
    return _CTX.get() or {"tool_context": None, "conversation_context": None}
