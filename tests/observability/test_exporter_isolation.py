"""Definition of Done row E2: the app does not notice, and the exporter says so.

Three conditions - a backend at a port nothing is listening on, a backend that
answers too slowly, and no credentials at all - each measured against a control
run with a healthy (in-memory) exporter. The bar is two-sided and both halves
matter:

* **The run is unchanged.** Same terminal status, same result, same frame count
  as the control. An observability layer that changes what the application does
  is worse than no observability layer.
* **The failure is COUNTED.** A run whose backend was unreachable and that
  reports `http_errors=0` is telling an operator the export worked. That is the
  one number most easily made a lie, and it is why the summary is logged only
  after the run's final flush attempt has finished - a line written before the
  flush reports success the flush is about to disprove.

The first two conditions build the REAL backend, because a double cannot fail
the way a network does. They are the only tests in this package that open a
socket, and both point at localhost.
"""

from __future__ import annotations

import http.server
import importlib.util
import socket
import threading
import time
import unittest
from unittest.mock import patch

from brief_crew.observability import build_exporter
from brief_crew.observability.langfuse_exporter import LangfuseExporter, NullExporter
from brief_crew.observability.policy import ExporterPolicy


FASTAPI_AVAILABLE = importlib.util.find_spec("fastapi") is not None
LANGFUSE_AVAILABLE = importlib.util.find_spec("langfuse") is not None

IDEA = "a synthetic idea for the fail-open control"


def _dead_port() -> int:
    """A port nothing is listening on, chosen by binding and releasing one."""

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


class _SlowHandler(http.server.BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802 - the base class names it
        time.sleep(3.0)
        try:
            self.send_response(200)
            self.end_headers()
        except Exception:  # pragma: no cover - the client has usually gone
            pass

    def log_message(self, *args: object) -> None:
        return None


class _RunOutcome:
    """What a run looked like from the application's side, and nothing else."""

    def __init__(self, payload: dict) -> None:
        self.status = payload["status"]
        self.frames = payload["frames"]["count"]
        self.result = payload.get("result")

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, _RunOutcome)
            and self.status == other.status
            and self.frames == other.frames
            and self.result == other.result
        )

    def __repr__(self) -> str:  # pragma: no cover - only on a failure message
        return f"<run {self.status} frames={self.frames}>"


def _run_once(exporter) -> tuple[_RunOutcome, str]:
    """One synthetic validator run, unattended, through the real service."""

    from fastapi.testclient import TestClient

    from brief_crew.service.app import create_app

    with patch("brief_crew.observability.build_exporter", return_value=exporter):
        app = create_app(synthetic=True)
    with TestClient(app) as client:
        response = client.post(
            "/api/sessions/isolation/runs",
            json={
                "workflow_id": "idea-validator",
                "inputs": {"idea": IDEA},
                "gates": "auto",
            },
        )
        assert response.status_code == 202, response.text
        run_id = response.json()["run_id"]
        for _ in range(400):
            payload = client.get(f"/api/runs/{run_id}").json()
            if payload["status"] in ("completed", "failed", "cancelled"):
                break
            time.sleep(0.05)
    return _RunOutcome(payload), run_id


@unittest.skipUnless(FASTAPI_AVAILABLE, "FastAPI is not installed")
class ControlTests(unittest.TestCase):
    """The healthy run every other case is compared against."""

    def test_the_control_run_completes(self) -> None:
        from brief_crew.observability.backend import RecordingBackend

        exporter = LangfuseExporter(
            ExporterPolicy(
                public_key="pk",
                secret_key="sk",
                base_url="http://langfuse.invalid",
                enabled=True,
                environment="synthetic",
                flush_interval_seconds=0.05,
            ),
            sender=RecordingBackend(),
        )
        try:
            outcome, run_id = _run_once(exporter)
            exporter.flush()
        finally:
            exporter.close()
        self.assertEqual("completed", outcome.status)
        self.assertGreater(outcome.frames, 20)
        self.assertEqual(0, exporter.stats(run_id)["http_errors"])


