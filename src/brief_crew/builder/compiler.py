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
    attachment_edges,
    back_edge_indices,
    compiled_identifiers,
    error_router_labels,
    has_errors,
    is_routed,
    member_edges,
    member_of,
    nodes_on_cycles,
    routes_errors,
    step_nodes,
)
from brief_crew.builder.budget import estimate_budget
from brief_crew.builder.document import (
    ATTACHMENT_KINDS,
    ROUTING_KINDS,
    AuthoredAgentConfig,
    AuthoredCrewConfig,
    LibraryAgentConfig,
    BuilderBudget,
    BuilderDocument,
    BuilderNode,
    LibraryCrewConfig,
    GateConfig,
    InputConfig,
    McpConfig,
    OutputConfig,
    RouterConfig,
    SkillConfig,
    ToolConfig,
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
    BUILDER_ERROR_ROUTER_PREFIX,
    BUILDER_GATE_ROUTER_PREFIX,
    BUILDER_ROUTER_OTHERWISE,
    BUILDER_STATE_ERROR_PREFIX,
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
    "ReplayPlan",
    "compile_replay_plan",
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
_REPLAY_OUTPUT = "brief_crew.builder.runtime:replay_output"

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
    _REPLAY_OUTPUT,
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


@dataclass(frozen=True)
class ReplayPlan:
    """Which node a derived plan stops at, and where the replayed values come from.

    09 D7. `resume_from` re-enters a saved run at `node_id`, so everything
    UPSTREAM is replayed and everything downstream runs for real. `node_test`
    exercises `node_id` alone, so everything upstream is replayed and everything
    DOWNSTREAM is not compiled at all - a node test that ran the rest of the
    graph would be a run, and would bill like one.
    """

    node_id: str
    #: `resume_from` keeps the downstream; `node_test` drops it.
    mode: str = "resume_from"
    #: `run` reads the source run's last `flow_states` row; `test_input` reads
    #: the saved test input's mocked values (C7).
    source: str = "run"

    @property
    def drops_downstream(self) -> bool:
        return self.mode == "node_test"


def compile_document(
    document: BuilderDocument,
    *,
    ceiling_usd: float | None = None,
    credential_check: Callable[[str], bool] | None = None,
    replay: ReplayPlan | None = None,
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

    plan = _Plan(document, replay=replay)
    methods: dict[str, Any] = {}
    for node in plan.steps:
        if node.id in plan.dropped:
            continue
        methods.update(plan.methods_for(node))

    name = f"builder_{document.id}_v{document.version}"
    if replay is not None:
        name = f"{name}_replay_{replay.node_id}"
    definition: dict[str, Any] = {
        "schema": FLOW_SCHEMA,
        # Identifier-shaped and derived from the version, so two versions of one
        # document are two flows in a trace rather than one flow that changed
        # shape. The author's own name is the description.
        "name": name,
        "description": document.name,
        "state": plan.state_block(),
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
    _assert_methods_cover_the_kept_namespace(definition, plan.method_idents, plan.dropped)
    _assert_routers_declare_what_they_emit(definition)

    # A DROPPED node has no methods, so it has no entry in any of these maps.
    # The plan keeps them all - `compiled_identifiers` is compared against the
    # whole namespace, and the namespace is a property of the document rather
    # than of one derived plan - but what a caller receives has to describe the
    # definition it was handed.
    kept = [node_id for node_id in plan.method_idents if node_id not in plan.dropped]
    return CompiledFlow(
        definition=definition,
        method_idents={node_id: plan.method_idents[node_id] for node_id in kept},
        node_ids={
            ident: node_id for node_id in kept for ident in plan.method_idents[node_id]
        },
        event_labels={
            node_id: labels
            for node_id, labels in plan.event_labels.items()
            if node_id not in plan.dropped
        },
        out_ports={
            node_id: ports
            for node_id, ports in plan.out_ports.items()
            if node_id not in plan.dropped
        },
        route_targets={
            key: target
            for key, target in plan.route_targets.items()
            if key[0] not in plan._suppressed and target not in plan.dropped
        },
        router_methods=frozenset(
            ident for ident in plan.router_methods if ident not in plan._suppressed
        ),
        budget=estimate_budget(document).as_budget(),
    )


def compile_replay_plan(
    document: BuilderDocument,
    *,
    node_id: str,
    mode: str = "resume_from",
    source: str = "run",
    ceiling_usd: float | None = None,
    credential_check: Callable[[str], bool] | None = None,
) -> CompiledFlow:
    """The DERIVED plan for a resume or a node test (09 D7).

    The same document, in which every node upstream of `node_id` compiles to
    `runtime:replay_output` instead of to the entrypoint that would have billed.
    The entrypoint writes `out__<node>` from the saved source and returns, so
    every downstream listener fires exactly as it would after a real run - the
    flow engine cannot tell the difference, which is the point.

    Nothing here touches CrewAI's own resume: `Flow.from_pending` stays what it
    is for gates. A derived plan is compiled fresh per request and is never
    published, never priced onto a document and never rehydrated at boot.
    """

    if node_id not in {node.id for node in step_nodes(document)}:
        raise BuilderCompileError(
            f"no step node has the id {node_id!r}; a replay point is a node the run "
            "actually visits, which an attachment and a crew member are not"
        )
    if mode not in ("resume_from", "node_test"):
        raise BuilderCompileError(
            f"unknown replay mode {mode!r}; a derived plan is a resume_from or a node_test"
        )
    return compile_document(
        document,
        ceiling_usd=ceiling_usd,
        credential_check=credential_check,
        replay=ReplayPlan(node_id=node_id, mode=mode, source=source),
    )


def replay_ancestors(
    document: BuilderDocument,
    node_id: str,
    *,
    step_ids: frozenset[str] | None = None,
) -> frozenset[str]:
    """Every step node a derived plan would REPLAY for `node_id` - 09 D7.

    Public because the question is asked outside the compiler too: the service
    has to know, before it spends a queue slot, whether the replay it is about
    to compile needs something the source run never recorded - a gate's
    decision, most of all.

    Attachment and member edges are excluded, which is the whole reason this
    walks the flow edges rather than `document.edges`: a tool is not upstream of
    the agent that holds it, and replaying one would be replaying a possession.
    """

    ids = step_ids if step_ids is not None else frozenset(
        node.id for node in step_nodes(document)
    )
    incoming: dict[str, list[str]] = {}
    for edge in document.edges:
        if edge.target_port != "in":
            continue
        if edge.source not in ids or edge.target not in ids:
            continue
        incoming.setdefault(edge.target, []).append(edge.source)
    seen: set[str] = set()
    queue = list(incoming.get(node_id, ()))
    while queue:
        current = queue.pop()
        if current in seen or current == node_id:
            continue
        seen.add(current)
        queue.extend(incoming.get(current, ()))
    return frozenset(seen)


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


def _assert_methods_cover_the_kept_namespace(
    definition: Mapping[str, Any],
    method_idents: Mapping[str, tuple[str, ...]],
    dropped: frozenset[str],
) -> None:
    """A node the plan KEEPS emits every method its name reserves.

    The invariant a derived plan broke, stated directly. A gate reserves TWO
    idents - the pause and the paired deterministic router - and a replay that
    emitted only the first left the router's labels produced by nothing at all.

    `_assert_routers_declare_what_they_emit` below catches that too, but from
    the other side and only by luck: it fires when some kept method happens to
    listen for one of the vanished labels. A routed node at the END of a
    derived plan, or one whose only successor was dropped by a node test, would
    disappear in silence and the run would simply stop early. This asks the
    question the other way round, so the next shape that loses a method fails a
    compile rather than a run.

    `dropped` is the node test's own answer to "compile only the target and its
    ancestors" and is exempt by construction - those nodes have no methods
    because the plan deliberately did not emit them.
    """

    methods = set(definition.get("methods", {}))
    missing = sorted(
        ident
        for node_id, idents in method_idents.items()
        if node_id not in dropped
        for ident in idents
        if ident not in methods
    )
    if missing:
        raise BuilderCompileError(
            "the compiled flow is missing "
            + ", ".join(missing)
            + ". Every node this plan keeps reserves its own method names, and a "
            "reserved name with no method is a router whose labels nothing produces"
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

    def __init__(
        self, document: BuilderDocument, *, replay: "ReplayPlan | None" = None
    ) -> None:
        self.document = document
        self.nodes = document.nodes_by_id()
        self.replay = replay

        # The two families that are NOT steps, folded rather than emitted
        # (09 D2). `bounds.py` already refuses the shapes that would make this
        # ambiguous - an attach edge that does not reach an agent, a member
        # agent wired into the flow - and this asserts them again on the plan,
        # because two independent checks agreeing is the whole guarantee.
        self.member_of: dict[str, str] = member_of(document)
        self.members: dict[str, list[str]] = {}
        for edge in member_edges(document):
            self.members.setdefault(edge.target, []).append(edge.source)
        self.attached: dict[str, list[str]] = {}
        for edge in attachment_edges(document):
            self.attached.setdefault(edge.target, []).append(edge.source)
        self.steps: tuple[BuilderNode, ...] = step_nodes(document)
        self.step_ids: frozenset[str] = frozenset(node.id for node in self.steps)
        self._assert_folded_nodes_are_not_steps()

        # The derived replay plan (09 D7), computed before anything is named so
        # the dropped half never reaches the namespace at all.
        self.replayed: frozenset[str] = frozenset()
        self.dropped: frozenset[str] = frozenset()
        if replay is not None:
            upstream = self._ancestors(replay.node_id)
            self.replayed = upstream
            if replay.drops_downstream:
                self.dropped = frozenset(
                    node.id
                    for node in self.steps
                    if node.id != replay.node_id and node.id not in upstream
                )

        self.method_idents: dict[str, tuple[str, ...]] = {}
        self.routing_index: dict[str, int] = {}
        index = 0
        for node in self.steps:
            own = [f"n{index}_{node.id}"]
            self.routing_index[node.id] = index
            index += 1
            if node.kind == "gate":
                self.routing_index[node.id] = index
                own.append(f"n{index}_{BUILDER_GATE_ROUTER_PREFIX}{node.id}")
                index += 1
            elif routes_errors(node):
                self.routing_index[node.id] = index
                own.append(f"n{index}_{BUILDER_ERROR_ROUTER_PREFIX}{node.id}")
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
        # A ROUTED node is one that compiles a router - a gate, a router, or a
        # node whose `on_error` is `route`. The third emits `ok`/`error` rather
        # than its port names, so the labels are asked for per node instead of
        # derived from the ports.
        self.out_ports: dict[str, tuple[str, ...]] = {
            node.id: tuple(node.out_ports) for node in self.steps if is_routed(node)
        }
        self.event_labels: dict[str, tuple[str, ...]] = {
            node.id: tuple(
                f"e{self.routing_index[node.id]}_{label}"
                for label in (error_router_labels(node) or node.out_ports)
            )
            for node in self.steps
            if is_routed(node)
        }
        self.router_methods: set[str] = {
            self.method_idents[node.id][-1] for node in self.steps if is_routed(node)
        }
        # Every name a DROPPED node would have produced. A node test compiles
        # only the target and its ancestors, so a kept node must not go on
        # listening for an event nothing emits any more - `_assert_routers_
        # declare_what_they_emit` would refuse the derived plan, and rightly.
        self._suppressed: frozenset[str] = frozenset(
            name
            for node_id in self.dropped
            for name in (
                *self.method_idents.get(node_id, ()),
                *self.event_labels.get(node_id, ()),
            )
        )

        back = set(back_edge_indices(document))
        self.route_targets: dict[tuple[str, str], str] = {}
        self.normal_events: dict[str, list[str]] = {}
        self.loop_events: dict[str, list[str]] = {}
        self.rearm: dict[str, list[str]] = {}
        for position, edge in enumerate(document.edges):
            if edge.target_port != "in":
                continue
            if edge.source not in self.step_ids or edge.target not in self.step_ids:
                continue
            source = self.nodes[edge.source]
            event = (
                f"{self._label(source.id, edge.source_port)}"
                if is_routed(source)
                else self.method_idents[source.id][0]
            )
            if is_routed(source):
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

        # 09 D5, and it is the half the back-edge rule above does NOT cover.
        # A node declared `joins: 'any'` compiles to a multi-event `or_()`
        # whether or not a back edge reaches it, and CrewAI adds such a listener
        # to `_fired_or_listeners` on its FIRST fire and skips it forever after
        # (`crewai/flow/runtime/__init__.py:3288-3297`, verified at 1.15.18 -
        # closed item 35). So a join INSIDE a cycle fires on lap one and is
        # silently skipped on lap two: no exception, no warning, the run just
        # ends having produced nothing. Every router that closes a cycle
        # therefore re-arms every multi-event or_ listener on it, not only the
        # node its own back edge lands on.
        #
        # HONEST ABOUT ITS OWN STRENGTH: this is DEFENCE IN DEPTH, not the only
        # thing holding the loop up. `_execute_single_listener` calls CrewAI's
        # own `_clear_or_listeners()` when it re-enters a method that had
        # completed, which covers this topology today - measured by disabling
        # the loop below and watching the shape test go red while the execution
        # test stayed green. What it does not cover is a cycle re-entered
        # without re-running a completed method, and the cost of being wrong
        # about that is a run that ends having produced nothing, with no
        # exception and no warning. That asymmetry is why it stays.
        #
        # `_discard_or_listener` is private CrewAI API, knowingly (decision 13).
        # `test_compiler.py` pins its existence, and the guard's failure message
        # names the router variant as the replacement.
        cyclic = nodes_on_cycles(document)
        for source_id, targets in self.rearm.items():
            for node in self.steps:
                if node.id not in cyclic or node.id in self.dropped:
                    continue
                ident = self.method_idents[node.id][0]
                if ident in targets:
                    continue
                if _is_multi_event_or(self._listen_for(node)):
                    targets.append(ident)

    def _assert_folded_nodes_are_not_steps(self) -> None:
        """`bounds.py` refuses these shapes; this asserts them on the plan.

        Two independent checks agreeing is the whole guarantee - the same
        argument `compiled_identifiers` is compared against below - and the cost
        is one pass over the edges.
        """

        for edge in attachment_edges(self.document):
            source = self.nodes.get(edge.source)
            target = self.nodes.get(edge.target)
            if source is None or target is None:
                continue
            if source.kind not in ATTACHMENT_KINDS or target.kind not in ("agent", "crew"):
                raise BuilderCompileError(
                    f"edge {edge.id!r} attaches a {source.kind} node to a {target.kind} "
                    "node; an attach edge runs from a tool, an MCP server or a skill TO "
                    "an agent or a crew, and bounds.py should have refused this document"
                )
        for member_id, crew_id in self.member_of.items():
            member = self.nodes.get(member_id)
            crew = self.nodes.get(crew_id)
            if member is None or crew is None:
                continue
            if member.kind != "agent" or crew.kind != "crew":
                raise BuilderCompileError(
                    f"{member_id!r} is a {member.kind} member of a {crew.kind}; membership "
                    "runs from an agent to a crew, and bounds.py should have refused this"
                )

    def _ancestors(self, node_id: str) -> frozenset[str]:
        """Every step node upstream of `node_id` along FLOW edges.

        Attachment and member edges are excluded, which is the whole reason this
        walks `is_flow_edge` rather than `document.edges`: a tool is not upstream
        of the agent that holds it, and replaying one would be replaying a
        possession.
        """

        return replay_ancestors(self.document, node_id, step_ids=self.step_ids)

    def attachments_for(self, node_id: str) -> dict[str, list[Any]]:
        """One node's folded attachments, as C5's three lists.

        Order is the order the author drew them, which is the order the agent's
        tool list is rendered in - so two authors who wired the same tools the
        same way get the same prompt, and a golden stays byte-equal.

        A reference that did not survive an export is REPORTED, never crashed
        past: `export.py` nulls `server_id` and `skill_id` on purpose, so an
        imported graph legitimately has an mcp node naming no server. That is a
        problem on a node the author can fix, and `bounds.py` carries the code.
        """

        tools: list[dict[str, Any]] = []
        mcps: list[dict[str, Any]] = []
        skills: list[str] = []
        for source_id in self.attached.get(node_id, ()):
            config = self.nodes[source_id].config
            if isinstance(config, ToolConfig):
                tools.append(
                    {
                        "node_id": source_id,
                        "tool_id": config.tool_id,
                        "params": dict(config.params),
                        **(
                            {"credential_id": config.credential_id}
                            if config.credential_id
                            else {}
                        ),
                    }
                )
            elif isinstance(config, McpConfig) and config.server_id:
                mcps.append(
                    {
                        "node_id": source_id,
                        "server_id": config.server_id,
                        "tool_names": list(config.tool_names),
                        **(
                            {"credential_id": config.credential_id}
                            if config.credential_id
                            else {}
                        ),
                    }
                )
            elif isinstance(config, SkillConfig) and config.skill_id:
                skills.append(config.skill_id)
        return {"tools": tools, "mcps": mcps, "skills": skills}

    # ---------------------------------------------------------------- naming
    def _label(self, node_id: str, port: str) -> str:
        """The event label an edge leaving `port` listens on.

        Usually the port's own name. An `on_error: route` node is the exception:
        its ports are `out` and `error` and its labels are `ok` and `error`
        (C5), so the mapping is positional through `error_router_labels` rather
        than an interpolation of the port. Getting this wrong is not a wrong
        name - it is a listener on an event nothing emits, which
        `_assert_routers_declare_what_they_emit` catches and which would
        otherwise be a node that never runs.
        """

        node = self.nodes.get(node_id)
        if node is not None:
            labels = error_router_labels(node)
            ports = node.out_ports
            if labels and port in ports:
                port = labels[ports.index(port)]
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
        if node.id in self.replayed and not isinstance(config, RouterConfig):
            # 09 D7: everything upstream of a replay point publishes its SAVED
            # output and returns. The listeners downstream fire exactly as they
            # would after a real run, and nothing calls a model.
            #
            # EXCEPT THE ROUTER HALF, and getting that wrong made every derived
            # plan below a routed node uncompilable. A gate is TWO methods - the
            # pause and the paired deterministic router that turns the reply
            # into an event - and an `on_error: route` node is two the same way.
            # Replacing the pair with one `replay_output` emits no event at all,
            # so the node below goes on listening for `e2_approve` while nothing
            # produces it. Measured verbatim, on `input -> gate -> agent ->
            # output`: `n3_safe listens for 'e2_approve', which no method emits`.
            #
            # It is not an exotic shape. `BUILDER_ALLOW_GATELESS_GRAPHS` is off,
            # so a gate above the first billable node is the ONLY shape an
            # anonymous author may launch - which made every graph they can
            # launch one that `resume_from` could not resume past.
            #
            # So the router survives the replay, and it routes on what the
            # source run recorded: `route_gate` reads the decision out of the
            # replay values (its `replayed` flag travels in the compiled routing
            # table below), and an error router reads `err__<node>`, which
            # `replay_output` restores. A plain `router` node is not replayed at
            # all - it bills nothing and it is a pure function of the state a
            # replay restores, so re-running it reproduces the branch the source
            # run took rather than guessing at it.
            method["do"] = self._action(
                _REPLAY_OUTPUT,
                {
                    "node_id": node.id,
                    "source": self.replay.source if self.replay else "run",
                },
            )
            if isinstance(config, GateConfig):
                return {ident: method, **self._gate_router(node, config)}
            if routes_errors(node) and node.kind not in ROUTING_KINDS:
                return {ident: method, **self._error_router(node)}
            return {ident: method}
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
        elif isinstance(config, LibraryAgentConfig):
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
                    # 09 D2: a library agent's canvas attachments reach it as
                    # the one `kind`-discriminated list `bind_attachments`
                    # reads. Its `tools` field stays what it has always been -
                    # the research tool NAMES - because one key with two
                    # element types across two arms is the drift these modules
                    # exist to prevent.
                    **self._library_attachments_with(node),
                    **self._policy_with(config),
                },
            )
        elif isinstance(config, AuthoredAgentConfig):
            method["do"] = self._action(_RUN_AGENT, self._authored_agent_with(node, config))
        elif isinstance(config, LibraryCrewConfig):
            method["do"] = self._action(
                _RUN_CREW,
                {
                    "node_id": node.id,
                    "crew_id": config.crew_id,
                    # PASSED AND NOT HONOURED, and `library_problems` says so on
                    # the node (decision 12). A registered crew builds its own
                    # LLMs inside the crew; this word prices and bounds the
                    # graph, which is what it is for. It travels so the frame
                    # spine can report what the author declared.
                    "tier": config.tier,
                    "max_iter": config.max_iter,
                    "guardrail_max_retries": config.guardrail_max_retries,
                    "prompt_inputs": dict(config.prompt_inputs),
                    **self._policy_with(config),
                },
            )
        elif isinstance(config, AuthoredCrewConfig):
            method["do"] = self._action(_RUN_CREW, self._authored_crew_with(node, config))
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
                    # THE EDGE THE AUTHOR DREW IS THE ANSWER, and an unset
                    # `source` used to mean nothing at all.
                    #
                    # Found by the first paid run of an authored graph, 2026-09-04.
                    # `input -> agent -> output`, drawn on the canvas, validating
                    # with ZERO problems, publishing, launching, spending money on
                    # a real model that produced 896 completion tokens - and
                    # handing back `markdown_body: ""`. `config.source` defaulted
                    # to None, `emit_output` did `_as_text(None)`, and the run
                    # completed successfully with nothing in it.
                    #
                    # That is the drag-and-drop case, not an edge case. An author
                    # who connects an agent to an output has already said where
                    # the body comes from; making them ALSO hand-type
                    # `${state.out__writer}` is the redundancy a visual builder
                    # exists to remove, and getting it wrong is silent.
                    #
                    # `_inbound_source` is the same function the gate and the
                    # router use, so all three read a graph's edges one way: one
                    # predecessor gives one reference, several give an ordered
                    # list the runtime resolves last-with-a-value, and back edges
                    # sort after normal ones so a revise loop shows the revision.
                    # An explicit `source` still wins - an author who names one
                    # means it.
                    "source": (
                        config.source
                        if config.source is not None
                        else self._inbound_source(node)
                    ),
                },
            )
        else:  # pragma: no cover - the seven flow kinds are exhaustive
            raise BuilderCompileError(f"node {node.id!r} has no compiled shape")
        if routes_errors(node) and node.kind not in ROUTING_KINDS:
            return {ident: method, **self._error_router(node)}
        return {ident: method}

    # ------------------------------------------------------ the authored arms
    def _policy_with(self, config: Any) -> dict[str, Any]:
        """`retry` and `on_error`, emitted only when they say something.

        Omitted rather than defaulted so a document that asks for neither
        compiles byte-identical to what it compiled to before the fields
        existed - the same rule `credential_id` already follows, and the reason
        every committed golden survived this plan.
        """

        emitted: dict[str, Any] = {}
        retry = getattr(config, "retry", None)
        if retry is not None and (retry.max_retries or retry.fallback_model):
            emitted["retry"] = {
                "max_retries": retry.max_retries,
                "backoff_seconds": retry.backoff_seconds,
                "fallback_model": retry.fallback_model,
            }
        if getattr(config, "on_error", "fail") != "fail":
            emitted["on_error"] = config.on_error
        return emitted

    def _library_attachments_with(self, node: BuilderNode) -> dict[str, Any]:
        folded = self.attachments_for(node.id)
        attachments = [
            *({"kind": "tool", **entry} for entry in folded["tools"]),
            *({"kind": "mcp", **entry} for entry in folded["mcps"]),
            *({"kind": "skill", "skill_id": skill} for skill in folded["skills"]),
        ]
        return {"attachments": attachments} if attachments else {}

    def _authored_agent_with(
        self, node: BuilderNode, config: AuthoredAgentConfig, *, member: bool = False
    ) -> dict[str, Any]:
        """One authored agent node's whole `with:` block - C5, values only.

        Every entry is a value the author typed or an OPAQUE ID the entrypoint
        dereferences against the run's owner. There is no module path, no class
        name and no callable anywhere in it, which is what keeps
        `assert_action_refs` the whole of the code-execution answer even though
        the block grew from six keys to sixteen.

        A MEMBER carries no `retry` and no `on_error`: it is not a step, so it
        has no error port to route out of and no listener to re-enter. Its crew
        owns both.
        """

        folded = self.attachments_for(node.id)
        block: dict[str, Any] = {
            "node_id": node.id,
            "role": config.role,
            "goal": config.goal,
            "backstory": config.backstory,
            "task": {
                "description": config.task.description,
                "expected_output": config.task.expected_output,
                "output_schema": dict(config.task.output_schema)
                if config.task.output_schema
                else None,
                "markdown": config.task.markdown,
                "async_execution": config.task.async_execution,
            },
            "llm": _llm_block(config.llm),
            "tier": config.tier,
            "max_iter": config.max_iter,
            "guardrail_max_retries": config.guardrail_max_retries,
            "advanced": {
                "max_rpm": config.max_rpm,
                "max_execution_time": config.max_execution_time,
                "allow_delegation": config.allow_delegation,
                "memory": config.memory,
                "cache": config.cache,
                "respect_context_window": config.respect_context_window,
            },
            "expert": {
                "system_template": config.system_template,
                "prompt_template": config.prompt_template,
                "response_template": config.response_template,
                "planning": config.planning,
                "planning_config": config.planning_config.model_dump()
                if config.planning_config is not None
                else None,
            },
            "tools": folded["tools"],
            "mcps": folded["mcps"],
            "skills": folded["skills"],
            "prompt_inputs": dict(config.prompt_inputs),
        }
        if config.tool_failure_policy:
            block["tool_failure_policy"] = config.tool_failure_policy
        if config.credential_id:
            block["credential_id"] = config.credential_id
        if not member:
            block.update(self._policy_with(config))
        return block

    def _authored_crew_with(
        self, node: BuilderNode, config: AuthoredCrewConfig
    ) -> dict[str, Any]:
        """One authored crew's `with:` block, its members folded in (09 D2).

        A `member` agent is NOT a flow method. It runs inside its crew, in the
        crew's own order, so compiling it as a step too would run it twice and
        leave nothing downstream able to say which output it was reading -
        which is exactly what `member-agent-has-flow-edges` refuses an author
        for drawing.
        """

        members: list[dict[str, Any]] = []
        for member_id in self.members.get(node.id, ()):
            member_node = self.nodes[member_id]
            member_config = member_node.config
            if not isinstance(member_config, AuthoredAgentConfig):
                raise BuilderCompileError(
                    f"{member_id!r} is a member of the authored crew {node.id!r} and names "
                    "a registered agent. A crew's members carry their own prompts, because "
                    "the crew's own task order is what runs them"
                )
            members.append(
                self._authored_agent_with(member_node, member_config, member=True)
            )
        ordered = [item for item in config.task_order if item in self.members.get(node.id, ())]
        ordered += [item for item in self.members.get(node.id, ()) if item not in ordered]
        folded = self.attachments_for(node.id)
        return {
            "node_id": node.id,
            "process": config.process,
            "members": members,
            "task_order": ordered,
            "manager_llm": _llm_block(config.manager_llm) if config.manager_llm else None,
            "manager_agent": config.manager_agent,
            "tier": config.tier,
            "max_iter": config.max_iter,
            "guardrail_max_retries": config.guardrail_max_retries,
            "memory": config.memory,
            "cache": config.cache,
            "max_rpm": config.max_rpm,
            "planning": config.planning,
            "planning_llm": _llm_block(config.planning_llm) if config.planning_llm else None,
            "verbose": config.verbose,
            "prompt_inputs": dict(config.prompt_inputs),
            "tools": folded["tools"],
            "mcps": folded["mcps"],
            **self._policy_with(config),
        }

    def _error_router(self, node: BuilderNode) -> dict[str, Any]:
        """The paired router of an `on_error: route` node - 09 D3.

        The SAME shape a gate already uses, and for the same measured reason:
        only a `@router` can choose an event. The step method catches, records
        `err__<node>` and returns normally; this reads that key and emits `ok`
        or `error`. A step that raised past its own listener would end the run
        instead of taking the recovery path the author drew.
        """

        _, router_ident = self.method_idents[node.id]
        ok_label, error_label = self.event_labels[node.id]
        return {
            router_ident: {
                "description": f"{node.label}: route success or failure",
                "listen": self.method_idents[node.id][0],
                "router": True,
                "emit": [ok_label, error_label],
                "do": self._action(
                    _ROUTE_BRANCH,
                    {
                        "node_id": node.id,
                        "rules": [
                            {
                                "label": ok_label,
                                "op": "eq",
                                "key": f"{BUILDER_STATE_ERROR_PREFIX}{node.id}",
                                "value": None,
                            },
                            {
                                "label": error_label,
                                "op": BUILDER_ROUTER_OTHERWISE,
                                "key": f"{BUILDER_STATE_ERROR_PREFIX}{node.id}",
                                "value": None,
                            },
                        ],
                        "rearm": self.rearm.get(node.id, []),
                        # Its own output, passed through unchanged: `route_branch`
                        # re-records what flowed through it, and for an error
                        # router that is the step's own result.
                        "source": f"${{state.{BUILDER_STATE_OUTPUT_PREFIX}{node.id}}}",
                    },
                ),
            }
        }

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
            if edge.target_port != "in" or edge.target != node.id:
                continue
            if edge.source not in self.step_ids or edge.source in self.dropped:
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

        A node the document declares `join: "all"` waits for all of its
        predecessors: `{"and": [...]}`, which `_is_multi_event_or` reads as
        false, so a fan-in is never the listener CrewAI suppresses.

        A node with several predecessors and NO declared join - or one declared
        `join: "any"`, which is the same compiled shape said out loud - is the
        other thing entirely: alternatives. Two branches of one router converging on
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

        normal = [
            event
            for event in _deduplicated(self.normal_events.get(node.id, []))
            if event not in self._suppressed
        ]
        loops = [
            event
            for event in _deduplicated(self.loop_events.get(node.id, []))
            if event not in self._suppressed
        ]
        if not normal and not loops:
            return None
        declared = self.document.joins.get(node.id)
        if normal and (declared == "all" or self._is_concurrent_fan_in(normal, declared)):
            base: Any = {"and": normal}
            return base if not loops else {"or": [base, *loops]}
        alternatives = normal + [event for event in loops if event not in normal]
        if len(alternatives) == 1:
            return alternatives[0]
        return {"or": alternatives}

    def _is_concurrent_fan_in(self, normal: Sequence[str], declared: str | None) -> bool:
        """Whether an UNDECLARED fan-in is two branches that both really run.

        MEASURED, and it is the sharpest thing in this module. A compiled
        `{"or": [a, b]}` whose alternatives are two plain METHOD names makes
        CrewAI treat them as a RACING GROUP (`_build_racing_groups`,
        `crewai/flow/runtime/__init__.py:1098-1144`): they run in parallel, the
        first to finish wins, and **the loser is cancelled along with anything
        its completion had already triggered**. Run against 1.15.18 on a
        two-branch diamond, that means the join itself dies with a
        `CancelledError` nobody sees - `kickoff()` returns the losing branch's
        own output, the join never ran, and no exception leaves the flow.

        So an undeclared fan-in over two steps compiles to `and`. That is what
        an author who drew a diamond meant, and it is the only shape that does
        not cancel a branch.

        Alternatives are kept where they are correct and necessary: a fan-in
        whose predecessors are ROUTER LABELS. Only one label fires per pass, so
        two of them are never in one triggered batch and the racing group can
        never form; compiling those as `and` would deadlock the most ordinary
        graph anyone draws, because the join would wait forever for the branch
        that was not taken.

        `joins: "any"` still means alternatives, because that is what the word
        says - the first arrival runs it and the rest never fire - and an author
        who typed it has asked for the race.
        """

        if declared == "any" or len(normal) < 2:
            return False
        if not all(event in self.node_ids for event in normal):
            # At least one arrival is a router LABEL, so at least one arm is
            # conditional. Alternatives, and the racing group cannot form.
            return False
        # A predecessor with a ROUTING ancestor may or may not run: a router
        # took one of its ports and the other arm's chain never fired. Two of
        # those are alternatives, and `and` over them would deadlock. Only when
        # NOTHING upstream of any arrival chose a branch are they certain to
        # both arrive - which is the diamond, and the shape that races.
        for event in normal:
            predecessor = self.node_ids[event]
            if any(
                is_routed(self.nodes[ancestor])
                for ancestor in self._ancestors(predecessor)
                if ancestor in self.nodes
            ):
                return False
        return True

    # ----------------------------------------------------------------- state
    def state_block(self) -> dict[str, Any]:
        """The compiled `state:` block - 09 D6.

        A document that declares nothing keeps the `dict` state every v1 graph
        has, byte for byte. A document that DECLARES keys compiles to CrewAI's
        `json_schema` state (`crewai/flow/flow_definition.py:133`), whose schema
        is the author's declaration widened with every key the compiler owns -
        because `additionalProperties` would otherwise refuse `out__*` at
        kickoff, and those keys are not optional.

        A `pydantic` state is deliberately not offered: it needs a python class
        the author cannot write.
        """

        default = self.state_default()
        declared = self.document.state
        if declared is None or not declared.fields:
            return {"type": "dict", "default": default}

        properties: dict[str, Any] = {}
        for key, field in declared.fields.items():
            entry: dict[str, Any] = {"type": _JSON_SCHEMA_TYPES[field.type]}
            if field.description:
                entry["description"] = field.description
            properties[key] = entry
            default.setdefault(key, field.default)
        for key, value in default.items():
            properties.setdefault(key, _permissive_property(value))
        return {
            "type": "json_schema",
            # `json_schema`, NOT `schema`. 09 D6 wrote `schema`;
            # `FlowJsonSchemaStateDefinition` is `extra="forbid"` and its field
            # is `json_schema`, so the plan's spelling is refused at
            # `Flow.from_declaration` - measured, and the package wins.
            "json_schema": {
                "type": "object",
                "properties": properties,
                # OPEN, and it has to be: CEL raises on a key that is absent, so
                # `state_default` pre-seeds every key any `with:` block can
                # mention, and a run's own inputs land beside them.
                "additionalProperties": True,
            },
            "default": default,
        }

    def state_default(self) -> dict[str, Any]:
        """The initial state, with every key any `with:` block can reference.

        Pre-seeding is not tidiness. CEL raises
        `no such member in mapping: 'x'` on a key that is absent, so a
        `${state.out__scoper}` rendered before the Scoper has run - which is
        exactly what happens on the revise side of a loop - would fail the
        method rather than render empty.
        """

        default: dict[str, Any] = {}
        for node in self.steps:
            if node.id in self.dropped:
                continue
            default[f"{BUILDER_STATE_OUTPUT_PREFIX}{node.id}"] = None
            if routes_errors(node) and node.kind not in ROUTING_KINDS:
                # A FAILED node's output is still null, so the failure needs a
                # key of its own; folding the two would make "produced nothing"
                # and "exploded" the same state, and the error router reads
                # exactly this key.
                default[f"{BUILDER_STATE_ERROR_PREFIX}{node.id}"] = None
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
                    # A replayed gate does not pause, so its router is never
                    # handed a `HumanFeedbackResult`; without this flag it would
                    # route on `None`, and `gate_decision(None)` is an approve.
                    # Silently approving on behalf of an operator is the exact
                    # failure `lint_gates` exists to refuse, so the replay says
                    # so out loud and `route_gate` reads the recorded decision.
                    "replayed": node.id in self.replayed,
                }
                for node in self.steps
                if isinstance(node.config, GateConfig) and node.id not in self.dropped
            },
        }
        return default

    def _referenced_state_keys(self) -> set[str]:
        """Every `${state.<key>}` any node config mentions."""

        found: set[str] = set()
        for node in self.steps:
            if node.id in self.dropped:
                continue
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

        # Recomputed on the DERIVED graph for a replay plan (09 D7): a node
        # test that dropped the downstream half may have dropped the loop with
        # it, and sizing the backstop to a cycle that is no longer compiled
        # would be sizing it to a graph that is not running.
        live = [
            position
            for position, edge in enumerate(self.document.edges)
            if position in set(back_edge_indices(self.document))
            and edge.source in self.step_ids
            and edge.target in self.step_ids
            and edge.source not in self.dropped
            and edge.target not in self.dropped
        ]
        cycles = max(1, len(live))
        return (1 + MAX_CYCLE_ITERATIONS) ** cycles


