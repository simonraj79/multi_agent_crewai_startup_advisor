"""Frame attribution for a flow that was compiled, not decorated.

`NodeRegistry.from_flow_structure` reads CrewAI's static introspection of a
decorated class. A builder graph has no such class: the compiler builds one at
runtime with `type()`, and three of the four answers that constructor needs are
simply not in the result.

* **The method names are the compiler's.** CrewAI refuses a flow definition
  whose method names fall outside `^[A-Za-z_][A-Za-z0-9_]*$`, so document node
  ids cannot be method names in general and the compiler emits `n{index}_{id}`.
  `flow_method_nodes` is a `Mapping[str, str]` and has never required identity,
  but every registry in the tree happens to be one, so nothing had ever proved
  the non-identity case end to end. `NonIdentityAttributionTests` does, through
  the real `StreamSinkAdapter` and the real serializer.
* **A runtime `@router` declares no events.** `route_targets` comes back empty
  and every `EDGE_TAKEN` frame points at the quarantine node. The document knows
  the answer, so the document is where this constructor reads it.
* **`VERDICT_NODE_ID` is the literal `"synthesize"`.** A builder graph that
  scores something has no reason to have drawn a node by that name, so the one
  frame carrying the deliverable quarantined.

The other half of this module is the regression it must not cause: the
validator's attribution is pinned here as well as in `tests/events/`, node by
node and route by route, because "additive" is a claim and the whole point of
this change is that it is invisible from the validator's side.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timezone
from typing import Any

from crewai.events import MethodExecutionStartedEvent, ToolUsageStartedEvent
from crewai.flow import build_flow_structure
from crewai.flow.flow_context import current_flow_method_name

from brief_crew.builder import compiled_identifiers
from brief_crew.builder.document import ROUTING_KINDS, BuilderDocument
from brief_crew.events import (
    FrameBuffer,
    NodeRegistry,
    QUARANTINE_NODE_ID,
    ROUTING_NODE_KINDS,
    StreamSinkAdapter,
    VERDICT_NODE_ID,
    VerdictComputedEvent,
    verdict_frame_node,
)
from brief_crew.events.models import MAX_IDENTIFIER_LENGTH
from brief_crew.events.registry import current_node_scope
from brief_crew.validator_flow import ValidatorFlow

from tests.builder.test_document import (
    agent_node,
    document,
    edge,
    gate_node,
    input_node,
    output_node,
    router_node,
    validator_shaped_document,
)
from tests.events.test_verdict_frame import RESCORED


TS = datetime(2026, 9, 2, 12, 0, 0, tzinfo=timezone.utc)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def compiled_registry(doc: BuilderDocument, **kwargs: Any) -> NodeRegistry:
    """A registry built the way the compiler will build it.

    `compiled_identifiers` returns method idents per node - two for a gate - and
    router labels in each node's own `out_ports` order, so the port-to-label map
    is one `zip`. Written out here rather than hidden in a fixture because this
    zip IS the call site `from_document`'s docstring promises, and a test that
    paraphrased it would stop proving the promise.
    """

    methods, labels = compiled_identifiers(doc)
    by_id = doc.nodes_by_id()
    return NodeRegistry.from_document(
        doc,
        method_names=methods,
        event_labels={
            node_id: dict(zip(by_id[node_id].out_ports, emitted))
            for node_id, emitted in labels.items()
        },
        **kwargs,
    )


def small_document() -> BuilderDocument:
    """Input -> agent -> gate -> two branches -> router -> output.

    Small enough to assert every entry of every table by hand, and still
    carrying one of each thing that breaks: a gate (two compiled methods, and a
    routing port that is not `out`), a router (declared branch labels), a
    fan-out from one port, and a back edge closed by that router.
    """

    nodes = [
        input_node("idea", "idea"),
        agent_node("scoper", tier="escalation"),
        gate_node("confirm", max_turns=3),
        agent_node("market"),
        agent_node("signal"),
        agent_node("redo", tier="escalation"),
        router_node(
            "again_or_not",
            branches=(
                {"label": "again", "op": "otherwise"},
                {"label": "give_up", "op": "gte", "key": "turns", "value": 3},
            ),
        ),
        output_node("report"),
    ]
    edges = [
        edge("e01", "idea", "scoper"),
        edge("e02", "scoper", "confirm"),
        edge("e03", "confirm", "market", source_port="approve"),
        edge("e04", "confirm", "signal", source_port="approve"),
        edge("e05", "confirm", "redo", source_port="revise"),
        edge("e06", "redo", "again_or_not"),
        edge("e07", "again_or_not", "confirm", source_port="again"),
        edge("e08", "again_or_not", "report", source_port="give_up"),
        edge("e09", "market", "report"),
        edge("e10", "signal", "report"),
    ]
    return document(nodes, edges, name="Small graph")


def start_method(adapter: StreamSinkAdapter, method_name: str) -> None:
    """Start a flow method the way CrewAI does, through the real event."""

    adapter(
        None,
        MethodExecutionStartedEvent(
            type="method_execution_started",
            timestamp=TS,
            flow_name="CompiledFlow",
            method_name=method_name,
            state={},
            params={},
        ),
    )


def use_tool(
    adapter: StreamSinkAdapter, tool_name: str = "research_market_landscape"
) -> None:
    """A tool call, which names no flow method of ours at all."""

    adapter(
        None,
        ToolUsageStartedEvent(
            type="tool_usage_started",
            timestamp=TS,
            tool_name=tool_name,
            tool_args={"query": "clinic scheduling"},
            tool_class="MarketResearchTool",
        ),
    )


# --------------------------------------------------------------------------
# The duplicated constant
# --------------------------------------------------------------------------
class RoutingKindTests(unittest.TestCase):
    def test_the_two_routing_kind_sets_agree(self) -> None:
        """`events` restates `builder`'s routing kinds; drift must fail here.

        `registry.py` cannot import `builder.document` - the compiler imports
        the registry, and the builder package pulls in the whole document
        schema - so the set is written twice. That is only safe while something
        compares the two copies, which is this.
        """

        self.assertEqual(ROUTING_NODE_KINDS, ROUTING_KINDS)

    def test_a_gate_and_a_router_are_the_only_routing_kinds(self) -> None:
        """Stated as a value, not only as an equality between two copies.

        A `transform` that acquired a second output port would compile to a
        plain listener, and its edges would silently become route targets that
        no router ever emits a label for.
        """

        self.assertEqual(ROUTING_NODE_KINDS, frozenset({"gate", "router"}))


# --------------------------------------------------------------------------
# The tables the constructor builds
# --------------------------------------------------------------------------
class FromDocumentTableTests(unittest.TestCase):
    def setUp(self) -> None:
        self.document = small_document()
        self.registry = compiled_registry(self.document)

    def test_every_compiled_ident_resolves_to_its_document_node(self) -> None:
        self.assertEqual(self.registry.declared_node("n0_idea"), "idea")
        self.assertEqual(self.registry.declared_node("n1_scoper"), "scoper")
        self.assertEqual(self.registry.declared_node("n8_report"), "report")

    def test_both_of_a_gates_two_methods_resolve_to_the_one_gate_node(self) -> None:
        """A gate compiles to a pause and a router, and both are that node.

        The canvas draws one box. If the router half resolved anywhere else the
        operator would watch a node they never placed take the decision they
        just made.
        """

        self.assertEqual(self.registry.declared_node("n2_confirm"), "confirm")
        self.assertEqual(self.registry.declared_node("n3_route_confirm"), "confirm")
        # And the gate consumed BOTH indices, so the node drawn after it is
        # `n4`, not `n3`. The idents asserted throughout this module are the
        # compiler's real ones for that reason.
        self.assertEqual(self.registry.declared_node("n4_market"), "market")

    def test_the_map_is_many_to_one_and_not_an_identity(self) -> None:
        """The property the whole constructor rests on, stated once.

        Every registry in the tree before this one was `{name: name}`, so
        nothing had ever exercised the two places that read the map's values
        rather than its keys.
        """

        self.assertNotEqual(
            dict(self.registry.flow_method_nodes),
            {node.id: node.id for node in self.document.nodes},
        )
        self.assertEqual(
            self.registry.declared_node_ids,
            {node.id for node in self.document.nodes},
        )
        self.assertGreater(
            len(self.registry.flow_method_nodes), len(self.registry.declared_node_ids)
        )

    def test_a_gates_router_half_is_the_router_method_not_its_pause(self) -> None:
        """Off by one here and every gate decision loses its edge frame.

        The serializer only draws an `EDGE_TAKEN` when `is_router(method_name)`,
        and the method that returns the label is the SECOND of the gate's two.
        """

        self.assertTrue(self.registry.is_router("n3_route_confirm"))
        self.assertFalse(self.registry.is_router("n2_confirm"))
        self.assertEqual(
            self.registry.router_methods, {"n3_route_confirm", "n7_again_or_not"}
        )

    def test_routes_are_keyed_by_the_compiled_label_the_router_returns(self) -> None:
        """`resolve_route` is handed the router's return value verbatim.

        The document says the port is `revise`; the compiled flow emits
        `e3_revise`. Keying on the port would resolve nothing at runtime and
        every gate edge would point at the quarantine node.
        """

        self.assertEqual(
            self.registry.resolve_route("n3_route_confirm", "e3_revise"), "redo"
        )
        self.assertEqual(
            self.registry.resolve_route("n7_again_or_not", "e7_give_up"), "report"
        )
        self.assertEqual(
            self.registry.resolve_route("n3_route_confirm", "revise"),
            QUARANTINE_NODE_ID,
        )

    def test_a_back_edge_resolves_to_the_node_it_returns_to(self) -> None:
        """The revise loop, which is the only cycle a builder graph may draw."""

        self.assertEqual(
            self.registry.resolve_route("n7_again_or_not", "e7_again"), "confirm"
        )

    def test_a_plain_successor_edge_is_not_a_route(self) -> None:
        """`idea -> scoper` is taken because a listener fired, not by a label.

        Admitting it would put `("n0_idea", "out")` in the table, and nothing
        would ever look it up - but a future reader would reasonably conclude
        that an `input` node emits a route.
        """

        keys = {method for method, _ in self.registry.route_targets}
        self.assertEqual(keys, {"n3_route_confirm", "n7_again_or_not"})

    def test_one_port_with_several_edges_keeps_the_last_one_drawn(self) -> None:
        """A fan-out has one frame and several successors; this says which one.

        Matching `from_flow_structure`, which collapses the validator's own
        three-way scope approval the same way. What runs is every listener on
        the label; only the drawn edge is singular.
        """

        self.assertEqual(
            self.registry.resolve_route("n3_route_confirm", "e3_approve"), "signal"
        )

    def test_task_and_role_tables_are_left_empty(self) -> None:
        """Both are consulted BEFORE the method name, so both would win wrongly.

        Two builder nodes may name the same allowlisted `agent_id` - a revise
        node re-running the scoper is the obvious case - and a role prefix would
        put every frame of both on whichever was registered first.
        """

        self.assertEqual(dict(self.registry.task_nodes), {})
        self.assertEqual(dict(self.registry.agent_role_prefixes), {})
        self.assertEqual(
            self.registry.resolve(agent_role="Scoper", method_name=None),
            QUARANTINE_NODE_ID,
        )


class FromDocumentInputTests(unittest.TestCase):
    def test_a_raw_json_document_gives_the_same_registry_as_a_parsed_one(self) -> None:
        """The store hands back JSON; the compiler holds a `BuilderDocument`.

        Both must produce the same tables, or a cached descriptor and a live
        compile would attribute the same run differently.
        """

        doc = small_document()
        methods, labels = compiled_identifiers(doc)
        by_id = doc.nodes_by_id()
        ports = {
            node_id: dict(zip(by_id[node_id].out_ports, emitted))
            for node_id, emitted in labels.items()
        }
        raw = doc.model_dump(by_alias=True, mode="json")

        self.assertEqual(
            NodeRegistry.from_document(raw, method_names=methods, event_labels=ports),
            compiled_registry(doc),
        )

    def test_without_method_names_a_node_id_is_its_own_method(self) -> None:
        """Legal only while every id is already a python identifier.

        Kept because it is what the spike measured first and what a hand-built
        graph in a test wants; the compiler passes the map.
        """

        registry = NodeRegistry.from_document(small_document())
        self.assertEqual(registry.declared_node("scoper"), "scoper")
        self.assertEqual(
            dict(registry.flow_method_nodes),
            {node.id: node.id for node in small_document().nodes},
        )

    def test_without_event_labels_the_port_is_the_label(self) -> None:
        registry = NodeRegistry.from_document(small_document())
        self.assertEqual(registry.resolve_route("confirm", "revise"), "redo")
        self.assertEqual(registry.resolve_route("again_or_not", "again"), "confirm")

    def test_a_node_id_longer_than_the_frame_bound_is_refused(self) -> None:
        """`_draft` clips `node_id` to 128 characters and says nothing.

        Two nodes agreeing on their first 128 would merge on the canvas and stay
        merged, which is the failure this refusal exists to make loud. The
        document schema caps ids at 40, so this can only arrive from a caller
        that skipped it - which is exactly when nothing else would notice.
        """

        long_id = "n" * (MAX_IDENTIFIER_LENGTH + 1)
        with self.assertRaises(ValueError) as caught:
            NodeRegistry.from_document({"nodes": [{"id": long_id, "kind": "agent"}]})
        self.assertIn(str(MAX_IDENTIFIER_LENGTH), str(caught.exception))

    def test_a_node_without_an_id_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            NodeRegistry.from_document({"nodes": [{"kind": "agent"}]})

    def test_a_node_given_no_compiled_method_name_is_refused(self) -> None:
        """An empty tuple would drop the node from the map without a word."""

        with self.assertRaises(ValueError) as caught:
            NodeRegistry.from_document(
                {"nodes": [{"id": "scoper", "kind": "agent"}]},
                method_names={"scoper": ()},
            )
        self.assertIn("scoper", str(caught.exception))

    def test_an_edge_from_a_node_the_document_does_not_declare_is_ignored(self) -> None:
        """Dangling edges are a Problem `bounds.py` reports, not a crash here.

        `from_document` runs after that check in the compiler, but it is also
        reachable from a store row written by an older version, and raising
        would make an unrenderable graph out of a reportable one.
        """

        registry = NodeRegistry.from_document(
            {
                "nodes": [{"id": "report", "kind": "output"}],
                "edges": [
                    {"source": "ghost", "source_port": "out", "target": "report"}
                ],
            }
        )
        self.assertEqual(dict(registry.route_targets), {})


class VerdictNodeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.validator = NodeRegistry.from_flow_structure(
            build_flow_structure(ValidatorFlow)
        )

    def test_the_validator_verdict_node_is_unchanged(self) -> None:
        """The literal still decides, because the validator declares no policy."""

        self.assertIsNone(self.validator.verdict_node_id)
        self.assertEqual(verdict_frame_node(self.validator), VERDICT_NODE_ID)
        self.assertEqual(verdict_frame_node(self.validator), "synthesize")

    def test_a_graph_declaring_no_such_node_still_quarantines(self) -> None:
        """Brief Flow's answer, which is honest rather than invented."""

        brief = NodeRegistry(flow_method_nodes={"check_cache": "check_cache"})
        self.assertEqual(verdict_frame_node(brief), QUARANTINE_NODE_ID)

    def test_a_builder_graph_without_a_policy_quarantines_its_verdict(self) -> None:
        """What the fallback answers for a graph that names no `synthesize`.

        Stated as behaviour, not as a live defect: no builder node KIND emits a
        verdict, `publish_verdict` is called only from `validator_flow`, and
        `builder_node_registry` passes no `verdict_node_id` - so this is the
        seam's shape being pinned before there is anything to feed it, which is
        the only honest thing to claim about an unused seam.
        """

        self.assertEqual(
            verdict_frame_node(compiled_registry(small_document())), QUARANTINE_NODE_ID
        )

    def test_a_declared_verdict_node_wins(self) -> None:
        registry = compiled_registry(small_document(), verdict_node_id="scoper")
        self.assertEqual(verdict_frame_node(registry), "scoper")

    def test_the_declared_node_wins_over_a_node_called_synthesize(self) -> None:
        """Policy beats the literal, or the fallback would be unoverridable.

        `validator_shaped_document` really does have a `synthesize` node, so
        without this ordering an author who pointed the verdict elsewhere would
        be quietly overruled.
        """

        doc = validator_shaped_document()
        self.assertIn("synthesize", {node.id for node in doc.nodes})
        registry = compiled_registry(doc, verdict_node_id="review_verdict")
        self.assertEqual(verdict_frame_node(registry), "review_verdict")

    def test_a_verdict_node_the_document_does_not_draw_is_refused(self) -> None:
        with self.assertRaises(ValueError) as caught:
            compiled_registry(small_document(), verdict_node_id="nowhere")
        self.assertIn("nowhere", str(caught.exception))

    def test_the_serializer_files_the_verdict_frame_on_the_declared_node(self) -> None:
        """End to end through the real adapter, not through `verdict_frame_node`.

        The serializer is the only caller that matters, and it read a module
        literal directly until this change.
        """

        buffer = FrameBuffer(capacity=8)
        adapter = StreamSinkAdapter(
            run_id="builder-run",
            buffer=buffer,
            registry=compiled_registry(small_document(), verdict_node_id="scoper"),
        )
        adapter(None, VerdictComputedEvent(verdict=RESCORED, timestamp=TS))
        frames = buffer.replay()
        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0].node_id, "scoper")
        self.assertEqual(buffer.stats().emit_errors, 0)


