"""`/api/admin/improve` - test a change, keep what worked, ask a model to read it.

Plan 21, step 4 of the loop. Steps 1-3 are live: a run records what happened
(plan 17), a person says whether it was any good (plan 20), and the console
mines many runs at once (plan 19). This module answers the question those three
set up and none of them can - **did the change help** - and the three surfaces
it answers it with:

* **Where runs go wrong** (`/improve/hotspots`): five ranked lists over one
  workflow's window - per agent, per tool, per error class, per gate, per
  route - and the outcomes they produced.
* **Compare two versions** (`/improve/compare`): two arms, six measures, `n` on
  the row. An arm under `IMPROVE_MIN_COMPARE_RUNS` is SHOWN and FLAGGED.
* **Export rated runs** (`/export/evalset`): the runs people rated, as one
  redacted NDJSON file with a header sentence saying what is in it.

and one that spends money, behind one click and one knob that defaults off:
**Ask a model to review** (`/improve/digests`), whose prompt is built by
`service/digest.py` from structural counts alone.

WHAT THIS MODULE IMPORTS RATHER THAN RESTATES
---------------------------------------------
Every helper below the router comes from `admin_api` - `require_admin`,
`_window`, `gate_outcome`, `median_or_none`, `_verdict_of`, `_money`, `_iso`.
Plan 17's window defaults, its `ADMIN_MAX_SCAN_ROWS` cap and its `truncated`
flag are therefore inherited rather than reimplemented, and a reworded refusal
moves in one place. `admin_frames_by_kind` and `admin_gate_window` are EXTENDED
rather than duplicated: every call site that predates this module passes
neither new argument and is unchanged.

THREE RULES, ALL OF THEM PLAN 17'S, AND THE FIRST IS ABSOLUTE
-------------------------------------------------------------
* **No JSON path is ever written in SQL.** `->>` on PostgreSQL and
  `json_extract` on SQLite are different spellings of the same idea and this
  repository runs both. Every `details`, every gate `request` and `response`
  comes back as a column and is read in Python.
* **404, never 403.** `require_admin` raises FastAPI's own unknown-route body
  byte for byte, so an admin route and a route that does not exist are
  indistinguishable.
* **Cost comes from `run_node_metrics.cost_usd`**, a `Numeric` column, never
  from the `usage` JSON - and every dollar on screen carries plan 17's error
  band, because the estimate was measured -14.5 % to +9.95 % against billed.

THE THREE RULINGS THIS MODULE RECORDS
-------------------------------------
**R3 - the eval set.** It is the most privacy-sensitive artifact this
repository produces: an idea, the model's answer and a human's edit in one
file. It carries user content BY DESIGN, because an eval set needs the input
and the outcome, on four conditions all implemented in `evalset_lines` and
`evalset_ndjson`: every free-text field passes through the existing
`events/redaction.py` **and** the credential scrub the exporter already uses;
the route is admin-only (404 to anyone else); the first line is a header saying
the file contains user-typed content; and it is capped on BOTH axes - rows and
bytes - with a `_truncated` trailer rather than a 500. Redaction is **key-name
based, not a value scan** - it removes a field called `api_key` and it does not
find a key pasted into an idea - which is why the header says so in words
rather than implying a guarantee it cannot make.

**R4 - the model axis is node-scoped.** `node_id` is required and its absence
is a 422. Without it a comparison would put a run in which the escalation tier
ran the Synthesist beside one in which it ran the Reporter and call the
difference a model effect. With it the arms are disjoint - one run, one arm -
and `cost_per_run_usd` is THAT NODE's cost, not the whole run's.

**R5 and the money rule - the review never runs unattended.** Explicit admin
`POST` only: never on page load, never on a `GET`, never on a schedule.
`IMPROVE_DIGEST_ENABLED` defaults off and there is no scheduler, no retry and
no timer anywhere in `service/digest.py`. After the call the MEASURED cost is
compared with `DIGEST_MAX_COST_USD`; the response and the stored row carry
`over_cap`, and a breach logs at WARNING rather than being swallowed.

NO `from __future__ import annotations` here, for the reason `admin_api.py` and
`builder_api.py` both give: FastAPI resolves handler annotations against module
globals, and `Depends`, `Query` and `Response` are imported inside the factory
because FastAPI is an optional dependency of this package.
"""

from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from datetime import datetime, timezone
from decimal import Decimal
import json
import logging
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from brief_crew import config
from brief_crew.service.admin_api import (
    ADMIN_API_PREFIX,
    SPEND_ERROR_NOTE,
    _iso,
    _money,
    _verdict_of,
    _window,
    gate_outcome,
    median_or_none,
)

__all__ = [
    "IMPROVE_API_PREFIX",
    "EVALSET_HEADER_NOTE",
    "ImproveCompareModel",
    "ImproveDigestModel",
    "ImproveDigestsModel",
    "ImproveHotspotsModel",
    "NodeModels",
    "build_hotspots",
    "create_improve_router",
    "evalset_lines",
    "evalset_ndjson",
    "mine_hotspots",
    "resolve_document_version",
]

logger = logging.getLogger(__name__)

#: Under the admin prefix, so `require_admin`'s 404, the CORS middleware, the
#: body limit and the client's own `authedFetch` all reach it unchanged.
IMPROVE_API_PREFIX = ADMIN_API_PREFIX + "/improve"

#: The first line of every eval-set export - R3's third condition.
#: A sentence rather than a flag, because the person who downloads this file is
#: the person who has to decide where to put it.
EVALSET_HEADER_NOTE = (
    "This file contains USER-TYPED CONTENT: run inputs, gate replies a person "
    "edited, rating notes and a slice of each run's report. Every string has "
    "passed this service's redaction, which is KEY-NAME based - it removes a "
    "field called api_key and it does NOT find a credential somebody pasted "
    "into an idea. Treat it as personal data."
)

#: The four words `?rating=` may take. `any` is not a rating - it is the
#: absence of the filter - and it is spelled rather than left to an omitted
#: parameter so a client cannot mean it by accident.
EVALSET_RATINGS = ("good", "bad", "unsure", "any")

#: The two axes a comparison may run on.
COMPARE_AXES = ("version", "model")

#: The arm a run is filed under when its version cannot be PROVED, or when the
#: node under comparison produced no priced call in it. Never merged into a
#: numbered arm: a run whose lineage is unknown is not evidence about either
#: side of the comparison.
UNKNOWN_ARM = "unknown"

#: And the arm for a run whose compared node ran under more than one model -
#: a fallback fired, or the node retried on a second tier. It is named rather
#: than dropped, and rather than counted twice: the run is real evidence about
#: something, and it is not evidence about either model alone.
MIXED_ARM = "mixed"


# ---------------------------------------------------------------------------
# Response models. `extra="forbid"` throughout, for `admin_api`'s reason: a
# field added to a handler without being added here fails in this process
# rather than appearing on the wire and quietly disappearing again.
# ---------------------------------------------------------------------------


class ImproveModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ImproveWindow(ImproveModel):
    """The resolved `?from=`/`?to=` pair, echoed on every mined answer.

    Echoed rather than assumed, because the caller may have named neither and
    a figure quoted for the wrong period is the failure `_window`'s refusal
    above `ADMIN_MAX_WINDOW_DAYS` exists to prevent.
    """

    start: str
    end: str
    days: int


class RatingCounts(ImproveModel):
    good: int = 0
    bad: int = 0
    unsure: int = 0
    unrated: int = 0


class AgentHotspot(ImproveModel):
    """One agent role at one node, with every count a sentence would cite.

    `cost_share` is this node's share of the workflow's cost in the window. It
    is an ESTIMATE like every other dollar here - see `SPEND_ERROR_NOTE` on the
    response - so "try the cheap tier on it" is never a measured saving;
    Compare, axis model, is what measures one.
    """

    agent_role: str
    node_id: str
    #: The name the AUTHOR gave this node, off the graph descriptor. A panel
    #: names it rather than the node id, because `n3_reviewer` is not what
    #: anybody drew - and it falls back to the id when the graph is gone, so a
    #: row is never a blank.
    node_label: str | None = None
    runs: int = 0
    executions: int = 0
    failures: int = 0
    error_classes: list[str] = Field(default_factory=list)
    guardrail_retries: int = 0
    #: Which guardrails retried here. A retry count with no name tells an
    #: author to tighten something unnamed.
    guardrail_names: list[str] = Field(default_factory=list)
    llm_calls: int = 0
    calls_per_execution: float = 0.0
    mean_ms: float | None = None
    cost_usd: float = 0.0
    cost_share: float = 0.0
    #: The SAME token counts priced at `CHEAP_MODEL` - "what if a cheaper model
    #: ran this task" turned into arithmetic with no model call and no second
    #: run.
    #:
    #: `None`, never `0.0`, in the two states where the question has no
    #: answer: this node already ran on the cheap tier, so there is nothing to
    #: swap; or its token split is unknown, so there is nothing to price. A
    #: zero would read as "free on the cheap tier", which is the shape of the
    #: defect that once priced 128,069 real tokens at $0.00.
    #:
    #: It is an ESTIMATE against an ESTIMATE - both sides are `PRICES`, not a
    #: bill - so it bounds the size of the prize and never promises it.
    cheap_tier_cost_usd: float | None = None
    #: Completions the PROVIDER stopped at a length bound (`finish_reason`),
    #: NOT answers this repository's own 2 KB frame preview clipped. The
    #: second is true of almost every long answer and says nothing about
    #: whether the model was cut off.
    truncated_outputs: int = 0


