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
import threading
import time
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
        """A run that is WAITING at its first gate - deliberately not finished."""

        response = self.client.post(
            "/api/sessions/session-1/runs", json=LAUNCH, headers=self.auth(token)
        )
        self.assertEqual(response.status_code, 202, response.text)
        run_id = response.json()["run_id"]
        self.registry.wait(run_id, timeout=5)
        return run_id

    def finish_as(self, token: str | None = None) -> str:
        """A run driven through both gates to a TERMINAL status (D4).

        Answered for real rather than stamped on the record: the rating routes
        now refuse a run that has not finished, so a fixture that faked the
        status would be testing a state the service never produces.
        `test_auth_endpoints._finish_run_as` is where this shape came from.
        """

        headers = self.auth(token) if token else {}
        run_id = self.launch_as(token) if token else self.launch_anonymously()
        for _ in range(4):
            gate = self.client.get(
                f"/api/runs/{run_id}", headers=headers
            ).json()["pending_gate"]
            if gate is None:
                break
            self.client.post(
                f"/api/runs/{run_id}/gates/{gate['gate_id']}",
                json={"outcome": "approve", "fields": {}},
                headers=headers,
            )
            self.registry.wait(run_id, timeout=5)
        status = self.client.get(f"/api/runs/{run_id}", headers=headers).json()["status"]
        self.assertIn(status, ("completed", "failed", "cancelled"), status)
        return run_id

    def launch_anonymously(self) -> str:
        response = self.client.post("/api/sessions/session-1/runs", json=LAUNCH)
        self.assertEqual(response.status_code, 202, response.text)
        run_id = response.json()["run_id"]
        self.registry.wait(run_id, timeout=5)
        return run_id

    def rate(self, run_id: str, token: str, **body: object):
        return self.client.put(
            f"/api/runs/{run_id}/rating", json=body, headers=self.auth(token)
        )

    def admin_rate(self, run_id: str, token: str, **body: object):
        return self.client.put(
            f"/api/admin/runs/{run_id}/rating", json=body, headers=self.auth(token)
        )


