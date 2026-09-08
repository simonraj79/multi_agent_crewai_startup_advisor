"""The two levers, on ANOTHER person's row, logged (plan 17 criterion 12).

PLANS.md decision 29 says yes to both, on the grounds that cancelling a run
and unpublishing a graph are the only two things that stop spend without a
redeploy. What that decision does NOT license is a second implementation: both
reach the same `registry.cancel` and the same `store.mark_unpublished` +
`unregister_builder_workflow` the owner-scoped routes reach, with
`require_own_run` replaced by `require_admin` and nothing else changed.

Four things are asserted for each lever, and the third is the one that makes
the decision reviewable after the fact:

1. it works on a row the admin does not own;
2. it reaches the same call the owner-scoped route reaches;
3. it emits exactly one `WARNING` naming the ACTOR's e-mail and the target -
   the run's own row records only that it was cancelled, so without this
   there is nothing anywhere saying who did it;
4. a non-admin gets the 404, on both.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from tests.builder.test_compiler import straight_line
from tests.service.admin_fixtures import ADMIN, ALICE, AdminCase
from tests.service.builder_registration import BuilderRegistrationCleanup


class CancelLeverTests(AdminCase):
    def test_an_admin_cancels_a_run_they_do_not_own(self) -> None:
        record = self.registry.create_run(
            session_id="s1",
            workflow_id="idea-validator",
            inputs={"idea": "a scheduling assistant for clinics"},
            user_id=ALICE.id,
        )
        with self.assertLogs("brief_crew.service.admin_api", level="WARNING") as logs:
            response = self.client.post(
                f"/api/admin/runs/{record.run_id}/cancel", headers=self.as_admin()
            )
        self.assertEqual(response.status_code, 202, response.text)
        body = response.json()
        self.assertEqual(body["run_id"], record.run_id)
        self.assertEqual(
            set(body), {"run_id", "status", "effect", "eta_hint"}
        )
        # Criterion 12's audit line: the ACTOR, and the target.
        self.assertEqual(len(logs.output), 1)
        self.assertIn(ADMIN.email, logs.output[0])
        self.assertIn(record.run_id, logs.output[0])
        self.assertIn(ALICE.id, logs.output[0])

    def test_it_reaches_registry_cancel_and_no_second_path(self) -> None:
        """The same call `/api/runs/{id}/cancel` makes, asserted by patching it.

        A second cancellation path would be a second set of statuses, a second
        sentence and a second chance to leave a run half-stopped.
        """

        record = self.registry.create_run(
            session_id="s1",
            workflow_id="idea-validator",
            inputs={"idea": "an idea"},
            user_id=ALICE.id,
        )
        answer = {
            "run_id": record.run_id,
            "status": "cancelling",
            "effect": "asked the run to stop at its next checkpoint",
            "eta_hint": "seconds",
        }
        with patch.object(
            self.registry, "cancel", return_value=answer
        ) as cancel, self.assertLogs("brief_crew.service.admin_api", level="WARNING"):
            response = self.client.post(
                f"/api/admin/runs/{record.run_id}/cancel", headers=self.as_admin()
            )
        self.assertEqual(response.status_code, 202, response.text)
        cancel.assert_called_once_with(record.run_id)

    def test_an_unknown_run_is_404(self) -> None:
        response = self.client.post(
            "/api/admin/runs/no-such-run/cancel", headers=self.as_admin()
        )
        self.assertEqual(response.status_code, 404, response.text)

    def test_a_non_admin_is_refused_and_nothing_is_cancelled(self) -> None:
        record = self.registry.create_run(
            session_id="s1",
            workflow_id="idea-validator",
            inputs={"idea": "an idea"},
            user_id=ALICE.id,
        )
        with patch.object(self.registry, "cancel") as cancel:
            response = self.client.post(
                f"/api/admin/runs/{record.run_id}/cancel", headers=self.as_alice()
            )
        self.assertEqual(response.status_code, 404, response.text)
        self.assertEqual(response.json(), {"detail": "Not Found"})
        cancel.assert_not_called()


class UnpublishLeverTests(AdminCase, BuilderRegistrationCleanup):
    """Alice publishes a graph; the admin takes it out of service."""

    def publish_as_alice(self) -> tuple[str, str]:
        created = self.client.post(
            "/api/builder/workflows",
            json={"document": _wire(straight_line())},
            headers=self.as_alice(),
        )
        self.assertEqual(created.status_code, 201, created.text)
        document_id = created.json()["document"]["id"]
        published = self.client.post(
            f"/api/builder/workflows/{document_id}/publish", headers=self.as_alice()
        )
        self.assertEqual(published.status_code, 200, published.text)
        workflow_id = published.json()["workflow_id"]
        self.track(workflow_id)
        return document_id, workflow_id

    def test_an_admin_unpublishes_somebody_elses_graph(self) -> None:
        from brief_crew.service.graph import builder_workflow

        document_id, workflow_id = self.publish_as_alice()
        self.assertIsNotNone(builder_workflow(workflow_id))

        with self.assertLogs("brief_crew.service.admin_api", level="WARNING") as logs:
            response = self.client.post(
                f"/api/admin/workflows/{document_id}/unpublish", headers=self.as_admin()
            )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "draft")
        # Both halves: the row, and the registration.
        self.assertIsNone(builder_workflow(workflow_id))
        self.assertEqual(len(logs.output), 1)
        self.assertIn(ADMIN.email, logs.output[0])
        self.assertIn(document_id, logs.output[0])
        self.assertIn(ALICE.id, logs.output[0])

    def test_the_owner_still_sees_their_own_document_afterwards(self) -> None:
        """An admin unpublishing is not an admin taking the row.

        `mark_unpublished` is passed the DOCUMENT'S owner, not the admin, so
        the store's ownership check runs and still means what it says - and
        Alice's document is still Alice's.
        """

        document_id, _workflow_id = self.publish_as_alice()
        self.client.post(
            f"/api/admin/workflows/{document_id}/unpublish", headers=self.as_admin()
        )
        mine = self.client.get(
            f"/api/builder/workflows/{document_id}", headers=self.as_alice()
        )
        self.assertEqual(mine.status_code, 200, mine.text)
        self.assertEqual(mine.json()["status"], "draft")

    def test_it_is_idempotent(self) -> None:
        """A graph that was never published answers 200 with nothing changed -
        the author asked for a state, and that is the state."""

        document_id, _workflow_id = self.publish_as_alice()
        first = self.client.post(
            f"/api/admin/workflows/{document_id}/unpublish", headers=self.as_admin()
        )
        second = self.client.post(
            f"/api/admin/workflows/{document_id}/unpublish", headers=self.as_admin()
        )
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200, second.text)
        self.assertEqual(second.json()["status"], "draft")

    def test_an_unknown_document_is_the_constant_404(self) -> None:
        """The CONSTANT, not a sentence about documents.

        An admin route answering "no such document" in different words from
        the 404 `require_admin` writes would be a way to tell an admin route
        apart from an unknown path - which is the one thing the gate exists to
        deny.
        """

        response = self.client.post(
            "/api/admin/workflows/ug_0123abcd/unpublish", headers=self.as_admin()
        )
        self.assertEqual(response.status_code, 404, response.text)
        self.assertEqual(response.json(), {"detail": "Not Found"})

    def test_a_non_admin_is_refused_and_the_graph_stays_live(self) -> None:
        from brief_crew.service.graph import builder_workflow

        document_id, workflow_id = self.publish_as_alice()
        response = self.client.post(
            f"/api/admin/workflows/{document_id}/unpublish", headers=self.as_alice()
        )
        self.assertEqual(response.status_code, 404, response.text)
        self.assertIsNotNone(builder_workflow(workflow_id))


def _wire(document: object) -> dict:
    """A `BuilderDocument` as the browser posts it - `schema`, not `document_schema`."""

    import json

    return json.loads(document.model_dump_json())  # type: ignore[attr-defined]


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