#: `FlowStateField.type` -> the JSON Schema type word. Four scalars and no
#: object: the declaration is a FLAT map, because a nested schema here would be
#: a second document format inside the document.
_JSON_SCHEMA_TYPES: dict[str, str] = {
    "string": "string",
    "number": "number",
    "integer": "integer",
    "boolean": "boolean",
}


def _permissive_property(value: Any) -> dict[str, Any]:
    """A JSON Schema entry for a compiler-owned key, which may hold anything.

    `out__*` holds whatever a node produced - a string, a JSON object, a null
    before it has run - so pinning a type here would fail a run on its own
    seeded default. The keys are DECLARED so a reader of the compiled document
    can see them; they are not constrained, because the compiler is the only
    writer and it is not the thing being guarded against.
    """

    del value
    return {}


def _is_multi_event_or(condition: Any) -> bool:
    """Whether a compiled `listen` is the shape CrewAI fires once and skips.

    `_is_multi_event_or` in `crewai/flow/runtime/__init__.py` asks exactly this,
    and a listener that answers yes is added to `_fired_or_listeners` on its
    first fire and skipped forever after unless something re-arms it. Naming the
    question here, in one place, is what lets `_Plan` decide which listeners a
    cycle's router has to re-arm.
    """

    if not isinstance(condition, Mapping):
        return False
    branch = condition.get("or")
    return isinstance(branch, (list, tuple)) and len(branch) > 1


