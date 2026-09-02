"""What the compiler emits, what it refuses, and that the result actually runs.

Three kinds of test here, and the third is the one that matters. Shape tests
assert the emitted `crewai.flow/v1` dict; guard tests assert the refusals, each
one written against a definition that WOULD run if the guard were absent; and
execution tests kick the compiled definition off through
`Flow.from_declaration` and read what really happened.

Nothing here spends money. Every billable node is built by an injected factory
whose `kickoff` returns a canned string, which is the same seam
`ValidatorFlow`'s crew factories provide - the model is replaced, and the
compiler, the flow engine, the joins, the routers and the state plumbing are
all real.
"""

from __future__ import annotations

import json
import threading
import unittest
from typing import Any, Sequence

from crewai.flow.flow import Flow
from crewai.flow.runtime._actions import resolve_ref

from brief_crew.builder import bounds
from brief_crew.builder.compiler import (
    BuilderCompileError,
    CompiledFlow,
    assert_action_refs,
    compile_document,
    library_problems,
    lint_gates,
)
from brief_crew.builder.document import BuilderDocument
from brief_crew.builder.runtime import (
    BUILDER_AGENT_LIBRARY,
    BUILDER_CREW_LIBRARY,
    BUILDER_STATE_KEY,
    BuilderRuntimeError,
    builder_cancellation,
    checkpoint,
    transform,
    use_crew_factories,
)
from brief_crew.config import (
    BUILDER_ACTION_REFS,
    BUILDER_TRANSFORM_OPS,
    MAX_CYCLE_ITERATIONS,
    RUN_RESULT_BODY_KEYS,
)
from brief_crew.events.registry import NodeRegistry
from tests.builder.test_document import document, edge, node

BODY_KEY = RUN_RESULT_BODY_KEYS[0]
MARKET_TOOL = "research_market_landscape"


# --------------------------------------------------------------------------
# Factories. Node ids ARE agent ids here, because the compiler refuses an
# agent the YAML registry does not declare - which is the point of that check.
# --------------------------------------------------------------------------
def input_node(node_id: str = "idea", field: str = "idea") -> dict[str, Any]:
    return node(node_id, "input", {"field": field})


def scoper_node(node_id: str = "scoper", *, tier: str = "escalation") -> dict[str, Any]:
    return node(
        node_id,
        "agent",
        {
            "agent_id": "scoper",
            "tier": tier,
            "prompt_inputs": {"idea": "${state.out__idea}", "human_override": ""},
        },
    )


def market_node(node_id: str = "market", *, source: str = "scoper") -> dict[str, Any]:
    return node(
        node_id,
        "agent",
        {
            "agent_id": "market_analyst",
            "tier": "cheap",
            "tools": [MARKET_TOOL],
            "prompt_inputs": {
                "scoped_idea_json": f"${{state.out__{source}}}",
                "market_query": "clinic scheduling",
                "cached_evidence_block": "",
            },
        },
    )


def sentiment_node(node_id: str = "signal", *, source: str = "scoper") -> dict[str, Any]:
    return node(
        node_id,
        "agent",
        {
            "agent_id": "sentiment_analyst",
            "tier": "cheap",
            "prompt_inputs": {
                "scoped_idea_json": f"${{state.out__{source}}}",
                "community_queries_block": "clinic scheduling",
            },
        },
    )


def crew_node(node_id: str = "scope_crew") -> dict[str, Any]:
    return node(node_id, "crew", {"crew_id": "scope", "tier": "escalation"})


def gate_node(
    node_id: str = "confirm",
    *,
    max_turns: int = 1,
    editable_fields: Sequence[str] = (),
) -> dict[str, Any]:
    return node(
        node_id,
        "gate",
        {
            "message": "Confirm the scope.",
            "max_turns": max_turns,
            "editable_fields": list(editable_fields),
        },
    )


def router_node(
    node_id: str = "again",
    *,
    key: str = "turns__confirm",
    value: Any = 1,
) -> dict[str, Any]:
    return node(
        node_id,
        "router",
        {
            "branches": [
                {"label": "retry", "op": "gte", "key": key, "value": value},
                {"label": "onward", "op": "otherwise"},
            ]
        },
    )


def transform_node(
    node_id: str = "merge", *, op: str = "merge", args: dict[str, Any] | None = None
) -> dict[str, Any]:
    return node(node_id, "transform", {"op": op, "args": args or {}})


def output_node(node_id: str = "report", *, source: str = "${state.out__merge}") -> dict[str, Any]:
    return node(node_id, "output", {"body_key": BODY_KEY, "source": source})


def straight_line() -> BuilderDocument:
    """input -> scoper -> report. The smallest graph that produces something."""

    return document(
        [input_node(), scoper_node(), output_node(source="${state.out__scoper}")],
        [edge("e1", "idea", "scoper"), edge("e2", "scoper", "report")],
    )


def fan_out_and_join() -> BuilderDocument:
    """The validator's own shape: one scope, two branches, one declared join."""

    return document(
        [
            input_node(),
            scoper_node(),
            market_node(),
            sentiment_node(),
            transform_node(
                args={"m": "${state.out__market}", "s": "${state.out__signal}"}
            ),
            output_node(),
        ],
        [
            edge("e1", "idea", "scoper"),
            edge("e2", "scoper", "market"),
            edge("e3", "scoper", "signal"),
            edge("e4", "market", "merge"),
            edge("e5", "signal", "merge"),
            edge("e6", "merge", "report"),
        ],
        joins={"merge": "all"},
    )