class NonIdentityAttributionTests(unittest.TestCase):
    """The claim: a compiled flow's frames land on the AUTHOR's node ids.

    Driven through the real `StreamSinkAdapter` and the real serializer with
    real CrewAI events, because the whole defect class this fixes is one where
    the tables looked right and the frames went somewhere else.
    """

    def setUp(self) -> None:
        self.registry = compiled_registry(small_document())
        self.buffer = FrameBuffer(capacity=64)
        self.adapter = StreamSinkAdapter(
            run_id="builder-run", buffer=self.buffer, registry=self.registry
        )
        self.addCleanup(current_node_scope.set, current_node_scope.get())

    def test_a_method_frame_lands_on_the_document_node(self) -> None:
        start_method(self.adapter, "n1_scoper")
        self.assertEqual(self.buffer.replay()[0].node_id, "scoper")

    def test_a_tool_call_lands_on_the_node_whose_method_is_running(self) -> None:
        """The frame names no method at all, so only the node scope can place it.

        This is the case that quarantined 148 frames of the first paid run, and
        the case a non-identity map could plausibly have broken: the scope holds
        a NODE id while `flow_method_nodes` is keyed by METHOD idents.
        """

        start_method(self.adapter, "n1_scoper")
        use_tool(self.adapter)
        frames = self.buffer.replay()
        self.assertEqual([frame.node_id for frame in frames], ["scoper", "scoper"])

    def test_a_tool_call_under_a_gates_router_lands_on_the_gate(self) -> None:
        """The second of a gate's two methods is still that one canvas node."""

        start_method(self.adapter, "n3_route_confirm")
        use_tool(self.adapter)
        self.assertEqual({frame.node_id for frame in self.buffer.replay()}, {"confirm"})

    def test_a_method_this_graph_does_not_declare_quarantines(self) -> None:
        """CrewAI's nested `AgentExecutor` is a Flow, and its methods are not ours."""

        start_method(self.adapter, "execute_tool_action")
        self.assertEqual(self.buffer.replay()[0].node_id, QUARANTINE_NODE_ID)

    def test_the_compiled_ident_is_not_accepted_as_a_node_scope(self) -> None:
        """`resolve`'s last fallback checks VALUES, and an ident is a KEY.

        The one place the identity assumption could have hidden. With a scope of
        `n1_scoper` - which is a real method name - the answer must still be the
        quarantine node, because the scope is meant to hold what
        `declared_node` returned.
        """

        current_node_scope.set("n1_scoper")
        self.assertEqual(self.registry.resolve(), QUARANTINE_NODE_ID)
        current_node_scope.set("scoper")
        self.assertEqual(self.registry.resolve(), "scoper")

    def test_a_whole_small_run_quarantines_nothing(self) -> None:
        """Every compiled method, with a tool call under each, nothing left over."""

        doc = small_document()
        methods, _ = compiled_identifiers(doc)
        for node in doc.nodes:
            for ident in methods[node.id]:
                start_method(self.adapter, ident)
                use_tool(self.adapter)
        frames = self.buffer.replay()
        self.assertEqual([f for f in frames if f.node_id == QUARANTINE_NODE_ID], [])
        self.assertEqual(
            {frame.node_id for frame in frames}, {node.id for node in doc.nodes}
        )
        self.assertEqual(self.buffer.stats().emit_errors, 0)