def _control_outcome() -> _RunOutcome:
    from brief_crew.observability.backend import RecordingBackend

    exporter = LangfuseExporter(
        ExporterPolicy(
            public_key="pk",
            secret_key="sk",
            base_url="http://langfuse.invalid",
            enabled=True,
            environment="synthetic",
            flush_interval_seconds=0.05,
        ),
        sender=RecordingBackend(),
    )
    try:
        outcome, _ = _run_once(exporter)
    finally:
        exporter.close()
    return outcome


@unittest.skipUnless(FASTAPI_AVAILABLE, "FastAPI is not installed")
class MissingKeysTests(unittest.TestCase):
    def test_an_exporter_with_no_keys_is_a_no_op_that_says_so_once(self) -> None:
        policy = ExporterPolicy(
            public_key="", secret_key="", base_url="http://x", enabled=True
        )
        with self.assertLogs("brief_crew.observability", level="INFO") as captured:
            exporter = build_exporter(policy=policy)
        self.assertIsInstance(exporter, NullExporter)
        lines = [line for line in captured.output if "langfuse export is off" in line]
        self.assertEqual(1, len(lines))
        self.assertIn("LANGFUSE_PUBLIC_KEY", lines[0])

    def test_the_run_is_identical_with_no_exporter_at_all(self) -> None:
        control = _control_outcome()
        outcome, run_id = _run_once(NullExporter("no keys"))
        self.assertEqual(control, outcome)
        self.assertEqual({}, NullExporter("no keys").stats(run_id))

    def test_no_credential_is_ever_named_in_the_reason(self) -> None:
        policy = ExporterPolicy(
            public_key="pk-lf-real-looking",
            secret_key="",
            base_url="http://x",
            enabled=True,
        )
        reason = policy.reason_unusable()
        self.assertIn("LANGFUSE_SECRET_KEY", reason)
        self.assertNotIn("pk-lf-real-looking", reason)


@unittest.skipUnless(
    FASTAPI_AVAILABLE and LANGFUSE_AVAILABLE,
    "FastAPI and the langfuse SDK are both needed for the transport cases",
)
class UnreachableBackendTests(unittest.TestCase):
    """The two cases a recording double cannot express."""

    def _exporter_pointed_at(self, base_url: str) -> LangfuseExporter:
        return LangfuseExporter(
            ExporterPolicy(
                public_key="pk-lf-not-a-real-key",
                secret_key="sk-lf-not-a-real-key",
                base_url=base_url,
                enabled=True,
                environment="synthetic",
                flush_interval_seconds=0.05,
                # One second, so a host that never answers costs the test a few
                # seconds rather than a minute. It is the same figure the SDK
                # hands to both the HTTP client and the batch processor.
                http_timeout_seconds=1.0,
            )
        )

    def test_a_black_hole_host_leaves_the_run_alone_and_is_counted(self) -> None:
        control = _control_outcome()
        exporter = self._exporter_pointed_at(f"http://127.0.0.1:{_dead_port()}")
        try:
            outcome, run_id = _run_once(exporter)
            exporter.flush(timeout=15.0)
            stats = exporter.stats(run_id)
        finally:
            exporter.close()
        self.assertEqual(control, outcome)
        self.assertGreaterEqual(
            stats["http_errors"],
            1,
            "a backend that was never reachable must not report a clean export",
        )
        self.assertGreater(stats["frames_enqueued"], 20)

    def test_a_slow_host_leaves_the_run_alone_and_is_counted(self) -> None:
        control = _control_outcome()
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _SlowHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            exporter = self._exporter_pointed_at(
                f"http://127.0.0.1:{server.server_address[1]}"
            )
            try:
                outcome, run_id = _run_once(exporter)
                exporter.flush(timeout=15.0)
                stats = exporter.stats(run_id)
            finally:
                exporter.close()
        finally:
            server.shutdown()
            server.server_close()
        self.assertEqual(control, outcome)
        self.assertGreaterEqual(stats["http_errors"], 1)

    def test_the_summary_line_carries_the_failure_count(self) -> None:
        """The line is logged after the final flush, so it can report the truth.

        A summary written the instant the terminal frame landed reported
        `http_errors=0` for a backend nothing was listening on. This asserts the
        ordering by reading the line itself.
        """

        exporter = self._exporter_pointed_at(f"http://127.0.0.1:{_dead_port()}")
        try:
            with self.assertLogs(
                "brief_crew.observability.summary", level="WARNING"
            ) as captured:
                _run_once(exporter)
                exporter.flush(timeout=15.0)
        finally:
            exporter.close()
        lines = [line for line in captured.output if "langfuse-exporter run=" in line]
        self.assertEqual(1, len(lines), captured.output)
        summary = lines[0]
        for field in (
            "frames_enqueued=",
            "frames_dropped=",
            "observations_sent=",
            "http_errors=",
            "lookup_ok=",
            "lookup_failed=",
            "enqueue_p50_us=",
            "enqueue_p95_us=",
        ):
            self.assertIn(field, summary)
        self.assertNotIn("http_errors=0 ", summary)


