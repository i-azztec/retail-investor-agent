"""ADK multi-agent declarations.

Imports are lazy-friendly: importing this module must not require ADK unless
`build_agents()` is called. The graph is:

    router (LlmAgent, output_schema=RouteIntent)         # replaces regex router
      -> [Python tool dispatch happens in agent_runtime]
      -> analysis = Sequential[ Parallel[analyst, skeptic] -> narrator ]

Numbers are computed by tools (grounding). LLMs only produce language: routing,
pros/cons, headline/eli5/followups.
"""

from app import contracts as c
from app.agent_tools import RouteIntent
from app.models import make_model
from app.security import before_model_injection_guard

_ROUTER_INSTRUCTION = (
    "You classify a beginner retail-investor question. Choose exactly one intent from: "
    "overlap, forensic, beginner_fees, growth, compare, ticker_card, term, market_today, generic. "
    "overlap = comparing holdings/duplication between funds/ETFs. forensic = risk/red-flags/'should I buy' "
    "for one company. beginner_fees = fee/expense-ratio drag. growth = 'what if I invested $X'. "
    "compare = compare two tickers. ticker_card = price/quote/overview of one ticker. term = 'what is X' "
    "glossary. market_today = market movers. generic = anything else. "
    "Extract tickers (UPPERCASE symbols), term, amount, years, expense_ratio, gross_return if present. "
    "Set is_price_question=true for price/quote/'сколько стоит'/'цена'. Do NOT give investment advice."
)

_ANALYST_INSTRUCTION = (
    "You are the Analyst. Given tool data in state key 'result': {result?}. "
    "Give 2-4 honest PROS/positives, each grounded in that data. "
    "Educational only, never say 'buy'. Return JSON matching the schema."
)

_SKEPTIC_INSTRUCTION = (
    "You are the Skeptic. Given tool data in state key 'result': {result?}. "
    "Give 2-4 RISKS/cons (bear-case, concentration, what could go wrong). "
    "Note this is a screen, not a verdict. Educational only. Return JSON matching the schema."
)

_NARRATOR_INSTRUCTION = (
    "You are the Narrator for a beginner. Given 'result': {result?}, 'pros': {pros?}, 'cons': {cons?}. "
    "Produce: headline (1 plain sentence), eli5 (2-3 simple sentences), and 9-12 followups "
    "(3-4 per kind deeper/wider/simpler — add a 4th only when there is a genuinely "
    "interesting or important extra question, otherwise keep 3), each having text, kind, prefill_query. "
    "Plain language, no jargon, educational only."
)

_TOOL_AGENT_INSTRUCTION = (
    "You gather grounded data for a beginner retail-investor assistant by calling exactly ONE tool. "
    "Read the user's question, pick the single best-fitting tool, and call it with correct arguments "
    "(tickers UPPERCASE). Guide: forensic_screen for risk/red-flags/'should I buy' on one company; "
    "holdings_overlap for comparing two or more ETFs; ticker_overview for price/quote/overview of one "
    "ticker; fee_drag for expense-ratio / fee-cost questions; define_term for 'what is X'. "
    "If no tool fits, answer in one short sentence without calling a tool. Never give investment advice."
)


def build_agents():
    """Construct (router, analysis) ADK agents. Requires ADK installed."""
    from google.adk.agents import LlmAgent, ParallelAgent, SequentialAgent

    router = LlmAgent(
        name="router",
        model=make_model("router"),
        output_key="route",
        output_schema=RouteIntent,
        before_model_callback=before_model_injection_guard,
        instruction=_ROUTER_INSTRUCTION,
    )
    analyst = LlmAgent(
        name="analyst",
        model=make_model("analyst"),
        output_key="pros",
        output_schema=c.Pros,
        instruction=_ANALYST_INSTRUCTION,
    )
    skeptic = LlmAgent(
        name="skeptic",
        model=make_model("skeptic"),
        output_key="cons",
        output_schema=c.Cons,
        instruction=_SKEPTIC_INSTRUCTION,
    )
    narrator = LlmAgent(
        name="narrator",
        model=make_model("narrator"),
        output_key="narr",
        output_schema=c.Narr,
        instruction=_NARRATOR_INSTRUCTION,
    )
    analysis = SequentialAgent(
        name="analysis",
        sub_agents=[
            ParallelAgent(name="pros_cons", sub_agents=[analyst, skeptic]),
            narrator,
        ],
    )
    return router, analysis


def build_tool_agent():
    """M9: an ``LlmAgent`` that *itself* invokes a FunctionTool (function calling).

    Distinct from the ``output_schema`` router: in ADK an agent cannot both emit
    structured output and call tools, so this is a separate agent whose only job
    is to issue one real tool call. ``agent_runtime`` maps whichever tool the
    agent picked back onto the deterministic assemble path; ``dispatch`` stays the
    fallback, so grounding never depends on the model choosing the right tool.
    Gated by ``AGENT_TOOL_CALLING`` at runtime.
    """
    from google.adk.agents import LlmAgent

    from app import function_tools

    return LlmAgent(
        name="tool_caller",
        model=make_model("router"),
        before_model_callback=before_model_injection_guard,
        instruction=_TOOL_AGENT_INSTRUCTION,
        tools=_mcp_toolset() or list(function_tools.ALL_TOOLS),
    )


def _mcp_toolset():
    """Optional: consume the finance tools over MCP instead of in-process (M9 bonus).

    When ``AGENT_MCP_TOOLS`` is on, the agent talks to our own ``app.mcp_server``
    (the previously-orphan FastMCP module) over stdio via ADK's ``MCPToolset`` —
    the "Agent Tools: Interoperability with MCP" pillar, agent side. Best-effort:
    returns ``None`` (→ in-process FunctionTools) if MCP/ADK isn't wired, so the
    tool-calling path never hard-depends on a subprocess.
    """
    import os

    if os.getenv("AGENT_MCP_TOOLS", "0").strip().lower() not in {"1", "true", "yes", "on"}:
        return None
    try:
        import sys

        from google.adk.tools.mcp_tool import MCPToolset, StdioConnectionParams
        from mcp import StdioServerParameters

        return [
            MCPToolset(
                connection_params=StdioConnectionParams(
                    server_params=StdioServerParameters(
                        command=sys.executable, args=["-m", "app.mcp_server"]
                    )
                )
            )
        ]
    except Exception:  # noqa: BLE001 — no mcp/subprocess → fall back to in-process tools
        return None


def build_app():
    """Wrap the graph as an ADK 2.x ``App(root_agent=…)`` so ``agents-cli``
    (playground / run / eval) can discover and drive it.

    The production request path uses the manual ``Runner`` in ``agent_runtime``
    (Python tool dispatch happens *between* router and analysis, which a pure
    agent graph can't express). This ``App`` exposes the same agents as one
    root ``SequentialAgent`` for the CLI/playground checkbox; see
    ``app/adk_app.py`` for the entry module.
    """
    from google.adk.agents import SequentialAgent
    from google.adk.apps import App

    router, analysis = build_agents()
    root = SequentialAgent(name="retail_investor_flow", sub_agents=[router, analysis])
    return App(name="retail-investor-agent", root_agent=root)
