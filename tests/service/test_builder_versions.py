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
        self.assertEqual(
            set(entries[0]),
            # `edge_count` joined in round 3 (D-15-24): the browser subtracts
            # adjacent rows into `+2 nodes, -1 edge`, and a delta over nodes
            # alone would report a rewiring as no change at all.
            {
                "version",
                "status",
                "created_at",
                "bytes",
                "source",
                "name",
                "node_count",
                "edge_count",
            },
        )
        self.assertEqual(entries[0]["version"], 1)
        self.assertEqual(entries[0]["status"], "draft")
        self.assertGreater(entries[0]["bytes"], 0)
        # Both counts are read leniently off the raw row, so a document the
        # schema would refuse still lists; this one parses, so both are numbers.
        self.assertIsInstance(entries[0]["node_count"], int)
        self.assertIsInstance(entries[0]["edge_count"], int)

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


class WhatARowSays(VersionsCase):
    """Round 2, D-15-3: a row carries a label, its source and a dated time.

    Round 1 found two rows that read "3 Sept, 00:19 · DRAFT" apart from 0.2 KB
    of size, so choosing which to restore was guesswork. `name` and
    `node_count` are the label, read leniently off the stored row; `source` is
    the new column, composed by the server from what the client declared.
    """

    def row(self, document_id: str, version: int) -> dict[str, Any]:
        return next(r for r in self.listed(ADA_TOKEN, document_id) if r["version"] == version)

    def test_every_row_carries_its_name_node_count_and_source(self) -> None:
        created = self.create_as(ADA_TOKEN)
        self.save_named(created["id"], "two", expected_version=1)
        first, second = self.row(created["id"], 1), self.row(created["id"], 2)
        self.assertEqual(first["name"], "Test graph")
        self.assertEqual(second["name"], "two")
        self.assertEqual(first["node_count"], len(document_payload()["nodes"]))
        self.assertEqual(second["node_count"], len(document_payload()["nodes"]))
        self.assertEqual(first["source"], "created")
        self.assertEqual(second["source"], "saved")

    def test_the_save_source_is_composed_from_what_the_client_declared(self) -> None:
        created = self.create_as(ADA_TOKEN)
        for version, body, expected in (
            (2, {"source": "autosave"}, "autosaved"),
            (3, {"source": "save"}, "saved"),
            (4, {"source": "restore", "restored_from": 1}, "restored from v1"),
            (5, {"source": "restore"}, "restored"),
            (6, {}, "saved"),
        ):
            with self.subTest(expected=expected):
                saved = self.client.put(
                    f"/api/builder/workflows/{created['id']}",
                    json={"document": document_payload(), "expected_version": version - 1, **body},
                    headers=self.auth(ADA_TOKEN),
                )
                self.assertEqual(saved.status_code, 200, saved.text)
                self.assertEqual(self.row(created["id"], version)["source"], expected)

    def test_a_source_the_server_does_not_know_is_refused(self) -> None:
        created = self.create_as(ADA_TOKEN)
        refused = self.client.put(
            f"/api/builder/workflows/{created['id']}",
            json={"document": document_payload(), "expected_version": 1, "source": "magic"},
            headers=self.auth(ADA_TOKEN),
        )
        self.assertEqual(refused.status_code, 422, refused.text)

    def test_an_import_and_a_duplicate_say_where_they_came_from(self) -> None:
        created = self.create_as(ADA_TOKEN)
        envelope = self.export_as(ADA_TOKEN, created["id"]).json()
        imported = self.import_as(ADA_TOKEN, envelope)
        self.assertEqual(imported.status_code, 201, imported.text)
        self.assertEqual(self.row(imported.json()["id"], 1)["source"], "imported")
        duplicated = self.client.post(
            f"/api/builder/workflows/{created['id']}/duplicate", headers=self.auth(ADA_TOKEN)
        )
        self.assertEqual(duplicated.status_code, 201, duplicated.text)
        self.assertEqual(self.row(duplicated.json()["id"], 1)["source"], "duplicated")

    def test_a_row_older_than_the_column_reads_stored(self) -> None:
        created = self.create_as(ADA_TOKEN)
        persistence = self.app.state.run_registry.persistence
        with persistence.begin() as connection:
            connection.execute(
                update(builder_document_versions)
                .where(builder_document_versions.c.document_id == created["id"])
                .values(source=None)
            )
        self.assertEqual(self.row(created["id"], 1)["source"], "stored")

    def test_a_row_the_schema_refuses_still_says_what_it_can(self) -> None:
        created = self.create_as(ADA_TOKEN)
        persistence = self.app.state.run_registry.persistence
        with persistence.begin() as connection:
            connection.execute(
                update(builder_document_versions)
                .where(builder_document_versions.c.document_id == created["id"])
                .values(document={"name": "Only a name", "nodes": "not a list"})
            )
        row = self.row(created["id"], 1)
        self.assertEqual(row["name"], "Only a name")
        self.assertIsNone(row["node_count"])


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

    def test_an_unknown_version_of_your_own_document_names_the_version_on_every_route(self) -> None:
        """D-15-8. GET, export, duplicate and publish all take `?version=`, and
        all four used to flatten the store's sentence to "document not found"
        about a document the caller was looking at. A stranger still hears the
        constant - see `test_isolation_matrix`."""

        created = self.create_as(ADA_TOKEN)
        self.save_named(created["id"], "two", expected_version=1)
        routes = (
            ("get", f"/api/builder/workflows/{created['id']}?version=99"),
            ("get", f"/api/builder/workflows/{created['id']}/export?version=99"),
            ("post", f"/api/builder/workflows/{created['id']}/duplicate?version=99"),
            ("post", f"/api/builder/workflows/{created['id']}/publish?version=99"),
        )
        for method, path in routes:
            with self.subTest(route=f"{method} {path}"):
                refused = getattr(self.client, method)(path, headers=self.auth(ADA_TOKEN))
                self.assertEqual(refused.status_code, 404, refused.text)
                detail = refused.json()["detail"]
                self.assertNotEqual(detail, "document not found")
                self.assertIn(created["id"], detail)
                self.assertIn("version 99", detail)
                self.assertIn("newest is v2", detail)

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


