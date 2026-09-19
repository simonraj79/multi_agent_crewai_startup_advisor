"""The real handlers agree with `improveApi.json`, per endpoint (plan 21, T5).

The UI builder built the Improve tab against a committed fixture before these
handlers existed. That is the only reason two builders could work at once, and
it buys exactly one failure mode: **a mirror that agrees with itself.** Section
14 defect 2 is the precedent - `PROBLEM_CODES` carried 27 codes where the
server emitted 30, and its own anti-rot test read two of the three files that
declare them, so the builder's single most frequent server complaint was one
the console had never heard of.

Two things close that here, and this module is the second:

* `scripts/emit_improve_fixture.py` builds the fixture from INSTANCES of the
  real response models, so a field added to a model without an example is a
  `ValidationError` when the script runs.
* **This module drives the real routes against a seeded database and compares
  the KEYS.** The values in the fixture are illustrative; the keys are the
  contract. Plan 17 criterion 21's shape, applied to this plan's five.

Free-form mappings whose keys belong to somebody else are compared as OPAQUE:
a run's own inputs, a router's own route names, a status or verdict mix.
Comparing those key by key would be this module asserting over a vocabulary it
does not own - and each one is listed with its reason, because an unexplained
exemption is how the `/readyz` example in the admin fixture stayed wrong for a
week.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
import json
import pathlib
import unittest
from unittest.mock import patch

from brief_crew import config
from brief_crew.events import FrameData, FrameKind, FrameLevel, UIEventType
from brief_crew.service import digest as digest_module
from tests.service.admin_fixtures import ALICE, NOW, RUN_UUID, AdminCase

FIXTURE = (
    pathlib.Path(__file__).resolve().parents[2]
    / "frontend"
    / "tests"
    / "fixtures"
    / "improveApi.json"
)

WORKFLOW = "ug_shapes001"

#: Paths whose VALUE is a mapping owned by something else. Each is a
#: vocabulary this repository does not define, so the KEYS are not a contract.
OPAQUE = {
    # A router's own branch names, and a run's own status and verdict words.
    ("GET /api/admin/improve/hotspots", "routes", "routes"),
    ("GET /api/admin/improve/compare", "arms", "status_mix"),
    ("GET /api/admin/improve/compare", "arms", "verdict_mix"),
    # The author's own input keys.
    ("GET /api/admin/export/evalset", "inputs"),
}


def shape(value: object, path: tuple[str, ...]) -> object:
    """The KEY structure of a value, with the opaque paths collapsed.

    Lists collapse to the shape of their first element, because a fixture
    carrying one example row and a handler answering three must not differ.
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
        merged = merge(left[0], right[0])
        return [merged[0]], [merged[1]]
    if isinstance(left, dict) and isinstance(right, dict) and set(left) == set(right):
        pairs = {key: merge(left[key], right[key]) for key in left}
        return (
            {key: pair[0] for key, pair in pairs.items()},
            {key: pair[1] for key, pair in pairs.items()},
        )
    return left, right


