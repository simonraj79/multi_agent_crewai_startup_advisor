"""The gallery's templates, as documents the compiler actually accepts.

A template is the first thing a new author sees, and a template that does not
validate is worse than no template at all: it opens with a red problems dock
about a graph they have not touched. So "every template validates" has to be a
measurement rather than a claim, and this file is the Python half of that -
`frontend/tests/templates.spec.ts` is the other, and `test_client_fixtures.py`
is what stops the two describing different documents.

WHAT THIS FILE ASSERTS THAT THE FIXTURE COMPARISON DOES NOT. The byte-compare in
`test_client_fixtures.py` proves the committed fixtures are what the generator
produces today; it would be just as green over four templates that all failed
validation, because the fixture would faithfully record the failure. What is
asserted here is the CONTENT of that answer - zero problems, a price under the
ceiling, and the four structural facts each pattern exists to demonstrate.

No cost: this reads two packages and nine JSON files. No network, no model, no
credential.
"""

from __future__ import annotations

import json
import pathlib
import sys
import unittest

REPO = pathlib.Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:  # pragma: no cover - import bootstrap
    sys.path.insert(0, str(REPO))

from brief_crew.builder import (  # noqa: E402
    BuilderDocument,
    back_edge_indices,
    estimate_budget,
    validate_document,
)
from brief_crew.builder.compiler import compile_document  # noqa: E402
from brief_crew.builder.document import AuthoredAgentConfig, AuthoredCrewConfig  # noqa: E402
from brief_crew.config import (  # noqa: E402
    GRAPH_STATIC_BUDGET_MARGIN,
    MAX_CYCLE_ITERATIONS,
    MAX_RUN_COST_USD,
    MODEL_BY_ID,
    MODEL_PRESETS,
)
from scripts.emit_builder_fixtures import (  # noqa: E402
    FIXTURE_DOCUMENT_ID,
    template_documents,
)

#: The gallery's first row, in the order it is drawn. Restated here rather than
#: read from the dump, because the ORDER is a judgement plan 14 D7 makes -
#: by how much a reader has to understand before the card helps them - and a
#: test that read it from the file it is checking would ratify any order at all.
GALLERY_ORDER = (
    "blank",
    "sequential-pipeline",
    "conditional-router",
    "reflection-loop",
    "hierarchical-delegation",
    "idea-validator",
)

#: The second row: library-agent templates kept because `e2e/builder.spec.ts`
#: drives them (owner's decision 21).
MORE_ROW = ("minimal-gated-agent", "fan-out-join")

#: Every template that has something to launch. `blank` is the two ends of a run
#: and nothing between them.
LAUNCHABLE = tuple(t for t in GALLERY_ORDER + MORE_ROW if t != "blank")

#: The one launchable template that is NOT gated above its first billable node,
#: and it is a shape rather than an oversight: the evaluator scopes first,
#: exactly as `validator_flow.py` does, and its scope GATE reads what the Scoper
#: produced. Publishing it answers `gated_before_spend: false`, and an anonymous
#: launch is refused with 403 - measured against a synthetic backend on
#: 2026-09-04. `PublishDialog` renders that refusal in full, which is the right
#: place for it; what is wrong is a template SILENTLY not launching, and this one
#: does not do that.
UNGATED_BY_DESIGN = ("idea-validator",)


def documents() -> dict[str, BuilderDocument]:
    """Every template parsed, keyed by id."""

    dumped = template_documents()["documents"]
    parsed: dict[str, BuilderDocument] = {}
    for template_id, wire in dumped.items():
        document = dict(wire)
        document["id"] = FIXTURE_DOCUMENT_ID
        document["version"] = 1
        parsed[template_id] = BuilderDocument.model_validate(document)
    return parsed


DOCUMENTS = documents()


class GalleryTests(unittest.TestCase):
    """The set of templates, and the order they are offered in."""

    def test_the_gallery_ships_the_six_and_keeps_the_two(self) -> None:
        dumped = template_documents()
        self.assertEqual(tuple(dumped["order"]), GALLERY_ORDER)
        self.assertEqual(tuple(dumped["more"]), MORE_ROW)
        self.assertEqual(
            sorted(dumped["documents"]),
            sorted(GALLERY_ORDER + MORE_ROW),
            "the dumped documents and the two rendered rows disagree",
        )

    def test_the_flagship_is_last_and_the_blank_is_first(self) -> None:
        """The one ordering property that is a decision rather than a list.

        A gallery that opens on the biggest graph teaches an author that the
        builder is for transcribing something rather than for drawing, which is
        the failure mode the ordering rule exists to avoid.
        """

        self.assertEqual(GALLERY_ORDER[0], "blank")
        self.assertEqual(GALLERY_ORDER[-1], "idea-validator")

    def test_every_card_carries_what_it_teaches_and_what_to_change(self) -> None:
        cards = template_documents()["cards"]
        for template_id in GALLERY_ORDER + MORE_ROW:
            with self.subTest(template=template_id):
                card = cards[template_id]
                for field in ("title", "blurb", "teaches", "modifyFirst"):
                    self.assertGreater(
                        len(card[field] or ""),
                        10,
                        f"{template_id}.{field} is the card's whole explanation",
                    )
                # R14: only the validator earns a caveat, and it must be there.
                if template_id == "idea-validator":
                    self.assertIn("judgement", card["caveat"])
                else:
                    self.assertIsNone(card["caveat"])


