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


class ScoreIdTests(unittest.TestCase):
    """One id, upserted, and a write that never deletes. Refine round 2.

    Two designs failed here before this one, and both failed on a REAL trace
    rather than in a test:

    * no id at all - `create_score` appends, so `good` then `bad` left both
      1 and 0 on the trace and a clear left both while Postgres said unrated;
    * two ids, numeric and categorical, with the write deleting the loser -
      four PUTs inside eight seconds left TWO scores permanently, because
      `delete_score` is a synchronous HTTP call while `create_score` sits in
      the SDK's asynchronous batch queue, so the delete arrived first, 404'd
      against a create that had not been ingested, and the create landed
      behind it and stayed.

    So: **one CATEGORICAL id, the word as the value, and no delete on any
    write.** These assert what is SENT - the double records deletes rather
    than simulating them, so nothing here can pass over a sequence the real
    API would have reordered.
    """

    def setUp(self) -> None:
        self.backend = RecordingBackend()
        self.exporter = FakeExporter(self.backend)
        self.trace = trace_id_for(RUN_ID)
        self.score_id = f"{self.trace}{scores.RATING_SCORE_ID_SUFFIX}"

    def rate(self, rating: str | None, **kwargs: object) -> bool:
        return scores.record_run_rating(
            RUN_ID, rating, exporter=self.exporter, **kwargs
        )

    # -- a write is an upsert and NOTHING else ----------------------------

    def test_four_rapid_ratings_are_four_upserts_of_one_id(self) -> None:
        """The measured failure, as an assertion: a misclick corrected within
        seconds is the commonest reason anybody re-rates."""

        for word in ("good", "bad", "unsure", "good"):
            self.rate(word)
        self.assertEqual(
            [self.score_id] * 4, [row.score_id for row in self.backend.scores]
        )
        self.assertEqual(
            ["good", "bad", "unsure", "good"],
            [row.value for row in self.backend.scores],
        )

    def test_no_write_ever_deletes(self) -> None:
        """The property that makes the ordering irrelevant. If this fails, the
        race is back however the ids are named."""

        for word in ("good", "bad", "unsure", "good"):
            self.rate(word)
        self.assertEqual([], self.backend.deleted_scores)

    def test_every_write_is_categorical_including_good_and_bad(self) -> None:
        """Never a type change, because a type change needs two ids."""

        for word in ("good", "bad", "unsure"):
            self.rate(word)
        self.assertEqual(
            {"CATEGORICAL"}, {row.data_type for row in self.backend.scores}
        )

    def test_one_name_for_every_value(self) -> None:
        """A Langfuse filter has to see one series."""

        for word in ("good", "unsure"):
            self.rate(word)
        self.assertEqual({"human_rating"}, {row.name for row in self.backend.scores})

    def test_a_word_this_module_does_not_know_is_not_written(self) -> None:
        """A score nobody can count is worse than no score."""

        self.assertFalse(self.rate("excellent"))
        self.assertEqual([], self.backend.scores)

    # -- a clear is the only delete, and it is issued twice ---------------

    def test_a_clear_deletes_now_and_schedules_one_sweep(self) -> None:
        self.addCleanup(self._drain)
        self.assertTrue(self.rate(None, sweep_after_seconds=3600))
        self.assertEqual([], self.backend.scores)
        self.assertEqual([self.score_id], self.backend.deleted_scores)
        self.assertEqual(1, scores.pending_clear_sweeps())

    def test_the_deferred_sweep_deletes_the_same_id_again(self) -> None:
        """The fix for the race: the create the first delete missed may only
        have been ingested afterwards."""

        scores.sweep_cleared_rating(run_id=RUN_ID, exporter=self.exporter)
        self.assertEqual([self.score_id], self.backend.deleted_scores)

    def test_the_sweep_does_nothing_when_somebody_re_rated(self) -> None:
        """The source of truth wins. A rating made four seconds after a clear
        must not vanish forty seconds later."""

        self.assertFalse(
            scores.sweep_cleared_rating(
                run_id=RUN_ID, exporter=self.exporter, still_cleared=lambda: False
            )
        )
        self.assertEqual([], self.backend.deleted_scores)

    def test_a_store_that_cannot_answer_is_not_a_licence_to_delete(self) -> None:
        def explode() -> bool:
            raise RuntimeError("the database is away")

        self.assertFalse(
            scores.sweep_cleared_rating(
                run_id=RUN_ID, exporter=self.exporter, still_cleared=explode
            )
        )
        self.assertEqual([], self.backend.deleted_scores)

    def test_a_second_clear_replaces_the_first_timer(self) -> None:
        self.addCleanup(self._drain)
        self.rate(None, sweep_after_seconds=3600)
        self.rate(None, sweep_after_seconds=3600)
        self.assertEqual(
            1, scores.pending_clear_sweeps(), "two timers against one score id"
        )

    def test_a_fired_sweep_leaves_no_entry_behind(self) -> None:
        self.rate(None, sweep_after_seconds=3600)
        scores.sweep_cleared_rating(run_id=RUN_ID, exporter=self.exporter)
        self.assertEqual(0, scores.pending_clear_sweeps())

    def test_a_sweep_that_404s_is_not_an_error(self) -> None:
        """A 404 is the ORDINARY answer - it means the score was never
        ingested, which is the goal."""

        class NotFound:
            def score(self, **_: object) -> None:
                return None

            def delete_score(self, _score_id: str) -> None:
                raise RuntimeError("status_code: 404, body: not found")

        self.assertTrue(
            scores.sweep_cleared_rating(
                run_id=RUN_ID, exporter=FakeExporter(NotFound())
            )
        )

    def test_a_delete_that_explodes_does_not_reach_the_caller(self) -> None:
        self.addCleanup(self._drain)

        class Stubborn:
            def score(self, **_: object) -> None:
                return None

            def delete_score(self, _score_id: str) -> None:
                raise RuntimeError("langfuse is down")

        self.assertTrue(
            scores.record_run_rating(
                RUN_ID, None, exporter=FakeExporter(Stubborn()), sweep_after_seconds=3600
            )
        )

    # -- the exporter being off changes none of it ------------------------

    def test_a_clear_with_no_exporter_is_false_and_schedules_nothing(self) -> None:
        scores.set_score_exporter(None)
        self.assertFalse(scores.record_run_rating(RUN_ID, None))
        self.assertEqual(0, scores.pending_clear_sweeps())

    def test_a_null_exporter_schedules_nothing_either(self) -> None:
        self.assertFalse(
            scores.record_run_rating(
                RUN_ID, None, exporter=FakeExporter(None), sweep_after_seconds=3600
            )
        )
        self.assertEqual(0, scores.pending_clear_sweeps())

    # -- older backends still get the value -------------------------------

    def test_a_backend_with_no_delete_still_writes_the_score(self) -> None:
        written: list[dict[str, object]] = []

        class OldBackend:
            def score(self, **fields: object) -> None:
                written.append(fields)

        self.assertTrue(
            scores.record_run_rating(
                RUN_ID, "good", exporter=FakeExporter(OldBackend())
            )
        )
        self.assertEqual("good", written[0]["value"])

    def test_a_backend_whose_score_predates_score_id_still_gets_the_value(self) -> None:
        written: list[dict[str, object]] = []

        class OlderBackend:
            def score(self, **fields: object) -> None:
                if "score_id" in fields:
                    raise TypeError("unexpected keyword argument 'score_id'")
                written.append(fields)

            def delete_score(self, _score_id: str) -> None:
                return None

        scores.record_run_rating(
            RUN_ID, "good", exporter=FakeExporter(OlderBackend())
        )
        self.assertEqual(1, len(written))
        self.assertEqual("good", written[0]["value"])

    def test_the_exporters_own_scores_still_carry_no_id(self) -> None:
        """`guardrail_passed` is one fact per check; there is nothing to
        overwrite, and giving it an id would collapse a run's checks into
        one score."""

        scores.record_run_score(
            RUN_ID,
            name="guardrail_passed",
            value=1,
            data_type="NUMERIC",
            exporter=self.exporter,
        )
        self.assertIsNone(self.backend.scores[0].score_id)
        self.assertEqual([], self.backend.deleted_scores)

    @staticmethod
    def _drain() -> None:
        """Cancel any armed timer, so no case leaks one into the next."""

        with scores._sweep_lock:
            for timer in scores._sweeps.values():
                timer.cancel()
            scores._sweeps.clear()

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
