"""12 D8's six failure modes: each one legible, each one recoverable.

The table in `.agent/plans/12-error-handling.md` D8 names six ways a builder
graph fails, and for each a trigger, what the canvas says, what the log says and
what the author does next. This module is the Python half of that table.

**Five of the six RUN and one never does**, and that asymmetry is the whole
argument of the plan. A bad key, a tool timeout, a refusal, a malformed answer
and a rate limit are all discovered by executing something; a cyclic graph is
refused by `bounds.py` at validate and again at publish, so there is no run, no
node and no frame - which is why `SYNTHETIC_FAILURE_REASONS` has five entries
and not six. Flowise's equivalent check (`docs/flowise-notes.md` §1) drops the
edge silently on the canvas and finds out at run time; this one is a sentence
with the closing edge named in it, before anything bills.

Every mode is one value of `SYNTHETIC_FAILURE`, read PER INSTANCE, so a critic
triggering all six from a browser restarts nothing. `SYNTHETIC_FAILURE_NODE`
says which node when the entry does not, which is what makes the knob usable on
a graph whose ids the person setting it did not write.

`test_no_secret_in_any_failure` is criterion 4, and it is the one that would go
vacuous most easily: a synthetic factory that never resolves a credential would
pass a leak test having never held the secret. `ResolvingFactories` builds the
REAL `Agent` and so the REAL `LLM` - which resolves the key and costs nothing,
because construction calls no model - and the test asserts it held the sentinel
BEFORE asserting the sentinel is nowhere else.

No cost: every billable node here is built by the double `SYNTHETIC=1`
installs, and the two places a real `Agent` is constructed call no model.
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
from typing import Any
import unittest
import zipfile
from unittest.mock import patch

from brief_crew.builder import structural_problems
from brief_crew.builder.runtime import DefaultCrewFactories
from brief_crew.config import RUN_RESULT_BODY_KEYS
from brief_crew.service.builder_runner import (
    SYNTHETIC_FAILURE_REASONS,
    SyntheticCrewFactories,
    parse_synthetic_failures,
)
from tests.builder.test_compiler import authored_agent_node, input_node, output_node
from tests.builder.test_document import document, edge, node
from tests.service.identities import SECRET, AuthenticatedTwoUserCase, wire

FASTAPI_AVAILABLE = importlib.util.find_spec("fastapi") is not None
BODY_KEY = RUN_RESULT_BODY_KEYS[0]
IDEA = "a scheduling assistant for clinics"

#: D8's five running modes, as `(SYNTHETIC_FAILURE reason, C6 error_class)`.
#: Written out rather than derived from `SYNTHETIC_FAILURE_REASONS`, because a
#: table derived from the thing it checks agrees with itself by construction.
RUNNING_MODES: tuple[tuple[str, str], ...] = (
    ("bad_key", "auth"),
    ("tool_timeout", "tool_timeout"),
    ("refusal", "refusal"),
    ("malformed_output", "schema"),
    ("rate_limit", "rate_limit"),
)


def two_step(*, retry: dict[str, Any] | None = None, on_error: str = "fail") -> Any:
    """`idea -> a -> b -> report`, both steps authored.

    Two billable steps and not one, because criterion 3 asks that
    `resume_from` the failed node completes - and a resume that replayed
    nothing would prove only that a run can be started twice. `b` is the node
    every mode below is aimed at, so `a`'s output is what the replay carries.
    """

    return document(
        [
            input_node(),
            authored_agent_node("a"),
            authored_agent_node("b", source="a", retry=retry, on_error=on_error),
            output_node("report", source="${state.out__b}"),
        ],
        [
            edge("e1", "idea", "a"),
            edge("e2", "a", "b"),
            edge("e3", "b", "report"),
        ],
    )


def cyclic() -> Any:
    """A loop closed by a plain agent - D8's sixth mode, which never runs.

    The closer is `b`, an agent, and not a router. `bounds.py`'s own module
    docstring records what happens when such a document is compiled anyway: the
    join fires once, the second arrival is suppressed, and `kickoff()` returns
    normally having produced nothing.
    """

    return document(
        [
            input_node(),
            authored_agent_node("a"),
            authored_agent_node("b", source="a"),
            output_node("report", source="${state.out__b}"),
        ],
        [
            edge("e1", "idea", "a"),
            edge("e2", "a", "b"),
            edge("e3", "b", "a"),
            edge("e4", "b", "report"),
        ],
    )


class ResolvingFactories(SyntheticCrewFactories):
    """Builds the real `Agent` (and so the real `LLM`), kicks off synthetically.

    The same shape `tests/service/test_credentials_runtime.py` uses, and here
    for the same reason: a plain synthetic factory never calls `_authored_llm`,
    so a leak test over one would be green without the secret ever having been
    fetched. `built` keeps the agents so the control assertion can look at
    where the plaintext ended up.

    The real construction happens BEFORE `_record`, so a mode that raises still
    resolves the credential first - which is what makes this usable for the
    failure paths as well as for the happy one.
    """

    def __init__(self, failures: str | None = None) -> None:
        super().__init__(failures=failures)
        self.built: list[Any] = []

    def authored_agent_crew(self, *, node_id: str, spec: Any) -> Any:
        self.built.append(DefaultCrewFactories()._authored_agent(spec, node_id=node_id))
        return super().authored_agent_crew(node_id=node_id, spec=spec)


class SyntheticFailureGrammarTests(unittest.TestCase):
    """The knob itself, before anything is run with it."""

    def test_the_five_running_modes_are_the_declared_reasons(self) -> None:
        self.assertEqual(
            sorted(reason for reason, _ in RUNNING_MODES),
            sorted(SYNTHETIC_FAILURE_REASONS),
        )

    def test_there_is_deliberately_no_cyclic_graph_reason(self) -> None:
        """The sixth mode has no runtime trigger because it has no run.

        A reason that produced one would be a synthetic double diverging from
        its subject, which is the failure CLAUDE.md's closed items 20 and 33
        both are.
        """

        self.assertNotIn("cyclic_graph", SYNTHETIC_FAILURE_REASONS)

    def test_each_reason_carries_d8s_error_class(self) -> None:
        for reason, error_class in RUNNING_MODES:
            with self.subTest(reason=reason):
                self.assertEqual(
                    SYNTHETIC_FAILURE_REASONS[reason].error_class, error_class
                )

    def test_the_default_node_applies_only_where_no_node_was_named(self) -> None:
        """`SYNTHETIC_FAILURE_NODE`, and the precedence that keeps it additive."""

        plans = parse_synthetic_failures("refusal", default_node="b")
        self.assertEqual([plan.node_id for plan in plans], ["b"])
        self.assertTrue(plans[0].applies_to("b"))
        self.assertFalse(plans[0].applies_to("a"))

        named = parse_synthetic_failures("a:refusal", default_node="b")
        self.assertEqual([plan.node_id for plan in named], ["a"])

        everywhere = parse_synthetic_failures("refusal")
        self.assertTrue(everywhere[0].applies_to("anything at all"))

    def test_the_environment_is_what_a_bare_factory_reads(self) -> None:
        with patch.dict(
            os.environ,
            {"SYNTHETIC_FAILURE": "refusal", "SYNTHETIC_FAILURE_NODE": "b"},
        ):
            factories = SyntheticCrewFactories()
        self.assertEqual([plan.node_id for plan in factories.plans], ["b"])

    def test_an_unreadable_value_is_no_failure_rather_than_a_crash(self) -> None:
        """A typo in a testing knob must not be how a free backend refuses to start."""

        self.assertEqual(parse_synthetic_failures("not_a_mode"), ())
        self.assertEqual(parse_synthetic_failures(None), ())


class CyclicGraphTests(unittest.TestCase):
    """D8's sixth mode, which is refused before anything can bill."""

    def test_a_loop_closed_by_an_agent_is_refused_with_the_edge_named(self) -> None:
        problems = [
            problem
            for problem in structural_problems(cyclic())
            if problem.code == "back-edge-not-router"
        ]
        self.assertEqual(len(problems), 1, "the closing edge is not reported")
        problem = problems[0]
        self.assertEqual(problem.severity, "error")
        self.assertEqual(problem.edge_id, "e3")
        self.assertEqual(problem.node_id, "b")
        self.assertIn("router", problem.message)