def gated_loop(max_turns: int = 1) -> BuilderDocument:
    """input -> scoper -> gate; revise loops back through a router."""

    return document(
        [
            input_node(),
            scoper_node(),
            gate_node(max_turns=max_turns, editable_fields=("notes",)),
            transform_node(
                "restate",
                op="default",
                args={"value": "${state.out__confirm}", "default": "no note"},
            ),
            router_node(key="turns__confirm", value=1),
            output_node("report", source="${state.out__confirm}"),
        ],
        [
            edge("e1", "idea", "scoper"),
            edge("e2", "scoper", "confirm"),
            edge("e3", "confirm", "report", source_port="approve"),
            edge("e4", "confirm", "restate", source_port="revise"),
            edge("e5", "restate", "again"),
            edge("e6", "again", "confirm", source_port="retry"),
            edge("e7", "again", "report", source_port="onward"),
        ],
    )


# --------------------------------------------------------------------------
# The no-cost seam
# --------------------------------------------------------------------------
class StubCrew:
    """Whatever a real Crew would have cost, for free."""

    def __init__(self, factories: "StubFactories", node_id: str) -> None:
        self.factories = factories
        self.node_id = node_id

    def kickoff(self, inputs: dict[str, Any] | None = None) -> str:
        self.factories.kickoffs.append((self.node_id, dict(inputs or {})))
        return self.factories.outputs.get(self.node_id, f"{self.node_id}-output")


class StubFactories:
    """Records what the compiler asked to be built, and builds nothing paid."""

    def __init__(self, outputs: dict[str, str] | None = None) -> None:
        self.outputs = outputs or {}
        self.built: list[dict[str, Any]] = []
        self.kickoffs: list[tuple[str, dict[str, Any]]] = []

    def agent_crew(
        self,
        *,
        node_id: str,
        agent_id: str,
        tier: str,
        tools: Sequence[str],
        max_iter: int,
        guardrail_max_retries: int,
    ) -> StubCrew:
        self.built.append(
            {
                "kind": "agent",
                "node_id": node_id,
                "agent_id": agent_id,
                "tier": tier,
                "tools": tuple(tools),
                "max_iter": max_iter,
                "guardrail_max_retries": guardrail_max_retries,
            }
        )
        return StubCrew(self, node_id)

    def crew(
        self,
        *,
        node_id: str,
        crew_id: str,
        tier: str,
        max_iter: int,
        guardrail_max_retries: int,
    ) -> StubCrew:
        self.built.append(
            {"kind": "crew", "node_id": node_id, "crew_id": crew_id, "tier": tier}
        )
        return StubCrew(self, node_id)


def run(
    compiled: CompiledFlow,
    *,
    inputs: dict[str, Any] | None = None,
    factories: StubFactories | None = None,
    persistence: Any = None,
) -> tuple[Any, Flow]:
    """Kick the compiled definition off for real, with no model behind it."""

    stub = factories or StubFactories()
    flow = Flow.from_declaration(
        contents=compiled.definition,
        suppress_flow_events=True,
        **({"persistence": persistence} if persistence is not None else {}),
    )
    with use_crew_factories(stub):
        result = flow.kickoff(inputs=inputs or {"idea": "a scheduling assistant"})
    return result, flow


