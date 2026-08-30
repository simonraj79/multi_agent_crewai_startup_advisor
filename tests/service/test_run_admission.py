"""Hardening for the one public endpoint that spends the owner's money.

``POST /api/sessions/{session_id}/runs`` is deployed unauthenticated on
purpose - the owner wants to hand the URL to people and have them click Launch
- so the guards under test here all have to be invisible to one honest visitor
and expensive for a script:

* the input bounds, which turn an attacker-controlled prompt into a constant;
* the admission cap, which bounds the executor's otherwise unbounded work
  queue so a flood cannot starve the owner's own run;
* a per-client token bucket on run creation ONLY, so /healthz, /readyz and
  every read-only GET stay untouched and monitoring is unaffected;
* the OpenAPI documents, which are off unless the app is synthetic or an
  operator asks for them.

Everything here is no-cost. The runners are the synthetic doubles or a local
parked callable - no LLM, no tool, no network - and the limiter's clock is
injected, so nothing waits on a wall clock for correctness.
"""

from __future__ import annotations

import importlib.util
import threading
import unittest
from unittest.mock import patch


FASTAPI_AVAILABLE = importlib.util.find_spec("fastapi") is not None

# How long a parked worker waits before giving up on its release signal. Long
# enough that it never fires in a passing run, short enough that a failing test
# finishes instead of hanging the suite.
PARK_TIMEOUT_SECONDS = 20.0
JOIN_TIMEOUT_SECONDS = 20.0


