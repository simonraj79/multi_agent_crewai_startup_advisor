"""Rating a run: three words, a note, and who is allowed (L3, L4, L5).

Plan 20 section 2.2, the Label step. Before this the application had no
post-hoc label at all: a gate reply says what a person accepted mid-run and a
guardrail says what a machine checked, and neither answers *was this run any
good*. Without that, a run is useful only to itself.

Four criteria:

* **L3** - three values and `null`; a fourth is 422 and a note over
  `MAX_RATING_NOTE_CHARS` is 422, both before the column; **another user's run
  is 404, not 403**; an unowned run is ratable by anyone; and **503** on a
  deployment with no durable store.
* **L4** - the admin lever rates somebody else's run, logs one `WARNING`
  naming the actor, and is 404 to a non-admin.
* **L5** - `GET /api/runs` rows and `GET /api/runs/{id}/rating` return what
  was stored. Its admin half is in `test_admin_aggregates.py`, where the rest
  of that list's contract lives.
* **L6** - the ROUTE calls the score hook, with the exporter's own trace id
  and the mapped value, and an exporter that is off or exploding still
  answers 200. What `record_run_score` itself does is
  `tests/observability/test_run_score_hook.py`'s; that the route calls it at
  all is this module's, because a green hook nothing calls is exactly what
  `resolve_billed_cost` turned out to be.
"""

from __future__ import annotations

import logging
import unittest
from unittest.mock import patch

from brief_crew import config
from brief_crew.service.auth import AuthenticatedUser, AuthError
from tests.service.identities import TEST_MASTER_KEY


ADA = AuthenticatedUser(id="user_ada", email="ada@example.test", name="Ada")
GRACE = AuthenticatedUser(id="user_grace", email="grace@example.test", name="Grace")
ADMIN = AuthenticatedUser(id="user_admin", email="admin@example.test", name="Admin")
TOKENS = {"ada-token": ADA, "grace-token": GRACE, "admin-token": ADMIN}
LAUNCH = {"workflow_id": "idea-validator", "inputs": {"idea": "a scheduling assistant"}}