# --------------------------------------------------------------------------
# Shape
# --------------------------------------------------------------------------
class CompiledShapeTests(unittest.TestCase):
    def test_every_kind_compiles_to_its_declared_entrypoint(self) -> None:
        compiled = compile_document(gated_loop())
        refs = {
            compiled.node_ids[name]: method["do"]["ref"]
            for name, method in compiled.methods.items()
        }
        self.assertEqual(refs["idea"], "brief_crew.builder.runtime:seed_input")
        self.assertEqual(refs["scoper"], "brief_crew.builder.runtime:run_agent")
        self.assertEqual(refs["restate"], "brief_crew.builder.runtime:transform")
        self.assertEqual(refs["again"], "brief_crew.builder.runtime:route_branch")
        self.assertEqual(refs["report"], "brief_crew.builder.runtime:emit_output")

    def test_a_crew_node_compiles_to_run_crew(self) -> None:
        compiled = compile_document(
            document(
                [input_node(), crew_node(), output_node(source="${state.out__scope_crew}")],
                [edge("e1", "idea", "scope_crew"), edge("e2", "scope_crew", "report")],
            )
        )
        method = compiled.methods[compiled.method_idents["scope_crew"][0]]
        self.assertEqual(method["do"]["ref"], "brief_crew.builder.runtime:run_crew")
        self.assertEqual(method["do"]["with"]["crew_id"], "scope")

    def test_one_gate_node_compiles_to_two_methods(self) -> None:
        # Measured, not stylistic: with the pause and the routing on ONE method
        # the step returns a HumanFeedbackResult, which is not an event name, so
        # neither branch fires and the run ends silently producing nothing.
        compiled = compile_document(gated_loop())
        idents = compiled.method_idents["confirm"]
        self.assertEqual(len(idents), 2)
        gate, router = idents
        self.assertIn("human_feedback", compiled.methods[gate])
        self.assertNotIn("human_feedback", compiled.methods[router])
        self.assertTrue(compiled.methods[router]["router"])
        self.assertEqual(compiled.methods[router]["listen"], gate)
        self.assertEqual(compiled.node_ids[gate], compiled.node_ids[router])

    def test_the_gate_router_carries_no_with_block(self) -> None:
        # With a `with:` block CodeAction calls handler(**rendered) and DROPS
        # the positional HumanFeedbackResult - the router would route on
        # nothing, which is the silent approval this whole design avoids.
        compiled = compile_document(gated_loop())
        _, router = compiled.method_idents["confirm"]
        self.assertNotIn("with", compiled.methods[router]["do"])

    def test_the_gate_declares_llm_explicitly_null_and_the_pausing_provider(self) -> None:
        compiled = compile_document(gated_loop())
        gate, _ = compiled.method_idents["confirm"]
        feedback = compiled.methods[gate]["human_feedback"]
        # `in` and `is None` separately: the schema default is the STRING
        # "gpt-4o-mini", so an omitted key is a paid client per gate.
        self.assertIn("llm", feedback)
        self.assertIsNone(feedback["llm"])
        self.assertIsNone(feedback["emit"])
        self.assertIsNone(feedback["default_outcome"])
        self.assertEqual(feedback["provider"], "brief_crew.builder.gates:GATE_PROVIDER")
        self.assertEqual(feedback["metadata"]["gate_id"], "confirm")
        self.assertEqual(feedback["metadata"]["editable_fields"], ["notes"])

    def test_a_declared_join_waits_for_all_and_alternatives_do_not(self) -> None:
        compiled = compile_document(gated_loop())
        merge = compile_document(fan_out_and_join())
        # Declared: an `and`, which `_is_multi_event_or` reads as false and
        # CrewAI therefore never suppresses.
        self.assertEqual(
            merge.methods[merge.method_idents["merge"][0]]["listen"],
            {"and": ["n2_market", "n3_signal"]},
        )
        # Undeclared, and mutually exclusive: compiling these as `and` would
        # deadlock the report on the branch that was not taken.
        self.assertEqual(
            compiled.methods[compiled.method_idents["report"][0]]["listen"],
            {"or": ["e3_approve", "e5_onward"]},
        )

    def test_a_back_edge_becomes_the_targets_alternative(self) -> None:
        compiled = compile_document(gated_loop())
        gate, _ = compiled.method_idents["confirm"]
        self.assertEqual(
            compiled.methods[gate]["listen"], {"or": ["n1_scoper", "e5_retry"]}
        )

    def test_the_input_node_is_the_start_and_nothing_else_is(self) -> None:
        compiled = compile_document(fan_out_and_join())
        starts = [name for name, method in compiled.methods.items() if method.get("start")]
        self.assertEqual(starts, [compiled.method_idents["idea"][0]])

    def test_state_seeds_every_key_a_with_block_references(self) -> None:
        # CEL raises "no such member in mapping" on an absent key rather than
        # rendering it empty, so an unseeded reference fails the method.
        compiled = compile_document(fan_out_and_join())
        default = compiled.definition["state"]["default"]
        for node_id in ("idea", "scoper", "market", "signal", "merge", "report"):
            self.assertIn(f"out__{node_id}", default)
        self.assertEqual(default["idea"], "")
        self.assertIn(BUILDER_STATE_KEY, default)

    def test_a_gates_turn_counter_and_routing_table_are_seeded(self) -> None:
        compiled = compile_document(gated_loop(max_turns=3))
        default = compiled.definition["state"]["default"]
        self.assertEqual(default["turns__confirm"], 0)
        _, router = compiled.method_idents["confirm"]
        entry = default[BUILDER_STATE_KEY]["gates"][router]
        self.assertEqual(entry["node_id"], "confirm")
        self.assertEqual(entry["max_turns"], 3)
        self.assertEqual(entry["approve"], "e3_approve")
        self.assertEqual(entry["revise"], "e3_revise")

    def test_two_gates_get_two_routing_rows_with_their_own_labels(self) -> None:
        # A gate consumes TWO method indices, so a second gate's labels must
        # not collide with the first's - which is what the index walk buys.
        two = document(
            [
                input_node(),
                gate_node("first"),
                gate_node("second"),
                output_node(source="${state.out__second}"),
            ],
            [
                edge("e1", "idea", "first"),
                edge("e2", "first", "second", source_port="approve"),
                edge("e3", "first", "report", source_port="revise"),
                edge("e4", "second", "report", source_port="approve"),
                edge("e5", "second", "report", source_port="revise"),
            ],
        )
        compiled = compile_document(two)
        gates = compiled.definition["state"]["default"][BUILDER_STATE_KEY]["gates"]
        self.assertEqual(
            {row["node_id"] for row in gates.values()}, {"first", "second"}
        )
        labels = [label for row in gates.values() for label in (row["approve"], row["revise"])]
        self.assertEqual(len(set(labels)), 4)

    def test_max_method_calls_bounds_the_cycles_that_are_legal(self) -> None:
        self.assertEqual(
            compile_document(straight_line()).definition["config"]["max_method_calls"],
            1 + MAX_CYCLE_ITERATIONS,
        )
        self.assertEqual(
            compile_document(gated_loop()).definition["config"]["max_method_calls"],
            1 + MAX_CYCLE_ITERATIONS,
        )

    def test_the_gate_shows_its_predecessor_and_the_revision_after_a_loop(self) -> None:
        compiled = compile_document(gated_loop())
        gate, _ = compiled.method_idents["confirm"]
        self.assertEqual(
            compiled.methods[gate]["do"]["with"]["source"],
            ["${state.out__scoper}", "${state.out__again}"],
        )