class ToolHotspot(ImproveModel):
    """One tool as one agent used it: how often it answered nothing.

    `empty` counts a tool envelope whose `result_count` is zero or whose
    `tool_status` says it found nothing - the state the first paid run spent
    two of three research branches in, and which read on every panel as an
    absent market rather than as a badly shaped query.
    """

    tool: str
    agent_role: str | None = None
    node_id: str
    node_label: str | None = None
    calls: int = 0
    empty: int = 0
    empty_rate: float = 0.0
    failed: int = 0
    failed_rate: float = 0.0
    from_cache: int = 0
    error_classes: list[str] = Field(default_factory=list)
    queries_sample: list[str] = Field(default_factory=list)


class ErrorHotspot(ImproveModel):
    error_class: str
    count: int = 0
    nodes: list[str] = Field(default_factory=list)
    agent_roles: list[str] = Field(default_factory=list)


class GateHotspot(ImproveModel):
    gate_id: str
    node_id: str
    node_label: str | None = None
    opened: int = 0
    answered: int = 0
    revise: int = 0
    revise_rate: float = 0.0
    expired: int = 0
    median_seconds: float | None = None
    edited_fields: list[str] = Field(default_factory=list)


class RouteHotspot(ImproveModel):
    """A router and the branches it has taken.

    A router with one unique route has either a condition that never varies or
    a dead branch, and the two are different problems with the same shape on
    this row. The row says both rather than picking one, because the data
    cannot tell them apart.
    """

    node_id: str
    node_label: str | None = None
    decisions: int = 0
    routes: dict[str, int] = Field(default_factory=dict)
    unique_routes: int = 0


class TaskHotspot(ImproveModel):
    """One task's completions, and how many finished over a tool failure.

    The only row here that CANNOT be answered for a run recorded before the
    serializer change shipped: `tool_failure_count` did not exist, so
    `completions` counts the frames that carry it rather than every task that
    finished. A window with none reads zero, which is why the panel prints
    `task_completions` beside it - an empty list must never imply a zero.
    """

    task_name: str
    node_id: str
    node_label: str | None = None
    completions: int = 0
    tool_failures: int = 0
    truncated_outputs: int = 0


class VerdictOutcome(ImproveModel):
    verdict: str
    runs: int = 0
    mean_confidence: float | None = None
    cost_usd: float = 0.0
    cost_per_run: float = 0.0


class RatingOutcome(ImproveModel):
    rating: str
    runs: int = 0
    cost_usd: float = 0.0


class StatusOutcome(ImproveModel):
    completed: int = 0
    failed: int = 0
    cancelled: int = 0
    other: int = 0


class Outcomes(ImproveModel):
    by_verdict: list[VerdictOutcome] = Field(default_factory=list)
    by_rating: list[RatingOutcome] = Field(default_factory=list)
    by_status: StatusOutcome = Field(default_factory=StatusOutcome)


class NodeModels(ImproveModel):
    """Which models one node has actually run on, in this window.

    The model axis of a comparison needs a node AND two models, and
    nothing else on this surface says which models a given node has ever
    used - so a picker built without this offers every model the whole
    deployment has ever spent on, most of which produce an empty arm.

    Structural by construction and therefore safe under R2: a node id, the
    name its author gave it, model slugs, and a count. No free text beyond
    the names, which the ruling admits by name.
    """

    node_id: str
    #: The author's own label, falling back to the node id when the graph
    #: is gone - a picker entry is never a blank.
    label: str
    #: Sorted, so two identical loads offer the same order and a picker
    #: cannot reshuffle under somebody reading it.
    models: list[str] = Field(default_factory=list)
    #: DISTINCT runs in which this node produced a priced call - not calls.
    #: It is what tells an author whether a node is worth comparing at all.
    runs: int = 0


class ImproveHotspotsModel(ImproveModel):
    """Five ranked lists over one workflow, and the outcomes they produced."""

    window: ImproveWindow
    workflow_id: str
    runs: int = 0
    min_runs: int = config.IMPROVE_MIN_RUNS
    document_version: int | None = None
    agents: list[AgentHotspot] = Field(default_factory=list)
    tools: list[ToolHotspot] = Field(default_factory=list)
    errors: list[ErrorHotspot] = Field(default_factory=list)
    gates: list[GateHotspot] = Field(default_factory=list)
    routes: list[RouteHotspot] = Field(default_factory=list)
    outcomes: Outcomes = Field(default_factory=Outcomes)
    tasks: list[TaskHotspot] = Field(default_factory=list)
    #: The total across `tasks`, and the honest "can this layer see tool
    #: failures yet" number for this workflow. It needs the serializer change,
    #: so it reads 0 for a window of historic runs.
    task_completions: int = 0
    task_tool_failures: int = 0
    rated: int = 0
    rating_mix: RatingCounts = Field(default_factory=RatingCounts)
    verdicts: int = 0
    low_confidence: int = 0
    mean_confidence: float | None = None
    sample_run_ids: list[str] = Field(default_factory=list)
    #: The model picker's own data, nodes by descending run count. Off the
    #: SAME `run_node_metrics` rows every dollar here comes from, so a node
    #: offered for comparison is one that really has priced calls.
    node_models: list[NodeModels] = Field(default_factory=list)
    estimate: bool = True
    error_note: str = SPEND_ERROR_NOTE
    truncated: bool = False


class CompareArm(ImproveModel):
    """One side of a comparison, with `n` on the row and never beside it.

    `underpowered` is `n < IMPROVE_MIN_COMPARE_RUNS`, and the arm is still
    returned. Hiding it would leave a reader to conclude the comparison could
    not be made; showing it with the flag lets them disbelieve it.
    """

    key: str
    n: int = 0
    underpowered: bool = True
    status_mix: dict[str, int] = Field(default_factory=dict)
    verdict_mix: dict[str, int] = Field(default_factory=dict)
    mean_confidence: float | None = None
    rating_mix: RatingCounts = Field(default_factory=RatingCounts)
    gate_revise_rate: float | None = None
    median_duration_ms: float | None = None
    #: On the version axis this is the WHOLE run's cost. On the model axis it
    #: is the compared NODE's cost only (R4) - the whole run's would carry
    #: every other node's spend into a figure labelled as one model's.
    cost_per_run_usd: float = 0.0


class ImproveCompareModel(ImproveModel):
    window: ImproveWindow
    workflow_id: str
    axis: str
    node_id: str | None = None
    min_runs: int = config.IMPROVE_MIN_COMPARE_RUNS
    arms: list[CompareArm] = Field(default_factory=list)
    estimate: bool = True
    error_note: str = SPEND_ERROR_NOTE
    truncated: bool = False


class ImproveDigestModel(ImproveModel):
    """One stored review. `body` is MODEL OUTPUT and therefore untrusted.

    It is rendered only through the escape-first `markdown.ts`, never re-fed
    to anything, and never read by any decision this service makes: it is a
    review for a person.
    """

    id: str
    workflow_id: str
    created_by: str | None = None
    window: ImproveWindow
    sample_runs: int = 0
    sample_frames: int = 0
    truncated_sample: bool = False
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    #: MEASURED from a captured `LLMCallCompletedEvent` through
    #: `config.compute_cost_usd` - the same function the token frame uses, so a
    #: review's dollars and a run's dollars mean the same thing. `None` means
    #: the model was not in the price table, never 0.0.
    cost_usd: float | None = None
    max_cost_usd: float = config.DIGEST_MAX_COST_USD
    #: R5. Decided ONCE, from the measured cost against the cap in force at
    #: the moment it was charged, and stored - so a row read back after
    #: somebody lowered the cap still says what was true when it ran.
    over_cap: bool = False
    body: str = ""
    created_at: str


class ImproveDigestsModel(ImproveModel):
    """The stored reviews, and what they have cost between them.

    `total_cost_usd` exists because a review reaches NO other money figure in
    this product: it has no `run_id`, so it appears in no `run_node_metrics`
    row, and every read plan 17 built starts from that table. Without this the
    one thing in this layer that spends money would be the one thing invisible
    to the console that watches spending.
    """

    workflow_id: str
    enabled: bool = False
    #: Summed from `improve_digests.cost_usd`, and never added to run spend.
    #: A `None` row (a model with no price on file) contributes nothing rather
    #: than a zero.
    total_cost_usd: float = 0.0
    model: str = config.CHEAP_MODEL
    max_cost_usd: float = config.DIGEST_MAX_COST_USD
    max_sample_runs: int = config.DIGEST_MAX_SAMPLE_RUNS
    max_sample_frames: int = config.DIGEST_MAX_SAMPLE_FRAMES
    #: R5: the other two bounds, so the panel can state the whole of what one
    #: click may spend before anybody presses it.
    max_input_chars: int = config.DIGEST_MAX_INPUT_CHARS
    max_output_tokens: int = config.DIGEST_MAX_OUTPUT_TOKENS
    #: How many reviews exist for this workflow, whatever `?limit=` returned.
    #: `len(rows)` is the PAGE and would silently become the answer to "how
    #: many reviews have been run" the first time somebody hits the cap -
    #: which is the same conflation `truncated` exists to prevent everywhere
    #: else on this surface.
    total_count: int = 0
    rows: list[ImproveDigestModel] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Reading frames. Every function below takes rows the persistence layer
