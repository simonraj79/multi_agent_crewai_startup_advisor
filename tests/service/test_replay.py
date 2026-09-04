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
from tests.builder.test_compiler import (
    StubFactories,
    authored_agent_node,
    gate_node,
    input_node,
    output_node,
    scoper_node,
    transform_node,
)
from tests.builder.test_document import document, edge, node
from tests.service.identities import ALICE, AuthenticatedTwoUserCase

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


def gated() -> Any:
    """idea -> confirm (a GATE) -> safe -> report.

    The shape the launch rule forces on an anonymous author:
    `BUILDER_ALLOW_GATELESS_GRAPHS` is off, so a graph reachable without a
    sign-in must put a human gate above its first billable node. Every such
    graph is therefore one a `resume_from` has to be able to replay past.
    """

    return document(
        [
            input_node(),
            gate_node("confirm"),
            scoper_node("safe"),
            output_node("report", source="${state.out__safe}"),
        ],
        [
            edge("e1", "idea", "confirm"),
            edge("e2", "confirm", "safe", source_port="approve"),
            edge("e3", "safe", "report"),
        ],
    )


def gated_loop() -> Any:
    """The same gate with its revise port wired back through a router.

    `again` is a router because `bounds.py` refuses any other node as the one
    that closes a loop. `redo` is an AGENT rather than a transform so that a
    source run can fail inside the revise lap: that is the only shape whose LAST
    recorded decision is a revise, and therefore the only shape that can tell a
    replayed decision apart from a hardcoded approve.
    """

    return document(
        [
            input_node(),
            gate_node("confirm", max_turns=2),
            scoper_node("redo"),
            node(
                "again",
                "router",
                {
                    "branches": [
                        # One lap and no more: the second revise leaves
                        # `turns__confirm` at 2 and the router goes onward.
                        {"label": "retry", "op": "lte", "key": "turns__confirm", "value": 1},
                        {"label": "onward", "op": "otherwise"},
                    ]
                },
            ),
            scoper_node("safe"),
            output_node("report", source="${state.out__safe}"),
        ],
        [
            edge("e1", "idea", "confirm"),
            edge("e2", "confirm", "safe", source_port="approve"),
            edge("e3", "confirm", "redo", source_port="revise"),
            edge("e4", "redo", "again"),
            edge("e5", "again", "confirm", source_port="retry"),
            edge("e6", "again", "safe", source_port="onward"),
            edge("e7", "safe", "report"),
        ],
    )


def branched() -> Any:
    """idea -> a -> pick (a ROUTER) -> safe -> report.

    A plain router above the resume point is the same defect wearing a
    different kind: it emits the label its successor listens for, and a
    derived plan that replaced it with `replay_output` emitted nothing.
    """

    return document(
        [
            input_node(),
            scoper_node("a"),
            node(
                "pick",
                "router",
                {
                    "branches": [
                        # A comparison nothing an agent writes can satisfy,
                        # so the branch taken is the same on both runs and an
                        # assertion about it is about the replay.
                        {"label": "retry", "op": "eq", "key": "out__a", "value": "—never—"},
                        {"label": "onward", "op": "otherwise"},
                    ]
                },
            ),
            scoper_node("safe"),
            scoper_node("other"),
            output_node("report", source="${state.out__safe}"),
        ],
        [
            edge("e1", "idea", "a"),
            edge("e2", "a", "pick"),
            edge("e3", "pick", "other", source_port="retry"),
            edge("e4", "pick", "safe", source_port="onward"),
            edge("e5", "safe", "report"),
        ],
    )


def _events(condition: Any) -> list[str]:
    """Every event name inside a compiled `listen`, at any nesting."""

    if condition is None:
        return []
    if isinstance(condition, str):
        return [condition]
    if isinstance(condition, dict):
        found: list[str] = []
        for branch in condition.values():
            for item in branch if isinstance(branch, (list, tuple)) else [branch]:
                found += _events(item)
        return found
    return []


def dangling_triggers(definition: Any) -> list[str]:
    """Every `listen` in a compiled definition that nothing can ever satisfy.

    Written out here rather than imported from the compiler on purpose: this
    is the invariant the compiler is being asked to hold, and two independent
    statements of it agreeing is the whole guarantee.
    """

    methods = dict(definition.get("methods", {}))
    produced = set(methods)
    for method in methods.values():
        produced.update(method.get("emit") or ())
    return [
        f"{name} listens for {event!r}"
        for name, method in methods.items()
        for event in _events(method.get("listen"))
        if event not in produced
    ]

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