class TheSummaryKnowsWhichVersionIsLive(VersionsCase):
    """Critic round product-1, P-04 and P-05.

    D-15-23 made the *version rows* honest about a document whose live version
    is behind head. The **document summary** above them stayed head-derived, so
    `GET /api/builder/workflows` answered `status: "draft"` for a graph that was
    answering launches, and the gallery - the only place an author sees all
    their graphs - drew it identically to one that had never been published.
    `GET /api/builder/workflows/{id}` had the same gap from the other side:
    `published` answers "is THIS version the live one", which goes false the
    moment the author saves past it.

    Both now carry `live_version`, from the one helper all three readers share.
    """

    def summary(self, document_id: str) -> dict[str, Any]:
        response = self.client.get(
            "/api/builder/workflows", headers=self.auth(ADA_TOKEN)
        )
        self.assertEqual(response.status_code, 200, response.text)
        rows = [row for row in response.json() if row["id"] == document_id]
        self.assertEqual(len(rows), 1, response.text)
        return rows[0]

    def document(self, document_id: str) -> dict[str, Any]:
        response = self.client.get(
            f"/api/builder/workflows/{document_id}", headers=self.auth(ADA_TOKEN)
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_a_never_published_document_has_no_live_version(self) -> None:
        created = self.create_as(ADA_TOKEN)
        self.assertIsNone(self.summary(created["id"])["live_version"])
        self.assertIsNone(self.document(created["id"])["live_version"])

    def test_a_published_head_names_itself_as_live(self) -> None:
        created = self.create_as(ADA_TOKEN)
        self.publish(created["id"])
        row = self.summary(created["id"])
        self.assertEqual((row["status"], row["version"], row["live_version"]), ("published", 1, 1))
        self.assertEqual(self.document(created["id"])["live_version"], 1)

    def test_a_head_saved_past_a_published_version_still_names_it(self) -> None:
        """P-04 and P-05 in one measurement: `draft v2` and `v1` live.

        Before the fix the summary carried `status: "draft"` and nothing else,
        and the canvas's `published: false` was the only signal - which is why
        the `v1 is live` chip vanished at the exact moment it started mattering.
        """

        created = self.create_as(ADA_TOKEN)
        self.publish(created["id"])
        self.save_named(created["id"], "edited after publish", expected_version=1)

        row = self.summary(created["id"])
        self.assertEqual((row["status"], row["version"], row["live_version"]), ("draft", 2, 1))

        document = self.document(created["id"])
        self.assertEqual(document["status"], "draft")
        self.assertEqual(document["version"], 2)
        self.assertFalse(document["published"])
        self.assertEqual(document["live_version"], 1)

    def test_the_summary_and_the_version_rows_never_disagree(self) -> None:
        created = self.create_as(ADA_TOKEN)
        self.publish(created["id"])
        self.save_named(created["id"], "edited after publish", expected_version=1)
        live = [
            entry["version"]
            for entry in self.listed(ADA_TOKEN, created["id"])
            if entry["status"] == "published"
        ]
        self.assertEqual(live, [self.summary(created["id"])["live_version"]])

    def test_a_published_row_registered_nowhere_reports_no_live_version(self) -> None:
        """The boot sweep's skip, from the summary's side.

        The row says `published` and this process runs nothing, so `live_version`
        is honestly `None` while `status` is honestly `published`. Two facts, and
        the bar needs both to say "published but not registered here".
        """

        from tests.builder.test_compiler import straight_line

        stored = self.store().create(straight_line(), user_id="user_ada")
        self.store().mark_published(stored.id, 1, user_id="user_ada")
        row = self.summary(stored.id)
        self.assertEqual(row["status"], "published")
        self.assertIsNone(row["live_version"])