class DeclaredNodeIdsTests(unittest.TestCase):
    """The precomputed set that replaced an O(n) scan on every non-method event."""

    def test_it_equals_the_values_of_the_method_map(self) -> None:
        for registry in (
            compiled_registry(validator_shaped_document()),
            NodeRegistry.from_flow_structure(build_flow_structure(ValidatorFlow)),
            NodeRegistry(),
        ):
            with self.subTest(size=len(registry.flow_method_nodes)):
                self.assertEqual(
                    registry.declared_node_ids,
                    set(registry.flow_method_nodes.values()),
                )

    def test_it_is_a_set_rather_than_a_view(self) -> None:
        """A `values()` view would still be O(n) and would defeat the change."""

        registry = compiled_registry(small_document())
        self.assertIsInstance(registry.declared_node_ids, frozenset)

    def test_it_does_not_enter_equality(self) -> None:
        """Derived, so two registries with the same map are the same registry."""

        self.assertEqual(
            NodeRegistry(flow_method_nodes={"a": "b"}),
            NodeRegistry(flow_method_nodes={"a": "b"}),
        )


class ValidatorRegressionTests(unittest.TestCase):
    """The validator's attribution must not move by one frame.

    `tests/events/` already covers the behaviour; what is pinned here is that
    the tables built by `from_flow_structure` are what they were before
    `from_document`, `verdict_node_id` and `declared_node_ids` existed.
    """

    def setUp(self) -> None:
        self.structure = build_flow_structure(ValidatorFlow)
        self.registry = NodeRegistry.from_flow_structure(self.structure)

    def test_the_method_map_is_still_the_identity_the_flow_declares(self) -> None:
        self.assertEqual(
            dict(self.registry.flow_method_nodes),
            {name: name for name in self.structure["nodes"]},
        )

    def test_the_validator_nodes_still_resolve_to_themselves(self) -> None:
        for node_id in (
            "scope_idea",
            "confirm_scope",
            "route_scope",
            "revise_scope",
            "research_market",
            "research_sentiment",
            "research_feasibility",
            "synthesize",
            "review_verdict",
            "route_verdict",
            "revise_verdict",
            "write_report",
            "persist",
        ):
            with self.subTest(node_id=node_id):
                self.assertEqual(self.registry.declared_node(node_id), node_id)
                self.assertEqual(self.registry.resolve(method_name=node_id), node_id)

    def test_the_router_set_and_every_route_are_unchanged(self) -> None:
        expected = {
            (str(item["source"]), str(item["router_event"])): str(item["target"])
            for item in self.structure["edges"]
            if item.get("is_router_event") and item.get("router_event") is not None
        }
        self.assertEqual(dict(self.registry.route_targets), expected)
        self.assertEqual(
            self.registry.router_methods, frozenset(self.structure["router_methods"])
        )

    def test_the_enclosing_scope_fallback_still_attributes_a_tool_call(self) -> None:
        """The path `declared_node_ids` replaced the `values()` scan on."""

        self.addCleanup(current_node_scope.set, current_node_scope.get())
        buffer = FrameBuffer(capacity=16)
        adapter = StreamSinkAdapter(
            run_id="validator-run", buffer=buffer, registry=self.registry
        )
        start_method(adapter, "research_market")
        use_tool(adapter)
        self.assertEqual(
            [frame.node_id for frame in buffer.replay()],
            ["research_market", "research_market"],
        )

    def test_crewais_own_method_name_still_resolves_a_bare_event(self) -> None:
        """The fallback ahead of the node scope, which nothing here touched."""

        self.addCleanup(current_node_scope.set, current_node_scope.get())
        current_node_scope.set(None)
        token = current_flow_method_name.set("synthesize")
        self.addCleanup(current_flow_method_name.reset, token)
        self.assertEqual(self.registry.resolve(), "synthesize")


if __name__ == "__main__":  # pragma: no cover - parity with the suite's modules
    unittest.main()
