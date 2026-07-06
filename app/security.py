"""Security guardrails for the agent runtime.

Two gates around the LLM:
  * injection-guard  — refuse prompt-injection / secret-exfiltration attempts
                       (Python `check_injection` + ADK `before_model_callback`).
  * disclaimer-guard — guarantee every panel carries the educational-not-advice
                       note (`enforce_disclaimer`).

The ADK callback is written against ADK 2.x, but imports are lazy so this module
loads without ADK. If a future ADK changes the callback contract, the Python
`check_injection` gate in agent_runtime still enforces the policy.
"""

import re

from app import contracts as c

DISCLAIMER = "Educational information, not financial advice."

# Prompt-injection / secret-exfiltration / code-exec attempts.
INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?(previous|prior|above)\s+instructions",
    r"disregard\s+(all\s+)?(previous|prior|your)\s+instructions",
    r"forget\s+(everything|all|your)\s+(you|instructions|rules)",
    r"(system|developer)\s+prompt",
    # Exfiltration: a "reveal/print/show/…" verb *targeting* the prompt/instructions.
    # The verbs MUST be grouped — without the parens, bare "show"/"print" matched
    # any text (e.g. "show red flags"), refusing legitimate questions.
    r"(reveal|print|show|repeat|leak)\b.{0,20}(prompt|instructions|system\s+message)",
    r"\bapi[\s_-]*key\b",
    r"\bsecret(s)?\b|\bcredential(s)?\b|\bpassword\b|\btoken\b",
    r"\bAIzaSy[A-Za-z0-9_\-]{10,}\b",  # a leaked Google API key literal
    r"rm\s+-rf|\bsudo\b|os\.system|subprocess|exec\(|eval\(",
    r"you\s+are\s+now\s+(a|an|dan|jailbroken)",
    r"act\s+as\s+(a\s+)?(dan|jailbreak|unfiltered|developer\s+mode)",
]
_COMPILED = [re.compile(p, re.IGNORECASE) for p in INJECTION_PATTERNS]


def check_injection(text: str) -> bool:
    """Return True if the text looks like a prompt-injection / exfiltration attempt."""
    if not text:
        return False
    return any(p.search(text) for p in _COMPILED)


def before_model_injection_guard(callback_context, llm_request):
    """ADK before_model_callback for the router.

    Inspect the outgoing user text; if it looks like an injection attempt, return
    an `LlmResponse` to short-circuit the model call (ADK skips the LLM and uses
    this response). Returning None lets the call proceed normally.
    """
    try:
        from google.adk.models import LlmResponse
        from google.genai import types
    except Exception:  # ADK/genai not importable — Python gate still applies upstream
        return None

    text = _request_text(llm_request)
    if not check_injection(text):
        return None
    return LlmResponse(
        content=types.Content(
            role="model",
            parts=[types.Part(text='{"intent": "generic", "tickers": []}')],
        )
    )


def _request_text(llm_request) -> str:
    """Best-effort extraction of user text from an ADK LlmRequest across versions."""
    parts: list[str] = []
    contents = getattr(llm_request, "contents", None) or []
    for content in contents:
        for part in getattr(content, "parts", None) or []:
            t = getattr(part, "text", None)
            if isinstance(t, str):
                parts.append(t)
    return "\n".join(parts)


def enforce_disclaimer(panel: c.ResponsePanel) -> c.ResponsePanel:
    """Guarantee the educational-not-advice disclaimer is present in honesty_notes."""
    notes = list(panel.honesty_notes)
    if not any("not financial advice" in n.lower() for n in notes):
        notes.append(DISCLAIMER)
        panel = panel.model_copy(update={"honesty_notes": notes})
    return panel
