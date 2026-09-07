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

#: The thirteen cards, in the order the gallery draws them - 16 D2. Restated
#: here rather than read from the dump, because the ORDER is a judgement two
#: plans make (14 D7 inside a category, 16 D1 across them) and a test that read
#: it from the file it is checking would ratify any order at all.
GALLERY_ORDER = (
    # start
    "blank",
    "single-agent",
    "minimal-gated-agent",
    # chain
    "sequential-pipeline",
    "news-to-social",
    # route
    "conditional-router",
    "tiered-routing",
    # parallel
    "fan-out-join",
    "vote-review",
    # review
    "reflection-loop",
    "fallback-bar",
    # team
    "hierarchical-delegation",
    "idea-validator",
)

#: The six sections, in `frontend/src/data/templateCategories.ts`'s order, which
#: is the order the gallery renders them in. Restated for the same reason
#: `GALLERY_ORDER` is: the progression is the decision, and reading it off the
#: thing under test would ratify anything.
CATEGORY_ORDER = ("start", "chain", "route", "parallel", "review", "team")

#: The four templates added with the categories. Named so the assertions that
#: are ABOUT them read as being about them, rather than as a slice.
NEW_TEMPLATES = ("single-agent", "tiered-routing", "vote-review", "fallback-bar")

#: Every template that has something to launch. `blank` is the two ends of a run
#: and nothing between them.
LAUNCHABLE = tuple(t for t in GALLERY_ORDER if t != "blank")

#: The one `input_field` more than one template declares, and every template
#: that declares it.
#:
#: 16 D9 asks for "no two templates share an `input_field`", and the tree it was
#: written against already had four templates sharing `idea`: the empty canvas,
#: the two library-agent cards and the flagship. That is deliberate and
#: documented at `frontend/src/data/templates/testInputs.ts:20-26` - the field
#: means the same thing in each and one sample serves all of them - so the rule
#: is asserted here in the only form that is both true and useful: every field
#: is declared by exactly one template EXCEPT this one, and this one is declared
#: by exactly these four. A fifth sharer fails, and a new template quietly
#: reusing somebody's field fails, which is what the rule is for
#: (`testInputs.ts` resolves a sample BY FIELD and `Object.fromEntries` keeps
#: the last write, so a collision silently hands one template another's sample).
SHARED_INPUT_FIELD = "idea"
SHARES_THE_IDEA_FIELD = (
    "blank",
    "minimal-gated-agent",
    "idea-validator",
    "fan-out-join",
)

#: The two launchable templates that are NOT gated above their first billable
#: node. Both are shapes rather than oversights, and they arrive at the same
#: place from opposite directions.
#:
#: `idea-validator` scopes first, exactly as `validator_flow.py` does, and its
#: scope GATE reads what the Scoper produced - so the billing has to come first
#: for the gate to have anything to ask about.
#:
#: `news-to-social` has no gate at all, on purpose: it is the template written
#: to run UNATTENDED, and a gate is the one thing that makes that impossible.
#: What it pays for that is precise and stated on its own card - only a
#: signed-in caller may launch it, because `create_run` answers 403 otherwise
#: unless `BUILDER_ALLOW_GATELESS_GRAPHS` is set.
#:
#: Publishing either answers `gated_before_spend: false`, and `PublishDialog`
#: renders the refusal in full - which is the right place for it. What is wrong
#: is a template SILENTLY not launching, and neither of these does that.
UNGATED_BY_DESIGN = ("news-to-social", "idea-validator")

#: The word on each caveat that makes it THAT caveat. R14 renders a caveat
#: verbatim, so a card whose text was replaced with a different truth has to
#: fail here rather than pass on a non-empty string. Six cards carry one and
#: seven carry none; both halves are asserted.
CAVEAT_MARKERS = {
    "news-to-social": "403",
    "conditional-router": "Four desks",
    "fan-out-join": "Four branches",
    "fallback-bar": "transport failure",
    "hierarchical-delegation": "roster is fixed",
    "idea-validator": "judgement",
}