class OwnerRatingTests(RatingCase):
    def setUp(self) -> None:
        super().setUp()
        self.run_id = self.finish_as("ada-token")

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
        self.run_id = self.finish_as("ada-token")

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
        self.run_id = self.finish_as("ada-token")

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
    """D6: an unowned run is written by its deployment's only author.

    A separate app rather than a doctored row: with no `AUTH_BASE_URL` every
    run this service writes has `user_id = None`, which is the state a local
    checkout, `SYNTHETIC=1` and every row written before authentication
    existed are all in. Refusing those would make deploying this destroy the
    history it organises - so here, where there is nobody else, the anonymous
    caller keeps the write. `IdentityOnAnUnownedRunTests` is the other half.
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
        self.registry = self.app.state.run_registry
        self.run_id = self._finish()

    def _finish(self) -> str:
        response = self.client.post("/api/sessions/session-1/runs", json=LAUNCH)
        self.assertEqual(response.status_code, 202, response.text)
        run_id = response.json()["run_id"]
        self.registry.wait(run_id, timeout=5)
        for _ in range(4):
            gate = self.client.get(f"/api/runs/{run_id}").json()["pending_gate"]
            if gate is None:
                break
            self.client.post(
                f"/api/runs/{run_id}/gates/{gate['gate_id']}",
                json={"outcome": "approve", "fields": {}},
            )
            self.registry.wait(run_id, timeout=5)
        return run_id

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


class IdentityOnAnUnownedRunTests(RatingCase):
    """D6's other half: a signed-in caller gets 403, and the admin door works.

    The builder-documents precedent (plan 15 round 2), applied to runs. **403
    and not 404**, which is the one place this repository's usual rule bends
    and it bends for a reason: an unowned run is READABLE by everybody
    already, so the caller is looking at the row while being refused, and a
    404 would contradict the page in front of them. The sentence names the
    remedy rather than the rule.
    """

    def setUp(self) -> None:
        super().setUp()
        # An auth-CONFIGURED app, with an unowned row - the pre-auth shape.
        # Written through the store rather than launched, because this app
        # stamps an owner on everything it launches, which is the point.
        self.run_id = self.finish_as("ada-token")
        from sqlalchemy import update

        from brief_crew.service.persistence import runs

        with self.registry.persistence._begin() as connection:
            connection.execute(
                update(runs).where(runs.c.id == self.run_id).values(user_id=None)
            )
        self.registry._records.pop(self.run_id, None)

    def test_a_signed_in_caller_is_refused_with_403_and_a_remedy(self) -> None:
        response = self.rate(self.run_id, "ada-token", rating="good")
        self.assertEqual(response.status_code, 403, response.text)
        self.assertIn("no owner", response.text)
        self.assertIn("admin", response.text)

    def test_the_refusal_wrote_nothing(self) -> None:
        """The control: a 403 that had written anyway would pass the test above."""

        self.rate(self.run_id, "ada-token", rating="good")
        body = self.client.get(
            f"/api/runs/{self.run_id}/rating", headers=self.auth("ada-token")
        ).json()
        self.assertIsNone(body["rating"])

    def test_reading_it_is_still_allowed(self) -> None:
        """D6 bounds the WRITE. An unowned run stays readable by everyone."""

        response = self.client.get(
            f"/api/runs/{self.run_id}/rating", headers=self.auth("grace-token")
        )
        self.assertEqual(response.status_code, 200, response.text)

    def test_the_admin_door_rates_it_normally(self) -> None:
        with self.assertLogs("brief_crew.service.rating_api", level="WARNING"):
            response = self.admin_rate(self.run_id, "admin-token", rating="bad")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual("bad", response.json()["rating"])

    def test_an_auth_configured_deployment_has_no_anonymous_writer(self) -> None:
        """The clause the ruling asked to be verified rather than assumed.

        With `VALIDATOR_REQUIRE_AUTH` on, `current_user` answers 401 before
        any of this runs - so the anonymous carve-out
        `NoAuthDeploymentTests` exercises cannot be reached here, and the 403
        above is the only answer a person can get.
        """

        response = self.client.put(
            f"/api/runs/{self.run_id}/rating", json={"rating": "good"}
        )
        self.assertEqual(response.status_code, 401, response.text)


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
        self.run_id = self.finish_as("ada-token")
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
        self.run_id = self.finish_as("ada-token")

    def arm(self, capture_content: bool = False):
        """One recording exporter for the whole test, so a SEQUENCE is visible."""

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
        return backend

    def rate_with_recording_exporter(self, capture_content: bool = False, **body):
        backend = self.arm(capture_content)
        response = self.rate(self.run_id, "ada-token", **body)
        self.assertEqual(200, response.status_code, response.text)
        return backend

    def score_id(self) -> str:
        from brief_crew.observability import scores
        from brief_crew.observability.backend import trace_id_for

        return f"{trace_id_for(self.run_id)}{scores.RATING_SCORE_ID_SUFFIX}"

    def tearDown(self) -> None:
        from brief_crew.observability import scores

        with scores._sweep_lock:
            for timer in scores._sweeps.values():
                timer.cancel()
            scores._sweeps.clear()
        super().tearDown()

    def test_good_is_the_word_on_the_runs_own_trace(self) -> None:
        from brief_crew.observability.backend import trace_id_for

        backend = self.rate_with_recording_exporter(rating="good")
        self.assertEqual(1, len(backend.scores))
        written = backend.scores[0]
        self.assertEqual("human_rating", written.name)
        self.assertEqual("good", written.value)
        self.assertEqual("CATEGORICAL", written.data_type)
        self.assertEqual(trace_id_for(self.run_id), written.trace_id)

    def test_every_word_goes_as_itself_and_as_one_type(self) -> None:
        for word in ("bad", "unsure"):
            with self.subTest(rating=word):
                written = self.rate_with_recording_exporter(rating=word).scores[0]
                self.assertEqual(word, written.value)
                self.assertEqual("CATEGORICAL", written.data_type)

    # -- D11 round 2: one id, upserted, and a write that never deletes ----

    def test_every_write_carries_the_one_deterministic_id(self) -> None:
        """Without an id, `create_score` APPENDS - the first defect."""

        self.assertEqual(
            self.score_id(),
            self.rate_with_recording_exporter(rating="good").scores[0].score_id,
        )

    def test_four_rapid_ratings_are_four_upserts_and_zero_deletes(self) -> None:
        """The measured failure, through the route: four PUTs inside eight
        seconds left TWO scores on a real trace, because the write's delete
        (a synchronous call) overtook its own queued create."""

        backend = self.arm()
        for word in ("good", "bad", "unsure", "good"):
            self.assertEqual(
                200, self.rate(self.run_id, "ada-token", rating=word).status_code
            )
        self.assertEqual([self.score_id()] * 4, [row.score_id for row in backend.scores])
        self.assertEqual(
            ["good", "bad", "unsure", "good"], [row.value for row in backend.scores]
        )
        self.assertEqual([], backend.deleted_scores, "a write deleted something")

    def test_clearing_deletes_once_now_and_arms_one_sweep(self) -> None:
        """A clear is the only delete, and it is issued twice: the immediate
        one can 404 against a create still in the SDK's queue."""

        from brief_crew.observability import scores

        backend = self.arm()
        self.rate(self.run_id, "ada-token", rating="good")
        backend.scores.clear()
        with patch.object(config, "RATING_SCORE_CLEAR_SWEEP_SECONDS", 3600.0):
            self.assertEqual(
                200, self.rate(self.run_id, "ada-token", rating=None).status_code
            )
        self.assertEqual([], backend.scores)
        self.assertEqual([self.score_id()], backend.deleted_scores)
        self.assertEqual(1, scores.pending_clear_sweeps())

    def test_the_armed_sweep_deletes_again_while_the_run_is_still_unrated(self) -> None:
        from brief_crew.observability import scores

        backend = self.arm()
        with patch.object(config, "RATING_SCORE_CLEAR_SWEEP_SECONDS", 3600.0):
            self.rate(self.run_id, "ada-token", rating=None)
        backend.deleted_scores.clear()
        timer = list(scores._sweeps.values())[0]
        timer.cancel()
        timer.function(**timer.kwargs)
        self.assertEqual([self.score_id()], backend.deleted_scores)

    def test_the_armed_sweep_does_nothing_once_somebody_re_rates(self) -> None:
        """The source of truth is the DATABASE, re-read at sweep time - a
        rating made four seconds after a clear must not vanish later."""

        from brief_crew.observability import scores

        backend = self.arm()
        with patch.object(config, "RATING_SCORE_CLEAR_SWEEP_SECONDS", 3600.0):
            self.rate(self.run_id, "ada-token", rating=None)
        timer = list(scores._sweeps.values())[0]
        timer.cancel()
        self.rate(self.run_id, "ada-token", rating="good")
        backend.deleted_scores.clear()
        timer.function(**timer.kwargs)
        self.assertEqual([], backend.deleted_scores, "it deleted a live rating")

    def test_a_backend_that_cannot_delete_does_not_fail_the_button(self) -> None:
        from brief_crew.observability import scores

        class Stubborn:
            def score(self, **_: object) -> None:
                return None

            def delete_score(self, _score_id: str) -> None:
                raise RuntimeError("langfuse said no")

        class Policy:
            capture_content = False

        class Exporter:
            _backend = Stubborn()
            policy = Policy()

        scores.set_score_exporter(Exporter())
        self.addCleanup(scores.set_score_exporter, None)
        self.assertEqual(
            200, self.rate(self.run_id, "ada-token", rating=None).status_code
        )

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