# --------------------------------------------------------------------------
# The compiled namespace
# --------------------------------------------------------------------------
class NamespaceTests(unittest.TestCase):
    def test_method_idents_agree_with_the_generator_bounds_checked(self) -> None:
        # The disjointness guarantee is only worth what the two generators
        # agreeing makes it, so the compiler compares rather than trusts.
        for factory in (straight_line, fan_out_and_join, gated_loop):
            document_under_test = factory()
            declared, _ = bounds.compiled_identifiers(document_under_test)
            self.assertEqual(
                compile_document(document_under_test).method_idents, declared
            )

    def test_method_idents_and_event_labels_are_disjoint(self) -> None:
        compiled = compile_document(gated_loop())
        labels = {label for group in compiled.event_labels.values() for label in group}
        self.assertTrue(labels)
        self.assertTrue(set(compiled.node_ids).isdisjoint(labels))

    def test_the_disjointness_assertion_fires_when_a_name_is_in_both(self) -> None:
        from brief_crew.builder.compiler import _assert_namespaces_disjoint

        with self.assertRaises(BuilderCompileError) as raised:
            _assert_namespaces_disjoint({"n0_idea": "idea"}, ["n0_idea"])
        self.assertIn("n0_idea", str(raised.exception))

    def test_a_gates_two_methods_map_to_one_canvas_node(self) -> None:
        compiled = compile_document(gated_loop())
        gate, router = compiled.method_idents["confirm"]
        self.assertEqual(compiled.node_ids[gate], "confirm")
        self.assertEqual(compiled.node_ids[router], "confirm")

    def test_the_maps_feed_a_node_registry_that_quarantines_nothing(self) -> None:
        # The whole point of handing the maps back: frames from a compiled flow
        # have to reach the canvas nodes rather than the quarantine node.
        compiled = compile_document(gated_loop())
        registry = NodeRegistry.from_document(
            gated_loop(),
            method_names=compiled.method_idents,
            event_labels=compiled.port_labels,
        )
        for ident, node_id in compiled.node_ids.items():
            self.assertEqual(registry.resolve(method_name=ident), node_id)
            self.assertNotEqual(node_id, registry.quarantine_node_id)
        _, router = compiled.method_idents["confirm"]
        self.assertEqual(registry.resolve_route(router, "e3_approve"), "report")
        self.assertEqual(registry.resolve_route(router, "e3_revise"), "restate")

    def test_route_targets_name_the_router_method_not_the_node(self) -> None:
        compiled = compile_document(gated_loop())
        _, router = compiled.method_idents["confirm"]
        self.assertEqual(compiled.route_targets[(router, "e3_approve")], "report")
        self.assertIn(router, compiled.router_methods)


# --------------------------------------------------------------------------
# The guards
# --------------------------------------------------------------------------
class GateLintTests(unittest.TestCase):
    def _gate(self, **overrides: Any) -> dict[str, Any]:
        feedback = {
            "message": "Confirm.",
            "emit": None,
            "llm": None,
            "provider": "brief_crew.builder.gates:GATE_PROVIDER",
            "default_outcome": None,
        }
        feedback.update(overrides)
        for key, value in list(feedback.items()):
            if value is _ABSENT:
                del feedback[key]
        return {"methods": {"n1_gate": {"do": {}, "human_feedback": feedback}}}

    def test_the_compiled_definition_passes_its_own_lint(self) -> None:
        self.assertEqual(lint_gates(compile_document(gated_loop()).definition), [])

    def test_a_non_null_emit_is_refused(self) -> None:
        # THE trap. With emit set and llm null, CrewAI returns emit[0]
        # unconditionally, so a reply of {"decision": "revise"} runs the approve
        # branch - reproduced end to end - and CrewAI logs it at severity=error
        # and runs the flow anyway.
        problems = lint_gates(self._gate(emit=["approve", "revise"]))
        self.assertEqual(len(problems), 1)
        self.assertIn("emit[0]", problems[0])

    def test_an_omitted_llm_is_refused(self) -> None:
        problems = lint_gates(self._gate(llm=_ABSENT))
        self.assertEqual(len(problems), 1)
        self.assertIn("gpt-4o-mini", problems[0])

    def test_a_named_llm_is_refused(self) -> None:
        problems = lint_gates(self._gate(llm="openrouter/anything"))
        self.assertEqual(len(problems), 1)
        self.assertIn("openrouter/anything", problems[0])

    def test_a_missing_provider_is_refused(self) -> None:
        # Without one the engine falls through to a blocking input() on a
        # worker thread that has no console to answer it.
        problems = lint_gates(self._gate(provider=None))
        self.assertEqual(len(problems), 1)
        self.assertIn("input()", problems[0])

    def test_a_default_outcome_is_refused(self) -> None:
        self.assertEqual(len(lint_gates(self._gate(default_outcome="approve"))), 1)

    def test_a_method_with_no_human_feedback_is_not_linted(self) -> None:
        self.assertEqual(lint_gates({"methods": {"n0_a": {"do": {}}}}), [])


