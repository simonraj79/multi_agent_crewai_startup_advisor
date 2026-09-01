#!/usr/bin/env python
"""Re-run the Synthesist alone, at several reasoning efforts, on fixed evidence.

The point is to make a dial empirical instead of argued, for cents.

The Synthesist is the most expensive step in the pipeline - 61 seconds of a
150-second run, at the escalation tier, with reasoning billed at the completion
rate. It is also, uniquely, a PURE FUNCTION of three things a finished run has
already stored: the scope and the three branch findings. Nothing about it
depends on the branches being re-run, so replaying it costs one call per arm
instead of one full pipeline per arm - roughly two cents against nine.

That is what makes "is `low` too aggressive?" answerable. Before this, the only
way to find out was a paid end-to-end run whose result was a single sample with
no control.

WHAT IT MEASURES, and why these three and not others:

* **wall clock** - the reason the dial was turned at all.
* **anchor margin** - the thing predicted to degrade FIRST. The Synthesist must
  reproduce rubric anchor prose at `ANCHOR_MATCH_THRESHOLD` (0.85) token
  overlap; below that `anchor_problems` rejects and the task is re-run, so a
  shrinking margin is a retry waiting to happen.
* **the five scores** - because a faster model that still passes every guardrail
  and quietly scores differently is the ONE failure mode that does not announce
  itself. Two arms disagreeing on an integer is the only way to see it.

⚠️ THIS SPENDS MONEY. One escalation-tier call per arm per repetition, on real
OpenRouter. It refuses to run without `--yes`. It calls no tools and writes
nothing to the database.

    python scripts/replay_synthesis.py --from-fixtures --yes
    python scripts/replay_synthesis.py --from-fixtures --efforts low,medium,high --repeat 3 --yes

`--from-fixtures` replays the deterministic test fixtures, which is enough to
compare arms against each other. To replay a REAL run's evidence, pass
`--state-file` with a JSON dump of that run's `flow_states` row - the branch
findings live there, so a production incident can be reproduced exactly.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from brief_crew.config import (  # noqa: E402
    ANCHOR_MATCH_THRESHOLD,
    ESCALATION_MODEL,
    RUBRIC_ANCHORS,
)
from brief_crew.schemas import (  # noqa: E402
    FeasibilityFindings,
    MarketFindings,
    ScopedIdea,
    SentimentFindings,
)
from brief_crew.validator_guardrails import (  # noqa: E402
    anchor_margins,
    parse_raw_model,
    rubric_problems,
)
from brief_crew.schemas import Verdict  # noqa: E402

DIMENSIONS = ("D", "M", "C", "F", "X")
FIELD_BY_CODE = {
    "D": "demand",
    "M": "market",
    "C": "competitive_room",
    "F": "feasibility",
    "X": "headroom_over_free",
}


def load_fixtures() -> tuple[ScopedIdea, MarketFindings, SentimentFindings, FeasibilityFindings]:
    from tests.validator.test_flow import fixtures

    scope, market, sentiment, feasibility, _, _ = fixtures()
    return scope, market, sentiment, feasibility


def load_state(path: Path):
    """Rehydrate a real run's evidence from a `flow_states` dump."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    state = payload.get("state", payload)
    return (
        ScopedIdea.model_validate(state["scope"]),
        MarketFindings.model_validate(state["market"]),
        SentimentFindings.model_validate(state["sentiment"]),
        FeasibilityFindings.model_validate(state["feasibility"]),
    )


