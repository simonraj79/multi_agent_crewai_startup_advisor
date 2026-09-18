"""The generic score hook: one number against one run's trace (A12, A13).

Plan 18 section 2.2. `docs/observability/DEFINITION-OF-DONE.md` section 5.6
permits a flow's own metric to be scored *"through a declared, generic hook
later"*; the owner asked for the integration, so 5.6's authorisation is given
and `observability/scores.py` is that hook.

Two criteria, and the second is the one that keeps the observability
programme's central guarantee intact:

* **A12** - `record_run_score` calls the backend once with
  `trace_id_for(run_id)`, **imported and not re-derived**, proved by patching
  the imported name and watching the answer move; and it returns `False`
  without raising when the exporter is off.
* **A13** - `test_no_flow_identifiers.py` passes **unmodified** with
  `scores.py` present, and a planted identifier still fails it. That test is
  the one thing standing between this repository and an exporter that names
  its own product, so a new module in the package is exactly the moment to
  re-run it and to prove it can still fail.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from brief_crew.observability import scores
from brief_crew.observability.backend import RecordingBackend, trace_id_for


RUN_ID = "11111111-2222-4333-8444-555555555555"


class FakePolicy:
    def __init__(self, capture_content: bool = False) -> None:
        self.capture_content = capture_content


class FakeExporter:
    """An exporter shaped like the real one where this hook touches it."""

    def __init__(self, backend: object | None, capture_content: bool = False) -> None:
        self._backend = backend
        self.policy = FakePolicy(capture_content)


class ScoreHookTests(unittest.TestCase):
    def setUp(self) -> None:
        self.backend = RecordingBackend()
        self.exporter = FakeExporter(self.backend)

    def test_one_score_reaches_the_backend(self) -> None:
        sent = scores.record_run_score(
            RUN_ID,
            name=scores.SCORE_HUMAN_RATING,
            value=1,
            data_type="NUMERIC",
            exporter=self.exporter,
        )
        self.assertTrue(sent)
        self.assertEqual(1, len(self.backend.scores))
        written = self.backend.scores[0]
        self.assertEqual("human_rating", written.name)
        self.assertEqual(1, written.value)
        self.assertEqual("NUMERIC", written.data_type)

    def test_the_trace_id_is_the_imported_derivation(self) -> None:
        """A12's proof, and it is the shape of proof that can fail.

        `trace_id_for` is imported into this module's namespace at import, so
        patching that NAME changes the answer only if the hook calls it. A
        second derivation of the same id would ignore the patch and produce
        the real hex - which is what the assertion below would then catch.
        """

        scores.record_run_score(
            RUN_ID,
            name="human_rating",
            value=0,
            data_type="NUMERIC",
            exporter=self.exporter,
        )
        self.assertEqual(trace_id_for(RUN_ID), self.backend.scores[0].trace_id)

        with patch.object(scores, "trace_id_for", return_value="a-patched-id"):
            scores.record_run_score(
                RUN_ID,
                name="human_rating",
                value=0,
                data_type="NUMERIC",
                exporter=self.exporter,
            )
        self.assertEqual("a-patched-id", self.backend.scores[1].trace_id)

    def test_the_score_is_on_the_trace_and_not_an_observation(self) -> None:
        """A rating arrives AFTER the trace closed; there is no span to hang it on."""

        scores.record_run_score(
            RUN_ID,
            name="human_rating",
            value=1,
            data_type="NUMERIC",
            exporter=self.exporter,
        )
        self.assertIsNone(self.backend.scores[0].observation_id)

    # -- it cannot fail a caller ------------------------------------------

    def test_no_exporter_returns_false_and_raises_nothing(self) -> None:
        scores.set_score_exporter(None)
        self.assertFalse(
            scores.record_run_score(
                RUN_ID, name="human_rating", value=1, data_type="NUMERIC"
            )
        )

    def test_an_exporter_with_no_backend_returns_false(self) -> None:
        """The `NullExporter` shape a misconfigured deployment gets."""

        self.assertFalse(
            scores.record_run_score(
                RUN_ID,
                name="human_rating",
                value=1,
                data_type="NUMERIC",
                exporter=FakeExporter(None),
            )
        )

    def test_a_backend_that_raises_does_not_reach_the_caller(self) -> None:
        """Telemetry is never the reason a person's button reports an error."""

        class Exploding:
            def score(self, **_: object) -> None:
                raise RuntimeError("langfuse is down")

        self.assertTrue(
            scores.record_run_score(
                RUN_ID,
                name="human_rating",
                value=1,
                data_type="NUMERIC",
                exporter=FakeExporter(Exploding()),
            )
        )

    def test_an_underivable_trace_id_returns_false(self) -> None:
        with patch.object(scores, "trace_id_for", side_effect=ValueError("no")):
            self.assertFalse(
                scores.record_run_score(
                    RUN_ID,
                    name="human_rating",
                    value=1,
                    data_type="NUMERIC",
                    exporter=self.exporter,
                )
            )

    def test_the_module_exporter_is_used_when_none_is_passed(self) -> None:
        scores.set_score_exporter(self.exporter)
        self.addCleanup(scores.set_score_exporter, None)
        self.assertTrue(
            scores.record_run_score(
                RUN_ID, name="human_rating", value=1, data_type="NUMERIC"
            )
        )
        self.assertEqual(1, len(self.backend.scores))

    # -- the note is content ----------------------------------------------

    def test_a_note_is_withheld_under_the_default_policy(self) -> None:
        """Free text a person typed. The default is not a denylist."""

        scores.record_run_score(
            RUN_ID,
            name="human_rating",
            value=1,
            data_type="NUMERIC",
            comment="the segment was wrong and the report cited nothing",
            exporter=self.exporter,
        )
        self.assertIsNone(self.backend.scores[0].comment)

    def test_a_note_is_written_when_capture_is_on(self) -> None:
        exporter = FakeExporter(self.backend, capture_content=True)
        scores.record_run_score(
            RUN_ID,
            name="human_rating",
            value=1,
            data_type="NUMERIC",
            comment="the segment was wrong",
            exporter=exporter,
        )
        self.assertEqual("the segment was wrong", self.backend.scores[0].comment)

    def test_a_backend_whose_score_predates_comment_still_gets_the_number(
        self,
    ) -> None:
        """The number is the point; the note is the annotation."""

        written: list[dict[str, object]] = []

        class OldBackend:
            def score(self, **fields: object) -> None:
                if "comment" in fields:
                    raise TypeError("unexpected keyword argument 'comment'")
                written.append(fields)

        scores.record_run_score(
            RUN_ID,
            name="human_rating",
            value=1,
            data_type="NUMERIC",
            comment="a note",
            exporter=FakeExporter(OldBackend(), capture_content=True),
        )
        self.assertEqual(1, len(written))
        self.assertEqual(1, written[0]["value"])


