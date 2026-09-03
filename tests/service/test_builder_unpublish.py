"""`POST /api/builder/workflows/{id}/unpublish` - round 2, D-15-10; decision 24.

Round 1 found the delete guard one save deep: it keyed on the HEAD's status,
and the 409's own remedy - "save a new version to return it to draft" -
returned the head to draft while the older version stayed registered, so the
next delete passed the guard and unregistered a graph that was still
answering launches. The guard now keys on the registration alone, and the
remedy it names is this route. Three things it must do, and one order:

* the row's status moves FIRST, then the registration - the boot sweep
  re-registers every row that says `published`, so the other order would let
  a crash between the two halves put the graph back into service on the next
  deploy (`autoDeploy: yes`);
* both halves of the registration go - `service/graph.py`'s maps and this
  application's runtime map - and the graph endpoint answers 404 afterwards;
* the same visibility as every other write: a stranger's document is 404, an
  unowned one is 403 naming Duplicate, nobody-at-all is 401.

The client half - the Unpublish item and the docked confirm's remedy - is in
`frontend/tests/documentLifecycle.spec.ts`.
"""

from __future__ import annotations

from typing import Any

from brief_crew.service.builder_rehydrate import rehydrate_published_workflows
from brief_crew.service.builder_runner import synthetic_builder_runner
from brief_crew.service.graph import builder_workflow
from tests.builder.test_compiler import straight_line
from tests.service.builder_auth import (
    ADA_TOKEN,
    GRACE_TOKEN,
    BuilderAuthCase,
    document_payload,
)
from tests.service.builder_registration import forget_builder_workflow


