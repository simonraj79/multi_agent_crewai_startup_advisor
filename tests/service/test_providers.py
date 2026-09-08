"""The three probes: keys at call time, five failures, a TTL (14-18).

**No test in this file makes a network call.** Every one injects an
`httpx.MockTransport`, and every one also clears the real keys from
`os.environ` first - belt and braces, because the harness's own
`tests/__init__.py` puts a placeholder in the environment with `setdefault`,
which means a developer with a real `.env` has the REAL key there. A probe
that reached its HTTP path with that key would dial OpenRouter for money's
sake with nobody watching.

The five criteria, and what each is really about:

* **14** - keys are read from `os.environ` at CALL time, never captured at
  construction. `HttpCostLookup`'s stated reason: the probe cache is built
  once at startup and a deployment may set the variable afterwards, and a
  captured credential is a credential living in an object graph for the life
  of the process for no benefit. Asserted by setting the variable AFTER the
  object exists.
* **15/16** - the two rungs, both spellings, and five failure modes each:
  401, 500, timeout, malformed JSON, missing field. **Never a raise.**
* **17** - two calls inside the TTL make ONE request, the body says how old
  the answer is, and a FAILURE is cached too.
* **18** - no key, and no URL containing one, reaches any serialised body.
"""

from __future__ import annotations

import json
import os
import unittest
from unittest.mock import patch

import httpx

from brief_crew import config
from brief_crew.service import providers

#: Obviously fake, obviously greppable - the `identities.py::SECRET` technique.
#: Every "no key on the wire" assertion searches responses for these.
OR_KEY = "sk-or-v1-0123456789abcdef-NEVER-ON-THE-WIRE"
MGMT_KEY = "sk-or-mgmt-0123456789abcdef-NEVER-ON-THE-WIRE"
FC_KEY = "fc-0123456789abcdef-NEVER-ON-THE-WIRE"
LF_PUBLIC = "pk-lf-0123456789-NEVER-ON-THE-WIRE"
LF_SECRET = "sk-lf-0123456789-NEVER-ON-THE-WIRE"
SECRETS = (OR_KEY, MGMT_KEY, FC_KEY, LF_PUBLIC, LF_SECRET)

CLEARED = {
    "OPENROUTER_API_KEY": "",
    "OPENROUTER_MANAGEMENT_KEY": "",
    "FIRECRAWL_API_KEY": "",
    "LANGFUSE_PUBLIC_KEY": "",
    "LANGFUSE_SECRET_KEY": "",
}


def mock_client(handler) -> httpx.Client:
    """One `httpx.Client` that can only ever reach the handler."""

    return httpx.Client(transport=httpx.MockTransport(handler))


def json_response(payload: object, status: int = 200):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=payload)

    return handler


class NoKeysCase(unittest.TestCase):
    """Every case starts with an environment that carries no upstream key."""

    def setUp(self) -> None:
        super().setUp()
        patcher = patch.dict(os.environ, CLEARED)
        patcher.start()
        self.addCleanup(patcher.stop)


