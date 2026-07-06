"""Model factory for ADK LlmAgents.

Provider-agnostic: Gemini native (a plain model-id string that ADK resolves),
or gpt-5.5/other OpenAI-compatible endpoints via LiteLlm. One place to pick the
provider so every agent role (router/analyst/skeptic/narrator) stays consistent.

`AGENT_PROVIDER` selects the backend (default `gemini`). Roles can be overridden
individually via GEMINI_<ROLE>_MODEL env vars. LiteLlm is imported lazily so this
module (and the whole app) imports fine without ADK installed.
"""

import os

# Role -> default Gemini model id. Overridable per role via env.
_DEFAULT_GEMINI = {
    "router": os.getenv("GEMINI_ROUTER_MODEL", "gemini-3-flash"),
    "analyst": os.getenv("GEMINI_ANALYST_MODEL", "gemini-3-flash"),
    "skeptic": os.getenv("GEMINI_SKEPTIC_MODEL", "gemini-3-flash"),
    "narrator": os.getenv("GEMINI_NARRATOR_MODEL", "gemini-3-flash"),
}
_GEMINI_FALLBACK = "gemini-3-flash"


def _api_key() -> str | None:
    """Reuse llm_client's .env-aware key lookup (OPENAI_API_KEY/LLM_API_KEY)."""
    from app import llm_client

    return llm_client._api_key()


def make_model(role: str):
    """Return a model object/string for an ADK LlmAgent by role."""
    provider = os.getenv("AGENT_PROVIDER", "gemini").lower()
    if provider == "gemini":
        return _DEFAULT_GEMINI.get(role, _GEMINI_FALLBACK)
    if provider in ("openai", "codex", "gpt", "litellm"):
        from google.adk.models.lite_llm import LiteLlm
        from app.settings import llm_settings

        s = llm_settings()
        # LiteLlm's openai provider appends /chat/completions to api_base, so the
        # base must point at the OpenAI-compatible /v1 root, not the site root.
        base = s.base_url.rstrip("/")
        if not base.endswith("/v1"):
            base = f"{base}/v1"
        return LiteLlm(model=f"openai/{s.model}", api_base=base, api_key=_api_key())
    raise ValueError(f"unknown AGENT_PROVIDER: {provider!r}")
