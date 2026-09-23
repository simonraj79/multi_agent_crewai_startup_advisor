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
import contextvars
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
    "LABEL_KEYS",
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
    """`(system, user, truncated)`, and it NEVER exceeds the ceiling.

    MEASURED defect: this shrank `sample` and nothing else, so a large mined
    payload rendered a **51,533-character** prompt against a 40,000 ceiling
    and reported `truncated=False`. That figure is not cosmetic -
    `worst_case_digest_cost()` prices exactly `DIGEST_MAX_INPUT_CHARS`, so a
    prompt over it is a bill over the cap that was checked at import.

    Three steps, in this order, and the order is a judgement:

    1. **Drop sample runs, newest kept.** The mined counts are what the review
       is being asked to read across; raw frames are the cheapest thing to
       lose, and runs go whole so the model never sees half of one.
    2. **Trim the mined lists to fewer rows each.** They are RANKED, so the
       first rows are the ones a review would cite anyway.
    3. **Clip, as a last resort.** Only reachable when the template plus the
       two fixed values already exceed the ceiling, and a clipped prompt is
       worth more than a refusal at the moment somebody clicks.

    `truncated` is True if ANY of the three fired, because the caller stores
    it and a reader of a stored review needs to know it was made over part of
    the evidence.
    """

    ceiling = config.DIGEST_MAX_INPUT_CHARS if max_chars is None else int(max_chars)
    scrubbed = structural_hotspots(hotspots)
    rows = list(sample) if isinstance(sample, Sequence) else []
    truncated = False

    def render(hotspot_payload: Any, sample_rows: list[Any]) -> tuple[str, str]:
        values = {
            "workflow_name": str(workflow_name),
            "window": str(window),
            "hotspots_json": _compact(hotspot_payload),
            "lessons_json": _compact(lessons),
            "sample_json": _compact(sample_rows),
        }
        return (
            template["system"].format_map(_MissingKeys(values)),
            template["user"].format_map(_MissingKeys(values)),
        )

    # 1 - the sample.
    while True:
        system, user = render(scrubbed, rows)
        if len(system) + len(user) <= ceiling or not rows:
            break
        rows = rows[:-1]
        truncated = True

    # 2 - the mined lists, halved until they fit or there is one row each.
    limit = _longest_list(scrubbed)
    while len(system) + len(user) > ceiling and limit > 1:
        limit = max(1, limit // 2)
        trimmed = _capped_lists(scrubbed, limit)
        system, user = render(trimmed, rows)
        truncated = True
        scrubbed = trimmed

    # 3 - the clip. `user` first, because `system` is the instructions and a
    # review missing half its rules is worse than one missing half its data.
    total = len(system) + len(user)
    if total > ceiling:
        truncated = True
        room = max(0, ceiling - len(system))
        user = user[:room]
        if len(system) + len(user) > ceiling:
            system = system[: max(0, ceiling - len(user))]
    return system, user, truncated


def _longest_list(payload: Any) -> int:
    """The longest list anywhere in the mined counts - step 2's starting cap."""

    longest = 0
    if isinstance(payload, Mapping):
        for value in payload.values():
            longest = max(longest, _longest_list(value))
    elif isinstance(payload, Sequence) and not isinstance(payload, (str, bytes)):
        longest = max(len(payload), *(0,))
        for item in payload:
            longest = max(longest, _longest_list(item))
    return longest


def _capped_lists(payload: Any, limit: int) -> Any:
    """The same payload with every list cut to `limit` rows, deepest included.

    The lists are RANKED by the miner, so the rows that survive are the ones a
    review would have cited: this loses the tail rather than a random slice.
    """

    if isinstance(payload, Mapping):
        return {key: _capped_lists(value, limit) for key, value in payload.items()}
    if isinstance(payload, Sequence) and not isinstance(payload, (str, bytes)):
        return [_capped_lists(item, limit) for item in payload[:limit]]
    return payload


#: Which meter, if any, the CURRENT context belongs to.
#:
#: A `ContextVar` rather than a thread id, and the difference was measured:
#: `crewai_event_bus` delivers a sync handler on an EXECUTOR thread, not on
#: the thread that emitted, so `threading.get_ident()` inside a handler names
#: a worker and never the caller. What the bus does carry across is the
#: emitter's CONTEXT - `copy_context()` at submit - so a token set around the
#: one `llm.call` is present in that handler and absent in a handler serving a
#: paid run emitted from a registry worker.
#:
#: That is the whole of the attribution: an unrelated completion arriving mid
#: review is not counted, so a concurrent run can no longer inflate a review's
#: `cost_usd` or set a false `over_cap`.
_ACTIVE_METER: contextvars.ContextVar[object | None] = contextvars.ContextVar(
    "brief_crew_digest_meter", default=None
)


#: How long `__exit__` waits for the bus to deliver what it already accepted.
#:
#: Five seconds rather than the SDK's 30 s default: the only handler this
#: review's own event has to reach is the meter, and everything else on that
#: bus belongs to somebody whose slowness must not park a request thread.
#: Giving up leaves the figure short, which `cost_usd` then reports honestly;
#: hanging would leave the service short, which nothing reports at all.
_METER_FLUSH_SECONDS = 5.0


#: The keys whose value is a NODE LABEL - a string the author typed.
#:
#: They are the one unscrubbed free text that was reaching the prompt: every
#: other key on these payloads is a name this program chose, a code or a
#: number. A label is carried because a review that cannot name a node is
#: useless, and it is bounded at `MAX_PROMPT_LABEL_CHARS` and passed through
#: `scrub_text` because it is the author's words.
LABEL_KEYS: frozenset[str] = frozenset({"node_label", "label"})

#: The two `details` keys that name a task. Allowed by `SAMPLE_DETAIL_KEYS`
#: because a declared task name is an identifier, and carried ONLY when the
#: value is one: CrewAI falls back to `task.description` for an unnamed task,
#: and on a builder frame that is the rendered prompt with the user's input
#: in it (`config.declared_task_name`). The mined payload's `tasks[].task_name`
#: is safe at its source - `mine_hotspots` never writes a description there -
#: and this key set is also applied to it below, so the guarantee holds even
#: for a payload built by something else.
TASK_NAME_KEYS: frozenset[str] = frozenset({"task_name", "task"})


def structural_hotspots(payload: Any, secrets: Sequence[str] | None = None) -> Any:
    """The mined counts with the one non-structural key removed (R2).

    A hotspots payload is counts, names and rates - all of it structural -
    with one exception: `queries_sample` holds the strings a model asked a
    tool, which is a tool argument by another name. It is dropped here rather
    than removed from the model, because the admin panel showing an author
    their own workflow's queries is not the same act as sending them to a
    third-party inference provider.

    `node_models` is deliberately NOT dropped: a node id, its author's label
    and a list of model slugs are names and counts, which the ruling admits,
    and a review that cannot see which tier a node ran on cannot say anything
    useful about cost. Its LABEL is scrubbed like every other, below.

    Total: anything that is not a mapping or a list comes back unchanged, so a
    caller that hands this a string gets a string.
    """

    if secrets is None:
        from brief_crew.observability.content import credential_values_in_environment

        secrets = credential_values_in_environment()
    if isinstance(payload, Mapping):
        return {
            key: (
                _clean_label(value, secrets)
                if key in LABEL_KEYS
                else structural_hotspots(value, secrets)
            )
            for key, value in payload.items()
            if key not in NON_STRUCTURAL_HOTSPOT_KEYS
            # A task name that is not a declared identifier is a rendered
            # description, and it is dropped rather than carried.
            and not (
                key in TASK_NAME_KEYS
                and isinstance(value, str)
                and not config.declared_task_name(value)
            )
        }
    if isinstance(payload, Sequence) and not isinstance(payload, (str, bytes)):
        return [structural_hotspots(item, secrets) for item in payload]
    return payload


def _clean_label(value: Any, secrets: Sequence[str]) -> Any:
    """One node label on its way to a model: bounded, then scrubbed.

    Bounded FIRST so the scrub runs over a short string, and scrubbed after so
    a key that sat inside the first forty characters is still found. A
    non-string comes back unchanged rather than being coerced - a label that
    is not text is a shape this function has no opinion about.
    """

    if not isinstance(value, str):
        return value
    from brief_crew.observability.content import scrub_text

    return scrub_text(value[: config.MAX_PROMPT_LABEL_CHARS], secrets)


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
                if name in TASK_NAME_KEYS:
                    # A task name is a name only when somebody declared one.
                    # Otherwise CrewAI filled it with the RENDERED task
                    # description, which carries the user's input - so it is
                    # dropped, never truncated: forty characters of a
                    # customer's message is still a customer's message.
                    declared = config.declared_task_name(value)
                    if declared:
                        kept[name] = declared
                    continue
                # A node label is the author's own words - bounded and
                # scrubbed like the ones on the mined payload.
                kept[name] = (
                    _clean_label(value, secrets) if name in LABEL_KEYS else value
                )
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
    """What THIS call used, and nothing else. Scoped, unregistered, attributed.

    Three properties, and the first two were absent and MEASURED absent: the
    handler count on the process-wide bus went 1 -> 2 -> 3 -> 4 over three
    reviews, and an exited meter absorbed an unrelated event's tokens.

    * **It unregisters.** `__exit__` calls `crewai_event_bus.off(...)` with the
      handle `__enter__` kept. The bus is a process-wide singleton, so a
      listener left behind is not a slow leak - it is a permanent one, and
      every later review paid a little more of somebody else's usage.
    * **It is inert outside its own block.** `_active` is cleared before the
      handler is removed, because `off()` and an in-flight emit race and the
      flag is what makes the race harmless.
    * **It counts only THIS call**, through `_ACTIVE_METER`. Without it a
      concurrent run inflated the review's `cost_usd` and could set a false
      `over_cap` - a money figure made wrong by something the review had
      nothing to do with.

    `agent_id` is NOT the discriminator, though the event carries one: a
    review is an agentless `LLM.call` and so is any other bare call in this
    process, so "no agent" is a class and not an identity. Nor is the thread:
    the bus delivers on an executor thread, measured, so a thread check
    inside a handler names a worker and never the caller.

    Total, like every other listener here: an event that cannot be read adds
    nothing rather than raising inside the bus.
    """

    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _handle: Any = None
    _event_type: Any = None
    _token: Any = None
    _reset: Any = None
    _active: bool = False

    def __enter__(self) -> "_TokenMeter":
        try:
            from crewai.events import LLMCallCompletedEvent, crewai_event_bus
        except Exception:  # noqa: BLE001 - no bus is not an error here
            return self

        meter = self
        # A fresh object as the token, so two meters are never equal by
        # value. Set BEFORE the handler is registered: a handler that could
        # fire before the context is marked would count nothing anyway, but
        # the order is what makes that statement true rather than likely.
        self._token = object()
        self._reset = _ACTIVE_METER.set(self._token)
        self._active = True

        def _absorb(_source: Any, event: Any) -> None:
            meter.absorb(getattr(event, "usage", None))

        crewai_event_bus.register_handler(LLMCallCompletedEvent, _absorb)
        self._handle = _absorb
        self._event_type = LLMCallCompletedEvent
        return self

    def __exit__(self, *_exc: Any) -> None:
        # FLUSH FIRST, and this was measured: `emit` returns a future and the
        # bus runs sync handlers on an executor, so `totals()` read straight
        # after the call raced the delivery and reported 0 tokens about half
        # the time - a review priced at nothing, which is the same shape as
        # the defect that once priced 128,069 real tokens at $0.00.
        #
        # Bounded, because an unbounded wait here would park a request thread
        # on somebody else's slow handler: a short timeout that gives up is a
        # missing figure, and a hang is a missing service.
        try:
            from crewai.events import crewai_event_bus

            crewai_event_bus.flush(timeout=_METER_FLUSH_SECONDS)
        except Exception:  # noqa: BLE001 - a bus that cannot flush is not a
            # reason to fail a review that has already been paid for.
            pass
        # Flag next, handler last: `off()` and an in-flight emit can race,
        # and a handler that has already been entered must add nothing.
        self._active = False
        if self._reset is not None:
            try:
                _ACTIVE_METER.reset(self._reset)
            except ValueError:  # pragma: no cover - a context that moved
                _ACTIVE_METER.set(None)
            self._reset = None
        if self._handle is None or self._event_type is None:
            return None
        try:
            from crewai.events import crewai_event_bus

            crewai_event_bus.off(self._event_type, self._handle)
        except Exception:  # noqa: BLE001 - a bus that cannot unregister is
            # not a reason to fail a review that has already been paid for.
            pass
        finally:
            self._handle = None
            self._event_type = None
        return None

    def absorb(self, usage: Any) -> None:
        """One usage mapping into the running totals. Never raises."""

        if not self._active:
            return
        if self._token is not None and _ACTIVE_METER.get() is not self._token:
            return
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
