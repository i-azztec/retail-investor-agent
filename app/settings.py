"""Environment-backed settings helpers.

Kept dependency-free for now: the agent layer can later adapt these values to
ADK, LiteLLM, or an OpenAI-compatible SDK without changing the app surface.
"""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class LlmSettings:
    provider: str
    base_url: str
    wire_api: str
    model: str
    review_model: str
    reasoning_effort: str
    disable_response_storage: bool


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _load_dotenv() -> None:
    """Load .env file into os.environ if it exists and LLM_LOAD_DOTENV is not disabled."""
    if os.getenv("LLM_LOAD_DOTENV", "1").strip().lower() in {"0", "false", "no", "off"}:
        return
    path = ".env"
    if not os.path.exists(path):
        return
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key_stripped = key.strip()
                if key_stripped not in os.environ:
                    os.environ[key_stripped] = value.strip().strip('"').strip("'")
    except OSError:
        pass


_load_dotenv()


def llm_settings() -> LlmSettings:
    """Return current LLM runtime settings from environment variables."""
    model = os.getenv("LLM_MODEL", "google/gemini-3.1-flash-lite")
    return LlmSettings(
        provider=os.getenv("LLM_PROVIDER", "openrouter"),
        base_url=os.getenv("LLM_BASE_URL", "https://openrouter.ai/api/v1"),
        wire_api=os.getenv("LLM_WIRE_API", "responses"),
        model=model,
        review_model=os.getenv("LLM_REVIEW_MODEL", model),
        reasoning_effort=os.getenv("LLM_REASONING_EFFORT", "high"),
        disable_response_storage=_bool_env("LLM_DISABLE_RESPONSE_STORAGE", True),
    )
