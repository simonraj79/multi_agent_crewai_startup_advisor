"""A resolved credential reaches the tool and nothing else - plan 06 criterion 3.

The criterion asks that a tool frame captured during a run contain no substring
of the credential. That is asserted here at the two places it can actually be
decided, because a frame is only ever as safe as the two of them:

1. **The redaction walk.** `events/redaction.py::is_secret_key` is what the
   frame serializer and the persistence walk both ask, and this file proves it
   answers True for every field name a tool constructor here is handed -
   `api_key`, `gh_token`, `db_uri`, `headers`, `token`, `dsn`. Plan 06 D4 asks
   for those to be ADDED to `_SECRET_KEYS`; they were already there, three by
   name and the rest through the suffix rule, so the repair is a test rather
   than an edit and this file is that test.

2. **The serializer, end to end.** A frame is built with the real
   `events/serializer.py` over a payload carrying a plaintext key under each of
   those names, and the rendered frame is searched for the key.

Both halves are needed. A redaction list that is right about names proves
nothing if the walk does not consult it, and a serializer that redacts one
frame proves nothing about the name a later tool uses.

No cost: this builds frames in memory. No network, no model, no vault.
"""

from __future__ import annotations

import json
import unittest

from brief_crew.events.redaction import REDACTED, is_secret_key

#: Distinctive enough that a substring search cannot pass by luck. The
#: single-character key an earlier draft used answered "leaked" for every tool,
#: because "x" appears in the word "text".
SECRET = "sk-or-v1-LEAK-CANARY-0123456789abcdef"

#: Every constructor keyword a factory in `builder/tools.py` hands a plaintext
#: to, plus the two field names the classes hold them under. Read off the
#: factories rather than invented: `api_key=` on the Firecrawl classes and
#: Tavily and Exa, `gh_token`/`token` on GitHub, `db_uri` on NL2SQL, `headers`
#: on URLRead, and the two environment names `_env_scoped` writes.
CREDENTIAL_KEYS = (
    "api_key",
    "apiKey",
    "gh_token",
    "token",
    "db_uri",
    "dsn",
    "headers",
    "Authorization",
    "SERPER_API_KEY",
    "BRAVE_API_KEY",
    "FIRECRAWL_API_KEY",
    "GITHUB_TOKEN",
)


class RedactionListTests(unittest.TestCase):
    """D4's request, checked rather than performed: they are already covered."""

    def test_every_credential_carrying_key_a_factory_uses_is_secret(self) -> None:
        for key in CREDENTIAL_KEYS:
            with self.subTest(key=key):
                self.assertTrue(
                    is_secret_key(key),
                    f"{key!r} carries a plaintext credential in builder/tools.py and "
                    "the redaction walk does not treat it as secret",
                )

    def test_a_key_that_merely_NAMES_a_credential_is_not_redacted(self) -> None:
        """The other half, and the one a wider list would break.

        `credential_id` is an opaque reference the canvas has to be able to
        render, and `body_key` is the structural name `STRUCTURAL_KEY_NAMES`
        exists for. A redaction rule that swallowed either would hide the
        document from its own author.
        """

        self.assertFalse(is_secret_key("body_key"))
        self.assertFalse(is_secret_key("tool_id"))


class SerializedFrameTests(unittest.TestCase):
    """The walk, end to end, over a payload shaped like a real tool frame."""

    def _serialized(self, payload: dict) -> str:
        """Through the REAL serializer's own `clip`, not a stand-in.

        `FieldBoundedSerializer.clip` is what every frame in this service goes
        through on the way to the ring, the socket, `/frames` and the NDJSON
        export. A test that re-implemented the redaction would be asserting
        about its own copy.
        """

        from brief_crew.events.serializer import FieldBoundedSerializer

        return json.dumps(FieldBoundedSerializer().clip(payload))

    def test_no_credential_bearing_key_survives_into_a_tool_frame(self) -> None:
        payload = {
            "tool_id": "firecrawl_search",
            "status": "ok",
            "query": "a market",
            **{key: SECRET for key in CREDENTIAL_KEYS},
        }
        rendered = self._serialized(payload)
        self.assertNotIn(SECRET, rendered)
        self.assertIn(REDACTED, rendered)
        # And the frame is still USEFUL: what plan 12 renders survives.
        self.assertIn("firecrawl_search", rendered)
        self.assertIn("a market", rendered)

    def test_a_credential_nested_inside_a_tool_result_is_redacted_too(self) -> None:
        """A custom tool echoes the request it made, so the header travels one
        level down rather than at the top."""

        payload = {
            "tool_id": "ut_0123456789ab",
            "results": [
                {
                    "url": "https://api.example.test/x",
                    "headers": {"Authorization": SECRET},
                }
            ],
        }
        self.assertNotIn(SECRET, self._serialized(payload))

    def test_a_dsn_inside_free_TEXT_is_stripped_on_the_way_to_a_ROW(self) -> None:
        """The password a key name cannot protect, and where the two walks differ.

        `postgres_query` is handed a DSN, and a DSN carries its own password
        inside a string. `persistence._redact_text` strips it on the way to a
        row - asserted here - and the serializer's `clip`, which is what reaches
        the RING and the live socket, does NOT. That asymmetry is pre-existing
        and outside plan 06's surfaces; it is a follow-up in the report rather
        than a fix here, and this test records exactly which half holds so the
        next reader does not have to find out by leaking one.
        """

        from brief_crew.service.persistence import _redact_text
        from brief_crew.events.serializer import FieldBoundedSerializer

        dsn = "postgresql://user:hunter2@db.example.test/app"
        self.assertNotIn("hunter2", _redact_text(dsn))
        # The other half, stated rather than hidden.
        self.assertIn("hunter2", FieldBoundedSerializer().clip({"note": dsn})["note"])

    def test_the_KEY_a_dsn_arrives_under_is_redacted_by_both_walks(self) -> None:
        """Which is why the gap above is narrow: a DSN reaches a frame under
        `db_uri` or `dsn`, and both are secret names."""

        rendered = self._serialized(
            {"db_uri": "postgresql://user:hunter2@db.example.test/app"}
        )
        self.assertNotIn("hunter2", rendered)


if __name__ == "__main__":
    unittest.main()
