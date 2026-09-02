"""`/api/builder/credentials` - plan 01 C4, from the outside.

Four routes and a read, every one behind an identity, and none of them ever
returns a field. That last property is asserted the only way it can be: every
response body in this file is searched for the plaintext fixture, including
the 422s - `credentials_api.py` parses the body by hand precisely so that a
malformed request is never echoed back with the key inside it.

Isolation is asserted from both sides in the same test: Alice's row answers
200 for Alice and 404 - never 403 - for Bob on GET, DELETE and the probe,
because a 403 would confirm the row exists.

The probe is stubbed at `credentials_api.probe_credential`, so nothing here
touches a network; the one probe that is NOT stubbed is a format-only kind,
which `probe_credential` answers without sending anything anywhere and says so.
"""

from __future__ import annotations

import re
import unittest
from typing import Any
from unittest.mock import patch

from brief_crew import config
from brief_crew.service.credentials import ProbeResult
from tests.service.identities import (
    CREDENTIALS,
    SECRET,
    AuthenticatedTwoUserCase,
)

try:  # pragma: no cover
    from fastapi.testclient import TestClient  # noqa: F401

    FASTAPI_AVAILABLE = True
except Exception:  # pragma: no cover
    FASTAPI_AVAILABLE = False

PUBLIC_KEYS = {"id", "kind", "label", "created_at", "updated_at", "last_used_at"}
CREDENTIAL_ID = re.compile(config.CREDENTIAL_ID_PATTERN)


@unittest.skipUnless(FASTAPI_AVAILABLE, "FastAPI service extra is not installed")
class RoundTripTests(AuthenticatedTwoUserCase):
    def test_create_answers_201_with_exactly_the_public_shape(self) -> None:
        created = self.create_credential(self.as_alice())
        self.assertEqual(set(created), PUBLIC_KEYS)
        self.assertRegex(created["id"], CREDENTIAL_ID)
        self.assertEqual(created["kind"], "openrouter")
        self.assertEqual(created["label"], "My OpenRouter key")
        self.assertIsNone(created["last_used_at"])

    def test_list_get_and_delete_round_trip_and_never_carry_a_field(self) -> None:
        created = self.create_credential(self.as_alice())

        listed = self.client.get(CREDENTIALS, headers=self.as_alice())
        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertEqual([row["id"] for row in listed.json()], [created["id"]])
        self.assertEqual(set(listed.json()[0]), PUBLIC_KEYS)
        self.assertNotIn(SECRET, listed.text)
        self.assertNotIn("api_key", listed.text)

        got = self.client.get(f"{CREDENTIALS}/{created['id']}", headers=self.as_alice())
        self.assertEqual(got.status_code, 200, got.text)
        self.assertEqual(got.json(), created)
        self.assertNotIn(SECRET, got.text)

        deleted = self.client.delete(f"{CREDENTIALS}/{created['id']}", headers=self.as_alice())
        self.assertEqual(deleted.status_code, 204, deleted.text)
        self.assertEqual(self.client.get(CREDENTIALS, headers=self.as_alice()).json(), [])
        self.assertEqual(
            self.client.get(f"{CREDENTIALS}/{created['id']}", headers=self.as_alice()).status_code, 404
        )
        self.assertEqual(
            self.client.delete(f"{CREDENTIALS}/{created['id']}", headers=self.as_alice()).status_code,
            404,
        )

    def test_the_list_is_newest_first_and_scoped_in_sql(self) -> None:
        first = self.create_credential(self.as_alice(), label="first")
        second = self.create_credential(self.as_alice(), label="second")
        self.create_credential(self.as_bob(), label="bob's own")
        listed = [row["label"] for row in self.client.get(CREDENTIALS, headers=self.as_alice()).json()]
        self.assertEqual(listed, ["second", "first"])
        self.assertEqual(
            {row["id"] for row in self.client.get(CREDENTIALS, headers=self.as_bob()).json()} & {first["id"], second["id"]},
            set(),
        )