class ValidationTests(unittest.TestCase):
    """Criterion 2: every template, zero problems, priced under the ceiling."""

    def test_every_template_validates_with_no_problems_at_all(self) -> None:
        for template_id, document in DOCUMENTS.items():
            with self.subTest(template=template_id):
                problems = validate_document(document, ceiling_usd=MAX_RUN_COST_USD)
                self.assertEqual(
                    [f"{p.code}@{p.node_id}" for p in problems],
                    [],
                    "a template is the first thing a new author sees; one that "
                    "opens with a problem is worse than no template",
                )

    def test_every_template_is_priced_and_fits_under_the_ceiling(self) -> None:
        for template_id, document in DOCUMENTS.items():
            with self.subTest(template=template_id):
                estimate = estimate_budget(document)
                self.assertEqual(
                    list(estimate.unpriced_models),
                    [],
                    "an unpriced model contributes NOTHING to the total, so it "
                    "reads as free rather than as unknown",
                )
                self.assertLess(
                    estimate.static_cost_usd * GRAPH_STATIC_BUDGET_MARGIN,
                    MAX_RUN_COST_USD,
                    "the margin multiplies the STATIC price, not the floor",
                )

    def test_every_launchable_template_gates_before_it_spends(self) -> None:
        """The 403 an anonymous launch gets otherwise names this exact condition.

        `create_run` refuses a published graph that reaches a billable node
        before any human gate unless `BUILDER_ALLOW_GATELESS_GRAPHS` is set,
        because while nobody is signed in human inaction IS the spend cap. A
        template that cannot be launched from a cold sign-in is not a template.
        """

        for template_id in LAUNCHABLE:
            if template_id in UNGATED_BY_DESIGN:
                continue
            with self.subTest(template=template_id):
                document = DOCUMENTS[template_id]
                kinds = {node.id: node.kind for node in document.nodes}
                targets = {
                    edge.source: edge.target
                    for edge in document.edges
                    if edge.target_port == "in"
                }
                start = next(
                    node.id for node in document.nodes if node.kind == "input"
                )
                self.assertEqual(
                    kinds[targets[start]],
                    "gate",
                    f"{template_id} reaches {targets[start]!r} straight from its input",
                )

    def test_the_evaluator_is_the_only_one_that_bills_before_its_gate(self) -> None:
        """Named rather than merely skipped above.

        A test that quietly excluded a case would let a SECOND template become
        ungated without anybody noticing; this fails if one does, and it fails if
        the evaluator is ever gated first and the exclusion is left behind.
        """

        ungated: list[str] = []
        for template_id in LAUNCHABLE:
            document = DOCUMENTS[template_id]
            kinds = {node.id: node.kind for node in document.nodes}
            targets = {
                edge.source: edge.target for edge in document.edges if edge.target_port == "in"
            }
            start = next(node.id for node in document.nodes if node.kind == "input")
            if kinds[targets[start]] != "gate":
                ungated.append(template_id)
        self.assertEqual(tuple(ungated), UNGATED_BY_DESIGN)

    def test_blank_has_nothing_to_gate_because_it_bills_nothing(self) -> None:
        blank = DOCUMENTS["blank"]
        self.assertEqual([node.kind for node in blank.nodes], ["input", "output"])
        self.assertEqual(estimate_budget(blank).billable_nodes, 0)


