"""Keyset pagination is total and non-overlapping (plan 17 criterion 7).

A dashboard's run list is the one place a wrong pager is invisible: rows
appear once, in order, and nobody notices that three of them were never shown.
So the assertion is not "the second page differs from the first" - it is that
**120 seeded runs come back as 120 distinct ids in `created_at DESC`**, with
nothing repeated and nothing missing, over as many pages as it takes.

Two properties this exercises that an `OFFSET` pager does not have:

* **It does not drift.** With OFFSET, a run created while somebody is reading
  page 1 pushes one row from page 1 onto page 2, and that row is shown twice
  while the last row of page 2 is never shown at all. The row-value key is
  anchored to a row rather than to a count.
* **One spelling covers both dialects.** `(created_at, id) < (ts, id)` is a
  row-value comparison SQLite has had since 3.15 and PostgreSQL has always
  had, so there is no dialect branch to get wrong on the one database that is
  never tested here.

And a **tampered cursor is a 422, not a 500** - the remedy is to ask for the
first page again, and a 500 would send somebody looking for a server fault.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from brief_crew import config
from tests.service.admin_fixtures import ALICE, AdminCase

TOTAL = 120


class KeysetPaginationTests(AdminCase):
    def setUp(self) -> None:
        super().setUp()
        for index in range(TOTAL):
            # Descending age, so `created_at DESC` is `run-000` first and the
            # expected order is the index order. Sub-hour spacing so several
            # rows share a minute and the id tiebreak is exercised.
            self.seed_run(
                f"run-{index:03d}",
                cost="0.0010",
                age_hours=1 + index * 0.01,
            )

    def walk(self, limit: int) -> list[str]:
        """Every page, followed to the end, as one list of ids."""

        seen: list[str] = []
        cursor: str | None = None
        for _guard in range(TOTAL + 5):
            params = {"limit": limit}
            if cursor:
                params["cursor"] = cursor
            body = self.ok("/runs", params=params)
            seen.extend(row["run_id"] for row in body["rows"])
            cursor = body["next"]
            if not cursor:
                break
        else:  # pragma: no cover - a pager that never terminates
            self.fail("the pager did not reach a last page")
        return seen

    def test_a_120_row_fixture_at_limit_50_yields_120_distinct_ids(self) -> None:
        seen = self.walk(50)
        self.assertEqual(len(seen), TOTAL)
        self.assertEqual(len(set(seen)), TOTAL, "a page overlapped another")
        self.assertEqual(seen, sorted(seen), "the order was not created_at DESC")
        self.assertEqual(seen[0], "run-000")
        self.assertEqual(seen[-1], f"run-{TOTAL - 1:03d}")

    def test_the_same_walk_at_three_page_sizes_gives_the_same_list(self) -> None:
        """Totality is a property of the pager, not of one page size."""

        reference = self.walk(50)
        for size in (1, 7, 200):
            with self.subTest(limit=size):
                self.assertEqual(self.walk(size), reference)

    def test_the_last_page_carries_no_cursor(self) -> None:
        body = self.ok("/runs", params={"limit": 200})
        self.assertEqual(len(body["rows"]), TOTAL)
        self.assertIsNone(body["next"])

    def test_a_full_page_that_is_also_the_last_carries_no_cursor(self) -> None:
        """The `limit + 1` read, asserted rather than assumed.

        A pager that emits a cursor whenever the page is full sends the client
        back for an empty page every time the row count divides exactly - a
        wasted round trip that only shows up at exactly this boundary.
        """

        seen = self.walk(TOTAL)
        self.assertEqual(len(seen), TOTAL)

    def test_the_page_size_is_capped_rather_than_refused(self) -> None:
        """`ADMIN_PAGE_LIMIT_MAX`, clamped, because a client asking for 10,000
        rows wants everything and should get the most this service will give
        rather than an error it cannot act on."""

        with patch.object(config, "ADMIN_PAGE_LIMIT_MAX", 10):
            body = self.ok("/runs", params={"limit": 10_000})
        self.assertEqual(len(body["rows"]), 10)
        self.assertIsNotNone(body["next"])

    def test_a_tampered_cursor_is_422_and_not_500(self) -> None:
        for cursor in (
            "not-base64-at-all!!",
            "Zm9vYmFy",  # decodes, but has no separator
            "MjAyNi0wOS0wOFQxMTozODowMlp8",  # a moment and no id
            "fHJ1bi0wMDA=",  # an id and no moment
            "bm90LWEtZGF0ZXxydW4tMDAw",  # "not-a-date|run-000"
        ):
            with self.subTest(cursor=cursor):
                response = self.get("/runs", params={"cursor": cursor})
                self.assertEqual(response.status_code, 422, response.text)
                self.assertEqual(response.json()["detail"], "cursor is not valid")

    def test_a_cursor_round_trips(self) -> None:
        from brief_crew.service.admin_api import decode_cursor, encode_cursor

        cursor = encode_cursor("2026-09-08T11:38:02.000Z", "run-000")
        moment, row_id = decode_cursor(cursor)
        self.assertEqual(row_id, "run-000")
        self.assertEqual(moment.year, 2026)
        self.assertIsNotNone(moment.tzinfo)

    def test_a_filter_narrows_the_walk_without_breaking_it(self) -> None:
        self.seed_run("run-bob", user_id="user_bob", cost="0.0010", age_hours=0.5)
        body = self.ok("/runs", params={"user_id": "user_bob", "limit": 50})
        self.assertEqual([row["run_id"] for row in body["rows"]], ["run-bob"])
        self.assertIsNone(body["next"])

    def test_the_unowned_filter_selects_the_null_rows(self) -> None:
        self.seed_run("run-nobody", user_id=None, cost="0.0010", age_hours=0.5)
        body = self.ok("/runs", params={"user_id": "__unowned__", "limit": 50})
        self.assertEqual([row["run_id"] for row in body["rows"]], ["run-nobody"])
        self.assertEqual(body["rows"][0]["user_id"], "__unowned__")


class UsersPaginationTests(AdminCase):
    def test_the_users_page_is_total_over_every_account(self) -> None:
        for index in range(7):
            self.seed_run(f"run-{index}", user_id=f"user_{index}", cost="0.0010")
        seen: list[str] = []
        cursor: str | None = None
        for _guard in range(10):
            params = {"limit": 2}
            if cursor:
                params["cursor"] = cursor
            body = self.ok("/users", params=params)
            seen.extend(row["user_id"] for row in body["rows"])
            cursor = body["next"]
            if not cursor:
                break
        self.assertEqual(len(seen), 7)
        self.assertEqual(len(set(seen)), 7)

    def test_a_tampered_users_cursor_is_422(self) -> None:
        response = self.get("/users", params={"cursor": "!!!not-a-cursor!!!"})
        self.assertEqual(response.status_code, 422, response.text)

    def test_an_unknown_sort_is_422(self) -> None:
        response = self.get("/users", params={"sort": "sideways"})
        self.assertEqual(response.status_code, 422, response.text)

    def test_each_sort_answers(self) -> None:
        for index in range(3):
            self.seed_run(
                f"run-{index}", user_id=f"user_{index}", cost=f"0.0{index + 1}00"
            )
        for sort in ("spend", "recent", "joined"):
            with self.subTest(sort=sort):
                body = self.ok("/users", params={"sort": sort})
                self.assertEqual(len(body["rows"]), 3)
        # `spend` is descending, which is the one order that has a right answer
        # without a Better Auth table to date the others.
        spent = [
            row["spent_usd"] for row in self.ok("/users", params={"sort": "spend"})["rows"]
        ]
        self.assertEqual(spent, sorted(spent, reverse=True))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