_ABSENT = object()


class ActionRefTests(unittest.TestCase):
    def test_every_allowlisted_ref_resolves_to_something_real(self) -> None:
        # BUILDER_ACTION_REFS is the whole code-execution answer, so a name in
        # it that does not import is a graph that compiles and then dies.
        self.assertEqual(len(BUILDER_ACTION_REFS), 10)
        for ref in sorted(BUILDER_ACTION_REFS):
            with self.subTest(ref=ref):
                self.assertIsNotNone(resolve_ref(ref, field="do"))

    def test_the_compiler_emits_only_allowlisted_refs(self) -> None:
        for factory in (straight_line, fan_out_and_join, gated_loop):
            compiled = compile_document(factory())
            emitted = {
                method["do"]["ref"] for method in compiled.methods.values()
            }
            self.assertTrue(emitted <= BUILDER_ACTION_REFS)
            assert_action_refs(compiled.definition)

    def test_a_foreign_ref_is_refused(self) -> None:
        definition = {"methods": {"n0_a": {"do": {"call": "code", "ref": "os:system"}}}}
        with self.assertRaises(BuilderCompileError) as raised:
            assert_action_refs(definition)
        self.assertIn("os:system", str(raised.exception))

    def test_a_script_action_is_refused(self) -> None:
        # CrewAI's own _actions.py records that inline script execution is not
        # sandboxed; the compiler never emits it and asserts that it did not.
        definition = {"methods": {"n0_a": {"do": {"call": "script", "code": "1"}}}}
        with self.assertRaises(BuilderCompileError) as raised:
            assert_action_refs(definition)
        self.assertIn("script", str(raised.exception))

    def test_a_foreign_gate_provider_is_refused(self) -> None:
        definition = {
            "methods": {
                "n0_a": {
                    "do": {"call": "code", "ref": "brief_crew.builder.runtime:seed_input"},
                    "human_feedback": {"provider": "os:system"},
                }
            }
        }
        with self.assertRaises(BuilderCompileError):
            assert_action_refs(definition)


class RefusalTests(unittest.TestCase):
    def test_a_cycle_closed_by_a_plain_node_is_refused(self) -> None:
        # Measured: with the loop closer as plain code the join fires once, the
        # second arrival is suppressed and kickoff() returns normally having
        # produced nothing. No exception, no warning, no frame.
        looping = document(
            [
                input_node(),
                scoper_node(),
                transform_node("back", op="default", args={"value": "x"}),
                output_node(source="${state.out__scoper}"),
            ],
            [
                edge("e1", "idea", "scoper"),
                edge("e2", "scoper", "back"),
                edge("e3", "back", "scoper"),
                edge("e4", "scoper", "report"),
            ],
        )
        with self.assertRaises(BuilderCompileError) as raised:
            compile_document(looping)
        self.assertIn(
            bounds.BACK_EDGE_NOT_ROUTER,
            [problem.code for problem in raised.exception.problems],
        )

    def test_the_problems_travel_with_the_refusal(self) -> None:
        broken = document(
            [input_node(), output_node(source="${state.out__idea}")],
            [edge("e1", "idea", "ghost")],
        )
        with self.assertRaises(BuilderCompileError) as raised:
            compile_document(broken)
        self.assertTrue(raised.exception.problems)

    def test_an_unknown_agent_id_is_refused_by_name(self) -> None:
        unknown = document(
            [
                input_node(),
                node("mystery", "agent", {"agent_id": "nobody", "tier": "cheap"}),
                output_node(source="${state.out__mystery}"),
            ],
            [edge("e1", "idea", "mystery"), edge("e2", "mystery", "report")],
        )
        with self.assertRaises(BuilderCompileError) as raised:
            compile_document(unknown)
        self.assertIn("nobody", str(raised.exception))
        self.assertIn("scoper", str(raised.exception))

    def test_a_prompt_the_yaml_task_needs_and_the_node_omits_is_refused(self) -> None:
        # CrewAI interpolates inside kickoff, so without this the run fails
        # AFTER every upstream node has been billed for the context this one
        # was going to use.
        starved = document(
            [
                input_node(),
                node("scoper", "agent", {"agent_id": "scoper", "tier": "cheap"}),
                output_node(source="${state.out__scoper}"),
            ],
            [edge("e1", "idea", "scoper"), edge("e2", "scoper", "report")],
        )
        with self.assertRaises(BuilderCompileError) as raised:
            compile_document(starved)
        self.assertIn("human_override", str(raised.exception))
        self.assertIn("idea", str(raised.exception))

    def test_an_unknown_crew_id_is_refused(self) -> None:
        unknown = document(
            [
                input_node(),
                node("bad", "crew", {"crew_id": "nope", "tier": "cheap"}),
                output_node(source="${state.out__bad}"),
            ],
            [edge("e1", "idea", "bad"), edge("e2", "bad", "report")],
        )
        self.assertTrue(library_problems(unknown))

    def test_a_reference_to_a_node_that_does_not_exist_is_refused(self) -> None:
        dangling = document(
            [input_node(), scoper_node(), output_node(source="${state.out__ghost}")],
            [edge("e1", "idea", "scoper"), edge("e2", "scoper", "report")],
        )
        with self.assertRaises(BuilderCompileError) as raised:
            compile_document(dangling)
        self.assertIn("ghost", str(raised.exception))

    def test_a_router_operand_that_reads_as_an_expression_is_refused(self) -> None:
        # `RouterBranch.value` is the one author scalar the schema does not run
        # through its `${` check, and a compiled `with:` block is CEL-rendered.
        smuggled = document(
            [
                input_node(),
                node(
                    "again",
                    "router",
                    {
                        "branches": [
                            {
                                "label": "retry",
                                "op": "eq",
                                "key": "turns__confirm",
                                "value": "${state.out__idea}",
                            },
                            {"label": "onward", "op": "otherwise"},
                        ]
                    },
                ),
                output_node(source="${state.out__idea}"),
            ],
            [
                edge("e1", "idea", "again"),
                edge("e2", "again", "report", source_port="onward"),
                edge("e3", "again", "report", source_port="retry"),
            ],
        )
        with self.assertRaises(BuilderCompileError) as raised:
            compile_document(smuggled)
        self.assertIn("literal", str(raised.exception))

    def test_an_input_field_that_collides_with_a_compiler_key_is_refused(self) -> None:
        colliding = document(
            [
                input_node("idea", field="out__scoper"),
                scoper_node(),
                output_node(source="${state.out__scoper}"),
            ],
            [edge("e1", "idea", "scoper"), edge("e2", "scoper", "report")],
            input_field="out__scoper",
        )
        with self.assertRaises(BuilderCompileError) as raised:
            compile_document(colliding)
        self.assertIn("out__", str(raised.exception))

    def test_a_listener_on_an_event_nothing_produces_is_refused(self) -> None:
        from brief_crew.builder.compiler import _assert_routers_declare_what_they_emit

        # Measured as the single most dangerous silent failure in the spikes: a
        # router returned 'fail' while the successor listened on 'route_fail',
        # and the run ended with no error at all.
        with self.assertRaises(BuilderCompileError):
            _assert_routers_declare_what_they_emit(
                {"methods": {"n0_a": {"do": {}, "listen": "e9_nothing"}}}
            )


