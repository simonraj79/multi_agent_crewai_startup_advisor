"""`/runs/{id}/billed` against a mocked Langfuse (plan 17 criterion 19).

**No test in this file makes a network call.** Every request goes through an
`httpx.MockTransport` and every key is set with `patch.dict(os.environ, ...)`.

Five facts about the v2 API decide the request, and four of them fail
SILENTLY rather than loudly - which is why each one has an assertion of its
own rather than being reviewed:

* **The selector is `traceId`, and this file used to assert the opposite.**
  `sessionId` is a TRACE attribute; on a GENERATION row it is null, so the
  filter clause matched nothing and every lookup answered `{"data": []}`.
  Measured on the paid proof, run `4681d938-427d-4e0c-be85-cc9d84153052`,
  nine minutes after it finished: the sessionId filter gave 0 rows and
  `?traceId=4681d938427d4e0cbe85cc9d84153052` gave 3, each with a
  `costDetails.total`. **The old tests all passed** - they asserted the
  request this code sent, which is the failure mode a mock cannot see, and
  only a real project could.
* **`fields=core,basic,usage`.** The default `core,basic` omits **every** cost
  field, so a reader that does not ask gets a 200 carrying observations with
  no costs and concludes the run was free.
* **There is no `page`.** Paging follows `meta.cursor`, bounded at
  `LANGFUSE_BILLED_PAGE_LIMIT`.
* **`calculatedTotalCost` was v1 and is gone.** `costDetails.total` is the
  figure, with the flat `totalCost` as the fallback.
* **`model` is null too**, for the same class of reason: it is Langfuse's
  RESOLVED model and an `openrouter/...` string matches nothing in its model
  table. `providedModelName` carries what was sent.

The measured run's own rows are the fixture for several tests below, so the
shape being asserted is one a real project produced rather than one this file
invented.

And the comparison this route exists for: the billed figure beside the app's
own `run_node_metrics` estimate, with the percentage between them - which is
what the Money banner's error band is measured against.
"""

from __future__ import annotations

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


#: The run the paid proof measured. Its trace id is the UUID's hex, which is
#: `trace_id_for`'s first branch - so the expected query parameter below is a
#: value taken from production, not one this file computed for itself.
PROOF_RUN = "4681d938-427d-4e0c-be85-cc9d84153052"
PROOF_TRACE = "4681d938427d4e0cbe85cc9d84153052"


