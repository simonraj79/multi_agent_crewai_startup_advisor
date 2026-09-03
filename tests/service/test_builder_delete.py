"""`DELETE /api/builder/workflows/{id}` - plan 15 D3, criterion 5's server half.

Two things the route has to get right and one thing it has to refuse:

* the row goes WITH its versions and its saved test inputs. Both child tables
  carry `ON DELETE CASCADE`, and SQLite honours neither without a pragma this
  service never sets, so `store.delete` deletes them by name. The assertion is
  a row count in SQL rather than a 404 from the API, because a 404 would also
  be the answer if only the head had gone.
* a draft that still has an OLDER version registered is unregistered on the
  way out - the graph must not stay launchable after its document is gone.
* a document with ANY version registered on this service is refused with a
  **409** (PLANS.md decision 24, S1 ruling 10). Deleting it would take the
  graph out of the registration maps and the row out of the table in one
  request - the one shape the boot sweep can never put back. The sentence says
  what to do instead, in the words the docked confirm uses: unpublish it
  first, then delete it. Round 1 (D-15-10) found the guard one save deep - it
  keyed on the HEAD's status, and its own remedy ("save a new version") turned
  the head to draft while the older version stayed registered, so the next
  delete unregistered a live graph. `test_builder_unpublish.py` is the route
  the remedy now names.

The UI half - the confirm inside the docked rail - is criterion 5's other half
and belongs to `s1/15-ui`.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import func, insert, select

from brief_crew.service.graph import builder_workflow
from brief_crew.service.persistence import (
    builder_document_versions,
    builder_documents,
    builder_test_inputs,
    utcnow,
)
from tests.builder.test_compiler import straight_line
from tests.service.builder_auth import (
    ADA_TOKEN,
    GRACE_TOKEN,
    BuilderAuthCase,
    document_payload,
)
from tests.service.builder_registration import forget_builder_workflow


class DeleteCase(BuilderAuthCase):
    def delete_as(self, token: str | None, document_id: str) -> Any:
        return self.client.delete(
            f"/api/builder/workflows/{document_id}",
            headers=self.auth(token) if token else {},
        )

    def publish_as(self, token: str, document_id: str) -> dict[str, Any]:
        response = self.client.post(
            f"/api/builder/workflows/{document_id}/publish", headers=self.auth(token)
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.addCleanup(forget_builder_workflow, body["workflow_id"])
        return body

    def counts(self, document_id: str) -> tuple[int, int, int]:
        """(heads, versions, test inputs) for one document id, straight from SQL."""

        persistence = self.app.state.run_registry.persistence
        with persistence.connect() as connection:
            heads = connection.execute(
                select(func.count()).select_from(builder_documents).where(
                    builder_documents.c.id == document_id
                )
            ).scalar_one()
            versions = connection.execute(
                select(func.count()).select_from(builder_document_versions).where(
                    builder_document_versions.c.document_id == document_id
                )
            ).scalar_one()
            inputs = connection.execute(
                select(func.count()).select_from(builder_test_inputs).where(
                    builder_test_inputs.c.document_id == document_id
                )
            ).scalar_one()
        return int(heads), int(versions), int(inputs)

    def seed_test_input(self, document_id: str, *, user_id: str = "user_ada") -> None:
        """A plan-13 row keyed by this document, written the way its route will."""

        persistence = self.app.state.run_registry.persistence
        now = utcnow()
        with persistence.begin() as connection:
            connection.execute(
                insert(builder_test_inputs).values(
                    id=f"ti_{document_id[3:]}",
                    user_id=user_id,
                    document_id=document_id,
                    label="clinic scheduling",
                    inputs={"idea": "a scheduling assistant for clinics"},
                    node_mocks=None,
                    created_at=now,
                    updated_at=now,
                )
            )


class DraftDeletion(DeleteCase):
    def test_the_head_and_every_version_are_gone(self) -> None:
        """Criterion 5: the row and its versions."""

        created = self.create_as(ADA_TOKEN)
        saved = self.save_as(
            ADA_TOKEN, created["id"], document_payload(name="v2"), expected_version=1
        )
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(self.counts(created["id"]), (1, 2, 0))

        response = self.delete_as(ADA_TOKEN, created["id"])

        self.assertEqual(response.status_code, 204, response.text)
        self.assertEqual(response.content, b"")
        self.assertEqual(self.counts(created["id"]), (0, 0, 0))
        self.assertEqual(self.get_as(ADA_TOKEN, created["id"]).status_code, 404)
        self.assertEqual(self.list_ids_as(ADA_TOKEN), [])

    def test_saved_test_inputs_go_with_the_document(self) -> None:
        """The explicit cascade, because SQLite would otherwise orphan them."""

        created = self.create_as(ADA_TOKEN)
        self.seed_test_input(created["id"])
        self.assertEqual(self.counts(created["id"]), (1, 1, 1))
        self.assertEqual(self.delete_as(ADA_TOKEN, created["id"]).status_code, 204)
        self.assertEqual(self.counts(created["id"]), (0, 0, 0))

    def test_other_documents_are_untouched(self) -> None:
        keep = self.create_as(ADA_TOKEN)
        self.seed_test_input(keep["id"])
        gone = self.create_as(ADA_TOKEN)
        self.assertEqual(self.delete_as(ADA_TOKEN, gone["id"]).status_code, 204)
        self.assertEqual(self.counts(keep["id"]), (1, 1, 1))
        self.assertEqual(self.list_ids_as(ADA_TOKEN), [keep["id"]])

    def test_deleting_twice_is_a_404_the_second_time(self) -> None:
        created = self.create_as(ADA_TOKEN)
        self.assertEqual(self.delete_as(ADA_TOKEN, created["id"]).status_code, 204)
        self.assertEqual(self.delete_as(ADA_TOKEN, created["id"]).status_code, 404)


class PublishedDeletion(DeleteCase):
    def test_a_published_and_registered_head_is_refused_with_409(self) -> None:
        """Criterion 5: 409 while published-and-registered; nothing changes."""

        created = self.create_as(ADA_TOKEN)
        published = self.publish_as(ADA_TOKEN, created["id"])
        self.assertIsNotNone(builder_workflow(published["workflow_id"]))

        response = self.delete_as(ADA_TOKEN, created["id"])

        self.assertEqual(response.status_code, 409, response.text)
        detail = response.json()["detail"]
        self.assertIn("published", detail)
        # D-15-10: the remedy is one the server honours, in the docked
        # confirm's own words.
        self.assertIn("cannot be deleted; unpublish it first, then delete it", detail)
        self.assertNotIn("save a new version", detail)
        self.assertIn(created["id"], detail)
        # Still there, still launchable, still published.
        self.assertEqual(self.counts(created["id"]), (1, 1, 0))
        self.assertIsNotNone(builder_workflow(published["workflow_id"]))
        self.assertIn(published["workflow_id"], self.app.state.run_registry.workflows)
        self.assertEqual(self.get_as(ADA_TOKEN, created["id"]).json()["status"], "published")

    def test_a_save_does_not_make_a_registered_graph_deletable(self) -> None:
        """D-15-10: the guard was one save deep, and this is the save.

        Before round 2 this test asserted the opposite - that a save returned
        the head to draft and the delete then went through - and it was green
        while the delete unregistered a still-launchable v1. The registered
        version is what the guard keys on now; the head's status is not.
        """

        created = self.create_as(ADA_TOKEN)
        published = self.publish_as(ADA_TOKEN, created["id"])
        saved = self.save_as(
            ADA_TOKEN, created["id"], document_payload(name="edited"), expected_version=1
        )
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(saved.json()["status"], "draft")
        # The older version is still the one registered and still launchable.
        self.assertIsNotNone(builder_workflow(published["workflow_id"]))
        graph = self.client.get(
            f"/api/workflows/{published['workflow_id']}/graph", headers=self.auth(ADA_TOKEN)
        )
        self.assertEqual(graph.status_code, 200, graph.text)

        response = self.delete_as(ADA_TOKEN, created["id"])

        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn("v1 is registered", response.json()["detail"])
        self.assertIn("unpublish it first, then delete it", response.json()["detail"])
        self.assertEqual(self.counts(created["id"]), (1, 2, 0))
        self.assertIsNotNone(builder_workflow(published["workflow_id"]))
        self.assertEqual(
            self.client.get(
                f"/api/workflows/{published['workflow_id']}/graph", headers=self.auth(ADA_TOKEN)
            ).status_code,
            200,
        )

    def test_unpublish_then_delete_removes_the_row_and_the_registration(self) -> None:
        """The recipe the 409 now names, followed to the end."""

        created = self.create_as(ADA_TOKEN)
        published = self.publish_as(ADA_TOKEN, created["id"])
        unpublished = self.client.post(
            f"/api/builder/workflows/{created['id']}/unpublish", headers=self.auth(ADA_TOKEN)
        )
        self.assertEqual(unpublished.status_code, 200, unpublished.text)
        self.assertIsNone(builder_workflow(published["workflow_id"]))

        response = self.delete_as(ADA_TOKEN, created["id"])

        self.assertEqual(response.status_code, 204, response.text)
        self.assertEqual(self.counts(created["id"]), (0, 0, 0))
        self.assertNotIn(published["workflow_id"], self.app.state.run_registry.workflows)
        self.assertEqual(
            self.client.get(
                f"/api/workflows/{published['workflow_id']}/graph", headers=self.auth(ADA_TOKEN)
            ).status_code,
            404,
        )

    def test_a_published_row_this_process_never_registered_deletes(self) -> None:
        """The boot sweep skips a row that no longer compiles; that row is
        published in the table and registered nowhere, and it must be
        deletable or the author is stuck with a graph they cannot run or
        remove."""

        stored = self.store().create(straight_line(), user_id="user_ada")
        self.store().mark_published(stored.id, stored.document.version, user_id="user_ada")
        self.assertIsNone(builder_workflow(stored.id))
        self.assertEqual(self.get_as(ADA_TOKEN, stored.id).json()["status"], "published")

        response = self.delete_as(ADA_TOKEN, stored.id)

        self.assertEqual(response.status_code, 204, response.text)
        self.assertEqual(self.counts(stored.id), (0, 0, 0))


class SomebodyElsesDocument(DeleteCase):
    def test_another_user_s_document_is_a_404_and_stays(self) -> None:
        created = self.create_as(ADA_TOKEN)
        response = self.delete_as(GRACE_TOKEN, created["id"])
        self.assertEqual(response.status_code, 404, response.text)
        self.assertEqual(self.counts(created["id"]), (1, 1, 0))

    def test_another_user_cannot_even_learn_that_it_is_published(self) -> None:
        """404 beats 409: the 409 would confirm a document B may not see."""

        created = self.create_as(ADA_TOKEN)
        self.publish_as(ADA_TOKEN, created["id"])
        self.assertEqual(self.delete_as(GRACE_TOKEN, created["id"]).status_code, 404)
        self.assertEqual(self.counts(created["id"]), (1, 1, 0))

    def test_an_anonymous_caller_is_refused(self) -> None:
        created = self.create_as(ADA_TOKEN)
        self.assertEqual(self.delete_as(None, created["id"]).status_code, 401)
        self.assertEqual(self.counts(created["id"]), (1, 1, 0))


class StoreLevelCascade(DeleteCase):
    def test_the_store_deletes_test_inputs_by_name(self) -> None:
        """Pinned at the store too, so the route is not the only guard."""

        store = self.store()
        stored = store.create(straight_line())
        self.seed_test_input(stored.id)
        self.assertEqual(self.counts(stored.id), (1, 1, 1))
        store.delete(stored.id)
        self.assertEqual(self.counts(stored.id), (0, 0, 0))
        # And the source of the assertion above really is the table: the id
        # the seed wrote is derived from the document's, so a stray row would
        # have been counted.
        self.assertEqual(json.loads(json.dumps(stored.id))[:3], "ug_")
