"""`GET /api/builder/workflows/{id}/versions` - plan 15 D3, the version browser's list.

`[{version, status, created_at, bytes}]`, newest first, from `store.history`.
A version has no status column of its own - `status` lives on the head row - so
the route computes one: `published` for the head after a publish and for the
OLDER version this service is still running when the head has been edited
since, `draft` for everything else. Both can be `published` at once, and the
browser has to show both or the author sees `draft` on the graph that is
answering launches.

`bytes` is the serialised size `MAX_BUILDER_DOCUMENT_BYTES` is compared against,
and the entries are never parsed, so a version written under a schema this
service no longer reads still appears - the author has to be able to see which
version it was that stopped opening.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import update

from brief_crew.builder.store import DocumentNotFound
from brief_crew.service.persistence import builder_document_versions
from tests.service.builder_auth import (
    ADA_TOKEN,
    GRACE_TOKEN,
    BuilderAuthCase,
    document_payload,
)
from tests.service.builder_registration import forget_builder_workflow


class VersionsCase(BuilderAuthCase):
    def versions_as(self, token: str | None, document_id: str) -> Any:
        return self.client.get(
            f"/api/builder/workflows/{document_id}/versions",
            headers=self.auth(token) if token else {},
        )

    def listed(self, token: str, document_id: str) -> list[dict[str, Any]]:
        response = self.versions_as(token, document_id)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def save_named(self, document_id: str, name: str, *, expected_version: int) -> None:
        saved = self.save_as(
            ADA_TOKEN, document_id, document_payload(name=name), expected_version=expected_version
        )
        self.assertEqual(saved.status_code, 200, saved.text)

    def publish(self, document_id: str) -> dict[str, Any]:
        response = self.client.post(
            f"/api/builder/workflows/{document_id}/publish", headers=self.auth(ADA_TOKEN)
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.addCleanup(forget_builder_workflow, response.json()["workflow_id"])
        return response.json()


class TheList(VersionsCase):
    def test_a_new_document_has_one_draft_version(self) -> None:
        created = self.create_as(ADA_TOKEN)
        entries = self.listed(ADA_TOKEN, created["id"])
        self.assertEqual(len(entries), 1)
        self.assertEqual(set(entries[0]), {"version", "status", "created_at", "bytes"})
        self.assertEqual(entries[0]["version"], 1)
        self.assertEqual(entries[0]["status"], "draft")
        self.assertGreater(entries[0]["bytes"], 0)

    def test_every_save_adds_a_version_and_the_newest_is_first(self) -> None:
        created = self.create_as(ADA_TOKEN)
        self.save_named(created["id"], "two", expected_version=1)
        self.save_named(created["id"], "three", expected_version=2)
        entries = self.listed(ADA_TOKEN, created["id"])
        self.assertEqual([entry["version"] for entry in entries], [3, 2, 1])
        self.assertEqual({entry["status"] for entry in entries}, {"draft"})

    def test_bytes_is_the_size_the_document_bound_is_measured_against(self) -> None:
        created = self.create_as(ADA_TOKEN)
        stored = self.store().load(created["id"], user_id="user_ada")
        compact = json.dumps(
            stored.document.model_dump(mode="json", by_alias=True), separators=(",", ":")
        ).encode("utf-8")
        entries = self.listed(ADA_TOKEN, created["id"])
        self.assertEqual(entries[0]["bytes"], len(compact))

    def test_a_version_that_no_longer_parses_is_still_listed(self) -> None:
        created = self.create_as(ADA_TOKEN)
        self.save_named(created["id"], "two", expected_version=1)
        persistence = self.app.state.run_registry.persistence
        with persistence.begin() as connection:
            connection.execute(
                update(builder_document_versions)
                .where(
                    builder_document_versions.c.document_id == created["id"],
                    builder_document_versions.c.version == 1,
                )
                .values(document={"schema": "builder.flow/v0"})
            )
        entries = self.listed(ADA_TOKEN, created["id"])
        self.assertEqual([entry["version"] for entry in entries], [2, 1])


class OpeningAnOlderVersion(VersionsCase):
    def test_get_with_version_keeps_head_version_at_the_current_head(self) -> None:
        """The client derives its read-only lock from `version !== head_version`."""

        created = self.create_as(ADA_TOKEN)
        self.save_named(created["id"], "two", expected_version=1)
        self.save_named(created["id"], "three", expected_version=2)
        older = self.get_as(ADA_TOKEN, created["id"], version=1)
        self.assertEqual(older.status_code, 200, older.text)
        body = older.json()
        self.assertEqual(body["version"], 1)
        self.assertEqual(body["head_version"], 3)
        self.assertEqual(body["document"]["name"], "Test graph")
        head = self.get_as(ADA_TOKEN, created["id"]).json()
        self.assertEqual((head["version"], head["head_version"]), (3, 3))

    def test_restore_is_a_normal_save_from_the_head(self) -> None:
        """Restore commits the old content as head + 1 through the CAS - one
        version, never a rewrite of history."""

        created = self.create_as(ADA_TOKEN)
        self.save_named(created["id"], "two", expected_version=1)
        first = self.get_as(ADA_TOKEN, created["id"], version=1).json()["document"]
        restored = self.save_as(ADA_TOKEN, created["id"], first, expected_version=2)
        self.assertEqual(restored.status_code, 200, restored.text)
        self.assertEqual(restored.json()["head_version"], 3)
        self.assertEqual(restored.json()["document"]["name"], "Test graph")
        self.assertEqual([e["version"] for e in self.listed(ADA_TOKEN, created["id"])], [3, 2, 1])
        # Restoring from a stale base is the same 409 any stale save gets.
        stale = self.save_as(ADA_TOKEN, created["id"], first, expected_version=2)
        self.assertEqual(stale.status_code, 409, stale.text)
        self.assertIn("is at version 3, not 2", stale.json()["detail"])


class ConflictNamesTheVersionThatWon(VersionsCase):
    """`store.save` re-reads the head after a lost compare-and-set.

    Found by `tests/pg/test_two_writers.py`: the version a losing save named
    was the one it had READ before its UPDATE, so the 409 said "is at version
    1, not 1; reload it" and sent the client to reload the version that lost.
    SQLite is single-writer, so the other writer is played here by a listener
    that bumps the head on the same connection just before the CAS runs.
    """

    def test_the_409_names_the_head_that_won(self) -> None:
        from sqlalchemy import event

        from brief_crew.builder.store import DocumentVersionConflict
        from tests.builder.test_compiler import straight_line

        store = self.store()
        stored = store.create(straight_line())
        engine = self.app.state.run_registry.persistence.engine
        fired = {"done": False}

        def other_writer(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
            if not fired["done"] and statement.lstrip().lower().startswith("update builder_documents"):
                fired["done"] = True
                conn.exec_driver_sql(
                    "UPDATE builder_documents SET version = 7 WHERE id = ?", (stored.id,)
                )

        event.listen(engine, "before_cursor_execute", other_writer)
        self.addCleanup(event.remove, engine, "before_cursor_execute", other_writer)
        with self.assertRaises(DocumentVersionConflict) as caught:
            store.save(stored.document.model_copy(update={"name": "mine"}), expected_version=1)
        self.assertTrue(fired["done"])
        self.assertIn("is at version 7, not 1", str(caught.exception))


class PublishedStatus(VersionsCase):
    def test_the_published_head_says_so(self) -> None:
        created = self.create_as(ADA_TOKEN)
        self.publish(created["id"])
        entries = self.listed(ADA_TOKEN, created["id"])
        self.assertEqual([(e["version"], e["status"]) for e in entries], [(1, "published")])

    def test_editing_a_published_graph_shows_two_truths(self) -> None:
        """The head is a draft again AND the older version is still running."""

        created = self.create_as(ADA_TOKEN)
        self.publish(created["id"])
        self.save_named(created["id"], "edited after publish", expected_version=1)
        entries = self.listed(ADA_TOKEN, created["id"])
        self.assertEqual(
            [(e["version"], e["status"]) for e in entries],
            [(2, "draft"), (1, "published")],
        )

    def test_a_published_row_this_process_never_registered_still_reads_published(self) -> None:
        """The boot sweep's skip: published in the table, registered nowhere."""

        from tests.builder.test_compiler import straight_line

        stored = self.store().create(straight_line(), user_id="user_ada")
        self.store().mark_published(stored.id, 1, user_id="user_ada")
        entries = self.listed(ADA_TOKEN, stored.id)
        self.assertEqual([(e["version"], e["status"]) for e in entries], [(1, "published")])


class Visibility(VersionsCase):
    def test_another_user_s_document_is_a_404(self) -> None:
        created = self.create_as(ADA_TOKEN)
        response = self.versions_as(GRACE_TOKEN, created["id"])
        self.assertEqual(response.status_code, 404, response.text)

    def test_an_anonymous_caller_is_refused(self) -> None:
        created = self.create_as(ADA_TOKEN)
        self.assertEqual(self.versions_as(None, created["id"]).status_code, 401)

    def test_an_unknown_document_is_a_404(self) -> None:
        self.assertEqual(self.versions_as(ADA_TOKEN, "ug_00000000").status_code, 404)

    def test_the_store_refuses_by_name_too(self) -> None:
        with self.assertRaises(DocumentNotFound):
            self.store().history("ug_00000000")
