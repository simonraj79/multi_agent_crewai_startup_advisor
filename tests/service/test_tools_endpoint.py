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

import threading
import time
import unittest
from typing import Any
from unittest.mock import patch

from brief_crew import config as project_config
from brief_crew.builder import tools as tools_module
from brief_crew.builder.tools import catalogue
from tests.service.identities import ALICE_TOKEN, AuthenticatedTwoUserCase

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
    # The six `types/builder.ts::BuilderToolCatalogueEntry` already declared,
    # and which `NodePalette.vue`, `BuilderNode.vue` and `ToolForm.vue` already
    # read. The key is `tool_id` and not `id`: plan 06's Interfaces section
    # writes `id`, three client files written before the catalogue existed read
    # `tool_id`, and two of them are outside this plan's surfaces - so the
    # client's spelling is the contract and the plan's is the correction.
    "tool_id",
    "label",
    "category",
    "description",
    "credential_kind",
    "attaches_to",
    "params",
    # And the plan's own additions, each answering a question the six cannot.
    "credential_kind_by_param",
    "credential_optional",
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
            [entry["tool_id"] for entry in served], [entry.id for entry in catalogue()]
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
        self.assertNotIn("code_interpreter", [entry["tool_id"] for entry in served])
        with patch.object(project_config, "BUILDER_CODE_INTERPRETER_ENABLED", True):
            lifted = self.client.get(TOOLS, headers=self.as_alice()).json()["tools"]
        self.assertEqual(len(lifted), 11)
        self.assertIn("code_interpreter", [entry["tool_id"] for entry in lifted])

    def test_no_entry_carries_a_class_ref_or_any_other_server_side_key(self) -> None:
        served = self.client.get(TOOLS, headers=self.as_alice()).json()["tools"]
        for entry in served:
            with self.subTest(tool=entry["tool_id"]):
                self.assertEqual(set(entry), ENTRY_KEYS)
                self.assertNotIn("class_ref", entry)
                self.assertNotIn("factory", entry)

    def test_every_param_is_declared_with_a_type_and_a_default(self) -> None:
        """The gauntlet forbids a parameter rendered in the UI that the compiler
        ignores, and this is the other side of it: every parameter an author can
        set is DECLARED, with the bound the server checks it against, so a
        control the server would refuse cannot be drawn."""

        types = {"string", "number", "integer", "boolean", "array", "json"}
        for entry in self.client.get(TOOLS, headers=self.as_alice()).json()["tools"]:
            for param in entry["params"]:
                with self.subTest(tool=entry["tool_id"], param=param["name"]):
                    self.assertIn(param["type"], types)
                    self.assertIn("default", param)
                    self.assertIs(param["required"], False)

    def test_every_tool_attaches_to_the_kinds_the_server_would_accept(self) -> None:
        """`attach-target-not-agent` is what the server answers otherwise, so an
        entry advertising a third target would be advertising a refused drop."""

        from brief_crew.builder.document import ATTACH_TARGET_KINDS

        for entry in self.client.get(TOOLS, headers=self.as_alice()).json()["tools"]:
            with self.subTest(tool=entry["tool_id"]):
                self.assertEqual(set(entry["attaches_to"]), set(ATTACH_TARGET_KINDS))

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
        self.assertIn(created["id"], [entry["tool_id"] for entry in listed])

    def test_it_appears_in_NOBODY_elses_catalogue(self) -> None:
        created = self.create(self.as_alice())
        listed = self.client.get(TOOLS, headers=self.as_bob()).json()["tools"]
        self.assertNotIn(created["id"], [entry["tool_id"] for entry in listed])

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
        self.assertNotIn(created["id"], [entry["tool_id"] for entry in listed])

    def test_the_ceiling_is_a_422_naming_the_ceiling(self) -> None:
        from unittest.mock import patch

        with patch.object(project_config, "MAX_CUSTOM_TOOLS_PER_USER", 1):
            self.create(self.as_alice())
            response = self.client.post(
                CUSTOM, json={**WEATHER, "name": "another_one"}, headers=self.as_alice()
            )
        self.assertEqual(response.status_code, 422, response.text)
        self.assertIn("ceiling is 1", response.json()["detail"])