# selected as COLUMNS and reads their JSON in Python.
# ---------------------------------------------------------------------------


def _window_model(start: datetime, end: datetime) -> ImproveWindow:
    return ImproveWindow(
        start=_iso(start) or "",
        end=_iso(end) or "",
        days=max(0, (end - start).days),
    )


def _node_labels(workflow_id: str) -> dict[str, dict[str, str]]:
    """`{node_id: {label, agent_role, task_name}}` off the graph descriptor.

    Both hand-written flows and every published builder graph are in `GRAPHS`,
    so one lookup covers all three kinds. An unregistered or deleted workflow
    yields `{}` and every row falls back to the node id - a count about a graph
    somebody has since unpublished is still a true count.
    """

    from brief_crew.service.graph import GRAPHS

    descriptor = GRAPHS.get(workflow_id)
    if descriptor is None:
        return {}
    labels: dict[str, dict[str, str]] = {}
    for node in getattr(descriptor, "nodes", ()):
        labels[node.id] = {
            "label": getattr(node, "label", "") or node.id,
            "agent_role": getattr(node, "agent_role", "") or "",
            "task_name": getattr(node, "task_name", "") or "",
        }
    return labels


def _detail_str(details: Mapping[str, Any], key: str) -> str:
    value = details.get(key)
    return value.strip() if isinstance(value, str) and value.strip() else ""


def _is_agent_execution(details: Mapping[str, Any]) -> bool:
    """Whether an `agent` frame is an AGENT executing, not a task or a crew.

    Measured off the frame vocabulary rather than off the message: the
    serializer's agent-execution branches carry a `task` key and its task and
    crew branches do not. Without this every execution would be counted at
    least twice - once for the agent and once for the task around it - and
    every per-execution rate in this module would be halved.
    """

    return "task" in details


def gate_pairs(
    request: Mapping[str, Any] | None, response: Mapping[str, Any] | None
) -> list[dict[str, Any]]:
    """The machine's proposal beside the human's correction, key by key.

    `run_gates.request` is a `GatePrompt` whose `fields` are what the system
    PROPOSED; `response.fields` is what a person left there. The pair is more
    informative than either half: a reply showing "independent clinics" says
    what was accepted, and only the pair says it was changed.

    Keys come from the REQUEST, because the proposal defines the form. A key
    only the reply carries is appended after, so an operator who added a field
    is not silently dropped.
    """

    proposed: dict[str, Any] = {}
    if isinstance(request, Mapping):
        raw = request.get("fields")
        if isinstance(raw, Mapping):
            proposed = {str(key): raw[key] for key in raw}
    corrected: dict[str, Any] = {}
    if isinstance(response, Mapping):
        raw = response.get("fields")
        if isinstance(raw, Mapping):
            corrected = {str(key): raw[key] for key in raw}
    keys = list(proposed) + [key for key in corrected if key not in proposed]
    pairs: list[dict[str, Any]] = []
    for key in keys:
        before = proposed.get(key)
        after = corrected.get(key)
        pairs.append(
            {
                "key": key,
                "proposed": None if before is None else str(before),
                "corrected": None if after is None else str(after),
                # A reply that did not answer this field at all is NOT a
                # change: the gate closed without it, and calling that an edit
                # would count every unanswered field as a correction.
                "changed": after is not None and str(before or "") != str(after),
            }
        )
    return pairs


def _rating_counts(rows: Sequence[Mapping[str, Any]]) -> RatingCounts:
    counts = RatingCounts()
    for row in rows:
        rating = row.get("rating")
        if rating == "good":
            counts.good += 1
        elif rating == "bad":
            counts.bad += 1
        elif rating == "unsure":
            counts.unsure += 1
        else:
            counts.unrated += 1
    return counts