# --------------------------------------------------------------------------
# Execution - the compiled definition really runs
# --------------------------------------------------------------------------
class ExecutionTests(unittest.TestCase):
    def test_a_compiled_document_runs_end_to_end(self) -> None:
        compiled = compile_document(straight_line())
        factories = StubFactories(outputs={"scoper": "SCOPE"})
        result, flow = run(compiled, factories=factories)

        self.assertEqual(result, {BODY_KEY: "SCOPE", "node_id": "report"})
        self.assertEqual(flow.state["out__idea"], "a scheduling assistant")
        self.assertEqual(flow.state["out__scoper"], "SCOPE")
        # The seeded input reached the agent through the compiled `with:` block.
        self.assertEqual(
            factories.kickoffs,
            [("scoper", {"idea": "a scheduling assistant", "human_override": ""})],
        )

    def test_the_node_config_reaches_the_thing_that_gets_built(self) -> None:
        compiled = compile_document(fan_out_and_join())
        factories = StubFactories()
        run(compiled, factories=factories)
        built = {entry["node_id"]: entry for entry in factories.built}
        self.assertEqual(built["scoper"]["tier"], "escalation")
        self.assertEqual(built["market"]["tier"], "cheap")
        self.assertEqual(built["market"]["tools"], (MARKET_TOOL,))
        self.assertEqual(built["signal"]["tools"], ())

    def test_the_and_join_fires_once_after_both_branches(self) -> None:
        compiled = compile_document(fan_out_and_join())
        factories = StubFactories(outputs={"market": '{"m": 1}', "signal": '{"s": 2}'})
        result, flow = run(compiled, factories=factories)

        # Both branches ran, and the join saw both outputs - not one of them
        # twice, and not one of them alone.
        self.assertEqual(flow.state["out__merge"], {"m": 1, "s": 2})
        self.assertEqual(
            sorted(node_id for node_id, _ in factories.kickoffs),
            ["market", "scoper", "signal"],
        )
        self.assertEqual(json.loads(result[BODY_KEY]), {"m": 1, "s": 2})
        # ONCE, not once per arriving branch: an `and` join that fired twice
        # would run everything downstream of it twice, at full price.
        self.assertEqual(
            [output for output in flow.method_outputs if output == {"m": 1, "s": 2}],
            [{"m": 1, "s": 2}],
        )

    def test_the_join_is_not_the_listener_crewai_suppresses(self) -> None:
        compiled = compile_document(fan_out_and_join())
        from crewai.flow.runtime import _is_multi_event_or

        listen = compiled.methods[compiled.method_idents["merge"][0]]["listen"]
        self.assertFalse(_is_multi_event_or(listen))

    def test_a_router_takes_the_branch_its_rule_selects(self) -> None:
        forked = document(
            [
                input_node(),
                transform_node("score", op="default", args={"value": 9, "default": 0}),
                router_node("fork", key="out__score", value=5),
                transform_node("high", op="default", args={"value": "HIGH"}),
                transform_node("low", op="default", args={"value": "LOW"}),
                output_node(source="${state.out__high}"),
            ],
            [
                edge("e1", "idea", "score"),
                edge("e2", "score", "fork"),
                edge("e3", "fork", "high", source_port="retry"),
                edge("e4", "fork", "low", source_port="onward"),
                edge("e5", "high", "report"),
                edge("e6", "low", "report"),
            ],
        )
        _, flow = run(compile_document(forked))
        # A router passes its input through rather than recording its own
        # label: what a downstream node wants is what flowed through it.
        self.assertEqual(flow.state["out__fork"], 9)
        self.assertEqual(flow.state["out__high"], "HIGH")
        self.assertIsNone(flow.state["out__low"])

    def test_a_router_falls_through_to_otherwise(self) -> None:
        forked = document(
            [
                input_node(),
                transform_node("score", op="default", args={"value": 1, "default": 0}),
                router_node("fork", key="out__score", value=5),
                transform_node("high", op="default", args={"value": "HIGH"}),
                transform_node("low", op="default", args={"value": "LOW"}),
                output_node(source="${state.out__low}"),
            ],
            [
                edge("e1", "idea", "score"),
                edge("e2", "score", "fork"),
                edge("e3", "fork", "high", source_port="retry"),
                edge("e4", "fork", "low", source_port="onward"),
                edge("e5", "high", "report"),
                edge("e6", "low", "report"),
            ],
        )
        result, flow = run(compile_document(forked))
        self.assertEqual(flow.state["out__fork"], 1)
        self.assertEqual(result[BODY_KEY], "LOW")

    def test_a_required_input_the_run_did_not_carry_is_refused(self) -> None:
        compiled = compile_document(straight_line())
        flow = Flow.from_declaration(contents=compiled.definition, suppress_flow_events=True)
        with use_crew_factories(StubFactories()):
            with self.assertRaises(BuilderRuntimeError):
                flow.kickoff(inputs={"idea": "   "})


