"""`/runs/{id}/billed` against a mocked Langfuse (plan 17 criterion 19).

**No test in this file makes a network call.** Every request goes through an
`httpx.MockTransport` and every key is set with `patch.dict(os.environ, ...)`.

Four facts about the v2 API decide the request, and three of them fail
SILENTLY rather than loudly - which is why each one has an assertion of its
own rather than being reviewed:

* **`fields=core,basic,usage`.** The default `core,basic` omits **every** cost
  field, so a reader that does not ask gets a 200 carrying observations with
  no costs and concludes the run was free. This is the one that would ship.
* **`sessionId` is a FILTER, not a query parameter.** The named parameters do
  not include it, and `filter` takes precedence over them anyway.
* **There is no `page`.** Paging follows `meta.cursor`, bounded at
  `LANGFUSE_BILLED_PAGE_LIMIT`.
* **`calculatedTotalCost` was v1 and is gone.** `costDetails.total` is the
  figure, with the flat `totalCost` as the fallback.

And the comparison this route exists for: the billed figure beside the app's
own `run_node_metrics` estimate, with the percentage between them - which is
what the Money banner's error band is measured against.
"""

from __future__ import annotations

import json
import os
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import httpx

from brief_crew import config
from brief_crew.service import providers
from tests.service.admin_fixtures import ALICE, AdminCase

LF_PUBLIC = "pk-lf-0123456789-NEVER-ON-THE-WIRE"
LF_SECRET = "sk-lf-0123456789-NEVER-ON-THE-WIRE"
PROJECT = "cmf0examplelangfuseproj"


def observation(cost: float | None, *, source: str = "openrouter-billed") -> dict:
    row: dict = {"id": "obs", "type": "GENERATION", "metadata": {"cost_source": source}}
    if cost is not None:
        row["costDetails"] = {"input": cost / 2, "output": cost / 2, "total": cost}
    return row