def mine_hotspots(
    *,
    window: ImproveWindow,
    workflow_id: str,
    runs: Sequence[Mapping[str, Any]],
    frames: Sequence[Mapping[str, Any]],
    gates: Sequence[Mapping[str, Any]],
    node_costs: Sequence[Mapping[str, Any]],
    document_version: int | None = None,
    truncated: bool = False,
) -> ImproveHotspotsModel:
    """Five ranked lists and the outcomes they produced, all in Python.

    A free function rather than a method on the router: this is the one place
    the counts are computed, and a test can hand it rows without a database.
    """

    labels = _node_labels(workflow_id)

    agents: dict[tuple[str, str], dict[str, Any]] = {}
    tools: dict[tuple[str, str], dict[str, Any]] = {}
    tasks: dict[tuple[str, str], dict[str, Any]] = {}
    errors: dict[str, dict[str, Any]] = {}
    routes: dict[str, dict[str, Any]] = {}
    verdict_rows: list[tuple[str, float | None, str]] = []

    def agent_bucket(node_id: str, role: str) -> dict[str, Any]:
        key = (role, node_id)
        bucket = agents.get(key)
        if bucket is None:
            bucket = {
                "agent_role": role,
                "node_id": node_id,
                "node_label": labels.get(node_id, {}).get("label") or node_id,
                "runs": set(),
                "executions": 0,
                "failures": 0,
                "error_classes": {},
                "guardrail_retries": 0,
                "guardrail_names": {},
                "llm_calls": 0,
            }
            agents[key] = bucket
        return bucket

    def note_error(error_class: str, node_id: str, role: str) -> None:
        bucket = errors.setdefault(
            error_class,
            {
                "error_class": error_class,
                "count": 0,
                "nodes": set(),
                "agent_roles": set(),
            },
        )
        bucket["count"] += 1
        if node_id:
            bucket["nodes"].add(node_id)
        if role:
            bucket["agent_roles"].add(role)

    # A pre-pass, so the answer does not depend on the order frames arrive in.
    # `finish_reason` is on the LLM after-frame and a task completion is a
    # different frame in a different kind, so "was this node's answer cut
    # short" cannot be decided inside a single ordered walk without assuming
    # one comes before the other.
    length_stopped: set[tuple[str, str]] = set()
    truncated_by_node: dict[str, int] = {}
    for frame in frames:
        details = frame.get("details") or {}
        if not isinstance(details, Mapping):
            continue
        if str(frame.get("kind") or "") != "llm":
            continue
        if _detail_str(details, "stage") != "after":
            continue
        if not config.finish_reason_is_truncation(details.get("finish_reason")):
            continue
        node_id = str(frame.get("node_id") or "")
        truncated_by_node[node_id] = truncated_by_node.get(node_id, 0) + 1
        length_stopped.add((str(frame.get("run_id") or ""), node_id))

    for frame in frames:
        details = frame.get("details") or {}
        if not isinstance(details, Mapping):
            continue
        kind = str(frame.get("kind") or "")
        node_id = str(frame.get("node_id") or "")
        stage = _detail_str(details, "stage")
        role = _detail_str(details, "agent_role") or labels.get(node_id, {}).get(
            "agent_role", ""
        )
        run_id = frame.get("run_id")
        error_class = _detail_str(details, "error_class") or _detail_str(
            details, "error_type"
        )

        if kind == "agent":
            if _is_agent_execution(details):
                bucket = agent_bucket(node_id, role or node_id)
                if run_id:
                    bucket["runs"].add(run_id)
                if stage == "before":
                    bucket["executions"] += 1
                elif stage == "error":
                    bucket["failures"] += 1
                    if error_class:
                        bucket["error_classes"][error_class] = (
                            bucket["error_classes"].get(error_class, 0) + 1
                        )
                        note_error(error_class, node_id, role)
            elif stage == "after" and "tool_failure_count" in details:
                # A TASK completion carrying the serializer's tool-failure
                # pair. A run recorded before that shipped produces none,
                # which is why `task_completions` is reported beside these
                # rows rather than left to an empty list.
                task_name = (
                    _detail_str(details, "task_name")
                    or labels.get(node_id, {}).get("task_name")
                    or node_id
                )
                task = tasks.setdefault(
                    (task_name, node_id),
                    {
                        "task_name": task_name,
                        "node_id": node_id,
                        "node_label": labels.get(node_id, {}).get("label") or node_id,
                        "completions": 0,
                        "tool_failures": 0,
                        "truncated_outputs": 0,
                    },
                )
                task["completions"] += 1
                try:
                    if int(details.get("tool_failure_count") or 0) > 0:
                        task["tool_failures"] += 1
                except (TypeError, ValueError):
                    pass
                # The provider's own `finish_reason` on this node in this run,
                # never a comparison against this repository's frame bound.
                if (str(run_id or ""), node_id) in length_stopped:
                    task["truncated_outputs"] += 1
            continue

        if kind == "tool":
            tool_name = _detail_str(details, "tool") or "tool"
            bucket = tools.setdefault(
                (tool_name, node_id),
                {
                    "tool": tool_name,
                    "agent_role": role or None,
                    "node_id": node_id,
                    "node_label": labels.get(node_id, {}).get("label") or node_id,
                    "calls": 0,
                    "empty": 0,
                    "failed": 0,
                    "from_cache": 0,
                    "queries": [],
                    "error_classes": {},
                },
            )
            query = _detail_str(details, "query")
            if query and query not in bucket["queries"]:
                bucket["queries"].append(query)
            # A call is COUNTED when it ends, not when it starts: a tool that
            # began and never finished has no outcome, and counting it would
            # make every rate here smaller than the truth.
            if stage == "error":
                bucket["calls"] += 1
                bucket["failed"] += 1
                if error_class:
                    bucket["error_classes"][error_class] = (
                        bucket["error_classes"].get(error_class, 0) + 1
                    )
                    note_error(error_class, node_id, role)
            elif stage == "after":
                bucket["calls"] += 1
                if details.get("from_cache"):
                    bucket["from_cache"] += 1
                if details.get("failure"):
                    bucket["failed"] += 1
                count = details.get("result_count")
                status = _detail_str(details, "tool_status").lower()
                if (isinstance(count, int) and count == 0) or status in (
                    "empty",
                    "no_results",
                ):
                    bucket["empty"] += 1
            continue

        if kind == "llm":
            if stage == "before":
                agent_bucket(node_id, role or node_id)["llm_calls"] += 1
            elif stage == "after" and config.finish_reason_is_truncation(
                details.get("finish_reason")
            ):
                # The COUNT comes from the pre-pass above, which is order
                # independent; this call exists so a node whose only evidence
                # is a length-stopped call still has a row to carry it.
                agent_bucket(node_id, role or node_id)
            elif stage == "error" and error_class:
                note_error(error_class, node_id, role)
            continue

        if kind == "guardrail" and stage == "after":
            if not details.get("success"):
                bucket = agent_bucket(node_id, role or node_id)
                bucket["guardrail_retries"] += 1
                name = _detail_str(details, "guardrail")
                if name:
                    bucket["guardrail_names"][name] = (
                        bucket["guardrail_names"].get(name, 0) + 1
                    )
            continue

        if kind == "edge_taken":
            route = _detail_str(details, "route")
            if not route:
                continue
            bucket = routes.setdefault(
                node_id,
                {
                    "node_id": node_id,
                    "node_label": labels.get(node_id, {}).get("label") or node_id,
                    "decisions": 0,
                    "routes": {},
                },
            )
            bucket["decisions"] += 1
            bucket["routes"][route] = bucket["routes"].get(route, 0) + 1
            continue

        if kind == "error":
            if error_class:
                note_error(error_class, node_id, role)
            continue

        if kind == "verdict":
            verdict = _verdict_of(details)
            if not verdict:
                continue
            confidence = details.get("confidence")
            verdict_rows.append(
                (
                    verdict,
                    float(confidence) if isinstance(confidence, (int, float)) else None,
                    str(run_id or ""),
                )
            )

    # --- money, from the Numeric column and never from the usage JSON -----
    cost_by_node: dict[str, Decimal] = {}
    elapsed_by_node: dict[str, int] = {}
    cost_by_run: dict[str, Decimal] = {}
    for row in node_costs:
        node_id = str(row["node_id"])
        amount = Decimal(str(row["cost_usd"] or 0))
        cost_by_node[node_id] = cost_by_node.get(node_id, Decimal("0")) + amount
        elapsed_by_node[node_id] = elapsed_by_node.get(node_id, 0) + int(
            row.get("elapsed_ms") or 0
        )
        run_id = str(row["run_id"])
        cost_by_run[run_id] = cost_by_run.get(run_id, Decimal("0")) + amount
    total_cost = sum(cost_by_node.values(), Decimal("0"))

    agent_rows: list[AgentHotspot] = []
    for bucket in agents.values():
        node_id = bucket["node_id"]
        executions = bucket["executions"]
        node_cost = cost_by_node.get(node_id, Decimal("0"))
        elapsed = elapsed_by_node.get(node_id, 0)
        agent_rows.append(
            AgentHotspot(
                agent_role=bucket["agent_role"],
                node_id=node_id,
                node_label=bucket["node_label"],
                runs=len(bucket["runs"]),
                executions=executions,
                failures=bucket["failures"],
                error_classes=_ranked(bucket["error_classes"]),
                guardrail_retries=bucket["guardrail_retries"],
                guardrail_names=_ranked(bucket["guardrail_names"]),
                llm_calls=bucket["llm_calls"],
                calls_per_execution=(
                    round(bucket["llm_calls"] / executions, 3) if executions else 0.0
                ),
                mean_ms=(round(elapsed / executions, 1) if executions else None),
                cost_usd=_money(node_cost),
                cost_share=(
                    round(float(node_cost / total_cost), 4) if total_cost else 0.0
                ),
                cheap_tier_cost_usd=_cheap_tier_cost(node_costs, node_id),
                truncated_outputs=truncated_by_node.get(node_id, 0),
            )
        )
    agent_rows.sort(key=lambda row: (-row.cost_usd, -row.executions, row.node_id))

    tool_rows = [
        ToolHotspot(
            tool=bucket["tool"],
            agent_role=bucket["agent_role"],
            node_id=bucket["node_id"],
            node_label=bucket["node_label"],
            calls=bucket["calls"],
            empty=bucket["empty"],
            empty_rate=_rate(bucket["empty"], bucket["calls"]),
            failed=bucket["failed"],
            failed_rate=_rate(bucket["failed"], bucket["calls"]),
            from_cache=bucket["from_cache"],
            error_classes=_ranked(bucket["error_classes"]),
            queries_sample=bucket["queries"][:4],
        )
        for bucket in tools.values()
    ]
    tool_rows.sort(key=lambda row: (-row.calls, row.tool))

    error_rows = [
        ErrorHotspot(
            error_class=bucket["error_class"],
            count=bucket["count"],
            nodes=sorted(bucket["nodes"]),
            agent_roles=sorted(bucket["agent_roles"]),
        )
        for bucket in errors.values()
    ]
    error_rows.sort(key=lambda row: (-row.count, row.error_class))

    gate_rows = _gate_hotspots(gates, labels)
    route_rows = [
        RouteHotspot(
            node_id=bucket["node_id"],
            node_label=bucket["node_label"],
            decisions=bucket["decisions"],
            routes=dict(bucket["routes"]),
            unique_routes=len(bucket["routes"]),
        )
        for bucket in routes.values()
    ]
    route_rows.sort(key=lambda row: (-row.decisions, row.node_id))

    task_rows = [
        TaskHotspot(
            task_name=bucket["task_name"],
            node_id=bucket["node_id"],
            node_label=bucket["node_label"],
            completions=bucket["completions"],
            tool_failures=bucket["tool_failures"],
            truncated_outputs=bucket["truncated_outputs"],
        )
        for bucket in tasks.values()
    ]
    task_rows.sort(key=lambda row: (-row.completions, row.task_name))

    outcomes = _outcomes(runs, verdict_rows, cost_by_run)
    rated = [row for row in runs if row.get("rating")]
    confidences = [value for _verdict, value, _run in verdict_rows if value is not None]

    return ImproveHotspotsModel(
        window=window,
        workflow_id=workflow_id,
        runs=len(runs),
        document_version=document_version,
        agents=agent_rows,
        tools=tool_rows,
        errors=error_rows,
        gates=gate_rows,
        routes=route_rows,
        outcomes=outcomes,
        tasks=task_rows,
        task_completions=sum(row.completions for row in task_rows),
        task_tool_failures=sum(row.tool_failures for row in task_rows),
        rated=len(rated),
        rating_mix=_rating_counts(runs),
        verdicts=len(verdict_rows),
        low_confidence=sum(1 for value in confidences if value < 0.35),
        mean_confidence=(
            round(sum(confidences) / len(confidences), 3) if confidences else None
        ),
        sample_run_ids=[
            row["run_id"]
            for row in sorted(
                rated, key=lambda item: _money(cost_by_run.get(item["run_id"], 0))
            )[:3]
        ],
        node_models=_node_models(node_costs, labels),
        truncated=truncated,
    )


