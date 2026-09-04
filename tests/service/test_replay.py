"""`resume_from` replays what was already paid for - 10 D5, criterion 6.

A run that dies at node 7 of 9 could only ever be started again from node 1.
`resume_from {run_id, node_id}` compiles the DERIVED plan 09 D7 emits - every
node above the resume point compiled to `runtime:replay_output` instead of to
the entrypoint that would have billed - seeds each one from the source run's
saved state, and runs the rest for real.

The three things worth proving, and they are the three the criterion names: the
replayed nodes announce themselves (`replayed: true`), the result equals a
clean run's, and somebody else's source run is a 404.
"""

from __future__ import annotations

import importlib.util
from typing import Any
import unittest

from brief_crew.builder.runtime import ReplayMissingOutput
from brief_crew.config import RUN_RESULT_BODY_KEYS
from brief_crew.events import FrameKind
from brief_crew.service.builder_runner import SyntheticCrewFactories
from tests.builder.test_compiler import input_node, output_node, scoper_node
from tests.builder.test_document import document, edge
from tests.service.identities import AuthenticatedTwoUserCase

FASTAPI_AVAILABLE = importlib.util.find_spec("fastapi") is not None
BODY_KEY = RUN_RESULT_BODY_KEYS[0]
IDEA = "a scheduling assistant for clinics"


def abc() -> Any:
    """idea -> a -> b -> c -> report. Three billable steps to replay two of."""

    return document(
        [
            input_node(),
            scoper_node("a"),
            scoper_node("b"),
            scoper_node("c"),
            output_node("report", source="${state.out__c}"),
        ],
        [
            edge("e1", "idea", "a"),
            edge("e2", "a", "b"),
            edge("e3", "b", "c"),
            edge("e4", "c", "report"),
        ],
    )


@unittest.skipUnless(FASTAPI_AVAILABLE, "fastapi is not installed")
class ResumeFromTests(AuthenticatedTwoUserCase):
    def setUp(self) -> None:
        super().setUp()
        self.registry = self.app.state.run_registry

    def launch(self, workflow_id: str, **body: Any) -> Any:
        payload: dict[str, Any] = {
            "workflow_id": workflow_id,
            "inputs": {"idea": IDEA},
        }
        payload.update(body)
        return self.client.post(
            "/api/sessions/s1/runs", json=payload, headers=self.as_alice()
        )

    def completed(self, workflow_id: str, **body: Any) -> str:
        response = self.launch(workflow_id, **body)
        self.assertEqual(response.status_code, 202, response.text)
        run_id = response.json()["run_id"]
        self.registry.wait(run_id, timeout=20)
        return run_id

    def frames(self, run_id: str) -> list[dict[str, Any]]:
        page = self.client.get(
            f"/api/runs/{run_id}/frames?limit=500", headers=self.as_alice()
        ).json()
        return [frame["data"] for frame in page["frames"]]

    def result_of(self, run_id: str) -> Any:
        return self.client.get(
            f"/api/runs/{run_id}", headers=self.as_alice()
        ).json()["result"]

    def test_a_resume_replays_the_nodes_above_it_and_runs_the_rest(self) -> None:
        _, workflow_id = self.publish(abc(), self.as_alice())
        source = self.completed(workflow_id)
        clean = self.result_of(source)

        resumed = self.completed(
            workflow_id, resume_from={"run_id": source, "node_id": "c"}
        )
        replayed = {
            frame["node_id"]
            for frame in self.frames(resumed)
            if frame["details"].get("replayed") is True
        }
        self.assertEqual(replayed, {"idea", "a", "b"})
        # `c` ran for real, so it is NOT in the replayed set.
        self.assertNotIn("c", replayed)
        self.assertEqual(self.result_of(resumed)[BODY_KEY], clean[BODY_KEY])

    def test_the_replay_frames_are_a_pair_per_node(self) -> None:
        _, workflow_id = self.publish(abc(), self.as_alice())
        source = self.completed(workflow_id)
        resumed = self.completed(
            workflow_id, resume_from={"run_id": source, "node_id": "c"}
        )
        pairs = [
            (frame["node_id"], frame["event_type"])
            for frame in self.frames(resumed)
            if frame["details"].get("replayed") is True
        ]
        for node_id in ("idea", "a", "b"):
            self.assertIn((node_id, "NODE_START"), pairs)
            self.assertIn((node_id, "NODE_END"), pairs)

    def test_a_resumed_run_records_what_it_resumed_from(self) -> None:
        _, workflow_id = self.publish(abc(), self.as_alice())
        source = self.completed(workflow_id)
        resumed = self.completed(
            workflow_id, resume_from={"run_id": source, "node_id": "c"}
        )
        body = self.client.get(f"/api/runs/{resumed}", headers=self.as_alice()).json()
        self.assertEqual(body["resume_from"], {"run_id": source, "node_id": "c"})

    def test_a_source_run_owned_by_somebody_else_is_404(self) -> None:
        """404 and not 403, for `require_own_run`'s own reason.

        A 403 would confirm the run exists, turning this into an oracle that
        answers "is this a real run id" for a stranger.
        """

        _, mine = self.publish(abc(), self.as_alice())
        _, theirs = self.publish(abc(), self.as_bob())
        bob_run = self.client.post(
            "/api/sessions/s2/runs",
            json={"workflow_id": theirs, "inputs": {"idea": IDEA}},
            headers=self.as_bob(),
        ).json()["run_id"]
        self.registry.wait(bob_run, timeout=20)

        response = self.launch(mine, resume_from={"run_id": bob_run, "node_id": "c"})
        self.assertEqual(response.status_code, 404, response.text)

    def test_a_source_run_that_is_still_going_is_422(self) -> None:
        """A state still being written is not a state to replay."""

        from brief_crew.service.models import RunStatus

        _, workflow_id = self.publish(abc(), self.as_alice())
        source = self.completed(workflow_id)
        self.registry.require(source).status = RunStatus.RUNNING
        response = self.launch(
            workflow_id, resume_from={"run_id": source, "node_id": "c"}
        )
        self.assertEqual(response.status_code, 422, response.text)
        self.assertIn("has finished", response.json()["detail"])

    def test_a_resume_point_that_is_not_a_step_node_is_422(self) -> None:
        _, workflow_id = self.publish(abc(), self.as_alice())
        source = self.completed(workflow_id)
        response = self.launch(
            workflow_id, resume_from={"run_id": source, "node_id": "nope"}
        )
        # The compile happens in the runner, so the refusal reaches the client
        # as a failed run rather than as a 4xx - and it is the COMPILER's own
        # sentence, which is the one that says what a replay point is.
        run_id = response.json()["run_id"]
        self.registry.wait(run_id, timeout=20)
        body = self.client.get(f"/api/runs/{run_id}", headers=self.as_alice()).json()
        self.assertEqual(body["status"], "failed")
        self.assertIn("replay point", str(body["error"]))