class ModelRoleTests(unittest.TestCase):
    """Criterion 4: a template names a ROLE, and the two halves resolve alike."""

    #: `frontend/src/data/templates/modelRoles.ts`, in Python. The client half
    #: derives its answer from the served roster and this half from the registry
    #: the roster is generated out of; asserting the two agree is the R7
    #: condition a client mirror is admitted on.
    def _cheapest(self) -> str:
        usable = [
            model
            for model in MODEL_BY_ID.values()
            if model.supports_tools and model.supports_json_mode
        ]
        return min(
            usable, key=lambda m: (m.cost_in_max_endpoint, m.cost_in, m.id)
        ).id

    def test_the_client_resolved_the_same_three_models_this_build_would(self) -> None:
        dumped = template_documents()["roles"]

        def slug(model: str) -> str:
            return model.removeprefix("openrouter/").split(":", 1)[0]

        self.assertEqual(slug(dumped["workhorse"]), slug(MODEL_PRESETS["cheap"]))
        self.assertEqual(slug(dumped["escalation"]), slug(MODEL_PRESETS["escalation"]))
        self.assertEqual(dumped["cheapest"], self._cheapest())

    def test_no_template_source_file_carries_a_model_slug(self) -> None:
        """The whole point of the role tokens, asserted against the files.

        A slug written into a template is wrong the first time
        `scripts/refresh_models.py` runs, and wrong silently: the id parses, the
        canvas draws, and the server answers `model-unknown` on a graph nobody
        touched.
        """

        providers = ("openrouter/", "google/", "openai/", "deepseek/", "qwen/", "z-ai/", "moonshotai/")
        directory = REPO / "frontend" / "src" / "data" / "templates"
        offenders: list[str] = []
        for path in sorted(directory.glob("*.ts")):
            # `modelRoles.ts` is the module that RESOLVES the tokens; its
            # docstring names the two presets by role, not by slug, and its code
            # reads them off the roster. It is scanned like everything else.
            text = path.read_text(encoding="utf-8")
            for line_no, line in enumerate(text.splitlines(), start=1):
                if any(provider in line for provider in providers):
                    offenders.append(f"{path.name}:{line_no}: {line.strip()}")
        self.assertEqual(offenders, [])

    def test_every_authored_model_resolved_to_a_registry_row(self) -> None:
        dumped = template_documents()["documents"]
        seen = 0
        for template_id, wire in dumped.items():
            for node in wire["nodes"]:
                for field in ("llm", "manager_llm", "planning_llm"):
                    llm = (node.get("config") or {}).get(field)
                    if not isinstance(llm, dict):
                        continue
                    model = str(llm["model"])
                    with self.subTest(template=template_id, node=node["id"]):
                        self.assertNotIn("{{", model, "an unresolved role token shipped")
                        self.assertIn(model.split(":", 1)[0], MODEL_BY_ID)
                    seen += 1
        self.assertGreaterEqual(seen, 10, "too few authored models to be a gate")