def _node_models(
    node_costs: Sequence[Mapping[str, Any]],
    labels: Mapping[str, Mapping[str, str]],
) -> list[NodeModels]:
    """`{node_id, label, models, runs}` off the metric rows already read.

    No second query: `improve_node_costs` is `run_node_metrics` scoped to
    the runs `improve_runs` selected for this workflow and window under
    `ADMIN_MAX_SCAN_ROWS`, so this inherits that bound rather than opening
    a second scan with a second cap to keep in step.

    A row with no model is skipped rather than filed under `""`: an empty
    slug is not a model somebody can pick, and offering one would put an
    arm on the page that can never have a name.
    """

    buckets: dict[str, dict[str, Any]] = {}
    for row in node_costs:
        node_id = str(row.get("node_id") or "")
        model = str(row.get("model") or "")
        if not node_id or not model:
            continue
        bucket = buckets.setdefault(
            node_id, {"models": set(), "runs": set()}
        )
        bucket["models"].add(model)
        bucket["runs"].add(str(row.get("run_id") or ""))
    rows = [
        NodeModels(
            node_id=node_id,
            label=labels.get(node_id, {}).get("label") or node_id,
            models=sorted(bucket["models"]),
            runs=len(bucket["runs"]),
        )
        for node_id, bucket in buckets.items()
    ]
    # Busiest first, then by id so the order is stable across two loads.
    rows.sort(key=lambda row: (-row.runs, row.node_id))
    return rows


def _gate_hotspots(
    gates: Sequence[Mapping[str, Any]], labels: Mapping[str, Mapping[str, str]]
) -> list[GateHotspot]:
    buckets: dict[str, dict[str, Any]] = {}
    for gate in gates:
        gate_id = str(gate.get("gate_id") or "gate")
        node_id = str(gate.get("node_id") or "")
        bucket = buckets.setdefault(
            gate_id,
            {
                "gate_id": gate_id,
                "node_id": node_id,
                "node_label": labels.get(node_id, {}).get("label") or node_id,
                "opened": 0,
                "answered": 0,
                "revise": 0,
                "expired": 0,
                "seconds": [],
                "edited": {},
            },
        )
        bucket["opened"] += 1
        if str(gate.get("status") or "") == "expired":
            bucket["expired"] += 1
        answered_at = gate.get("answered_at")
        if answered_at is None:
            continue
        bucket["answered"] += 1
        opened_at = gate.get("opened_at")
        if opened_at is not None:
            bucket["seconds"].append((answered_at - opened_at).total_seconds())
        if gate_outcome(gate.get("response")) == "revise":
            bucket["revise"] += 1
        for pair in gate_pairs(gate.get("request"), gate.get("response")):
            if pair["changed"]:
                bucket["edited"][pair["key"]] = bucket["edited"].get(pair["key"], 0) + 1
    rows = [
        GateHotspot(
            gate_id=bucket["gate_id"],
            node_id=bucket["node_id"],
            node_label=bucket["node_label"],
            opened=bucket["opened"],
            answered=bucket["answered"],
            revise=bucket["revise"],
            revise_rate=_rate(bucket["revise"], bucket["answered"]),
            expired=bucket["expired"],
            median_seconds=median_or_none(bucket["seconds"]),
            edited_fields=_ranked(bucket["edited"]),
        )
        for bucket in buckets.values()
    ]
    rows.sort(key=lambda row: (-row.opened, row.gate_id))
    return rows


def _outcomes(
    runs: Sequence[Mapping[str, Any]],
    verdicts: Sequence[tuple[str, float | None, str]],
    cost_by_run: Mapping[str, Decimal],
) -> Outcomes:
    by_verdict: dict[str, dict[str, Any]] = {}
    for verdict, confidence, run_id in verdicts:
        bucket = by_verdict.setdefault(
            verdict, {"runs": 0, "confidences": [], "cost": Decimal("0")}
        )
        bucket["runs"] += 1
        if confidence is not None:
            bucket["confidences"].append(confidence)
        bucket["cost"] += cost_by_run.get(run_id, Decimal("0"))
    verdict_rows = [
        VerdictOutcome(
            verdict=verdict,
            runs=bucket["runs"],
            mean_confidence=(
                round(sum(bucket["confidences"]) / len(bucket["confidences"]), 3)
                if bucket["confidences"]
                else None
            ),
            cost_usd=_money(bucket["cost"]),
            cost_per_run=(
                round(_money(bucket["cost"]) / bucket["runs"], 6)
                if bucket["runs"]
                else 0.0
            ),
        )
        for verdict, bucket in by_verdict.items()
    ]
    verdict_rows.sort(key=lambda row: (-row.runs, row.verdict))

    by_rating: dict[str, dict[str, Any]] = {}
    status = StatusOutcome()
    for row in runs:
        rating = row.get("rating")
        if rating:
            bucket = by_rating.setdefault(
                str(rating), {"runs": 0, "cost": Decimal("0")}
            )
            bucket["runs"] += 1
            bucket["cost"] += cost_by_run.get(row["run_id"], Decimal("0"))
        name = str(row.get("status") or "")
        if name == "completed":
            status.completed += 1
        elif name == "failed":
            status.failed += 1
        elif name == "cancelled":
            status.cancelled += 1
        else:
            status.other += 1
    rating_rows = [
        RatingOutcome(
            rating=rating, runs=bucket["runs"], cost_usd=_money(bucket["cost"])
        )
        for rating, bucket in sorted(by_rating.items())
    ]
    return Outcomes(by_verdict=verdict_rows, by_rating=rating_rows, by_status=status)


def _ranked(counts: Mapping[str, int], limit: int = 6) -> list[str]:
    """Keys by descending count, then alphabetically - stable, not arbitrary.

    Ties broken by name so two identical loads produce the same order, which
    is the property that stops a panel reshuffling under somebody reading it.
    """

    return [
        key
        for key, _count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ][:limit]


def _cheap_tier_cost(
    node_costs: Sequence[Mapping[str, Any]], node_id: str
) -> float | None:
    """This node's own token counts, priced at `CHEAP_MODEL`. `None` if moot.

    "What if a cheaper model ran this task" has, for one very specific version
    of the question, an answer this data already holds: the same prompt and
    completion token counts, at the cheap tier's published rate. No model call,
    no second run, no guess.

    Three honest limits, and each is why the value is `None` rather than a
    number in its own case:

    * **Already cheap.** Every metric row for this node is `CHEAP_MODEL`
      already, so there is nothing to swap and a figure would only repeat
      `cost_usd`.
    * **Tokens unknown.** A row with no prompt or completion tokens cannot be
      repriced, and `0.0` would say "free", which is the defect that once
      priced 128,069 real tokens at nothing.
    * **The model has no price on file.** `compute_cost_usd` answers `None`,
      and that is passed through rather than turned into a zero.

    And the limit no `None` can express: a cheaper model would produce a
    DIFFERENT number of tokens, usually more of them. This bounds the prize;
    Compare, axis model, is what measures it.
    """

    prompt = 0
    completion = 0
    models: set[str] = set()
    for row in node_costs:
        if str(row.get("node_id")) != node_id:
            continue
        models.add(str(row.get("model") or ""))
        prompt += int(row.get("prompt_tokens") or 0)
        completion += int(row.get("completion_tokens") or 0)
    if not models or models == {config.CHEAP_MODEL}:
        return None
    if prompt <= 0 and completion <= 0:
        return None
    priced = config.compute_cost_usd(config.CHEAP_MODEL, prompt, completion)
    return None if priced is None else round(priced, 6)


def _rate(top: int, bottom: int) -> float:
    return round(top / bottom, 3) if bottom else 0.0


def resolve_document_version(
    store: Any,
    document_id: str,
    graph_version: str,
    *,
    user_id: str | None = None,
    cache: dict[str, int | None] | None = None,
) -> int | None:
    """Which stored version has this content hash - for runs written earlier.

    `runs.graph_version` is `sha256({id, version, nodes, edges, start_nodes})`
    truncated to 16 hex, content-addressed on purpose (`descriptor.py`), so
    "v3 versus v4" is a Python step and not a column comparison. Every run
    written from now on carries the integer; this is the ONLY way an older one
    gets an answer.

    The hash is recomputed with the IMPORTED `_descriptor_version`, never a
    second implementation of the same digest: two derivations of one id are
    two answers to "which version is this", and they would disagree the first
    time either changed.

    An unmatched hash returns `None` - grouped `"unknown"` by the caller,
    never merged into an arm it might not belong to. So does a document that
    no longer parses, or a store that cannot answer: a version this function
    cannot prove is not a version it should guess.

    `user_id` is the DOCUMENT'S OWN owner, and it is not optional in practice
    for an owned document: `BuilderDocumentStore.versions` and `.load` refuse a
    caller who does not own the row, and the caller here is an admin who
    usually does not. Plan 17 met this boundary first and answered it the same
    way - `persistence.admin_document_owner` reads the owner, and the store is
    then asked the question it was written to answer rather than bypassed. The
    route reads the owner; this function does not, because a pure lookup that
    also queried for its own authority would be two responsibilities.
    """

    if cache is not None and graph_version in cache:
        return cache[graph_version]
    answer: int | None = None
    try:
        from brief_crew.builder.descriptor import (
            _descriptor_version,
            builder_graph_descriptor,
        )

        for version in store.versions(document_id, user_id=user_id):
            stored = store.load(document_id, version=version, user_id=user_id)
            descriptor = builder_graph_descriptor(stored.document)
            recomputed = _descriptor_version(
                stored.document,
                list(descriptor.nodes),
                list(descriptor.edges),
                list(descriptor.start_nodes),
            )
            if recomputed == graph_version:
                answer = int(version)
                break
    except Exception:  # noqa: BLE001 - an unresolvable version is `unknown`
        answer = None
    if cache is not None:
        cache[graph_version] = answer
    return answer


