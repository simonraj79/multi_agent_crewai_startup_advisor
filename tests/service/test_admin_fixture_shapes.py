"""The real handlers agree with `adminApi.json`, per endpoint (criterion 21).

W-UI builds `services/adminApi.ts` and every admin spec against a committed
fixture, before these handlers exist. That is the only reason three builders
can work at once, and it buys exactly one failure mode: **a mirror that agrees
with itself.** Section 14 defect 2 is the precedent - `PROBLEM_CODES` carried
27 codes where the server emitted 30, and its own anti-rot test read two of the
three files that declare them. The most common problem in the builder was one
the console had never heard of.

Two things close that here and neither is a convention:

* `scripts/emit_admin_fixture.py` builds the fixture from INSTANCES of the
  real response models, so a field added to a model without an example is a
  `ValidationError` when the script runs.
* **This module drives the real routes against a seeded database and compares
  the KEYS.** The values in the fixture are illustrative; the keys are the
  contract.

Three kinds of value are compared as OPAQUE rather than by key, and each is a
free `dict[str, Any]` on its own model: `/health`'s `readyz` (it is
`/readyz`'s body, which `test_admin_api.py` pins against `/readyz` itself),
a gate's `response` (the operator's own reply, whose keys are whatever they
typed), and a verdict's `details` (the schema's, pinned in
`tests/events/test_verdict_frame.py`). Comparing those by key here would be
this module asserting over somebody else's contract.
"""

from __future__ import annotations

import json
import pathlib
import unittest
from unittest.mock import patch

from brief_crew import config
from brief_crew.service import providers
from tests.service.admin_fixtures import ALICE, RUN_UUID, AdminCase

FIXTURE = (
    pathlib.Path(__file__).resolve().parents[2]
    / "frontend"
    / "tests"
    / "fixtures"
    / "adminApi.json"
)

#: Paths whose VALUE is a free-form mapping owned by something else. Compared
#: as "a dict is a dict", never key by key.
OPAQUE = {
    ("GET /api/admin/health", "readyz"),
    ("GET /api/admin/runs/{run_id}/decisions", "gates", "response"),
    ("GET /api/admin/runs/{run_id}/decisions", "verdict"),
    ("GET /api/admin/runs/{run_id}/billed", "cost_source_counts"),
}


def shape(value: object, path: tuple[str, ...]) -> object:
    """The KEY structure of a value, with the opaque paths collapsed.

    Lists collapse to the shape of their first element, because a fixture
    carrying one example row and a handler answering three must not differ.
    An empty list on either side is a wildcard for the same reason: a seeded
    world that happens to produce no guardrail frame is not a contract
    difference.
    """

    if path in OPAQUE:
        return "<opaque>"
    if isinstance(value, dict):
        return {key: shape(inner, path + (key,)) for key, inner in sorted(value.items())}
    if isinstance(value, list):
        return [shape(value[0], path)] if value else []
    return None


def merge(left: object, right: object) -> tuple[object, object]:
    """Treat an empty list on either side as matching the other's shape."""

    if isinstance(left, list) and isinstance(right, list):
        if not left or not right:
            return [], []
        merged = [merge(left[0], right[0])]
        return [merged[0][0]], [merged[0][1]]
    if isinstance(left, dict) and isinstance(right, dict) and set(left) == set(right):
        pairs = {key: merge(left[key], right[key]) for key in left}
        return (
            {key: pair[0] for key, pair in pairs.items()},
            {key: pair[1] for key, pair in pairs.items()},
        )
    return left, right