class OnlyAFinishedRunTests(RatingCase):
    """D4: a run that has not finished is a 409 at both doors.

    The plan's subject is a POST-HOC judgement of a finished run, and a run
    waiting at its scope gate has not produced the thing being judged. The
    terminal set is `registry.TERMINAL_STATUSES`, imported and not retyped -
    the same set the eviction sweep and the orphan recovery read.
    """

    def setUp(self) -> None:
        super().setUp()
        self.waiting = self.launch_as("ada-token")

    def test_the_status_really_is_non_terminal(self) -> None:
        """The control. Without it every assertion below could pass on a run
        that was finished and refused for some other reason."""

        from brief_crew.service.registry import TERMINAL_STATUSES

        self.assertNotIn(self.registry.require(self.waiting).status, TERMINAL_STATUSES)

    def test_the_owner_door_is_409_with_one_plain_sentence(self) -> None:
        response = self.rate(self.waiting, "ada-token", rating="good")
        self.assertEqual(409, response.status_code, response.text)
        self.assertEqual(
            "this run has not finished; rate it when it has",
            response.json()["detail"],
        )

    def test_the_admin_door_is_409_with_the_same_sentence(self) -> None:
        response = self.admin_rate(self.waiting, "admin-token", rating="bad")
        self.assertEqual(409, response.status_code, response.text)
        self.assertEqual(
            self.rate(self.waiting, "ada-token", rating="bad").json()["detail"],
            response.json()["detail"],
        )

    def test_clearing_a_run_that_never_finished_is_409_too(self) -> None:
        """Nothing can be there to clear, so the refusal is the same one."""

        self.assertEqual(409, self.rate(self.waiting, "ada-token", rating=None).status_code)

    def test_the_refusal_wrote_nothing(self) -> None:
        self.rate(self.waiting, "ada-token", rating="good")
        body = self.client.get(
            f"/api/runs/{self.waiting}/rating", headers=self.auth("ada-token")
        ).json()
        self.assertIsNone(body["rating"])

    def test_reading_a_running_runs_rating_is_still_fine(self) -> None:
        """D4 bounds the write. A GET on a live run answers four nulls."""

        response = self.client.get(
            f"/api/runs/{self.waiting}/rating", headers=self.auth("ada-token")
        )
        self.assertEqual(200, response.status_code, response.text)

    def test_the_same_run_is_ratable_once_it_finishes(self) -> None:
        """The other control: a 409 that never lifts would be a broken feature
        rather than a guard. The SAME run, answered through to the end - not a
        second launch, which the $1 account cap would refuse."""

        for _ in range(4):
            gate = self.client.get(
                f"/api/runs/{self.waiting}", headers=self.auth("ada-token")
            ).json()["pending_gate"]
            if gate is None:
                break
            self.client.post(
                f"/api/runs/{self.waiting}/gates/{gate['gate_id']}",
                json={"outcome": "approve", "fields": {}},
                headers=self.auth("ada-token"),
            )
            self.registry.wait(self.waiting, timeout=5)
        self.assertEqual(
            200, self.rate(self.waiting, "ada-token", rating="good").status_code
        )


