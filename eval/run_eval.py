"""Agent-quality evaluation over eval/evalset.json.

Two modes:

* **router accuracy** (default) — runs the ADK router on each labelled question,
  compares the predicted intent to the expected one, prints accuracy + confusion
  matrix. Measures the *language* routing quality (black-box).

* **``--judge``** — the Agent-Quality pillar ("the trajectory is the truth",
  glass-box). For each case it runs the *full* agent (router -> tools -> narrator),
  then scores two things: (1) **trajectory** — did the agent invoke the expected
  tool (``panel.intent == expected``)? and (2) **answer quality** via an
  LLM-as-judge on helpfulness + groundedness + safety (1-5 each). Additive — the
  router metric still runs first.

Both modes require a working LLM provider:

    AGENT_PROVIDER=openai uv run python eval/run_eval.py            # router only
    AGENT_PROVIDER=openai uv run python eval/run_eval.py --judge    # + answer quality

Numbers land in docs/ARCHITECTURE.md. Deterministic dispatch/tools are already
covered by the pytest suite.
"""

import argparse
import collections
import json
import os
import pathlib
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_EVALSET = pathlib.Path(__file__).parent / "evalset.json"


def load_evalset() -> list[dict]:
    return json.loads(_EVALSET.read_text(encoding="utf-8"))


def run_router_eval(cases: list[dict]) -> int:
    from app import agent_runtime

    correct = 0
    confusion: dict[tuple[str, str], int] = collections.defaultdict(int)

    for case in cases:
        query, expected = case["query"], case["expected_intent"]
        try:
            predicted = agent_runtime.route_only(query).intent
        except Exception as exc:  # noqa: BLE001
            predicted = f"ERROR:{type(exc).__name__}"
        ok = predicted == expected
        correct += ok
        confusion[(expected, predicted)] += 1
        print(f"[{'ok ' if ok else 'MISS'}] {expected:13s} -> {predicted:13s} | {query}")

    total = len(cases)
    print(f"\nRouter accuracy: {correct}/{total} = {correct / total:.0%}")
    print("\nMisclassifications (expected -> predicted):")
    for (exp, pred), n in sorted(confusion.items()):
        if exp != pred:
            print(f"  {exp:13s} -> {pred:13s}  x{n}")
    return 0


def _answer_summary(panel) -> str:
    """Flatten a ResponsePanel into the text the judge grades (glass-box view)."""
    lines = [panel.headline, panel.eli5]
    lines += [f"+ {p}" for p in panel.pros]
    lines += [f"- {c}" for c in panel.cons]
    lines += [f"* {b.takeaway}" for b in panel.blocks if getattr(b, "takeaway", None)]
    return "\n".join(filter(None, lines))


def run_judge_eval(cases: list[dict], limit: int) -> int:
    from app import agent_runtime, llm_client
    from app.llm_client import LlmUnavailable

    sample = cases[:limit]
    traj_ok = 0
    totals = collections.defaultdict(int)
    scored = 0

    print(f"Agent-Quality judge over {len(sample)} turns (trajectory + LLM-as-judge)\n")
    agent_calls = 0
    for case in sample:
        query, expected = case["query"], case["expected_intent"]
        try:
            panel = agent_runtime.run(query, session_id="eval")
        except Exception as exc:  # noqa: BLE001
            print(f"[RUN-ERR] {expected:13s} | {query} :: {type(exc).__name__}: {exc}")
            continue

        on_traj = panel.intent == expected
        traj_ok += on_traj
        # M9: did the AGENT itself invoke the tool (vs deterministic dispatch)?
        agent_tool = panel.meta.tool_invoked
        agent_calls += bool(agent_tool)
        try:
            verdict = llm_client.judge_answer(query, _answer_summary(panel))
        except LlmUnavailable as exc:
            print(f"[JUDGE-NA] {expected:13s} -> {panel.intent:13s} | {query} :: {exc}")
            continue

        scored += 1
        totals["helpfulness"] += verdict.helpfulness
        totals["groundedness"] += verdict.groundedness
        totals["safety"] += verdict.safety
        flag = "traj-ok " if on_traj else "TRAJ-OFF"
        tool_note = f" [agent→{agent_tool}]" if agent_tool else ""
        print(
            f"[{flag}] {expected:13s} -> {panel.intent:13s} "
            f"| help={verdict.helpfulness} ground={verdict.groundedness} safe={verdict.safety} "
            f"| {query}{tool_note}"
        )

    total = len(sample)
    print(f"\nTrajectory: expected tool invoked on {traj_ok}/{total} = {traj_ok / total:.0%}")
    print(f"Agent-issued tool calls (M9): {agent_calls}/{total}")
    if scored:
        print(f"Judged answers: {scored}/{total}")
        for axis in ("helpfulness", "groundedness", "safety"):
            print(f"  avg {axis:13s} = {totals[axis] / scored:.2f} / 5")
    else:
        print("No answers judged (LLM judge unavailable).")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Agent-quality evaluation.")
    parser.add_argument(
        "--judge",
        action="store_true",
        help="run the full agent and score answer quality + trajectory (LLM-as-judge)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="max turns to run through the judge (default 10; --judge only)",
    )
    args = parser.parse_args()

    cases = load_evalset()
    rc = run_router_eval(cases)
    if args.judge:
        print("\n" + "=" * 60 + "\n")
        rc = run_judge_eval(cases, args.limit) or rc
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
