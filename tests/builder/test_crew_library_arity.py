"""The crew library, checked against the constructors it claims to build.

THE MONEY BUG THIS MODULE EXISTS FOR. `BUILDER_CREW_LIBRARY` advertises six
`@CrewBase` classes and `DefaultCrewFactories.crew` builds them with a bare
zero-argument call - `getattr(validator_crew, class_name)().crew()`. Two of the
six do not have a zero-argument `__init__`: `SynthesisCrew` wants the three
research findings and `ReportCrew` wants a verdict and the tool URLs behind it,
both as typed pydantic objects the validator flow passes in Python. A document
naming `crew_id: "synthesis"` therefore validated clean, published clean, was
priced and registered, and raised a bare `TypeError` inside a worker thread at
the moment that node ran - after the scoper and all three research branches had
billed real money for a context nothing would consume.

`UNBUILDABLE_BUILDER_CREWS` is a DECLARATION, because deriving it would mean
importing `crews.validator_crew` - Firecrawl, the HN client, the GitHub client
- inside the compiler, which the note above `BUILDER_CREW_LIBRARY` forbids for
exactly the reason it sounds like. A declaration can lie, so this module is
what stops it: it imports the real classes, reads the real signatures, and
asserts the map is EXACTLY right for all six. A seventh crew added to the
library with a required argument fails here, in a no-cost test, rather than on
a paid run.

No model is called and no network is touched: `inspect.signature` reads a
function object, and none of these classes is instantiated.
"""

from __future__ import annotations

import inspect
import unittest
from typing import Any

from brief_crew.builder import BuilderDocument
from brief_crew.builder.compiler import (
    LIBRARY_UNBUILDABLE,
    LIBRARY_UNKNOWN,
    document_problems,
    library_problems,
)
from brief_crew.builder.runtime import (
    BUILDABLE_BUILDER_CREW_IDS,
    BUILDER_CREW_LIBRARY,
    UNBUILDABLE_BUILDER_CREWS,
    BuilderRuntimeError,
    DefaultCrewFactories,
    unbuildable_crew_reason,
)
from tests.builder.test_document import (
    document,
    edge,
    input_node,
    node,
    output_node,
)


def required_arguments(cls: type) -> tuple[str, ...]:
    """Parameters of ``cls.__init__`` that a zero-argument call cannot satisfy.

    ``self`` is dropped, as are ``*args``/``**kwargs`` and anything carrying a
    default - none of which makes ``Class()`` fail. What is left is precisely
    the set that turns the factory's zero-argument call into a ``TypeError``.
    """

    parameters = list(inspect.signature(cls.__init__).parameters.values())[1:]
    return tuple(
        parameter.name
        for parameter in parameters
        if parameter.default is inspect.Parameter.empty
        and parameter.kind
        not in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
    )


def crew_node(node_id: str, crew_id: str) -> dict[str, Any]:
    return node(node_id, "crew", {"crew_id": crew_id, "tier": "cheap"})


def one_crew_document(crew_id: str) -> BuilderDocument:
    """Input -> one crew node -> output. The node is `writer` because that is
    the id `output_node`'s default source references, and a document whose
    output points at a node that is not there is a different refusal."""

    return document(
        [input_node("idea"), crew_node("writer", crew_id), output_node()],
        [edge("e1", "idea", "writer"), edge("e2", "writer", "report")],
    )