class NoteSanitisingTests(RatingCase):
    """D2: a control character in a note was a 500, and logged the note."""

    def setUp(self) -> None:
        super().setUp()
        self.run_id = self.finish_as("ada-token")

    def test_a_nul_in_the_note_is_stripped_rather_than_crashing(self) -> None:
        """psycopg cannot store a NUL in a `text` value at all: the driver
        raised, the route answered 500, and the traceback wrote the note - user
        content - into the server log."""

        response = self.rate(self.run_id, "ada-token", rating="bad", note="a\x00b")
        self.assertEqual(200, response.status_code, response.text)
        self.assertEqual("ab", response.json()["rating_note"])

    def test_every_control_character_goes_not_just_nul(self) -> None:
        response = self.rate(
            self.run_id, "ada-token", rating="bad", note="a\x01b\x07c\x1bd"
        )
        self.assertEqual(200, response.status_code, response.text)
        self.assertEqual("abcd", response.json()["rating_note"])

    def test_newlines_and_tabs_survive(self) -> None:
        """Somebody typing a two-line note is doing the thing this field is
        for."""

        note = "the market branch found nothing\n\tand the report cited it anyway"
        response = self.rate(self.run_id, "ada-token", rating="bad", note=note)
        self.assertEqual(200, response.status_code, response.text)
        self.assertEqual(note, response.json()["rating_note"])

    def test_a_note_of_only_control_characters_becomes_none(self) -> None:
        response = self.rate(self.run_id, "ada-token", rating="bad", note="\x00\x01\x02")
        self.assertEqual(200, response.status_code, response.text)
        self.assertIsNone(response.json()["rating_note"])

    def test_the_note_is_in_no_log_line(self) -> None:
        """The half of D2 that is about disclosure rather than about a 500."""

        with self.assertLogs(level="DEBUG") as caught:
            logging.getLogger("brief_crew").debug("a line, so assertLogs has one")
            self.rate(
                self.run_id, "ada-token", rating="bad", note="MY SECRET NOTE\x00"
            )
            self.admin_rate(
                self.run_id, "admin-token", rating="bad", note="MY SECRET NOTE"
            )
        self.assertNotIn("MY SECRET NOTE", "\n".join(caught.output))

    def test_the_length_is_re_checked_after_stripping(self) -> None:
        """`max_length` ran BEFORE this validator, so a note made of control
        characters could otherwise arrive as an empty string that had been
        refused - or a long one slip through by being padded."""

        long_note = "y" * config.MAX_RATING_NOTE_CHARS + "\x00" * 50
        response = self.rate(self.run_id, "ada-token", rating="good", note=long_note)
        self.assertEqual(200, response.status_code, response.text)
        self.assertEqual(
            config.MAX_RATING_NOTE_CHARS, len(response.json()["rating_note"])
        )


