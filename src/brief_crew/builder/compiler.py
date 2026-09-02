"""`builder.flow/v1` -> a `crewai.flow/v1` definition that actually runs.

The compiler is the only thing in this package that produces something CrewAI
executes, and almost every rule it enforces was measured on a flow that ran
rather than argued from the schema. Four of them are worth reading before
changing anything here.

**One canvas gate compiles to TWO methods.** A single method that is both the
pause and the router returns a `HumanFeedbackResult`, which is not a valid
event name, so neither branch fires and the run ends silently having produced
nothing - measured, `landed=None`, no exception. So a gate emits the pause and
a paired deterministic router, and consumes two indices in the method
namespace.

**The gate lint is the highest-value check in the file.** `human_feedback.emit`
non-null with `llm: null` makes CrewAI collapse the reply to `emit[0]`
unconditionally: an operator who replies `revise` runs the approve branch, and
CrewAI logs the combination at `severity="error"` and RUNS THE FLOW ANYWAY. So
its own validation cannot be relied on, and `lint_gates` refuses the shape
before anything can execute it.

**Every loop-closing node is a router.** With the loop closer compiled as plain
code, the join fires once, the second arrival is suppressed and `kickoff()`
returns normally having produced nothing. `bounds.py` refuses that document;
this module additionally asserts the compiled shape, because the two agreeing
is the whole guarantee.

**The document carries no `ref`.** Every `do.ref` is picked here from
`BUILDER_ACTION_REFS`, ten compiler-owned entrypoints, and
`assert_action_refs` re-checks the emitted definition against that frozenset.
That assertion IS the code-execution mitigation: author data travels in `with:`
as values, and there is no field anywhere in the document schema that names
code. `call: "script"` is never emitted.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from brief_crew.builder.bounds import (
    Problem,
    back_edge_indices,
    compiled_identifiers,
    has_errors,
)
from brief_crew.builder.budget import estimate_budget
from brief_crew.builder.document import (
    ROUTING_KINDS,
    AgentConfig,
    BuilderBudget,
    BuilderDocument,
    BuilderNode,
    CrewConfig,
    GateConfig,
    InputConfig,
    OutputConfig,
    RouterConfig,
    TransformConfig,
)
from brief_crew.builder.runtime import (
    BUILDABLE_BUILDER_CREW_IDS,
    BUILDER_AGENT_LIBRARY,
    BUILDER_CREW_LIBRARY,
    BUILDER_STATE_KEY,
    BUILDER_STATE_TURNS_PREFIX,
    missing_prompt_inputs,
    unbuildable_crew_reason,
)
from brief_crew.config import (
    BUILDER_ACTION_REFS,
    BUILDER_GATE_ROUTER_PREFIX,
    BUILDER_STATE_OUTPUT_PREFIX,
    GATE_EDITABLE_FIELDS_METADATA_KEY,
    GATE_EXPIRY_METADATA_KEY,
    GATE_LABEL_METADATA_KEY,
    GATE_MAX_TURNS_METADATA_KEY,
    MAX_CYCLE_ITERATIONS,
)

__all__ = [
    "BuilderCompileError",
    "CompiledFlow",
    "FLOW_SCHEMA",
    "GATE_REPLY_INSTRUCTION",
    "assert_action_refs",
    "compile_document",
    "credential_problems",
    "document_problems",
    "library_problems",
    "lint_gates",
]

FLOW_SCHEMA = "crewai.flow/v1"

# The ten refs, named once. Each is asserted against BUILDER_ACTION_REFS at
# import, so a typo here is an ImportError on the first import rather than a
# graph that compiles and then cannot resolve its own action.
_SEED_INPUT = "brief_crew.builder.runtime:seed_input"
_RUN_AGENT = "brief_crew.builder.runtime:run_agent"
_RUN_CREW = "brief_crew.builder.runtime:run_crew"
_RENDER_GATE = "brief_crew.builder.runtime:render_gate"
_GATE_PROVIDER = "brief_crew.builder.gates:GATE_PROVIDER"
_ROUTE_GATE = "brief_crew.builder.runtime:route_gate"
_ROUTE_BRANCH = "brief_crew.builder.runtime:route_branch"
_TRANSFORM = "brief_crew.builder.runtime:transform"
_EMIT_OUTPUT = "brief_crew.builder.runtime:emit_output"

for _ref in (
    _SEED_INPUT,
    _RUN_AGENT,
    _RUN_CREW,
    _RENDER_GATE,
    _GATE_PROVIDER,
    _ROUTE_GATE,
    _ROUTE_BRANCH,
    _TRANSFORM,
    _EMIT_OUTPUT,
):
    if _ref not in BUILDER_ACTION_REFS:
        raise RuntimeError(
            f"{_ref} is not in BUILDER_ACTION_REFS; the compiler may only emit refs "
            "the allowlist declares, and the allowlist is the whole of the "
            "code-execution answer"
        )
del _ref

# What every gate's message ends with, whatever the author wrote. The operator
# has to send a decision the router can read, and the author cannot be relied
# on to document a wire format they never see.
GATE_REPLY_INSTRUCTION = (
    "Reply with JSON: decision=approve, or decision=revise plus feedback."
)

_STATE_REFERENCE = re.compile(r"\$\{state\.([a-z0-9_]{1,64})\}")

# State keys the compiler owns. An input field that collided with one of these
# would let a request body overwrite a node's output or a gate's turn counter.
_RESERVED_STATE_PREFIXES = (BUILDER_STATE_OUTPUT_PREFIX, BUILDER_STATE_TURNS_PREFIX)


class BuilderCompileError(RuntimeError):
    """This document cannot become a flow definition that runs correctly.

    Carries the structural problems when there are any, because the canvas
    shows a list with one entry per offending node and a single sentence would
    throw away everything but the first.
    """

    def __init__(self, message: str, *, problems: Sequence[Problem] = ()) -> None:
        super().__init__(message)
        self.problems: tuple[Problem, ...] = tuple(problems)


@dataclass(frozen=True)
class CompiledFlow:
    """One document, compiled, with everything the service needs beside it."""

    #: The `crewai.flow/v1` document, ready for `Flow.from_declaration`.
    definition: dict[str, Any]
    #: Document node id -> the flow method idents it compiled to. A gate has
    #: two; everything else has one.
    method_idents: Mapping[str, tuple[str, ...]]
    #: The inverse, flattened: compiled method ident -> document node id. This
    #: is exactly `NodeRegistry.flow_method_nodes`, and it is many-to-one
    #: because a gate's pause and its router are one node on the canvas.
    node_ids: Mapping[str, str]
    #: Document node id -> the router event labels it emits, in port order.
    event_labels: Mapping[str, tuple[str, ...]]
    #: Document node id -> the out ports those labels correspond to, same order.
    out_ports: Mapping[str, tuple[str, ...]]
    #: (router method ident, event label) -> target document node id. What
    #: `NodeRegistry.route_targets` needs, and the reason a compiled router's
    #: EDGE_TAKEN frames do not all land in quarantine.
    route_targets: Mapping[tuple[str, str], str]
    #: The compiled method idents that are routers.
    router_methods: frozenset[str]
    #: The static price of this graph, to be stored on the document.
    budget: BuilderBudget

    @property
    def methods(self) -> Mapping[str, Any]:
        """The compiled `methods` block, for a caller that only wants that."""

        return self.definition["methods"]

    @property
    def port_labels(self) -> dict[str, dict[str, str]]:
        """Node id -> {out port: emitted label}, the shape `NodeRegistry` wants.

        `from_document` reads a routing node's ports off the EDGES and looks
        each one up here, so this is the join between what an author drew
        (`source_port: "approve"`) and what CrewAI actually emits
        (`e6_approve`). Without it every `EDGE_TAKEN` frame from a compiled
        router resolves to the quarantine node.
        """

        return {
            node_id: dict(zip(self.out_ports[node_id], labels))
            for node_id, labels in self.event_labels.items()
        }


def compile_document(
    document: BuilderDocument,
    *,
    ceiling_usd: float | None = None,
    credential_check: Callable[[str], bool] | None = None,
) -> CompiledFlow:
    """Compile one document, or refuse it with every reason at once.

    Structure, library and price are checked FIRST, through the same
    `document_problems` every author-facing endpoint calls, because a graph
    that is miswired, unbuildable or unpriceable must never reach a queue slot
    - and because the author's list of problems must be the same list whether
    they pressed Save, Validate or Publish. It was not: `library_problems` ran
    only here, so a document naming an unbuildable crew validated CLEAN and
    then refused to publish, which reads as a broken server rather than as a
    node the author has to change.
    """

    problems = document_problems(
        document, ceiling_usd=ceiling_usd, credential_check=credential_check
    )
    if has_errors(problems):
        blocking = [problem for problem in problems if problem.severity == "error"]
        raise BuilderCompileError(
            f"this graph has {len(blocking)} problem(s) that stop it compiling: "
            + "; ".join(problem.message for problem in blocking[:3]),
            problems=problems,
        )

    plan = _Plan(document)
    methods: dict[str, Any] = {}
    for node in document.nodes:
        methods.update(plan.methods_for(node))

    definition: dict[str, Any] = {
        "schema": FLOW_SCHEMA,
        # Identifier-shaped and derived from the version, so two versions of one
        # document are two flows in a trace rather than one flow that changed
        # shape. The author's own name is the description.
        "name": f"builder_{document.id}_v{document.version}",
        "description": document.name,
        "state": {"type": "dict", "default": plan.state_default()},
        "config": {"max_method_calls": plan.max_method_calls()},
        "methods": methods,
    }

    lint_problems = lint_gates(definition)
    if lint_problems:
        raise BuilderCompileError(
            "the compiled gates are unsafe: " + "; ".join(lint_problems)
        )
    assert_action_refs(definition)
    _assert_namespaces_disjoint(plan.node_ids, plan.all_labels())
    _assert_routers_declare_what_they_emit(definition)

    return CompiledFlow(
        definition=definition,
        method_idents=dict(plan.method_idents),
        node_ids=dict(plan.node_ids),
        event_labels=dict(plan.event_labels),
        out_ports=dict(plan.out_ports),
        route_targets=dict(plan.route_targets),
        router_methods=frozenset(plan.router_methods),
        budget=estimate_budget(document).as_budget(),
    )


# --------------------------------------------------------------------------
# The checks that run over the EMITTED definition
# --------------------------------------------------------------------------
def lint_gates(definition: Mapping[str, Any]) -> list[str]:
    """Every way a compiled `human_feedback` block could silently approve.

    Run over the emitted definition rather than over the document, because the
    document has no gate wire format to be wrong about - the failure this
    guards is a compiler that emits the wrong shape, and only the output can
    show that.

    Returns messages rather than raising so a test can assert on all of them at
    once; `compile_document` raises on anything returned.
    """

    problems: list[str] = []
    for name, method in dict(definition.get("methods", {})).items():
        feedback = method.get("human_feedback") if isinstance(method, Mapping) else None
        if not isinstance(feedback, Mapping):
            continue
        if feedback.get("emit") is not None:
            problems.append(
                f"{name} declares human_feedback.emit={feedback['emit']!r}. With emit set "
                "CrewAI collapses the reply to emit[0] before the router ever sees it, so "
                "an operator who replies 'revise' runs the approve branch - measured end to "
                "end. The decision belongs to the paired router method"
            )
        if "llm" not in feedback:
            problems.append(
                f"{name} omits human_feedback.llm. The schema default is the STRING "
                "'gpt-4o-mini', and it is deserialized before emit is even checked, so an "
                "omitted key buys a real model client per gate for a path that cannot use it"
            )
        elif feedback.get("llm") is not None:
            problems.append(
                f"{name} declares human_feedback.llm={feedback['llm']!r}; a builder gate "
                "never collapses a reply with a model, so naming one is spend with no effect"
            )
        if feedback.get("default_outcome") is not None:
            problems.append(
                f"{name} declares a default_outcome, which only means anything alongside "
                "emit; with emit null it is an outcome nothing can select"
            )
        if feedback.get("provider") != _GATE_PROVIDER:
            problems.append(
                f"{name} declares provider={feedback.get('provider')!r} and must declare "
                f"{_GATE_PROVIDER!r}. Without it the engine falls through to a blocking "
                "input() on a worker thread with no console attached"
            )
    return problems


def assert_action_refs(definition: Mapping[str, Any]) -> None:
    """Every emitted `do` is a `code` call at a ref the allowlist declares.

    The document has no ref field, so nothing an author writes can reach here -
    which is exactly why this is an assertion over the OUTPUT. It is the last
    place a compiler bug could turn author data into an import path, and it
    costs one pass over a dict.
    """

    for name, method in dict(definition.get("methods", {})).items():
        action = method.get("do") if isinstance(method, Mapping) else None
        if not isinstance(action, Mapping):
            raise BuilderCompileError(f"{name} compiled without a do action")
        call = action.get("call")
        if call != "code":
            raise BuilderCompileError(
                f"{name} compiled to a {call!r} action; the compiler emits only code "
                "actions, and 'script' in particular is unsandboxed by CrewAI's own "
                "admission"
            )
        ref = action.get("ref")
        if ref not in BUILDER_ACTION_REFS:
            raise BuilderCompileError(
                f"{name} compiled to the ref {ref!r}, which is not one of the "
                f"{len(BUILDER_ACTION_REFS)} entrypoints in BUILDER_ACTION_REFS"
            )
        feedback = method.get("human_feedback")
        if isinstance(feedback, Mapping) and feedback.get("provider") not in BUILDER_ACTION_REFS:
            raise BuilderCompileError(
                f"{name} declares the provider {feedback.get('provider')!r}, which is not "
                "in BUILDER_ACTION_REFS"
            )


def _assert_namespaces_disjoint(
    node_ids: Mapping[str, str], labels: Iterable[str]
) -> None:
    """Method idents and router labels must not share a name.

    Every method starts `n` and every label starts `e`, so this cannot fire
    today. It is here because that guarantee is a property of the generator
    rather than of the design, and a name in both namespaces is a listener
    firing on the wrong thing - which produces a wrong run, not an error.
    """

    collisions = sorted(set(node_ids) & set(labels))
    if collisions:
        raise BuilderCompileError(
            "compiled flow method names and router event labels share "
            + ", ".join(collisions)
        )


def _assert_routers_declare_what_they_emit(definition: Mapping[str, Any]) -> None:
    """Every declared router label is listened for by at least one method.

    A router returning a string nothing listens on ends the flow with no error
    at all - measured: `route()` returned 'fail' while the successor listened
    on 'route_fail', and `kickoff()` returned 'fail' having run nothing else.
    The runtime validates neither direction, so this does.

    A declared label with no listener is legal - it is how a graph ends early,
    and `bounds.py` already warns about it - so this checks the dangerous
    direction only: a label a method LISTENS for must be produced by something.
    """

    methods = dict(definition.get("methods", {}))
    produced = set(methods)
    for method in methods.values():
        produced.update(method.get("emit") or ())
    for name, method in methods.items():
        for event in _condition_events(method.get("listen")):
            if event not in produced:
                raise BuilderCompileError(
                    f"{name} listens for {event!r}, which no method emits and no method "
                    "is called. A trigger nothing produces is a node that never runs"
                )


def _condition_events(condition: Any) -> list[str]:
    """Every event name inside a `listen` condition, at any nesting."""

    if condition is None:
        return []
    if isinstance(condition, str):
        return [condition]
    if isinstance(condition, Mapping):
        found: list[str] = []
        for branch in condition.values():
            for item in branch if isinstance(branch, (list, tuple)) else [branch]:
                found += _condition_events(item)
        return found
    return []


# --------------------------------------------------------------------------
# The plan - one pass over the document, then one method per index
# --------------------------------------------------------------------------
class _Plan:
    """The names, events and edges of one document, computed once.

    Kept as a class rather than threaded through a dozen functions because
    every method below needs the same four maps, and building them twice is how
    the compiled namespace and the namespace `bounds.py` checked drift apart.
    """

    def __init__(self, document: BuilderDocument) -> None:
        self.document = document
        self.nodes = document.nodes_by_id()

        self.method_idents: dict[str, tuple[str, ...]] = {}
        self.routing_index: dict[str, int] = {}
        index = 0
        for node in document.nodes:
            own = [f"n{index}_{node.id}"]
            self.routing_index[node.id] = index
            index += 1
            if node.kind == "gate":
                self.routing_index[node.id] = index
                own.append(f"n{index}_{BUILDER_GATE_ROUTER_PREFIX}{node.id}")
                index += 1
            self.method_idents[node.id] = tuple(own)

        # The generator above must agree with the one `bounds.py` asserted the
        # disjointness of. Two generators for one namespace is the drift this
        # whole check exists to prevent, so they are compared rather than
        # trusted.
        declared, _ = compiled_identifiers(document)
        if declared != self.method_idents:
            raise BuilderCompileError(
                "the compiler and bounds.compiled_identifiers disagree about the "
                "compiled method names; the namespace guarantee is only worth what "
                "those two agreeing makes it"
            )

        self.node_ids: dict[str, str] = {
            ident: node_id
            for node_id, idents in self.method_idents.items()
            for ident in idents
        }
        self.out_ports: dict[str, tuple[str, ...]] = {
            node.id: tuple(node.out_ports)
            for node in document.nodes
            if node.kind in ROUTING_KINDS
        }
        self.event_labels: dict[str, tuple[str, ...]] = {
            node_id: tuple(f"e{self.routing_index[node_id]}_{port}" for port in ports)
            for node_id, ports in self.out_ports.items()
        }
        self.router_methods: set[str] = {
            self.method_idents[node.id][-1]
            for node in document.nodes
            if node.kind in ROUTING_KINDS
        }

        back = set(back_edge_indices(document))
        self.route_targets: dict[tuple[str, str], str] = {}
        self.normal_events: dict[str, list[str]] = {}
        self.loop_events: dict[str, list[str]] = {}
        self.rearm: dict[str, list[str]] = {}
        for position, edge in enumerate(document.edges):
            source = self.nodes[edge.source]
            event = (
                f"{self._label(source.id, edge.source_port)}"
                if source.kind in ROUTING_KINDS
                else self.method_idents[source.id][0]
            )
            if source.kind in ROUTING_KINDS:
                self.route_targets[(self.method_idents[source.id][-1], event)] = edge.target
            bucket = self.loop_events if position in back else self.normal_events
            bucket.setdefault(edge.target, []).append(event)
            if position in back:
                # The target's condition becomes a multi-event `or_()`, and
                # such a listener is fired once and skipped forever after. The
                # router that re-enters it re-arms it first.
                self.rearm.setdefault(source.id, []).append(
                    self.method_idents[edge.target][0]
                )

    # ---------------------------------------------------------------- naming
    def _label(self, node_id: str, port: str) -> str:
        return f"e{self.routing_index[node_id]}_{port}"

    def all_labels(self) -> list[str]:
        return [label for labels in self.event_labels.values() for label in labels]

    # --------------------------------------------------------------- methods
    def methods_for(self, node: BuilderNode) -> dict[str, Any]:
        """The one or two flow methods this node compiles to."""

        ident = self.method_idents[node.id][0]
        method: dict[str, Any] = {"description": node.label}
        listen = self._listen_for(node)
        if listen is None:
            method["start"] = True
        else:
            method["listen"] = listen

        config = node.config
        if isinstance(config, InputConfig):
            method["do"] = self._action(
                _SEED_INPUT,
                {
                    "node_id": node.id,
                    "field": config.field,
                    "max_chars": config.max_chars,
                    "required": config.required,
                },
            )
        elif isinstance(config, AgentConfig):
            method["do"] = self._action(
                _RUN_AGENT,
                {
                    "node_id": node.id,
                    "agent_id": config.agent_id,
                    "tier": config.tier,
                    "tools": list(config.tools),
                    "max_iter": config.max_iter,
                    "guardrail_max_retries": config.guardrail_max_retries,
                    "prompt_inputs": dict(config.prompt_inputs),
                    # The ID and only the id (C5). The runtime resolves it
                    # inside `run_agent`, scoped to the run's owner; the
                    # definition, the trace and the store never see a key.
                    # Omitted rather than `null` when unset, so a document
                    # that names no credential compiles byte-identical to
                    # what it compiled to before the field existed.
                    **(
                        {"credential_id": config.credential_id}
                        if config.credential_id
                        else {}
                    ),
                },
            )
        elif isinstance(config, CrewConfig):
            method["do"] = self._action(
                _RUN_CREW,
                {
                    "node_id": node.id,
                    "crew_id": config.crew_id,
                    "tier": config.tier,
                    "max_iter": config.max_iter,
                    "guardrail_max_retries": config.guardrail_max_retries,
                    "prompt_inputs": dict(config.prompt_inputs),
                },
            )
        elif isinstance(config, GateConfig):
            return {ident: self._gate_method(node, config, method), **self._gate_router(node, config)}
        elif isinstance(config, RouterConfig):
            method["router"] = True
            method["emit"] = list(self.event_labels[node.id])
            method["do"] = self._action(
                _ROUTE_BRANCH,
                {
                    "node_id": node.id,
                    "rules": [
                        {
                            "label": self._label(node.id, branch.label),
                            "op": branch.op,
                            "key": branch.key,
                            "value": _literal(branch.value, where=f"{node.id}.{branch.label}"),
                        }
                        for branch in config.branches
                    ],
                    "rearm": self.rearm.get(node.id, []),
                    "source": self._inbound_source(node),
                },
            )
        elif isinstance(config, TransformConfig):
            method["do"] = self._action(
                _TRANSFORM,
                {"node_id": node.id, "op": config.op, "args": dict(config.args)},
            )
        elif isinstance(config, OutputConfig):
            method["do"] = self._action(
                _EMIT_OUTPUT,
                {
                    "node_id": node.id,
                    "body_key": config.body_key,
                    "source": config.source,
                },
            )
        else:  # pragma: no cover - the seven kinds are exhaustive
            raise BuilderCompileError(f"node {node.id!r} has no compiled shape")
        return {ident: method}

    def _gate_method(
        self, node: BuilderNode, config: GateConfig, method: dict[str, Any]
    ) -> dict[str, Any]:
        method["do"] = self._action(
            _RENDER_GATE,
            {
                "node_id": node.id,
                "source": self._inbound_source(node),
                "editable_fields": list(config.editable_fields),
            },
        )
        message = config.message.strip()
        method["human_feedback"] = {
            "message": f"{message} {GATE_REPLY_INSTRUCTION}",
            # All four values are emitted EXPLICITLY, including the two nulls.
            # `llm` especially: its schema default is the string "gpt-4o-mini",
            # so an omitted key is a paid client per gate, and `emit` non-null
            # is the silent-approval trap `lint_gates` exists for.
            "emit": None,
            "llm": None,
            "provider": _GATE_PROVIDER,
            "default_outcome": None,
            # Everything the SERVICE needs to describe this gate to an
            # operator, because `metadata` is the only thing that travels with
            # the pause. `service/registry.py` builds the gate prompt from a
            # `PendingFeedbackContext` and nothing else - it never sees the
            # document - so a value that is not here is a value it has to
            # assume, and every one of these four was an assumption borrowed
            # from the validator: the label became "Review verdict",
            # `editable_fields` was ignored and the whole payload offered as a
            # text box, `max_turns` became 5 while `route_gate` honoured this
            # one, and `expiry_seconds` was authored, range-validated and read
            # by nothing at all.
            "metadata": {
                "gate_id": node.id,
                "canvas_node": node.id,
                GATE_LABEL_METADATA_KEY: node.label,
                GATE_EDITABLE_FIELDS_METADATA_KEY: list(config.editable_fields),
                GATE_MAX_TURNS_METADATA_KEY: config.max_turns,
                GATE_EXPIRY_METADATA_KEY: config.expiry_seconds,
            },
        }
        return method

    def _gate_router(self, node: BuilderNode, config: GateConfig) -> dict[str, Any]:
        """The paired router: the half that reads the operator's actual decision."""

        gate_ident, router_ident = self.method_idents[node.id]
        return {
            router_ident: {
                "description": f"{node.label}: route the operator's decision",
                "listen": gate_ident,
                "router": True,
                "emit": list(self.event_labels[node.id]),
                # NO `with:` block, deliberately. `CodeAction.run` calls
                # `handler(**rendered)` whenever one is present, which DROPS the
                # positional `HumanFeedbackResult` - the router would then route
                # on nothing at all. Its node id, labels and turn cap travel in
                # the compiled state table instead, keyed by this method name.
                "do": {"call": "code", "ref": _ROUTE_GATE},
            }
        }

    def _inbound_source(self, node: BuilderNode) -> Any:
        """What flowed INTO this node, as one reference or an ordered list.

        A gate shows it; a router passes it through. One predecessor gives one
        reference. Several give a LIST, and the runtime takes the last entry
        that has a value - which is what makes a revise loop show the revision.
        On the first pass the revise branch has not run and its output is still
        null, so the gate shows the original; on the second it has, and the
        gate shows what the operator asked for. Picking statically would show
        the stale one forever.
        """

        back = set(back_edge_indices(self.document))
        normal: list[str] = []
        looped: list[str] = []
        for position, edge in enumerate(self.document.edges):
            if edge.target != node.id or edge.source not in self.nodes:
                continue
            bucket = looped if position in back else normal
            if edge.source not in bucket:
                bucket.append(edge.source)
        ordered = [source for source in normal + looped]
        references = [
            f"${{state.{BUILDER_STATE_OUTPUT_PREFIX}{source}}}" for source in ordered
        ]
        if not references:
            return None
        return references[0] if len(references) == 1 else references

    def _action(self, ref: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
        return {"call": "code", "ref": ref, "with": dict(arguments)}

    # ---------------------------------------------------------------- listen
    def _listen_for(self, node: BuilderNode) -> Any:
        """This node's trigger condition, or None when it is a start method.

        A node the document DECLARES as a join waits for all of its
        predecessors: `{"and": [...]}`, which `_is_multi_event_or` reads as
        false, so a fan-in is never the listener CrewAI suppresses. That is why
        `join: "any"` is cut from the schema - there is no such thing as a
        waiting-for-either fan-in that survives its second arrival.

        A node with several predecessors and NO declared join is the other
        shape entirely: alternatives. Two branches of one router converging on
        one output are mutually exclusive, and compiling them as `and` would
        deadlock the most ordinary graph anyone draws - the output would wait
        forever for the branch that was not taken, with no error. So they
        compile to alternatives, and the suppression is not reachable from
        here: each alternative is a router label, only one of them fires per
        pass, and CrewAI re-arms an or-listener whose condition names the label
        a router just emitted.

        A back edge adds its label to those alternatives, which is the rejoin
        shape the taxonomy declares.
        """

        normal = _deduplicated(self.normal_events.get(node.id, []))
        loops = _deduplicated(self.loop_events.get(node.id, []))
        if not normal and not loops:
            return None
        declared_join = self.document.joins.get(node.id) == "all"
        if declared_join and normal:
            base: Any = {"and": normal}
            return base if not loops else {"or": [base, *loops]}
        alternatives = normal + [event for event in loops if event not in normal]
        if len(alternatives) == 1:
            return alternatives[0]
        return {"or": alternatives}

    # ----------------------------------------------------------------- state
    def state_default(self) -> dict[str, Any]:
        """The initial state, with every key any `with:` block can reference.

        Pre-seeding is not tidiness. CEL raises
        `no such member in mapping: 'x'` on a key that is absent, so a
        `${state.out__scoper}` rendered before the Scoper has run - which is
        exactly what happens on the revise side of a loop - would fail the
        method rather than render empty.
        """

        default: dict[str, Any] = {}
        for node in self.document.nodes:
            default[f"{BUILDER_STATE_OUTPUT_PREFIX}{node.id}"] = None
            if isinstance(node.config, InputConfig):
                default.setdefault(_checked_field(node.config.field), "")
            if isinstance(node.config, GateConfig):
                default[f"{BUILDER_STATE_TURNS_PREFIX}{node.id}"] = 0

        for referenced in sorted(self._referenced_state_keys()):
            if referenced.startswith(BUILDER_STATE_OUTPUT_PREFIX):
                node_id = referenced[len(BUILDER_STATE_OUTPUT_PREFIX) :]
                if node_id not in self.nodes:
                    raise BuilderCompileError(
                        f"a node references ${{state.{referenced}}} and no node has the id "
                        f"{node_id!r}. A reference to a node that is not there renders as "
                        "nothing, and the agent downstream would be asked to work from a "
                        "blank with nothing saying why"
                    )
            default.setdefault(referenced, None)

        default[BUILDER_STATE_KEY] = {
            "document": {
                "id": self.document.id,
                "version": self.document.version,
                "input_field": self.document.input_field,
            },
            "gates": {
                self.method_idents[node.id][1]: {
                    "node_id": node.id,
                    "approve": self._label(node.id, "approve"),
                    "revise": self._label(node.id, "revise"),
                    "max_turns": node.config.max_turns,
                    "rearm": self.rearm.get(node.id, []),
                }
                for node in self.document.nodes
                if isinstance(node.config, GateConfig)
            },
        }
        return default

    def _referenced_state_keys(self) -> set[str]:
        """Every `${state.<key>}` any node config mentions."""

        found: set[str] = set()
        for node in self.document.nodes:
            for value in _scalar_values(node.config.model_dump()):
                if isinstance(value, str):
                    found.update(_STATE_REFERENCE.findall(value))
        return found

    def max_method_calls(self) -> int:
        """The per-method runaway backstop, sized to the cycles that are legal.

        CrewAI counts this PER METHOD, so it is a loop bound and not a graph
        size bound. A node inside two nested cycles can legitimately run
        `(1 + MAX_CYCLE_ITERATIONS)` times per outer iteration, which is where
        the exponent comes from; with no cycles at all every method runs once
        and the value is only a backstop.
        """

        cycles = max(1, len(back_edge_indices(self.document)))
        return (1 + MAX_CYCLE_ITERATIONS) ** cycles


def _deduplicated(events: Sequence[str]) -> list[str]:
    """The events in document order, each once.

    Two edges from one port to one node are one trigger; listing it twice in an
    `and` would make a join wait for an arrival that can never come separately.
    """

    seen: dict[str, None] = {}
    for event in events:
        seen.setdefault(event, None)
    return list(seen)


def _scalar_values(value: Any) -> list[Any]:
    """Every leaf of a nested config dump."""

    if isinstance(value, Mapping):
        return [leaf for item in value.values() for leaf in _scalar_values(item)]
    if isinstance(value, (list, tuple)):
        return [leaf for item in value for leaf in _scalar_values(item)]
    return [value]


def _literal(value: Any, *, where: str) -> Any:
    """A comparison operand, refused if it is trying to be an expression.

    `RouterBranch.value` is the one author-supplied scalar the document schema
    does not run through its `${` check, and everything in a compiled `with:`
    block is CEL-rendered. CEL here can only reach `state` and `outputs`, so
    this is not an execution surface - but a comparison operand that quietly
    reads a different state key than it appears to is a router that lies about
    its own rule.
    """

    if isinstance(value, str) and "${" in value:
        raise BuilderCompileError(
            f"the router branch {where} compares against {value!r}, which reads as an "
            "expression. A comparison operand is a literal; reference state with the "
            "branch's `key` instead"
        )
    return value


def _checked_field(field: str) -> str:
    """An input field name that cannot collide with a key the compiler owns."""

    if field == BUILDER_STATE_KEY or field.startswith(_RESERVED_STATE_PREFIXES):
        raise BuilderCompileError(
            f"the input field {field!r} collides with a state key the compiler owns "
            f"({BUILDER_STATE_KEY}, {BUILDER_STATE_OUTPUT_PREFIX}*, "
            f"{BUILDER_STATE_TURNS_PREFIX}*). A request input under that name would "
            "overwrite a node's output or a gate's turn counter"
        )
    return field


def document_problems(
    document: BuilderDocument,
    *,
    ceiling_usd: float | None = None,
    credential_check: Callable[[str], bool] | None = None,
) -> list[Problem]:
    """Every reason this document may not be published. The whole list.

    `validate_document` answers about structure and price and deliberately does
    not ask whether THIS deployment can build what the document names - that
    question needs the agent and crew libraries, and every fixture in
    `tests/builder/` wires a realistic topology out of placeholder ids. This is
    the composition, and it is what an author actually meets:
    `/api/builder/validate`, the saved-document view, and `compile_document`
    below all call it, so all three answer with one list.

    Composed here rather than folded into `validate_document` for the import
    direction as much as the fixtures: this module already reaches back into
    `brief_crew.builder`, and having that package reach forward into this one
    would close the cycle.
    """

    # Imported inside the function rather than at module scope:
    # `brief_crew.builder` is the package this module lives in, and a top-level
    # import would make adding the compiler to its `__init__` a circular
    # import.
    from brief_crew.builder import validate_document

    problems = validate_document(document, ceiling_usd=ceiling_usd) + library_problems(document)
    # Only with an identity to check against (plan 01 D10). `None` means the
    # caller is anonymous, and the ABSENCE of a check is reported by the
    # endpoint as `identity_checked: false` rather than passed off as a clean
    # answer.
    if credential_check is not None:
        problems += credential_problems(document, owned=credential_check)
    return problems


#: The three ways a node can name work this service cannot do. Separate codes
#: rather than one, because the canvas groups by code and these are three
#: different repairs: pick another id, fill a prompt input, or pick a crew that
#: can actually be constructed.
LIBRARY_UNKNOWN = "library-unknown-id"
LIBRARY_PROMPT_INPUT = "library-missing-prompt-input"
LIBRARY_UNBUILDABLE = "library-unbuildable-crew"

#: A credential id that is not one of the caller's (C8, plan 01 D6/D10). One
#: code for absent and foreign, because the vault answers the two with one
#: exception and a canvas that could tell them apart would be an oracle for
#: other people's ids.
CREDENTIAL_MISSING = "credential-missing"


def credential_problems(
    document: BuilderDocument, *, owned: Callable[[str], bool]
) -> list[Problem]:
    """Every credential reference `owned` does not vouch for.

    `owned` is the caller's identity as a predicate - typically the vault's
    `exists(user_id, credential_id)` - and this function never touches the
    vault itself, so the compiler stays importable without the service
    package and a test can prove the check with a lambda. The document
    schema has already checked the id's spelling; what is asked here is only
    whether it names a row this person may use.
    """

    problems: list[Problem] = []
    for node in document.nodes:
        config = node.config
        credential_id = getattr(config, "credential_id", None)
        if not credential_id or owned(credential_id):
            continue
        problems.append(
            Problem(
                code=CREDENTIAL_MISSING,
                severity="error",
                message=(
                    f"{node.id} names the credential {credential_id}, which is not "
                    "in your vault; pick one of your own or create it first"
                ),
                node_id=node.id,
            )
        )
    return problems


def library_problems(document: BuilderDocument) -> list[Problem]:
    """Agent and crew ids this runtime cannot build, and prompts left unfilled.

    Checked before anything runs because the alternative is finding out at the
    first paid run: CrewAI interpolates a task's `{placeholders}` inside
    `kickoff`, after every upstream node has already been billed for the
    context this one was going to use.

    `document_problems` calls this - NOT `validate_document`, which deliberately
    answers about structure and price alone and knows nothing about this
    deployment's libraries - and that is why this returns `Problem` rather than
    strings. It used to run only inside `compile_document`, so the canvas -
    which polls `/api/builder/validate` on every edit - reported a document with
    an unbuildable node as CLEAN and the author met the refusal only on Publish.
    Every problem carries its `node_id`, so what the author gets is a rim on the
    node rather than a sentence in a list.
    """

    problems: list[Problem] = []
    for node in document.nodes:
        config = node.config
        if isinstance(config, AgentConfig):
            if config.agent_id not in BUILDER_AGENT_LIBRARY:
                problems.append(
                    Problem(
                        code=LIBRARY_UNKNOWN,
                        severity="error",
                        message=(
                            f"{node.id} names the agent {config.agent_id!r}; the registered "
                            f"agents are {', '.join(sorted(BUILDER_AGENT_LIBRARY))}"
                        ),
                        node_id=node.id,
                    )
                )
                continue
            missing = missing_prompt_inputs(config.agent_id, config.prompt_inputs)
            if missing:
                problems.append(
                    Problem(
                        code=LIBRARY_PROMPT_INPUT,
                        severity="error",
                        message=(
                            f"{node.id} runs {config.agent_id!r}, whose task needs "
                            f"{', '.join(missing)} and this node does not supply "
                            f"{'it' if len(missing) == 1 else 'them'}"
                        ),
                        node_id=node.id,
                    )
                )
        elif isinstance(config, CrewConfig):
            if config.crew_id not in BUILDER_CREW_LIBRARY:
                problems.append(
                    Problem(
                        code=LIBRARY_UNKNOWN,
                        severity="error",
                        message=(
                            f"{node.id} names the crew {config.crew_id!r}; the registered "
                            f"crews are {', '.join(sorted(BUILDABLE_BUILDER_CREW_IDS))}"
                        ),
                        node_id=node.id,
                    )
                )
                continue
            # Registered is not the same as buildable. `SynthesisCrew` and
            # `ReportCrew` take typed findings at construction, so
            # `DefaultCrewFactories.crew`'s zero-argument call raised a bare
            # TypeError - and it raised it at the moment that node RAN, after
            # every upstream node had billed. A document naming one of them
            # validated clean, published clean, was priced and was registered.
            # It is refused here instead, for the same reason
            # `missing_prompt_inputs` is refused here.
            reason = unbuildable_crew_reason(config.crew_id)
            if reason is not None:
                problems.append(
                    Problem(
                        code=LIBRARY_UNBUILDABLE,
                        severity="error",
                        message=f"{node.id}: {reason}",
                        node_id=node.id,
                    )
                )
    return problems