class ExporterSurfaceTests(unittest.TestCase):
    def test_the_no_op_answers_every_call_the_service_makes(self) -> None:
        exporter = NullExporter("not configured")
        exporter.begin_run(object())
        exporter.on_frames("r1", ())
        self.assertEqual({}, exporter.stats("r1"))
        self.assertTrue(exporter.flush())
        exporter.close()
        exporter.close()

    def test_closing_twice_is_harmless(self) -> None:
        from brief_crew.observability.backend import RecordingBackend

        backend = RecordingBackend()
        exporter = LangfuseExporter(
            ExporterPolicy(
                public_key="pk", secret_key="sk", base_url="http://x", enabled=True
            ),
            sender=backend,
        )
        exporter.close()
        exporter.close()
        self.assertTrue(backend.closed)

    def test_a_backend_that_raises_on_every_call_never_reaches_the_caller(self) -> None:
        from brief_crew.observability.backend import RecordingBackend
        from tests.observability.replay import Recorder, drive, exporter_for

        exporter, backend = exporter_for(
            RecordingBackend(fail_with=RuntimeError("the backend is on fire"))
        )
        recorder = Recorder()
        recorder.run_started({})
        recorder.node_started("n1")
        recorder.model_call("n1", "call-1")
        recorder.node_ended("n1")
        recorder.run_completed({})
        drive(exporter, recorder.frames)
        stats = exporter.stats(recorder.run_id)
        self.assertGreater(stats["http_errors"], 0)
        self.assertGreater(stats["frames_enqueued"], 0)

    def test_the_hook_drops_the_oldest_when_the_queue_is_full(self) -> None:
        from brief_crew.observability.backend import RecordingBackend
        from tests.observability.replay import Recorder

        exporter = LangfuseExporter(
            ExporterPolicy(
                public_key="pk",
                secret_key="sk",
                base_url="http://x",
                enabled=True,
                queue_capacity=2,
            ),
            sender=RecordingBackend(),
            start_thread=False,
        )
        recorder = Recorder()
        for _ in range(5):
            recorder.run_started({})
        for frame in recorder.frames:
            exporter.on_frames(recorder.run_id, (frame,))
        self.assertEqual(2, exporter._queue.qsize())


