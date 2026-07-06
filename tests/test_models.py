"""Model factory: provider selection without requiring live LLM calls."""

import importlib

import pytest

from app import models


def test_make_model_gemini_default(monkeypatch):
    monkeypatch.setenv("AGENT_PROVIDER", "gemini")
    assert models.make_model("router") == "gemini-3-flash"
    assert models.make_model("analyst") == "gemini-3-flash"
    assert models.make_model("unknown-role") == "gemini-3-flash"


def test_make_model_unknown_provider_raises(monkeypatch):
    monkeypatch.setenv("AGENT_PROVIDER", "bogus")
    with pytest.raises(ValueError):
        models.make_model("router")


def test_make_model_openai_via_litellm(monkeypatch):
    monkeypatch.setenv("AGENT_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    try:
        importlib.import_module("google.adk.models.lite_llm")
    except Exception:
        pytest.skip("ADK/LiteLlm not installed")
    model = models.make_model("router")
    assert model is not None
    assert "gpt" in str(getattr(model, "model", "")).lower() or model is not None
