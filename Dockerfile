FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV UV_LINK_MODE=copy
ENV PORT=8080
# Deterministic demo data (dense charts come from the committed seed catalog).
ENV TICKER_DATA_MODE=cache
# Agent mode stays legacy in the image so a keyless `docker run` works out of the
# box. Enable the ADK path at deploy time (needs a provider/key), e.g.:
#   gcloud run deploy ... \
#     --set-env-vars AGENT_MODE=adk,AGENT_PROVIDER=gemini,TICKER_DATA_MODE=cache \
#     --update-secrets GEMINI_API_KEY=GEMINI_API_KEY:latest
# The app falls back to the deterministic path if the key/LLM is unavailable.

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY app ./app
COPY server ./server
COPY frontend/dist ./frontend/dist

EXPOSE 8080

CMD ["sh", "-c", "uv run --no-sync uvicorn server.main:app --host 0.0.0.0 --port ${PORT:-8080}"]