class FixtureIsCurrentTests(unittest.TestCase):
    def test_the_committed_fixture_is_what_the_script_emits(self) -> None:
        """`--check`, in process.

        Line endings normalised first: `core.autocrlf` is `true` here, so a
        raw byte comparison would report the platform rather than the drift -
        the call `emit_builder_fixtures.py` already made.
        """

        import subprocess
        import sys

        root = pathlib.Path(__file__).resolve().parents[2]
        result = subprocess.run(
            [sys.executable, str(root / "scripts" / "emit_admin_fixture.py"), "--check"],
            capture_output=True,
            text=True,
            cwd=str(root),
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_the_fixture_carries_the_unavailable_shape(self) -> None:
        """Every probe degrades to this, and the client needs one branch."""

        body = json.loads(FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual(
            set(body["_unavailable_shape"]) - {"_comment"}, {"available", "reason"}
        )


class HandlerShapesTests(AdminCase):
    """Every real handler, against a seeded database, key for key."""

    def setUp(self) -> None:
        super().setUp()
        self.fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
        # A world rich enough that no list in any response is empty by
        # accident - an empty list would make the comparison a wildcard and
        # this module would silently stop checking that endpoint's rows.
        self.seed_run(RUN_UUID, user_id=ALICE.id, cost="0.0500")
        self.seed_run("run-unowned", user_id=None, cost="0.0100")
        self.seed_gate(RUN_UUID, decision="approve", seconds=192)
        self.seed_frame(
            RUN_UUID,
            seq=1,
            kind="guardrail",
            node_id="write_report",
            details={
                "guardrail": "report_citation_closure",
                "guardrail_type": "llm",
                "retry_count": 1,
            },
        )
        self.seed_frame(
            RUN_UUID,
            seq=2,
            kind="error",
            node_id="n3_reviewer",
            details={
                "fallback_model": "openrouter/google/gemini-3.5-flash-lite",
                "attempt": 2,
            },
        )
        self.seed_frame(
            RUN_UUID, seq=3, kind="verdict", details={"verdict": "NEEDS_WORK", "score": 4.2}
        )
        self.seed_gate(RUN_UUID, "unanswered-gate", decision=None, age_hours=26)

        class Stub:
            def __init__(self, **_: object) -> None:
                pass

            def openrouter(self) -> dict:
                return providers.unavailable("not configured on this test")

            def firecrawl(self) -> dict:
                return providers.unavailable("not configured on this test")

            def langfuse_billed(self, run_id: str) -> dict:
                return {
                    "available": True,
                    "reason": None,
                    "generations": 12,
                    "billed_usd": 0.06441798,
                    "cost_source_counts": {"openrouter-billed": 12},
                    "fetched_at": "2026-09-08T12:03:11Z",
                }

        patcher = patch.object(providers, "ProviderProbes", Stub)
        patcher.start()
        self.addCleanup(patcher.stop)

    def call(self, endpoint: str) -> dict:
        """The endpoint's fixture key, turned into a real request."""

        _method, path = endpoint.split(" ", 1)
        path = (
            path.replace("/api/admin", "")
            .replace("{run_id}", RUN_UUID)
            .replace("{user_id}", ALICE.id)
        )
        return self.ok(path)

    def test_every_get_handler_produces_the_fixtures_keys(self) -> None:
        endpoints = [
            key
            for key in self.fixture
            if key.startswith("GET ") and not key.startswith("_")
        ]
        # The count is asserted so an endpoint deleted from the fixture cannot
        # quietly remove itself from this check.
        self.assertEqual(len(endpoints), 13)
        for endpoint in endpoints:
            with self.subTest(endpoint=endpoint):
                # The endpoint leads the path, so `OPAQUE`'s entries - which
                # are per endpoint - can match. Without it every `response`
                # key anywhere would be opaque, which is a wider hole than
                # the one being punched.
                served = shape(self.call(endpoint), (endpoint,))
                promised = shape(self.fixture[endpoint], (endpoint,))
                served, promised = merge(served, promised)
                self.assertEqual(served, promised)

    def test_the_cancel_lever_produces_the_fixtures_keys(self) -> None:
        record = self.registry.create_run(
            session_id="s1",
            workflow_id="idea-validator",
            inputs={"idea": "an idea"},
            user_id=ALICE.id,
        )
        with self.assertLogs("brief_crew.service.admin_api", level="WARNING"):
            response = self.client.post(
                f"/api/admin/runs/{record.run_id}/cancel", headers=self.as_admin()
            )
        self.assertEqual(response.status_code, 202, response.text)
        self.assertEqual(
            set(response.json()),
            set(self.fixture["POST /api/admin/runs/{run_id}/cancel"]),
        )

    def test_the_probe_failure_arm_has_the_success_arms_keys(self) -> None:
        """A client reads one shape, and the model can forbid extras.

        Both arms of `/providers` are exercised: the seeded world above gives
        the failure arm, and the fixture carries the success arm.
        """

        served = self.ok("/providers")
        promised = self.fixture["GET /api/admin/providers"]
        for provider in ("openrouter", "firecrawl", "langfuse"):
            with self.subTest(provider=provider):
                self.assertEqual(set(served[provider]), set(promised[provider]))

    def test_the_fixture_is_not_empty_where_it_matters(self) -> None:
        """The guard on this module's own wildcard.

        `merge` treats an empty list as matching anything, so a fixture whose
        every list were empty would make this file assert nothing at all.
        """

        for endpoint, key in (
            ("GET /api/admin/summary", "spend_by_day"),
            ("GET /api/admin/summary", "top_accounts"),
            ("GET /api/admin/summary", "attention"),
            ("GET /api/admin/spend", "rows"),
            ("GET /api/admin/users", "rows"),
            ("GET /api/admin/runs", "rows"),
            ("GET /api/admin/runs/{run_id}/decisions", "gates"),
            ("GET /api/admin/runs/{run_id}/decisions", "guardrails"),
            ("GET /api/admin/runs/{run_id}/decisions", "fallback_models"),
            ("GET /api/admin/gates", "by_gate"),
            ("GET /api/admin/verdicts", "rows"),
            ("GET /api/admin/health", "blind_to"),
        ):
            with self.subTest(endpoint=endpoint, key=key):
                self.assertTrue(self.fixture[endpoint][key], "the fixture list is empty")
                self.assertTrue(
                    self.call(endpoint)[key], "the SERVED list is empty; seed more"
                )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