#: 16 D4's caps, in characters.
LENGTH_CAPS = {"blurb": 140, "useCase": 240, "useWhen": 170, "notWhen": 170}


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
    """The set of templates, the sections they sit in, and their order."""

    def test_the_gallery_ships_the_thirteen_and_the_second_row_is_gone(self) -> None:
        dumped = template_documents()
        self.assertEqual(tuple(dumped["order"]), GALLERY_ORDER)
        self.assertEqual(
            sorted(dumped["documents"]),
            sorted(GALLERY_ORDER),
            "the dumped documents and the rendered order disagree",
        )
        # `more` is EMPTY and still emitted. The demoted second row is retired
        # (16 D2) and `ALL_BUILDER_TEMPLATES` aliases `BUILDER_TEMPLATES`, so
        # there is nothing left for the key to hold - but `test_client_fixtures`
        # asserts `sorted(documents) == sorted(order + more)`, which is a real
        # property, and a missing key would replace it with a KeyError. The
        # dump's own comment says to delete the key in the same commit as that
        # assertion and not before.
        self.assertEqual(list(dumped["more"]), [])

    def test_the_flagship_is_last_and_the_blank_is_first(self) -> None:
        """The one ordering property that is a decision rather than a list.

        A gallery that opens on the biggest document teaches an author that the
        builder is for transcribing something rather than for drawing, which is
        the failure mode the ordering rule exists to avoid. Plan 14 D7 and 16 D2
        fix these two positions by name; everything between them is now decided
        by the category a card declares.
        """

        self.assertEqual(GALLERY_ORDER[0], "blank")
        self.assertEqual(GALLERY_ORDER[-1], "idea-validator")

    def test_every_template_declares_a_category_from_the_closed_six(self) -> None:
        cards = template_documents()["cards"]
        for template_id in GALLERY_ORDER:
            with self.subTest(template=template_id):
                self.assertIn(
                    cards[template_id]["category"],
                    CATEGORY_ORDER,
                    "a card in no section is a card the gallery cannot draw",
                )

    def test_every_section_has_at_least_one_card(self) -> None:
        """A section heading over an empty shelf is a promise nothing keeps."""

        cards = template_documents()["cards"]
        declared = {cards[template_id]["category"] for template_id in GALLERY_ORDER}
        self.assertEqual(sorted(declared), sorted(CATEGORY_ORDER))

    def test_gallery_order_is_category_order_with_the_sections_unbroken(self) -> None:
        """The gallery renders sections, so the list has to be sorted into them.

        Asserted as "the categories in order, with consecutive repeats
        collapsed" rather than as a sort, because that fails BOTH ways a
        sectioned gallery can be wrong: a section out of place, and a card of
        one section stranded among another's.
        """

        cards = template_documents()["cards"]
        seen: list[str] = []
        for template_id in GALLERY_ORDER:
            category = cards[template_id]["category"]
            if not seen or seen[-1] != category:
                seen.append(category)
        self.assertEqual(tuple(seen), CATEGORY_ORDER)

    def test_no_two_templates_share_an_input_field_but_the_declared_four(self) -> None:
        """A shared field silently shares a saved sample. See `SHARED_INPUT_FIELD`."""

        by_field: dict[str, list[str]] = {}
        for template_id in GALLERY_ORDER:
            field = str(DOCUMENTS[template_id].input_field)
            by_field.setdefault(field, []).append(template_id)

        self.assertEqual(
            sorted(by_field[SHARED_INPUT_FIELD]),
            sorted(SHARES_THE_IDEA_FIELD),
            "the one field more than one template declares has changed hands",
        )
        for field, owners in sorted(by_field.items()):
            if field == SHARED_INPUT_FIELD:
                continue
            with self.subTest(field=field):
                self.assertEqual(
                    owners,
                    owners[:1],
                    f"{owners} all declare '{field}', so they share one saved "
                    "sample: `testInputs.ts` resolves by field and the last "
                    "write wins",
                )

    def test_each_new_template_brought_its_own_input_field(self) -> None:
        """16 criterion 4, stated about the four rather than inferred."""

        fields = {t: str(DOCUMENTS[t].input_field) for t in NEW_TEMPLATES}
        self.assertEqual(
            fields,
            {
                "single-agent": "question",
                "tiered-routing": "ticket",
                "vote-review": "draft",
                "fallback-bar": "enquiry",
            },
        )

    def test_every_pattern_card_names_its_pattern_in_its_own_copy(self) -> None:
        """The ask itself, made a test - `AUDIT-REPO.md` section 1.4.

        Not one card named its pattern before this plan: every `teaches` string
        was written in the vocabulary of this builder's syntax. A card whose
        copy quietly regressed to syntax would look fine and would lose the one
        thing that lets a reader match a job to a shape, so the name has to
        appear in a field the card renders. The `none` cards are exempt because
        they are instances of nothing: `blank` is the empty state and
        `minimal-gated-agent` demonstrates a rule of this service.
        """

        cards = template_documents()["cards"]
        for template_id in GALLERY_ORDER:
            card = cards[template_id]
            pattern = card["pattern"]
            with self.subTest(template=template_id):
                self.assertIn(pattern["source"], ("anthropic", "google", "both", "none"))
                if pattern["source"] == "none":
                    continue
                copy = " ".join(
                    str(card[field]) for field in ("blurb", "useCase", "useWhen", "teaches")
                )
                self.assertIn(
                    pattern["name"],
                    copy,
                    f"{template_id} is offered as {pattern['name']!r} and never "
                    "says so in a field a reader sees",
                )

    def test_every_card_carries_every_field_the_gallery_renders(self) -> None:
        cards = template_documents()["cards"]
        for template_id in GALLERY_ORDER:
            with self.subTest(template=template_id):
                card = cards[template_id]
                for field in (
                    "title",
                    "blurb",
                    "useCase",
                    "useWhen",
                    "notWhen",
                    "teaches",
                    "modifyFirst",
                ):
                    self.assertGreater(
                        len(card[field] or ""),
                        10,
                        f"{template_id}.{field} is part of the card's explanation",
                    )

    def test_the_four_copy_fields_stay_inside_their_caps(self) -> None:
        """16 D4. A card is read at a glance in a grid, not opened and studied.

        The caps are what stop one long card making its neighbours look
        unfinished - the defect D-15-27 fixed for the caveat - and what keeps
        `e2e/builder-layout.spec.ts`'s tallest-to-shortest content ratio under
        two as the gallery grows from nine cards to thirteen.
        """

        cards = template_documents()["cards"]
        for template_id in GALLERY_ORDER:
            for field, cap in LENGTH_CAPS.items():
                length = len(cards[template_id][field] or "")
                with self.subTest(template=template_id, field=field):
                    self.assertLessEqual(
                        length,
                        cap,
                        f"{template_id}.{field} is {length} characters against a "
                        f"cap of {cap}",
                    )

    def test_six_cards_carry_a_caveat_and_the_rest_carry_none(self) -> None:
        """R14, asserted by the word that makes each caveat that caveat."""

        cards = template_documents()["cards"]
        for template_id in GALLERY_ORDER:
            with self.subTest(template=template_id):
                caveat = cards[template_id]["caveat"]
                marker = CAVEAT_MARKERS.get(template_id)
                if marker is None:
                    self.assertIsNone(
                        caveat,
                        "a caveat on a card that needs none dilutes the ones that do",
                    )
                else:
                    self.assertIsNotNone(caveat, "the caveat this card must carry is gone")
                    self.assertIn(marker, caveat)

    def test_no_card_calls_the_thing_a_graph(self) -> None:
        """ROUND-2 section 5 ruling 1, over the copy this plan wrote.

        TWO STRINGS ARE EXEMPT AND THEY ARE NAMED HERE, because the exemption
        is a contradiction worth seeing rather than hiding. 16 criterion 6
        requires `idea-validator`'s and `news-to-social`'s caveats to keep their
        existing sentences word for word, and the flagship's contains "a drawn
        graph carries plain text between its nodes". The two specs that enforce
        the ban scan the home and the run shell, and the home renders no
        caveat, so nothing shipped contradicts the ruling today. A gallery-wide
        scan added later would catch that string, and whoever adds one has to
        rule on it rather than discover it.
        """

        cards = template_documents()["cards"]
        exempt = {cards["idea-validator"]["caveat"], cards["news-to-social"]["caveat"]}
        for template_id in GALLERY_ORDER:
            card = cards[template_id]
            for field in (
                "title",
                "blurb",
                "useCase",
                "useWhen",
                "notWhen",
                "teaches",
                "modifyFirst",
                "caveat",
            ):
                value = card[field]
                if not value or value in exempt:
                    continue
                with self.subTest(template=template_id, field=field):
                    self.assertNotRegex(str(value), r"(?i)\bgraphs?\b")

    def test_no_card_names_a_vendor_or_a_source_in_its_prose(self) -> None:
        """16 D5, twice over.

        No vendor model name anywhere - the rule the model-role tokens exist
        for, applied to prose - and provenance in the pattern line only, so a
        card reads as advice about work rather than as a citation. The two
        verbatim caveats are exempt for the reason the test above gives; neither
        names a vendor today, and the exemption is here so that a future edit to
        one fails for the right reason.
        """

        banned = (
            "Gemini",
            "Claude",
            "GPT",
            "OpenAI",
            "Anthropic",
            "Google",
            "Qwen",
            "DeepSeek",
        )
        cards = template_documents()["cards"]
        offenders: list[str] = []
        for template_id in GALLERY_ORDER:
            card = cards[template_id]
            for field in (
                "title",
                "blurb",
                "useCase",
                "useWhen",
                "notWhen",
                "teaches",
                "modifyFirst",
                "caveat",
            ):
                value = str(card[field] or "")
                for word in banned:
                    if word in value:
                        offenders.append(f"{template_id}.{field}: {word}")
        self.assertEqual(offenders, [])


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

    def test_only_the_declared_two_bill_before_a_gate(self) -> None:
        """Named rather than merely skipped above.

        A test that quietly excluded a case would let a THIRD template become
        ungated without anybody noticing; this fails if one does, and it fails
        if either declared one is ever gated and the exclusion is left behind.

        The order is `LAUNCHABLE`'s, which is gallery order - so this also pins
        that `news-to-social` sits before the flagship.
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

    def test_a_fallback_model_is_a_ROLE_and_resolves_like_any_other(self) -> None:
        """16 criterion 5. `retry.fallback_model` is the fifth model-carrying field.

        `resolveModelRoles` walks every string under a node's config rather than
        naming the four paths it knew about, which is the only reason this
        works without a client change - a path list is the kind of mirror that
        rots without saying so. What is asserted here is the outcome: the token
        is gone, and what replaced it is the escalation preset this build names.
        """

        node = next(
            node
            for node in DOCUMENTS["fallback-bar"].nodes
            if node.id == "answer"
        )
        config = node.config
        assert isinstance(config, AuthoredAgentConfig)
        fallback = config.retry.fallback_model
        self.assertIsNotNone(fallback, "the whole template is this one field")
        self.assertNotIn("{{", str(fallback), "an unresolved role token shipped")
        self.assertIn(str(fallback).split(":", 1)[0], MODEL_BY_ID)
        self.assertEqual(
            str(fallback).removeprefix("openrouter/").split(":", 1)[0],
            MODEL_PRESETS["escalation"].removeprefix("openrouter/").split(":", 1)[0],
        )

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

    def test_the_fallback_retries_at_least_once_or_it_is_inert(self) -> None:
        """The trap this template exists to name, asserted against the document.

        `model_for` offers the fallback only when `index == attempts - 1 and
        index`, so a node carrying a `fallback_model` with `max_retries: 0`
        never reaches the second model at all. It would look configured on the
        canvas, price as though it were, and do nothing - which is worse than
        not offering the field, and is exactly the state a copy-paste of this
        template into a smaller graph would arrive at.
        """

        by_id = {node.id: node for node in DOCUMENTS["fallback-bar"].nodes}
        answer = by_id["answer"].config
        assert isinstance(answer, AuthoredAgentConfig)
        self.assertGreaterEqual(
            answer.retry.max_retries,
            1,
            "a fallback model behind zero retries is inert and looks configured",
        )
        self.assertIsNotNone(answer.retry.fallback_model)
        self.assertGreater(answer.retry.backoff_seconds, 0)

        # The bar itself: one checker, downstream of the answerer, reading
        # whatever came back without knowing which model wrote it. Google's
        # pattern is the single choke point rather than the second model.
        check = by_id["check"].config
        assert isinstance(check, AuthoredAgentConfig)
        self.assertEqual(check.task.output_schema, {"cleared": "boolean", "notes": "string"})
        self.assertEqual(
            [edge.source for edge in DOCUMENTS["fallback-bar"].edges if edge.target == "check"],
            ["answer"],
        )

    def test_the_fallback_loop_is_one_cycle_closed_by_a_router(self) -> None:
        document = DOCUMENTS["fallback-bar"]
        self.assertEqual(estimate_budget(document).cycles, 1)
        back = back_edge_indices(document)
        self.assertEqual(len(back), 1)
        closer = document.edges[back[0]]
        kinds = {node.id: node.kind for node in document.nodes}
        self.assertEqual(kinds[closer.source], "router")
        self.assertEqual(closer.target, "answer")

    def test_the_rule_tier_reaches_the_output_past_no_billable_node(self) -> None:
        """The whole claim of `tiered-routing`, and the only one worth a test.

        Walked rather than asserted about named nodes, so it stays true if the
        phrases, the labels or the number of self-serve replies change: from
        the input, follow flow edges, refuse to enter an agent or a crew, and
        see whether an output is still reachable. If it is, some real traffic
        reaches an answer having paid for nothing, which is what the card
        promises. `conditional-router` is the control: every one of its paths
        goes through the classifier, so the same walk finds nothing there.
        """

        def free_path_exists(template_id: str) -> bool:
            document = DOCUMENTS[template_id]
            kinds = {node.id: node.kind for node in document.nodes}
            forward: dict[str, list[str]] = {}
            for edge in document.edges:
                if edge.target_port == "in":
                    forward.setdefault(str(edge.source), []).append(str(edge.target))
            start = next(node.id for node in document.nodes if node.kind == "input")
            seen: set[str] = set()
            stack = [str(start)]
            while stack:
                current = stack.pop()
                if current in seen:
                    continue
                seen.add(current)
                if kinds[current] in ("agent", "crew"):
                    continue
                if kinds[current] == "output":
                    return True
                stack.extend(forward.get(current, []))
            return False

        self.assertTrue(
            free_path_exists("tiered-routing"),
            "the rule tier is the card's claim and it now costs a model call",
        )
        self.assertFalse(
            free_path_exists("conditional-router"),
            "the control: every path through the classifier template bills",
        )

    def test_the_vote_is_three_independent_reviewers_and_a_counted_tally(self) -> None:
        """The two facts that make it a vote rather than a chain.

        Independence first: no reviewer's `prompt_inputs` may name another
        reviewer's output, or the second one agrees with the first and the
        third agrees with both. Then the join, because `joins: 'all'` is what
        stops the tally counting one opinion out of three having paid for all
        three.
        """

        document = DOCUMENTS["vote-review"]
        by_id = {node.id: node for node in document.nodes}
        reviewers = ("accuracy", "tone", "policy")
        for reviewer in reviewers:
            config = by_id[reviewer].config
            assert isinstance(config, AuthoredAgentConfig)
            with self.subTest(reviewer=reviewer):
                self.assertEqual(sorted(config.prompt_inputs), ["draft"])
                for other in reviewers:
                    self.assertNotIn(
                        f"out__{other}",
                        str(config.prompt_inputs),
                        "a reviewer that can read another reviewer is a chain",
                    )

        self.assertEqual(document.joins["votes"], "all")
        arrivals = [edge.source for edge in document.edges if edge.target == "votes"]
        self.assertEqual(sorted(arrivals), sorted(reviewers))

        # A transform cannot count, so the tally is a model call and the card
        # says so. Asserted here so the card cannot quietly stop being true.
        tally = by_id["tally"].config
        assert isinstance(tally, AuthoredAgentConfig)
        self.assertEqual(
            tally.task.output_schema,
            {"approvals": "number", "objections": "string"},
        )
        self.assertEqual(document.joins["outcome"], "any")

    def test_the_single_agent_is_one_billable_node_with_one_keyless_tool(self) -> None:
        document = DOCUMENTS["single-agent"]
        self.assertEqual(estimate_budget(document).billable_nodes, 1)
        attachments = [edge for edge in document.edges if edge.target_port == "attach"]
        self.assertEqual(len(attachments), 1)
        self.assertEqual(attachments[0].target, "answer")
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