@unittest.skipUnless(FASTAPI_AVAILABLE, "fastapi is not installed")
class ResumeFromAGateTests(AuthenticatedTwoUserCase):
    """A derived plan that has to get PAST a gate - the defect plan 12 measured.

    `resume_from` replaced every upstream node with `runtime:replay_output`,
    including a gate - and a gate is TWO methods, the pause and the paired
    deterministic router that turns the operator's reply into an event. The
    replacement kept the first and dropped the second, so the node below the
    gate went on listening for `e2_approve` while nothing emitted it. The
    compiler's own post-condition caught it, which is the only reason this was
    a refusal rather than a run that produced nothing.

    It matters because of the launch rule and not because gates are common: a
    gate above the first billable node is the only shape an anonymous author
    may launch, so EVERY graph they can launch was one `resume_from` could not
    resume past.
    """

    def setUp(self) -> None:
        super().setUp()
        self.registry = self.app.state.run_registry

    # ------------------------------------------------------------- driving
    def launch(self, workflow_id: str, **body: Any) -> Any:
        payload: dict[str, Any] = {"workflow_id": workflow_id, "inputs": {"idea": IDEA}}
        payload.update(body)
        return self.client.post(
            "/api/sessions/s1/runs", json=payload, headers=self.as_alice()
        )

    def drive(self, workflow_id: str, *decisions: str, **body: Any) -> str:
        """Launch, answer each gate in turn with the given outcome, and settle."""

        response = self.launch(workflow_id, **body)
        self.assertEqual(response.status_code, 202, response.text)
        run_id = response.json()["run_id"]
        for outcome in decisions:
            self.registry.wait(run_id, timeout=20)
            prompt = self.registry.require(run_id).pending_gate
            self.assertIsNotNone(prompt, f"no gate to answer {outcome!r} at")
            assert prompt is not None
            self.registry.answer_gate(
                run_id, str(prompt["gate_id"]), outcome=outcome, fields={}
            )
        self.registry.wait(run_id, timeout=20)
        return run_id

    def snapshot(self, run_id: str) -> dict[str, Any]:
        return self.client.get(f"/api/runs/{run_id}", headers=self.as_alice()).json()

    def frames(self, run_id: str) -> list[dict[str, Any]]:
        page = self.client.get(
            f"/api/runs/{run_id}/frames?limit=500", headers=self.as_alice()
        ).json()
        return [frame["data"] for frame in page["frames"]]

    def compiled(self, doc: Any, node_id: str, mode: str = "resume_from") -> Any:
        from brief_crew.builder.compiler import compile_replay_plan

        return compile_replay_plan(doc, node_id=node_id, mode=mode)

    # -------------------------------------------------------------- shapes
    def test_the_derived_plan_over_a_gate_compiles_at_all(self) -> None:
        compiled = self.compiled(gated(), "safe")
        self.assertEqual(dangling_triggers(compiled.definition), [])

    def test_the_gates_paired_router_survives_the_replay(self) -> None:
        """The step method replays; the ROUTER is still there and still routes.

        Without the router the approve label is emitted by nothing at all,
        which is exactly what `dangling_triggers` above reports.
        """

        compiled = self.compiled(gated(), "safe")
        methods = compiled.definition["methods"]
        self.assertEqual(
            methods["n1_confirm"]["do"]["ref"],
            "brief_crew.builder.runtime:replay_output",
        )
        router = methods["n2_route_confirm"]
        self.assertTrue(router["router"])
        self.assertEqual(router["emit"], ["e2_approve", "e2_revise"])
        # And the pause is gone: a replayed gate must not ask the operator to
        # answer a question they already answered.
        self.assertNotIn("human_feedback", methods["n1_confirm"])

    def test_a_router_above_the_resume_point_still_emits(self) -> None:
        compiled = self.compiled(branched(), "safe")
        self.assertEqual(dangling_triggers(compiled.definition), [])

    def test_a_node_test_below_a_gate_compiles_too(self) -> None:
        compiled = self.compiled(gated(), "safe", mode="node_test")
        self.assertEqual(dangling_triggers(compiled.definition), [])

    # ----------------------------------------------------------- behaviour
    def test_a_resume_past_a_gate_completes_with_output(self) -> None:
        _, workflow_id = self.publish(gated(), self.as_alice())
        source = self.drive(workflow_id, "approve")
        clean = self.snapshot(source)
        self.assertEqual(clean["status"], "completed", clean)

        resumed = self.drive(
            workflow_id, resume_from={"run_id": source, "node_id": "safe"}
        )
        body = self.snapshot(resumed)
        self.assertEqual(body["status"], "completed", body)
        self.assertEqual(body["result"][BODY_KEY], clean["result"][BODY_KEY])
        replayed = {
            frame["node_id"]
            for frame in self.frames(resumed)
            if frame["details"].get("replayed") is True
        }
        self.assertEqual(replayed, {"idea", "confirm"})

    def test_a_resume_past_a_gate_does_not_ask_again(self) -> None:
        """The operator answered once. A replay that paused would be a regression."""

        _, workflow_id = self.publish(gated(), self.as_alice())
        source = self.drive(workflow_id, "approve")
        response = self.launch(
            workflow_id, resume_from={"run_id": source, "node_id": "safe"}
        )
        run_id = response.json()["run_id"]
        self.registry.wait(run_id, timeout=20)
        record = self.registry.require(run_id)
        self.assertIsNone(record.pending_gate)
        self.assertEqual(self.snapshot(run_id)["status"], "completed")

    def test_the_replayed_gate_re_emits_the_decision_that_was_recorded(self) -> None:
        """A revise that was HONOURED replays as a revise, not as an approve.

        The lap itself is not re-run - `redo` is replayed like every other
        ancestor - but the branch the source run took is the branch the derived
        plan takes, which is the difference between replaying a run and
        inventing one.
        """

        _, workflow_id = self.publish(gated_loop(), self.as_alice())
        source = self.drive(workflow_id, "revise", "approve")
        self.assertEqual(self.snapshot(source)["status"], "completed")

        resumed = self.drive(
            workflow_id, resume_from={"run_id": source, "node_id": "safe"}
        )
        self.assertEqual(self.snapshot(resumed)["status"], "completed")
        replayed = {
            frame["node_id"]
            for frame in self.frames(resumed)
            if frame["details"].get("replayed") is True
        }
        self.assertIn("confirm", replayed)

    def test_a_replayed_gate_re_takes_a_REVISE_and_not_a_convenient_approve(self) -> None:
        """The test that can tell the fix from a hardcoded `approve`.

        `route_gate` on a replayed gate is handed no `HumanFeedbackResult` at
        all, and `gate_decision(None)` is an approve - so a replay that simply
        let the live path run would send every resume down the approve port and
        every assertion about a completed run would still pass. Here it cannot:
        the source run died INSIDE the revise lap, so approve skips `redo`
        entirely and `redo` is the node being resumed from.
        """

        _, workflow_id = self.publish(gated_loop(), self.as_alice())
        runtime = self.registry.workflow_runtime(workflow_id)
        runtime.runner.crew_factories = SyntheticCrewFactories(failures="redo:rate_limit")
        source = self.drive(workflow_id, "revise")
        failed = self.snapshot(source)
        self.assertEqual(failed["status"], "failed", failed)

        clean = SyntheticCrewFactories()
        runtime.runner.crew_factories = clean
        resumed = self.drive(
            workflow_id, resume_from={"run_id": source, "node_id": "redo"}
        )
        body = self.snapshot(resumed)
        self.assertEqual(body["status"], "completed", body)
        # The revise branch was taken again, so the node the operator sent the
        # run back to is the node that ran.
        self.assertIn("redo", [node_id for node_id, _ in clean.calls])
        replayed = {
            frame["node_id"]
            for frame in self.frames(resumed)
            if frame["details"].get("replayed") is True
        }
        self.assertEqual(replayed, {"idea", "confirm"})

    def test_a_node_test_below_a_gate_runs_only_that_node(self) -> None:
        """13 D4's derived plan meets the same gate, and mocks its decision.

        A node test compiles every ancestor as a replay and drops everything
        downstream, so the gate above the node under test is exactly the shape
        that broke - and here the decision comes from the author's saved mocks
        rather than from a run, which is the second of `replay_output`'s two
        sources.
        """

        from sqlalchemy import insert

        from brief_crew.service.persistence import builder_test_inputs, utcnow

        document_id, workflow_id = self.publish(gated(), self.as_alice())
        now = utcnow()
        with self.registry.persistence.begin() as connection:
            connection.execute(
                insert(builder_test_inputs).values(
                    id="ti_gated",
                    user_id=ALICE.id,
                    document_id=document_id,
                    label="past the gate",
                    inputs={"idea": IDEA},
                    node_mocks={
                        "idea": IDEA,
                        "confirm": {"decision": "approve", "honoured": False},
                    },
                    created_at=now,
                    updated_at=now,
                )
            )

        runtime = self.registry.workflow_runtime(workflow_id)
        factories = SyntheticCrewFactories()
        runtime.runner.crew_factories = factories
        run_id = self.drive(
            workflow_id,
            mode="node_test",
            node_id="safe",
            test_input_id="ti_gated",
        )
        body = self.snapshot(run_id)
        self.assertEqual(body["status"], "completed", body)
        self.assertEqual([node_id for node_id, _ in factories.calls], ["safe"])

    def test_a_gate_the_source_run_never_answered_is_refused_with_its_name(self) -> None:
        """A resume needs the DECISION, and a run that stopped at the gate has none.

        422 rather than a run that fails later: the caller can act on it, and
        the alternative is a queue slot spent to be told the same thing.
        """

        _, workflow_id = self.publish(gated(), self.as_alice())
        response = self.launch(workflow_id)
        source = response.json()["run_id"]
        self.registry.wait(source, timeout=20)
        self.registry.cancel(source)
        self.registry.wait(source, timeout=20)

        refused = self.launch(
            workflow_id, resume_from={"run_id": source, "node_id": "safe"}
        )
        self.assertEqual(refused.status_code, 422, refused.text)
        self.assertIn("confirm", refused.json()["detail"])


