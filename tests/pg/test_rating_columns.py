"""The four plan-20 columns reach a SHIPPED PostgreSQL `runs` table (L2).

`tests/service/test_additive_migration.py::RunRatingColumnsTests` proves the
same migration on SQLite, which is what every other test in this repository
runs on. That is not enough here, for the two reasons
`tests/pg/test_run_ceiling_columns.py` gives about the ceiling columns and one
this plan adds:

* **SQLite's `ALTER TABLE ... ADD COLUMN` is permissive to the point of being
  uninformative.** It accepts a type name it does not implement and stores
  whatever it is handed, so a green SQLite run says the statement parsed, not
  that the column production gets is the column the `Table()` describes.
  PostgreSQL either creates a `varchar(512)` and a `timestamptz` or refuses.
* **`rated_at` is a timestamp with a time zone**, and SQLite has no such type
  at all - it keeps a string. Every other datetime in this schema is
  `TIMESTAMP WITH TIME ZONE`, and a rating that came back naive would sort
  wrongly against `created_at` on exactly the panel that pairs them.
* **`varchar(512)` REFUSES an over-long note on PostgreSQL** where SQLite
  stores it, so the three bounds above the column - the request model, the
  `str(note)[:MAX_RATING_NOTE_CHARS]` clip, the column itself - are what keep
  a write from failing in production and nowhere else.

Skipped unless `TEST_DATABASE_URL` is set, and a throwaway database is created
on the server that URL names, so nothing is written into the database itself.
`_throwaway_database` is IMPORTED from `test_two_writers` rather than copied -
a copy is how two halves drift.

Local recipe (Docker):

    docker start pg18-test
    $env:TEST_DATABASE_URL = "postgresql+psycopg://postgres:test@127.0.0.1:5433/postgres"
    .\\.venv\\Scripts\\python.exe -m unittest tests.pg.test_rating_columns -v
"""

from __future__ import annotations

import os
import unittest

from tests.pg.test_run_ceiling_columns import SHIPPED_RUNS_DDL, SHIPPED_ROW
from tests.pg.test_two_writers import _throwaway_database

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")

RATING_COLUMNS = ("rating", "rating_note", "rated_by", "rated_at")