@unittest.skipUnless(FASTAPI_AVAILABLE, "fastapi is not installed")
class FailureModeCase(AuthenticatedTwoUserCase):
    """A published two-step graph and one knob, per mode."""

    def setUp(self) -> None:
        super().setUp()
        self.registry = self.app.state.run_registry

    def install(self, graph: Any, reason: str | None, *, node_id: str = "b") -> str:
        """Publish `graph` and give its runner factories built from the KNOB.

        The environment is what the factory reads, so what is exercised is the
        knob a critic would set and not a constructor argument only a test can
        reach. The runner is built at publish, so the swap happens on the object
        the registry already holds - `test_error_routing.py` does the same, and
        for the same reason: this app has other runners that must not fail.
        """

        _, workflow_id = self.publish(graph, self.as_alice())
        environment = (
            {"SYNTHETIC_FAILURE": reason, "SYNTHETIC_FAILURE_NODE": node_id}
            if reason
            else {"SYNTHETIC_FAILURE": "", "SYNTHETIC_FAILURE_NODE": ""}
        )
        with patch.dict(os.environ, environment):
            factories = SyntheticCrewFactories()
        self.registry.workflow_runtime(workflow_id).runner.crew_factories = factories
        return workflow_id

    def clear_failure(self, workflow_id: str) -> None:
        """What "fix the credential and re-run" means to a synthetic backend."""

        with patch.dict(os.environ, {"SYNTHETIC_FAILURE": "", "SYNTHETIC_FAILURE_NODE": ""}):
            self.registry.workflow_runtime(workflow_id).runner.crew_factories = (
                SyntheticCrewFactories()
            )

    def run_to_end(self, workflow_id: str, **body: Any) -> str:
        payload: dict[str, Any] = {"workflow_id": workflow_id, "inputs": {"idea": IDEA}}
        payload.update(body)
        response = self.client.post(
            "/api/sessions/s1/runs", json=payload, headers=self.as_alice()
        )
        self.assertEqual(response.status_code, 202, response.text)
        run_id = response.json()["run_id"]
        self.registry.wait(run_id, timeout=30)
        return run_id

    def frames(self, run_id: str) -> list[dict[str, Any]]:
        page = self.client.get(
            f"/api/runs/{run_id}/frames?limit=500", headers=self.as_alice()
        ).json()
        return [frame["data"] for frame in page["frames"]]

    def node_errors(self, run_id: str) -> list[dict[str, Any]]:
        """The C6 `node_error` frames, and only those.

        `stage: "error"` alone is not the discriminator: `serializer.py:455`
        raises one for CrewAI's own `MethodExecutionFailedEvent`, and a tool, an
        llm call and a crew each raise another. Those are the package narrating
        the same failure from its own side and they carry no `attempt`, which is
        the field this plan's frames are told apart by - `attempt` and
        `will_retry` are decisions the RUNTIME made and CrewAI has no event for
        either.
        """

        return [
            dict(frame["details"])
            for frame in self.frames(run_id)
            if dict(frame["details"] or {}).get("stage") == "error"
            and "attempt" in dict(frame["details"] or {})
        ]

    def snapshot(self, run_id: str) -> dict[str, Any]:
        return self.client.get(f"/api/runs/{run_id}", headers=self.as_alice()).json()

    def assert_mode(self, reason: str, error_class: str, **graph: Any) -> str:
        """D8's row, asserted: the frame, its class, and a terminal `failed`."""

        workflow_id = self.install(two_step(**graph), reason)
        run_id = self.run_to_end(workflow_id)

        errors = self.node_errors(run_id)
        self.assertTrue(errors, f"{reason} produced no node_error frame at all")
        self.assertEqual(errors[-1]["error_class"], error_class)
        # The node the knob named, and not the one before it.
        failed = [
            frame["node_id"]
            for frame in self.frames(run_id)
            if dict(frame["details"] or {}).get("stage") == "error"
            and "attempt" in dict(frame["details"] or {})
        ]
        self.assertEqual(set(failed), {"b"})
        self.assertEqual(self.snapshot(run_id)["status"], "failed")
        return workflow_id