class RatingScoreValueTests(unittest.TestCase):
    """`good` and `bad` are a scale; `unsure` is a person declining to say."""

    def test_good_and_bad_are_the_numeric_pair(self) -> None:
        self.assertEqual((1, "NUMERIC"), scores.rating_score_value("good"))
        self.assertEqual((0, "NUMERIC"), scores.rating_score_value("bad"))

    def test_unsure_is_categorical_and_not_a_made_up_half(self) -> None:
        value, data_type = scores.rating_score_value("unsure")
        self.assertEqual("CATEGORICAL", data_type)
        self.assertNotIsInstance(value, (int, float))

    def test_a_cleared_rating_scores_nothing(self) -> None:
        """Langfuse has no "unset a score", and a third value would be a fourth
        thing for a reader to interpret."""

        self.assertIsNone(scores.rating_score_value(None))
        self.assertIsNone(scores.rating_score_value("something-else"))


class NoFlowIdentifierTests(unittest.TestCase):
    """A13, run from here as well as from its own module.

    The point is not to duplicate that test - it is to state, in the module
    that adds a file to the package, that the guarantee still holds and that
    the guard can still fail. A guard nobody can make fail is a comment.
    """

    def test_the_package_scan_passes_with_scores_py_present(self) -> None:
        import io
        import unittest as _unittest

        from tests.observability import test_no_flow_identifiers

        suite = _unittest.defaultTestLoader.loadTestsFromModule(
            test_no_flow_identifiers
        )
        result = _unittest.TextTestRunner(stream=io.StringIO(), verbosity=0).run(
            suite
        )
        self.assertTrue(result.wasSuccessful(), result.failures + result.errors)
        # Ten tests, and the count is asserted so a module that silently
        # stopped collecting cannot pass this by running nothing - gotcha 20's
        # failure mode, which is exactly the one a nested runner invites.
        self.assertGreaterEqual(result.testsRun, 10)

    def test_scores_py_names_no_agent_task_tool_crew_or_flow(self) -> None:
        """The same question asked directly of the new file.

        Its two score names - `human_rating` and `gate_outcome` - are facts
        about a run rather than about anything a particular product does,
        which is why they are allowed to be literals here.
        """

        import pathlib

        source = pathlib.Path(scores.__file__).read_text(encoding="utf-8").lower()
        for identifier in (
            "market evidence analyst",
            "idea-validator",
            "scope_idea",
            "validatorflow",
            "market_research",
        ):
            with self.subTest(identifier=identifier):
                self.assertNotIn(identifier, source)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