def build_hotspots(
    persistence,
    *,
    workflow_id: str,
    start: datetime,
    end: datetime,
    document_version: int | None = None,
) -> ImproveHotspotsModel:
    """One workflow's five ranked lists and its outcomes.

    Four reads and no model call: the runs in the window, their frames, their
    gates and their node metrics - each bounded by `ADMIN_MAX_SCAN_ROWS` and
    each reporting `truncated` rather than silently answering over a slice.
    `mine_hotspots` then does every bit of the JSON reading in Python.
    """

    rows, truncated = persistence.improve_runs(
        workflow_id=workflow_id,
        start=start,
        end=end,
        limit=config.ADMIN_MAX_SCAN_ROWS,
    )
    if document_version is not None:
        rows = [row for row in rows if row.get("document_version") == document_version]
    run_ids = [row["run_id"] for row in rows]
    frames, frames_truncated = persistence.admin_frames_by_kind(
        ["agent", "tool", "llm", "guardrail", "error", "verdict", "edge_taken"],
        run_ids=run_ids,
        limit=config.ADMIN_MAX_SCAN_ROWS,
    )
    gates, gates_truncated = persistence.admin_gate_window(
        run_ids=run_ids, limit=config.ADMIN_MAX_SCAN_ROWS
    )
    return mine_hotspots(
        window=_window_model(start, end),
        workflow_id=workflow_id,
        runs=rows,
        frames=frames,
        gates=gates,
        node_costs=persistence.improve_node_costs(run_ids),
        document_version=document_version,
        truncated=bool(truncated or frames_truncated or gates_truncated),
    )


# ---------------------------------------------------------------------------
# The router
# ---------------------------------------------------------------------------


def create_improve_router(
    *,
    resolve_user: Callable[..., Any],
    persistence_factory: Callable[[], Any],
    store_factory: Callable[[], Any],
) -> Any:
    """The `/api/admin/improve` router, closed over the app's dependencies.

    A factory rather than a module-level `APIRouter`, matching
    `create_admin_router` and `create_builder_router`: the persistence and the
    user dependency are per-application.

    `resolve_user` is `optional_user` and NOT `current_user`, for exactly the
    reason plan 17 criterion 4 gives on the admin router: `current_user`
    raises 401 first when authentication is required, which would make an
    admin route answer differently from an unknown path - the one property
    this gate exists to deny.
    """

    from fastapi import APIRouter, Depends, HTTPException, Query
    from fastapi.responses import StreamingResponse

    from brief_crew.service.auth import require_admin

    # `ADMIN_API_PREFIX`, not `IMPROVE_API_PREFIX`, and every path below
    # spells its own `/improve` or `/export`. One router and one mount,
    # because the eval-set export lives at `/api/admin/export/evalset` while
    # everything else lives under `/improve` - and two routers to serve two
    # path segments would be two places to keep `require_admin` in step.
    router = APIRouter(prefix=ADMIN_API_PREFIX, tags=["improve"])

    def admin(user: Any = Depends(resolve_user)) -> Any:
        return require_admin(user)

    def store() -> Any:
        persistence = persistence_factory()
        if persistence is None:
            raise HTTPException(
                status_code=503,
                detail="this service has no durable store, so there is nothing to read",
            )
        return persistence

    def window(since: str | None, until: str | None) -> tuple[datetime, datetime]:
        try:
            return _window(since, until)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    # -- Where runs go wrong ------------------------------------------------

    @router.get("/improve/hotspots", response_model=ImproveHotspotsModel)
    async def hotspots(
        workflow_id: str = Query(...),
        document_version: int | None = Query(default=None),
        since: str | None = Query(default=None, alias="from"),
        until: str | None = Query(default=None, alias="to"),
        _: Any = Depends(admin),
    ) -> ImproveHotspotsModel:
        """Five ranked lists over ONE workflow, and the outcomes they produced.

        `workflow_id` is required rather than optional, and that is the whole
        of why this is not a console-wide panel. A hot spot is a statement
        about a graph - this node, this tool, this gate - and pooling two
        workflows' nodes into one ranking would put a name beside a count that
        belongs to something else.
        """

        start, end = window(since, until)
        return build_hotspots(
            store(),
            workflow_id=workflow_id,
            start=start,
            end=end,
            document_version=document_version,
        )

    # -- Compare two versions ------------------------------------------------

    @router.get("/improve/compare", response_model=ImproveCompareModel)
    async def compare(
        workflow_id: str = Query(...),
        axis: str = Query(default="version"),
        a: str | None = Query(default=None),
        b: str | None = Query(default=None),
        node_id: str | None = Query(default=None),
        since: str | None = Query(default=None, alias="from"),
        until: str | None = Query(default=None, alias="to"),
        _: Any = Depends(admin),
    ) -> ImproveCompareModel:
        """Did the change help, on six measures, with `n` on every arm.

        `axis=model` groups by `run_node_metrics.model` **scoped to one
        node**, which is the counterfactual this data actually supports -
        "what if a cheaper model ran this task" - and the only one. R4 makes
        `node_id` REQUIRED there: without it a comparison would put a run in
        which the escalation tier ran the Synthesist beside one in which it
        ran the Reporter and call the difference a model effect.

        An arm under `IMPROVE_MIN_COMPARE_RUNS` is returned with
        `underpowered: true` rather than hidden: a difference over three runs
        is noise wearing a number, and hiding the arm would let a reader
        conclude the comparison could not be made at all.

        A HAND-WRITTEN flow has no document and therefore no versions, so the
        version axis answers one `unknown` arm holding every run. That is the
        truth about it rather than an error, and the panel says so in a
        sentence.
        """

        if axis not in COMPARE_AXES:
            raise HTTPException(
                status_code=422, detail="axis must be `version` or `model`"
            )
        if axis == "model" and not node_id:
            raise HTTPException(
                status_code=422,
                detail=(
                    "axis=model needs a node_id: two models compared across a "
                    "whole run measure which node happened to run on which "
                    "tier, not the models"
                ),
            )
        start, end = window(since, until)
        persistence = store()
        rows, truncated = persistence.improve_runs(
            workflow_id=workflow_id,
            start=start,
            end=end,
            limit=config.ADMIN_MAX_SCAN_ROWS,
        )
        run_ids = [row["run_id"] for row in rows]
        node_costs = persistence.improve_node_costs(run_ids)
        frames, frames_truncated = persistence.admin_frames_by_kind(
            ["verdict"], run_ids=run_ids, limit=config.ADMIN_MAX_SCAN_ROWS
        )
        gates, gates_truncated = persistence.admin_gate_window(
            run_ids=run_ids, limit=config.ADMIN_MAX_SCAN_ROWS
        )

        if axis == "version":
            groups = _version_groups(persistence, store_factory, workflow_id, rows)
        else:
            groups = _model_groups(rows, node_costs, node_id or "")

        wanted = [value for value in (a, b) if value]
        if wanted:
            groups = {key: value for key, value in groups.items() if key in wanted}

        arms = [
            _arm(
                key,
                group,
                node_costs,
                frames,
                gates,
                node_id=node_id if axis == "model" else None,
            )
            for key, group in sorted(groups.items())
        ]
        arms.sort(key=lambda arm: (-arm.n, arm.key))
        return ImproveCompareModel(
            window=_window_model(start, end),
            workflow_id=workflow_id,
            axis=axis,
            node_id=node_id,
            arms=arms,
            truncated=bool(truncated or frames_truncated or gates_truncated),
        )

    # -- Ask a model to review ----------------------------------------------

    @router.get("/improve/digests", response_model=ImproveDigestsModel)
    async def list_digests(
        workflow_id: str = Query(...),
        limit: int = Query(default=20, ge=1, le=100),
        _: Any = Depends(admin),
    ) -> ImproveDigestsModel:
        """Stored reviews. **This route spends nothing and calls no model.**

        The read and the write are separate verbs on purpose: a `GET` that
        could generate would be a model call on page load, which is exactly
        what the money rule forbids. Everything a client needs to draw the
        button BEFORE the click - the model, the cap, all four sample bounds
        and whether the knob is on - is on this response.
        """

        persistence = store()
        rows = persistence.list_digests(workflow_id, limit=limit)
        return ImproveDigestsModel(
            workflow_id=workflow_id,
            enabled=config.digest_enabled(),
            total_cost_usd=_money(persistence.digest_cost_total(workflow_id)),
            total_count=persistence.digest_count(workflow_id),
            rows=[_digest_model(row) for row in rows],
        )

    @router.post("/improve/digests", response_model=ImproveDigestModel)
    async def create_digest(
        workflow_id: str = Query(...),
        since: str | None = Query(default=None, alias="from"),
        until: str | None = Query(default=None, alias="to"),
        user: Any = Depends(admin),
    ) -> ImproveDigestModel:
        """The one model call in this plan, and the only one behind a click.

        422 rather than 403 when the knob is off: the request is well formed
        and the caller is allowed, and what is missing is a deployment
        setting. `service/digest.py` raises before constructing an `LLM` at
        all, which a test proves by patching the class to raise.

        R5 is the block after the call: the MEASURED cost is compared with
        `DIGEST_MAX_COST_USD`, the answer rides the response and the stored
        row, and a breach logs at WARNING. A breach cannot be prevented from
        here - the tokens are already spent - so what matters is that it is
        recorded where somebody watching money will see it.
        """

        from brief_crew.service import digest as digest_module

        start, end = window(since, until)
        persistence = store()
        payload = build_hotspots(
            persistence, workflow_id=workflow_id, start=start, end=end
        )
        rows, _truncated = persistence.improve_runs(
            workflow_id=workflow_id,
            start=start,
            end=end,
            limit=config.DIGEST_MAX_SAMPLE_RUNS,
        )
        frames, _frames_truncated = persistence.admin_frames_by_kind(
            list(digest_module.SAMPLE_FRAME_KINDS),
            run_ids=[row["run_id"] for row in rows],
            limit=config.ADMIN_MAX_SCAN_ROWS,
        )
        sample, sample_truncated = digest_module.build_sample(rows, frames)
        try:
            result = digest_module.run_digest(
                workflow_name=_workflow_name(workflow_id),
                window=f"{_iso(start)} to {_iso(end)}",
                hotspots=payload.model_dump(mode="json"),
                # Plan 21 drops the deterministic rules, so there is nothing
                # to hand across. An EMPTY list rather than the key removed,
                # because the prompt names the slot and a missing key would
                # leave a `{lessons_json}` brace in the rendered text.
                lessons=[],
                sample=sample,
                sample_truncated=sample_truncated,
                sample_frames=sum(len(row["frames"]) for row in sample),
            )
        except digest_module.DigestUnavailable as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        over_cap = (
            result.cost_usd is not None
            and result.cost_usd > config.DIGEST_MAX_COST_USD
        )
        if over_cap:
            logger.warning(
                "a model review of %s cost $%.6f, over the $%.2f cap "
                "(DIGEST_MAX_COST_USD); %s prompt / %s completion tokens on %s",
                workflow_id,
                result.cost_usd,
                config.DIGEST_MAX_COST_USD,
                result.prompt_tokens,
                result.completion_tokens,
                result.model,
            )
        stored = persistence.save_digest(
            {
                "id": digest_module.new_digest_id(),
                "workflow_id": workflow_id,
                "created_by": getattr(user, "id", None),
                "window_from": start,
                "window_to": end,
                "sample_runs": result.sample_runs,
                "sample_frames": result.sample_frames,
                "truncated_sample": result.truncated_sample,
                "model": result.model,
                "prompt_tokens": result.prompt_tokens,
                "completion_tokens": result.completion_tokens,
                "cost_usd": result.cost_usd,
                "over_cap": over_cap,
                "body": result.body,
                "created_at": digest_module.utcnow(),
            }
        )
        logger.warning(
            "admin %s generated a model review for %s (%s prompt / %s completion tokens)",
            getattr(user, "email", None) or getattr(user, "id", None),
            workflow_id,
            result.prompt_tokens,
            result.completion_tokens,
        )
        return _digest_model(stored)

    # -- Export rated runs ---------------------------------------------------

    @router.get("/export/evalset")
    async def export_evalset(
        workflow_id: str = Query(...),
        rating: str = Query(default="good"),
        since: str | None = Query(default=None, alias="from"),
        until: str | None = Query(default=None, alias="to"),
        _: Any = Depends(admin),
    ) -> Any:
        """The runs worth learning from, as one file - and the most sensitive
        artifact this repository produces.

        `rating=good` is the runs a person approved; `rating=any` is every run
        in the window with the outcome a human left on it, to check a future
        change against.

        STREAMED, because the alternative is joining up to `EVALSET_MAX_RUNS`
        rows into one string on the event loop, which is the shape audit M13
        found in the log export and fixed there.

        R3 is implemented in `evalset_lines` and `evalset_ndjson` and cited
        there rather than restated: redaction plus the credential scrub on
        every free-text field, admin-only, a header line saying the file holds
        user-typed content, and a cap on rows AND bytes.
        """

        if rating not in EVALSET_RATINGS:
            raise HTTPException(
                status_code=422,
                detail="rating must be `good`, `bad`, `unsure` or `any`",
            )
        start, end = window(since, until)
        persistence = store()
        rows, truncated = persistence.improve_runs(
            workflow_id=workflow_id,
            start=start,
            end=end,
            ratings=None if rating == "any" else [rating],
            limit=config.EVALSET_MAX_RUNS,
        )
        run_ids = [row["run_id"] for row in rows]
        frames, _truncated = persistence.admin_frames_by_kind(
            ["verdict"], run_ids=run_ids, limit=config.MAX_EXPORT_FRAMES
        )
        verdicts = {
            frame["run_id"]: frame["details"]
            for frame in frames
            if isinstance(frame["details"], Mapping)
        }
        gates, _gates_truncated = persistence.admin_gate_window(
            run_ids=run_ids, limit=config.ADMIN_MAX_SCAN_ROWS
        )
        costs: dict[str, Decimal] = {}
        for metric in persistence.improve_node_costs(run_ids):
            costs[metric["run_id"]] = costs.get(
                metric["run_id"], Decimal("0")
            ) + Decimal(str(metric["cost_usd"] or 0))
        lines = evalset_lines(
            workflow_id=workflow_id,
            rating=rating,
            window=_window_model(start, end),
            runs=rows,
            payloads=persistence.improve_run_payloads(run_ids),
            gates=gates,
            verdicts=verdicts,
            costs=costs,
            truncated=truncated,
        )
        return StreamingResponse(
            evalset_ndjson(lines),
            media_type="application/x-ndjson",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="evalset-{workflow_id}-{rating}.ndjson"'
                )
            },
        )

    return router


