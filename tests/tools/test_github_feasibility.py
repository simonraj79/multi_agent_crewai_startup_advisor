from __future__ import annotations

import json
import os
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from brief_crew.schemas import Repo
from brief_crew.tools.github_feasibility import (
    AUTHENTICATED_REQUESTS_PER_MINUTE,
    GITHUB_USER_AGENT,
    UNAUTHENTICATED_REQUESTS_PER_MINUTE,
    GitHubFeasibilityTool,
    _TOKEN_BUCKETS,
)
from brief_crew.validator_guardrails import is_reusable_repository


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


ENVELOPE_KEYS = {
    "status",
    "tool",
    "query",
    "retrieved_at",
    "result_count",
    "results",
    "notes",
}


def _as_repo(row: dict, *, relevance: str) -> dict:
    """What the Feasibility Analyst has to do to a tool row, minimally.

    Two steps, and both are the point of rubric review finding F4. The
    `query_term_overlap` evidence is DROPPED - `Repo` sets `extra="forbid"`, so
    a row pasted straight from the envelope is rejected outright - and
    `relevance` is SUPPLIED, because the tool no longer offers one. Copying is
    not merely discouraged now; it does not validate.
    """

    return {k: v for k, v in row.items() if k != "query_term_overlap"} | {
        "relevance": relevance
    }


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
                    "archived": False,
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
                "query_term_overlap": {
                    "matched": ["automation", "clinic", "intake"],
                    "query_terms": ["automation", "clinic", "intake"],
                },
                "url": "https://github.com/clinic/intake-automation",
                "archived": False,
            },
        )
        # The envelope reports the overlap and stops. `relevance` is the
        # analyst's call, so the row is deliberately NOT a complete `Repo` -
        # see test_the_envelope_is_not_directly_schema_valid below.
        self.assertTrue(
            is_reusable_repository(
                Repo.model_validate(
                    _as_repo(envelope["results"][0], relevance="SOLVES_ENTIRELY")
                )
            )
        )
        self.assertEqual(bucket.acquire.call_count, 2)
        self.assertTrue(all(call.kwargs["headers"]["User-Agent"] == GITHUB_USER_AGENT for call in get.call_args_list))
        self.assertTrue(all("Authorization" not in call.kwargs["headers"] for call in get.call_args_list))

    def _run_with_payloads(
        self,
        get: MagicMock,
        *,
        search_item: dict[str, object],
        repository: dict[str, object],
    ) -> tuple[dict[str, object], MagicMock]:
        """Drive one search + one repository detail response through the tool."""
        get.side_effect = [
            _Response(200, {"items": [search_item]}),
            _Response(200, repository),
        ]
        bucket = MagicMock()
        with patch.dict(
            "brief_crew.tools.github_feasibility._TOKEN_BUCKETS",
            {False: bucket},
            clear=True,
        ):
            envelope = json.loads(self.tool._run("clinic intake automation", limit=1))
        return envelope, bucket

    @patch.dict(os.environ, {}, clear=True)
    @patch("brief_crew.tools.github_feasibility._utc_now")
    @patch("brief_crew.tools.github_feasibility.requests.get")
    def test_archived_costs_no_extra_request_per_repository(
        self,
        get: MagicMock,
        utc_now: MagicMock,
    ) -> None:
        """R-7: `archived` rides the two calls the tool already makes, not a third."""
        utc_now.return_value = datetime(2026, 8, 29, tzinfo=timezone.utc)

        envelope, bucket = self._run_with_payloads(
            get,
            search_item={
                "full_name": "clinic/abandoned-intake",
                "html_url": "https://github.com/clinic/abandoned-intake",
            },
            repository={
                "full_name": "clinic/abandoned-intake",
                "html_url": "https://github.com/clinic/abandoned-intake",
                "license": {"spdx_id": "MIT"},
                "pushed_at": "2022-01-01T00:00:00Z",
                "archived": True,
            },
        )

        self.assertEqual(envelope["status"], "ok")
        self.assertTrue(envelope["results"][0]["archived"])
        # One search plus one detail call, exactly as before this field existed.
        self.assertEqual(get.call_count, 2)
        self.assertEqual(bucket.acquire.call_count, 2)

    @patch.dict(os.environ, {}, clear=True)
    @patch("brief_crew.tools.github_feasibility._utc_now")
    @patch("brief_crew.tools.github_feasibility.requests.get")
    def test_archived_falls_back_to_the_search_item(
        self,
        get: MagicMock,
        utc_now: MagicMock,
    ) -> None:
        """Search items are full repository representations and carry it too."""
        utc_now.return_value = datetime(2026, 8, 29, tzinfo=timezone.utc)

        envelope, bucket = self._run_with_payloads(
            get,
            search_item={
                "full_name": "clinic/intake-automation",
                "html_url": "https://github.com/clinic/intake-automation",
                "archived": False,
            },
            repository={
                "full_name": "clinic/intake-automation",
                "html_url": "https://github.com/clinic/intake-automation",
                "license": {"spdx_id": "MIT"},
                "pushed_at": "2026-06-29T00:00:00Z",
            },
        )

        self.assertIs(envelope["results"][0]["archived"], False)
        self.assertEqual(bucket.acquire.call_count, 2)

    @patch.dict(os.environ, {}, clear=True)
    @patch("brief_crew.tools.github_feasibility._utc_now")
    @patch("brief_crew.tools.github_feasibility.requests.get")
    def test_unreported_archive_state_stays_null_not_false(
        self,
        get: MagicMock,
        utc_now: MagicMock,
    ) -> None:
        """"Not reported" must never read as "confirmed still maintained"."""
        utc_now.return_value = datetime(2026, 8, 29, tzinfo=timezone.utc)

        envelope, _ = self._run_with_payloads(
            get,
            search_item={
                "full_name": "clinic/intake-automation",
                "html_url": "https://github.com/clinic/intake-automation",
            },
            repository={
                "full_name": "clinic/intake-automation",
                "html_url": "https://github.com/clinic/intake-automation",
                "license": {"spdx_id": "MIT"},
                "pushed_at": "2026-06-29T00:00:00Z",
                "archived": "no",
            },
        )

        self.assertIsNone(envelope["results"][0]["archived"])
        self.assertIn("archived is null rather than false", envelope["notes"])

    @patch.dict(os.environ, {}, clear=True)
    @patch("brief_crew.tools.github_feasibility._utc_now")
    @patch("brief_crew.tools.github_feasibility.requests.get")
    def test_unknown_push_date_is_null_not_a_negative_sentinel(
        self,
        get: MagicMock,
        utc_now: MagicMock,
    ) -> None:
        """The tool used to emit -1, which `Repo.months_since_push` (ge=0)
        rejects: an honest copy failed validation, so the only routes through
        were to drop the repository or invent an age."""
        utc_now.return_value = datetime(2026, 8, 29, tzinfo=timezone.utc)

        envelope, _ = self._run_with_payloads(
            get,
            search_item={
                "full_name": "clinic/intake-automation",
                "html_url": "https://github.com/clinic/intake-automation",
            },
            repository={
                "full_name": "clinic/intake-automation",
                "html_url": "https://github.com/clinic/intake-automation",
                "license": {"spdx_id": "MIT"},
                "archived": False,
                # GitHub reported no pushed_at at all.
            },
        )

        row = envelope["results"][0]
        self.assertIsNone(row["months_since_push"])
        self.assertIn("months_since_push", envelope["notes"])
        self.assertIn("null is not 'pushed recently'", envelope["notes"])
        # The schema accepts the row once the analyst has added the judgement
        # the tool no longer makes for them.
        repo = Repo.model_validate(_as_repo(row, relevance="PARTIAL"))
        self.assertIsNone(repo.months_since_push)
        self.assertFalse(is_reusable_repository(repo))

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
        self.assertEqual(set(envelope), ENVELOPE_KEYS)
        self.assertEqual(
            get.call_args.kwargs["headers"]["Authorization"],
            "Bearer test-token",
        )
        self.assertEqual(bucket.acquire.call_count, 1)

    @patch.dict(os.environ, {}, clear=True)
    @patch("brief_crew.tools.github_feasibility.requests.get")
    def test_failed_search_reports_status_and_invents_nothing(self, get: MagicMock) -> None:
        import requests

        get.side_effect = requests.ConnectionError("no route to host")
        bucket = MagicMock()

        with patch.dict(
            "brief_crew.tools.github_feasibility._TOKEN_BUCKETS",
            {False: bucket},
            clear=True,
        ):
            envelope = json.loads(self.tool._run("clinic intake automation"))

        self.assertEqual(envelope["status"], "failed")
        self.assertEqual(envelope["results"], [])
        self.assertEqual(envelope["result_count"], 0)
        self.assertEqual(set(envelope), ENVELOPE_KEYS)
        self.assertIn("ConnectionError", envelope["notes"])


if __name__ == "__main__":
    unittest.main()