@unittest.skipUnless(FASTAPI_AVAILABLE, "fastapi is not installed")
class RunningModeTests(FailureModeCase):
    """The five that run, one test each - criterion 3."""

    def test_bad_api_key(self) -> None:
        """401. Not retryable: the same key is rejected identically next time."""

        self.assert_mode("bad_key", "auth")

    def test_tool_timeout(self) -> None:
        """408, and the one of the five the node loop WILL spend an attempt on."""

        self.assert_mode("tool_timeout", "tool_timeout")

    def test_model_refusal(self) -> None:
        """Decision 16 made observable: a refusal is a decision, never retried."""

        workflow_id = self.assert_mode("refusal", "refusal")
        run_id = self.run_to_end(workflow_id)
        self.assertFalse(
            any(error["will_retry"] for error in self.node_errors(run_id)),
            "a refusal was retried; decision 16 says a second judge is not a retry",
        )

    def test_malformed_output(self) -> None:
        """The schema failed after the guardrail loop; another attempt is not the repair."""

        workflow_id = self.assert_mode("malformed_output", "schema")
        run_id = self.run_to_end(workflow_id)
        self.assertFalse(any(error["will_retry"] for error in self.node_errors(run_id)))

    def test_rate_limit(self) -> None:
        """429, retried, and the retry frames say attempt N of M - D8's row."""

        workflow_id = self.install(
            two_step(retry={"max_retries": 2, "backoff_seconds": 0}), "rate_limit"
        )
        run_id = self.run_to_end(workflow_id)

        errors = self.node_errors(run_id)
        self.assertEqual([error["error_class"] for error in errors], ["rate_limit"] * 3)
        self.assertEqual([error["attempt"] for error in errors], [1, 2, 3])
        # Amber while retrying, red once exhausted: the first two say another
        # attempt is coming and the last one does not.
        self.assertEqual(
            [error["will_retry"] for error in errors], [True, True, False]
        )
        self.assertEqual(self.snapshot(run_id)["status"], "failed")

    def test_a_clean_run_of_the_same_graph_is_the_control(self) -> None:
        """Without this, every assertion above would pass over a graph that never works."""

        workflow_id = self.install(two_step(), None)
        run_id = self.run_to_end(workflow_id)
        self.assertEqual(self.node_errors(run_id), [])
        self.assertEqual(self.snapshot(run_id)["status"], "completed")


