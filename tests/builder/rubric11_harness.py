"""Compile one rubric-11 fixture, run it for free, and describe what happened.

A MODULE rather than a function inside the test, because criterion 10 runs each
fixture twice in one process AND once in a fresh one, and the third leg needs
something a subprocess can import and call:

    python -m tests.builder.rubric11_harness <name>

prints the artefact as sorted JSON on stdout. That is the whole subprocess
contract, and it exists so `PYTHONHASHSEED` really is fresh on the third leg -
a `set` or `dict` iteration order reaching the definition would differ there and
nowhere else.

**What is captured, and why each of the three.**

* `definition` - the compiled `crewai.flow/v1` document. The artefact everything
  else is downstream of.
* `frames` - the REAL event spine: `StreamSinkAdapter` over a `FrameBuffer`,
  subscribed through `capture_events`, with the workflow's own `NodeRegistry`.
  Not a recorder written for this test: a double that diverges from its subject
  certifies nothing, and a frame sequence is exactly the thing an operator sees.
  Projected to `(node_id, event_type, kind)` - `kind` where 09 D9 says "stage",
  because that is the field `FrameData` actually carries.
* `result` - the run's own result body, and `budget` beside it.

**`compiled_at` is PINNED and not stripped.** `as_budget` defaults it to
`datetime.now(timezone.utc)` and it drifts between two calls a second apart, so
a golden carrying a budget cannot be compared while that default applies. The
seam already exists and costs nothing. Stripping the field instead would make it
a field the test stops checking, which is the one repair this plan set has
already learned not to make.

No cost. Every billable node is built by `SyntheticCrewFactories`, the same
object `SYNTHETIC=1` installs; no model is called and no network is touched.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from typing import Any

#: One run id for every fixture and every leg. It appears in no artefact - the
#: frame projection drops it - but a random one would be a value in the buffer
#: that differed between legs for no reason anybody could see.
RUN_ID = "rubric11"

#: What every fixture is kicked off with. Fixed, because "deterministic keyed on
#: (node_id, input hash)" needs the input half to be a constant.
INPUTS: dict[str, Any] = {"idea": "a scheduling assistant for clinics"}

#: The pinned `compiled_at`. See the module docstring.
COMPILED_AT = datetime(2026, 9, 4, tzinfo=timezone.utc)


def artefact(name: str) -> dict[str, Any]:
    """The three byte-comparable artefacts for one fixture, plus its budget."""

    from brief_crew.builder.budget import estimate_budget
    from brief_crew.builder.compiler import compile_document, compile_replay_plan
    from tests.builder.rubric11_documents import FIXTURES, REPLAYS

    if name in REPLAYS:
        build, target, mode = REPLAYS[name]
        document = build()
        compiled = compile_replay_plan(document, node_id=target, mode=mode)
    else:
        document = FIXTURES[name]()
        compiled = compile_document(document)

    frames, result = _run(document, compiled, replay=name in REPLAYS)
    budget = estimate_budget(document).as_budget(compiled_at=COMPILED_AT)
    return {
        "definition": compiled.definition,
        "frames": frames,
        "result": result,
        "budget": budget.model_dump(mode="json"),
    }


def _run(document: Any, compiled: Any, *, replay: bool) -> tuple[list[Any], Any]:
    """Kick the compiled definition off through the real spine, for free."""

    from crewai.flow.async_feedback import HumanFeedbackPending
    from crewai.flow.flow import Flow

    from brief_crew.builder.descriptor import build_builder_workflow
    from brief_crew.builder.runtime import replay_source, use_crew_factories
    from brief_crew.events.adapter import StreamSinkAdapter
    from brief_crew.events.buffer import FrameBuffer
    from brief_crew.events.context import CaptureContext, capture_events
    from brief_crew.service.builder_runner import SyntheticCrewFactories

    workflow = build_builder_workflow(document)
    buffer = FrameBuffer(quarantine_node_id=workflow.node_registry.quarantine_node_id)
    adapter = StreamSinkAdapter(
        run_id=RUN_ID, buffer=buffer, registry=workflow.node_registry
    )
    flow = Flow.from_declaration(contents=compiled.definition)
    saved = {
        node_id: f"saved output for {node_id}"
        for node_id in compiled.method_idents
    }

    result: Any
    with capture_events(CaptureContext(RUN_ID, adapter)):
        with use_crew_factories(SyntheticCrewFactories()):
            with replay_source(saved if replay else None):
                try:
                    result = flow.kickoff(inputs={**INPUTS, "id": RUN_ID})
                except HumanFeedbackPending:
                    # A gate PAUSED, which is a result rather than a failure -
                    # and the one shape a determinism harness can capture with
                    # no human in it.
                    result = {"paused_at_gate": True}

    return (
        [
            [frame.node_id, str(frame.event_type), str(frame.kind)]
            for frame in buffer.replay()
        ],
        _plain(result),
    )


def _plain(value: Any) -> Any:
    """Whatever a run produced, as something `json.dumps` can sort."""

    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    raw = getattr(value, "raw", None)
    if isinstance(raw, str):
        return raw
    return str(value)


def render(payload: dict[str, Any]) -> str:
    """One artefact as the bytes a golden holds.

    `sort_keys` and a trailing newline, so a diff of two goldens is a diff of
    two graphs rather than of two dict orderings - and so `core.autocrlf` is the
    only remaining difference, which `test_rubric11.py` normalises.
    """

    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


#: The marker the test slices the artefact block out on. The flow engine prints
#: its own panels to stdout and there is no way to ask it not to, so the
#: harness has to say where its own output starts rather than hoping it is the
#: only thing there.
BEGIN = "<<<RUBRIC11>>>"


def main(argv: list[str]) -> int:  # pragma: no cover - the subprocess entrypoint
    """One fixture, or `--all` of them in ONE fresh process.

    `--all` is what `test_rubric11.py` uses, and the reason is measured: what a
    subprocess buys is a fresh `PYTHONHASHSEED`, and one fresh process buys it
    for every fixture at once. Twenty-two interpreter starts cost two minutes of
    CrewAI imports and buy no additional guarantee.
    """

    from tests.builder.rubric11_documents import FIXTURES, REPLAYS

    if len(argv) != 2:
        print("usage: python -m tests.builder.rubric11_harness <fixture>|--all", file=sys.stderr)
        return 2
    if argv[1] == "--all":
        payload = {name: artefact(name) for name in (*FIXTURES, *REPLAYS)}
    else:
        payload = {argv[1]: artefact(argv[1])}
    sys.stdout.write("\n" + BEGIN + "\n" + render(payload))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv))
