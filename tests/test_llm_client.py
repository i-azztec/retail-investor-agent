"""OpenAI-compatible generic LLM client behavior."""

import httpx

from app import contracts as c
from app import llm_client


class _Response:
    def __init__(self, payload: dict):
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


def test_generic_answer_uses_configured_responses_api(monkeypatch):
    seen = {}

    def fake_post(url, headers, json, timeout):
        seen["url"] = url
        seen["auth"] = headers["Authorization"]
        seen["body"] = json
        return _Response(
            {
                "output_text": (
                    '{"headline":"h","answer_md":"body","pros":["p"],"cons":["c"],'
                    '"tickers":["AAPL"],"terms":["valuation"],'
                    '"followups":[{"text":"A","kind":"deeper","prefill_query":"A?"}],'
                    '"limitations":"educational"}'
                )
            }
        )

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("LLM_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("LLM_MODEL", "test-model")
    monkeypatch.setattr(httpx, "post", fake_post)

    result = llm_client.generic_answer("q")

    assert isinstance(result, c.GenericAnswerResult)
    assert result.tickers == ["AAPL"]
    assert result.limitations == ["educational"]
    assert seen["url"] == "https://example.test/v1/responses"
    assert seen["auth"] == "Bearer test-key"
    assert seen["body"]["model"] == "test-model"


def _ok_payload():
    return _Response(
        {
            "output_text": (
                '{"headline":"h","answer_md":"body","pros":[],"cons":[],'
                '"tickers":["NVDA"],"terms":[],"followups":[],"limitations":[]}'
            )
        }
    )


def test_generic_answer_grounds_in_tool_context(monkeypatch):
    seen = {}

    def fake_post(url, headers, json, timeout):
        seen["body"] = json
        return _ok_payload()

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("LLM_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("LLM_MODEL", "test-model")
    monkeypatch.setattr(httpx, "post", fake_post)

    llm_client.generic_answer("explain NVDA", tool_context="P/E=45")

    assert seen["body"]["max_output_tokens"] == 2000
    system_msgs = " ".join(m["content"] for m in seen["body"]["input"] if m["role"] == "system")
    assert "P/E=45" in system_msgs


def test_generic_answer_without_key_raises_unavailable(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setenv("LLM_LOAD_DOTENV", "0")

    try:
        llm_client.generic_answer("q")
    except llm_client.LlmUnavailable as exc:
        assert "not configured" in str(exc)
    else:
        raise AssertionError("missing key should raise LlmUnavailable")


def test_judge_answer_parses_verdict(monkeypatch):
    seen = {}

    def fake_post(url, headers, json, timeout):
        seen["body"] = json
        return _Response(
            {"output_text": '{"helpfulness":5,"groundedness":4,"safety":5,"rationale":"grounded"}'}
        )

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("LLM_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("LLM_MODEL", "test-model")
    monkeypatch.setattr(httpx, "post", fake_post)

    verdict = llm_client.judge_answer("Is NVDA risky?", "NVDA has an Altman-Z of 8.")

    assert isinstance(verdict, c.JudgeVerdict)
    assert (verdict.helpfulness, verdict.groundedness, verdict.safety) == (5, 4, 5)
    user_msg = " ".join(m["content"] for m in seen["body"]["input"] if m["role"] == "user")
    assert "Altman-Z" in user_msg


def test_judge_answer_without_key_raises_unavailable(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setenv("LLM_LOAD_DOTENV", "0")

    try:
        llm_client.judge_answer("q", "a")
    except llm_client.LlmUnavailable as exc:
        assert "not configured" in str(exc)
    else:
        raise AssertionError("missing key should raise LlmUnavailable")