class EmptyRatingStringTests(RatingCase):
    """D7: only JSON `null` clears; `""` is a 422."""

    def setUp(self) -> None:
        super().setUp()
        self.run_id = self.finish_as("ada-token")

    def test_an_empty_string_is_422_and_not_a_silent_clear(self) -> None:
        self.rate(self.run_id, "ada-token", rating="good")
        for value in ("", "   ", "\t"):
            with self.subTest(rating=value):
                response = self.rate(self.run_id, "ada-token", rating=value)
                self.assertEqual(422, response.status_code, response.text)
        body = self.client.get(
            f"/api/runs/{self.run_id}/rating", headers=self.auth("ada-token")
        ).json()
        self.assertEqual("good", body["rating"], "the empty string cleared it")

    def test_null_still_clears(self) -> None:
        self.rate(self.run_id, "ada-token", rating="good")
        self.assertIsNone(
            self.rate(self.run_id, "ada-token", rating=None).json()["rating"]
        )

    def test_the_admin_door_agrees(self) -> None:
        self.assertEqual(
            422, self.admin_rate(self.run_id, "admin-token", rating="").status_code
        )


class AnUnusableRunIdTests(RatingCase):
    """A >128-character id was a 500 on these routes; it is a 404 now.

    `persistence._identifier` raises above 128 characters, and a shape
    question must not become a server fault. **The sibling run routes
    (`/api/runs/{id}`, `/state`, `/frames`) have the same hole and are
    deliberately left alone** - they are not this plan's surface, and a guard
    added to them here would be an unreviewed change to routes nobody asked
    about.
    """

    def test_both_doors_answer_404_rather_than_500(self) -> None:
        long_id = "x" * 300
        self.assertEqual(404, self.rate(long_id, "ada-token", rating="good").status_code)
        self.assertEqual(
            404, self.admin_rate(long_id, "admin-token", rating="good").status_code
        )
        self.assertEqual(
            404,
            self.client.get(
                f"/api/runs/{long_id}/rating", headers=self.auth("ada-token")
            ).status_code,
        )