class DeclarationMatchesTheRealSignaturesTests(unittest.TestCase):
    """The anti-drift half: the map is checked against the classes."""

    def _classes(self) -> dict[str, type]:
        import brief_crew.crews.validator_crew as validator_crew

        return {
            crew_id: getattr(validator_crew, class_name)
            for crew_id, class_name in BUILDER_CREW_LIBRARY.items()
        }

    def test_every_registered_crew_declares_its_real_required_arguments(self) -> None:
        for crew_id, cls in self._classes().items():
            with self.subTest(crew=crew_id):
                self.assertEqual(
                    required_arguments(cls),
                    UNBUILDABLE_BUILDER_CREWS.get(crew_id, ()),
                )

    def test_the_declared_unbuildable_set_is_exactly_the_unbuildable_one(self) -> None:
        measured = {
            crew_id
            for crew_id, cls in self._classes().items()
            if required_arguments(cls)
        }
        self.assertEqual(measured, set(UNBUILDABLE_BUILDER_CREWS))

    def test_the_two_named_crews_are_the_ones_the_survey_measured(self) -> None:
        """Pinned as literals so a silent widening of the set is visible."""

        self.assertEqual(
            dict(UNBUILDABLE_BUILDER_CREWS),
            {
                "synthesis": ("market", "sentiment", "feasibility"),
                "report": ("verdict", "tool_urls"),
            },
        )

    def test_buildable_is_the_library_minus_the_unbuildable(self) -> None:
        self.assertEqual(
            BUILDABLE_BUILDER_CREW_IDS,
            frozenset({"scope", "market", "sentiment", "feasibility"}),
        )
        self.assertEqual(
            BUILDABLE_BUILDER_CREW_IDS | set(UNBUILDABLE_BUILDER_CREWS),
            set(BUILDER_CREW_LIBRARY),
        )

    def test_every_buildable_crew_really_takes_no_arguments(self) -> None:
        """The other direction: nothing is refused that would have worked."""

        classes = self._classes()
        for crew_id in sorted(BUILDABLE_BUILDER_CREW_IDS):
            with self.subTest(crew=crew_id):
                self.assertEqual(required_arguments(classes[crew_id]), ())


class ReasonTests(unittest.TestCase):
    def test_a_buildable_crew_has_no_reason(self) -> None:
        for crew_id in sorted(BUILDABLE_BUILDER_CREW_IDS):
            with self.subTest(crew=crew_id):
                self.assertIsNone(unbuildable_crew_reason(crew_id))

    def test_an_unknown_crew_has_no_reason_either(self) -> None:
        """An unknown id is a different refusal, and the caller makes it."""

        self.assertIsNone(unbuildable_crew_reason("nope"))

    def test_the_reason_names_the_class_and_every_argument(self) -> None:
        reason = unbuildable_crew_reason("synthesis")
        assert reason is not None
        self.assertIn("SynthesisCrew", reason)
        for argument in ("market", "sentiment", "feasibility"):
            self.assertIn(argument, reason)
        self.assertIn("scope", reason)

    def test_the_report_reason_names_its_own_two_arguments(self) -> None:
        reason = unbuildable_crew_reason("report")
        assert reason is not None
        self.assertIn("ReportCrew", reason)
        self.assertIn("verdict", reason)
        self.assertIn("tool_urls", reason)

    def test_the_reason_offers_only_crews_that_can_run(self) -> None:
        reason = unbuildable_crew_reason("synthesis")
        assert reason is not None
        offered = reason.split("may name are")[1]
        self.assertEqual(
            {item.strip() for item in offered.split(",")},
            set(BUILDABLE_BUILDER_CREW_IDS),
        )


class LibraryProblemsTests(unittest.TestCase):
    """The refusal at the layer that costs nothing: validate and publish."""

    def test_an_unbuildable_crew_is_an_error_before_anything_bills(self) -> None:
        for crew_id in sorted(UNBUILDABLE_BUILDER_CREWS):
            with self.subTest(crew=crew_id):
                problems = library_problems(one_crew_document(crew_id))
                self.assertEqual(len(problems), 1)
                self.assertEqual(problems[0].code, LIBRARY_UNBUILDABLE)
                self.assertEqual(problems[0].severity, "error")
                self.assertIn(crew_id, problems[0].message)

    def test_the_problem_carries_the_node_the_canvas_has_to_rim(self) -> None:
        problem = library_problems(one_crew_document("synthesis"))[0]
        self.assertEqual(problem.node_id, "writer")

    def test_a_buildable_crew_is_accepted(self) -> None:
        for crew_id in sorted(BUILDABLE_BUILDER_CREW_IDS):
            with self.subTest(crew=crew_id):
                self.assertEqual(library_problems(one_crew_document(crew_id)), [])

    def test_an_unknown_crew_is_still_refused_and_lists_the_buildable_ones(self) -> None:
        problems = library_problems(one_crew_document("nope"))
        self.assertEqual(len(problems), 1)
        self.assertEqual(problems[0].code, LIBRARY_UNKNOWN)
        self.assertIn("'nope'", problems[0].message)
        self.assertNotIn("synthesis", problems[0].message)
        self.assertNotIn("report", problems[0].message)

    def test_an_unknown_crew_is_refused_once_and_not_twice(self) -> None:
        """The unknown branch continues, or the author reads two sentences."""

        self.assertEqual(len(library_problems(one_crew_document("synthesist"))), 1)