def run_arm(effort: str, scope, market, sentiment, feasibility) -> dict:
    """One synthesis call at `effort`. Returns what happened, never raises."""
    # Imported here so `--help` and a refusal cost no imports and no key checks.
    from crewai import LLM
    from brief_crew.config import openrouter_reasoning_params
    from brief_crew.crews.validator_crew import SynthesisCrew

    crew_wrapper = SynthesisCrew(market, sentiment, feasibility)
    crew = crew_wrapper.crew()
    # Override the effort on the built agent. The dial has to travel in
    # `extra_body`: CrewAI 1.15.18 drops `LLM(reasoning_effort=...)` for every
    # OpenRouter model, so setting the field would silently measure nothing.
    crew.agents[0].llm = LLM(
        model=ESCALATION_MODEL,
        additional_params=openrouter_reasoning_params(effort),
    )

    started = time.monotonic()
    error = None
    verdict = None
    try:
        result = crew.kickoff(
            inputs={
                "scoped_idea_json": scope.model_dump_json(indent=2),
                "market_findings_json": market.model_dump_json(indent=2),
                "sentiment_findings_json": sentiment.model_dump_json(indent=2),
                "feasibility_findings_json": feasibility.model_dump_json(indent=2),
                "human_override": "",
            }
        )
        raw = getattr(result, "raw", None) or str(result)
        verdict = parse_raw_model(raw, Verdict)
    except Exception as exc:  # noqa: BLE001 - an arm that fails is a RESULT
        error = f"{type(exc).__name__}: {exc}"
    elapsed = time.monotonic() - started

    row: dict = {"effort": effort, "seconds": round(elapsed, 1), "error": error}
    if verdict is not None:
        row["scores"] = {code: getattr(verdict, FIELD_BY_CODE[code]).score for code in DIMENSIONS}
        row["margins"] = anchor_margins(verdict)
        row["guardrail_problems"] = len(
            rubric_problems(verdict, findings=(market, sentiment, feasibility))
        )
    return row


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--efforts", default="low,medium,high")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--from-fixtures", action="store_true")
    parser.add_argument("--state-file", type=Path)
    parser.add_argument("--yes", action="store_true", help="required; this spends money")
    args = parser.parse_args()

    efforts = [item.strip() for item in args.efforts.split(",") if item.strip()]
    supported = {"low", "medium", "high"}
    unknown = set(efforts) - supported
    if unknown:
        # The live catalogue reports supported_efforts exactly ["high","medium",
        # "low"] for this model, with reasoning MANDATORY - there is no
        # "minimal" or "none" to fall back to, and an unknown value is dropped
        # silently by the provider, so the arm would measure the default and
        # look like a result.
        print(f"unsupported effort(s): {sorted(unknown)}; this model allows {sorted(supported)}")
        return 2

    calls = len(efforts) * args.repeat
    if not args.yes:
        print(
            f"This makes {calls} REAL escalation-tier calls on {ESCALATION_MODEL}.\n"
            "Re-run with --yes to proceed."
        )
        return 1

    if args.state_file:
        scope, market, sentiment, feasibility = load_state(args.state_file)
        source = str(args.state_file)
    elif args.from_fixtures:
        scope, market, sentiment, feasibility = load_fixtures()
        source = "test fixtures"
    else:
        print("pass --from-fixtures or --state-file")
        return 2

    print(f"evidence: {source}")
    print(f"model:    {ESCALATION_MODEL}")
    print(f"arms:     {efforts} x{args.repeat}\n")

    rows: list[dict] = []
    for effort in efforts:
        for index in range(args.repeat):
            row = run_arm(effort, scope, market, sentiment, feasibility)
            rows.append(row)
            note = row.get("error") or (
                f"scores={row['scores']} problems={row['guardrail_problems']}"
            )
            print(f"  {effort:<7} #{index + 1}  {row['seconds']:6.1f}s  {note}")

    print("\nSUMMARY")
    baseline_scores = None
    for effort in efforts:
        arm = [r for r in rows if r["effort"] == effort and not r["error"]]
        if not arm:
            print(f"  {effort:<7} all attempts failed")
            continue
        seconds = statistics.fmean(r["seconds"] for r in arm)
        worst_margin = min(min(r["margins"].values(), default=1.0) for r in arm)
        problems = sum(r["guardrail_problems"] for r in arm)
        scores = arm[0]["scores"]
        if baseline_scores is None:
            baseline_scores = scores
            drift = "baseline"
        else:
            differing = [c for c in DIMENSIONS if scores[c] != baseline_scores[c]]
            drift = "same scores" if not differing else f"DIFFERS on {','.join(differing)}"
        flag = "  <-- margin near the 0.85 floor" if worst_margin < 0.90 else ""
        print(
            f"  {effort:<7} {seconds:6.1f}s  worst-margin={worst_margin:.3f}"
            f"  guardrail-problems={problems}  {drift}{flag}"
        )

    print(
        f"\nA margin below {ANCHOR_MATCH_THRESHOLD:.2f} is a REJECTION, and a rejection re-runs\n"
        "the whole task - so an arm that is faster and closer to the floor may be slower\n"
        "in production. Scores that DIFFER between arms are the finding that matters most:\n"
        "that is the failure no guardrail reports."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