def _document_store(store_factory: Callable[[], Any]) -> Any:
    try:
        return store_factory()
    except Exception:  # noqa: BLE001 - no document store is `unknown`, not a 500
        return None


def _workflow_name(workflow_id: str) -> str:
    from brief_crew.service.graph import GRAPHS

    descriptor = GRAPHS.get(workflow_id)
    return str(getattr(descriptor, "name", "") or workflow_id)


def _digest_model(row: Mapping[str, Any]) -> "ImproveDigestModel":
    return ImproveDigestModel(
        id=row["id"],
        workflow_id=row["workflow_id"],
        created_by=row.get("created_by"),
        window=_window_model(row["window_from"], row["window_to"]),
        sample_runs=int(row.get("sample_runs") or 0),
        sample_frames=int(row.get("sample_frames") or 0),
        truncated_sample=bool(row.get("truncated_sample")),
        model=str(row.get("model") or ""),
        prompt_tokens=int(row.get("prompt_tokens") or 0),
        completion_tokens=int(row.get("completion_tokens") or 0),
        cost_usd=row.get("cost_usd"),
        over_cap=bool(row.get("over_cap")),
        body=str(row.get("body") or ""),
        created_at=_iso(row.get("created_at")) or "",
    )


def _version_groups(
    persistence: Any,
    store_factory: Callable[[], Any],
    workflow_id: str,
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, list[Mapping[str, Any]]]:
    """Runs by document version, with the unprovable ones kept apart.

    A run written since the lineage column exists carries the integer. An
    older one is resolved by recomputing its content hash against the stored
    versions, and a hash that matches nothing is `"unknown"` - never merged
    into a numbered arm it might not belong to.
    """

    cache: dict[str, int | None] = {}
    document_store = _document_store(store_factory)
    # The document's OWN owner, read once. `store.versions` refuses a caller
    # who does not own the row and the caller here is an admin, so without
    # this every older run would resolve to `"unknown"` - which is the honest
    # answer to "I cannot prove it" and the wrong answer to "I did not ask
    # properly".
    try:
        _exists, owner = persistence.admin_document_owner(workflow_id)
    except Exception:  # noqa: BLE001 - a hand-written flow has no document row
        owner = None
    groups: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        version = row.get("document_version")
        if version is None and document_store is not None:
            version = resolve_document_version(
                document_store,
                workflow_id,
                str(row.get("graph_version") or ""),
                user_id=owner,
                cache=cache,
            )
        groups.setdefault(
            str(version) if version is not None else UNKNOWN_ARM, []
        ).append(row)
    return groups


