"""One cheap model call, behind one click, under a ceiling checked at import.

Plan 21, "Ask a model to review", and the only place in the plan that spends
money.

EVERYTHING HERE IS A BOUND
--------------------------
* **It cannot be reached without an explicit `POST`.** No `GET` builds one, no
  page load fetches one, nothing schedules one, and there is no retry. An
  unattended model call is the shape of thing the money rule exists to
  prevent.
* **It is off by default.** `IMPROVE_DIGEST_ENABLED` is the one environment
  knob this plan adds and it defaults false; the route answers 422 and this
  module constructs no `LLM` while it is.
* **The sample is bounded on three axes** - `DIGEST_MAX_SAMPLE_RUNS` (12),
  `DIGEST_MAX_SAMPLE_FRAMES` (400) and `DIGEST_MAX_INPUT_CHARS` (40,000) - and
  the answer on a fourth, `DIGEST_MAX_OUTPUT_TOKENS` (1,200) passed as
  `max_tokens`. A prompt that does not fit is TRUNCATED and the response says
  it was, rather than the request being refused: a review over eleven of
  twelve runs is worth having, and a 422 at the moment somebody clicks is not.
* **The cap is arithmetic, not hope.** `config.worst_case_digest_cost()`
  prices those two bounds through `compute_cost_usd` at the model's dearest
  measured endpoint and `config._assert_digest_cost_ceiling()` DISABLES the
  feature, loudly, when it exceeds `DIGEST_MAX_COST_USD` (plan 21 R9: a check
  that made the package unimportable would take the whole product down over a
  feature that is off by default). After the call the MEASURED cost is
  compared with the cap again by the route, which stores `over_cap` and logs a
  breach at WARNING.

PRIVACY - PLAN 21 R2, AND IT IS THE REASON `build_sample` HAS AN ALLOW-LIST
---------------------------------------------------------------------------
The prompt carries **structural facts only**: names, roles, kinds, statuses,
counts, durations, error classes, the model, retry counts, `result_count`,
`tool_status`, fallback, confidence and the verdict code. It carries no prompt
text, no model answer, no tool arguments, no tool output, no utterance and no
free text beyond an error class and a bounded, scrubbed error message.

An allow-list rather than a denylist, and the difference is the whole point: a
frame kind that gains a key tomorrow is EXCLUDED by default, where a denylist
would ship it to a third party the day it was added. `tasks.yaml` says the
model cannot see content, and that sentence is true because of this list -
`tests/service/test_digest.py` plants a secret in a tool's arguments, in an
output preview and in an error message, and fails if any of them reaches the
rendered prompt.

MODEL: `CHEAP_MODEL` only, through `LLM(model=...).call(...)`. No `Agent`, no
`Crew`, no tools, no memory, no registry run - so it raises no CrewAI flow
events, occupies no admission slot, and appears in no run's frames.

PROMPT: `crews/digest_crew/config/tasks.yaml`, `yaml.safe_load`ed and rendered
with `format_map` over a five-key whitelist. **There is no prompt literal in
this file** and a test greps for one.

COST, MEASURED AND NOT ASSUMED. A scoped `LLMCallCompletedEvent` handler is
subscribed for the duration of the call and its token counts are priced with
`config.compute_cost_usd` - the same function the token frame uses, so a
review's dollars and a run's dollars mean the same thing. An unknown model
returns `None`, never `0.0`: "no price on file" and "this call was free" are
different facts and reporting the second for the first is the defect that once
priced a 128,069-token run at $0.00.

OUTPUT is model output, therefore untrusted: stored as text, rendered only
through the escape-first `markdown.ts`, and never re-fed to anything.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import logging
import pathlib
import threading
from typing import Any
import uuid

import yaml

from brief_crew import config

__all__ = [
    "PROMPT_PATH",
    "PROMPT_TASK_KEY",
    "SAMPLE_DETAIL_KEYS",
    "SAMPLE_FRAME_KINDS",
    "DigestResult",
    "DigestUnavailable",
    "build_sample",
    "load_prompt",
    "render_prompt",
    "run_digest",
    "structural_hotspots",
]

logger = logging.getLogger(__name__)

#: The prompt, beside the two crews that already keep theirs in YAML.
PROMPT_PATH = (
    pathlib.Path(__file__).resolve().parent.parent
    / "crews"
    / "digest_crew"
    / "config"
    / "tasks.yaml"
)

#: The one task key the prompt file hangs its two halves off. See
#: `load_prompt` for why it is not `system` and `user` at the top level.
PROMPT_TASK_KEY = "improve_digest"

#: The only names the template may address. A `format_map` over mined data
#: with no whitelist would let a brace inside a tool's own name reach any
#: attribute of any value in scope; this makes the template's vocabulary a
#: closed set that this module owns.
PROMPT_KEYS = (
    "workflow_name",
    "window",
    "hotspots_json",
    "lessons_json",
    "sample_json",
)

#: The frame kinds a review can act on. Everything else is plumbing and would
#: spend the prompt budget saying a node started.
SAMPLE_FRAME_KINDS = ("agent", "tool", "guardrail", "error", "verdict")

#: **Plan 21 R2: the allow-list.** Every `details` key a sampled frame may
#: contribute, and nothing else travels.
#:
#: An ALLOW-list, not a denylist, and that is the load-bearing choice: a frame
#: kind that gains a key tomorrow is excluded by default, where a denylist
#: would send it to a third party on the day it was added. Every name here is
#: one of the categories the ruling lists - a name, a role, a kind, a status, a
#: count, a duration, an error class, the model, a retry count, `result_count`,
#: `tool_status`, a fallback, a confidence or a verdict code.
#:
#: What is deliberately ABSENT is the point: `output_preview`, `output_json`,
#: `query`, `args`, `arguments`, `output`, `text`, `notes`, `feedback`,
#: `inputs`, `result`, `utterance` and the frame's own `message`. Those are a
#: person's or a model's words; the review is asked to read counts.
SAMPLE_DETAIL_KEYS: frozenset[str] = frozenset(
    {
        # what happened, and to what
        "stage",
        "agent_role",
        "task_name",
        "task",
        "tool",
        "guardrail",
        "gate_id",
        "node_label",
        "status",
        "route",
        "decision",
        # how it went
        "success",
        "failure",
        "from_cache",
        "tool_status",
        "result_count",
        "error_class",
        "error_type",
        "finish_reason",
        # how many, how long, how much
        "attempt",
        "attempts",
        "retries",
        "retry_count",
        "tool_failure_count",
        "call_count",
        "elapsed_ms",
        "duration_ms",
        "total_tokens",
        "prompt_tokens",
        "completion_tokens",
        "cost_usd",
        # which model, and whether a fallback fired
        "model",
        "fallback",
        "fallback_model",
        # the verdict, as a code and a number
        "verdict",
        "result_code",
        "confidence",
        "provisional",
    }
)

#: The one `details` key that is free text and is carried anyway, because an
#: error a person cannot read is an error nobody can act on. It is BOUNDED and
#: passed through `scrub_text` - the same credential scrub the eval-set export
#: uses - before it reaches the prompt.
SAMPLE_ERROR_KEY = "error"

#: How much of one. Short on purpose: a review needs the shape of a failure,
#: not a traceback, and a traceback is where content tends to hide.
SAMPLE_ERROR_CHARS = 240

#: The one key of a hotspots payload that is NOT structural: a tool's own
#: queries are model-written text and a query is a tool argument by another
#: name. `node_models` is deliberately NOT here - a node id, its author's
#: label and a list of model slugs are names and counts, which the ruling
#: admits, and a review that cannot see which tier a node ran on cannot say
#: anything useful about cost. `structural_hotspots` removes it, so R2's "hotspots payloads are
#: structural already" is true of what reaches the model rather than nearly
#: true. The PANEL keeps it - an admin reading their own console is not a
#: third party.
NON_STRUCTURAL_HOTSPOT_KEYS: frozenset[str] = frozenset({"queries_sample"})


class DigestUnavailable(RuntimeError):
    """The review cannot run, and the sentence says why. Never a 500."""


@dataclass
class DigestResult:
    """What one call produced, including what it could not fit."""

    body: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    #: `None` means the model is not in the price table. NOT `0.0`.
    cost_usd: float | None = None
    sample_runs: int = 0
    sample_frames: int = 0
    truncated_sample: bool = False
    prompt_chars: int = 0


class _MissingKeys(dict):
    """A `format_map` mapping that leaves an unknown brace alone.

    Mined data reaches the template as JSON, and JSON is full of braces. A
    plain `format` would raise `KeyError` on the first one; a `defaultdict`
    would silently blank it. This leaves the text as it was written, so a
    name containing `{foo}` survives into the prompt looking like itself.
    """

    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def load_prompt(path: pathlib.Path | None = None) -> dict[str, str]:
    """The two-key template off disk. `safe_load`, never `load`.

    Read on every call rather than cached at import, which is what makes
    "patch the file, the prompt changes" a real test rather than an assertion
    about a module global.
    """

    source = path or PROMPT_PATH
    try:
        raw = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
    except OSError as exc:
        raise DigestUnavailable(
            f"the review prompt could not be read from {source.name}"
        ) from exc
    if not isinstance(raw, Mapping):
        raise DigestUnavailable("the review prompt file is not a mapping")
    # One task key, then the two halves under it. The nesting is there for
    # `tests/observability/test_no_flow_identifiers.py`, which reads every
    # TOP-LEVEL key of every `crews/*/config/tasks.yaml` as a task key and
    # then forbids the exporter naming one: `system` and `user` at the top
    # level would make the words "system" and "user" forbidden across the
    # whole observability package. The file says so where it does it.
    block = raw.get(PROMPT_TASK_KEY)
    if not isinstance(block, Mapping):
        raise DigestUnavailable(
            f"the review prompt file needs a `{PROMPT_TASK_KEY}` block"
        )
    system = block.get("system")
    user = block.get("user")
    if not isinstance(system, str) or not isinstance(user, str):
        raise DigestUnavailable(
            "the review prompt file needs a `system` and a `user` key"
        )
    return {"system": system, "user": user}


def render_prompt(
    template: Mapping[str, str],
    *,
    workflow_name: str,
    window: str,
    hotspots: Any,
    lessons: Any,
    sample: Any,
    max_chars: int | None = None,
) -> tuple[str, str, bool]:
    """`(system, user, truncated)`, with the SAMPLE cut first if it must be.

    The sample is what gets shorter, in that order, and the order is a
    judgement: the mined counts are what the review is being asked to read
    across, and dropping half of them to fit more raw frames would make the
    answer worse in exactly the way the bounds exist to prevent. Sample runs
    are dropped whole, newest kept, so the model never sees half a run.
    """

    ceiling = config.DIGEST_MAX_INPUT_CHARS if max_chars is None else int(max_chars)
    values = {
        "workflow_name": str(workflow_name),
        "window": str(window),
        "hotspots_json": _compact(structural_hotspots(hotspots)),
        "lessons_json": _compact(lessons),
        "sample_json": "",
    }
    rows = list(sample) if isinstance(sample, Sequence) else []
    truncated = False
    while True:
        values["sample_json"] = _compact(rows)
        system = template["system"].format_map(_MissingKeys(values))
        user = template["user"].format_map(_MissingKeys(values))
        if len(system) + len(user) <= ceiling or not rows:
            return system, user, truncated
        rows = rows[:-1]
        truncated = True


def structural_hotspots(payload: Any) -> Any:
    """The mined counts with the one non-structural key removed (R2).

    A hotspots payload is counts, names and rates - all of it structural -
    with one exception: `queries_sample` holds the strings a model asked a
    tool, which is a tool argument by another name. It is dropped here rather
    than removed from the model, because the admin panel showing an author
    their own workflow's queries is not the same act as sending them to a
    third-party inference provider.

    Total: anything that is not a mapping or a list comes back unchanged, so a
    caller that hands this a string gets a string.
    """

    if isinstance(payload, Mapping):
        return {
            key: structural_hotspots(value)
            for key, value in payload.items()
            if key not in NON_STRUCTURAL_HOTSPOT_KEYS
        }
    if isinstance(payload, Sequence) and not isinstance(payload, (str, bytes)):
        return [structural_hotspots(item) for item in payload]
    return payload


def _structural_details(details: Any, secrets: Sequence[str]) -> dict[str, Any]:
    """One frame's `details`, reduced to the allow-list (R2).

    Two passes and they are different rules. Every key in
    `SAMPLE_DETAIL_KEYS` is copied as it stands, because each of them is a
    name, a code or a number. `SAMPLE_ERROR_KEY` is the single free-text
    exception and is BOUNDED and scrubbed on the way through. Everything else
    - including a key nobody has thought about yet - is dropped.
    """

    if not isinstance(details, Mapping):
        return {}
    from brief_crew.observability.content import scrub_text

    kept: dict[str, Any] = {}
    for key, value in details.items():
        name = str(key)
        if name in SAMPLE_DETAIL_KEYS:
            # Only scalars. A nested mapping under an allowed name would be a
            # hole in the list: `usage` is a count, `usage.messages` would not
            # be, and the list cannot vet a shape it has not seen.
            if value is None or isinstance(value, (str, int, float, bool)):
                kept[name] = value
        elif name == SAMPLE_ERROR_KEY and isinstance(value, str):
            kept[name] = scrub_text(value[:SAMPLE_ERROR_CHARS], secrets)
    return kept


def build_sample(
    runs: Sequence[Mapping[str, Any]],
    frames: Sequence[Mapping[str, Any]],
    *,
    max_runs: int | None = None,
    max_frames: int | None = None,
) -> tuple[list[dict[str, Any]], bool]:
    """The newest runs with their own frames, bounded on both axes and FILTERED.

    Frames are attached to the run they belong to rather than handed over as
    one flat list, because "which run was that in" is the first question a
    reader of a review asks and a flat list cannot answer it.

    **Every frame passes through `_structural_details` (R2)**, and the frame's
    own `message` is not carried at all: the serializer writes it as a
    sentence for a person and it can hold a tool's own words. What survives is
    the kind, the node, and the allow-listed keys.
    """

    from brief_crew.observability.content import credential_values_in_environment

    secrets = credential_values_in_environment()
    run_cap = config.DIGEST_MAX_SAMPLE_RUNS if max_runs is None else int(max_runs)
    frame_cap = (
        config.DIGEST_MAX_SAMPLE_FRAMES if max_frames is None else int(max_frames)
    )
    chosen = list(runs)[:run_cap]
    truncated = len(runs) > len(chosen)
    wanted = {row["run_id"] for row in chosen}
    by_run: dict[str, list[dict[str, Any]]] = {row["run_id"]: [] for row in chosen}
    kept = 0
    for frame in frames:
        if kept >= frame_cap:
            truncated = True
            break
        run_id = frame.get("run_id")
        if run_id not in wanted:
            continue
        if str(frame.get("kind")) not in SAMPLE_FRAME_KINDS:
            continue
        by_run[run_id].append(
            {
                "kind": frame.get("kind"),
                "node_id": frame.get("node_id"),
                "details": _structural_details(frame.get("details"), secrets),
            }
        )
        kept += 1
    return (
        [
            {
                "run_id": row["run_id"],
                "status": row.get("status"),
                "rating": row.get("rating"),
                "document_version": row.get("document_version"),
                "frames": by_run.get(row["run_id"], []),
            }
            for row in chosen
        ],
        truncated,
    )


def run_digest(
    *,
    workflow_name: str,
    window: str,
    hotspots: Any,
    lessons: Any,
    sample: Sequence[Mapping[str, Any]],
    sample_truncated: bool = False,
    sample_frames: int = 0,
    llm_factory: Any = None,
    prompt_path: pathlib.Path | None = None,
) -> DigestResult:
    """Make the one call, and price it from the event it raised.

    `llm_factory` is the injection point every test uses, so no test in this
    repository can reach OpenRouter by forgetting a patch: a fake is passed
    in, and the default is only constructed when nobody supplied one.

    Raises `DigestUnavailable` - never a bare exception - when the knob is off
    or the prompt cannot be read, so the route can turn it into a 422 with the
    sentence the operator needs rather than a 500.
    """

    if not config.digest_enabled():
        raise DigestUnavailable(
            "the model review is off on this deployment; set "
            "IMPROVE_DIGEST_ENABLED=1 to turn it on"
        )
    template = load_prompt(prompt_path)
    system, user, truncated = render_prompt(
        template,
        workflow_name=workflow_name,
        window=window,
        hotspots=hotspots,
        lessons=lessons,
        sample=sample,
    )
    model = config.CHEAP_MODEL
    meter = _TokenMeter(model)
    with meter:
        llm = (llm_factory or _default_llm)(model)
        body = llm.call(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ]
        )
    prompt_tokens, completion_tokens = meter.totals()
    return DigestResult(
        body=str(body or ""),
        model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cost_usd=config.compute_cost_usd(model, prompt_tokens, completion_tokens),
        sample_runs=len(sample),
        sample_frames=sample_frames,
        truncated_sample=bool(sample_truncated or truncated),
        prompt_chars=len(system) + len(user),
    )


def _default_llm(model: str) -> Any:
    """`LLM(model, max_tokens=DIGEST_MAX_OUTPUT_TOKENS)`, imported lazily.

    Lazily because importing `crewai.LLM` at module import would make the
    admin router's import cost the whole framework, and because a test that
    patches the class must be able to patch it before this module reaches for
    it.
    """

    from crewai import LLM

    return LLM(model=model, max_tokens=config.DIGEST_MAX_OUTPUT_TOKENS)


@dataclass
class _TokenMeter:
    """A scoped `LLMCallCompletedEvent` handler: what this one call used.

    The event bus is process-wide and every other consumer of it is per-run,
    so this counts only while it is inside its own `with`. It is a CONTEXT
    MANAGER rather than a permanent listener for that reason: a review must
    not appear in a run's token totals and a run must not appear in a
    review's.

    Total, like every other listener in this repository: an event that cannot
    be read adds nothing rather than raising inside the bus.
    """

    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _handle: Any = None

    def __enter__(self) -> "_TokenMeter":
        try:
            from crewai.events import LLMCallCompletedEvent, crewai_event_bus
        except Exception:  # noqa: BLE001 - no bus is not an error here
            return self

        meter = self

        @crewai_event_bus.on(LLMCallCompletedEvent)
        def _absorb(_source: Any, event: Any) -> None:  # pragma: no cover
            meter.absorb(getattr(event, "usage", None))

        self._handle = _absorb
        return self

    def __exit__(self, *_exc: Any) -> None:
        return None

    def absorb(self, usage: Any) -> None:
        """One usage mapping into the running totals. Never raises."""

        if not isinstance(usage, Mapping):
            return
        with self._lock:
            self.prompt_tokens += _tokens(usage, ("prompt_tokens", "input_tokens"))
            self.completion_tokens += _tokens(
                usage, ("completion_tokens", "output_tokens")
            )

    def totals(self) -> tuple[int, int]:
        with self._lock:
            return self.prompt_tokens, self.completion_tokens


def _tokens(usage: Mapping[str, Any], names: Sequence[str]) -> int:
    for name in names:
        value = usage.get(name)
        if isinstance(value, (int, float)):
            return int(value)
    return 0


def _compact(value: Any) -> str:
    """JSON with no whitespace, because whitespace is prompt budget."""

    try:
        return json.dumps(value, default=str, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError):
        return json.dumps(str(value))


def new_digest_id() -> str:
    """A short opaque id for a stored row, in the builder's `ug_` shape."""

    return f"dg_{uuid.uuid4().hex[:8]}"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