class PatternTests(unittest.TestCase):
    """Criterion 5: the four structural facts each pattern exists to teach."""

    def test_the_reflection_loop_is_one_cycle_closed_by_a_router(self) -> None:
        document = DOCUMENTS["reflection-loop"]
        estimate = estimate_budget(document)
        self.assertEqual(estimate.cycles, 1)

        back = back_edge_indices(document)
        self.assertEqual(len(back), 1, "exactly one back edge, or it is not this pattern")
        closer = document.edges[back[0]]
        kinds = {node.id: node.kind for node in document.nodes}
        self.assertEqual(
            kinds[closer.source],
            "router",
            "a plain listener closing a loop ends the run silently - no exception, "
            "no warning, no frame",
        )
        self.assertEqual(closer.target, "generate")

    def test_the_reflection_loop_compiles_with_a_backstop_of_four(self) -> None:
        """`(1 + MAX_CYCLE_ITERATIONS) ** cycles`, so at most four drafts.

        Four is ALSO the floor - `max_method_calls` clamps `cycles` to at least
        one, so an acyclic graph gets the same number - which is why the back
        edge is counted above rather than inferred from this. Both are asserted
        because only together do they say "one cycle, bounded at four".
        """

        definition = compile_document(DOCUMENTS["reflection-loop"]).definition
        self.assertEqual(definition["config"]["max_method_calls"], 4)
        self.assertEqual((1 + MAX_CYCLE_ITERATIONS) ** 1, 4)

    def test_the_drafter_listens_for_the_gate_and_for_the_back_edge(self) -> None:
        """The compiled shape of a loop, rather than the document's picture of one."""

        compiled = compile_document(DOCUMENTS["reflection-loop"])
        ident = compiled.method_idents["generate"][0]
        method = compiled.definition["methods"][ident]
        listen = method["listen"]
        self.assertIn("or", listen, f"generate listens for {listen!r}, not for two events")
        self.assertEqual(len(listen["or"]), 2)

    def test_the_conditional_router_joins_on_any(self) -> None:
        """Exactly one branch fires, so the merge must run on the first arrival.

        Declared `'all'` the join would wait forever for two branches that were
        never going to happen - and there would be no error, because waiting is
        not failing.
        """

        document = DOCUMENTS["conditional-router"]
        self.assertEqual(document.joins, {"merge": "any"})
        arrivals = [edge for edge in document.edges if edge.target == "merge"]
        self.assertEqual(len(arrivals), 3)

    def test_the_conditional_router_puts_the_cheap_model_on_the_decision(self) -> None:
        document = DOCUMENTS["conditional-router"]
        by_id = {node.id: node for node in document.nodes}
        classify = by_id["classify"].config
        assert isinstance(classify, AuthoredAgentConfig)
        specialist = by_id["billing"].config
        assert isinstance(specialist, AuthoredAgentConfig)
        self.assertLess(
            MODEL_BY_ID[classify.llm.model.split(":", 1)[0]].cost_in,
            MODEL_BY_ID[specialist.llm.model.split(":", 1)[0]].cost_in,
            "the whole lesson is that the cheap model belongs where the decision "
            "is small",
        )
        self.assertEqual(classify.task.output_schema, {"category": "string"})

    def test_the_hierarchical_crew_has_three_members_and_no_flow_edge_into_one(
        self,
    ) -> None:
        document = DOCUMENTS["hierarchical-delegation"]
        members = [edge for edge in document.edges if edge.target_port == "member"]
        self.assertEqual([edge.source for edge in members], ["market", "product", "risk"])
        self.assertTrue(all(edge.target == "team" for edge in members))

        member_ids = {edge.source for edge in members}
        flow_into_member = [
            edge.id
            for edge in document.edges
            if edge.target_port == "in" and (edge.source in member_ids or edge.target in member_ids)
        ]
        self.assertEqual(
            flow_into_member,
            [],
            "a member agent that is also a step runs twice, and nothing "
            "downstream could say which output it was reading",
        )

        crew = next(node for node in document.nodes if node.id == "team").config
        assert isinstance(crew, AuthoredCrewConfig)
        self.assertEqual(crew.process, "hierarchical")
        self.assertIsNotNone(crew.manager_llm)
        self.assertEqual(list(crew.task_order), ["market", "product", "risk"])

    def test_the_sequential_pipeline_attaches_one_keyless_tool(self) -> None:
        """Zero configuration means no credential anywhere (D8).

        `web_search` would have been the natural choice and every one of its four
        providers needs the author's own key, so a template carrying it opens
        with `tool-credential-required` and cannot be launched at all from a cold
        sign-in.
        """

        document = DOCUMENTS["sequential-pipeline"]
        attachments = [edge for edge in document.edges if edge.target_port == "attach"]
        self.assertEqual(len(attachments), 1)
        self.assertEqual(attachments[0].target, "research")

        tool = next(node for node in document.nodes if node.kind == "tool")
        self.assertEqual(tool.config.tool_id, "analyze_community_sentiment")

    def test_no_template_names_a_credential(self) -> None:
        for template_id, wire in template_documents()["documents"].items():
            with self.subTest(template=template_id):
                blob = json.dumps(wire)
                self.assertNotIn("credential_id", blob)


class CompileTests(unittest.TestCase):
    """Every launchable template compiles to a `crewai.flow/v1` definition."""

    def test_every_launchable_template_compiles(self) -> None:
        for template_id in LAUNCHABLE:
            with self.subTest(template=template_id):
                definition = compile_document(DOCUMENTS[template_id]).definition
                self.assertEqual(definition["schema"], "crewai.flow/v1")
                self.assertTrue(definition["methods"])

    def test_every_gate_compiles_to_two_methods_with_no_emit_and_a_null_llm(self) -> None:
        """The highest-value check in the compiler, asserted over what ships.

        With `emit` set and `llm: null` CrewAI collapses the reply to `emit[0]`
        UNCONDITIONALLY, so an operator who replies `revise` runs the approve
        branch - and CrewAI logs the combination at `severity="error"` and runs
        the flow anyway.
        """

        for template_id in LAUNCHABLE:
            document = DOCUMENTS[template_id]
            gates = [node for node in document.nodes if node.kind == "gate"]
            compiled = compile_document(document)
            for gate in gates:
                with self.subTest(template=template_id, gate=gate.id):
                    idents = compiled.method_idents[gate.id]
                    self.assertEqual(len(idents), 2, "a gate is a pause AND a router")
                    feedback = compiled.definition["methods"][idents[0]]["human_feedback"]
                    self.assertIsNone(feedback["emit"])
                    self.assertIsNone(feedback["llm"])


if __name__ == "__main__":
    unittest.main()
