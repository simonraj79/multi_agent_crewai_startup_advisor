"""The `builder.flow/v1` document schema, and the per-workflow reserved keys.

What this module pins is SHAPE: the things `document.py` raises about, one
object at a time. Counts, wiring and price are `test_bounds.py` and
`test_budget.py`, and the split is asserted here too - a router with nine
branches must PARSE, because refusing it at parse time would deny the canvas
the numbered message the bounds table promises.

It also carries the factories the other two modules build documents with, the
way `tests/validator/test_flow.py` carries `fixtures` for five other modules.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timezone
from typing import Any

from pydantic import ValidationError

from brief_crew.builder import (
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
from brief_crew.config import (
    BUILDER_DOCUMENT_SCHEMA,
    BUILDER_MAX_AGENT_ITER,
    BUILDER_MAX_GUARDRAIL_RETRIES,
    BUILDER_MAX_ID_CHARS,
    BUILDER_MAX_NAME_CHARS,
    BUILDER_RESEARCH_TOOLS,
    GLOBAL_RESERVED_RUN_INPUT_KEYS,
    MAX_RUN_INPUT_CHARS,
    PUBLIC_RUN_INPUT_KEYS,
    RESERVED_RUN_INPUT_KEYS,
    RUN_RESULT_BODY_KEYS,
    WORKFLOW_RESERVED_RUN_INPUT_KEYS,
    all_reserved_run_input_keys,
    register_workflow_reserved_run_input_keys,
    reserved_run_input_keys,
)

DOCUMENT_ID = "ug_7f3a2b19"
BODY_KEY = RUN_RESULT_BODY_KEYS[0]
MARKET_TOOL = "research_market_landscape"


# --------------------------------------------------------------------------
# Factories, shared with test_bounds.py and test_budget.py
# --------------------------------------------------------------------------
def node(node_id: str, kind: str, config: dict[str, Any] | None = None) -> dict[str, Any]:
    """A node dict. `label` defaults to the id, which is what a canvas does."""

    return {"id": node_id, "kind": kind, "label": node_id[:40], "config": config or {}}


def input_node(node_id: str = "idea", field: str = "idea") -> dict[str, Any]:
    return node(node_id, "input", {"field": field})


def agent_node(
    node_id: str,
    *,
    tier: str = "cheap",
    tools: tuple[str, ...] = (),
    max_iter: int = 2,
    guardrail_max_retries: int = 2,
) -> dict[str, Any]:
    return node(
        node_id,
        "agent",
        {
            "agent_id": node_id,
            "tier": tier,
            "tools": list(tools),
            "max_iter": max_iter,
            "guardrail_max_retries": guardrail_max_retries,
        },
    )


def gate_node(node_id: str, *, max_turns: int = 1) -> dict[str, Any]:
    return node(node_id, "gate", {"message": "Confirm this.", "max_turns": max_turns})


def router_node(node_id: str, *, branches: tuple[dict[str, Any], ...] | None = None) -> dict[str, Any]:
    declared = branches or (
        {"label": "again", "op": "gte", "key": "turns", "value": 1},
        {"label": "onward", "op": "otherwise"},
    )
    return node(node_id, "router", {"branches": list(declared)})


def transform_node(node_id: str, *, op: str = "merge") -> dict[str, Any]:
    return node(node_id, "transform", {"op": op, "args": {}})


def output_node(node_id: str = "report") -> dict[str, Any]:
    return node(node_id, "output", {"body_key": BODY_KEY, "source": "${state.out__writer}"})


def edge(
    edge_id: str, source: str, target: str, *, source_port: str = "out"
) -> dict[str, Any]:
    return {
        "id": edge_id,
        "source": source,
        "source_port": source_port,
        "target": target,
        "target_port": "in",
    }


def document(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]] | None = None,
    **overrides: Any,
) -> BuilderDocument:
    """A valid-by-default document, so a test states only what it is about."""

    payload: dict[str, Any] = {
        "schema": BUILDER_DOCUMENT_SCHEMA,
        "id": DOCUMENT_ID,
        "name": "Test graph",
        "version": 1,
        "input_field": "idea",
        "nodes": nodes,
        "edges": edges or [],
    }
    payload.update(overrides)
    return BuilderDocument.model_validate(payload)


def chain(*node_ids: str, prefix: str = "e") -> list[dict[str, Any]]:
    """Edges wiring the given ids nose to tail, all on the `out` port."""

    return [
        edge(f"{prefix}{index}", source, target)
        for index, (source, target) in enumerate(zip(node_ids, node_ids[1:]))
    ]


def validator_shaped_document() -> BuilderDocument:
    """Fourteen nodes wired the way the shipped validator actually runs.

    A realistic document rather than a small one, because a graph that only
    passes because it is tiny proves nothing: 8 billable nodes, 5 of them
    escalation, a 4-wide fan-out at the scope gate and 2 cycles. Those four
    counts are the SHIPPED VALIDATOR'S, read off `service/graph.py`, and they
    are what the bounds were originally set to - exactly, with no headroom, so
    this graph errored on the first node anybody added to it. Three of the four
    bounds have since been raised over these counts; MAX_FANOUT_WIDTH has not,
    and the fan-out here still sits on it deliberately. See the notes above
    MAX_BILLABLE_NODES and MAX_FANOUT_WIDTH in `config.py`.

    Both loops are closed by a ROUTER, which is the rule that makes the whole
    thing legal: `revise_scope` hands to `route_revise`, and it is the router
    that draws the back edge.
    """

    nodes = [
        input_node("idea", "idea"),
        agent_node("scope_idea", tier="escalation"),
        gate_node("confirm_scope", max_turns=3),
        agent_node("revise_scope", tier="escalation"),
        router_node(
            "route_revise",
            branches=(
                {"label": "again", "op": "otherwise"},
                {"label": "give_up", "op": "gte", "key": "scope_turns", "value": 3},
            ),
        ),
        agent_node("research_market", tools=(MARKET_TOOL,)),
        agent_node("research_sentiment", tools=("analyze_community_sentiment",)),
        agent_node("research_feasibility", tools=("assess_technical_feasibility",)),
        agent_node("synthesize", tier="escalation"),
        gate_node("review_verdict", max_turns=3),
        agent_node("revise_verdict", tier="escalation"),
        router_node(
            "route_reverdict",
            branches=(
                {"label": "again", "op": "otherwise"},
                {"label": "give_up", "op": "gte", "key": "verdict_turns", "value": 3},
            ),
        ),
        agent_node("write_report", tier="escalation"),
        output_node("report"),
    ]
    edges = [
        edge("e01", "idea", "scope_idea"),
        edge("e02", "scope_idea", "confirm_scope"),
        edge("e03", "confirm_scope", "research_market", source_port="approve"),
        edge("e04", "confirm_scope", "research_sentiment", source_port="approve"),
        edge("e05", "confirm_scope", "research_feasibility", source_port="approve"),
        edge("e06", "confirm_scope", "revise_scope", source_port="revise"),
        edge("e07", "revise_scope", "route_revise"),
        edge("e08", "route_revise", "confirm_scope", source_port="again"),
        edge("e09", "route_revise", "report", source_port="give_up"),
        edge("e10", "research_market", "synthesize"),
        edge("e11", "research_sentiment", "synthesize"),
        edge("e12", "research_feasibility", "synthesize"),
        edge("e13", "synthesize", "review_verdict"),
        edge("e14", "review_verdict", "write_report", source_port="approve"),
        edge("e15", "review_verdict", "revise_verdict", source_port="revise"),
        edge("e16", "revise_verdict", "route_reverdict"),
        edge("e17", "route_reverdict", "review_verdict", source_port="again"),
        edge("e18", "route_reverdict", "report", source_port="give_up"),
        edge("e19", "write_report", "report"),
    ]
    return document(nodes, edges, name="Validator shaped", joins={"synthesize": "all"})


# --------------------------------------------------------------------------
# Tests
# --------------------------------------------------------------------------
class NodeKindTests(unittest.TestCase):
    """Each of the seven kinds parses into its own config model."""

    def test_every_kind_parses_into_its_own_config_model(self) -> None:
        cases = [
            (input_node("idea"), InputConfig),
            (agent_node("scoper"), AgentConfig),
            (node("crew", "crew", {"crew_id": "market_crew", "tier": "cheap"}), CrewConfig),
            (gate_node("confirm"), GateConfig),
            (router_node("route"), RouterConfig),
            (transform_node("merge"), TransformConfig),
            (output_node(), OutputConfig),
        ]
        for payload, expected in cases:
            with self.subTest(kind=payload["kind"]):
                parsed = BuilderNode.model_validate(payload)
                self.assertIsInstance(parsed.config, expected)

    def test_an_eighth_kind_is_refused_and_the_seven_are_named(self) -> None:
        with self.assertRaises(ValidationError) as caught:
            BuilderNode.model_validate(node("thing", "python", {}))
        message = str(caught.exception)
        for kind in ("input", "agent", "crew", "gate", "router", "transform", "output"):
            self.assertIn(kind, message)

    def test_only_agent_and_crew_are_billable(self) -> None:
        billable = {
            BuilderNode.model_validate(payload).kind
            for payload in (
                input_node("idea"),
                agent_node("a"),
                node("c", "crew", {"crew_id": "c", "tier": "cheap"}),
                gate_node("g"),
                router_node("r"),
                transform_node("t"),
                output_node(),
            )
            if BuilderNode.model_validate(payload).is_billable
        }
        self.assertEqual(billable, {"agent", "crew"})

    def test_out_ports_are_the_ones_the_taxonomy_declares(self) -> None:
        self.assertEqual(BuilderNode.model_validate(input_node("i")).out_ports, ("out",))
        self.assertEqual(BuilderNode.model_validate(gate_node("g")).out_ports, ("approve", "revise"))
        self.assertEqual(BuilderNode.model_validate(output_node()).out_ports, ())
        self.assertEqual(
            BuilderNode.model_validate(router_node("r")).out_ports, ("again", "onward")
        )

    def test_only_an_input_node_refuses_an_incoming_edge(self) -> None:
        self.assertFalse(BuilderNode.model_validate(input_node("i")).accepts_incoming)
        self.assertTrue(BuilderNode.model_validate(output_node()).accepts_incoming)


class IdentifierShapeTests(unittest.TestCase):
    """The regexes, at their boundaries."""

    def test_a_node_id_of_exactly_forty_characters_is_accepted(self) -> None:
        node_id = "a" + "b" * (BUILDER_MAX_ID_CHARS - 1)
        self.assertEqual(len(node_id), BUILDER_MAX_ID_CHARS)
        self.assertEqual(BuilderNode.model_validate(agent_node(node_id)).id, node_id)

    def test_a_node_id_of_forty_one_characters_is_refused(self) -> None:
        node_id = "a" + "b" * BUILDER_MAX_ID_CHARS
        with self.assertRaises(ValidationError):
            BuilderNode.model_validate(agent_node(node_id))

    def test_a_node_id_must_be_lowercase_and_start_with_a_letter(self) -> None:
        for bad in ("Scoper", "7scoper", "_scoper", "scope-idea", "scope idea", ""):
            with self.subTest(node_id=bad), self.assertRaises(ValidationError):
                BuilderNode.model_validate(agent_node(bad))

    def test_the_document_id_is_the_server_assigned_shape(self) -> None:
        document([input_node("idea")])
        for bad in ("ug_7F3A2B19", "ug_7f3a2b1", "7f3a2b19", "ug_7f3a2b199"):
            with self.subTest(document_id=bad), self.assertRaises(ValidationError):
                document([input_node("idea")], id=bad)

    def test_the_name_is_bounded_at_eighty_characters(self) -> None:
        document([input_node("idea")], name="x" * BUILDER_MAX_NAME_CHARS)
        with self.assertRaises(ValidationError):
            document([input_node("idea")], name="x" * (BUILDER_MAX_NAME_CHARS + 1))
        with self.assertRaises(ValidationError):
            document([input_node("idea")], name="   ")

    def test_a_version_must_be_at_least_one(self) -> None:
        self.assertEqual(document([input_node("idea")], version=1).version, 1)
        with self.assertRaises(ValidationError):
            document([input_node("idea")], version=0)


class StateReferenceTests(unittest.TestCase):
    """`${state.<key>}` is the one expression, and a near miss is refused."""

    def test_the_single_key_reference_is_accepted(self) -> None:
        parsed = BuilderNode.model_validate(
            node(
                "scoper",
                "agent",
                {
                    "agent_id": "scoper",
                    "tier": "cheap",
                    "prompt_inputs": {"idea": "${state.out__idea}"},
                },
            )
        )
        assert isinstance(parsed.config, AgentConfig)
        self.assertEqual(parsed.config.prompt_inputs["idea"], "${state.out__idea}")

    def test_a_nested_reference_is_refused_rather_than_treated_as_text(self) -> None:
        with self.assertRaises(ValidationError) as caught:
            BuilderNode.model_validate(
                node(
                    "scoper",
                    "agent",
                    {
                        "agent_id": "scoper",
                        "tier": "cheap",
                        "prompt_inputs": {"idea": "${state.out__idea.segment}"},
                    },
                )
            )
        message = str(caught.exception)
        self.assertIn("idea", message)
        self.assertIn("does not resolve", message)

    def test_a_plain_literal_is_untouched(self) -> None:
        parsed = BuilderNode.model_validate(
            node(
                "scoper",
                "agent",
                {
                    "agent_id": "scoper",
                    "tier": "cheap",
                    "prompt_inputs": {"tone": "terse", "depth": 3, "deep": True, "none": None},
                },
            )
        )
        assert isinstance(parsed.config, AgentConfig)
        self.assertEqual(parsed.config.prompt_inputs["tone"], "terse")
        self.assertEqual(parsed.config.prompt_inputs["depth"], 3)

    def test_the_same_rule_covers_transform_args_and_an_output_source(self) -> None:
        with self.assertRaises(ValidationError):
            BuilderNode.model_validate(
                node("merge", "transform", {"op": "merge", "args": {"a": "${state.a.b}"}})
            )
        with self.assertRaises(ValidationError):
            BuilderNode.model_validate(
                node("report", "output", {"body_key": BODY_KEY, "source": "${state.a.b}"})
            )


class AgentConfigTests(unittest.TestCase):
    """Tier, tools and the two retry ceilings."""

    def test_only_the_three_registered_research_tools_may_be_bound(self) -> None:
        parsed = BuilderNode.model_validate(agent_node("m", tools=(MARKET_TOOL,)))
        assert isinstance(parsed.config, AgentConfig)
        self.assertEqual(parsed.config.tools, (MARKET_TOOL,))
        with self.assertRaises(ValidationError) as caught:
            BuilderNode.model_validate(agent_node("m", tools=("read_the_filesystem",)))
        self.assertIn("read_the_filesystem", str(caught.exception))

    def test_the_same_tool_may_not_be_bound_twice(self) -> None:
        with self.assertRaises(ValidationError):
            BuilderNode.model_validate(agent_node("m", tools=(MARKET_TOOL, MARKET_TOOL)))

    def test_max_iter_is_bounded_at_its_ceiling(self) -> None:
        BuilderNode.model_validate(agent_node("a", max_iter=BUILDER_MAX_AGENT_ITER))
        with self.assertRaises(ValidationError):
            BuilderNode.model_validate(agent_node("a", max_iter=BUILDER_MAX_AGENT_ITER + 1))
        with self.assertRaises(ValidationError):
            BuilderNode.model_validate(agent_node("a", max_iter=0))

    def test_guardrail_retries_are_bounded_at_two(self) -> None:
        BuilderNode.model_validate(
            agent_node("a", guardrail_max_retries=BUILDER_MAX_GUARDRAIL_RETRIES)
        )
        with self.assertRaises(ValidationError):
            BuilderNode.model_validate(
                agent_node("a", guardrail_max_retries=BUILDER_MAX_GUARDRAIL_RETRIES + 1)
            )

    def test_a_tier_outside_the_two_declared_models_is_refused(self) -> None:
        with self.assertRaises(ValidationError):
            BuilderNode.model_validate(agent_node("a", tier="premium"))

    def test_a_crew_node_has_no_tools_field_at_all(self) -> None:
        with self.assertRaises(ValidationError):
            BuilderNode.model_validate(
                node("c", "crew", {"crew_id": "c", "tier": "cheap", "tools": [MARKET_TOOL]})
            )


class InputAndOutputConfigTests(unittest.TestCase):
    def test_max_chars_cannot_exceed_what_the_run_endpoint_accepts(self) -> None:
        BuilderNode.model_validate(
            node("idea", "input", {"field": "idea", "max_chars": MAX_RUN_INPUT_CHARS})
        )
        with self.assertRaises(ValidationError):
            BuilderNode.model_validate(
                node("idea", "input", {"field": "idea", "max_chars": MAX_RUN_INPUT_CHARS + 1})
            )

    def test_the_body_key_must_be_one_that_escapes_the_frame_clip(self) -> None:
        with self.assertRaises(ValidationError) as caught:
            BuilderNode.model_validate(
                node("report", "output", {"body_key": "report_text", "source": None})
            )
        self.assertIn("truncated", str(caught.exception))


class RouterBranchTests(unittest.TestCase):
    """One comparison per branch, and `otherwise` takes neither key nor value."""

    def test_an_unknown_comparison_is_refused(self) -> None:
        with self.assertRaises(ValidationError) as caught:
            BuilderNode.model_validate(
                router_node("r", branches=({"label": "a", "op": "matches", "key": "s"},))
            )
        self.assertIn("matches", str(caught.exception))

    def test_a_comparison_must_name_the_state_key_it_reads(self) -> None:
        with self.assertRaises(ValidationError) as caught:
            BuilderNode.model_validate(
                router_node("r", branches=({"label": "a", "op": "gte", "value": 6},))
            )
        self.assertIn("state key", str(caught.exception))

    def test_the_otherwise_branch_takes_no_key_and_no_value(self) -> None:
        for extra in ({"key": "score"}, {"value": 3}):
            with self.subTest(extra=extra), self.assertRaises(ValidationError):
                BuilderNode.model_validate(
                    router_node("r", branches=({"label": "a", "op": "otherwise", **extra},))
                )

    def test_a_router_with_nine_branches_parses_because_counting_is_not_shape(self) -> None:
        """The bound is reported by `bounds.py`, with the number quoted."""

        branches = tuple(
            {"label": f"b{index}", "op": "eq", "key": "score", "value": index} for index in range(9)
        )
        parsed = BuilderNode.model_validate(router_node("r", branches=branches))
        assert isinstance(parsed.config, RouterConfig)
        self.assertEqual(len(parsed.config.branches), 9)


class TransformConfigTests(unittest.TestCase):
    def test_the_six_operations_are_the_whole_vocabulary(self) -> None:
        for op in ("pick", "merge", "join_text", "to_json", "default", "format"):
            with self.subTest(op=op):
                BuilderNode.model_validate(transform_node("t", op=op))
        with self.assertRaises(ValidationError) as caught:
            BuilderNode.model_validate(transform_node("t", op="eval"))
        self.assertIn("eval", str(caught.exception))


class JoinTests(unittest.TestCase):
    """`join: "any"` is the one policy rule refused at parse time."""

    def test_all_is_accepted(self) -> None:
        parsed = document([input_node("idea")], joins={"idea": "all"})
        self.assertEqual(parsed.joins, {"idea": "all"})

    def test_any_is_refused_and_the_message_says_what_it_would_do(self) -> None:
        with self.assertRaises(ValidationError) as caught:
            document([input_node("idea")], joins={"synthesize": "any"})
        message = str(caught.exception)
        self.assertIn("synthesize", message)
        self.assertIn("silently", message)
        self.assertIn("or_()", message)

    def test_a_third_join_mode_is_refused_too(self) -> None:
        with self.assertRaises(ValidationError) as caught:
            document([input_node("idea")], joins={"synthesize": "first"})
        self.assertIn("first", str(caught.exception))


class DocumentShapeTests(unittest.TestCase):
    def test_an_unknown_schema_names_the_one_this_service_compiles(self) -> None:
        with self.assertRaises(ValidationError) as caught:
            document([input_node("idea")], schema="builder.flow/v2")
        self.assertIn(BUILDER_DOCUMENT_SCHEMA, str(caught.exception))

    def test_an_unknown_key_anywhere_is_refused(self) -> None:
        with self.assertRaises(ValidationError):
            document([input_node("idea")], notes=[{"text": "remember to..."}])
        with self.assertRaises(ValidationError):
            BuilderNode.model_validate({**agent_node("a"), "collapsed": True})
        with self.assertRaises(ValidationError):
            BuilderNode.model_validate(
                node("a", "agent", {"agent_id": "a", "tier": "cheap", "ref": "os:system"})
            )

    def test_the_document_is_frozen(self) -> None:
        parsed = document([input_node("idea")])
        with self.assertRaises(ValidationError):
            parsed.version = 2

    def test_it_round_trips_through_its_wire_form(self) -> None:
        original = validator_shaped_document()
        rebuilt = BuilderDocument.model_validate(original.model_dump(mode="json", by_alias=True))
        self.assertEqual(rebuilt, original)
        self.assertEqual(
            original.model_dump(mode="json", by_alias=True)["schema"], BUILDER_DOCUMENT_SCHEMA
        )

    def test_nodes_by_id_survives_a_duplicate_rather_than_raising(self) -> None:
        """`bounds.py` reports the duplicate; this map must still be usable."""

        parsed = document([agent_node("a"), agent_node("a")])
        self.assertEqual(set(parsed.nodes_by_id()), {"a"})

    def test_a_budget_block_parses_but_is_never_required(self) -> None:
        self.assertIsNone(document([input_node("idea")]).budget)
        priced = document(
            [input_node("idea")],
            budget=BuilderBudget(
                static_cost_usd=2.48,
                billable_nodes=5,
                escalation_nodes=3,
                cycles=1,
                compiled_at=datetime(2026, 9, 2, tzinfo=timezone.utc),
            ).model_dump(mode="json"),
        )
        assert priced.budget is not None
        self.assertAlmostEqual(priced.budget.static_cost_usd, 2.48)

    def test_the_validator_shaped_fixture_is_the_shape_it_claims(self) -> None:
        parsed = validator_shaped_document()
        self.assertEqual(len(parsed.nodes), 14)
        self.assertEqual(len(parsed.edges), 19)
        billable = [item for item in parsed.nodes if item.is_billable]
        self.assertEqual(len(billable), 8)
        self.assertEqual(len([item for item in billable if item.tier == "escalation"]), 5)


class ResearchToolNameTests(unittest.TestCase):
    """`config.py` restates the three tool names; they must not drift."""

    def test_the_allowlist_equals_the_tools_own_declared_names(self) -> None:
        from brief_crew.tools.github_feasibility import TOOL_NAME as GITHUB
        from brief_crew.tools.hn_sentiment import TOOL_NAME as HN
        from brief_crew.tools.market_research import TOOL_NAME as MARKET

        self.assertEqual(BUILDER_RESEARCH_TOOLS, frozenset({GITHUB, HN, MARKET}))


class ReservedRunInputKeyTests(unittest.TestCase):
    """Per-workflow reserved keys, and the fail-closed answer for the rest."""

    def test_the_validator_reserves_twenty_two_keys_not_two(self) -> None:
        """CLAUDE.md says two. It has said two since the fourteen were added."""

        self.assertEqual(len(RESERVED_RUN_INPUT_KEYS), 22)
        self.assertIn("feasibility_cache_enabled", RESERVED_RUN_INPUT_KEYS)

    def test_the_two_workflow_ids_are_the_ones_the_service_registers(self) -> None:
        from brief_crew.service.graph import BRIEF_WORKFLOW_ID, VALIDATOR_WORKFLOW_ID

        self.assertEqual(
            set(WORKFLOW_RESERVED_RUN_INPUT_KEYS), {BRIEF_WORKFLOW_ID, VALIDATOR_WORKFLOW_ID}
        )

    def test_brief_flows_reserved_set_is_its_state_minus_its_public_prompt(self) -> None:
        from brief_crew.main import BriefState

        declared = set(BriefState.model_fields)
        expected = declared - PUBLIC_RUN_INPUT_KEYS
        self.assertEqual(WORKFLOW_RESERVED_RUN_INPUT_KEYS["brief-flow"], expected)
        self.assertNotIn("topic", WORKFLOW_RESERVED_RUN_INPUT_KEYS["brief-flow"])

    def test_a_validator_key_is_free_on_brief_flow_and_reserved_on_the_validator(self) -> None:
        self.assertIn("verdict", reserved_run_input_keys("idea-validator"))
        self.assertNotIn("verdict", reserved_run_input_keys("brief-flow"))

    def test_crewais_own_state_restore_key_is_reserved_everywhere(self) -> None:
        for workflow_id in ("brief-flow", "idea-validator", None, "invented"):
            with self.subTest(workflow_id=workflow_id):
                self.assertIn("id", reserved_run_input_keys(workflow_id))
                self.assertIn("no_gates", reserved_run_input_keys(workflow_id))

    def test_an_unknown_or_missing_workflow_id_fails_closed_to_the_union(self) -> None:
        union = all_reserved_run_input_keys()
        self.assertEqual(reserved_run_input_keys(None), union)
        self.assertEqual(reserved_run_input_keys("never-registered"), union)
        self.assertIn("verdict", reserved_run_input_keys("never-registered"))
        self.assertIn("scraped_sources", reserved_run_input_keys("never-registered"))

    def test_registering_a_builder_graph_narrows_it_and_widens_the_union(self) -> None:
        workflow_id = "ug_deadbeef"
        self.addCleanup(WORKFLOW_RESERVED_RUN_INPUT_KEYS.pop, workflow_id, None)
        register_workflow_reserved_run_input_keys(workflow_id, {"out__scoper"})

        reserved = reserved_run_input_keys(workflow_id)
        self.assertIn("out__scoper", reserved)
        self.assertIn("no_gates", reserved)
        self.assertNotIn("verdict", reserved)
        self.assertIn("out__scoper", all_reserved_run_input_keys())
        self.assertIn("out__scoper", reserved_run_input_keys("still-unknown"))

    def test_the_global_set_is_a_subset_of_every_answer(self) -> None:
        for workflow_id in (*WORKFLOW_RESERVED_RUN_INPUT_KEYS, None, "invented"):
            with self.subTest(workflow_id=workflow_id):
                self.assertTrue(
                    GLOBAL_RESERVED_RUN_INPUT_KEYS <= reserved_run_input_keys(workflow_id)
                )


if __name__ == "__main__":
    unittest.main()