@unittest.skipUnless(FASTAPI_AVAILABLE, "FastAPI service extra is not installed")
class IsolationTests(AuthenticatedTwoUserCase):
    """Plan 01 D2 rule 3: not-found and not-yours are one 404."""

    def setUp(self) -> None:
        super().setUp()
        self.mine = self.create_credential(self.as_alice())["id"]

    def test_bob_gets_404_on_get_delete_and_test(self) -> None:
        for method, path in (
            ("get", f"{CREDENTIALS}/{self.mine}"),
            ("delete", f"{CREDENTIALS}/{self.mine}"),
            ("post", f"{CREDENTIALS}/{self.mine}/test"),
        ):
            with self.subTest(method=method):
                response = getattr(self.client, method)(path, headers=self.as_bob())
                self.assertEqual(response.status_code, 404, response.text)
                self.assertEqual(response.json()["detail"], "credential not found")
        # And the row is still Alice's, untouched by the DELETE.
        self.assertEqual(self.client.get(f"{CREDENTIALS}/{self.mine}", headers=self.as_alice()).status_code, 200)

    def test_bobs_list_does_not_contain_alices_row(self) -> None:
        self.assertEqual(self.client.get(CREDENTIALS, headers=self.as_bob()).json(), [])

    def test_a_foreign_id_and_an_unknown_id_are_the_same_answer(self) -> None:
        foreign = self.client.get(f"{CREDENTIALS}/{self.mine}", headers=self.as_bob())
        unknown = self.client.get(f"{CREDENTIALS}/cr_00000000", headers=self.as_bob())
        malformed = self.client.get(f"{CREDENTIALS}/not-an-id", headers=self.as_bob())
        self.assertEqual(foreign.json(), unknown.json())
        self.assertEqual(malformed.status_code, 404)


@unittest.skipUnless(FASTAPI_AVAILABLE, "FastAPI service extra is not installed")
class AnonymousTests(AuthenticatedTwoUserCase):
    """Plan 01 D2 rule 1: these rows never existed before auth, so 401, not a public row."""

    def test_every_route_refuses_a_caller_with_no_identity(self) -> None:
        mine = self.create_credential(self.as_alice())["id"]
        for method, path, body in (
            ("get", CREDENTIALS, None),
            ("post", CREDENTIALS, {"kind": "openrouter", "label": "x", "fields": {"api_key": SECRET}}),
            ("get", f"{CREDENTIALS}/{mine}", None),
            ("delete", f"{CREDENTIALS}/{mine}", None),
            ("post", f"{CREDENTIALS}/{mine}/test", None),
        ):
            with self.subTest(method=method, path=path):
                call = getattr(self.client, method)
                response = call(path, json=body) if body is not None else call(path)
                self.assertEqual(response.status_code, 401, response.text)
                self.assertIn("Bearer", response.headers.get("WWW-Authenticate", ""))
                self.assertNotIn(SECRET, response.text)

    def test_a_bad_token_is_refused_the_same_way(self) -> None:
        response = self.client.get(CREDENTIALS, headers=self.auth("nonsense"))
        self.assertEqual(response.status_code, 401)


@unittest.skipUnless(FASTAPI_AVAILABLE, "FastAPI service extra is not installed")
class RefusalTests(AuthenticatedTwoUserCase):
    """Every refusal names a FIELD and never quotes a value."""

    def _post(self, body: Any) -> Any:
        return self.client.post(CREDENTIALS, json=body, headers=self.as_alice())

    def test_an_unknown_kind_is_422_naming_the_kinds(self) -> None:
        response = self._post({"kind": "carrier-pigeon", "label": "x", "fields": {"api_key": SECRET}})
        self.assertEqual(response.status_code, 422, response.text)
        self.assertIn("openrouter", response.json()["detail"])
        self.assertNotIn(SECRET, response.text)

    def test_a_missing_field_is_422_naming_the_field(self) -> None:
        response = self._post({"kind": "openrouter", "label": "x", "fields": {}})
        self.assertEqual(response.status_code, 422, response.text)
        self.assertIn("api_key", response.json()["detail"])

    def test_an_extra_field_is_422_naming_the_extra_and_not_its_value(self) -> None:
        response = self._post(
            {"kind": "openrouter", "label": "x", "fields": {"api_key": SECRET, "bonus": "ALSO-SECRET"}}
        )
        self.assertEqual(response.status_code, 422, response.text)
        self.assertIn("bonus", response.json()["detail"])
        self.assertNotIn(SECRET, response.text)
        self.assertNotIn("ALSO-SECRET", response.text)

    def test_an_empty_value_a_line_break_and_a_non_string_are_422(self) -> None:
        for fields in ({"api_key": "   "}, {"api_key": "a\nb"}, {"api_key": 42}):
            with self.subTest(fields=fields):
                response = self._post({"kind": "openrouter", "label": "x", "fields": fields})
                self.assertEqual(response.status_code, 422, response.text)
                self.assertIn("api_key", response.json()["detail"])

    def test_a_body_that_is_not_an_object_and_fields_that_are_not_are_422(self) -> None:
        self.assertEqual(self.client.post(CREDENTIALS, json=[1], headers=self.as_alice()).status_code, 422)
        self.assertEqual(self._post({"kind": "openrouter", "label": "x", "fields": "sk-x"}).status_code, 422)
        self.assertEqual(self._post({"kind": "openrouter", "label": "x"}).status_code, 422)
        self.assertEqual(self._post({"label": "x", "fields": {"api_key": SECRET}}).status_code, 422)

    def test_a_blank_or_oversized_label_is_422(self) -> None:
        self.assertEqual(self._post({"kind": "openrouter", "label": "  ", "fields": {"api_key": SECRET}}).status_code, 422)
        self.assertEqual(
            self._post({"kind": "openrouter", "label": "x" * 81, "fields": {"api_key": SECRET}}).status_code, 422
        )

    def test_over_the_byte_ceiling_is_413(self) -> None:
        big = "k" * (config.MAX_CREDENTIAL_BYTES + 1)
        response = self._post({"kind": "openrouter", "label": "big", "fields": {"api_key": big}})
        self.assertEqual(response.status_code, 413, response.text)
        self.assertIn(str(config.MAX_CREDENTIAL_BYTES), response.json()["detail"])
        self.assertNotIn(big, response.text)

    def test_a_duplicate_label_is_409_for_the_same_person_only(self) -> None:
        self.create_credential(self.as_alice(), label="the same")
        again = self._post({"kind": "openrouter", "label": "the same", "fields": {"api_key": SECRET}})
        self.assertEqual(again.status_code, 409, again.text)
        # Labels are unique PER USER (15 D6): Bob may use the same words.
        self.create_credential(self.as_bob(), label="the same")


