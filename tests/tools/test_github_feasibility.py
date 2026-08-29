from __future__ import annotations

import json
import os
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from brief_crew.tools.github_feasibility import (
    AUTHENTICATED_REQUESTS_PER_MINUTE,
    GITHUB_USER_AGENT,
    UNAUTHENTICATED_REQUESTS_PER_MINUTE,
    GitHubFeasibilityTool,
    _TOKEN_BUCKETS,
)


class _Response:
    def __init__(
        self,
        status_code: int,
        payload: dict[str, object],
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            import requests

            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self) -> dict[str, object]:
        return self._payload


class GitHubFeasibilityToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tool = GitHubFeasibilityTool()

    def test_module_buckets_have_required_shared_rates(self) -> None:
        self.assertEqual(
            _TOKEN_BUCKETS[False].rate_per_minute,
            UNAUTHENTICATED_REQUESTS_PER_MINUTE,
        )
        self.assertEqual(UNAUTHENTICATED_REQUESTS_PER_MINUTE, 8)
        self.assertEqual(
            _TOKEN_BUCKETS[True].rate_per_minute,
            AUTHENTICATED_REQUESTS_PER_MINUTE,
        )
        self.assertEqual(AUTHENTICATED_REQUESTS_PER_MINUTE, 24)

    @patch.dict(os.environ, {}, clear=True)
    @patch("brief_crew.tools.github_feasibility._utc_now")
    @patch("brief_crew.tools.github_feasibility.requests.get")
    def test_returns_license_activity_relevance_and_user_agent(
        self,
        get: MagicMock,
        utc_now: MagicMock,
    ) -> None:
        utc_now.return_value = datetime(2026, 8, 29, tzinfo=timezone.utc)
        get.side_effect = [
            _Response(
                200,
                {
                    "items": [
                        {
                            "full_name": "clinic/intake-automation",
                            "html_url": "https://github.com/clinic/intake-automation",
                        }
                    ]
                },
            ),
            _Response(
                200,
                {
                    "full_name": "clinic/intake-automation",
                    "name": "intake-automation",
                    "description": "Clinic intake automation forms and workflow",
                    "topics": ["clinic", "intake", "automation"],
                    "html_url": "https://github.com/clinic/intake-automation",
                    "license": {"spdx_id": "MIT"},
                    "pushed_at": "2026-06-29T00:00:00Z",
                },
            ),
        ]
        bucket = MagicMock()

        with patch.dict(
            "brief_crew.tools.github_feasibility._TOKEN_BUCKETS",
            {False: bucket},
            clear=True,
        ):
            envelope = json.loads(self.tool._run("  clinic intake automation  ", limit=1))

        self.assertEqual(envelope["status"], "ok")
        self.assertEqual(envelope["tool"], "assess_technical_feasibility")
        self.assertEqual(envelope["query"], "clinic intake automation")
        self.assertEqual(envelope["result_count"], 1)
        self.assertEqual(
            envelope["results"][0],
            {
                "name": "clinic/intake-automation",
                "license_permits_commercial": True,
                "months_since_push": 2,
                "relevance": "SOLVES_ENTIRELY",
                "url": "https://github.com/clinic/intake-automation",
            },
        )
        self.assertEqual(bucket.acquire.call_count, 2)
        self.assertTrue(all(call.kwargs["headers"]["User-Agent"] == GITHUB_USER_AGENT for call in get.call_args_list))
        self.assertTrue(all("Authorization" not in call.kwargs["headers"] for call in get.call_args_list))

    @patch.dict(os.environ, {"GITHUB_TOKEN": "test-token"}, clear=True)
    @patch("brief_crew.tools.github_feasibility.requests.get")
    def test_authenticated_rate_limit_discards_results(self, get: MagicMock) -> None:
        get.return_value = _Response(
            403,
            {"message": "API rate limit exceeded"},
            {"X-RateLimit-Remaining": "0"},
        )
        bucket = MagicMock()

        with patch.dict(
            "brief_crew.tools.github_feasibility._TOKEN_BUCKETS",
            {True: bucket},
            clear=True,
        ):
            envelope = json.loads(self.tool._run("clinic intake automation"))

        self.assertEqual(envelope["status"], "rate_limited")
        self.assertEqual(envelope["results"], [])
        self.assertEqual(envelope["result_count"], 0)
        self.assertEqual(
            get.call_args.kwargs["headers"]["Authorization"],
            "Bearer test-token",
        )
        self.assertEqual(bucket.acquire.call_count, 1)


if __name__ == "__main__":
    unittest.main()