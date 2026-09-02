"""The durable pause a builder gate compiles to, and the two halves around it.

One canvas gate node compiles to TWO flow methods - the pause and a
deterministic router that reads its answer - and this module owns everything
about the pause that is not a `do.ref`: the provider, the payload the operator
is shown, and the parse of what they reply.

**Three rules, and every one of them was measured rather than reasoned.**

1. `human_feedback.emit` MUST be null. With `emit` set and `llm: null`,
   `_finalize_human_feedback` returns `emit[0]` unconditionally
   (`crewai/flow/runtime/__init__.py:3707-3721`), so a reply of
   `{"decision": "revise"}` runs the approve branch. Reproduced end to end.
   CrewAI logs the combination at `severity="error"` and runs the flow anyway,
   so its own validation cannot be relied on - `compiler.lint_gates` is the
   guard, and it is the single highest-value check in the compiler.
2. `llm` MUST be explicitly null. `FlowHumanFeedbackDefinition.llm` defaults to
   the *string* `"gpt-4o-mini"` (`flow_definition.py:298`), and the value is
   deserialized before `emit` is even checked, so an omitted key buys a real
   model client per gate for a code path that can never use it.
3. `provider` MUST be set. Without one the engine falls through to
   `input("Your feedback: ")` (`runtime/__init__.py:3806`) on a service worker
   thread, where there is no console and nothing to answer it.

`GATE_PROVIDER` is modelled on `ValidatorFeedbackProvider`, which has been
answering the two shipped gates over HTTP and WebSocket since the service
existed. It is a second instance of that machinery, not a second design: it
raises the same `HumanFeedbackPending`, so the same `RunRegistry._mark_pending`
writes the same `pending_feedback` row and the same `from_pending()` resume
answers it.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from crewai.flow.async_feedback import (
    HumanFeedbackPending,
    HumanFeedbackProvider,
    PendingFeedbackContext,
)

from brief_crew.config import GATE_REVISE_TURNS_METADATA_KEY

__all__ = [
    "GATE_PROVIDER",
    "BuilderFeedbackProvider",
    "gate_decision",
    "gate_payload",
]

# The key a gate's own summary text lands under when the node upstream of it
# produced prose rather than an object. It matches what `service/registry.py`
# calls a gate's note field in spirit: one named place for free text, so a
# client never has to guess which key is the body.
GATE_SUMMARY_FIELD = "summary"

# Where the compiler records the node id on `human_feedback.metadata`, and what
# the provider reads to find which gate it is pausing. The router finds the
# same thing through the compiled routing table instead, because a router runs
# with no metadata of its own.
GATE_ID_METADATA_KEY = "gate_id"

# How the router counts a gate's spent revise turns on the flow's own state.
# Restated from `runtime.py` rather than imported, because importing it would
# make this module depend on the one that depends on it.
_TURNS_PREFIX = "turns__"


def gate_payload(
    node_id: str,
    source: Any,
    editable_fields: Sequence[str] = (),
) -> dict[str, Any]:
    """What the operator sees at this gate, as a plain JSON object.

    A mapping is shown as it is; a JSON object arriving as text is parsed, so a
    gate downstream of an agent shows that agent's fields rather than one wall
    of escaped JSON; anything else becomes a single summary field.

    A declared editable field the payload does not carry is added EMPTY rather
    than dropped. Dropping it is the silent half of the failure: the author
    said "let the operator set this", the form renders every key it is given,
    and a key that is not there is simply an input that never appears with
    nothing on screen to say why.
    """

    payload: dict[str, Any]
    if isinstance(source, Mapping):
        payload = {str(key): value for key, value in source.items()}
    elif isinstance(source, str):
        try:
            parsed = json.loads(source)
        except (json.JSONDecodeError, TypeError):
            parsed = None
        payload = (
            {str(key): value for key, value in parsed.items()}
            if isinstance(parsed, Mapping)
            else {GATE_SUMMARY_FIELD: source}
        )
    elif source is None:
        payload = {GATE_SUMMARY_FIELD: ""}
    else:
        payload = {GATE_SUMMARY_FIELD: str(source)}

    for field in editable_fields:
        payload.setdefault(str(field), "")
    return payload


def gate_decision(feedback: Any) -> tuple[str, dict[str, Any]]:
    """The operator's decision, and everything else their reply carried.

    Returns `("approve" | "revise", rest)`. Anything that is not the word
    `revise` is an approval, which is the same reading `route_scope` already
    takes: a reply the router cannot parse must go FORWARD rather than wedge a
    run at a gate a human has already answered. `rest` is recorded as the gate
    node's output so a downstream node can reference `${state.out__<gate>}` -
    an author's revise note is the input to the node that acts on it.
    """

    raw = feedback if isinstance(feedback, str) else ""
    try:
        parsed = json.loads(raw) if raw else {}
    except (json.JSONDecodeError, TypeError):
        parsed = {}
    if not isinstance(parsed, Mapping):
        parsed = {}

    decision = str(parsed.get("decision", "approve")).strip().lower()
    rest = {
        str(key): value
        for key, value in parsed.items()
        if str(key) != "decision"
    }
    if not parsed and raw.strip():
        # An unparseable reply is not nothing: the operator typed it, and the
        # node downstream of a revise is the one that needs to read it.
        rest["feedback"] = raw
    return ("revise" if decision == "revise" else "approve"), rest


class BuilderFeedbackProvider(HumanFeedbackProvider):
    """Pause the flow durably; never read a console, never call a model."""

    def request_feedback(
        self,
        context: PendingFeedbackContext,
        flow: Any,
    ) -> str:
        state = getattr(flow, "state", None)
        if isinstance(state, Mapping) and state.get("no_gates"):
            # The same escape hatch `ValidatorFeedbackProvider` has, reached the
            # same way: `no_gates` is a RESERVED run input key, so it can only
            # be set by the service after it has checked
            # VALIDATOR_ALLOW_AUTO_GATES - never by a request body.
            return json.dumps({"decision": "approve"})

        metadata = dict(context.metadata or {})
        node_id = str(metadata.get(GATE_ID_METADATA_KEY, "") or context.method_name)
        # A NEW dict, never a mutation. `_run_human_feedback_step` builds the
        # context with the definition's own metadata object
        # (`metadata=metadata or {}`), and a declarative gate ALWAYS declares
        # metadata - so unlike the validator's decorator, this dict really is
        # shared with every other run of the same compiled flow. Writing in
        # place would leak one operator's gate into another's.
        context.metadata = {
            **metadata,
            GATE_REVISE_TURNS_METADATA_KEY: _turns_used(state, node_id),
        }
        raise HumanFeedbackPending(
            context=context,
            callback_info={"gate": context.method_name, "node_id": node_id},
        )


def _turns_used(state: Any, node_id: str) -> int:
    """Revise turns already spent at this gate, per the flow's durable state.

    Defensive about the value for the same reason `service/registry.py` is
    about the metadata copy of it: this has been through JSON, and a float or a
    numeric string must not raise inside the one call that is about to ask a
    human something.
    """

    if not isinstance(state, Mapping):
        return 0
    try:
        return max(0, int(state.get(f"{_TURNS_PREFIX}{node_id}", 0) or 0))
    except (TypeError, ValueError):
        return 0


#: The one provider ref every compiled gate names. A module-level singleton
#: because `_resolve_instance_ref` returns an instance as-is and only calls a
#: class - either resolves, but an instance keeps identity stable across the
#: two resolutions a paused-then-resumed run performs.
GATE_PROVIDER = BuilderFeedbackProvider()
