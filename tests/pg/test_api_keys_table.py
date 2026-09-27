"""Plan 22 criterion 10 on real PostgreSQL 18: `api_keys` is created by boot.

The SQLite suite (`tests/service/test_api_keys.py`) proves the behaviour; this
proves the DDL and the queries on the dialect production runs, including the
UNIQUE hash, the partial "live keys" count and the conditional `last_used_at`
UPDATE with a timezone-aware comparison - the kind of thing SQLite accepts and
PostgreSQL refuses.

Skipped unless `TEST_DATABASE_URL` is set; a throwaway database is created on
that server, so nothing is written into the database it names:

    $env:TEST_DATABASE_URL = "postgresql+psycopg://postgres:test@127.0.0.1:5433/postgres"
"""

from __future__ import annotations

import os
import unittest

from tests.pg.test_two_writers import _throwaway_database

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")


@unittest.skipUnless(
    TEST_DATABASE_URL, "TEST_DATABASE_URL is not set; see the module docstring"
)
class ApiKeysOnPostgres(unittest.TestCase):
    def setUp(self) -> None:
        from brief_crew.service.persistence import PostgresFlowPersistence

        url, drop = _throwaway_database(TEST_DATABASE_URL)
        self.addCleanup(drop)
        self.store = PostgresFlowPersistence(url)
        self.addCleanup(self.store.close)

    def test_create_resolve_touch_revoke(self) -> None:
        from brief_crew.service.api_keys import generate_api_key

        from sqlalchemy.exc import IntegrityError

        secret, digest, prefix = generate_api_key()
        row = self.store.create_api_key(
            key_id="key_pg1", user_id="u1", name="ci", prefix=prefix,
            secret_hash=digest, user_email="u1@example.test", user_name="U",
            max_active=2,
        )
        self.assertIsNotNone(row)
        self.assertEqual(self.store.resolve_api_key(digest)["user_id"], "u1")
        self.assertTrue(self.store.touch_api_key("key_pg1", min_interval_seconds=60))
        self.assertFalse(self.store.touch_api_key("key_pg1", min_interval_seconds=60))

        with self.assertRaises(IntegrityError):
            self.store.create_api_key(
                key_id="key_pg2", user_id="u1", name="dup", prefix=prefix,
                secret_hash=digest, user_email=None, user_name=None, max_active=5,
            )

        _, digest2, _ = generate_api_key()
        self.assertIsNotNone(self.store.create_api_key(
            key_id="key_pg3", user_id="u1", name="b", prefix=prefix,
            secret_hash=digest2, user_email=None, user_name=None, max_active=2,
        ))
        _, digest3, _ = generate_api_key()
        self.assertIsNone(self.store.create_api_key(
            key_id="key_pg4", user_id="u1", name="c", prefix=prefix,
            secret_hash=digest3, user_email=None, user_name=None, max_active=2,
        ))

        self.assertFalse(self.store.revoke_api_key("someone_else", "key_pg1"))
        self.assertTrue(self.store.revoke_api_key("u1", "key_pg1"))
        self.assertIsNone(self.store.resolve_api_key(digest))
        self.assertEqual([k["id"] for k in self.store.list_api_keys("u1")], ["key_pg3"])


if __name__ == "__main__":
    unittest.main()