def _llm_block(config: Any) -> dict[str, Any]:
    """`LlmConfig` -> the `llm` entry of a compiled `with:` block.

    Every field is emitted, including the nulls, and that is the opposite of
    what `_policy_with` does two functions up. The difference is real: an
    omitted `retry` means "this author asked for no retry", while an omitted
    `temperature` would mean "this compiler forgot", and the block an author
    reads in the code preview should show the whole of what the model call will
    carry.
    """

    return {
        "model": config.model,
        "temperature": config.temperature,
        "top_p": config.top_p,
        "max_tokens": config.max_tokens,
        "timeout": config.timeout,
        "response_format": config.response_format,
        "frequency_penalty": config.frequency_penalty,
        "presence_penalty": config.presence_penalty,
        "stop": list(config.stop),
        "seed": config.seed,
        "reasoning_effort": config.reasoning_effort,
    }


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

#: A library crew node's `tier`, which prices and bounds the graph and does NOT
#: choose the crew's models (decision 12). A WARNING and not an error, because
#: the word is required by the schema and does real work in two other places -
#: what would be wrong is leaving an author to infer that the third place it
#: looks like it works is not one of them. The gauntlet's own forbidden list
#: names "a parameter rendered in the UI that the compiler ignores"; this is
#: that rule answered out loud rather than by silence.
CREW_TIER_NOT_HONOURED = "crew-tier-not-honoured"

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
        if isinstance(config, LibraryAgentConfig):
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
        elif isinstance(config, LibraryCrewConfig):
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
            problems.append(
                Problem(
                    code=CREW_TIER_NOT_HONOURED,
                    severity="warning",
                    message=(
                        f"{node.id!r} runs the registered crew {config.crew_id!r} on the "
                        f"{config.tier} tier, and that word does not choose the crew's "
                        "models: a registered crew builds its own LLMs in python, from "
                        "config.py, inside the crew. What the tier does do is price this "
                        "node and count it against the escalation bound. Author the agents "
                        "here if you need to choose the model"
                    ),
                    node_id=node.id,
                    field="tier",
                )
            )
    return problems