class RatingCase(unittest.TestCase):
    """A synthetic app, three people, and nothing inherited from a shell."""

    admin_emails: tuple[str, ...] = ("admin@example.test",)

    def setUp(self) -> None:
        super().setUp()
        # The score hook is telemetry and every case here is about the write,
        # so it is pointed at nothing: `record_run_score` then returns False
        # and no thread is started. The hook has its own module,
        # `tests/observability/test_run_score_hook.py`.
        from brief_crew.observability import scores

        scores.set_score_exporter(None)

        def fake_verify(token: str, **_: object) -> AuthenticatedUser:
            try:
                return TOKENS[token]
            except KeyError as exc:
                raise AuthError("token is not valid") from exc

        for item in (
            patch.object(config, "AUTH_BASE_URL", "https://auth.example.test"),
            patch.object(config, "VALIDATOR_REQUIRE_AUTH", True),
            patch.object(config, "CREDENTIALS_MASTER_KEY", TEST_MASTER_KEY),
            patch.object(config, "ADMIN_EMAILS", self.admin_emails),
            patch("brief_crew.service.app.verify_token", fake_verify),
        ):
            item.start()
            self.addCleanup(item.stop)

        from fastapi.testclient import TestClient

        from brief_crew.service.app import create_app

        self.app = create_app(synthetic=True)
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)
        self.registry = self.app.state.run_registry

    def auth(self, token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    def launch_as(self, token: str) -> str:
        response = self.client.post(
            "/api/sessions/session-1/runs", json=LAUNCH, headers=self.auth(token)
        )
        self.assertEqual(response.status_code, 202, response.text)
        run_id = response.json()["run_id"]
        self.registry.wait(run_id, timeout=5)
        return run_id

    def rate(self, run_id: str, token: str, **body: object):
        return self.client.put(
            f"/api/runs/{run_id}/rating", json=body, headers=self.auth(token)
        )


class OwnerRatingTests(RatingCase):
    def setUp(self) -> None:
        super().setUp()
        self.run_id = self.launch_as("ada-token")

    def test_each_of_the_three_words_is_accepted(self) -> None:
        for word in ("good", "bad", "unsure"):
            with self.subTest(rating=word):
                response = self.rate(self.run_id, "ada-token", rating=word)
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(word, response.json()["rating"])

    def test_null_clears_the_rating_and_the_note_with_it(self) -> None:
        """A note about a rating that no longer exists is a sentence with no
        subject."""

        self.rate(self.run_id, "ada-token", rating="bad", note="the segment was wrong")
        cleared = self.rate(self.run_id, "ada-token", rating=None)
        self.assertEqual(cleared.status_code, 200, cleared.text)
        body = cleared.json()
        self.assertIsNone(body["rating"])
        self.assertIsNone(body["rating_note"])
        self.assertIsNone(body["rated_at"])

    def test_the_last_writer_wins_rather_than_409ing(self) -> None:
        """Deliberately not a compare-and-set - plan 20 section 2.1.

        Every other `UPDATE ... WHERE ...; rowcount` in `persistence.py` guards
        a state machine where two writers mean two outcomes. This guards one
        person's opinion of their own finished run, and a 409 on a double
        press would refuse with nothing to protect.
        """

        self.rate(self.run_id, "ada-token", rating="good")
        second = self.rate(self.run_id, "ada-token", rating="bad")
        self.assertEqual(second.status_code, 200)
        self.assertEqual("bad", second.json()["rating"])

    def test_a_fourth_word_is_422(self) -> None:
        response = self.rate(self.run_id, "ada-token", rating="excellent")
        self.assertEqual(response.status_code, 422, response.text)
        self.assertIn("good", response.text)

    def test_a_note_over_the_bound_is_422(self) -> None:
        response = self.rate(
            self.run_id,
            "ada-token",
            rating="good",
            note="x" * (config.MAX_RATING_NOTE_CHARS + 1),
        )
        self.assertEqual(response.status_code, 422, response.text)

    def test_a_note_exactly_at_the_bound_is_accepted(self) -> None:
        """The boundary in both directions; one alone proves the wrong thing."""

        note = "y" * config.MAX_RATING_NOTE_CHARS
        response = self.rate(self.run_id, "ada-token", rating="good", note=note)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(note, response.json()["rating_note"])

    def test_an_unknown_field_in_the_body_is_422(self) -> None:
        """`extra="forbid"`: a client sending `score` gets told, not ignored."""

        response = self.rate(self.run_id, "ada-token", rating="good", score=5)
        self.assertEqual(response.status_code, 422, response.text)

    def test_the_actor_is_recorded(self) -> None:
        response = self.rate(self.run_id, "ada-token", rating="good")
        self.assertEqual(ADA.id, response.json()["rated_by"])

    # -- L5 --------------------------------------------------------------

    def test_the_get_returns_what_was_stored(self) -> None:
        self.rate(self.run_id, "ada-token", rating="unsure", note="hard to say")
        body = self.client.get(
            f"/api/runs/{self.run_id}/rating", headers=self.auth("ada-token")
        ).json()
        self.assertEqual("unsure", body["rating"])
        self.assertEqual("hard to say", body["rating_note"])
        self.assertIsNotNone(body["rated_at"])

    def test_an_unrated_run_answers_nulls_rather_than_404(self) -> None:
        body = self.client.get(
            f"/api/runs/{self.run_id}/rating", headers=self.auth("ada-token")
        ).json()
        self.assertIsNone(body["rating"])
        self.assertEqual(self.run_id, body["run_id"])

    def test_the_history_rows_carry_the_rating(self) -> None:
        self.rate(self.run_id, "ada-token", rating="good", note="it cited everything")
        rows = self.client.get(
            "/api/runs", headers=self.auth("ada-token")
        ).json()["runs"]
        row = next(row for row in rows if row["run_id"] == self.run_id)
        self.assertEqual("good", row["rating"])
        self.assertEqual("it cited everything", row["rating_note"])
        self.assertIsNotNone(row["rated_at"])

    def test_an_unrated_history_row_carries_three_nulls(self) -> None:
        rows = self.client.get(
            "/api/runs", headers=self.auth("ada-token")
        ).json()["runs"]
        row = next(row for row in rows if row["run_id"] == self.run_id)
        self.assertIsNone(row["rating"])
        self.assertIsNone(row["rating_note"])
        self.assertIsNone(row["rated_at"])


class SomebodyElsesRunTests(RatingCase):
    """404, never 403 - a 403 confirms the run exists."""

    def setUp(self) -> None:
        super().setUp()
        self.run_id = self.launch_as("ada-token")

    def test_a_stranger_rating_it_is_404(self) -> None:
        response = self.rate(self.run_id, "grace-token", rating="bad")
        self.assertEqual(response.status_code, 404, response.text)
        self.assertNotIn("403", response.text)

    def test_a_stranger_reading_it_is_404(self) -> None:
        response = self.client.get(
            f"/api/runs/{self.run_id}/rating", headers=self.auth("grace-token")
        )
        self.assertEqual(response.status_code, 404)

    def test_the_refusal_reads_the_same_as_an_unknown_run(self) -> None:
        """The oracle test: the two answers must be indistinguishable."""

        stranger = self.rate(self.run_id, "grace-token", rating="bad")
        unknown = self.rate("no-such-run", "grace-token", rating="bad")
        self.assertEqual(unknown.status_code, stranger.status_code)
        self.assertEqual(unknown.json(), stranger.json())

    def test_a_stranger_did_not_change_the_rating(self) -> None:
        """The control: a 404 that had written anyway would pass the test above."""

        self.rate(self.run_id, "grace-token", rating="bad")
        body = self.client.get(
            f"/api/runs/{self.run_id}/rating", headers=self.auth("ada-token")
        ).json()
        self.assertIsNone(body["rating"])


class AdminLeverTests(RatingCase):
    """A10: the second door, and the WARNING that makes it a lever."""

    def setUp(self) -> None:
        super().setUp()
        self.run_id = self.launch_as("ada-token")

    def admin_rate(self, run_id: str, token: str, **body: object):
        return self.client.put(
            f"/api/admin/runs/{run_id}/rating",
            json=body,
            headers=self.auth(token),
        )

    def test_an_admin_rates_somebody_elses_run(self) -> None:
        with self.assertLogs("brief_crew.service.rating_api", level="WARNING"):
            response = self.admin_rate(self.run_id, "admin-token", rating="bad")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual("bad", response.json()["rating"])

    def test_the_warning_names_the_actor_and_the_run(self) -> None:
        with self.assertLogs(
            "brief_crew.service.rating_api", level="WARNING"
        ) as caught:
            self.admin_rate(self.run_id, "admin-token", rating="good")
        line = "\n".join(caught.output)
        self.assertIn(ADMIN.email, line)
        self.assertIn(self.run_id, line)

    def test_the_actor_recorded_is_the_admin_not_the_owner(self) -> None:
        """`rated_by` is who typed it. The owner is on the run already."""

        with self.assertLogs("brief_crew.service.rating_api", level="WARNING"):
            response = self.admin_rate(self.run_id, "admin-token", rating="bad")
        self.assertEqual(ADMIN.id, response.json()["rated_by"])

    def test_the_owner_can_see_what_the_admin_wrote(self) -> None:
        with self.assertLogs("brief_crew.service.rating_api", level="WARNING"):
            self.admin_rate(self.run_id, "admin-token", rating="bad", note="a lever")
        body = self.client.get(
            f"/api/runs/{self.run_id}/rating", headers=self.auth("ada-token")
        ).json()
        self.assertEqual("bad", body["rating"])
        self.assertEqual("a lever", body["rating_note"])

    def test_a_non_admin_gets_404_from_the_lever(self) -> None:
        logging.getLogger("brief_crew.service.rating_api").setLevel(logging.CRITICAL)
        self.addCleanup(
            logging.getLogger("brief_crew.service.rating_api").setLevel,
            logging.NOTSET,
        )
        response = self.admin_rate(self.run_id, "grace-token", rating="good")
        self.assertEqual(response.status_code, 404, response.text)

    def test_the_lever_reads_as_an_unknown_path_to_a_non_admin(self) -> None:
        """`require_admin`'s rule: the surface does not announce itself."""

        refused = self.admin_rate(self.run_id, "grace-token", rating="good")
        unknown = self.client.put(
            "/api/admin/no-such-route",
            json={"rating": "good"},
            headers=self.auth("grace-token"),
        )
        self.assertEqual(unknown.json(), refused.json())

    def test_an_unknown_run_is_404_even_for_an_admin(self) -> None:
        response = self.admin_rate("no-such-run", "admin-token", rating="good")
        self.assertEqual(response.status_code, 404, response.text)


class NoAuthDeploymentTests(unittest.TestCase):
    """An unowned run is ratable by anyone - the pre-auth carve-out.

    A separate app rather than a doctored row: with no `AUTH_BASE_URL` every
    run this service writes has `user_id = None`, which is the state a local
    checkout, `SYNTHETIC=1` and every row written before authentication
    existed are all in. Refusing those would make deploying this destroy the
    history it organises.
    """

    def setUp(self) -> None:
        from brief_crew.observability import scores

        scores.set_score_exporter(None)
        for item in (
            patch.object(config, "AUTH_BASE_URL", ""),
            patch.object(config, "VALIDATOR_REQUIRE_AUTH", False),
        ):
            item.start()
            self.addCleanup(item.stop)

        from fastapi.testclient import TestClient

        from brief_crew.service.app import create_app

        self.app = create_app(synthetic=True)
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)
        response = self.client.post("/api/sessions/session-1/runs", json=LAUNCH)
        self.assertEqual(response.status_code, 202, response.text)
        self.run_id = response.json()["run_id"]
        self.app.state.run_registry.wait(self.run_id, timeout=5)

    def test_an_unowned_run_is_ratable_with_no_token(self) -> None:
        response = self.client.put(
            f"/api/runs/{self.run_id}/rating", json={"rating": "good"}
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual("good", response.json()["rating"])

    def test_the_actor_is_null_when_nobody_is_signed_in(self) -> None:
        response = self.client.put(
            f"/api/runs/{self.run_id}/rating", json={"rating": "good"}
        )
        self.assertIsNone(response.json()["rated_by"])


class NoDurableStoreTests(RatingCase):
    """L3's last clause: 503, and the same sentence at both doors.

    A rating is the one thing on a finished run that is written and never
    computed, so a service with nowhere to keep it has to say so rather than
    answer 200 over a write that went nowhere. **503 and not 500**: the
    request is well formed and it would work on a deployment that has a store,
    which is the same distinction `RunAdmissionError` draws against
    `RunBusyError`.
    """

    def setUp(self) -> None:
        super().setUp()
        self.run_id = self.launch_as("ada-token")
        # Patched AFTER the launch, because a run has to exist for the refusal
        # to be about the store rather than about the run.
        patcher = patch.object(self.registry, "persistence", None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_the_owner_door_answers_503(self) -> None:
        response = self.rate(self.run_id, "ada-token", rating="good")
        self.assertEqual(response.status_code, 503, response.text)
        self.assertIn("durable store", response.text)

    def test_the_admin_door_answers_503_too(self) -> None:
        """One sentence, both doors - a second wording is a second contract."""

        owner = self.rate(self.run_id, "ada-token", rating="good")
        admin = self.client.put(
            f"/api/admin/runs/{self.run_id}/rating",
            json={"rating": "good"},
            headers=self.auth("admin-token"),
        )
        self.assertEqual(503, admin.status_code, admin.text)
        self.assertEqual(owner.json(), admin.json())

    def test_a_non_admin_still_gets_404_rather_than_503(self) -> None:
        """The gate runs BEFORE the store is looked at.

        A 503 from the admin path would tell a stranger the route is there and
        merely unavailable, which is exactly what `require_admin`'s 404 exists
        to deny - and a missing store must not become the thing that leaks it.
        """

        refused = self.client.put(
            f"/api/admin/runs/{self.run_id}/rating",
            json={"rating": "good"},
            headers=self.auth("grace-token"),
        )
        self.assertEqual(404, refused.status_code, refused.text)

    def test_the_read_answers_nulls_rather_than_failing(self) -> None:
        """A GET is not a write: with no store there is simply no rating."""

        body = self.client.get(
            f"/api/runs/{self.run_id}/rating", headers=self.auth("ada-token")
        )
        self.assertEqual(200, body.status_code, body.text)
        self.assertIsNone(body.json()["rating"])


class TheScoreHookIsCalledTests(RatingCase):
    """L6, at the route rather than at the hook.

    `tests/observability/test_run_score_hook.py` proves what
    `record_run_score` does; this proves the ROUTE calls it, with the trace id
    the exporter would use, the mapped value, and not at all on a clear. The
    two halves are separate on purpose: a green hook that nothing calls is the
    shape of defect the observability programme's own `resolve_billed_cost`
    turned out to be (CLAUDE.md section 17 defect 4).
    """

    def setUp(self) -> None:
        super().setUp()
        self.run_id = self.launch_as("ada-token")

    def rate_with_recording_exporter(self, capture_content: bool = False, **body):
        from brief_crew.observability import scores
        from brief_crew.observability.backend import RecordingBackend

        class Policy:
            def __init__(self) -> None:
                self.capture_content = capture_content

        class Exporter:
            def __init__(self, backend: object) -> None:
                self._backend = backend
                self.policy = Policy()

        backend = RecordingBackend()
        scores.set_score_exporter(Exporter(backend))
        self.addCleanup(scores.set_score_exporter, None)
        response = self.rate(self.run_id, "ada-token", **body)
        self.assertEqual(200, response.status_code, response.text)
        return backend

    def test_good_is_one_on_the_runs_own_trace(self) -> None:
        from brief_crew.observability.backend import trace_id_for

        backend = self.rate_with_recording_exporter(rating="good")
        self.assertEqual(1, len(backend.scores))
        written = backend.scores[0]
        self.assertEqual("human_rating", written.name)
        self.assertEqual(1, written.value)
        self.assertEqual("NUMERIC", written.data_type)
        self.assertEqual(trace_id_for(self.run_id), written.trace_id)

    def test_bad_is_zero_and_unsure_is_categorical(self) -> None:
        self.assertEqual(0, self.rate_with_recording_exporter(rating="bad").scores[0].value)
        unsure = self.rate_with_recording_exporter(rating="unsure").scores[0]
        self.assertEqual("CATEGORICAL", unsure.data_type)
        self.assertNotIsInstance(unsure.value, (int, float))

    def test_clearing_writes_no_score(self) -> None:
        """Langfuse has no "unset a score", so a clear is silence."""

        self.assertEqual([], self.rate_with_recording_exporter(rating=None).scores)

    def test_the_note_is_withheld_under_the_default_policy(self) -> None:
        backend = self.rate_with_recording_exporter(
            rating="bad", note="the segment was wrong"
        )
        self.assertIsNone(backend.scores[0].comment)

    def test_the_note_travels_only_when_capture_is_on(self) -> None:
        backend = self.rate_with_recording_exporter(
            capture_content=True, rating="bad", note="the segment was wrong"
        )
        self.assertEqual("the segment was wrong", backend.scores[0].comment)

    def test_an_exporter_that_is_off_still_answers_200(self) -> None:
        """Telemetry is never the reason a person's button reports a failure."""

        from brief_crew.observability import scores

        scores.set_score_exporter(None)
        response = self.rate(self.run_id, "ada-token", rating="good")
        self.assertEqual(200, response.status_code, response.text)
        self.assertEqual("good", response.json()["rating"])

    def test_an_exploding_backend_still_answers_200(self) -> None:
        from brief_crew.observability import scores

        class Exploding:
            def score(self, **_: object) -> None:
                raise RuntimeError("langfuse is down")

        class Policy:
            capture_content = False

        class Exporter:
            _backend = Exploding()
            policy = Policy()

        scores.set_score_exporter(Exporter())
        self.addCleanup(scores.set_score_exporter, None)
        response = self.rate(self.run_id, "ada-token", rating="good")
        self.assertEqual(200, response.status_code, response.text)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
