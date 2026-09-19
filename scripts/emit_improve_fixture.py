#!/usr/bin/env python
"""Emit `frontend/tests/fixtures/improveApi.json` - the Improve tab's contract.

Plan 21, T5. The UI builder works against this file before
`service/improve_api.py`'s handlers exist, which is the only reason two
builders can work at the same time. A fixture bought at that price has exactly
one failure mode worth guarding against, and it is section 14 defect 2's: **a
mirror that agrees with itself.**

Two things stop that here, and neither is a convention:

* **This script never types a shape.** Every example below is an instance of a
  real response model from `service/improve_api.py`, dumped with
  `model_dump(mode="json")`. A field added to a model without being added to
  its example is a `ValidationError` when this script runs; a field added to an
  example that no model has is the same error, because every model here is
  `extra="forbid"`.
* **`tests/service/test_improve_fixture_shapes.py` drives the REAL handlers**
  against a seeded database and asserts the keys they produce equal the keys
  here, per endpoint. So the fixture cannot rot into a second, quieter
  contract: it either matches the server or a Python test fails naming the
  endpoint.

    ./.venv/Scripts/python.exe scripts/emit_improve_fixture.py
    ./.venv/Scripts/python.exe scripts/emit_improve_fixture.py --check

Newlines are written **LF, always**, and `--check` normalises the committed
file before comparing - `emit_admin_fixture.py`'s call, for `core.autocrlf`.

The eval-set export is NDJSON rather than a JSON body, so its entry is a list
of the two line shapes it streams: the header line R3 requires, then one run
line. The values are illustrative and the KEYS are the contract. No
network, no model, no credential, no database.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from typing import Any

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from brief_crew import config  # noqa: E402
from brief_crew.service.improve_api import (  # noqa: E402
    EVALSET_HEADER_NOTE,
    ImproveCompareModel,
    ImproveDigestModel,
    ImproveDigestsModel,
    ImproveHotspotsModel,
)

FIXTURE = REPO_ROOT / "frontend" / "tests" / "fixtures" / "improveApi.json"

#: One example run and one example workflow, referenced by every endpoint so
#: the client can join them the way the panel does.
RUN_ID = "073c021f-4ff7-43e1-84d5-d9e8dd7fa0ba"
WORKFLOW_ID = "ug_4d2b81ac"
WINDOW: dict[str, Any] = {
    "start": "2026-08-09T00:00:00Z",
    "end": "2026-09-08T00:00:00Z",
    "days": 30,
}


def hotspots() -> ImproveHotspotsModel:
    return ImproveHotspotsModel(
        window=WINDOW,
        workflow_id=WORKFLOW_ID,
        runs=9,
        document_version=4,
        agents=[
            {
                "agent_role": "Market evidence analyst",
                "node_id": "market_research",
                "node_label": "Market research",
                "runs": 9,
                "executions": 11,
                "failures": 1,
                "error_classes": ["BadRequestError"],
                "guardrail_retries": 4,
                "guardrail_names": ["market_source_closure"],
                "llm_calls": 96,
                "calls_per_execution": 8.7,
                "mean_ms": 21403.0,
                # The talk's counterfactual as arithmetic: the SAME token
                # counts priced at CHEAP_MODEL. `null` when the node already
                # runs cheap or its tokens are unknown - never 0.0.
                "cheap_tier_cost_usd": 0.2412,
                "cost_usd": 0.3184,
                "cost_share": 0.54,
                "truncated_outputs": 3,
            }
        ],
        tools=[
            {
                "tool": "MarketResearchTool",
                "agent_role": "Market evidence analyst",
                "node_id": "market_research",
                "node_label": "Market research",
                "calls": 18,
                "empty": 9,
                "empty_rate": 0.5,
                "failed": 2,
                "failed_rate": 0.111,
                "from_cache": 1,
                "queries_sample": [
                    "AI tool creates educational materials assessment",
                    "quiz generator LLM",
                ],
            }
        ],
        errors=[
            {
                "error_class": "BadRequestError",
                "count": 3,
                "nodes": ["market_research"],
                "agent_roles": ["Market evidence analyst"],
            }
        ],
        gates=[
            {
                "gate_id": "scope-confirmation",
                "node_id": "confirm_scope",
                "node_label": "Confirm the scope",
                "opened": 9,
                "answered": 8,
                "revise": 4,
                "revise_rate": 0.5,
                "expired": 1,
                "median_seconds": 192.0,
                "edited_fields": ["segment"],
            }
        ],
        routes=[
            {
                "node_id": "route_scope",
                "node_label": "Scope decision",
                "decisions": 8,
                "routes": {"scope_approved": 8},
                "unique_routes": 1,
            }
        ],
        outcomes={
            "by_verdict": [
                {
                    "verdict": "NEEDS_WORK",
                    "runs": 6,
                    "mean_confidence": 0.41,
                    "cost_usd": 0.3702,
                    "cost_per_run": 0.0617,
                }
            ],
            "by_rating": [{"rating": "good", "runs": 3, "cost_usd": 0.1841}],
            "by_status": {"completed": 8, "failed": 1, "cancelled": 0, "other": 0},
        },
        tasks=[
            {
                "task_name": "market_task",
                "node_id": "market_research",
                "node_label": "Market research",
                "completions": 9,
                "tool_failures": 4,
                "truncated_outputs": 3,
            }
        ],
        task_completions=38,
        task_tool_failures=13,
        rated=7,
        rating_mix={"good": 3, "bad": 3, "unsure": 1, "unrated": 2},
        verdicts=6,
        low_confidence=3,
        mean_confidence=0.41,
        sample_run_ids=[RUN_ID],
        # TWO shapes on purpose: a node that has run on two models, which is
        # the only kind a model comparison has anything to say about, and a
        # node that has run on one, which the picker must still offer and must
        # not pretend is comparable.
        node_models=[
            {
                "node_id": "market_research",
                "label": "Market research",
                "models": [config.CHEAP_MODEL, config.ESCALATION_MODEL],
                "runs": 9,
            },
            {
                "node_id": "confirm_scope",
                "label": "Confirm the scope",
                "models": [config.ESCALATION_MODEL],
                "runs": 4,
            },
        ],
        truncated=False,
    )


def compare() -> ImproveCompareModel:
    return ImproveCompareModel(
        window=WINDOW,
        workflow_id=WORKFLOW_ID,
        axis="version",
        node_id=None,
        arms=[
            {
                "key": "3",
                "n": 6,
                "underpowered": False,
                "status_mix": {"completed": 5, "failed": 1},
                "verdict_mix": {"NEEDS_WORK": 4, "VALIDATE": 1},
                "mean_confidence": 0.38,
                "rating_mix": {"good": 1, "bad": 2, "unsure": 0, "unrated": 3},
                "gate_revise_rate": 0.5,
                "median_duration_ms": 61402.0,
                "cost_per_run_usd": 0.0631,
            },
            {
                "key": "4",
                "n": 3,
                "underpowered": True,
                "status_mix": {"completed": 3},
                "verdict_mix": {"VALIDATE": 2, "NEEDS_WORK": 1},
                "mean_confidence": 0.62,
                "rating_mix": {"good": 2, "bad": 0, "unsure": 0, "unrated": 1},
                "gate_revise_rate": 0.0,
                "median_duration_ms": 58110.0,
                "cost_per_run_usd": 0.0588,
            },
            {
                # D9: an arm the caller ASKED for that this window has no runs
                # of. SHOWN and FLAGGED rather than omitted - `arms: []` with
                # no sentence lets a reader conclude the comparison could not
                # be made at all.
                "key": "5",
                "n": 0,
                "underpowered": True,
                "missing": True,
                "status_mix": {},
                "verdict_mix": {},
                "mean_confidence": None,
                "rating_mix": {"good": 0, "bad": 0, "unsure": 0, "unrated": 0},
                "gate_revise_rate": None,
                "median_duration_ms": None,
                "cost_per_run_usd": 0.0,
            },
        ],
        truncated=False,
    )


def digest_row() -> ImproveDigestModel:
    return ImproveDigestModel(
        id="dg_2f7a91c4",
        workflow_id=WORKFLOW_ID,
        created_by="user_admin",
        window=WINDOW,
        sample_runs=9,
        sample_frames=312,
        truncated_sample=False,
        model=config.CHEAP_MODEL,
        prompt_tokens=8214,
        completion_tokens=734,
        cost_usd=0.0043,
        # R5: the MEASURED cost against the cap in force when it ran,
        # decided once and stored.
        over_cap=False,
        # NULL on a review that worked. A failed ATTEMPT carries the reason
        # and no body, because a model call that raised may still have been
        # billed and the per-day brake counts attempts.
        error=None,
        body=(
            "## What went well\n\nThe scope gate is being approved first time "
            "in 4 of 8 runs.\n\n## What is failing\n\n**Market research** "
            "returns nothing half the time.\n"
        ),
        created_at="2026-09-08T12:41:07Z",
    )


def digests() -> ImproveDigestsModel:
    return ImproveDigestsModel(
        workflow_id=WORKFLOW_ID,
        enabled=False,
        # Summed from `improve_digests.cost_usd` for this workflow. It is the
        # ONLY place a review's spend appears - the row has no `run_id`, so
        # every money read plan 17 built is blind to it - and it is never
        # added to run spend.
        total_cost_usd=0.0121,
        # The COUNT, not `len(rows)`: the list is `?limit=`ed, so the two
        # disagree the moment a workflow passes the cap and the panel would
        # report the page as the total.
        total_count=3,
        # What is left of today's allowance, across the DEPLOYMENT, and what
        # the allowance is. On the READ so the panel can say it before the
        # press: a button that refuses after the click has already made
        # somebody think the product is broken.
        remaining_today=7,
        rows=[digest_row()],
    )


def evalset_lines() -> list[dict[str, Any]]:
    """The two NDJSON line shapes, in the order they are streamed.

    Typed here rather than dumped from a model, and it is the one example in
    this file that is: the export is a STREAM assembled line by line in
    `improve_api._evalset_lines` and there is no pydantic model to instance.
    `test_improve_fixture_shapes.py` compares the served lines against these
    two, which is what keeps the exemption honest.
    """

    return [
        {
            "_header": True,
            "note": EVALSET_HEADER_NOTE,
            "workflow_id": WORKFLOW_ID,
            "rating": "good",
            "window": WINDOW,
            "max_runs": config.EVALSET_MAX_RUNS,
            "max_bytes": config.EVALSET_MAX_BYTES,
            "generated_at": "2026-09-08T12:44:02Z",
        },
        {
            "run_id": RUN_ID,
            "workflow_id": WORKFLOW_ID,
            "document_version": 4,
            "graph_version": "8f14e45fceea167a",
            "created_at": "2026-09-07T09:12:44Z",
            "status": "completed",
            "mode": "run",
            "cost_usd": 0.061,
            "inputs": {"idea": "a scheduling assistant for clinics"},
            "outcome": {
                "verdict": "VALIDATE",
                "confidence": 0.71,
                "result_summary": "# Validation report\n\nThe clinics segment…",
            },
            "gates": [
                {
                    "gate_id": "scope-confirmation",
                    "decision": "revise",
                    "pairs": [
                        {
                            "key": "segment",
                            "proposed": "SMBs",
                            "corrected": "independent clinics",
                            "changed": True,
                        }
                    ],
                }
            ],
            "rating": "good",
            "rating_note": "the segment was right",
            "rated_at": "2026-09-08T12:03:11Z",
        },
    ]


def examples() -> dict[str, Any]:
    return {
        "GET /api/admin/improve/hotspots": hotspots(),
        "GET /api/admin/improve/compare": compare(),
        "GET /api/admin/improve/digests": digests(),
        "POST /api/admin/improve/digests": digest_row(),
        "GET /api/admin/export/evalset": {"_ndjson_lines": evalset_lines()},
    }


def payload() -> dict[str, Any]:
    body: dict[str, Any] = {
        "_comment": (
            "GENERATED by scripts/emit_improve_fixture.py from the response "
            "models in src/brief_crew/service/improve_api.py. Do not edit. The "
            "VALUES are illustrative; the KEYS are the contract, and "
            "tests/service/test_improve_fixture_shapes.py asserts the real "
            "handlers produce exactly these keys."
        ),
        "_error_note": (
            "Every dollar on this surface is the app's own estimate from "
            "run_node_metrics, measured -14.5% to +9.95% against billed."
        ),
        "_min_runs": config.IMPROVE_MIN_RUNS,
        "_min_compare_runs": config.IMPROVE_MIN_COMPARE_RUNS,
        "_evalset_ratings": ["good", "bad", "unsure", "any"],
        "_compare_axes": {
            "_comment": (
                "axis=model REQUIRES node_id (422 without it), the arms are "
                "disjoint, and cost_per_run_usd is then that node's cost "
                "rather than the whole run's (R4). A hand-written flow has "
                "no document, so the version axis answers one `unknown` arm."
            ),
            "version": {"node_id": "not used"},
            "model": {"node_id": "required"},
        },
        "_unknown_arm": "unknown",
        "_mixed_arm": "mixed",
        "_digest_bounds": {
            "_comment": (
                "Shown beside the review button BEFORE the click, with the "
                "model. max_cost_usd is checked at import from PRICES; a "
                "breach DISABLES the feature rather than raising (R9)."
            ),
            "model": config.CHEAP_MODEL,
            "max_cost_usd": config.DIGEST_MAX_COST_USD,
            "max_per_day": config.DIGEST_MAX_PER_DAY,
            "min_interval_seconds": config.DIGEST_MIN_INTERVAL_SECONDS,
            "max_sample_runs": config.DIGEST_MAX_SAMPLE_RUNS,
            "max_sample_frames": config.DIGEST_MAX_SAMPLE_FRAMES,
            "max_input_chars": config.DIGEST_MAX_INPUT_CHARS,
            "max_output_tokens": config.DIGEST_MAX_OUTPUT_TOKENS,
        },
        "_digest_refusals": {
            "_comment": (
                "The three 429 sentences the money brakes answer with. All "
                "server-side: the knob is a deployment switch, not a rate "
                "limit, and twenty POSTs were measured producing twenty model "
                "calls before these existed."
            ),
            "in_flight": (
                "a review is already running on this deployment; wait for it "
                "to finish and try again"
            ),
            "per_day": (
                "this deployment has asked for 10 reviews in the last 24 "
                "hours, the limit is 10; try again after "
                "2026-09-19T12:00:00Z"
            ),
            "min_interval": (
                "a review of this workflow ran less than 30 seconds ago; try "
                "again in 12 seconds"
            ),
            "model_failed": {
                "status": 502,
                "detail": (
                    "the model did not answer; the attempt was recorded "
                    "because it may still have been billed"
                ),
            },
        },
        "_digest_disabled_refusal": {
            "_comment": (
                "POST /improve/digests with IMPROVE_DIGEST_ENABLED off. 422, "
                "and no LLM is constructed."
            ),
            "detail": (
                "the model review is off on this deployment; set "
                "IMPROVE_DIGEST_ENABLED=1 to turn it on"
            ),
        },
    }
    for endpoint, example in examples().items():
        body[endpoint] = (
            example if isinstance(example, dict) else example.model_dump(mode="json")
        )
    return body


def rendered() -> str:
    return json.dumps(payload(), indent=2, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit 1 if the committed fixture differs, writing nothing",
    )
    args = parser.parse_args(argv)
    text = rendered()
    if args.check:
        if not FIXTURE.exists():
            print(f"missing: {FIXTURE}", file=sys.stderr)
            return 1
        committed = FIXTURE.read_text(encoding="utf-8").replace("\r\n", "\n")
        if committed != text:
            print(
                f"{FIXTURE} is stale; re-run scripts/emit_improve_fixture.py",
                file=sys.stderr,
            )
            return 1
        print(f"{FIXTURE.name} is current")
        return 0
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {FIXTURE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