@unittest.skipUnless(
    TEST_DATABASE_URL, "TEST_DATABASE_URL is not set; see the module docstring"
)
class RunRatingColumnsOnPostgres(unittest.TestCase):
    """One throwaway database per test, as the two-writers module does.

    The fixture is `runs` as it shipped BEFORE the ceiling columns, which is
    also before these four - so the migration under test has to add seven
    columns to one table in one pass, which is what a real deployment will do
    on its next boot.
    """

    def setUp(self) -> None:
        from sqlalchemy import create_engine, text

        self.database_url, drop_database = _throwaway_database(TEST_DATABASE_URL)
        self.addCleanup(drop_database)
        self.engine = create_engine(self.database_url)
        self.addCleanup(self.engine.dispose)
        with self.engine.begin() as connection:
            connection.execute(text(SHIPPED_RUNS_DDL))
            connection.execute(text(SHIPPED_ROW))

    def columns(self) -> dict[str, object]:
        from sqlalchemy import inspect

        return {c["name"]: c["type"] for c in inspect(self.engine).get_columns("runs")}

    def upgrade(self):
        from brief_crew.service.persistence import PostgresFlowPersistence

        store = PostgresFlowPersistence(self.database_url, initialize=False)
        self.addCleanup(store.close)
        store.init_db()
        return store

    def test_the_fixture_really_is_the_shipped_shape(self) -> None:
        """The control. Every assertion below must be able to fail."""

        present = self.columns()
        self.assertIn("user_id", present)
        for name in RATING_COLUMNS:
            with self.subTest(column=name):
                self.assertNotIn(name, present)

    def test_init_db_adds_all_four_to_a_shipped_table(self) -> None:
        self.upgrade()
        present = self.columns()
        for name in RATING_COLUMNS:
            with self.subTest(column=name):
                self.assertIn(name, present)

    def test_the_column_types_are_what_the_table_declares(self) -> None:
        """The assertion SQLite cannot make.

        It stores what it is handed and reports the declared text back; here
        the server has to have created a real `varchar(512)` and a real
        `timestamptz`.
        """

        self.upgrade()
        present = self.columns()
        self.assertEqual(16, present["rating"].length)
        self.assertEqual(512, present["rating_note"].length)
        self.assertEqual(128, present["rated_by"].length)
        self.assertTrue(getattr(present["rated_at"], "timezone", False))

    def test_the_row_written_before_them_keeps_four_nulls(self) -> None:
        from sqlalchemy import text

        self.upgrade()
        with self.engine.begin() as connection:
            row = connection.execute(
                text("SELECT id, rating, rating_note, rated_by, rated_at FROM runs")
            ).one()
        self.assertEqual(row.id, "capped-before-the-columns")
        self.assertIsNone(row.rating)
        self.assertIsNone(row.rating_note)
        self.assertIsNone(row.rated_by)
        self.assertIsNone(row.rated_at)

    def test_a_rating_round_trips_with_a_tz_aware_timestamp(self) -> None:
        """Write then read on the dialect that ships.

        `rated_at` comes back with a time zone, which is what lets a panel sort
        it against `created_at` without a naive-versus-aware comparison raising
        halfway down a list.
        """

        store = self.upgrade()
        stored = store.set_run_rating(
            "capped-before-the-columns",
            rating="good",
            note="the segment was right",
            rated_by="user_alice",
        )
        self.assertEqual("good", stored["rating"])
        self.assertIsNotNone(stored["rated_at"].tzinfo)

        from sqlalchemy import text

        with self.engine.begin() as connection:
            row = connection.execute(
                text("SELECT rating, rating_note, rated_by, rated_at FROM runs")
            ).one()
        self.assertEqual("good", row.rating)
        self.assertEqual("the segment was right", row.rating_note)
        self.assertEqual("user_alice", row.rated_by)
        self.assertIsNotNone(row.rated_at.tzinfo)

    def test_a_note_at_the_column_bound_is_stored_whole(self) -> None:
        """`varchar(512)` REFUSES an over-long value on PostgreSQL where SQLite
        would store it, so the three bounds above the column are what keep the
        write from failing in production."""

        from brief_crew.config import MAX_RATING_NOTE_CHARS

        store = self.upgrade()
        note = "y" * MAX_RATING_NOTE_CHARS
        stored = store.set_run_rating(
            "capped-before-the-columns", rating="bad", note=note, rated_by=None
        )
        self.assertEqual(note, stored["rating_note"])

    def test_a_nul_in_a_note_is_what_this_dialect_cannot_store(self) -> None:
        """D2's root cause, on the only dialect that has it.

        PostgreSQL cannot hold `\\x00` in a `text` value at ALL: psycopg
        raises, the route answered 500, and the traceback wrote the note -
        user content - into the server log. SQLite stores it happily, so this
        assertion is the one that proves the request-model strip is load
        bearing rather than tidy.
        """

        import psycopg

        store = self.upgrade()
        with self.assertRaises((psycopg.DataError, Exception)) as caught:
            store.set_run_rating(
                "capped-before-the-columns",
                rating="bad",
                note="a\x00b",
                rated_by=None,
            )
        self.assertIn("0x00", str(caught.exception).replace("\\x00", "0x00"))

    def test_the_note_the_request_model_produces_stores_fine(self) -> None:
        """The other half: what actually reaches the column after stripping."""

        from brief_crew.service.rating_api import RatingRequest

        store = self.upgrade()
        request = RatingRequest(rating="bad", note="a\x00b\nc")
        stored = store.set_run_rating(
            "capped-before-the-columns",
            rating=request.normalised(),
            note=request.note,
            rated_by=None,
        )
        self.assertEqual("ab\nc", stored["rating_note"])

    def test_an_over_long_note_is_clipped_rather_than_refused(self) -> None:
        """The third bound, and PostgreSQL is where it is load-bearing.

        A driver handed 900 characters for a `varchar(512)` raises here; on
        SQLite it would simply store them and nobody would learn that the
        request model's 422 is the thing keeping production up.
        """

        from brief_crew.config import MAX_RATING_NOTE_CHARS

        store = self.upgrade()
        stored = store.set_run_rating(
            "capped-before-the-columns",
            rating="bad",
            note="z" * (MAX_RATING_NOTE_CHARS + 400),
            rated_by=None,
        )
        self.assertEqual(MAX_RATING_NOTE_CHARS, len(stored["rating_note"]))

    def test_clearing_a_rating_clears_the_note_and_the_actor_with_it(self) -> None:
        store = self.upgrade()
        store.set_run_rating(
            "capped-before-the-columns", rating="bad", note="a note", rated_by="alice"
        )
        cleared = store.set_run_rating(
            "capped-before-the-columns", rating=None, note=None, rated_by=None
        )
        self.assertIsNone(cleared["rating"])
        self.assertIsNone(cleared["rating_note"])
        self.assertIsNone(cleared["rated_by"])
        self.assertIsNone(cleared["rated_at"])

    def test_the_admin_runs_rating_filter_works_on_this_dialect(self) -> None:
        """`unrated` is `IS NULL`, which is one spelling on both dialects - but
        the filter is only ever exercised against SQLite elsewhere, and the
        keyset it rides on is the row-value comparison that motivated this
        directory in the first place."""

        store = self.upgrade()
        store.set_run_rating(
            "capped-before-the-columns", rating="bad", note=None, rated_by=None
        )
        self.assertEqual(
            ["capped-before-the-columns"],
            [row["run_id"] for row in store.admin_list_runs(rating="bad")],
        )
        self.assertEqual([], store.admin_list_runs(rating="good"))
        self.assertEqual([], store.admin_list_runs(rating="unrated"))
        with self.assertRaises(ValueError):
            store.admin_list_runs(rating="excellent")

    def test_running_it_twice_changes_nothing(self) -> None:
        from sqlalchemy import text

        self.upgrade()
        before = set(self.columns())
        self.upgrade()
        self.assertEqual(before, set(self.columns()))
        with self.engine.begin() as connection:
            self.assertEqual(
                1, connection.execute(text("SELECT COUNT(*) FROM runs")).scalar_one()
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
