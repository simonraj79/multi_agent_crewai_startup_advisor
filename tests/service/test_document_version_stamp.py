"""Plan 21 T1's second half: a run RECORDS which version of the graph it ran.

`workflow_id` IS the document id and `runs.graph_version` is a 16-hex CONTENT
hash (`builder/descriptor.py`), so before this column "v1 versus v2" was a hash
join with no integer on either side. The integer is written at admission from
the runtime that already holds it, and the whole of that chain is what this
module exercises:

    publish -> `_register_runtime` -> `WorkflowRuntime.document_version`
            -> `RunRegistry.create` -> `persistence.create_run`
            -> `runs.document_version` -> `improve_runs`

Two doors reach `_register_runtime` and BOTH have to stamp: the publish route,
and the boot sweep that re-registers every published graph after a restart
(`BUILDER_REHYDRATE_PUBLISHED`; both Render services carry `autoDeploy: yes`,
so "after a restart" is every push to `main`). A version that depended on
whether the process had bounced would make a comparison's arms depend on it
too, which is the defect this module's rehydration case exists to catch.

Nothing here spends anything: `SYNTHETIC=1`, the same no-cost factories every
other builder test uses, and a gate calls no model by construction.
"""

from __future__ import annotations

import importlib.util
import json
from typing import Any
import unittest

from brief_crew.service.models import RunStatus
from tests.service.builder_registration import forget_builder_workflow
from tests.service.test_builder_runner import IDEA, gate_before_spend

FASTAPI_AVAILABLE = importlib.util.find_spec("fastapi") is not None


@unittest.skipUnless(FASTAPI_AVAILABLE, "FastAPI service extra is not installed")
class LaunchStampsTheVersion(unittest.TestCase):
    """The publish door, twice, so the two runs land in two different arms."""

    def setUp(self) -> None:
        from fastapi.testclient import TestClient

        from brief_crew.service.app import create_app

        self.app = create_app(
            synthetic=True, database_url="sqlite+pysqlite:///:memory:"
        )
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)

    def _create(self) -> str:
        created = self.client.post(
            "/api/builder/workflows",
            json={"document": json.loads(gate_before_spend().model_dump_json())},
        )
        self.assertEqual(created.status_code, 201, created.text)
        return created.json()["document"]["id"]

    def _publish(self, document_id: str) -> dict[str, Any]:
        published = self.client.post(f"/api/builder/workflows/{document_id}/publish")
        self.assertEqual(published.status_code, 200, published.text)
        body = published.json()
        # A publish through the real HTTP surface writes six process-global
        # maps and `TestClient.close` unwinds none of them.
        self.addCleanup(forget_builder_workflow, body["workflow_id"])
        return body

    def _run_to_completion(self, published: dict[str, Any]) -> str:
        launched = self.client.post(
            "/api/sessions/version-stamp/runs",
            json={
                "workflow_id": published["workflow_id"],
                "inputs": {published["input_field"]: IDEA},
            },
        )
        self.assertEqual(launched.status_code, 202, launched.text)
        run_id = launched.json()["run_id"]
        registry = self.app.state.run_registry
        registry.wait(run_id, timeout=30)
        waiting = self.client.get(f"/api/runs/{run_id}").json()
        self.assertEqual(waiting["status"], RunStatus.WAITING.value)
        answered = self.client.post(
            f"/api/runs/{run_id}/gates/{waiting['pending_gate']['gate_id']}",
            json={"outcome": "approve", "fields": {}},
        )
        self.assertEqual(answered.status_code, 202, answered.text)
        registry.wait(run_id, timeout=30)
        return run_id

    def test_the_runtime_carries_the_published_document_version(self) -> None:
        """The link in the chain that has no database in it."""

        published = self._publish(self._create())
        runtime = self.app.state.run_registry.workflow_runtime(
            published["workflow_id"]
        )
        self.assertEqual(1, runtime.document_version)

    def test_a_run_of_a_published_graph_records_its_version(self) -> None:
        published = self._publish(self._create())
        run_id = self._run_to_completion(published)
        persistence = self.app.state.run_registry.persistence
        record = persistence.get_run(run_id)
        assert record is not None
        self.assertEqual(1, record["document_version"])

    def test_two_published_versions_produce_two_arms(self) -> None:
        """The flywheel in miniature: edit, republish, run again, compare.

        Without the column both runs carry a different content hash and no
        integer, so grouping them is a hash join nobody can read; with it the
        two runs are `1` and `2` and a comparison has two arms that mean
        something to the person who made the change.
        """

        document_id = self._create()
        first = self._publish(document_id)
        self._run_to_completion(first)

        # Save a second version - a label edit is enough; the point is that
        # the stored version number moves, not what moved with it.
        stored = self.client.get(f"/api/builder/workflows/{document_id}").json()
        payload = dict(stored["document"])
        payload["name"] = "the second cut"
        saved = self.client.put(
            f"/api/builder/workflows/{document_id}",
            json={"document": payload, "expected_version": stored["document"]["version"]},
        )
        self.assertEqual(saved.status_code, 200, saved.text)
        second = self._publish(document_id)
        self._run_to_completion(second)

        persistence = self.app.state.run_registry.persistence
        rows, truncated = persistence.improve_runs(workflow_id=document_id)
        self.assertFalse(truncated)
        self.assertEqual(
            {1, 2}, {row["document_version"] for row in rows}, rows
        )

    def test_a_hand_written_flow_records_no_version(self) -> None:
        """NOT zero. There is no document, so there is nothing to compare."""

        launched = self.client.post(
            "/api/sessions/version-stamp/runs",
            json={"workflow_id": "idea-validator", "inputs": {"idea": IDEA}},
        )
        self.assertEqual(launched.status_code, 202, launched.text)
        run_id = launched.json()["run_id"]
        persistence = self.app.state.run_registry.persistence
        record = persistence.get_run(run_id)
        assert record is not None
        self.assertIsNone(record["document_version"])


class RehydrationStampsTheVersionToo(unittest.TestCase):
    """The boot sweep is the OTHER door onto `_register_runtime`.

    Reuses the rehydration module's own harness rather than a second copy of
    it: a copy is how two halves drift, and what is being asserted here is one
    field on the object that harness already builds.
    """

    def test_the_sweep_registers_the_stored_version(self) -> None:
        from tests.service.test_builder_rehydration import (
            GOOD_ID,
            BuilderRehydrationTestCase,
            _document,
            _workflow_id,
        )

        case = BuilderRehydrationTestCase("run")
        case.setUp()
        self.addCleanup(case.doCleanups)

        document = _document(GOOD_ID)
        workflow_id = _workflow_id(document)
        case.track(workflow_id)
        persistence = case.persistence()
        case.publish_into(persistence, document)
        registry = case.registry(persistence)
        case.sweep(persistence, registry)

        runtime = registry.workflow_runtime(workflow_id)
        self.assertEqual(1, runtime.document_version)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
