"""Deterministic governance findings over already-persisted run evidence.

This module reads metadata only.  It never returns prompts, outputs, gate
replies, model explanations or raw errors, and it performs no network or model
call.  JSON frame details are interpreted in Python for SQLite/PostgreSQL
portability.

Plan 20 added one rule whose evidence is a PERSON rather than a frame -
`rated_bad`, over `runs.rating` - and it obeys the same rule: the word is
metadata and is read, the rater's `rating_note` is free text somebody typed
and is never selected, never joined and never rendered here.
"""

from collections import defaultdict
from typing import Any, Callable

from pydantic import BaseModel, ConfigDict, Field

from brief_crew import config
from brief_crew.service import registry as registry_module

TERMINAL = ("completed", "failed", "cancelled")


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class InsightWorkflow(StrictModel):
    workflow_id: str
    runs: int


class InsightLink(StrictModel):
    session_url: str | None = None
    trace_url: str | None = None


class InsightSample(StrictModel):
    run_id: str
    user_id: str | None
    status: str
    created_at: str
    cost_usd: float
    seq: int | None = None
    gate_id: str | None = None
    langfuse: InsightLink


class InsightFinding(StrictModel):
    rule_id: str
    severity: str
    workflow_id: str
    node_id: str
    gate_id: str | None
    title: str
    explanation: str
    suggestion: str
    affected_runs: int
    total_runs: int
    rate: float
    samples: list[InsightSample] = Field(default_factory=list)


class InsufficientEvidence(StrictModel):
    workflow_id: str
    total_runs: int
    required_runs: int


class InsightThresholds(StrictModel):
    min_runs: int
    min_affected_runs: int


class InsightLabels(StrictModel):
    """How the scanned terminal runs were judged by a person (plan 20).

    Counted over the SAME rows every rule below is counted over, so the strip
    and the findings can never describe different windows. `unrated` is a real
    count and not a remainder the client works out: it is the interesting one
    early on, when it is nearly everything.
    """

    good: int = 0
    bad: int = 0
    unsure: int = 0
    unrated: int = 0


class InsightCoverage(StrictModel):
    runs_scanned: int
    frames_scanned: int
    gates_scanned: int
    runs_missing_frames: int
    runs_with_integrity_loss: int
    retention_days: int
    truncated: bool
    incomplete: bool
    warnings: list[str] = Field(default_factory=list)


class GovernanceInsightsResponse(StrictModel):
    workflows: list[InsightWorkflow] = Field(default_factory=list)
    findings: list[InsightFinding] = Field(default_factory=list)
    insufficient: list[InsufficientEvidence] = Field(default_factory=list)
    thresholds: InsightThresholds
    suppressed_count: int
    labels: InsightLabels = Field(default_factory=InsightLabels)
    coverage: InsightCoverage


#: The node a run-level finding is filed under. A rating is about the whole
#: run and not about anything in it, so inventing a node id would point the
#: console at a card nobody edited; `"(run)"` is parenthesised for the same
#: reason `"(none)"` is in the spend table - it is a label, never an id that
#: could collide with one an author typed.
RUN_LEVEL_NODE = "(run)"

#: A clause appended to one rule's explanation. Only `rated_bad` has one, and
#: it exists because the generic sentence reads identically for a signal a
#: machine observed and for an opinion a person typed - and those are not the
#: same kind of fact to act on.
EXPLANATION_TAILS = {
    "rated_bad": (
        " This one is a person's own judgement of the finished run, typed in "
        "the console - not something the system worked out."
    ),
}


