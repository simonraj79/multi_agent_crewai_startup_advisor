#!/usr/bin/env python
"""Emit `frontend/tests/fixtures/adminApi.json` - the admin console's contract.

W-UI builds `services/adminApi.ts` and every admin spec against this file
before `service/admin_api.py`'s handlers exist, which is the only reason the
three builders of plan 17 can work at the same time. A fixture bought at that
price has exactly one failure mode worth guarding against, and it is the one
section 14 defect 2 of CLAUDE.md is about: **a mirror that agrees with
itself.** `PROBLEM_CODES` carried 27 codes where the server emitted 30, and
its own anti-rot test read two of the three files that declare them.

Two things stop that here, and neither is a convention:

* **This script never types a shape.** Every example below is an instance of
  the real response model from `service/admin_api.py`, dumped with
  `model_dump(mode="json")`. A field added to a model without being added to
  its example is a `ValidationError` when this script runs; a field added to
  an example that no model has is the same error, because every admin model is
  `extra="forbid"`.
* **`tests/service/test_admin_fixture_shapes.py` drives the REAL handlers**
  against a seeded database and asserts the keys they produce equal the keys
  here, per endpoint (plan 17 criterion 21). So the fixture cannot rot into a
  second, quieter contract: it either matches the server or a Python test
  fails naming the endpoint.

    ./.venv/Scripts/python.exe scripts/emit_admin_fixture.py
    ./.venv/Scripts/python.exe scripts/emit_admin_fixture.py --check

Newlines are written **LF, always**, and `--check` normalises the committed
file before comparing. `core.autocrlf` is `true` in this repository, so a
checkout hands you CRLF and a naive byte comparison fails on every Windows
machine and passes on every Linux one - the drift alarm would then be about a
shell setting. `emit_builder_fixtures.py` made the same call for the same
reason.

The values are illustrative and the KEYS are the contract. No network, no
model, no credential, no database: this imports `brief_crew.service.admin_api`
and writes one file.
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

from brief_crew.service.admin_api import (  # noqa: E402
    AdminBilledModel,
    AdminDecisionsModel,
    AdminGatesModel,
    AdminHealthModel,
    AdminLinksModel,
    AdminProvidersModel,
    AdminRunsModel,
    AdminSpendModel,
    AdminSummaryModel,
    AdminUserDetailModel,
    AdminUsersModel,
    AdminVerdictsModel,
    AdminWhoamiModel,
    BLIND_TO,
    SPEND_ERROR_NOTE,
    VERDICT_NOTE,
)

FIXTURE = REPO_ROOT / "frontend" / "tests" / "fixtures" / "adminApi.json"

#: One example run, referenced by three endpoints so the client can join them.
RUN_ID = "073c021f-4ff7-43e1-84d5-d9e8dd7fa0ba"
PROJECT = "cmf0examplelangfuseproj"
LANGFUSE_HOST = "https://us.cloud.langfuse.com"
SESSION_URL = f"{LANGFUSE_HOST}/project/{PROJECT}/sessions/{RUN_ID}"
#: `trace_id_for` on a UUID run id is its hex, and this pairing is the one
#: measured in `docs/observability/evidence/` - criterion 20 asserts it.
TRACE_URL = f"{LANGFUSE_HOST}/project/{PROJECT}/traces/073c021f4ff743e184d5d9e8dd7fa0ba"

USER_ROW: dict[str, Any] = {
    "user_id": "user_owner",
    "email": "owner@example.test",
    "name": "The owner",
    "created_at": "2026-08-14T09:12:00Z",
    "last_run_at": "2026-09-08T11:41:07Z",
    "last_session_at": "2026-09-08T11:02:55Z",
    "runs": 28,
    "spent_usd": 1.4212,
    "committed_usd": 0.0,
    "committed_is_volatile": True,
    "cap_usd": None,
    "exempt": True,
    "documents": 4,
    "published": 1,
    "credentials": 2,
    "skills": 1,
    "tools": 0,
    "mcp_servers": 0,
    "firecrawl_today": 3,
}

RUN_ROW: dict[str, Any] = {
    "run_id": RUN_ID,
    "user_id": "user_owner",
    "email": "owner@example.test",
    "workflow_id": "idea-validator",
    "mode": "run",
    "status": "completed",
    "created_at": "2026-09-08T11:38:02Z",
    "started_at": "2026-09-08T11:38:03Z",
    "completed_at": "2026-09-08T11:41:07Z",
    "duration_ms": 184000,
    "cost_usd": 0.0562551,
    "ceiling_kind": "run",
    "max_cost_usd": 10.0,
    "account_cap_usd": None,
    "stop_reason": None,
    "error": None,
    "verdict": "NEEDS_WORK",
    "integrity": {"captured": 412, "dropped": 0, "gaps": 0},
    "langfuse": {"session_url": SESSION_URL, "trace_url": TRACE_URL},
}


def examples() -> dict[str, Any]:
    """One example response per endpoint of plan 17 section 3.

    Keyed by the endpoint's path template, so `adminApi.ts` and the criterion
    21 test both address them the same way and neither has to invent a name.
    A key beginning with `_` is not an endpoint - it is a second arm of one,
    or a note - and the criterion 21 test's `GET `-prefixed scan skips it.

    `POST /workflows/{document_id}/unpublish` is deliberately ABSENT: it
    answers the existing `BuilderDocumentModel`, which is already pinned by
    `frontend/tests/fixtures/builderGraphDescriptor.json` and
    `frontend/tests/builderApi.spec.ts`, and a second example of it here would
    be a second place for that shape to drift.
    """

    return {
        "GET /api/admin/whoami": AdminWhoamiModel(
            admin=True, user_id="user_owner", email="owner@example.test"
        ),
        # The SAME route's other arm, under a `_` key so the shape test's
        # `GET `-prefixed scan does not count it as a fourteenth endpoint.
        # `whoami` is the one route that answers everybody - a 404 there is a
        # console error on every non-admin's every page load, for a fact the
        # bundle already publishes. The key set is identical to the arm above,
        # which is what lets `adminApi.ts` read one shape.
        "_whoami_non_admin": AdminWhoamiModel(
            admin=False, user_id="user_someone", email="someone@example.test"
        ),
        "_whoami_anonymous": AdminWhoamiModel(admin=False, user_id=None, email=None),
        "GET /api/admin/summary": AdminSummaryModel(
            spend_usd_estimate=1.8412,
            runs={
                "queued": 0,
                "running": 0,
                "waiting": 2,
                "completed": 28,
                "failed": 6,
                "cancelling": 0,
                "cancelled": 3,
            },
            people_active=6,
            people_total=11,
            people_new=2,
            refusals={"account_cap": 2, "run_ceiling": 0},
            spend_by_day=[
                {"day": "2026-09-01", "usd": 0.42, "runs": 5},
                {"day": "2026-09-02", "usd": 0.1108, "runs": 2},
            ],
            top_accounts=[
                {
                    "user_id": "user_owner",
                    "email": "owner@example.test",
                    "spent_usd": 1.4212,
                    "committed_usd": 0.0,
                    "cap_usd": None,
                    "exempt": True,
                },
                {
                    "user_id": "__unowned__",
                    "email": None,
                    "spent_usd": 0.12,
                    "committed_usd": 0.0,
                    "cap_usd": None,
                    "exempt": False,
                },
            ],
            attention=[
                {"kind": "gate_open_long", "run_id": RUN_ID, "hours": 26.4},
            ],
            truncated=False,
        ),
        "GET /api/admin/spend": AdminSpendModel(
            group_by="model",
            rows=[
                {
                    "key": "google/gemini-3.8-flash",
                    "label": "google/gemini-3.8-flash",
                    "cost_usd": 1.0231,
                    "total_tokens": 412000,
                    "prompt_tokens": 331000,
                    "completion_tokens": 81000,
                    "call_count": 88,
                    "runs": 22,
                },
                {
                    "key": "google/gemini-3.5-flash-lite",
                    "label": "google/gemini-3.5-flash-lite",
                    "cost_usd": 0.8181,
                    "total_tokens": 903400,
                    "prompt_tokens": 812000,
                    "completion_tokens": 91400,
                    "call_count": 144,
                    "runs": 22,
                },
            ],
            total_usd=1.8412,
            truncated=False,
        ),
        "GET /api/admin/users": AdminUsersModel(rows=[USER_ROW], next=None),
        "GET /api/admin/users/{user_id}": AdminUserDetailModel(
            **USER_ROW,
            gates={"answered": 8, "expired": 1, "median_seconds": 192.0},
            recent_runs=[RUN_ROW],
            langfuse={"user_url": None},
        ),
        "GET /api/admin/runs": AdminRunsModel(
            rows=[RUN_ROW],
            next="MjAyNi0wOS0wOFQxMTozODowMiswMDowMHwwNzNjMDIxZg==",
        ),
        "GET /api/admin/runs/{run_id}/decisions": AdminDecisionsModel(
            run_id=RUN_ID,
            gates=[
                {
                    "gate_id": "scope-confirmation",
                    "node_id": "confirm_scope",
                    "status": "answered",
                    "opened_at": "2026-09-08T11:38:40Z",
                    "answered_at": "2026-09-08T11:41:52Z",
                    "seconds": 192.0,
                    "outcome": "approve",
                    "response": {
                        "decision": "approve",
                        "fields": {"note": "the segment is right, go on"},
                    },
                }
            ],
            guardrails=[
                {
                    "guardrail": "report_citation_closure",
                    "guardrail_type": "llm",
                    "retry_count": 1,
                    "node_id": "write_report",
                }
            ],
            fallback_models=[
                {
                    "node_id": "n3_reviewer",
                    "fallback_model": "openrouter/google/gemini-3.5-flash-lite",
                    "attempt": 2,
                }
            ],
            verdict={
                "verdict": "NEEDS_WORK",
                "score": 4.2,
                "confidence": 0.62,
                "decision_reason": "SCORE_BAND",
            },
            langfuse={"session_url": SESSION_URL, "trace_url": TRACE_URL},
        ),
        "GET /api/admin/gates": AdminGatesModel(
            approve=71,
            revise=22,
            expired=7,
            unanswered=3,
            median_seconds=192.0,
            by_gate=[
                {
                    "gate_id": "review_verdict",
                    "count": 12,
                    "median_seconds": 520.0,
                    "expired": 1,
                }
            ],
            truncated=False,
        ),
        "GET /api/admin/verdicts": AdminVerdictsModel(
            complete=True,
            rows=[
                {"verdict": "NEEDS_WORK", "count": 14},
                {"verdict": "REJECT", "count": 5},
                {"verdict": "VALIDATE", "count": 1},
            ],
            note=VERDICT_NOTE,
            truncated=False,
        ),
        "GET /api/admin/health": AdminHealthModel(
            # `/readyz`'s OWN body, key for key - the route validates the
            # same payload through the same `ReadyResponse`, so this example
            # is `executor` + `storage` and not the `persistence` this file
            # invented on its first pass. A fixture that describes a shape the
            # server does not produce is exactly the second, quieter contract
            # criterion 21 exists to prevent, and the two would have differed
            # in the one block a reader is most likely to trust.
            readyz={
                "status": "ok",
                "dependencies": {
                    "executor": {"status": "ok", "backend": None, "workers": 1},
                    "storage": {"status": "ok", "backend": "postgresql", "workers": None},
                },
                "gates": {
                    "open": 1,
                    "expired": 0,
                    "alerting": 0,
                    "expiries": 0,
                    "alerts": 0,
                    "sweeps": 0,
                },
                "observability": {
                    "exporter": "enabled",
                    "reason": None,
                    "environment": "live",
                    "capture_content": False,
                    "resolve_billed_cost": True,
                },
            },
            integrity={
                "captured": 41208,
                "dropped": 0,
                "gaps": 0,
                "emit_errors": 0,
                "subscriber_dropped": 12,
                "runs_with_drop": 1,
            },
            orphans=0,
            retention_days=0,
            ceilings={
                "run_usd": 10.0,
                "account_usd": 1.0,
                "margin": 1.25,
                "firecrawl_daily": 50,
            },
            blind_to=list(BLIND_TO),
        ),
        "GET /api/admin/links": AdminLinksModel(
            langfuse={
                "base_url": LANGFUSE_HOST,
                "project_id": PROJECT,
                "configured": True,
            },
            openrouter_activity_url="https://openrouter.ai/activity",
            openrouter_credits_url="https://openrouter.ai/settings/credits",
            firecrawl_dashboard_url="https://www.firecrawl.dev/app/settings?tab=billing",
        ),
        "GET /api/admin/providers": AdminProvidersModel(
            openrouter={
                "available": True,
                "reason": None,
                "source": "credits",
                "total_credits": 30.0,
                "total_usage": 2.45,
                "remaining_usd": 27.55,
                "usage": None,
                "limit": None,
                "limit_remaining": None,
                "is_free_tier": None,
                "label": None,
                "checked_at": "2026-09-08T11:59:00Z",
                "age_seconds": 12.0,
            },
            firecrawl={
                "available": True,
                "reason": None,
                "remaining_credits": 1000,
                "plan_credits": 500000,
                "billing_period_start": "2026-09-01T00:00:00Z",
                "billing_period_end": "2026-10-01T00:00:00Z",
                "checked_at": "2026-09-08T11:59:00Z",
                "age_seconds": 12.0,
            },
            langfuse={
                "available": True,
                "reason": None,
                "exporter": "enabled",
                "environment": "live",
                "project_configured": True,
            },
        ),
        "GET /api/admin/runs/{run_id}/billed": AdminBilledModel(
            available=True,
            reason=None,
            run_id=RUN_ID,
            generations=12,
            billed_usd=0.06441798,
            estimate_usd=0.0562551,
            delta_pct=14.5,
            cost_source_counts={"openrouter-billed": 12},
            session_url=SESSION_URL,
            trace_url=TRACE_URL,
            fetched_at="2026-09-08T12:03:11Z",
        ),
        "POST /api/admin/runs/{run_id}/cancel": {
            "run_id": RUN_ID,
            "status": "cancelling",
            "effect": "asked the run to stop at its next checkpoint",
            "eta_hint": "seconds",
        },
    }


def payload() -> dict[str, Any]:
    body: dict[str, Any] = {
        "_comment": (
            "GENERATED by scripts/emit_admin_fixture.py from the response "
            "models in src/brief_crew/service/admin_api.py. Do not edit. The "
            "VALUES are illustrative; the KEYS are the contract, and "
            "tests/service/test_admin_fixture_shapes.py asserts the real "
            "handlers produce exactly these keys."
        ),
        "_error_note": SPEND_ERROR_NOTE,
        "_unavailable_shape": {
            "_comment": (
                "Every probe and every upstream read degrades to HTTP 200 "
                "with this shape rather than a 500 - plan 17 section 3."
            ),
            "available": False,
            "reason": "OPENROUTER_MANAGEMENT_KEY and OPENROUTER_API_KEY are both unset",
        },
    }
    for endpoint, example in examples().items():
        body[endpoint] = (
            example
            if isinstance(example, dict)
            else example.model_dump(mode="json")
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
        # LF-normalised, for the `core.autocrlf` reason in the module docstring.
        committed = FIXTURE.read_text(encoding="utf-8").replace("\r\n", "\n")
        if committed != text:
            print(
                f"{FIXTURE} is stale; re-run scripts/emit_admin_fixture.py",
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
