"""Deep links import `trace_id_for` and never re-derive it (criterion 20).

`observability/backend.py::trace_id_for` is the exporter's own rule for
turning an app run id into a Langfuse trace id: the id's UUID hex, else the
SDK's seeded id, else a sha256 prefix. The link builder **imports** it.

A second spelling here would be a link that resolves for a UUID run id and
resolves to nothing for every other kind - which is exactly the case nobody
would test, because every run id this service mints today is a UUID and the
ones that are not come from a resume, a fixture or somebody's curl.

The measured pairing is asserted by value, not by re-running the function:
run `073c021f-4ff7-43e1-84d5-d9e8dd7fa0ba` traces as
`073c021f4ff743e184d5d9e8dd7fa0ba`, which is the pairing
`docs/observability/evidence/` recorded.

`/links` is the other half, and its rule is `exporter_state`'s: **never a
key, never a URL with userinfo.** Constants only.
"""

from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from brief_crew import config
from brief_crew.service import providers
from tests.service.admin_fixtures import (
    ALICE,
    RUN_TRACE_HEX,
    RUN_UUID,
    AdminCase,
)

PROJECT = "cmf0examplelangfuseproj"
HOST = "https://us.cloud.langfuse.com"


class TraceIdImportTests(unittest.TestCase):
    def test_the_link_builder_uses_the_exporters_own_function(self) -> None:
        """Patch `trace_id_for` and the link moves. A copy would not.

        This is the same construction criterion 8 uses for the two registry
        prefixes, and for the same reason: there is no way to write a
        re-derivation that passes it.
        """

        from brief_crew.service.admin_api import langfuse_links

        with patch.object(config, "LANGFUSE_PROJECT_ID", PROJECT), patch.object(
            config, "LANGFUSE_BASE_URL", HOST
        ), patch(
            "brief_crew.observability.backend.trace_id_for",
            return_value="deadbeefdeadbeefdeadbeefdeadbeef",
        ):
            links = langfuse_links(RUN_UUID)
        self.assertEqual(
            links.trace_url, f"{HOST}/project/{PROJECT}/traces/deadbeefdeadbeefdeadbeefdeadbeef"
        )

    def test_the_measured_pairing(self) -> None:
        """The value `docs/observability/evidence/` recorded, not a re-run."""

        from brief_crew.observability.backend import trace_id_for
        from brief_crew.service.admin_api import langfuse_links

        self.assertEqual(trace_id_for(RUN_UUID), RUN_TRACE_HEX)
        with patch.object(config, "LANGFUSE_PROJECT_ID", PROJECT), patch.object(
            config, "LANGFUSE_BASE_URL", HOST
        ):
            links = langfuse_links(RUN_UUID)
        self.assertEqual(links.session_url, f"{HOST}/project/{PROJECT}/sessions/{RUN_UUID}")
        self.assertEqual(links.trace_url, f"{HOST}/project/{PROJECT}/traces/{RUN_TRACE_HEX}")

    def test_a_non_uuid_run_id_still_gets_a_trace_link(self) -> None:
        """The branch a re-derivation would have got wrong.

        `trace_id_for` falls through to the SDK's seeded id and then to a
        sha256 prefix, and both are 32 hex characters. A link builder that
        only knew `UUID(...).hex` would produce nothing here.
        """

        from brief_crew.service.admin_api import langfuse_links

        with patch.object(config, "LANGFUSE_PROJECT_ID", PROJECT), patch.object(
            config, "LANGFUSE_BASE_URL", HOST
        ):
            links = langfuse_links("not-a-uuid-at-all")
        self.assertIsNotNone(links.trace_url)
        trace_id = links.trace_url.rsplit("/", 1)[-1]
        self.assertEqual(len(trace_id), 32)
        self.assertRegex(trace_id, r"^[0-9a-f]{32}$")

    def test_no_project_id_means_no_link_rather_than_a_broken_one(self) -> None:
        """A URL built without a project id 404s in somebody's browser and
        looks like the console lying. Two nulls is the honest answer."""

        from brief_crew.service.admin_api import langfuse_links

        with patch.object(config, "LANGFUSE_PROJECT_ID", ""):
            links = langfuse_links(RUN_UUID)
        self.assertIsNone(links.session_url)
        self.assertIsNone(links.trace_url)

    def test_a_trailing_slash_on_the_host_does_not_double(self) -> None:
        from brief_crew.service.admin_api import langfuse_links

        with patch.object(config, "LANGFUSE_PROJECT_ID", PROJECT), patch.object(
            config, "LANGFUSE_BASE_URL", HOST + "/"
        ):
            links = langfuse_links(RUN_UUID)
        self.assertNotIn("//project", links.session_url.replace("https://", ""))