class KeysAreReadAtCallTimeTests(NoKeysCase):
    """Criterion 14, and the assertion is the ORDER of two statements."""

    def test_a_key_set_after_the_cache_exists_is_used(self) -> None:
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request.headers.get("authorization", ""))
            return httpx.Response(200, json={"data": {"total_credits": 30.0, "total_usage": 2.45}})

        # Built while the environment is EMPTY.
        cache = providers.ProviderProbes(
            openrouter_probe=lambda: providers.openrouter_balance(
                client=mock_client(handler)
            )
        )
        self.assertFalse(os.environ.get("OPENROUTER_MANAGEMENT_KEY"))
        # Set afterwards - the deployment case.
        with patch.dict(os.environ, {"OPENROUTER_MANAGEMENT_KEY": MGMT_KEY}):
            answer = cache.openrouter()
        self.assertTrue(answer["available"])
        self.assertEqual(seen, [f"Bearer {MGMT_KEY}"])

    def test_with_no_key_at_all_the_probe_never_dials(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
            raise AssertionError("a probe with no key made a request")

        answer = providers.openrouter_balance(client=mock_client(handler))
        self.assertFalse(answer["available"])
        self.assertIn("OPENROUTER_MANAGEMENT_KEY", answer["reason"])

    def test_the_same_is_true_of_firecrawl_and_langfuse(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
            raise AssertionError("a probe with no key made a request")

        self.assertFalse(providers.firecrawl_credits(client=mock_client(handler))["available"])
        self.assertFalse(
            providers.langfuse_billed("r-1", client=mock_client(handler))["available"]
        )


class OpenRouterRungTests(NoKeysCase):
    """Criterion 15: two rungs, and the tile says which one answered."""

    def test_a_management_key_reads_credits(self) -> None:
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(str(request.url))
            return httpx.Response(
                200, json={"data": {"total_credits": 30.0, "total_usage": 2.45}}
            )

        with patch.dict(os.environ, {"OPENROUTER_MANAGEMENT_KEY": MGMT_KEY}):
            answer = providers.openrouter_balance(client=mock_client(handler))
        self.assertTrue(answer["available"])
        self.assertEqual(answer["source"], "credits")
        self.assertEqual(answer["total_credits"], 30.0)
        self.assertEqual(answer["total_usage"], 2.45)
        self.assertEqual(answer["remaining_usd"], 27.55)
        self.assertEqual(seen, [config.OPENROUTER_CREDITS_URL])

    def test_without_one_it_falls_to_the_ordinary_key(self) -> None:
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(str(request.url))
            return httpx.Response(
                200,
                json={
                    "data": {
                        "label": "studio",
                        "usage": 10.25,
                        "limit": 50.0,
                        "limit_remaining": 39.75,
                        "is_free_tier": False,
                    }
                },
            )

        with patch.dict(os.environ, {"OPENROUTER_API_KEY": OR_KEY}):
            answer = providers.openrouter_balance(client=mock_client(handler))
        self.assertTrue(answer["available"])
        self.assertEqual(answer["source"], "key")
        self.assertEqual(answer["usage"], 10.25)
        self.assertEqual(answer["limit"], 50.0)
        self.assertEqual(answer["limit_remaining"], 39.75)
        self.assertEqual(seen, [config.OPENROUTER_KEY_URL])

    def test_the_key_rung_reports_no_remaining_balance(self) -> None:
        """A key limit is not an account balance.

        Putting one in the other's field is how a tile starts lying: the owner
        would read a per-key allowance as the money left in the account.
        """

        with patch.dict(os.environ, {"OPENROUTER_API_KEY": OR_KEY}):
            answer = providers.openrouter_balance(
                client=mock_client(json_response({"data": {"usage": 1.0}}))
            )
        self.assertIsNone(answer["remaining_usd"])
        self.assertIsNone(answer["total_credits"])

    def test_a_404_on_the_documented_url_retries_the_vault_spelling_once(self) -> None:
        """The plan's one UNVERIFIED fact, coded as a retry rather than a guess.

        The vendor docs name `/api/v1/key`; this repository's own vault probe
        has always used `/api/v1/auth/key`, and whether they are aliases is
        undocumented. So a 404 - and ONLY a 404 - tries the second, once.
        """

        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(str(request.url))
            if str(request.url) == config.OPENROUTER_KEY_URL:
                return httpx.Response(404, json={"error": "not found"})
            return httpx.Response(200, json={"data": {"usage": 3.0}})

        with patch.dict(os.environ, {"OPENROUTER_API_KEY": OR_KEY}):
            answer = providers.openrouter_balance(client=mock_client(handler))
        self.assertTrue(answer["available"])
        self.assertEqual(
            seen, [config.OPENROUTER_KEY_URL, config.OPENROUTER_KEY_URL_FALLBACK]
        )

    def test_a_401_does_not_retry(self) -> None:
        """A key problem, not a URL problem: the same key at a second URL
        answers the same thing, so trying twice buys nothing and doubles the
        rate-limit cost of a misconfiguration."""

        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(str(request.url))
            return httpx.Response(401, json={"error": "no"})

        with patch.dict(os.environ, {"OPENROUTER_API_KEY": OR_KEY}):
            answer = providers.openrouter_balance(client=mock_client(handler))
        self.assertFalse(answer["available"])
        self.assertEqual(len(seen), 1)
        self.assertIn("401", answer["reason"])

    def test_the_management_key_wins_when_both_are_set(self) -> None:
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(str(request.url))
            return httpx.Response(
                200, json={"data": {"total_credits": 1.0, "total_usage": 0.0}}
            )

        with patch.dict(
            os.environ,
            {"OPENROUTER_MANAGEMENT_KEY": MGMT_KEY, "OPENROUTER_API_KEY": OR_KEY},
        ):
            answer = providers.openrouter_balance(client=mock_client(handler))
        self.assertEqual(answer["source"], "credits")
        self.assertEqual(seen, [config.OPENROUTER_CREDITS_URL])


class OpenRouterDegradationTests(NoKeysCase):
    """The five failure modes. **Never a raise, never a 500.**"""

    def probe(self, handler) -> dict:
        with patch.dict(os.environ, {"OPENROUTER_MANAGEMENT_KEY": MGMT_KEY}):
            return providers.openrouter_balance(client=mock_client(handler))

    def test_a_401_degrades(self) -> None:
        answer = self.probe(json_response({"error": "no"}, 401))
        self.assertFalse(answer["available"])
        self.assertIn("401", answer["reason"])

    def test_a_500_degrades(self) -> None:
        answer = self.probe(json_response({"error": "boom"}, 500))
        self.assertFalse(answer["available"])
        self.assertIn("500", answer["reason"])

    def test_a_timeout_degrades(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectTimeout("timed out", request=request)

        answer = self.probe(handler)
        self.assertFalse(answer["available"])
        self.assertIn("ConnectTimeout", answer["reason"])

    def test_malformed_json_degrades(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b"<html>not json at all</html>")

        answer = self.probe(handler)
        self.assertFalse(answer["available"])
        self.assertIn("not JSON", answer["reason"])

    def test_a_missing_field_degrades(self) -> None:
        answer = self.probe(json_response({"data": {"something_else": 1}}))
        self.assertFalse(answer["available"])
        self.assertIn("total_credits", answer["reason"])


class FirecrawlTests(NoKeysCase):
    """Criterion 16: one code path reads camelCase AND snake_case."""

    def probe(self, handler) -> dict:
        with patch.dict(os.environ, {"FIRECRAWL_API_KEY": FC_KEY}):
            return providers.firecrawl_credits(client=mock_client(handler))

    def test_the_v2_camelcase_shape(self) -> None:
        answer = self.probe(
            json_response(
                {
                    "success": True,
                    "data": {
                        "remainingCredits": 1000,
                        "planCredits": 500000,
                        "billingPeriodStart": "2026-09-01T00:00:00Z",
                        "billingPeriodEnd": "2026-10-01T00:00:00Z",
                    },
                }
            )
        )
        self.assertTrue(answer["available"])
        self.assertEqual(answer["remaining_credits"], 1000)
        self.assertEqual(answer["plan_credits"], 500000)
        self.assertEqual(answer["billing_period_end"], "2026-10-01T00:00:00Z")

    def test_the_v1_snake_case_shape_through_the_same_path(self) -> None:
        """Four lines against a whole class of silent `None`.

        Without the second spelling a perfectly configured account renders as
        "0 credits" - a wrong answer that looks like a real measurement.
        """

        answer = self.probe(
            json_response(
                {
                    "success": True,
                    "data": {
                        "remaining_credits": 1000,
                        "plan_credits": 500000,
                        "billing_period_start": "2026-09-01T00:00:00Z",
                        "billing_period_end": "2026-10-01T00:00:00Z",
                    },
                }
            )
        )
        self.assertTrue(answer["available"])
        self.assertEqual(answer["remaining_credits"], 1000)
        self.assertEqual(answer["plan_credits"], 500000)

    def test_a_401_a_500_a_timeout_malformed_json_and_a_missing_field(self) -> None:
        def timeout(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("slow", request=request)

        def html(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b"<html>nope</html>")

        cases = {
            "401": json_response({}, 401),
            "500": json_response({}, 500),
            "timeout": timeout,
            "malformed": html,
            "missing": json_response({"success": True, "data": {"planCredits": 1}}),
        }
        for name, handler in cases.items():
            with self.subTest(failure=name):
                answer = self.probe(handler)
                self.assertFalse(answer["available"])
                self.assertTrue(answer["reason"])

    def test_zero_remaining_credits_is_an_ANSWER_and_not_a_failure(self) -> None:
        """The one boundary a naive falsy check gets wrong.

        An account that has spent everything reports `0`, and `0` is exactly
        the number the owner most needs to see.
        """

        answer = self.probe(json_response({"data": {"remainingCredits": 0}}))
        self.assertTrue(answer["available"])
        self.assertEqual(answer["remaining_credits"], 0)


class CacheTests(NoKeysCase):
    """Criterion 17: one request per window, an age, and failures cached too."""

    def setUp(self) -> None:
        super().setUp()
        self.now = 1000.0
        self.calls = 0

    def clock(self) -> float:
        return self.now

    def probe(self) -> dict:
        self.calls += 1
        return {
            "available": True,
            "reason": None,
            "source": "credits",
            "total_credits": 30.0,
            "total_usage": 2.45,
            "remaining_usd": 27.55,
            "checked_at": "2026-09-08T11:59:00Z",
            "age_seconds": 0.0,
        }

    def test_two_calls_inside_the_window_make_one_request(self) -> None:
        cache = providers.ProviderProbes(clock=self.clock, openrouter_probe=self.probe)
        with patch.object(config, "ADMIN_PROVIDER_CACHE_SECONDS", 60.0):
            first = cache.openrouter()
            self.now += 12.0
            second = cache.openrouter()
        self.assertEqual(self.calls, 1)
        self.assertEqual(first["age_seconds"], 0.0)
        self.assertEqual(second["age_seconds"], 12.0)
        self.assertEqual(first["remaining_usd"], second["remaining_usd"])

    def test_past_the_window_it_asks_again(self) -> None:
        cache = providers.ProviderProbes(clock=self.clock, openrouter_probe=self.probe)
        with patch.object(config, "ADMIN_PROVIDER_CACHE_SECONDS", 60.0):
            cache.openrouter()
            self.now += 61.0
            cache.openrouter()
        self.assertEqual(self.calls, 2)

    def test_a_failure_is_cached_too(self) -> None:
        """A dead upstream is not hammered once per page load by every open
        dashboard - the expensive case is the one that repeats."""

        failures = 0

        def failing() -> dict:
            nonlocal failures
            failures += 1
            return providers.unavailable("OpenRouter answered HTTP 500")

        cache = providers.ProviderProbes(clock=self.clock, openrouter_probe=failing)
        with patch.object(config, "ADMIN_PROVIDER_CACHE_SECONDS", 60.0):
            for _ in range(5):
                answer = cache.openrouter()
        self.assertEqual(failures, 1)
        self.assertFalse(answer["available"])

    def test_both_arms_reach_the_client_with_the_same_key_set(self) -> None:
        """So `adminApi.ts` reads one shape and the model can forbid extras."""

        cache = providers.ProviderProbes(
            clock=self.clock,
            openrouter_probe=self.probe,
            firecrawl_probe=lambda: providers.unavailable("FIRECRAWL_API_KEY is unset"),
        )
        good = cache.openrouter()
        bad = providers.ProviderProbes(
            clock=self.clock,
            openrouter_probe=lambda: providers.unavailable("nope"),
        ).openrouter()
        self.assertEqual(set(good), set(bad))
        self.assertIn("age_seconds", bad)
        self.assertIsNone(bad["remaining_usd"])

    def test_the_billed_lookup_is_not_cached(self) -> None:
        """On an explicit click, one run at a time - and a second click is
        somebody asking precisely because the first answer was too early."""

        calls = 0

        def billed(run_id: str) -> dict:
            nonlocal calls
            calls += 1
            return {"available": True, "generations": 1, "billed_usd": 0.1}

        cache = providers.ProviderProbes(clock=self.clock, billed_probe=billed)
        cache.langfuse_billed("r-1")
        cache.langfuse_billed("r-1")
        self.assertEqual(calls, 2)


class NoKeyOnTheWireTests(NoKeysCase):
    """Criterion 18, on the probe layer: no key in any returned value."""

    def assertNoSecret(self, value: object) -> None:
        rendered = json.dumps(value, default=str)
        for secret in SECRETS:
            self.assertNotIn(secret, rendered)
            # And no fragment of one either - a truncated key is still a key.
            self.assertNotIn(secret[:20], rendered)

    def test_a_success_carries_no_key(self) -> None:
        with patch.dict(os.environ, {"OPENROUTER_MANAGEMENT_KEY": MGMT_KEY}):
            self.assertNoSecret(
                providers.openrouter_balance(
                    client=mock_client(
                        json_response({"data": {"total_credits": 1.0, "total_usage": 0.0}})
                    )
                )
            )

    def test_a_401_body_is_never_echoed(self) -> None:
        """The likeliest place a vendor echoes something back is the body of a
        4xx from a credential-bearing endpoint, so the body is not read at all
        - the status code is the whole of what the console is told."""

        with patch.dict(os.environ, {"OPENROUTER_MANAGEMENT_KEY": MGMT_KEY}):
            answer = providers.openrouter_balance(
                client=mock_client(
                    json_response({"error": f"bad key: {MGMT_KEY}"}, 401)
                )
            )
        self.assertNoSecret(answer)

    def test_a_transport_error_message_is_never_echoed(self) -> None:
        """`httpx` puts the request URL in some error messages, and a URL can
        carry a credential in its userinfo - so the CLASS name goes into the
        sentence and the message does not."""

        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError(
                f"failed connecting to https://user:{MGMT_KEY}@openrouter.ai",
                request=request,
            )

        with patch.dict(os.environ, {"OPENROUTER_MANAGEMENT_KEY": MGMT_KEY}):
            answer = providers.openrouter_balance(client=mock_client(handler))
        self.assertNoSecret(answer)
        self.assertIn("ConnectError", answer["reason"])

    def test_firecrawl_and_langfuse_the_same(self) -> None:
        with patch.dict(os.environ, {"FIRECRAWL_API_KEY": FC_KEY}):
            self.assertNoSecret(
                providers.firecrawl_credits(
                    client=mock_client(json_response({"error": FC_KEY}, 403))
                )
            )
        with patch.dict(
            os.environ,
            {"LANGFUSE_PUBLIC_KEY": LF_PUBLIC, "LANGFUSE_SECRET_KEY": LF_SECRET},
        ), patch.object(config, "LANGFUSE_PROJECT_ID", "proj"):
            self.assertNoSecret(
                providers.langfuse_billed(
                    "r-1", client=mock_client(json_response({"error": LF_SECRET}, 401))
                )
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