@unittest.skipUnless(FASTAPI_AVAILABLE, "fastapi is not installed")
class RecoveryTests(FailureModeCase):
    """Criterion 3's second half: `resume_from` the failed node completes.

    Every one of D8's recovery columns ends in **Re-run from here**, and the
    repair before it - a new key, a looser schema, a longer timeout - is a thing
    a human does between the two runs. Clearing the knob is what that looks like
    to a synthetic backend.
    """

    def test_every_running_mode_resumes_from_the_node_that_failed(self) -> None:
        for reason, _ in RUNNING_MODES:
            with self.subTest(reason=reason):
                workflow_id = self.install(two_step(), reason)
                failed = self.run_to_end(workflow_id)
                self.assertEqual(self.snapshot(failed)["status"], "failed")

                self.clear_failure(workflow_id)
                resumed = self.run_to_end(
                    workflow_id, resume_from={"run_id": failed, "node_id": "b"}
                )
                body = self.snapshot(resumed)
                self.assertEqual(body["status"], "completed", body.get("error"))
                self.assertIn(BODY_KEY, body["result"])

    def test_the_resume_replays_the_node_that_had_already_been_paid_for(self) -> None:
        """The point of resuming rather than relaunching, stated as an assertion."""

        workflow_id = self.install(two_step(), "refusal")
        failed = self.run_to_end(workflow_id)
        self.clear_failure(workflow_id)
        resumed = self.run_to_end(
            workflow_id, resume_from={"run_id": failed, "node_id": "b"}
        )
        replayed = {
            frame["node_id"]
            for frame in self.frames(resumed)
            if dict(frame["details"] or {}).get("replayed") is True
        }
        self.assertEqual(replayed, {"idea", "a"})
        self.assertNotIn("b", replayed)

    def test_a_routed_failure_completes_instead_of_failing(self) -> None:
        """D3's other recovery: the error PORT, rather than a second run.

        Asserted here beside the resume because D8's table offers the two as
        alternatives on the same row, and a reader of one wants the other.
        """

        graph = document(
            [
                input_node(),
                authored_agent_node("a"),
                authored_agent_node("b", source="a", on_error="route"),
                authored_agent_node("fallback", source="a"),
                output_node("report", source="${state.out__fallback}"),
            ],
            [
                edge("e1", "idea", "a"),
                edge("e2", "a", "b"),
                edge("e3", "b", "fallback", source_port="error"),
                edge("e4", "fallback", "report"),
            ],
        )
        workflow_id = self.install(graph, "tool_timeout")
        run_id = self.run_to_end(workflow_id)
        self.assertEqual(self.snapshot(run_id)["status"], "completed")
        self.assertTrue(self.node_errors(run_id)[-1]["routed"])