class FixtureIsCurrentTests(unittest.TestCase):
    def test_the_committed_fixture_is_what_the_script_emits(self) -> None:
        """`--check`, in process, with PYTHONPATH at THIS tree's `src`.

        Without the path the subprocess imports the main tree's `brief_crew`
        through the venv's editable install and checks the fixture against a
        different branch's models - which is the worktree trap, met where it
        is easiest to forget.
        """

        import os
        import subprocess
        import sys

        root = pathlib.Path(__file__).resolve().parents[2]
        env = dict(os.environ)
        env["PYTHONPATH"] = str(root / "src")
        result = subprocess.run(
            [
                sys.executable,
                str(root / "scripts" / "emit_improve_fixture.py"),
                "--check",
            ],
            capture_output=True,
            text=True,
            cwd=str(root),
            env=env,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_the_fixture_names_the_five_endpoints(self) -> None:
        """Four reads and one write - R7's four sections.

        Counted, because an endpoint added to the server without an
        example here is a shape the client never agreed to and an example
        here with no server behind it is a shape nothing serves.
        """

        body = json.loads(FIXTURE.read_text(encoding="utf-8"))
        endpoints = [key for key in body if not key.startswith("_")]
        self.assertEqual(
            [
                "GET /api/admin/improve/hotspots",
                "GET /api/admin/improve/compare",
                "GET /api/admin/improve/digests",
                "POST /api/admin/improve/digests",
                "GET /api/admin/export/evalset",
            ],
            endpoints,
        )


class HandlerShapesTests(AdminCase):
    """Every real handler, against a seeded database, key for key."""

    def setUp(self) -> None:
        super().setUp()
        self.fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
        self.seed()

    # -- the world --------------------------------------------------------

    def seed(self) -> None:
        """Rich enough that no list in any response is empty by accident.

        An empty list makes `merge` a wildcard, so a thin seed would silently
        stop this module checking the endpoint it was written for.
        """

        for index in range(6):
            run_id = RUN_UUID if index == 0 else f"shape-run-{index}"
            self.seed_shape_run(run_id, index)
        # One stored review, so `GET /improve/digests` answers a non-empty
        # `rows` without a model call. `merge` treats an empty list as a
        # wildcard, so a seed that left this empty would quietly stop the
        # module checking the row shape it exists to check.
        self.store.save_digest(
            {
                "id": "dg_seeded01",
                "workflow_id": WORKFLOW,
                "created_by": "user_admin",
                "window_from": NOW - timedelta(days=1),
                "window_to": NOW,
                "sample_runs": 6,
                "sample_frames": 40,
                "truncated_sample": False,
                "model": config.CHEAP_MODEL,
                "prompt_tokens": 8214,
                "completion_tokens": 734,
                "cost_usd": 0.0043,
                "over_cap": False,
                "error": None,
                "body": "## What went well - the scope gate.",
                # OLD on purpose: the per-workflow interval brake refuses a
                # second review within `DIGEST_MIN_INTERVAL_SECONDS`, and this
                # module's POST has to get through to be compared.
                "created_at": NOW - timedelta(hours=2),
            }
        )

    def seed_shape_run(self, run_id: str, index: int) -> None:
        created = NOW - timedelta(hours=2)
        self.store.create_run(
            run_id=run_id,
            session_id="s",
            workflow_id=WORKFLOW,
            graph_version="8f14e45fceea167a",
            inputs={"idea": "a scheduling assistant for clinics"},
            user_id=ALICE.id,
            status="queued",
            created_at=created,
            document_version=4,
        )
        self.store.save_node_metrics(
            run_id,
            "market_research",
            model=config.ESCALATION_MODEL,
            cost_usd=Decimal("0.0610"),
            total_tokens=1000,
            prompt_tokens=800,
            completion_tokens=200,
            call_count=2,
        )
        self.store.update_run_status(
            run_id,
            "completed",
            started_at=created,
            completed_at=created + timedelta(minutes=1),
            result={"markdown_body": "# Validation report\n\nThe clinics segment."},
        )
        self.store.set_run_rating(
            run_id,
            rating="good" if index % 2 == 0 else "bad",
            note="the segment was right",
            rated_by=ALICE.id,
        )
        self.store.open_gate(
            run_id,
            "scope-confirmation",
            node_id="confirm_scope",
            request={"fields": {"segment": "SMBs"}},
            opened_at=created,
        )
        self.store.answer_gate(
            run_id,
            "scope-confirmation",
            {"decision": "revise", "fields": {"segment": "independent clinics"}},
            answered_at=created + timedelta(seconds=200),
        )
        self.store.update_run_status(run_id, "completed")
        self.store.append_frames(run_id, list(self.frames(run_id)))

    def frames(self, run_id: str):
        rows = [
            (
                FrameKind.AGENT,
                "market_research",
                {
                    "stage": "before",
                    "task": "market_task",
                    "agent_role": "Market evidence analyst",
                },
            ),
            (
                FrameKind.TOOL,
                "market_research",
                {
                    "stage": "after",
                    "tool": "MarketResearchTool",
                    "query": "quiz generator LLM",
                    "tool_status": "ok",
                    "result_count": 0,
                    "agent_role": "Market evidence analyst",
                },
            ),
            (
                FrameKind.TOOL,
                "market_research",
                {
                    "stage": "error",
                    "tool": "MarketResearchTool",
                    "query": "quiz generator LLM",
                    "error_class": "HTTPStatusError",
                    "agent_role": "Market evidence analyst",
                },
            ),
            (
                FrameKind.GUARDRAIL,
                "market_research",
                {
                    "stage": "after",
                    "guardrail": "market_source_closure",
                    "success": False,
                    "agent_role": "Market evidence analyst",
                },
            ),
            (
                FrameKind.LLM,
                "market_research",
                {
                    "stage": "after",
                    "model": config.ESCALATION_MODEL,
                    "finish_reason": "length",
                    "agent_role": "Market evidence analyst",
                },
            ),
            (
                FrameKind.EDGE_TAKEN,
                "route_scope",
                {"route": "scope_approved", "from": "confirm_scope"},
            ),
            (
                FrameKind.AGENT,
                "market_research",
                {
                    "stage": "after",
                    "task_name": "market_task",
                    "agent_role": "Market evidence analyst",
                    "output_preview": "a finding",
                    "output_chars": 9,
                    "tool_failure_count": 1,
                },
            ),
            (
                FrameKind.VERDICT,
                "review_verdict",
                {"verdict": "VALIDATE", "confidence": 0.2},
            ),
        ]
        for seq, (kind, node_id, details) in enumerate(rows, start=1):
            yield FrameData(
                seq=seq,
                run_id=run_id,
                ts=NOW - timedelta(minutes=30),
                kind=kind,
                event_type=UIEventType.WORKFLOW_END,
                level=FrameLevel.INFO,
                node_id=node_id,
                message="a frame",
                details=details,
            )

    # -- the calls --------------------------------------------------------

    def served(self, endpoint: str) -> object:
        """The endpoint's fixture key, turned into a real request."""

        method, path = endpoint.split(" ", 1)
        query = f"?workflow_id={WORKFLOW}"
        if method == "GET" and path.endswith("/export/evalset"):
            response = self.client.get(
                path + query + "&rating=any", headers=self.as_admin()
            )
            self.assertEqual(response.status_code, 200, response.text)
            return [
                json.loads(line)
                for line in response.text.splitlines()
                if line.strip()
            ]
        if method == "GET":
            response = self.client.get(path + query, headers=self.as_admin())
        else:  # POST /improve/digests - the only write here, and it is
            # faked at `_default_llm` so no test can reach OpenRouter.
            with patch.object(config, "IMPROVE_DIGEST_ENABLED", True), patch.object(
                digest_module, "_default_llm", lambda _model: _FakeLLM()
            ):
                with self.assertLogs(
                    "brief_crew.service.improve_api", level="WARNING"
                ):
                    response = self.client.post(path + query, headers=self.as_admin())
        self.assertEqual(response.status_code, 200, f"{endpoint}: {response.text}")
        return response.json()

    def test_every_handler_produces_the_fixtures_keys(self) -> None:
        endpoints = [key for key in self.fixture if not key.startswith("_")]
        self.assertEqual(5, len(endpoints))
        for endpoint in endpoints:
            with self.subTest(endpoint=endpoint):
                promised = self.fixture[endpoint]
                served = self.served(endpoint)
                if endpoint.endswith("evalset"):
                    promised = promised["_ndjson_lines"]
                left = shape(served, (endpoint,))
                right = shape(promised, (endpoint,))
                left, right = merge(left, right)
                self.assertEqual(right, left)

    def test_the_fixture_is_not_empty_where_it_matters(self) -> None:
        """The guard on this module's own wildcard.

        `merge` treats an empty list as matching anything, so a fixture whose
        every list were empty would make this file assert nothing at all.
        """

        for endpoint, key in (
            ("GET /api/admin/improve/hotspots", "agents"),
            ("GET /api/admin/improve/hotspots", "tools"),
            ("GET /api/admin/improve/hotspots", "errors"),
            ("GET /api/admin/improve/hotspots", "gates"),
            ("GET /api/admin/improve/hotspots", "routes"),
            ("GET /api/admin/improve/hotspots", "tasks"),
            ("GET /api/admin/improve/hotspots", "node_models"),
            ("GET /api/admin/improve/compare", "arms"),
            ("GET /api/admin/improve/digests", "rows"),
        ):
            with self.subTest(endpoint=endpoint, key=key):
                self.assertTrue(
                    self.fixture[endpoint][key], "the FIXTURE list is empty"
                )
                self.assertTrue(
                    self.served(endpoint)[key], "the SERVED list is empty; seed more"
                )

    def test_the_fixture_shows_a_node_on_two_models_and_one_on_one(self) -> None:
        """The two cases a model picker has to draw differently.

        A node with two models is the only kind a comparison has anything to
        say about; a node with one must still be offered, and must not be
        presented as comparable. A fixture carrying only one of the two would
        let the client be written for half the problem.
        """

        rows = self.fixture["GET /api/admin/improve/hotspots"]["node_models"]
        widths = sorted(len(row["models"]) for row in rows)
        self.assertEqual([1, 2], widths)
        for row in rows:
            with self.subTest(node=row["node_id"]):
                self.assertEqual(sorted(row["models"]), row["models"])
                self.assertTrue(row["label"])
                self.assertGreater(row["runs"], 0)

    def test_the_review_total_is_a_count_and_not_the_page(self) -> None:
        """`len(rows)` becomes the answer to "how many reviews" the first
        time somebody hits the cap; the fixture states the difference."""

        page = self.fixture["GET /api/admin/improve/digests"]
        self.assertGreater(page["total_count"], len(page["rows"]))
        served = self.served("GET /api/admin/improve/digests")
        self.assertEqual(len(served["rows"]), served["total_count"])

    def test_the_evalset_example_carries_both_line_shapes(self) -> None:
        """A header line and a run line: an export with only one of them is a
        file no reader can parse in one pass."""

        lines = self.fixture["GET /api/admin/export/evalset"]["_ndjson_lines"]
        self.assertTrue(lines[0]["_header"])
        self.assertIn("run_id", lines[1])


class _FakeLLM:
    def call(self, _messages: list[dict[str, str]]) -> str:
        return "## What went well\n\nThe market node."


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