class FakeClock:
    """A monotonic clock the test moves by hand. No sleeping, no flake."""

    def __init__(self, start: float = 1000.0) -> None:
        self._now = float(start)

    def __call__(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += float(seconds)


class ParkedRunner:
    """A run that holds its worker until the test releases it.

    With ``RUN_CONCURRENCY`` at 1 the first of these occupies the single
    worker and every later submission sits in the executor's internal queue -
    which is exactly the unbounded structure the admission cap exists to
    bound - so both count as "queued or in flight".
    """

    def __init__(self) -> None:
        self.release = threading.Event()
        self.entered = threading.Semaphore(0)

    def __call__(self, execution: object) -> dict[str, bool]:
        self.entered.release()
        self.release.wait(timeout=PARK_TIMEOUT_SECONDS)
        return {"parked": True}


# --------------------------------------------------------------------------
# The limiter itself, with no HTTP anywhere near it.
# --------------------------------------------------------------------------
@unittest.skipUnless(
    FASTAPI_AVAILABLE,
    "FastAPI is not installed; install the existing project service extra",
)
class RunRateLimiterTests(unittest.TestCase):
    def limiter(self, **kwargs: object):
        from brief_crew.service.app import RunRateLimiter

        return RunRateLimiter(**kwargs)  # type: ignore[arg-type]

    def test_a_burst_is_allowed_and_the_next_call_is_refused(self) -> None:
        clock = FakeClock()
        limiter = self.limiter(max_runs=3, window_seconds=60.0, clock=clock)

        self.assertEqual(
            [limiter.acquire("ip") for _ in range(3)], [0.0, 0.0, 0.0]
        )
        retry_after = limiter.acquire("ip")
        self.assertGreater(retry_after, 0.0)
        # One token refills every window/capacity seconds, so a bucket that
        # just emptied is 20 s from its next token at 3 per minute.
        self.assertAlmostEqual(retry_after, 20.0, places=6)

    def test_the_bucket_refills_and_the_client_recovers(self) -> None:
        clock = FakeClock()
        limiter = self.limiter(max_runs=2, window_seconds=60.0, clock=clock)

        self.assertEqual(limiter.acquire("ip"), 0.0)
        self.assertEqual(limiter.acquire("ip"), 0.0)
        self.assertGreater(limiter.acquire("ip"), 0.0)

        # Not yet: half a token is not a token.
        clock.advance(15.0)
        self.assertGreater(limiter.acquire("ip"), 0.0)

        clock.advance(15.0)
        self.assertEqual(limiter.acquire("ip"), 0.0)

    def test_refusals_do_not_spend_tokens_they_do_not_have(self) -> None:
        """A refused call must not push the recovery time further out.

        Otherwise a client that retries in a tight loop locks itself out for
        as long as it keeps retrying, which is the classic way a courtesy
        limiter turns into an outage for the person it was meant to protect.
        """
        clock = FakeClock()
        limiter = self.limiter(max_runs=1, window_seconds=10.0, clock=clock)

        self.assertEqual(limiter.acquire("ip"), 0.0)
        for _ in range(20):
            self.assertGreater(limiter.acquire("ip"), 0.0)

        clock.advance(10.0)
        self.assertEqual(limiter.acquire("ip"), 0.0)

    def test_the_bucket_never_refills_past_its_capacity(self) -> None:
        clock = FakeClock()
        limiter = self.limiter(max_runs=2, window_seconds=60.0, clock=clock)

        self.assertEqual(limiter.acquire("ip"), 0.0)
        clock.advance(86_400.0)

        self.assertEqual(limiter.acquire("ip"), 0.0)
        self.assertEqual(limiter.acquire("ip"), 0.0)
        self.assertGreater(limiter.acquire("ip"), 0.0)

    def test_clients_have_separate_buckets(self) -> None:
        clock = FakeClock()
        limiter = self.limiter(max_runs=1, window_seconds=60.0, clock=clock)

        self.assertEqual(limiter.acquire("client-a"), 0.0)
        self.assertGreater(limiter.acquire("client-a"), 0.0)
        self.assertEqual(limiter.acquire("client-b"), 0.0)

    def test_capacity_zero_disables_the_limiter(self) -> None:
        limiter = self.limiter(max_runs=0, window_seconds=60.0, clock=FakeClock())

        self.assertFalse(limiter.enabled)
        self.assertEqual([limiter.acquire("ip") for _ in range(50)], [0.0] * 50)

    def test_the_client_map_is_bounded(self) -> None:
        """The key is attacker-supplied text, so the map needs its own ceiling."""
        limiter = self.limiter(
            max_runs=1,
            window_seconds=60.0,
            max_clients=8,
            clock=FakeClock(),
        )

        for index in range(500):
            limiter.acquire(f"ip-{index}")

        self.assertLessEqual(len(limiter._buckets), 8)

    def test_acquire_is_thread_safe(self) -> None:
        """Concurrent callers must spend exactly the tokens that exist."""
        clock = FakeClock()
        limiter = self.limiter(max_runs=10, window_seconds=600.0, clock=clock)
        allowed: list[float] = []
        allowed_lock = threading.Lock()
        start = threading.Barrier(24)

        def hammer() -> None:
            start.wait(timeout=JOIN_TIMEOUT_SECONDS)
            outcome = limiter.acquire("shared")
            if outcome == 0.0:
                with allowed_lock:
                    allowed.append(outcome)

        threads = [threading.Thread(target=hammer) for _ in range(24)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=JOIN_TIMEOUT_SECONDS)
            self.assertFalse(thread.is_alive())

        self.assertEqual(len(allowed), 10)

    def test_a_bad_configuration_is_refused_at_construction(self) -> None:
        with self.assertRaises(ValueError):
            self.limiter(max_runs=-1)
        with self.assertRaises(ValueError):
            self.limiter(max_runs=1, window_seconds=0.0)
        with self.assertRaises(ValueError):
            self.limiter(max_runs=1, max_clients=0)


@unittest.skipUnless(
    FASTAPI_AVAILABLE,
    "FastAPI is not installed; install the existing project service extra",
)
class ClientKeyTests(unittest.TestCase):
    """How a caller is identified. Advisory - see config.py, it is spoofable."""

    class StubRequest:
        def __init__(self, headers: dict[str, str], host: str | None) -> None:
            self.headers = headers
            self.client = type("Peer", (), {"host": host})() if host else None

    def key(self, headers: dict[str, str], host: str | None = "10.0.0.1") -> str:
        from brief_crew.service.app import client_rate_limit_key

        return client_rate_limit_key(self.StubRequest(headers, host))

    def test_the_leftmost_forwarded_for_entry_wins(self) -> None:
        self.assertEqual(
            self.key({"x-forwarded-for": "203.0.113.7, 10.1.1.1, 10.1.1.2"}),
            "203.0.113.7",
        )

    def test_the_peer_is_used_when_no_header_is_present(self) -> None:
        self.assertEqual(self.key({}), "10.0.0.1")

    def test_a_clientless_scope_still_yields_a_key(self) -> None:
        self.assertEqual(self.key({}, host=None), "unknown")

    def test_the_key_is_length_bounded(self) -> None:
        from brief_crew.config import RUN_RATE_LIMIT_KEY_MAX_CHARS

        key = self.key({"x-forwarded-for": "a" * 5000})
        self.assertEqual(len(key), RUN_RATE_LIMIT_KEY_MAX_CHARS)

    def test_the_header_is_ignored_when_it_is_not_trusted(self) -> None:
        from brief_crew import config as project_config

        with patch.object(project_config, "RUN_RATE_LIMIT_TRUST_FORWARDED_FOR", False):
            self.assertEqual(self.key({"x-forwarded-for": "203.0.113.7"}), "10.0.0.1")


# --------------------------------------------------------------------------
# The endpoint.
# --------------------------------------------------------------------------
@unittest.skipUnless(
    FASTAPI_AVAILABLE,
    "FastAPI is not installed; install the existing project service extra",
)
class ServiceHardeningTestCase(unittest.TestCase):
    """Builders shared by the HTTP cases below."""

    def synthetic_client(self, **kwargs: object):
        """A no-cost app with the limiter disabled unless a test wants one."""
        from fastapi.testclient import TestClient

        from brief_crew.service.app import RunRateLimiter, create_app

        kwargs.setdefault("rate_limiter", RunRateLimiter(max_runs=0))
        client = TestClient(create_app(synthetic=True, **kwargs))  # type: ignore[arg-type]
        self.addCleanup(client.close)
        return client

    def parked_client(self, *, max_queued_runs: int):
        """An app whose runs stay in flight until the test releases them."""
        from fastapi.testclient import TestClient

        from brief_crew.service.app import RunRateLimiter, create_app
        from brief_crew.service.graph import BRIEF_GRAPH, BRIEF_NODE_REGISTRY
        from brief_crew.service.registry import RunRegistry, WorkflowRuntime

        runner = ParkedRunner()
        registry = RunRegistry(
            graph_version=BRIEF_GRAPH.version,
            node_registry=BRIEF_NODE_REGISTRY,
            runner=runner,
            workflows={
                BRIEF_GRAPH.id: WorkflowRuntime(
                    graph_version=BRIEF_GRAPH.version,
                    node_registry=BRIEF_NODE_REGISTRY,
                    runner=runner,
                ),
            },
            gate_sweep_interval=0,
            max_queued_runs=max_queued_runs,
        )

        def shutdown() -> None:
            # Release before close: close() joins the executor, and a parked
            # worker would hang the suite rather than fail a test.
            runner.release.set()
            registry.close()

        self.addCleanup(shutdown)
        client = TestClient(create_app(registry=registry, rate_limiter=RunRateLimiter(max_runs=0)))
        self.addCleanup(client.close)
        return client, registry, runner

    @staticmethod
    def launch(client, body: dict[str, object], **kwargs: object):
        return client.post("/api/sessions/s-1/runs", json=body, **kwargs)

    @staticmethod
    def brief(topic: str = "a perfectly ordinary topic") -> dict[str, object]:
        return {"workflow_id": "brief-flow", "inputs": {"topic": topic}}


class InputBoundTests(ServiceHardeningTestCase):
    def test_a_normal_idea_is_still_accepted(self) -> None:
        client = self.synthetic_client()

        response = self.launch(
            client,
            {
                "workflow_id": "idea-validator",
                "inputs": {"idea": "A scheduling assistant for small clinics"},
            },
        )

        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()["status"], "queued")

    def test_an_over_long_idea_is_refused_with_a_readable_422(self) -> None:
        from brief_crew.config import MAX_RUN_INPUT_CHARS

        client = self.synthetic_client()

        response = self.launch(
            client,
            {
                "workflow_id": "idea-validator",
                "inputs": {"idea": "x" * (MAX_RUN_INPUT_CHARS + 1)},
            },
        )

        self.assertEqual(response.status_code, 422)
        detail = response.json()["detail"]
        self.assertIsInstance(detail, str)
        self.assertIn("inputs.idea", detail)
        self.assertIn(str(MAX_RUN_INPUT_CHARS), detail)

    def test_the_bound_is_the_same_for_brief_flow(self) -> None:
        from brief_crew.config import MAX_RUN_INPUT_CHARS

        client = self.synthetic_client()

        response = self.launch(client, self.brief("y" * (MAX_RUN_INPUT_CHARS + 1)))

        self.assertEqual(response.status_code, 422)
        self.assertIn("inputs.topic", response.json()["detail"])

    def test_an_idea_exactly_at_the_bound_is_accepted(self) -> None:
        from brief_crew.config import MAX_RUN_INPUT_CHARS

        client = self.synthetic_client()

        response = self.launch(client, self.brief("z" * MAX_RUN_INPUT_CHARS))

        self.assertEqual(response.status_code, 202)

    def test_the_whole_inputs_mapping_is_bounded_by_size(self) -> None:
        """`inputs` is dict[str, Any]; the named key is not the only way in."""
        from brief_crew.config import MAX_RUN_INPUT_BYTES

        client = self.synthetic_client()

        response = self.launch(
            client,
            {
                "workflow_id": "brief-flow",
                "inputs": {
                    "topic": "fine",
                    "padding": "p" * (MAX_RUN_INPUT_BYTES + 1),
                },
            },
        )

        self.assertEqual(response.status_code, 422)
        self.assertIn("bytes", response.text)

    def test_the_inputs_mapping_is_bounded_by_key_count(self) -> None:
        from brief_crew.config import MAX_RUN_INPUT_KEYS

        client = self.synthetic_client()

        response = self.launch(
            client,
            {
                "workflow_id": "brief-flow",
                "inputs": {
                    **{f"key-{index}": index for index in range(MAX_RUN_INPUT_KEYS)},
                    "topic": "one too many",
                },
            },
        )

        self.assertEqual(response.status_code, 422)
        self.assertIn("keys", response.text)

    def test_an_oversized_body_is_refused_before_it_is_parsed(self) -> None:
        from brief_crew.config import MAX_REQUEST_BODY_BYTES

        client = self.synthetic_client()

        response = client.post(
            "/api/sessions/s-1/runs",
            content=b"x" * (MAX_REQUEST_BODY_BYTES + 1),
            headers={"content-type": "application/json"},
        )

        self.assertEqual(response.status_code, 413)
        self.assertIn(str(MAX_REQUEST_BODY_BYTES), response.json()["detail"])

    def test_the_body_limit_leaves_ordinary_requests_alone(self) -> None:
        client = self.synthetic_client()

        self.assertEqual(client.get("/healthz").status_code, 200)
        self.assertEqual(self.launch(client, self.brief()).status_code, 202)