class UnpublishCase(BuilderAuthCase):
    def publish_as(self, token: str, document_id: str) -> dict[str, Any]:
        response = self.client.post(
            f"/api/builder/workflows/{document_id}/publish", headers=self.auth(token)
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.addCleanup(forget_builder_workflow, body["workflow_id"])
        return body

    def unpublish_as(self, token: str | None, document_id: str) -> Any:
        return self.client.post(
            f"/api/builder/workflows/{document_id}/unpublish",
            headers=self.auth(token) if token else {},
        )

    def graph_status(self, workflow_id: str) -> int:
        return self.client.get(
            f"/api/workflows/{workflow_id}/graph", headers=self.auth(ADA_TOKEN)
        ).status_code

    def versions(self, document_id: str) -> list[tuple[int, str]]:
        response = self.client.get(
            f"/api/builder/workflows/{document_id}/versions", headers=self.auth(ADA_TOKEN)
        )
        self.assertEqual(response.status_code, 200, response.text)
        return [(row["version"], row["status"]) for row in response.json()]


class TakingAGraphOutOfService(UnpublishCase):
    def test_the_head_returns_to_draft_and_the_answer_says_so(self) -> None:
        created = self.create_as(ADA_TOKEN)
        self.publish_as(ADA_TOKEN, created["id"])
        self.assertEqual(self.get_as(ADA_TOKEN, created["id"]).json()["status"], "published")

        response = self.unpublish_as(ADA_TOKEN, created["id"])

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["id"], created["id"])
        self.assertEqual(body["status"], "draft")
        self.assertFalse(body["published"])
        self.assertEqual(body["head_version"], 1)
        self.assertEqual(self.get_as(ADA_TOKEN, created["id"]).json()["status"], "draft")

    def test_both_halves_of_the_registration_go(self) -> None:
        created = self.create_as(ADA_TOKEN)
        published = self.publish_as(ADA_TOKEN, created["id"])
        workflow_id = published["workflow_id"]
        self.assertIsNotNone(builder_workflow(workflow_id))
        self.assertIn(workflow_id, self.app.state.run_registry.workflows)
        self.assertEqual(self.graph_status(workflow_id), 200)

        self.assertEqual(self.unpublish_as(ADA_TOKEN, created["id"]).status_code, 200)

        self.assertIsNone(builder_workflow(workflow_id))
        self.assertNotIn(workflow_id, self.app.state.run_registry.workflows)
        self.assertEqual(self.graph_status(workflow_id), 404)

    def test_the_version_list_shows_no_published_row_afterwards(self) -> None:
        created = self.create_as(ADA_TOKEN)
        self.publish_as(ADA_TOKEN, created["id"])
        self.assertEqual(self.versions(created["id"]), [(1, "published")])
        self.unpublish_as(ADA_TOKEN, created["id"])
        self.assertEqual(self.versions(created["id"]), [(1, "draft")])

    def test_an_older_registered_version_under_a_draft_head_is_taken_out_too(self) -> None:
        """The exact shape round 1 exploited: head edited after the publish."""

        created = self.create_as(ADA_TOKEN)
        published = self.publish_as(ADA_TOKEN, created["id"])
        saved = self.save_as(
            ADA_TOKEN, created["id"], document_payload(name="edited"), expected_version=1
        )
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(self.versions(created["id"]), [(2, "draft"), (1, "published")])

        response = self.unpublish_as(ADA_TOKEN, created["id"])

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "draft")
        self.assertIsNone(builder_workflow(published["workflow_id"]))
        self.assertEqual(self.versions(created["id"]), [(2, "draft"), (1, "draft")])

    def test_it_is_idempotent_and_a_never_published_draft_is_a_no_op(self) -> None:
        created = self.create_as(ADA_TOKEN)
        first = self.unpublish_as(ADA_TOKEN, created["id"])
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.json()["status"], "draft")
        self.publish_as(ADA_TOKEN, created["id"])
        self.assertEqual(self.unpublish_as(ADA_TOKEN, created["id"]).status_code, 200)
        again = self.unpublish_as(ADA_TOKEN, created["id"])
        self.assertEqual(again.status_code, 200, again.text)
        self.assertEqual(again.json()["status"], "draft")
        self.assertEqual(self.get_as(ADA_TOKEN, created["id"]).json()["head_version"], 1)

    def test_the_document_and_every_version_survive(self) -> None:
        created = self.create_as(ADA_TOKEN)
        self.save_as(ADA_TOKEN, created["id"], document_payload(name="two"), expected_version=1)
        self.publish_as(ADA_TOKEN, created["id"])
        self.unpublish_as(ADA_TOKEN, created["id"])
        self.assertEqual([v for v, _ in self.versions(created["id"])], [2, 1])
        self.assertEqual(self.get_as(ADA_TOKEN, created["id"], version=1).status_code, 200)

    def test_a_restart_does_not_put_it_back(self) -> None:
        """The reason the ROW moves and not only the maps: the boot sweep reads
        the row."""

        created = self.create_as(ADA_TOKEN)
        published = self.publish_as(ADA_TOKEN, created["id"])
        self.unpublish_as(ADA_TOKEN, created["id"])

        report = rehydrate_published_workflows(
            store=self.store(),
            registry=self.app.state.run_registry,
            runner_factory=synthetic_builder_runner,
        )

        self.assertEqual(report.registered, ())
        self.assertIsNone(builder_workflow(published["workflow_id"]))

    def test_it_can_be_republished_afterwards(self) -> None:
        created = self.create_as(ADA_TOKEN)
        self.publish_as(ADA_TOKEN, created["id"])
        self.unpublish_as(ADA_TOKEN, created["id"])
        again = self.publish_as(ADA_TOKEN, created["id"])
        self.assertEqual(self.graph_status(again["workflow_id"]), 200)
        self.assertEqual(self.get_as(ADA_TOKEN, created["id"]).json()["status"], "published")


class WhoMayUnpublish(UnpublishCase):
    def test_another_user_s_document_is_a_404_and_stays_live(self) -> None:
        created = self.create_as(ADA_TOKEN)
        published = self.publish_as(ADA_TOKEN, created["id"])
        refused = self.unpublish_as(GRACE_TOKEN, created["id"])
        self.assertEqual(refused.status_code, 404)
        self.assertEqual(refused.json(), {"detail": "document not found"})
        self.assertIsNotNone(builder_workflow(published["workflow_id"]))

    def test_an_anonymous_caller_is_refused(self) -> None:
        created = self.create_as(ADA_TOKEN)
        published = self.publish_as(ADA_TOKEN, created["id"])
        self.assertEqual(self.unpublish_as(None, created["id"]).status_code, 401)
        self.assertIsNotNone(builder_workflow(published["workflow_id"]))

    def test_an_unowned_document_is_a_403_naming_duplicate(self) -> None:
        unowned = self.store().create(straight_line()).id
        refused = self.unpublish_as(ADA_TOKEN, unowned)
        self.assertEqual(refused.status_code, 403, refused.text)
        self.assertIn("Duplicate", refused.json()["detail"])

    def test_an_unknown_document_is_a_404(self) -> None:
        self.assertEqual(self.unpublish_as(ADA_TOKEN, "ug_00000000").status_code, 404)
