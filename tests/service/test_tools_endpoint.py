"""`/api/builder/tools` and the custom-tool routes - plan 06 criteria 1 and 6.

Criterion 1 is a shape claim with a sharp edge: the entry the client sees must
carry no `class_ref`. Asserting the ABSENCE of one named key would pass while a
`factory` reached the wire beside it, so the assertion here is over the whole
key set - which is the only version of "no server-side field is serialised" that
stays true when somebody adds a field to the dataclass.

The custom-tool round trip is here rather than in `tests/builder/` because the
thing under test is the ROUTE: who may call it, what a bad grid is answered
with, and that a stranger's tool is 404 and never 403.

No cost: a synthetic app over in-memory SQLite. No network, no model.
"""

from __future__ import annotations

import unittest
from typing import Any

from brief_crew import config as project_config
from brief_crew.builder.tools import catalogue
from tests.service.identities import AuthenticatedTwoUserCase

try:  # pragma: no cover - the service extra is optional, as elsewhere in tests/
    from fastapi.testclient import TestClient  # noqa: F401

    FASTAPI_AVAILABLE = True
except Exception:  # pragma: no cover
    FASTAPI_AVAILABLE = False

TOOLS = "/api/builder/tools"
CUSTOM = "/api/builder/tools/custom"

#: The complete wire shape of one entry. Compared as a SET, so a new key has to
#: be added here deliberately - which is what stops `factory` arriving by
#: accident the day somebody adds a field to `ToolCatalogueEntry`.
ENTRY_KEYS = {
    "id",
    "label",
    "category",
    "credential_kind",
    "credential_kind_by_param",
    "credential_optional",
    "param_schema",
    "description",
    "docs_url",
    "owner",
    "available",
    "requires_packages",
    "packages_param",
}

WEATHER = {
    "name": "weather_lookup",
    "description": "Current weather for a city.",
    "properties": [
        {"name": "city", "type": "string", "description": "City", "required": True}
    ],
    "request": {
        "method": "GET",
        "url": "https://api.example.test/weather?q={city}",
        "timeout_seconds": 10,
        "max_response_bytes": 4096,
    },
}


@unittest.skipUnless(FASTAPI_AVAILABLE, "FastAPI service extra is not installed")
class CatalogueTests(AuthenticatedTwoUserCase):
    def test_it_lists_this_deployments_builtins_in_declaration_order(self) -> None:
        response = self.client.get(TOOLS, headers=self.as_alice())
        self.assertEqual(response.status_code, 200, response.text)
        served = response.json()["tools"]
        self.assertEqual(
            [entry["id"] for entry in served], [entry.id for entry in catalogue()]
        )

    def test_the_count_is_ten_with_the_interpreter_flag_off_and_eleven_with_it_on(self) -> None:
        """Plan 06 criterion 1 says ELEVEN, and the honest number here is ten.

        D2's table has eleven rows and its last one is `custom_http:<id>`, which
        is a PER-USER row rather than a builtin - so the builtins are the other
        ten, plus `code_interpreter`, which exists and is withheld behind
        `BUILDER_CODE_INTERPRETER_ENABLED` (PLANS.md decision 3, provisional).
        Turn that flag on and the endpoint answers eleven. Both halves are
        asserted so the arithmetic is on the page rather than in a reader's head.
        """

        from unittest.mock import patch

        served = self.client.get(TOOLS, headers=self.as_alice()).json()["tools"]
        self.assertEqual(len(served), 10)
        self.assertNotIn("code_interpreter", [entry["id"] for entry in served])
        with patch.object(project_config, "BUILDER_CODE_INTERPRETER_ENABLED", True):
            lifted = self.client.get(TOOLS, headers=self.as_alice()).json()["tools"]
        self.assertEqual(len(lifted), 11)
        self.assertIn("code_interpreter", [entry["id"] for entry in lifted])

    def test_no_entry_carries_a_class_ref_or_any_other_server_side_key(self) -> None:
        served = self.client.get(TOOLS, headers=self.as_alice()).json()["tools"]
        for entry in served:
            with self.subTest(tool=entry["id"]):
                self.assertEqual(set(entry), ENTRY_KEYS)
                self.assertNotIn("class_ref", entry)
                self.assertNotIn("factory", entry)

    def test_every_param_schema_is_a_closed_object(self) -> None:
        """`additionalProperties: false`, so a form control the compiler ignores
        is impossible by construction rather than by review."""

        for entry in self.client.get(TOOLS, headers=self.as_alice()).json()["tools"]:
            with self.subTest(tool=entry["id"]):
                self.assertEqual(entry["param_schema"]["type"], "object")
                self.assertIs(entry["param_schema"]["additionalProperties"], False)

    def test_the_vocabulary_serves_the_same_catalogue(self) -> None:
        """One source, two endpoints. A palette reading either must agree."""

        vocabulary = self.client.get("/api/builder/vocabulary").json()
        listed = self.client.get(TOOLS, headers=self.as_alice()).json()["tools"]
        self.assertEqual(vocabulary["tools"], listed)


