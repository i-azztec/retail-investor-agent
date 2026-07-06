"""agents-cli entry point (ADK 2.x App form).

Point the Agents CLI at this module to get playground / run / eval:

    uv run agents-cli playground app.adk_app
    uv run agents-cli eval app.adk_app ...

Importing this module DOES require ADK (unlike ``app.agent``, whose ADK imports
are lazy). The FastAPI product path never imports it, so the app still starts
without ADK. ``AGENT_PROVIDER=gemini`` (default) resolves model ids as plain
strings, so building the App needs no live API key.
"""

from app.agent import build_app

app = build_app()
root_agent = app.root_agent