@unittest.skipUnless(FASTAPI_AVAILABLE, "fastapi is not installed")
class SentinelTests(AuthenticatedTwoUserCase):
    """Criterion 4: no failure mode leaks the key, on any surface.

    One run per mode, each one REALLY resolving the credential, then the five
    places the plaintext could have reached: the frames, the run row, the status
    payload, the NDJSON export and the ZIP.
    """

    def setUp(self) -> None:
        super().setUp()
        self.registry = self.app.state.run_registry
        self.credential = self.create_credential(self.as_alice())["id"]

    def run_with(self, reason: str) -> tuple[str, ResolvingFactories]:
        graph = document(
            [
                input_node(),
                node(
                    "b",
                    "agent",
                    {
                        **authored_agent_node("b")["config"],
                        "credential_id": self.credential,
                        "task": {
                            "description": "work from ${state.out__idea}",
                            "expected_output": "a paragraph",
                        },
                    },
                ),
                output_node("report", source="${state.out__b}"),
            ],
            [edge("e1", "idea", "b"), edge("e2", "b", "report")],
        )
        _, workflow_id = self.publish(graph, self.as_alice())
        with patch.dict(
            os.environ,
            {"SYNTHETIC_FAILURE": reason, "SYNTHETIC_FAILURE_NODE": "b"},
        ):
            factories = ResolvingFactories()
        self.registry.workflow_runtime(workflow_id).runner.crew_factories = factories
        response = self.client.post(
            "/api/sessions/s1/runs",
            json={"workflow_id": workflow_id, "inputs": {"idea": IDEA}},
            headers=self.as_alice(),
        )
        self.assertEqual(response.status_code, 202, response.text)
        run_id = response.json()["run_id"]
        self.registry.wait(run_id, timeout=30)
        return run_id, factories

    def test_no_secret_in_any_failure(self) -> None:
        for reason, _ in RUNNING_MODES:
            with self.subTest(reason=reason):
                run_id, factories = self.run_with(reason)

                # The control, first. Without it the five assertions below would
                # be satisfied by a run that never held the key.
                self.assertTrue(
                    factories.built, f"{reason} built no real agent; this would be vacuous"
                )
                self.assertEqual(factories.built[0].llm.api_key, SECRET)

                frames = self.client.get(
                    f"/api/runs/{run_id}/frames?limit=500", headers=self.as_alice()
                )
                self.assertNotIn(SECRET, frames.text)

                row = self.registry.persistence.get_run(run_id)
                self.assertNotIn(SECRET, json.dumps(row, default=str))

                snapshot = self.client.get(
                    f"/api/runs/{run_id}", headers=self.as_alice()
                )
                self.assertNotIn(SECRET, snapshot.text)

                ndjson = self.client.get(
                    f"/api/runs/{run_id}/logs?format=ndjson", headers=self.as_alice()
                )
                self.assertEqual(ndjson.status_code, 200, ndjson.text)
                self.assertNotIn(SECRET, ndjson.text)

                archive = self.client.get(
                    f"/api/runs/{run_id}/logs?format=zip", headers=self.as_alice()
                )
                self.assertEqual(archive.status_code, 200)
                with zipfile.ZipFile(io.BytesIO(archive.content)) as zipped:
                    for name in zipped.namelist():
                        self.assertNotIn(
                            SECRET, zipped.read(name).decode("utf-8", "replace")
                        )

    def test_the_failure_sentence_names_the_node_and_not_the_key(self) -> None:
        """D8's log column: the credential LABEL, never the value."""

        run_id, _ = self.run_with("bad_key")
        page = self.client.get(
            f"/api/runs/{run_id}/frames?limit=500", headers=self.as_alice()
        ).json()
        sentences = [
            str(dict(frame["data"]["details"] or {}).get("message", ""))
            for frame in page["frames"]
            if "attempt" in dict(frame["data"]["details"] or {})
        ]
        self.assertTrue(sentences)
        self.assertIn("SyntheticBadCredential", " ".join(sentences))
        self.assertIn("b", " ".join(sentences))
        self.assertNotIn(SECRET, " ".join(sentences))


if __name__ == "__main__":
    unittest.main()


# `wire` is imported for symmetry with the other builder service modules, which
# publish through it; `publish` on the base case already applies it.
_ = wire