@unittest.skipUnless(FASTAPI_AVAILABLE, "FastAPI service extra is not installed")
class CustomToolRouteTests(AuthenticatedTwoUserCase):
    def create(self, headers: dict[str, str], **overrides: Any) -> dict[str, Any]:
        response = self.client.post(CUSTOM, json={**WEATHER, **overrides}, headers=headers)
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def test_a_custom_tool_round_trips_and_appears_in_its_owners_catalogue(self) -> None:
        created = self.create(self.as_alice())
        self.assertRegex(created["id"], project_config.CUSTOM_TOOL_ID_PATTERN)
        self.assertEqual(created["entry"]["owner"], "user")
        self.assertEqual(created["entry"]["category"], "custom")

        listed = self.client.get(TOOLS, headers=self.as_alice()).json()["tools"]
        self.assertIn(created["id"], [entry["id"] for entry in listed])

    def test_it_appears_in_NOBODY_elses_catalogue(self) -> None:
        created = self.create(self.as_alice())
        listed = self.client.get(TOOLS, headers=self.as_bob()).json()["tools"]
        self.assertNotIn(created["id"], [entry["id"] for entry in listed])

    def test_another_users_tool_is_404_and_never_403_on_every_verb(self) -> None:
        """A 403 would confirm the row exists, which is an oracle for ids."""

        created = self.create(self.as_alice())
        path = f"{CUSTOM}/{created['id']}"
        self.assertEqual(
            self.client.put(path, json=WEATHER, headers=self.as_bob()).status_code, 404
        )
        self.assertEqual(self.client.delete(path, headers=self.as_bob()).status_code, 404)
        self.assertEqual(
            self.client.post(f"{path}/test", json={"args": {}}, headers=self.as_bob()).status_code,
            404,
        )

    def test_a_bad_grid_is_422_with_a_sentence_an_author_can_act_on(self) -> None:
        response = self.client.post(
            CUSTOM, json={**WEATHER, "name": "Weather Lookup"}, headers=self.as_alice()
        )
        self.assertEqual(response.status_code, 422, response.text)
        self.assertIn("lowercase", response.json()["detail"])

    def test_a_second_tool_with_the_same_name_is_409(self) -> None:
        self.create(self.as_alice())
        response = self.client.post(CUSTOM, json=WEATHER, headers=self.as_alice())
        self.assertEqual(response.status_code, 409, response.text)

    def test_two_people_may_each_have_a_tool_of_the_same_name(self) -> None:
        """The uniqueness is PER USER, which the table's constraint says and
        this asserts, because a global one would let one author's names shadow
        everybody's."""

        self.create(self.as_alice())
        self.create(self.as_bob())

    def test_an_anonymous_caller_is_refused_on_a_service_that_requires_auth(self) -> None:
        """401 on BOTH, and the read is 401 for a reason worth naming.

        `GET /tools` takes `Depends(current_user)`, and on a service with
        `VALIDATOR_REQUIRE_AUTH` that dependency refuses an anonymous caller
        before the handler runs. That is the service's existing rule and this
        route does not get an exception to it - the catalogue is also on
        `GET /api/builder/vocabulary`, which takes no identity and is the route
        a signed-out palette reads. Asserted rather than assumed, because the
        first version of this test asserted 200 and was wrong.
        """

        self.assertEqual(self.client.get(TOOLS).status_code, 401)
        self.assertEqual(self.client.post(CUSTOM, json=WEATHER).status_code, 401)
        self.assertEqual(self.client.get("/api/builder/vocabulary").status_code, 200)

    def test_delete_removes_it_from_the_catalogue(self) -> None:
        created = self.create(self.as_alice())
        self.assertEqual(
            self.client.delete(f"{CUSTOM}/{created['id']}", headers=self.as_alice()).status_code,
            204,
        )
        listed = self.client.get(TOOLS, headers=self.as_alice()).json()["tools"]
        self.assertNotIn(created["id"], [entry["id"] for entry in listed])

    def test_the_ceiling_is_a_422_naming_the_ceiling(self) -> None:
        from unittest.mock import patch

        with patch.object(project_config, "MAX_CUSTOM_TOOLS_PER_USER", 1):
            self.create(self.as_alice())
            response = self.client.post(
                CUSTOM, json={**WEATHER, "name": "another_one"}, headers=self.as_alice()
            )
        self.assertEqual(response.status_code, 422, response.text)
        self.assertIn("ceiling is 1", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()