class AdmissionCapTests(ServiceHardeningTestCase):
    def test_a_full_queue_is_refused_with_429_and_a_retry_after(self) -> None:
        client, registry, runner = self.parked_client(max_queued_runs=2)

        first = self.launch(client, self.brief("one"))
        second = self.launch(client, self.brief("two"))
        self.assertEqual(first.status_code, 202)
        self.assertEqual(second.status_code, 202)

        refused = self.launch(client, self.brief("three"))
        self.assertEqual(refused.status_code, 429)
        self.assertIn("capacity", refused.json()["detail"])
        self.assertGreaterEqual(int(refused.headers["retry-after"]), 1)
        self.assertEqual(registry.admission_status()["refused"], 1)

        # And the refusal wrote nothing: no durable row, no orphaned record.
        self.assertEqual(registry.admission_status()["active"], 2)

    def test_capacity_is_returned_when_the_runs_finish(self) -> None:
        client, registry, runner = self.parked_client(max_queued_runs=1)

        accepted = self.launch(client, self.brief("first"))
        self.assertEqual(accepted.status_code, 202)
        self.assertEqual(self.launch(client, self.brief("second")).status_code, 429)

        runner.release.set()
        registry.wait(accepted.json()["run_id"], timeout=JOIN_TIMEOUT_SECONDS)

        self.assertEqual(registry.admission_status()["active"], 0)
        self.assertEqual(self.launch(client, self.brief("third")).status_code, 202)

    def test_a_run_waiting_on_a_human_holds_no_slot(self) -> None:
        """A gate is a person thinking, not work. It must not block the queue.

        This is the property that lets MAX_QUEUED_RUNS be small: a validator
        run returns its worker at ``confirm_scope`` and can sit there for the
        whole F03 timeout without costing anyone else a launch.
        """
        with patch("brief_crew.service.registry.MAX_QUEUED_RUNS", 1):
            client = self.synthetic_client()
        registry = client.app.state.run_registry
        self.assertEqual(registry.max_queued_runs, 1)

        first = self.launch(
            client,
            {"workflow_id": "idea-validator", "inputs": {"idea": "first idea"}},
        )
        self.assertEqual(first.status_code, 202)
        run_id = first.json()["run_id"]
        registry.wait(run_id, timeout=JOIN_TIMEOUT_SECONDS)
        self.assertEqual(client.get(f"/api/runs/{run_id}").json()["status"], "waiting")

        second = self.launch(
            client,
            {"workflow_id": "idea-validator", "inputs": {"idea": "second idea"}},
        )

        self.assertEqual(second.status_code, 202)

    def test_a_gate_reply_is_never_refused_for_capacity(self) -> None:
        """Resumes bypass admission on purpose: a flood must not strand a human."""
        with patch("brief_crew.service.registry.MAX_QUEUED_RUNS", 1):
            client = self.synthetic_client()
        registry = client.app.state.run_registry

        run_id = self.launch(
            client,
            {"workflow_id": "idea-validator", "inputs": {"idea": "gated idea"}},
        ).json()["run_id"]
        registry.wait(run_id, timeout=JOIN_TIMEOUT_SECONDS)
        gate = client.get(f"/api/runs/{run_id}").json()["pending_gate"]

        reply = client.post(
            f"/api/runs/{run_id}/gates/{gate['gate_id']}",
            json={"outcome": "approve", "fields": {}},
        )

        self.assertEqual(reply.status_code, 202)

    def test_the_cap_is_validated(self) -> None:
        from brief_crew.service.graph import BRIEF_GRAPH, BRIEF_NODE_REGISTRY
        from brief_crew.service.registry import RunRegistry
        from brief_crew.service.runner import SyntheticRunner

        with self.assertRaises(ValueError):
            RunRegistry(
                graph_version=BRIEF_GRAPH.version,
                node_registry=BRIEF_NODE_REGISTRY,
                runner=SyntheticRunner(),
                gate_sweep_interval=0,
                max_queued_runs=0,
            )