class TransformOpTests(unittest.TestCase):
    """The six operations, on a stand-in flow: no model, no engine, no cost."""

    class _Flow:
        def __init__(self) -> None:
            self.state: dict[str, Any] = {}

    def _apply(self, op: str, args: dict[str, Any]) -> Any:
        flow = self._Flow()
        return transform(flow, node_id="t", op=op, args=args)

    def test_the_six_ops_are_the_six_the_schema_allows(self) -> None:
        self.assertEqual(
            BUILDER_TRANSFORM_OPS,
            {"pick", "merge", "join_text", "to_json", "default", "format"},
        )

    def test_pick_reads_a_key_out_of_an_object_or_its_json(self) -> None:
        self.assertEqual(self._apply("pick", {"source": {"a": 1}, "key": "a"}), 1)
        self.assertEqual(self._apply("pick", {"source": '{"a": 2}', "key": "a"}), 2)
        self.assertIsNone(self._apply("pick", {"source": "not json", "key": "a"}))

    def test_merge_folds_objects_in_and_keeps_scalars_under_their_name(self) -> None:
        self.assertEqual(
            self._apply("merge", {"a": {"x": 1}, "b": '{"y": 2}', "c": 3}),
            {"x": 1, "y": 2, "c": 3},
        )

    def test_join_text_uses_the_declared_separator(self) -> None:
        self.assertEqual(
            self._apply("join_text", {"a": "one", "b": "two", "separator": " / "}),
            "one / two",
        )

    def test_to_json_serialises_the_declared_value(self) -> None:
        self.assertEqual(self._apply("to_json", {"value": {"a": 1}}), '{"a": 1}')

    def test_default_does_not_eat_a_legitimate_zero(self) -> None:
        # `value or default` is the defect that once priced a 128,069-token run
        # at nothing. Only None and "" count as absent.
        self.assertEqual(self._apply("default", {"value": 0, "default": 7}), 0)
        self.assertEqual(self._apply("default", {"value": False, "default": 7}), False)
        self.assertEqual(self._apply("default", {"value": None, "default": 7}), 7)
        self.assertEqual(self._apply("default", {"value": "", "default": 7}), 7)

    def test_format_substitutes_only_declared_names(self) -> None:
        self.assertEqual(
            self._apply("format", {"template": "hi {name}, {absent}", "name": "you"}),
            "hi you, {absent}",
        )

    def test_format_is_not_str_format_and_cannot_walk_out_of_the_data(self) -> None:
        # str.format on an author template is an attribute-read primitive:
        # {a.__class__.__init__.__globals__} walks straight out of the values.
        rendered = self._apply(
            "format", {"template": "{a.__class__}", "a": "x"}
        )
        self.assertEqual(rendered, "{a.__class__}")

    def test_an_unknown_op_is_refused(self) -> None:
        with self.assertRaises(BuilderRuntimeError):
            self._apply("exec", {})