class ReplayOfARoutedFailureTests(unittest.TestCase):
    """An `on_error: route` node above the resume point - the other routed kind.

    Its paired router reads `err__<node>`, which is a state key `out__<node>`
    does not carry, so a replay that restored only the output would replay a
    node that EXPLODED as one that succeeded and send the derived run down the
    branch the author drew for the other outcome. In process and free: the one
    node that runs is a stub.
    """

    def _graph(self) -> Any:
        return document(
            [
                input_node(),
                authored_agent_node("draft", on_error="route"),
                authored_agent_node("apology", source="draft"),
                authored_agent_node("onward", source="draft"),
                output_node("report", source="${state.out__apology}"),
            ],
            [
                edge("e1", "idea", "draft"),
                edge("e2", "draft", "onward", source_port="out"),
                edge("e3", "draft", "apology", source_port="error"),
                edge("e4", "apology", "report"),
            ],
        )

    def test_the_error_key_is_restored_beside_the_output(self) -> None:
        from brief_crew.builder.runtime import replay_output, replay_source

        class Stub:
            def __init__(self) -> None:
                self.state: dict[str, Any] = {}

        flow = Stub()
        with replay_source({"draft": ""}, {"draft": "ToolError: boom"}):
            replay_output(flow, node_id="draft")
        self.assertEqual(flow.state["err__draft"], "ToolError: boom")
        self.assertEqual(flow.state["out__draft"], "")

    def test_a_node_with_no_recorded_failure_replays_as_a_success(self) -> None:
        """The control. Restoring `err__` unconditionally would route every replay
        down the error port, which would look exactly like the fix working."""

        from brief_crew.builder.runtime import replay_output, replay_source

        class Stub:
            def __init__(self) -> None:
                self.state: dict[str, Any] = {}

        flow = Stub()
        with replay_source({"draft": "fine"}):
            replay_output(flow, node_id="draft")
        self.assertNotIn("err__draft", flow.state)

    def test_the_error_router_takes_the_branch_the_source_run_took(self) -> None:
        from crewai.flow.flow import Flow

        from brief_crew.builder.compiler import compile_replay_plan
        from brief_crew.builder.runtime import replay_source, use_crew_factories

        compiled = compile_replay_plan(self._graph(), node_id="apology")
        stub = StubFactories({"apology": "sorry about that"})
        flow = Flow.from_declaration(
            contents=compiled.definition, suppress_flow_events=True
        )
        with use_crew_factories(stub), replay_source(
            {"idea": IDEA, "draft": ""}, {"draft": "ToolError: boom"}
        ):
            flow.kickoff(inputs={"idea": IDEA})
        # Only the resume point ran, and it is the one on the ERROR port.
        self.assertEqual([node_id for node_id, _ in stub.kickoffs], ["apology"])
        self.assertEqual(flow.state["err__draft"], "ToolError: boom")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