def build_insights(
    rows: list[dict[str, Any]],
    frames: list[dict[str, Any]],
    gates: list[dict[str, Any]],
    *,
    links: Callable[[str], Any],
    outcome_of: Callable[[dict[str, Any]], str | None],
    truncated: bool,
    runs_with_frames: set[str],
) -> dict[str, Any]:
    by_workflow: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_workflow[str(row["workflow_id"])].append(row)
    run_workflow = {str(row["run_id"]): str(row["workflow_id"]) for row in rows}
    events: dict[tuple[str, str, str, str | None], dict[str, dict[str, Any]]] = (
        defaultdict(dict)
    )

    def mark(
        rule: str,
        run_id: str,
        node: str,
        gate_id: str | None = None,
        seq: int | None = None,
    ) -> None:
        workflow = run_workflow.get(run_id)
        if workflow is None:
            return
        events[(workflow, rule, node, gate_id)].setdefault(
            run_id, {"seq": seq, "gate_id": gate_id}
        )

    for row in rows:
        error = row.get("error")
        governed_stop = isinstance(error, str) and error.startswith(
            (
                registry_module.ACCOUNT_CAP_ERROR_PREFIX,
                registry_module.COST_CEILING_ERROR_PREFIX,
            )
        )
        if str(row["status"]) == "failed" and not governed_stop:
            mark("failed_run", str(row["run_id"]), "workflow")
        # Plan 20. The only rule here whose evidence is a person rather than a
        # frame, and the run is still counted by all four of the others: a run
        # somebody disliked that ALSO retried a guardrail is two facts, not
        # one. The rater's note is deliberately not read at any point below -
        # it is free text a person typed, and this response carries metadata.
        if str(row.get("rating") or "") == "bad":
            mark("rated_bad", str(row["run_id"]), RUN_LEVEL_NODE)
    for frame in frames:
        run_id, details = str(frame["run_id"]), dict(frame.get("details") or {})
        retry_count = details.get("retry_count")
        if frame.get("kind") == "guardrail" and details.get("stage") == "after":
            if (
                isinstance(retry_count, int)
                and not isinstance(retry_count, bool)
                and retry_count > 0
            ):
                mark(
                    "guardrail_retry",
                    run_id,
                    str(frame.get("node_id") or "workflow"),
                    seq=int(frame["seq"]),
                )
        if isinstance(details.get("fallback_model"), str) and details["fallback_model"]:
            mark(
                "fallback_model",
                run_id,
                str(frame.get("node_id") or "workflow"),
                seq=int(frame["seq"]),
            )
        if (
            frame.get("kind") == "node_state"
            and details.get("stage") == "retry"
            and isinstance(details.get("model"), str)
            and details["model"]
        ):
            mark(
                "fallback_model",
                run_id,
                str(frame.get("node_id") or "workflow"),
                seq=int(frame["seq"]),
            )
    for gate in gates:
        response = gate.get("response") or {}
        outcome = outcome_of(response)
        if outcome == "revise":
            mark(
                "gate_revise",
                str(gate["run_id"]),
                str(gate.get("node_id") or "workflow"),
                str(gate["gate_id"]),
            )

    definitions = {
        "failed_run": (
            "critical",
            "Runs are failing",
            "Inspect the supporting decisions and traces to locate the failure before choosing a change.",
        ),
        "guardrail_retry": (
            "warning",
            "A guardrail is causing repeated attempts",
            "Review this node's expected output and the guardrail's acceptance criteria.",
        ),
        "fallback_model": (
            "warning",
            "A fallback model is repeatedly attempted",
            "Review the retry and fallback policy for this node and inspect the sample runs.",
        ),
        "gate_revise": (
            "warning",
            "People repeatedly request revisions",
            "Review this gate's requirements and the preceding work in the supporting runs.",
        ),
        "rated_bad": (
            "high",
            "People marked these runs as bad",
            "Open the supporting runs and look at what they produced before choosing a change.",
        ),
    }
    row_by_id = {str(row["run_id"]): row for row in rows}
    findings: list[dict[str, Any]] = []
    suppressed_count = 0
    for (workflow, rule, node, gate_id), affected in events.items():
        total = len(by_workflow[workflow])
        if (
            total < config.GOVERNANCE_INSIGHTS_MIN_RUNS
            or len(affected) < config.GOVERNANCE_INSIGHTS_MIN_AFFECTED
        ):
            suppressed_count += 1
            continue
        severity, title, suggestion = definitions[rule]
        samples = []
        for run_id in sorted(
            affected, key=lambda rid: row_by_id[rid]["created_at"], reverse=True
        )[: config.GOVERNANCE_INSIGHTS_SAMPLE_RUNS]:
            row, evidence = row_by_id[run_id], affected[run_id]
            link = links(run_id)
            samples.append(
                {
                    "run_id": run_id,
                    "user_id": row.get("user_id"),
                    "status": row["status"],
                    "created_at": row["created_at"].isoformat(),
                    "cost_usd": float(row["cost_usd"]),
                    "seq": evidence["seq"],
                    "gate_id": evidence["gate_id"],
                    "langfuse": link.model_dump(),
                }
            )
        count = len(affected)
        qualifier = "At least " if truncated else ""
        findings.append(
            {
                "rule_id": rule,
                "severity": severity,
                "workflow_id": workflow,
                "node_id": node,
                "gate_id": gate_id,
                "title": title,
                "explanation": (
                    f"{qualifier}{count} of {total} sampled terminal runs "
                    f"({round(count / total * 100, 1)}%) matched this rule."
                    + EXPLANATION_TAILS.get(rule, "")
                ),
                "suggestion": suggestion,
                "affected_runs": count,
                "total_runs": total,
                "rate": round(count / total, 4),
                "samples": samples,
            }
        )
    # `high` sits between `critical` and `warning`: a person saying a run was
    # bad is a stronger signal than a retry and a weaker one than a crash.
    rank = {"critical": 0, "high": 1, "warning": 2, "info": 3}
    findings.sort(
        key=lambda item: (
            rank[item["severity"]],
            -item["rate"],
            -item["affected_runs"],
            item["workflow_id"],
            item["rule_id"],
            item["node_id"],
        )
    )
    insufficient = [
        {
            "workflow_id": workflow,
            "total_runs": len(items),
            "required_runs": config.GOVERNANCE_INSIGHTS_MIN_RUNS,
        }
        for workflow, items in sorted(by_workflow.items())
        if len(items) < config.GOVERNANCE_INSIGHTS_MIN_RUNS
    ]
    labels = {"good": 0, "bad": 0, "unsure": 0, "unrated": 0}
    for row in rows:
        value = row.get("rating")
        labels[value if value in ("good", "bad", "unsure") else "unrated"] += 1
    missing = len({str(row["run_id"]) for row in rows} - runs_with_frames)
    loss = sum(
        1
        for row in rows
        if int(row.get("dropped_frames") or 0) + int(row.get("frame_gaps") or 0) > 0
    )
    warnings = []
    if truncated:
        warnings.append(
            "A run, frame, or gate scan limit was reached; findings cover bounded evidence only."
        )
    if missing:
        warnings.append(f"{missing} sampled run(s) have no persisted frames.")
    if loss:
        warnings.append(
            f"{loss} sampled run(s) report dropped frames or sequence gaps."
        )
    if int(config.VALIDATOR_RUN_RETENTION_DAYS) > 0:
        warnings.append(
            "Frame retention is enabled; older evidence may have been purged."
        )
    return {
        "workflows": [
            {"workflow_id": key, "runs": len(value)}
            for key, value in sorted(by_workflow.items())
        ],
        "findings": findings,
        "insufficient": insufficient,
        "thresholds": {
            "min_runs": config.GOVERNANCE_INSIGHTS_MIN_RUNS,
            "min_affected_runs": config.GOVERNANCE_INSIGHTS_MIN_AFFECTED,
        },
        "suppressed_count": suppressed_count,
        "labels": labels,
        "coverage": {
            "runs_scanned": len(rows),
            "frames_scanned": len(frames),
            "gates_scanned": len(gates),
            "runs_missing_frames": missing,
            "runs_with_integrity_loss": loss,
            "retention_days": int(config.VALIDATOR_RUN_RETENTION_DAYS),
            "truncated": truncated,
            "incomplete": bool(warnings),
            "warnings": warnings,
        },
    }
