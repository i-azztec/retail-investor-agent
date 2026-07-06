# Threat Model

Scope: the FastAPI + static frontend prototype for Retail Investor Agent. This pass focuses on the deployed demo surface: user queries, deterministic tools, cached data, entity cards, and future ADK/Gemini integration.

## Assets

- User query text.
- Cached ETF holdings and demo fixtures.
- Generated `ResponsePanel` answers.
- Future API keys such as `GEMINI_API_KEY`.
- Cloud Run service availability.

## Trust Boundaries

- Browser to FastAPI API.
- FastAPI router to deterministic tools.
- Tool layer to local cached data and future live market-data providers.
- Future ADK/Gemini calls to external model APIs.

## STRIDE

| Category | Risk | Current Control | Next Hardening |
|---|---|---|---|
| Spoofing | Malformed ticker or term pretending to be a valid entity. | Ticker validation and glossary slug lookup. | Add stricter exchange-aware symbol resolution. |
| Tampering | User input changes tool arguments into filesystem paths or code. | Tools accept typed values, not raw paths; holdings are loaded by validated ticker. | Centralize request guards before every tool call. |
| Repudiation | Hard to debug which data mode produced an answer. | `meta.cached`, citations, assumptions, honesty notes. | Add structured request IDs and logs. |
| Information disclosure | Future secrets leak through model prompts or errors. | No secrets in repo; deterministic path does not require keys. | Redact env-like strings in errors and model context. |
| Denial of service | Large or repeated requests strain API or live providers. | Narrow request schema, cached demo data. | Add rate limiting and request length limits at FastAPI middleware. |
| Elevation of privilege | Prompt injection tries to override system/developer rules in future ADK path. | Current router is deterministic; tools do not execute user code. | Add prompt-injection classifier/regex guard before ADK calls. |

## Financial Safety

- The product is educational and not a broker, adviser, or trade execution system.
- Panels should show pros and risks, not buy/sell instructions.
- Numbers should be tied to citations or clearly marked as cached/demo data.
- Unsupported questions should return an honest fallback rather than a misleading canned answer.

## Deployment Checklist

- `.env` is not committed.
- Cloud Run secrets are set through environment variables or Secret Manager.
- `/api/health` responds before sharing the demo URL.
- README explains cached data and educational scope.

