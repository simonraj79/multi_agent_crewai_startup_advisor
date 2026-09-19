"""Compare: did the change help, on the same measures (plan 21, T2).

The join between a run and the version of the graph that
produced it is real but indirect: `runs.workflow_id` IS the document id, and
`runs.graph_version` is a content hash, so *"v3 versus v4"* was a question this
data could not answer.

Two halves:

* `resolve_document_version` recomputes each stored version's hash with the
  **imported** `_descriptor_version` and matches; an unmatched hash is `None`,
  grouped `"unknown"`, never merged into a numbered arm. It is what answers
  for a run written before the lineage column existed - the column itself is
  proved in `tests/service/test_document_version_stamp.py`, at both doors.
* Both axes return arms with six measures and `n`, and an arm under
  `IMPROVE_MIN_COMPARE_RUNS` carries `underpowered: true` rather than being
  hidden: a difference over three runs is noise wearing a number, and hiding
  the arm would let a reader conclude the comparison could not be made.

**R4 is the ruling this module pins hardest.** On the model axis `node_id` is
REQUIRED (422 without it), the arms are DISJOINT - one run reaches one arm -
and `cost_per_run_usd` is that node's cost for that model rather than the
whole run's.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import os
import unittest
from unittest.mock import patch

from brief_crew import config
from brief_crew.service.improve_api import resolve_document_version
from tests.service.builder_auth import (
    ADA,
    ADA_TOKEN,
    BuilderAuthCase,
    document_payload,
)


NOW = datetime.now(timezone.utc)


class ImproveBuilderCase(BuilderAuthCase):
    """A builder author who is also this deployment's admin.

    One identity in both roles, because the alternative is a third token for
    no gain: what these tests are about is the join between a run and a
    version, and `require_admin`'s own 404 is proved in `test_admin_auth.py`
    and again below.
    """

    def setUp(self) -> None:
        # An in-memory database of this case's own, and it is not tidiness.
        # `create_app` reads `DATABASE_URL` from the environment, and this
        # machine's `.env` points it at a shared local PostgreSQL loaded with
        # `override=True` - so without this every run of this module seeds
        # `v3-0` into a database that still has yesterday's `v3-0` and fails
        # on the primary key. A test that depends on which developer's box it
        # is on is a test that proves nothing.
        environment = patch.dict(
            os.environ, {"DATABASE_URL": "sqlite+pysqlite:///:memory:"}
        )
        environment.start()
        self.addCleanup(environment.stop)
        super().setUp()
        item = patch.object(config, "ADMIN_EMAILS", (ADA.email,))
        item.start()
        self.addCleanup(item.stop)
        self.persistence = self.app.state.run_registry.persistence

    def admin_get(self, path: str) -> object:
        return self.client.get(f"/api/admin{path}", headers=self.auth(ADA_TOKEN))

    def admin_ok(self, path: str) -> dict:
        response = self.admin_get(path)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()


class ResolveDocumentVersionTests(ImproveBuilderCase):
    """The reader for runs written before the lineage column existed."""

    def setUp(self) -> None:
        super().setUp()
        created = self.create_as(ADA_TOKEN)
        self.document_id = created["document"]["id"]
        saved = self.save_as(
            ADA_TOKEN,
            self.document_id,
            document_payload(name="A second version"),
            expected_version=1,
        )
        self.assertEqual(saved.status_code, 200, saved.text)
        self.store_ = self.store()

    def hash_of(self, version: int) -> str:
        """The content hash of one stored version, by the SAME derivation.

        Computed here through the same imported helper the resolver uses. It
        is not a duplicate implementation: it is the test naming the answer it
        expects, from the store, so a resolver that returned the newest
        version regardless would fail.
        """

        from brief_crew.builder.descriptor import (
            _descriptor_version,
            builder_graph_descriptor,
        )

        stored = self.store_.load(self.document_id, version=version, user_id=ADA.id)
        descriptor = builder_graph_descriptor(stored.document)
        return _descriptor_version(
            stored.document,
            list(descriptor.nodes),
            list(descriptor.edges),
            list(descriptor.start_nodes),
        )

    def test_each_version_resolves_to_its_own_integer(self) -> None:
        for version in (1, 2):
            with self.subTest(version=version):
                self.assertEqual(
                    version,
                    resolve_document_version(
                        self.store_,
                        self.document_id,
                        self.hash_of(version),
                        user_id=ADA.id,
                    ),
                )

    def test_a_caller_who_does_not_own_the_document_gets_none(self) -> None:
        """Which is why the route reads the owner first, and this test exists.

        The store refuses a stranger, so a resolver called with no owner would
        answer `"unknown"` for every run of every OWNED document - the honest
        answer to "I cannot prove it" and the wrong answer to "I did not ask
        properly".
        """

        self.assertIsNone(
            resolve_document_version(
                self.store_, self.document_id, self.hash_of(1), user_id=None
            )
        )

    def test_an_unmatched_hash_is_none(self) -> None:
        """`None` is grouped `"unknown"` by the caller and never merged."""

        self.assertIsNone(
            resolve_document_version(
                self.store_, self.document_id, "0" * 16, user_id=ADA.id
            )
        )

    def test_an_unknown_document_is_none_rather_than_raising(self) -> None:
        self.assertIsNone(
            resolve_document_version(
                self.store_, "ug_00000000", self.hash_of(1), user_id=ADA.id
            )
        )

    def test_the_cache_is_consulted_before_the_store(self) -> None:
        """Deterministic and cached per request - the same hash twice is one
        walk of the version history, not two."""

        cache: dict[str, int | None] = {"deadbeefdeadbeef": 7}
        self.assertEqual(
            7,
            resolve_document_version(
                self.store_,
                self.document_id,
                "deadbeefdeadbeef",
                user_id=ADA.id,
                cache=cache,
            ),
        )

    def test_the_whole_index_is_written_into_the_cache_at_once(self) -> None:
        """D10: one walk per document, not one per distinct hash.

        It used to re-list and re-load every stored version for each
        UNMATCHED hash, so a window holding ten unresolvable runs walked the
        history ten times, loading and re-deriving a descriptor each time.
        """

        cache: dict[str, int | None] = {}
        resolve_document_version(
            self.store_, self.document_id, self.hash_of(2), user_id=ADA.id, cache=cache
        )
        self.assertEqual({self.hash_of(1): 1, self.hash_of(2): 2}, {
            key: value for key, value in cache.items() if not key.startswith("__")
        })

    def test_an_unmatched_hash_does_not_walk_the_store_again(self) -> None:
        """The defect measured: the SECOND unknown hash cost a second walk."""

        calls: list[str] = []
        real = self.store_

        class Counting:
            """A thin shim, because the store itself refuses attribute
            assignment - and a shim is what the resolver actually takes."""

            def versions(self, document_id: str, **kwargs: object) -> list[int]:
                calls.append(document_id)
                return real.versions(document_id, **kwargs)

            def load(self, *args: object, **kwargs: object) -> object:
                return real.load(*args, **kwargs)

        store = Counting()
        cache: dict[str, int | None] = {}
        for digest in ("0" * 16, "1" * 16, "2" * 16):
            self.assertIsNone(
                resolve_document_version(
                    store, self.document_id, digest, user_id=ADA.id, cache=cache
                )
            )
        self.assertEqual([self.document_id], calls)


class CompareArmsTests(ImproveBuilderCase):
    """Six measures, `n` on every arm, and the floor made visible."""

    WORKFLOW = "ug_compare01"

    def setUp(self) -> None:
        super().setUp()
        # Version 3: six runs, so it clears `IMPROVE_MIN_COMPARE_RUNS`.
        # Version 4: two runs, so it does not - and must still be SHOWN.
        for index in range(6):
            self.seed(f"v3-{index}", version=3, verdict="VALIDATE", rating="good")
        for index in range(2):
            self.seed(f"v4-{index}", version=4, verdict="NEEDS_WORK", rating="bad")

    def seed(
        self,
        run_id: str,
        *,
        version: int,
        verdict: str,
        rating: str,
        model: str | None = None,
    ) -> None:
        created = NOW - timedelta(hours=2)
        self.persistence.create_run(
            run_id=run_id,
            session_id="s",
            workflow_id=self.WORKFLOW,
            graph_version=f"hash-v{version}",
            inputs={"idea": "an idea"},
            user_id=ADA.id,
            status="queued",
            created_at=created,
            document_version=version,
        )
        self.persistence.save_node_metrics(
            run_id,
            "n1_agent",
            model=model or config.ESCALATION_MODEL,
            cost_usd=Decimal("0.0500"),
            total_tokens=1000,
            prompt_tokens=800,
            completion_tokens=200,
            call_count=2,
        )
        self.persistence.update_run_status(
            run_id,
            "completed",
            started_at=created,
            completed_at=created + timedelta(seconds=30),
        )
        self.persistence.set_run_rating(
            run_id, rating=rating, note=None, rated_by=ADA.id
        )
        self.seed_verdict(run_id, verdict)
        self.persistence.open_gate(
            run_id,
            "confirm",
            node_id="n2_gate",
            request={"fields": {"segment": "SMBs"}},
            opened_at=created,
        )
        self.persistence.answer_gate(
            run_id,
            "confirm",
            {"decision": "revise" if version == 4 else "approve", "fields": {}},
            answered_at=created + timedelta(seconds=10),
        )

    def seed_verdict(self, run_id: str, verdict: str) -> None:
        from brief_crew.events import FrameData, FrameKind, FrameLevel, UIEventType

        self.persistence.append_frames(
            run_id,
            [
                FrameData(
                    seq=1,
                    run_id=run_id,
                    ts=NOW - timedelta(hours=1),
                    kind=FrameKind.VERDICT,
                    event_type=UIEventType.WORKFLOW_END,
                    level=FrameLevel.INFO,
                    node_id="n3_verdict",
                    message="a verdict",
                    details={"verdict": verdict, "confidence": 0.7},
                )
            ],
        )

    def model_arms(self, node_id: str = "n1_agent") -> dict:
        return self.arms(f"&axis=model&node_id={node_id}")

    def arms(self, query: str = "") -> dict:
        body = self.admin_ok(
            f"/improve/compare?workflow_id={self.WORKFLOW}{query}"
        )
        return {arm["key"]: arm for arm in body["arms"]}

    def test_both_versions_come_back_as_arms(self) -> None:
        self.assertEqual({"3", "4"}, set(self.arms()))

    def test_every_arm_carries_the_six_measures_and_n(self) -> None:
        arm = self.arms()["3"]
        for key in (
            "n",
            "status_mix",
            "verdict_mix",
            "mean_confidence",
            "rating_mix",
            "gate_revise_rate",
            "median_duration_ms",
            "cost_per_run_usd",
        ):
            with self.subTest(key=key):
                self.assertIn(key, arm)
        self.assertEqual(6, arm["n"])

    def test_the_measures_differ_between_the_arms(self) -> None:
        """The control: two arms that read identically would satisfy every
        assertion above and answer nothing."""

        arms = self.arms()
        self.assertEqual({"VALIDATE": 6}, arms["3"]["verdict_mix"])
        self.assertEqual({"NEEDS_WORK": 2}, arms["4"]["verdict_mix"])
        self.assertEqual(0.0, arms["3"]["gate_revise_rate"])
        self.assertEqual(1.0, arms["4"]["gate_revise_rate"])
        self.assertEqual(6, arms["3"]["rating_mix"]["good"])
        self.assertEqual(2, arms["4"]["rating_mix"]["bad"])

    def test_the_short_arm_is_flagged_rather_than_hidden(self) -> None:
        arms = self.arms()
        self.assertFalse(arms["3"]["underpowered"])
        self.assertTrue(arms["4"]["underpowered"])

    def test_the_floor_is_the_constant_and_not_a_literal(self) -> None:
        with patch.object(config, "IMPROVE_MIN_COMPARE_RUNS", 2):
            self.assertFalse(self.arms()["4"]["underpowered"])

    def test_a_and_b_narrow_the_comparison_to_two_arms(self) -> None:
        self.seed("v5-0", version=5, verdict="REJECT", rating="unsure")
        self.assertEqual({"3", "4"}, set(self.arms("&a=3&b=4")))

    def test_a_run_with_no_resolvable_version_is_grouped_unknown(self) -> None:
        """Never merged into a numbered arm it might not belong to."""

        self.persistence.create_run(
            run_id="orphan",
            session_id="s",
            workflow_id=self.WORKFLOW,
            graph_version="a-hash-nothing-matches",
            inputs={},
            user_id=ADA.id,
            status="queued",
            created_at=NOW - timedelta(hours=2),
        )
        self.persistence.update_run_status("orphan", "completed")
        self.assertIn("unknown", self.arms())

    def test_the_model_axis_needs_a_node_id(self) -> None:
        """R4. Without it the arms measure which node happened to run on which
        tier, and the difference gets labelled a model effect."""

        response = self.admin_get(
            f"/improve/compare?workflow_id={self.WORKFLOW}&axis=model"
        )
        self.assertEqual(response.status_code, 422, response.text)
        self.assertIn("node_id", response.json()["detail"])

    def test_the_model_axis_groups_by_the_model_on_one_node(self) -> None:
        self.seed(
            "cheap-1",
            version=3,
            verdict="VALIDATE",
            rating="good",
            model=config.CHEAP_MODEL,
        )
        arms = self.model_arms()
        self.assertIn(config.CHEAP_MODEL, arms)
        self.assertIn(config.ESCALATION_MODEL, arms)
        self.assertEqual(1, arms[config.CHEAP_MODEL]["n"])

    def test_the_model_arms_are_disjoint(self) -> None:
        """R4. A run counted in both arms would inflate both, and every rate
        on the page would be a weighted average of itself."""

        self.seed(
            "cheap-1",
            version=3,
            verdict="VALIDATE",
            rating="good",
            model=config.CHEAP_MODEL,
        )
        arms = self.model_arms()
        self.assertEqual(9, sum(arm["n"] for arm in arms.values()))

    def test_a_node_that_ran_under_two_models_is_its_own_arm(self) -> None:
        """A fallback fired, or the node retried on a second tier.

        NAMED rather than dropped and rather than counted twice: the run is
        real evidence about something, and it is not evidence about either
        model alone.
        """

        self.seed("mixed-1", version=3, verdict="VALIDATE", rating="good")
        self.persistence.save_node_metrics(
            "mixed-1",
            "n1_agent",
            model=config.CHEAP_MODEL,
            cost_usd=Decimal("0.0100"),
            total_tokens=100,
            prompt_tokens=80,
            completion_tokens=20,
            call_count=1,
        )
        arms = self.model_arms()
        self.assertIn("mixed", arms)
        self.assertEqual(1, arms["mixed"]["n"])

    def test_the_model_arm_costs_only_the_node_it_names(self) -> None:
        """R4's money half, and the one that changes a decision.

        Every seeded run also spends on a second node. The whole run's cost
        would carry that second node into a figure labelled as one model's -
        which is the error that makes a cheap-tier experiment look like it
        saved nothing.
        """

        for run_id in (f"v3-{index}" for index in range(6)):
            self.persistence.save_node_metrics(
                run_id,
                "n9_elsewhere",
                model=config.ESCALATION_MODEL,
                cost_usd=Decimal("1.0000"),
                total_tokens=10,
                prompt_tokens=5,
                completion_tokens=5,
                call_count=1,
            )
        arm = self.model_arms()[config.ESCALATION_MODEL]
        # `n1_agent` alone: $0.05 a run. With the other node it would be $1.05.
        self.assertEqual(0.05, arm["cost_per_run_usd"])

    def test_the_version_arm_still_costs_the_whole_run(self) -> None:
        """The control for the assertion above: scoping is the MODEL axis's."""

        for run_id in (f"v3-{index}" for index in range(6)):
            self.persistence.save_node_metrics(
                run_id,
                "n9_elsewhere",
                model=config.ESCALATION_MODEL,
                cost_usd=Decimal("1.0000"),
                total_tokens=10,
                prompt_tokens=5,
                completion_tokens=5,
                call_count=1,
            )
        self.assertEqual(1.05, self.arms()["3"]["cost_per_run_usd"])

    def test_a_requested_arm_with_no_runs_is_shown_and_flagged(self) -> None:
        """D9. `arms: []` with no sentence lets a reader conclude the
        comparison could not be made; `n: 0, missing: true` is a fact."""

        arms = self.arms("&a=3&b=99")
        self.assertEqual({"3", "99"}, set(arms))
        self.assertEqual(0, arms["99"]["n"])
        self.assertTrue(arms["99"]["missing"])
        self.assertTrue(arms["99"]["underpowered"])

    def test_an_arm_that_has_runs_is_not_flagged_missing(self) -> None:
        """The control: a flag that is always true says nothing."""

        self.assertFalse(self.arms("&a=3&b=99")["3"]["missing"])

    def test_both_sides_missing_still_answers_two_arms(self) -> None:
        arms = self.arms("&a=98&b=99")
        self.assertEqual({"98", "99"}, set(arms))
        self.assertTrue(all(arm["missing"] for arm in arms.values()))

    def test_an_unrequested_arm_is_never_invented(self) -> None:
        """Only what the caller ASKED for: an empty arm nobody named would be
        a row about nothing."""

        self.assertNotIn("99", self.arms())

    def test_an_unknown_axis_is_422(self) -> None:
        response = self.admin_get(
            f"/improve/compare?workflow_id={self.WORKFLOW}&axis=phase-of-the-moon"
        )
        self.assertEqual(response.status_code, 422, response.text)

    def test_the_route_is_404_to_a_non_admin(self) -> None:
        with patch.object(config, "ADMIN_EMAILS", ()):
            response = self.admin_get(
                f"/improve/compare?workflow_id={self.WORKFLOW}"
            )
        self.assertEqual(response.status_code, 404, response.text)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