class ReplayMissingOutputTests(unittest.TestCase):
    """The saved state does not carry the key the plan needs - 10 D5."""

    def test_a_missing_saved_output_names_itself(self) -> None:
        from brief_crew.builder.runtime import replay_output, replay_source

        class Flow:
            state: dict[str, Any] = {}

        with replay_source({"a": "done"}):
            with self.assertRaises(ReplayMissingOutput) as caught:
                replay_output(Flow(), node_id="b")
        self.assertEqual(caught.exception.error_class, "replay-missing-output")
        self.assertIn("no saved output for 'b'", str(caught.exception))

    def test_the_error_class_is_what_the_serializer_reads(self) -> None:
        from brief_crew.events.serializer import error_class_of

        self.assertEqual(
            error_class_of(ReplayMissingOutput("x")),
            {"error_class": "replay-missing-output"},
        )

    def test_an_unknown_source_word_is_refused(self) -> None:
        from brief_crew.builder.runtime import BuilderRuntimeError, replay_output

        class Flow:
            state: dict[str, Any] = {}

        with self.assertRaises(BuilderRuntimeError) as caught:
            replay_output(Flow(), node_id="b", source="somewhere")
        self.assertIn("run or test_input", str(caught.exception))


@unittest.skipUnless(FASTAPI_AVAILABLE, "fastapi is not installed")
class ReplayCostsNothingTests(AuthenticatedTwoUserCase):
    """The point of the whole feature: a replayed node builds no crew."""

    def setUp(self) -> None:
        super().setUp()
        self.registry = self.app.state.run_registry

    def test_a_replayed_node_never_reaches_the_factory(self) -> None:
        _, workflow_id = self.publish(abc(), self.as_alice())
        source = self.client.post(
            "/api/sessions/s1/runs",
            json={"workflow_id": workflow_id, "inputs": {"idea": IDEA}},
            headers=self.as_alice(),
        ).json()["run_id"]
        self.registry.wait(source, timeout=20)

        # A fresh recorder, so `calls` covers the resumed run alone.
        runtime = self.registry.workflow_runtime(workflow_id)
        factories = SyntheticCrewFactories()
        runtime.runner.crew_factories = factories

        resumed = self.client.post(
            "/api/sessions/s1/runs",
            json={
                "workflow_id": workflow_id,
                "inputs": {"idea": IDEA},
                "resume_from": {"run_id": source, "node_id": "c"},
            },
            headers=self.as_alice(),
        ).json()["run_id"]
        self.registry.wait(resumed, timeout=20)

        self.assertEqual([call[0] for call in factories.calls], ["c"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