@unittest.skipUnless(FASTAPI_AVAILABLE, "FastAPI service extra is not installed")
class TestRouteOffTheLoopTests(AuthenticatedTwoUserCase):
    """Audit H5: `POST .../custom/{id}/test` must not park the event loop.

    The route is `async def` and called `tool._run()` synchronously - one
    blocking httpx call to a host the CALLER chose, with a timeout that is per
    READ and no total deadline at all, so a server emitting one byte every 29
    seconds holds the whole process until `max_response_bytes` arrives. Nothing
    rate-limits the route either. The credential probe two routers over is
    rate-limited and `discover_mcp_server` is a plain `def` for exactly this
    reason; this one was neither.

    Both halves are asserted: that the call is handed to the threadpool, and -
    the property that actually matters - that a second request is served while
    the first is still sleeping.
    """

    SLEEP_SECONDS = 1.0
    #: Well under the sleep, and far above what an in-process GET costs.
    RESPONSIVE_SECONDS = 0.5

    def _tool_id(self) -> str:
        created = self.client.post(CUSTOM, json=WEATHER, headers=self.as_alice())
        self.assertEqual(created.status_code, 201, created.text)
        return created.json()["id"]

    @staticmethod
    def _public(_host: str) -> list[str]:
        """`api.example.test` resolves to nothing; the vetting needs an answer."""

        return ["93.184.216.34"]

    def test_H5_the_blocking_call_is_handed_to_the_threadpool(self) -> None:
        import starlette.concurrency as concurrency

        real = concurrency.run_in_threadpool
        handed: list[Any] = []

        async def recording(func: Any, *args: Any, **kwargs: Any) -> Any:
            handed.append(func)
            return await real(func, *args, **kwargs)

        tool_id = self._tool_id()
        with (
            patch.object(tools_module, "_default_resolver", self._public),
            patch.object(
                tools_module,
                "_default_transport",
                lambda *_a, **_k: (200, "{}"),
            ),
            patch.object(concurrency, "run_in_threadpool", recording),
        ):
            response = self.client.post(
                f"{CUSTOM}/{tool_id}/test", json={"args": {"city": "Lisbon"}},
                headers=self.as_alice(),
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["envelope"]["status"], "ok")
        self.assertEqual(len(handed), 1, "the tool call did not go to the threadpool")

    def test_H5_a_second_request_is_served_while_the_test_call_is_still_dialling(self) -> None:
        """One portal, one loop, two requests - which is the whole question.

        A `TestClient` used as a context manager runs ONE event loop for its
        lifetime; used per-request it spins a fresh portal each time, and two
        separate loops could not show this either way.
        """

        from fastapi.testclient import TestClient

        tool_id = self._tool_id()
        started = threading.Event()

        def slow_transport(*_args: Any, **_kwargs: Any) -> tuple[int, str]:
            started.set()
            time.sleep(self.SLEEP_SECONDS)
            return 200, "{}"

        with TestClient(self.app) as client:
            headers = {"Authorization": f"Bearer {ALICE_TOKEN}"}
            outcome: list[Any] = []

            def call_test_route() -> None:
                outcome.append(
                    client.post(
                        f"{CUSTOM}/{tool_id}/test",
                        json={"args": {"city": "Lisbon"}},
                        headers=headers,
                    )
                )

            with (
                patch.object(tools_module, "_default_resolver", self._public),
                patch.object(tools_module, "_default_transport", slow_transport),
            ):
                worker = threading.Thread(target=call_test_route, daemon=True)
                worker.start()
                self.assertTrue(started.wait(timeout=10), "the tool call never began")

                began = time.monotonic()
                catalogue_response = client.get(TOOLS, headers=headers)
                elapsed = time.monotonic() - began

                worker.join(timeout=30)

        self.assertEqual(catalogue_response.status_code, 200, catalogue_response.text)
        self.assertLess(
            elapsed,
            self.RESPONSIVE_SECONDS,
            f"the loop was parked: a plain GET took {elapsed:.2f}s while one "
            f"custom-tool test call slept {self.SLEEP_SECONDS}s",
        )
        self.assertEqual(outcome[0].status_code, 200, outcome[0].text)


if __name__ == "__main__":
    unittest.main()