class LangfuseRequestTests(unittest.TestCase):
    """What goes OUT, which is where the silent failures live."""

    def setUp(self) -> None:
        super().setUp()
        for item in (
            patch.dict(
                os.environ,
                {"LANGFUSE_PUBLIC_KEY": LF_PUBLIC, "LANGFUSE_SECRET_KEY": LF_SECRET},
            ),
            patch.object(config, "LANGFUSE_PROJECT_ID", PROJECT),
            patch.object(config, "LANGFUSE_BASE_URL", "https://us.cloud.langfuse.com"),
        ):
            item.start()
            self.addCleanup(item.stop)
        self.requests: list[httpx.Request] = []

    def client(self, pages: list[dict]) -> httpx.Client:
        remaining = list(pages)

        def handler(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            return httpx.Response(200, json=remaining.pop(0) if remaining else {"data": []})

        return httpx.Client(transport=httpx.MockTransport(handler))

    def query(self, index: int = 0) -> dict:
        return parse_qs(urlparse(str(self.requests[index].url)).query)

    def test_it_asks_for_the_usage_fields(self) -> None:
        """The one that would ship: without this the run reads as free."""

        providers.langfuse_billed(
            "r-1", client=self.client([{"data": [observation(0.01)]}])
        )
        self.assertEqual(self.query()["fields"], ["core,basic,usage"])

    def test_the_session_is_selected_by_a_filter_and_not_a_parameter(self) -> None:
        providers.langfuse_billed(
            "run-abc", client=self.client([{"data": [observation(0.01)]}])
        )
        query = self.query()
        self.assertNotIn("sessionId", query)
        clause = json.loads(query["filter"][0])
        self.assertEqual(
            clause,
            [
                {
                    "type": "string",
                    "column": "sessionId",
                    "operator": "=",
                    "value": "run-abc",
                }
            ],
        )

    def test_it_asks_only_for_generations(self) -> None:
        providers.langfuse_billed(
            "r-1", client=self.client([{"data": [observation(0.01)]}])
        )
        self.assertEqual(self.query()["type"], ["GENERATION"])

    def test_the_endpoint_is_v2(self) -> None:
        providers.langfuse_billed(
            "r-1", client=self.client([{"data": [observation(0.01)]}])
        )
        self.assertEqual(
            urlparse(str(self.requests[0].url)).path, "/api/public/v2/observations"
        )

    def test_auth_is_http_basic(self) -> None:
        import base64

        providers.langfuse_billed(
            "r-1", client=self.client([{"data": [observation(0.01)]}])
        )
        header = self.requests[0].headers["authorization"]
        self.assertTrue(header.startswith("Basic "))
        decoded = base64.b64decode(header.split(" ", 1)[1]).decode()
        self.assertEqual(decoded, f"{LF_PUBLIC}:{LF_SECRET}")

    def test_it_follows_meta_cursor_and_sums_across_pages(self) -> None:
        answer = providers.langfuse_billed(
            "r-1",
            client=self.client(
                [
                    {"data": [observation(0.01), observation(0.02)], "meta": {"cursor": "c1"}},
                    {"data": [observation(0.03)], "meta": {"cursor": None}},
                ]
            ),
        )
        self.assertEqual(len(self.requests), 2)
        self.assertNotIn("cursor", self.query(0))
        self.assertEqual(self.query(1)["cursor"], ["c1"])
        self.assertEqual(answer["generations"], 3)
        self.assertAlmostEqual(answer["billed_usd"], 0.06)

    def test_paging_stops_at_the_page_limit(self) -> None:
        """A bound rather than trust: a paging bug must not walk a project."""

        def handler(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            return httpx.Response(
                200, json={"data": [observation(0.01)], "meta": {"cursor": "always"}}
            )

        with patch.object(config, "LANGFUSE_BILLED_PAGE_LIMIT", 3):
            answer = providers.langfuse_billed(
                "r-1", client=httpx.Client(transport=httpx.MockTransport(handler))
            )
        self.assertEqual(len(self.requests), 3)
        self.assertEqual(answer["generations"], 3)

    def test_the_flat_total_cost_is_the_fallback(self) -> None:
        answer = providers.langfuse_billed(
            "r-1",
            client=self.client([{"data": [{"id": "o", "totalCost": 0.05}]}]),
        )
        self.assertAlmostEqual(answer["billed_usd"], 0.05)

    def test_cost_sources_are_counted(self) -> None:
        answer = providers.langfuse_billed(
            "r-1",
            client=self.client(
                [
                    {
                        "data": [
                            observation(0.01),
                            observation(0.02),
                            observation(0.03, source="app-estimate"),
                        ]
                    }
                ]
            ),
        )
        self.assertEqual(
            answer["cost_source_counts"], {"openrouter-billed": 2, "app-estimate": 1}
        )

    def test_no_observations_is_not_a_zero(self) -> None:
        """Langfuse's ingestion lags a run by up to a minute.

        `$0.00` here would be read as a measurement, so the answer says
        `available: false` with the reason instead. Observability defect 4 is
        the same mistake with the other provider.
        """

        answer = providers.langfuse_billed("r-1", client=self.client([{"data": []}]))
        self.assertFalse(answer["available"])
        self.assertIn("ingestion", answer["reason"])
        self.assertIsNone(answer["billed_usd"])

    def test_the_five_failure_modes_degrade(self) -> None:
        def timeout(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("slow", request=request)

        def html(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b"<html>nope</html>")

        cases = {
            "401": lambda request: httpx.Response(401, json={}),
            "500": lambda request: httpx.Response(500, json={}),
            "timeout": timeout,
            "malformed": html,
            "missing data": lambda request: httpx.Response(200, json={"meta": {}}),
        }
        for name, handler in cases.items():
            with self.subTest(failure=name):
                answer = providers.langfuse_billed(
                    "r-1", client=httpx.Client(transport=httpx.MockTransport(handler))
                )
                self.assertFalse(answer["available"])
                self.assertTrue(answer["reason"])

    def test_no_project_id_means_unavailable_and_no_request(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
            raise AssertionError("a lookup with no project id made a request")

        with patch.object(config, "LANGFUSE_PROJECT_ID", ""):
            answer = providers.langfuse_billed(
                "r-1", client=httpx.Client(transport=httpx.MockTransport(handler))
            )
        self.assertFalse(answer["available"])
        self.assertIn("LANGFUSE_PROJECT_ID", answer["reason"])

    def test_no_keys_means_unavailable_and_no_request(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
            raise AssertionError("a lookup with no keys made a request")

        with patch.dict(
            os.environ, {"LANGFUSE_PUBLIC_KEY": "", "LANGFUSE_SECRET_KEY": ""}
        ):
            answer = providers.langfuse_billed(
                "r-1", client=httpx.Client(transport=httpx.MockTransport(handler))
            )
        self.assertFalse(answer["available"])


class BilledRouteTests(AdminCase):
    """The route: the billed figure beside the app's own estimate."""

    def install(self, answer: dict) -> None:
        """Swap the router's probe cache for a double.

        The router builds its cache lazily, by name, on first use - so
        replacing the CLASS is enough and the route under test stays the one
        `create_app` actually mounted. A stub rather than a real
        `ProviderProbes` with an injected probe, because patching the class
        and then constructing it inside the patch is a recursion this test
        found the hard way.
        """

        class Stub:
            def __init__(self, **_: object) -> None:
                pass

            def langfuse_billed(self, run_id: str) -> dict:
                return dict(answer)

            def openrouter(self) -> dict:  # pragma: no cover - not this route
                return providers.unavailable("not configured")

            def firecrawl(self) -> dict:  # pragma: no cover - not this route
                return providers.unavailable("not configured")

        patcher = patch.object(providers, "ProviderProbes", Stub)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_the_billed_figure_is_compared_with_the_estimate(self) -> None:
        self.seed_run("r-1", user_id=ALICE.id, cost="0.05625510")
        self.install(
            {
                "available": True,
                "reason": None,
                "generations": 12,
                "billed_usd": 0.06441798,
                "cost_source_counts": {"openrouter-billed": 12},
                "fetched_at": "2026-09-08T12:03:11Z",
            }
        )
        body = self.ok("/runs/r-1/billed")
        self.assertTrue(body["available"])
        self.assertEqual(body["generations"], 12)
        self.assertEqual(body["billed_usd"], 0.06441798)
        # SIX decimal places, not eight: `run_node_metrics.cost_usd` is
        # NUMERIC(12,6), so the column itself is what rounds here. Asserting
        # the seeded literal would be asserting against a precision the
        # database does not have.
        self.assertEqual(body["estimate_usd"], 0.056255)
        # The band the Money banner quotes, computed rather than restated.
        self.assertAlmostEqual(body["delta_pct"], 14.51, places=1)
        self.assertEqual(body["cost_source_counts"], {"openrouter-billed": 12})

    def test_an_unavailable_lookup_is_200_and_not_a_500(self) -> None:
        self.seed_run("r-1", user_id=ALICE.id, cost="0.0500")
        self.install(
            {
                "available": False,
                "reason": "LANGFUSE_PROJECT_ID is unset, so there is no project to read",
            }
        )
        response = self.get("/runs/r-1/billed")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertFalse(body["available"])
        self.assertIn("LANGFUSE_PROJECT_ID", body["reason"])
        # The estimate is still there: the app's own figure does not depend on
        # the upstream that could not answer.
        self.assertEqual(body["estimate_usd"], 0.05)
        self.assertIsNone(body["delta_pct"])

    def test_a_run_with_no_estimate_has_no_percentage(self) -> None:
        """Division by zero is not a percentage, and `0` would read as agreement."""

        self.seed_run("r-free", user_id=ALICE.id, cost=None)
        self.install(
            {"available": True, "generations": 1, "billed_usd": 0.01, "reason": None}
        )
        body = self.ok("/runs/r-free/billed")
        self.assertEqual(body["estimate_usd"], 0.0)
        self.assertIsNone(body["delta_pct"])

    def test_the_shape_is_section_3s(self) -> None:
        self.seed_run("r-1", user_id=ALICE.id, cost="0.0500")
        self.install({"available": False, "reason": "nothing configured"})
        self.assertEqual(
            set(self.ok("/runs/r-1/billed")),
            {
                "available",
                "reason",
                "run_id",
                "generations",
                "billed_usd",
                "estimate_usd",
                "delta_pct",
                "cost_source_counts",
                "session_url",
                "trace_url",
                "fetched_at",
            },
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
