"""`GET /api/builder/tools` says what is left of the allowance - audit H4.

With `BUILDER_PLATFORM_FIRECRAWL_DEFAULT` on, `research_market_landscape` is
publishable with no credential of the author's own and is bounded instead by
`BUILDER_PLATFORM_FIRECRAWL_DAILY_CAP` per user per UTC day. A palette that
offers the tool and cannot say how much of the day is left would be offering an
allowance nobody can see, which is a smaller version of the finding this whole
change answers - so the catalogue route now carries the figure beside the
entries it bounds.

Served on the catalogue rather than as a route of its own because it is a fact
ABOUT one of the entries there. There is deliberately no UI for it yet; this
module is the server half, and the client half is a follow-up.

No cost: a synthetic app over in-memory SQLite. No network, no model.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from brief_crew import config as project_config
from tests.service.identities import ALICE, AuthenticatedTwoUserCase

try:  # pragma: no cover - the service extra is optional, as elsewhere in tests/
    from fastapi.testclient import TestClient  # noqa: F401

    FASTAPI_AVAILABLE = True
except Exception:  # pragma: no cover
    FASTAPI_AVAILABLE = False

TOOLS = "/api/builder/tools"
PROVIDER = project_config.PLATFORM_FIRECRAWL_PROVIDER


@unittest.skipUnless(FASTAPI_AVAILABLE, "FastAPI service extra is not installed")
class PlatformFirecrawlVisibilityTests(AuthenticatedTwoUserCase):
    def block(self, headers: dict[str, str] | None = None) -> dict:
        response = self.client.get(TOOLS, headers=headers if headers is not None else self.as_alice())
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertIn("platform_firecrawl", body)
        return body["platform_firecrawl"]

    def store(self):
        persistence = getattr(self.app.state.run_registry, "persistence", None)
        self.assertTrue(
            hasattr(persistence, "claim_platform_quota"),
            "the synthetic app has no store to meter against",
        )
        return persistence

    def test_it_carries_exactly_the_three_keys_the_client_needs(self) -> None:
        self.assertEqual(
            set(self.block()), {"enabled", "cap", "used_today"}
        )

    def test_the_cap_is_the_configured_daily_allowance(self) -> None:
        self.assertEqual(
            self.block()["cap"], project_config.BUILDER_PLATFORM_FIRECRAWL_DAILY_CAP
        )

    def test_enabled_follows_the_flag_in_both_directions(self) -> None:
        with patch.object(project_config, "BUILDER_PLATFORM_FIRECRAWL_DEFAULT", True):
            self.assertIs(self.block()["enabled"], True)
        with patch.object(project_config, "BUILDER_PLATFORM_FIRECRAWL_DEFAULT", False):
            self.assertIs(self.block()["enabled"], False)

    def test_used_today_counts_this_callers_own_claims_and_nobody_elses(self) -> None:
        store = self.store()
        self.assertEqual(self.block()["used_today"], 0)

        for _ in range(3):
            store.claim_platform_quota(ALICE.id, PROVIDER, 50)
        store.claim_platform_quota("user_bob", PROVIDER, 50)

        self.assertEqual(self.block()["used_today"], 3)
        self.assertEqual(self.block(self.as_bob())["used_today"], 1)

    def test_an_anonymous_caller_is_refused_by_the_endpoints_own_gate(self) -> None:
        """MEASURED, and it contradicts the route's own docstring.

        `list_tools` says "No auth for the builtins - it is a description of
        this build, like the vocabulary". That is not what the deployed app
        does: with `VALIDATOR_REQUIRE_AUTH` on, `current_user` refuses an
        anonymous caller with 401 before the handler runs. So the allowance
        block cannot be an oracle for whether an account exists, because
        nobody without an account reaches it - and the `owner is None` branch
        in `_platform_firecrawl` is reachable only on an auth-off deployment,
        where there is one author and nothing to leak.

        Asserted rather than corrected: the route's docstring is not this
        change's to rewrite, and a test that pins what the endpoint really
        does is worth more than one written from what it claims.
        """

        anonymous = self.client.get(TOOLS)
        self.assertEqual(anonymous.status_code, 401, anonymous.text)

    def test_a_deployment_with_no_identity_reads_zero_rather_than_failing(self) -> None:
        """The `owner is None` branch, which an auth-off checkout is all of."""

        from brief_crew.service.app import create_app

        with patch.object(project_config, "AUTH_BASE_URL", ""), patch.object(
            project_config, "VALIDATOR_REQUIRE_AUTH", False
        ):
            from fastapi.testclient import TestClient

            open_app = create_app(synthetic=True)
            with TestClient(open_app) as client:
                body = client.get(TOOLS).json()
        block = body["platform_firecrawl"]
        self.assertEqual(block["used_today"], 0)
        self.assertEqual(
            block["cap"], project_config.BUILDER_PLATFORM_FIRECRAWL_DAILY_CAP
        )

    def test_the_tools_list_is_unchanged_beside_it(self) -> None:
        """An additive key, so no client that reads `tools` can be broken by it."""

        from brief_crew.builder.tools import catalogue

        body = self.client.get(TOOLS, headers=self.as_alice()).json()
        self.assertEqual(
            [entry["tool_id"] for entry in body["tools"]],
            [entry.id for entry in catalogue()],
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