class CompileAndPublishTests(unittest.TestCase):
    """One list of problems, whether the author pressed Save or Publish."""

    def test_the_document_that_used_to_publish_cleanly_no_longer_compiles(self) -> None:
        from brief_crew.builder.compiler import BuilderCompileError, compile_document

        with self.assertRaises(BuilderCompileError) as raised:
            compile_document(one_crew_document("synthesis"))
        self.assertIn("SynthesisCrew", str(raised.exception))

    def test_the_endpoint_composition_reports_it_too_rather_than_only_publish(self) -> None:
        """The half of this that the canvas actually reads.

        `library_problems` ran only inside `compile_document` until this
        landed, so `/api/builder/validate` called a document with an
        unbuildable node CLEAN and the author met the refusal on Publish.
        `document_problems` is the composition every author-facing endpoint now
        calls, so the two lists cannot come apart again.
        """

        problems = document_problems(one_crew_document("report"))
        errors = [item for item in problems if item.severity == "error"]
        self.assertTrue(any("ReportCrew" in item.message for item in errors))

    def test_validate_document_itself_still_answers_only_structure_and_price(self) -> None:
        """Deliberate, and the reason `document_problems` exists at all.

        `structural_problems` reads a document on its own terms; the library
        check asks what THIS deployment can build. Folding the second into
        `validate_document` would make every fixture in `tests/builder/`
        illegal, because they wire realistic topologies out of placeholder
        agent ids on purpose.
        """

        from brief_crew.builder import validate_document

        self.assertEqual(validate_document(one_crew_document("synthesis")), [])

    def test_a_buildable_crew_document_validates_and_compiles(self) -> None:
        """The control: nothing here refuses a graph that would have worked."""

        from brief_crew.builder.compiler import compile_document

        graph = one_crew_document("market")
        self.assertEqual(document_problems(graph), [])
        self.assertIsNotNone(compile_document(graph).definition)


class FactoryTests(unittest.TestCase):
    """The same refusal at the site that actually raised the TypeError.

    Reachable independently of the compiler - a stored document published
    before the check existed, or a direct factory call - so it is not a
    duplicate of the compile-time refusal, it is the one that would have run.
    """

    def _build(self, crew_id: str) -> Any:
        return DefaultCrewFactories().crew(
            node_id="worker",
            crew_id=crew_id,
            tier="cheap",
            max_iter=3,
            guardrail_max_retries=2,
        )

    def test_the_factory_refuses_an_unbuildable_crew_by_name(self) -> None:
        for crew_id in sorted(UNBUILDABLE_BUILDER_CREWS):
            with self.subTest(crew=crew_id):
                with self.assertRaises(BuilderRuntimeError) as raised:
                    self._build(crew_id)
                self.assertIn(crew_id, str(raised.exception))

    def test_it_is_no_longer_a_bare_type_error(self) -> None:
        """The measured symptom was `__init__() missing 3 required arguments`."""

        with self.assertRaises(BuilderRuntimeError) as raised:
            self._build("synthesis")
        self.assertNotIsInstance(raised.exception, TypeError)
        self.assertIn("typed findings", str(raised.exception))

    def test_an_unknown_crew_id_lists_the_buildable_ones(self) -> None:
        with self.assertRaises(BuilderRuntimeError) as raised:
            self._build("nope")
        self.assertNotIn("synthesis", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