class RunRateLimitEndpointTests(ServiceHardeningTestCase):
    def limited_client(self, *, max_runs: int = 2, window_seconds: float = 60.0):
        from brief_crew.service.app import RunRateLimiter

        clock = FakeClock()
        limiter = RunRateLimiter(
            max_runs=max_runs, window_seconds=window_seconds, clock=clock
        )
        return self.synthetic_client(rate_limiter=limiter), clock

    def test_run_creation_is_limited_and_then_recovers(self) -> None:
        client, clock = self.limited_client(max_runs=2, window_seconds=60.0)

        self.assertEqual(self.launch(client, self.brief("a")).status_code, 202)
        self.assertEqual(self.launch(client, self.brief("b")).status_code, 202)

        refused = self.launch(client, self.brief("c"))
        self.assertEqual(refused.status_code, 429)
        self.assertIn("too many runs", refused.json()["detail"])
        self.assertGreaterEqual(int(refused.headers["retry-after"]), 1)

        clock.advance(30.0)

        self.assertEqual(self.launch(client, self.brief("d")).status_code, 202)

    def test_health_and_read_only_gets_are_never_limited(self) -> None:
        """Monitoring and a reconnecting UI must not be able to trip this."""
        client, _clock = self.limited_client(max_runs=1)

        created = self.launch(client, self.brief("only one"))
        self.assertEqual(created.status_code, 202)
        run_id = created.json()["run_id"]
        client.app.state.run_registry.wait(run_id, timeout=JOIN_TIMEOUT_SECONDS)

        # The bucket is empty; a POST would be refused right now.
        self.assertEqual(self.launch(client, self.brief("second")).status_code, 429)

        for _ in range(20):
            for path in (
                "/healthz",
                "/readyz",
                "/api/workflows",
                "/api/workflows/brief-flow/graph",
                f"/api/runs/{run_id}",
                f"/api/runs/{run_id}/frames?after=0&limit=10",
                f"/api/runs/{run_id}/logs?format=ndjson",
            ):
                self.assertEqual(
                    client.get(path).status_code, 200, msg=f"{path} was limited"
                )

    def test_the_limit_is_per_client(self) -> None:
        client, _clock = self.limited_client(max_runs=1)

        first = self.launch(
            client, self.brief("a"), headers={"X-Forwarded-For": "203.0.113.10"}
        )
        repeat = self.launch(
            client, self.brief("b"), headers={"X-Forwarded-For": "203.0.113.10"}
        )
        other = self.launch(
            client, self.brief("c"), headers={"X-Forwarded-For": "203.0.113.11"}
        )

        self.assertEqual(first.status_code, 202)
        self.assertEqual(repeat.status_code, 429)
        self.assertEqual(other.status_code, 202)

    def test_a_malformed_request_still_spends_a_token(self) -> None:
        """The limiter runs first, so a flood of junk bodies is throttled too."""
        client, _clock = self.limited_client(max_runs=1)

        self.assertEqual(self.launch(client, {"workflow_id": "nope"}).status_code, 404)
        self.assertEqual(self.launch(client, self.brief()).status_code, 429)

    def test_the_default_app_carries_a_live_limiter(self) -> None:
        """Nothing may ship with the limiter accidentally switched off."""
        from fastapi.testclient import TestClient

        from brief_crew.service.app import create_app

        client = TestClient(create_app(synthetic=True))
        self.addCleanup(client.close)

        self.assertTrue(client.app.state.run_rate_limiter.enabled)