@unittest.skipUnless(FASTAPI_AVAILABLE, "FastAPI service extra is not installed")
class ProbeTests(AuthenticatedTwoUserCase):
    def test_the_probe_decrypts_for_the_owner_and_answers_the_providers_verdict(self) -> None:
        seen: list[tuple[str, dict[str, str]]] = []

        def fake_probe(kind: str, fields: Any, **_: Any) -> ProbeResult:
            seen.append((kind, dict(fields)))
            return ProbeResult(False, "OpenRouter rejected this key (HTTP 401)")

        mine = self.create_credential(self.as_alice())["id"]
        with patch("brief_crew.service.credentials_api.probe_credential", fake_probe):
            response = self.client.post(f"{CREDENTIALS}/{mine}/test", headers=self.as_alice())

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {"ok": False, "detail": "OpenRouter rejected this key (HTTP 401)"})
        # The vault handed the probe the plaintext - proof the row decrypts -
        # and the response carried none of it.
        self.assertEqual(seen, [("openrouter", {"api_key": SECRET})])
        self.assertNotIn(SECRET, response.text)
        # A probe is the author checking a key, not a run using it.
        self.assertIsNone(
            self.client.get(f"{CREDENTIALS}/{mine}", headers=self.as_alice()).json()["last_used_at"]
        )

    def test_a_format_only_kind_is_answered_without_sending_anything(self) -> None:
        mine = self.create_credential(self.as_alice(), kind="firecrawl", label="fc")["id"]
        response = self.client.post(f"{CREDENTIALS}/{mine}/test", headers=self.as_alice())
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertIn("not sent anywhere", body["detail"])
        self.assertNotIn(SECRET, response.text)


@unittest.skipUnless(FASTAPI_AVAILABLE, "FastAPI service extra is not installed")
class ProbeRateLimitTests(AuthenticatedTwoUserCase):
    """A probe is a user-initiated call to a third party: the run limiter charges it."""

    def app_kwargs(self) -> dict[str, Any]:
        from brief_crew.service.app import RunRateLimiter

        return {"synthetic": True, "rate_limiter": RunRateLimiter(max_runs=1, window_seconds=60)}

    def test_the_second_probe_in_the_window_is_429_with_retry_after(self) -> None:
        mine = self.create_credential(self.as_alice(), kind="firecrawl", label="fc")["id"]
        first = self.client.post(f"{CREDENTIALS}/{mine}/test", headers=self.as_alice())
        self.assertEqual(first.status_code, 200, first.text)
        second = self.client.post(f"{CREDENTIALS}/{mine}/test", headers=self.as_alice())
        self.assertEqual(second.status_code, 429, second.text)
        self.assertGreaterEqual(int(second.headers["Retry-After"]), 1)
        # Per person: Bob's bucket is his own.
        his = self.create_credential(self.as_bob(), kind="firecrawl", label="fc")["id"]
        self.assertEqual(self.client.post(f"{CREDENTIALS}/{his}/test", headers=self.as_bob()).status_code, 200)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