class LinksRouteTests(AdminCase):
    def test_the_shape_and_the_three_human_pages(self) -> None:
        body = self.ok("/links")
        self.assertEqual(
            set(body),
            {
                "langfuse",
                "openrouter_activity_url",
                "openrouter_credits_url",
                "firecrawl_dashboard_url",
            },
        )
        self.assertEqual(body["openrouter_activity_url"], "https://openrouter.ai/activity")
        self.assertEqual(
            body["openrouter_credits_url"], "https://openrouter.ai/settings/credits"
        )
        self.assertEqual(
            body["firecrawl_dashboard_url"],
            "https://www.firecrawl.dev/app/settings?tab=billing",
        )

    def test_unconfigured_langfuse_says_so_rather_than_offering_a_url(self) -> None:
        body = self.ok("/links")
        self.assertFalse(body["langfuse"]["configured"])
        self.assertEqual(body["langfuse"]["project_id"], "")

    def test_configured_langfuse_reports_the_project(self) -> None:
        with patch.object(config, "LANGFUSE_PROJECT_ID", PROJECT), patch.object(
            config, "LANGFUSE_BASE_URL", HOST
        ):
            body = self.ok("/links")
        self.assertTrue(body["langfuse"]["configured"])
        self.assertEqual(body["langfuse"]["project_id"], PROJECT)
        self.assertEqual(body["langfuse"]["base_url"], HOST)

    def test_a_run_row_carries_the_pair_when_a_project_is_configured(self) -> None:
        self.seed_run(RUN_UUID, user_id=ALICE.id, cost="0.0500")
        with patch.object(config, "LANGFUSE_PROJECT_ID", PROJECT), patch.object(
            config, "LANGFUSE_BASE_URL", HOST
        ):
            row = self.ok("/runs")["rows"][0]
        self.assertEqual(
            row["langfuse"]["session_url"], f"{HOST}/project/{PROJECT}/sessions/{RUN_UUID}"
        )
        self.assertEqual(
            row["langfuse"]["trace_url"], f"{HOST}/project/{PROJECT}/traces/{RUN_TRACE_HEX}"
        )

    def test_no_key_reaches_links_providers_or_health(self) -> None:
        """Criterion 18 at the ROUTE layer, on the three that could leak one.

        Seeded fake keys, searched for in every serialised body - the
        `identities.py::SECRET` technique. `/links` publishes
        `LANGFUSE_BASE_URL`, which is a host a deployment configured
        deliberately; the two Langfuse KEYS never appear anywhere.
        """

        import os

        secrets = {
            "OPENROUTER_API_KEY": "sk-or-v1-NEVER-ON-THE-WIRE-0123456789",
            "OPENROUTER_MANAGEMENT_KEY": "sk-or-mgmt-NEVER-ON-THE-WIRE-0123",
            "FIRECRAWL_API_KEY": "fc-NEVER-ON-THE-WIRE-0123456789",
            "LANGFUSE_PUBLIC_KEY": "pk-lf-NEVER-ON-THE-WIRE-0123456789",
            "LANGFUSE_SECRET_KEY": "sk-lf-NEVER-ON-THE-WIRE-0123456789",
            "CREDENTIALS_MASTER_KEY": "bWFzdGVyLU5FVkVSLU9OLVRIRS1XSVJFISE=",
            "DATABASE_URL": "postgresql://user:pgpassword-NEVER-ON-THE-WIRE@host/db",
        }
        # The probe functions are replaced for the length of this test. With
        # the fake keys in the environment the real ones would DIAL - a real
        # outbound request to OpenRouter and Firecrawl from a unit test, which
        # this suite must never make. Their answers are echoed back with the
        # key inside, which is the hostile case this test is about anyway.
        def echoing(*_: object, **__: object) -> dict:
            return providers.unavailable(
                "OpenRouter answered HTTP 401"
            ) | {"label": None}

        with patch.dict(os.environ, secrets), patch.object(
            providers, "openrouter_balance", echoing
        ), patch.object(providers, "firecrawl_credits", echoing), patch.object(
            providers, "langfuse_billed", lambda run_id, **_: echoing()
        ):
            bodies = [
                self.ok("/links"),
                self.ok("/providers"),
                self.ok("/health"),
                self.ok("/summary"),
            ]
        rendered = json.dumps(bodies, default=str)
        for name, value in secrets.items():
            with self.subTest(key=name):
                self.assertNotIn(value, rendered)
                self.assertNotIn(value[:16], rendered)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
