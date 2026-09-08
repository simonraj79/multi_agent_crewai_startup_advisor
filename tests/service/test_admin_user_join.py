"""Better Auth's `user` table stays Better Auth's (plan 17 criterion 10).

`runs.user_id` **is** `user.id` verbatim, so the e-mail this console shows is
a join to a table another service owns, in another language, migrated by
another tool. Declaring it on `persistence.metadata` would put it in the set
`metadata.create_all()` creates - and `init_db()` runs on every boot - so this
service would create Better Auth's table, with columns this repository
guessed, on any database that booted the Python half first.

Three assertions, and the third is the one that matters in production:

1. `persistence.metadata.tables` has no `user` key.
2. `init_db()` on a fresh SQLite file creates none.
3. With the table ABSENT, `/users` still answers - `email: null, name: null`
   and nothing else different. Absent is the ordinary case here: SQLite in
   every test, a bare checkout, and any deployment whose Node half has not
   migrated yet.

And the fourth, which is what makes the join worth having at all: with the
table PRESENT, the e-mail arrives.
"""

from __future__ import annotations

import pathlib
import tempfile
import unittest

from sqlalchemy import inspect, text

from tests.service.admin_fixtures import ALICE, AdminCase


class SeparateMetadataTests(unittest.TestCase):
    def test_the_user_table_is_not_on_persistence_metadata(self) -> None:
        from brief_crew.service import persistence

        self.assertNotIn("user", persistence.metadata.tables)
        self.assertNotIn("session", persistence.metadata.tables)

    def test_the_admin_module_declares_it_on_a_metadata_of_its_own(self) -> None:
        from brief_crew.service import persistence
        from brief_crew.service.admin_api import auth_user

        self.assertIsNot(auth_user.metadata, persistence.metadata)
        self.assertIn("user", auth_user.metadata.tables)

    def test_init_db_on_a_fresh_file_creates_no_user_table(self) -> None:
        """The assertion that would have caught it in production.

        `create_all()` is create-if-absent PER TABLE, so the damage is not a
        crash - it is a `user` table quietly existing with this repository's
        guess at its columns, which the Node service then migrates on top of
        or fails against depending on which booted first.
        """

        from brief_crew.service.persistence import PostgresFlowPersistence

        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "fresh.db"
            store = PostgresFlowPersistence(f"sqlite+pysqlite:///{path}")
            try:
                store.init_db()
                names = set(inspect(store.engine).get_table_names())
            finally:
                # Closed INSIDE the `with`, not by `addCleanup`: on Windows an
                # open SQLite handle holds the file and the temporary
                # directory's own cleanup then raises `PermissionError`, which
                # would read as a defect in `init_db`.
                store.close()
        self.assertNotIn("user", names)
        self.assertNotIn("session", names)
        # And the tables it IS responsible for are there, so this is not a
        # green assertion over a database nothing created.
        self.assertIn("runs", names)
        self.assertIn("run_node_metrics", names)


class WithoutTheTableTests(AdminCase):
    """The ordinary case: SQLite, a bare checkout, an unmigrated deployment."""

    def test_users_answers_with_null_email_and_name(self) -> None:
        self.seed_run("r-1", user_id=ALICE.id, cost="0.0500")
        rows = self.ok("/users")["rows"]
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["user_id"], ALICE.id)
        self.assertIsNone(row["email"])
        self.assertIsNone(row["name"])
        self.assertIsNone(row["created_at"])
        self.assertIsNone(row["last_session_at"])
        # Everything this service DOES own is still there.
        self.assertEqual(row["runs"], 1)
        self.assertEqual(row["spent_usd"], 0.05)

    def test_the_head_counts_are_zero_rather_than_an_error(self) -> None:
        """Zero, and the Health panel's `blind_to` list is what stops a reader
        taking that as "nobody has signed up"."""

        self.seed_run("r-1", user_id=ALICE.id)
        body = self.ok("/summary")
        self.assertEqual(body["people_total"], 0)
        self.assertEqual(body["people_new"], 0)
        # `people_active` comes from `runs` and is NOT blind here.
        self.assertEqual(body["people_active"], 1)

    def test_a_run_row_carries_a_null_email(self) -> None:
        self.seed_run("r-1", user_id=ALICE.id)
        self.assertIsNone(self.ok("/runs")["rows"][0]["email"])


class WithTheTableTests(AdminCase):
    """The deployed case, with Better Auth's rows created by hand.

    Created with raw DDL rather than by `auth_user.metadata.create_all()`,
    because the point is to imitate a table this repository does not own -
    creating it from our own description would prove that our description
    matches itself.
    """

    def setUp(self) -> None:
        super().setUp()
        with self.store.begin() as connection:
            connection.execute(
                text(
                    'CREATE TABLE "user" ('
                    '"id" VARCHAR(128) PRIMARY KEY, '
                    '"name" VARCHAR(255), '
                    '"email" VARCHAR(255), '
                    '"emailVerified" BOOLEAN, '
                    '"createdAt" TIMESTAMP, '
                    '"updatedAt" TIMESTAMP)'
                )
            )
            connection.execute(
                text(
                    'CREATE TABLE "session" ('
                    '"id" VARCHAR(128) PRIMARY KEY, '
                    '"userId" VARCHAR(128), '
                    '"token" VARCHAR(255), '
                    '"createdAt" TIMESTAMP, '
                    '"updatedAt" TIMESTAMP)'
                )
            )
            connection.execute(
                text(
                    'INSERT INTO "user" ("id","name","email","createdAt") '
                    "VALUES ('user_alice','Alice','alice@example.test','2026-08-14 09:12:00')"
                )
            )
            connection.execute(
                text(
                    'INSERT INTO "session" ("id","userId","updatedAt") '
                    "VALUES ('sess1','user_alice','2026-09-08 11:02:55')"
                )
            )

    def test_the_email_and_the_join_date_arrive(self) -> None:
        self.seed_run("r-1", user_id=ALICE.id, cost="0.0500")
        row = self.ok("/users")["rows"][0]
        self.assertEqual(row["email"], "alice@example.test")
        self.assertEqual(row["name"], "Alice")
        self.assertIsNotNone(row["created_at"])
        self.assertIsNotNone(row["last_session_at"])

    def test_a_run_row_carries_the_owners_email(self) -> None:
        self.seed_run("r-1", user_id=ALICE.id)
        self.assertEqual(self.ok("/runs")["rows"][0]["email"], "alice@example.test")

    def test_the_head_counts_read_the_created_at_column(self) -> None:
        self.seed_run("r-1", user_id=ALICE.id)
        body = self.ok("/summary")
        self.assertEqual(body["people_total"], 1)

    def test_an_account_with_no_runs_at_all_is_still_reachable(self) -> None:
        """Better Auth knows them and this service does not - which is a real
        state on any deployment where somebody signed in and never launched."""

        body = self.ok("/users/user_alice")
        self.assertEqual(body["email"], "alice@example.test")
        self.assertEqual(body["runs"], 0)
        self.assertEqual(body["spent_usd"], 0.0)

    def test_an_id_nothing_knows_is_404(self) -> None:
        response = self.get("/users/user_nobody")
        self.assertEqual(response.status_code, 404, response.text)
        self.assertEqual(response.json(), {"detail": "Not Found"})


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