class TheLoopIsNotParkedTests(RatingCase):
    """D1: the write blocks, so it is handed to the threadpool - audit H5.

    Measured before the fix: a concurrent `GET /healthz` took **2.012 s**
    against 0.112 s, because both `async def` handlers made a synchronous
    database round trip and then joined `record_run_rating`'s bounded 2 s
    worker ON the event loop.

    A `TestClient` used as a context manager runs ONE event loop for its
    lifetime - which is the whole question here. Used per request it spins a
    fresh portal each time and two separate loops could not show this either
    way; `test_tools_endpoint`'s H5 test makes the same note.
    """

    SLEEP_SECONDS = 1.0
    #: Well under the sleep, and far above what an in-process GET costs.
    RESPONSIVE_SECONDS = 0.5

    def setUp(self) -> None:
        super().setUp()
        self.run_id = self.finish_as("ada-token")

    def _slow_exporter(self, started: threading.Event):
        from brief_crew.observability import scores

        sleep_for = self.SLEEP_SECONDS

        class Slow:
            def score(self, **_: object) -> None:
                started.set()
                time.sleep(sleep_for)

            def delete_score(self, _score_id: str) -> None:
                return None

        class Policy:
            capture_content = False

        class Exporter:
            _backend = Slow()
            policy = Policy()

        scores.set_score_exporter(Exporter())
        self.addCleanup(scores.set_score_exporter, None)

    def test_a_concurrent_request_is_served_while_a_rating_is_being_written(
        self,
    ) -> None:
        from fastapi.testclient import TestClient

        started = threading.Event()
        self._slow_exporter(started)
        with TestClient(self.app) as client:
            outcome: list[object] = []

            def rate() -> None:
                outcome.append(
                    client.put(
                        f"/api/runs/{self.run_id}/rating",
                        json={"rating": "good"},
                        headers=self.auth("ada-token"),
                    )
                )

            worker = threading.Thread(target=rate, daemon=True)
            worker.start()
            self.assertTrue(started.wait(timeout=10), "the score was never attempted")
            began = time.monotonic()
            health = client.get("/healthz")
            elapsed = time.monotonic() - began
            worker.join(timeout=30)

        self.assertEqual(200, health.status_code, health.text)
        self.assertLess(
            elapsed,
            self.RESPONSIVE_SECONDS,
            f"the loop was parked: GET /healthz took {elapsed:.2f}s while one "
            f"rating held the score backend for {self.SLEEP_SECONDS}s",
        )
        self.assertEqual(200, outcome[0].status_code, outcome[0].text)

    def test_the_admin_door_is_off_the_loop_too(self) -> None:
        from fastapi.testclient import TestClient

        started = threading.Event()
        self._slow_exporter(started)
        with TestClient(self.app) as client:
            outcome: list[object] = []

            def rate() -> None:
                outcome.append(
                    client.put(
                        f"/api/admin/runs/{self.run_id}/rating",
                        json={"rating": "bad"},
                        headers=self.auth("admin-token"),
                    )
                )

            logging.getLogger("brief_crew.service.rating_api").setLevel(logging.CRITICAL)
            self.addCleanup(
                logging.getLogger("brief_crew.service.rating_api").setLevel,
                logging.NOTSET,
            )
            worker = threading.Thread(target=rate, daemon=True)
            worker.start()
            self.assertTrue(started.wait(timeout=10), "the score was never attempted")
            began = time.monotonic()
            health = client.get("/healthz")
            elapsed = time.monotonic() - began
            worker.join(timeout=30)

        self.assertEqual(200, health.status_code, health.text)
        self.assertLess(elapsed, self.RESPONSIVE_SECONDS, f"{elapsed:.2f}s")
        self.assertEqual(200, outcome[0].status_code, outcome[0].text)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