class CancellationTests(unittest.TestCase):
    def test_a_set_flag_aborts_at_the_next_node_boundary(self) -> None:
        from crewai.hooks import HookAborted

        flag = threading.Event()
        flag.set()
        with builder_cancellation(flag):
            with self.assertRaises(HookAborted):
                checkpoint("n1_scoper")

    def test_an_unset_flag_passes_through(self) -> None:
        with builder_cancellation(threading.Event()):
            self.assertIsNone(checkpoint("n1_scoper"))

    def test_the_scope_does_not_leak_to_the_next_run(self) -> None:
        flag = threading.Event()
        flag.set()
        with builder_cancellation(flag):
            pass
        self.assertIsNone(checkpoint("n1_scoper"))

    def test_a_cancelled_run_stops_before_the_next_node(self) -> None:
        compiled = compile_document(fan_out_and_join())
        flow = Flow.from_declaration(contents=compiled.definition, suppress_flow_events=True)
        flag = threading.Event()
        flag.set()
        with builder_cancellation(flag), use_crew_factories(StubFactories()):
            with self.assertRaises(Exception):
                flow.kickoff(inputs={"idea": "a scheduling assistant"})
        self.assertIsNone(flow.state["out__scoper"])


class LibraryTests(unittest.TestCase):
    def test_every_registered_agent_exists_in_the_yaml(self) -> None:
        # A renamed YAML entry must fail a test rather than silently make an
        # agent unbindable at the first paid run.
        from brief_crew.builder.runtime import _yaml_config

        agents = _yaml_config("agents.yaml")
        tasks = _yaml_config("tasks.yaml")
        for agent_id, spec in BUILDER_AGENT_LIBRARY.items():
            with self.subTest(agent=agent_id):
                self.assertIn(spec.agent_key, agents)
                self.assertIn(spec.task_key, tasks)

    def test_every_registered_crew_exists(self) -> None:
        import brief_crew.crews.validator_crew as validator_crew

        for crew_id, class_name in BUILDER_CREW_LIBRARY.items():
            with self.subTest(crew=crew_id):
                self.assertTrue(hasattr(validator_crew, class_name))

    def test_the_default_factory_builds_a_real_one_agent_crew(self) -> None:
        # Constructs an Agent, a Task and a Crew for real - no network, no
        # model call - because the wiring is what this is about: the tier's
        # model, the YAML prompt, the bound tool and the retry ceiling.
        from brief_crew.builder.runtime import DefaultCrewFactories
        from brief_crew.config import CHEAP_MODEL, ESCALATION_MODEL

        crew = DefaultCrewFactories().agent_crew(
            node_id="market",
            agent_id="market_analyst",
            tier="cheap",
            tools=[MARKET_TOOL],
            max_iter=3,
            guardrail_max_retries=1,
        )
        agent, task = crew.agents[0], crew.tasks[0]
        # CrewAI's LLM.__new__ strips the `openrouter/` prefix for a native
        # provider - the same strip that once made every call price at $0.00 -
        # so the constant is compared by suffix rather than by equality.
        self.assertTrue(CHEAP_MODEL.endswith(agent.llm.model))
        self.assertFalse(ESCALATION_MODEL.endswith(agent.llm.model))
        self.assertEqual(agent.max_iter, 3)
        self.assertEqual([tool.name for tool in agent.tools], [MARKET_TOOL])
        self.assertEqual(task.guardrail_max_retries, 1)
        # The prompt came from config/tasks.yaml and nowhere else.
        self.assertIn("{scoped_idea_json}", task.description)

    def test_the_escalation_tier_selects_the_other_model(self) -> None:
        from brief_crew.builder.runtime import DefaultCrewFactories
        from brief_crew.config import ESCALATION_MODEL

        crew = DefaultCrewFactories().agent_crew(
            node_id="scoper",
            agent_id="scoper",
            tier="escalation",
            tools=[],
            max_iter=2,
            guardrail_max_retries=2,
        )
        self.assertTrue(ESCALATION_MODEL.endswith(crew.agents[0].llm.model))

    def test_an_unknown_tier_is_refused_rather_than_defaulted(self) -> None:
        from brief_crew.builder.runtime import DefaultCrewFactories

        with self.assertRaises(BuilderRuntimeError):
            DefaultCrewFactories().agent_crew(
                node_id="x",
                agent_id="scoper",
                tier="free",
                tools=[],
                max_iter=2,
                guardrail_max_retries=0,
            )

    def test_no_builder_module_inlines_a_model_name(self) -> None:
        # The platform rule, asserted rather than trusted: a tier is a word in
        # a document, and the model it means lives in config.py.
        import pathlib

        import brief_crew.builder as package

        for name in ("compiler.py", "runtime.py", "gates.py"):
            source = (pathlib.Path(package.__file__).parent / name).read_text(
                encoding="utf-8"
            )
            with self.subTest(module=name):
                self.assertNotIn("openrouter/", source)
                self.assertNotIn("gemini", source.lower())

    def test_the_private_crewai_rearm_hook_still_exists(self) -> None:
        # `route_gate` and `route_branch` call `_discard_or_listener` before
        # re-entering a loop. It is private API, knowingly: CrewAI's own cyclic
        # support leans on the same family. If an upgrade removes it, this
        # fails here rather than by ending runs silently.
        compiled = compile_document(gated_loop())
        flow = Flow.from_declaration(contents=compiled.definition, suppress_flow_events=True)
        self.assertTrue(callable(getattr(flow, "_discard_or_listener", None)))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