def _model_groups(
    rows: Sequence[Mapping[str, Any]],
    node_costs: Sequence[Mapping[str, Any]],
    node_id: str,
) -> dict[str, list[Mapping[str, Any]]]:
    """Runs by the model that ran ONE node - R4, and the arms are disjoint.

    One run reaches exactly one arm, which is what makes `n` mean anything: a
    run counted in both arms would inflate both and make every rate on the
    page a weighted average of itself.

    Three cases and each is named rather than dropped. The node ran under one
    model: that model's arm. It ran under several - a fallback fired, or it
    retried on a second tier: `mixed`, because the run is real evidence about
    something and it is not evidence about either model alone. It produced no
    priced call at all in this run: `unknown`, the same word the version axis
    uses for a fact it cannot prove.
    """

    models_by_run: dict[str, set[str]] = {}
    for row in node_costs:
        if str(row.get("node_id") or "") != node_id:
            continue
        name = str(row.get("model") or "")
        if not name:
            continue
        models_by_run.setdefault(str(row["run_id"]), set()).add(name)
    groups: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        models = models_by_run.get(row["run_id"]) or set()
        if len(models) == 1:
            key = next(iter(models))
        elif models:
            key = MIXED_ARM
        else:
            key = UNKNOWN_ARM
        groups.setdefault(key, []).append(row)
    return groups


def _arm(
    key: str,
    rows: Sequence[Mapping[str, Any]],
    node_costs: Sequence[Mapping[str, Any]],
    verdict_frames: Sequence[Mapping[str, Any]],
    gates: Sequence[Mapping[str, Any]],
    *,
    node_id: str | None = None,
) -> "CompareArm":
    """One side of a comparison: six measures, and `n` on the row itself.

    `node_id` scopes the MONEY and nothing else (R4). On the model axis the
    whole run's cost would carry every other node's spend into a figure
    labelled as one model's, which is the error that makes a cheap-tier
    experiment look like it saved nothing.
    """

    run_ids = {row["run_id"] for row in rows}
    cost = Decimal("0")
    for metric in node_costs:
        if metric["run_id"] not in run_ids:
            continue
        if node_id is not None and str(metric.get("node_id") or "") != node_id:
            continue
        cost += Decimal(str(metric["cost_usd"] or 0))

    status_mix: dict[str, int] = {}
    for row in rows:
        name = str(row.get("status") or "")
        status_mix[name] = status_mix.get(name, 0) + 1

    verdict_mix: dict[str, int] = {}
    confidences: list[float] = []
    for frame in verdict_frames:
        if frame["run_id"] not in run_ids:
            continue
        details = frame["details"]
        verdict = _verdict_of(details) if isinstance(details, Mapping) else None
        if not verdict:
            continue
        verdict_mix[verdict] = verdict_mix.get(verdict, 0) + 1
        value = details.get("confidence")
        if isinstance(value, (int, float)):
            confidences.append(float(value))

    answered = 0
    revised = 0
    for gate in gates:
        if gate["run_id"] not in run_ids or gate.get("answered_at") is None:
            continue
        answered += 1
        if gate_outcome(gate.get("response")) == "revise":
            revised += 1

    durations = [
        (row["completed_at"] - row["started_at"]).total_seconds() * 1000
        for row in rows
        if row.get("started_at") and row.get("completed_at")
    ]
    return CompareArm(
        key=key,
        n=len(rows),
        underpowered=len(rows) < config.IMPROVE_MIN_COMPARE_RUNS,
        status_mix=status_mix,
        verdict_mix=verdict_mix,
        mean_confidence=(
            round(sum(confidences) / len(confidences), 3) if confidences else None
        ),
        rating_mix=_rating_counts(rows),
        gate_revise_rate=(round(revised / answered, 3) if answered else None),
        median_duration_ms=median_or_none(durations),
        cost_per_run_usd=(round(_money(cost) / len(rows), 6) if rows else 0.0),
    )


def evalset_lines(
    *,
    workflow_id: str,
    rating: str,
    window: "ImproveWindow",
    runs: Sequence[Mapping[str, Any]],
    payloads: Mapping[str, Mapping[str, Any]],
    gates: Sequence[Mapping[str, Any]],
    verdicts: Mapping[str, Mapping[str, Any]],
    costs: Mapping[str, Decimal],
    truncated: bool = False,
) -> "list[dict[str, Any]]":
    """The NDJSON body, line by line - R3 implemented rather than cited.

    THREE OF THE FOUR CONDITIONS ARE HERE (the fourth, the byte cap, is in
    `evalset_ndjson`, because it is a property of the bytes on the wire and
    not of the rows):

    1. **Every free-text field passes through the existing redaction AND the
       exporter's own credential scrub.** `events/redaction.is_secret_key`
       removes a field NAMED like a credential; `content.scrub_text` finds a
       key SHAPED like one inside a value. Two rules because they catch
       different things, and neither catches a credential pasted into an idea
       under an innocent name - which is why condition 3 says so in words.
    2. **The route is admin-only**, which is the caller's business and is
       enforced by `require_admin`'s 404 above this.
    3. **The first line is a header** saying the file contains user-typed
       content, in a sentence rather than a flag, because the person
       downloading it is the person who has to decide where to put it.

    A run-capped export ends with one `{"_truncated": true, ...}` line rather
    than a 500, the way `/api/runs/{id}/logs` already does: a partial file is
    worth more to whoever is reading it than an error.
    """

    from brief_crew.events.redaction import redact_mapping
    from brief_crew.observability.content import (
        credential_values_in_environment,
        scrub_text,
    )

    secrets = credential_values_in_environment()

    def clean(value: Any) -> Any:
        if isinstance(value, str):
            return scrub_text(value, secrets)
        if isinstance(value, Mapping):
            return {key: clean(item) for key, item in redact_mapping(value).items()}
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            return [clean(item) for item in value]
        return value

    lines: list[dict[str, Any]] = [
        {
            "_header": True,
            "note": EVALSET_HEADER_NOTE,
            "workflow_id": workflow_id,
            "rating": rating,
            "window": window.model_dump(mode="json"),
            "max_runs": config.EVALSET_MAX_RUNS,
            "max_bytes": config.EVALSET_MAX_BYTES,
            "generated_at": _iso(datetime.now(timezone.utc)),
        }
    ]
    gates_by_run: dict[str, list[dict[str, Any]]] = {}
    for gate in gates:
        if gate.get("answered_at") is None:
            continue
        gates_by_run.setdefault(str(gate["run_id"]), []).append(
            {
                "gate_id": gate.get("gate_id"),
                "decision": gate_outcome(gate.get("response")),
                "pairs": [
                    clean(pair)
                    for pair in gate_pairs(gate.get("request"), gate.get("response"))
                ],
            }
        )
    for row in runs:
        run_id = row["run_id"]
        payload = payloads.get(run_id) or {}
        verdict = verdicts.get(run_id) or {}
        result = payload.get("result")
        summary = ""
        if isinstance(result, Mapping):
            body = result.get("markdown_body")
            if isinstance(body, str):
                summary = body[: config.EVALSET_MAX_RESULT_CHARS]
        lines.append(
            {
                "run_id": run_id,
                "workflow_id": row["workflow_id"],
                "document_version": row.get("document_version"),
                "graph_version": row.get("graph_version"),
                "created_at": _iso(row.get("created_at")),
                "status": row.get("status"),
                "mode": row.get("mode"),
                "cost_usd": _money(costs.get(run_id, 0)),
                "inputs": clean(payload.get("inputs") or {}),
                "outcome": {
                    "verdict": _verdict_of(verdict) if verdict else None,
                    "confidence": verdict.get("confidence"),
                    "result_summary": clean(summary),
                },
                "gates": gates_by_run.get(run_id, []),
                "rating": row.get("rating"),
                "rating_note": clean(row.get("rating_note")),
                "rated_at": _iso(row.get("rated_at")),
            }
        )
    if truncated:
        lines.append(
            {
                "_truncated": True,
                "reason": (
                    f"the export stopped at {config.EVALSET_MAX_RUNS} runs; "
                    "narrow the window to see the rest"
                ),
            }
        )
    return lines


def evalset_ndjson(
    lines: Iterable[Mapping[str, Any]], *, max_bytes: int | None = None
) -> Iterator[str]:
    """R3's fourth condition: the bytes on the wire are bounded too.

    `EVALSET_MAX_RUNS` bounds the ROW COUNT and says nothing about the size of
    a row. Two thousand runs each carrying a 2,000-character summary, an
    inputs mapping and every gate pair is tens of megabytes assembled by a
    generator that no admission check bounds - so the row cap alone is a cap
    on the wrong axis.

    A file that STOPS with a `_truncated` trailer is worth more to whoever is
    reading it than a browser that gives up halfway, which is the same call
    `/api/runs/{id}/logs` made for frames. The trailer says which bound it hit
    and what to do about it, because "narrow the window" is advice a reader
    can act on and a silent short file is not.

    The header line is always emitted, whatever the budget: a file whose first
    line is a truncation notice would say nothing about what it is a truncation
    OF.
    """

    budget = config.EVALSET_MAX_BYTES if max_bytes is None else int(max_bytes)
    spent = 0
    for line in lines:
        rendered = json.dumps(line, default=str, ensure_ascii=False) + "\n"
        size = len(rendered.encode("utf-8"))
        if spent and spent + size > budget:
            yield json.dumps(
                {
                    "_truncated": True,
                    "reason": (
                        f"the export stopped at {budget} bytes; narrow the "
                        "window or filter by rating to see the rest"
                    ),
                },
                ensure_ascii=False,
            ) + "\n"
            return
        spent += size
        yield rendered