@unittest.skipUnless(FASTAPI_AVAILABLE, "FastAPI is not installed")
class ExporterVisibilityTests(unittest.TestCase):
    """E2's other half: the service says what its exporter is doing, on demand.

    "The exporter failure is logged once" is only half an answer if nobody can
    read the log. Measured against a bare `serve.exe`: `build_exporter` logs its
    startup line at INFO, nothing in `src/brief_crew/` calls
    `logging.basicConfig`, so the record reaches a root logger with no handler
    and is served by `logging.lastResort` - which is fixed at WARNING and drops
    it. `/healthz` and `/readyz` said nothing about the exporter either. So the
    only way to find out whether anything was being exported was to launch a
    run and go and look in Langfuse, which on a PAID run spends the money
    before the answer arrives.
    """

    def _readyz(self, exporter) -> dict:
        from fastapi.testclient import TestClient

        from brief_crew.service.app import create_app

        with patch("brief_crew.observability.build_exporter", return_value=exporter):
            app = create_app(synthetic=True)
        with TestClient(app) as client:
            response = client.get("/readyz")
        self.assertEqual(200, response.status_code)
        return response.json()["observability"]

    def test_readyz_says_the_exporter_is_on_and_in_which_environment(self) -> None:
        from brief_crew.observability.backend import RecordingBackend

        exporter = LangfuseExporter(
            ExporterPolicy(
                public_key="pk",
                secret_key="sk",
                base_url="http://langfuse.invalid",
                enabled=True,
                environment="synthetic",
            ),
            sender=RecordingBackend(),
            start_thread=False,
        )
        try:
            state = self._readyz(exporter)
        finally:
            exporter.close()
        self.assertEqual("enabled", state["exporter"])
        self.assertIsNone(state["reason"])
        self.assertEqual("synthetic", state["environment"])
        self.assertFalse(state["capture_content"])
        # The EFFECTIVE answer: the billed-cost lookup is skipped outright on a
        # synthetic run whose generation ids are fabricated, so reporting the
        # knob would say "on" for a process that will never make the call.
        self.assertFalse(state["resolve_billed_cost"])

    def test_readyz_says_why_when_it_is_off(self) -> None:
        state = self._readyz(NullExporter("LANGFUSE_SECRET_KEY is empty"))
        self.assertEqual("disabled", state["exporter"])
        self.assertIn("LANGFUSE_SECRET_KEY", state["reason"])

    def test_readyz_carries_no_key_and_no_url(self) -> None:
        """The one field this answer must never grow.

        `/readyz` is unauthenticated. A base URL can carry credentials in its
        userinfo and neither key answers a question anybody has here - "which
        project" belongs to whoever set the variable.
        """

        from brief_crew.observability.backend import RecordingBackend

        exporter = LangfuseExporter(
            ExporterPolicy(
                public_key="pk-lf-a-key-shaped-value",
                secret_key="sk-lf-a-key-shaped-value",
                base_url="https://langfuse.invalid/project",
                enabled=True,
                environment="live",
            ),
            sender=RecordingBackend(),
            start_thread=False,
        )
        try:
            state = self._readyz(exporter)
        finally:
            exporter.close()
        rendered = repr(state)
        self.assertNotIn("pk-lf-", rendered)
        self.assertNotIn("sk-lf-", rendered)
        self.assertNotIn("langfuse.invalid", rendered)

    def test_an_exporter_that_is_off_with_keys_present_says_so_at_warning(self) -> None:
        """The misconfiguration a person needs to see, at a level they will.

        Keys in the environment and nothing being exported is a mistake
        somebody made; no keys at all is a choice somebody made. The first is
        the one that reaches `logging.lastResort` and is dropped at INFO.
        """

        policy = ExporterPolicy(
            public_key="pk-lf-a-key-shaped-value",
            secret_key="sk-lf-a-key-shaped-value",
            base_url="http://x",
            enabled=False,
        )
        with self.assertLogs("brief_crew.observability", level="INFO") as captured:
            self.assertIsInstance(build_exporter(policy=policy), NullExporter)
        self.assertEqual(1, len(captured.records))
        self.assertEqual("WARNING", captured.records[0].levelname)
        self.assertIn("LANGFUSE_EXPORT_ENABLED", captured.output[0])

    def test_no_keys_at_all_stays_at_info(self) -> None:
        policy = ExporterPolicy(
            public_key="", secret_key="", base_url="http://x", enabled=True
        )
        with self.assertLogs("brief_crew.observability", level="INFO") as captured:
            build_exporter(policy=policy)
        self.assertEqual(["INFO"], [r.levelname for r in captured.records])