def observation(
    cost: float | None,
    *,
    source: str = "openrouter-billed",
    model: str | None = "openrouter/google/gemini-3.8-flash",
) -> dict:
    """One v2 GENERATION row, in the shape production actually returns.

    `sessionId` and `model` are **None**, because that is what the measured
    rows carry - and they are the two nulls that broke the lookup and the
    model breakdown respectively. A fixture that filled them in would let a
    reader of these tests believe the old code worked.
    """

    row: dict = {
        "id": "obs",
        "type": "GENERATION",
        "sessionId": None,
        "model": None,
        "providedModelName": model,
        "metadata": {"cost_source": source},
    }
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

    def test_the_run_is_selected_by_traceId_and_no_filter_is_sent(self) -> None:
        """The defect the paid proof found, asserted from both sides.

        `traceId` carries the hex; NO `filter` and NO `sessionId` parameter is
        sent at all. Both halves matter: sending the filter as well would have
        gone on matching nothing and quietly emptying every page.
        """

        providers.langfuse_billed(
            PROOF_RUN, client=self.client([{"data": [observation(0.01)]}])
        )
        query = self.query()
        self.assertEqual(query["traceId"], [PROOF_TRACE])
        self.assertNotIn("filter", query)
        self.assertNotIn("sessionId", query)

    def test_the_traceId_is_the_one_trace_id_for_derives(self) -> None:
        """IMPORTED, never re-derived - criterion 20's rule on the read too.

        Patching `trace_id_for` moves the query parameter. A second spelling
        here would price a different trace from the one the deep link opens,
        and the two would agree for exactly the UUID run ids everybody tests
        with - which is every run this service mints today.
        """

        from brief_crew.observability.backend import trace_id_for

        self.assertEqual(trace_id_for(PROOF_RUN), PROOF_TRACE)
        with patch(
            "brief_crew.observability.backend.trace_id_for",
            return_value="deadbeefdeadbeefdeadbeefdeadbeef",
        ):
            providers.langfuse_billed(
                PROOF_RUN, client=self.client([{"data": [observation(0.01)]}])
            )
        self.assertEqual(
            self.query()["traceId"], ["deadbeefdeadbeefdeadbeefdeadbeef"]
        )

    def test_a_non_uuid_run_id_still_resolves_to_a_trace(self) -> None:
        """The branch a re-derivation would have got wrong, on the read side.

        `trace_id_for` falls through to the SDK's seeded id and then to a
        sha256 prefix; both are 32 hex characters, and a lookup that only knew
        `UUID(...).hex` would send nothing at all.
        """

        providers.langfuse_billed(
            "not-a-uuid-at-all", client=self.client([{"data": [observation(0.01)]}])
        )
        trace_id = self.query()["traceId"][0]
        self.assertRegex(trace_id, r"^[0-9a-f]{32}$")

    def test_the_measured_rows_are_priced_the_way_production_returned_them(
        self,
    ) -> None:
        """The three rows of run `4681d938-...`, to the cent.

        Their sum is `0.044475`; the trace's own `totalCost` was
        `0.0866014`, which is the whole trace including observations this
        lookup deliberately does not ask for (`type=GENERATION`). The two are
        not supposed to agree and this test says so, so that nobody later
        "fixes" the difference.
        """

        answer = providers.langfuse_billed(
            PROOF_RUN,
            client=self.client(
                [
                    {
                        "data": [
                            observation(0.02100225),
                            observation(0.00313875),
                            observation(0.020334),
                        ]
                    }
                ]
            ),
        )
        self.assertTrue(answer["available"])
        self.assertEqual(answer["generations"], 3)
        self.assertEqual(answer["billed_usd"], 0.044475)

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

    def test_the_model_comes_from_providedModelName_because_model_is_null(
        self,
    ) -> None:
        """`model` is Langfuse's RESOLVED model and is null on these rows.

        A breakdown that read `model` would report every generation of every
        run as `unknown` - a plausible-looking answer, which is what makes it
        worth an assertion rather than a comment.
        """

        answer = providers.langfuse_billed(
            PROOF_RUN,
            client=self.client(
                [
                    {
                        "data": [
                            observation(0.01),
                            observation(0.02),
                            observation(
                                0.03, model="openrouter/google/gemini-3.5-flash-lite"
                            ),
                        ]
                    }
                ]
            ),
        )
        self.assertEqual(
            answer["model_counts"],
            {
                "openrouter/google/gemini-3.8-flash": 2,
                "openrouter/google/gemini-3.5-flash-lite": 1,
            },
        )

    def test_a_row_with_no_model_anywhere_is_counted_as_unknown(self) -> None:
        """Counted, never dropped: a generation nobody can name still cost
        money, and a breakdown that omits it stops summing to the total
        printed beside it."""

        row = observation(0.01, model=None)
        row.pop("providedModelName")
        answer = providers.langfuse_billed(PROOF_RUN, client=self.client([{"data": [row]}]))
        self.assertEqual(answer["model_counts"], {"unknown": 1})
        self.assertEqual(answer["generations"], 1)

    def test_the_resolved_model_wins_when_langfuse_did_match_one(self) -> None:
        """`_MODEL_KEYS` is ordered, and `model` leads it.

        On a project whose model table DOES carry the string, Langfuse fills
        `model` in - and that is the better answer, because it is the one its
        own cost figures were computed against.
        """

        row = observation(0.01)
        row["model"] = "gemini-3.8-flash"
        answer = providers.langfuse_billed(PROOF_RUN, client=self.client([{"data": [row]}]))
        self.assertEqual(answer["model_counts"], {"gemini-3.8-flash": 1})

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
                "model_counts": {"openrouter/google/gemini-3.8-flash": 12},
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
        self.assertEqual(
            body["model_counts"], {"openrouter/google/gemini-3.8-flash": 12}
        )

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
                "model_counts",
                "session_url",
                "trace_url",
                "fetched_at",
            },
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