class OpenApiDocsTests(ServiceHardeningTestCase):
    DOC_PATHS = ("/docs", "/redoc", "/openapi.json")

    def bare_registry_client(self, **kwargs: object):
        from fastapi.testclient import TestClient

        from brief_crew.service.app import create_app
        from brief_crew.service.graph import BRIEF_GRAPH, BRIEF_NODE_REGISTRY
        from brief_crew.service.registry import RunRegistry
        from brief_crew.service.runner import SyntheticRunner

        registry = RunRegistry(
            graph_version=BRIEF_GRAPH.version,
            node_registry=BRIEF_NODE_REGISTRY,
            runner=SyntheticRunner(),
            gate_sweep_interval=0,
        )
        self.addCleanup(registry.close)
        client = TestClient(create_app(registry=registry, **kwargs))  # type: ignore[arg-type]
        self.addCleanup(client.close)
        return client

    def test_docs_are_served_for_a_synthetic_app(self) -> None:
        client = self.synthetic_client()

        for path in self.DOC_PATHS:
            self.assertEqual(client.get(path).status_code, 200, msg=path)

    def test_docs_are_absent_from_a_paid_app_by_default(self) -> None:
        from brief_crew import config as project_config

        with patch.object(project_config, "EXPOSE_API_DOCS", False):
            client = self.bare_registry_client()

        self.assertFalse(client.app.state.expose_docs)
        for path in self.DOC_PATHS:
            self.assertEqual(client.get(path).status_code, 404, msg=path)

    def test_the_config_flag_turns_them_back_on(self) -> None:
        from brief_crew import config as project_config

        with patch.object(project_config, "EXPOSE_API_DOCS", True):
            client = self.bare_registry_client()

        self.assertTrue(client.app.state.expose_docs)
        for path in self.DOC_PATHS:
            self.assertEqual(client.get(path).status_code, 200, msg=path)

    def test_the_explicit_argument_wins_over_the_flag(self) -> None:
        client = self.synthetic_client(expose_docs=False)

        for path in self.DOC_PATHS:
            self.assertEqual(client.get(path).status_code, 404, msg=path)

    def test_hiding_the_docs_does_not_hide_the_api(self) -> None:
        """Obscurity, not a control - and the tests should say so out loud."""
        client = self.synthetic_client(expose_docs=False)

        self.assertEqual(client.get("/api/workflows").status_code, 200)
        self.assertEqual(self.launch(client, self.brief()).status_code, 202)


if __name__ == "__main__":
    unittest.main()
