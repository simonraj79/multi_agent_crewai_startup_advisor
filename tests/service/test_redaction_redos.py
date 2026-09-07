"""Audit C1 - one 64 KiB gate reply must not freeze the process.

Two halves of one defect, and each is only half a fix.

The *regex* half: ``_URL_CREDENTIALS`` matched ``[a-z][a-z0-9+.-]*://`` - an
unbounded run of a class whose first character it also admits - so on a subject
that never contains ``://`` the engine rescans from every start position and the
match is quadratic. Measured on the reporter's machine: 0.83 s at 16k
characters, 3.35 s at 32k, 13.95 s at 65,490. ``_redact_text`` is applied to
every persisted string, and the HTTP gate route is ``async def`` calling it
inline, so that time is spent on the event loop with the interpreter lock held -
no other request, health check or run stream is served meanwhile.

The *bound* half: the WebSocket transport caps a gate field at
``WS_MAX_GATE_FIELD_CHARS`` (app.py, handle_gate_reply) and the HTTP one capped
only the whole 64 KiB body, so one field could carry 65,490 characters. Two
transports reaching one durable path must not disagree about what a reply may
hold.

Everything here is no-cost: the timing test is pure ``re``, and the HTTP test
runs the synthetic registry - in-memory SQLite, deterministic runner, no model
and no network.
"""

from __future__ import annotations

import importlib.util
import time
import unittest

from brief_crew.config import WS_MAX_GATE_FIELD_CHARS
from brief_crew.service.persistence import _redact_text


FASTAPI_AVAILABLE = importlib.util.find_spec("fastapi") is not None

# The reporter's subject, to the character: a 64 KiB JSON body leaves this much
# room for one field value once the envelope is paid for.
REDOS_SUBJECT_CHARS = 65_490

# Generous against the fixed regex (microseconds) and unreachable by the old one
# (~14 s). Chosen so a loaded CI runner cannot make this flap: the gap between
# pass and fail is four orders of magnitude, not a factor of two.
REDOS_BUDGET_SECONDS = 0.5


class AuditC1RedactionReDoSTests(unittest.TestCase):
    def test_c1_a_64_kib_string_with_no_url_is_redacted_in_well_under_a_second(
        self,
    ) -> None:
        subject = "a" * REDOS_SUBJECT_CHARS

        started = time.perf_counter()
        redacted = _redact_text(subject)
        elapsed = time.perf_counter() - started

        # Nothing to redact, so the answer must be the subject verbatim - a
        # "fix" that truncated or refused would pass a timing bound and lose
        # data.
        self.assertEqual(redacted, subject)
        self.assertLess(
            elapsed,
            REDOS_BUDGET_SECONDS,
            f"_redact_text took {elapsed:.3f}s on {REDOS_SUBJECT_CHARS} "
            "characters; the pattern is quadratic again",
        )

    def test_c1_the_bounded_pattern_still_redacts_every_url_shape_it_must(
        self,
    ) -> None:
        # (subject, expected) - the shapes the audit checked the replacement
        # against, so a future tightening of the quantifiers cannot quietly
        # stop catching one.
        cases = (
            (
                "postgres://u:p@h/db",
                "postgres://[REDACTED]@h/db",
            ),
            (
                "postgresql+psycopg://a:b@h",
                "postgresql+psycopg://[REDACTED]@h",
            ),
            (
                "HTTPS://U:P@H/",
                "HTTPS://[REDACTED]@H/",
            ),
            # A password may contain ':' - only the user half may not.
            (
                "postgres://user:pa:ss:word@host:5432/db",
                "postgres://[REDACTED]@host:5432/db",
            ),
            # Embedded in prose, which is how it actually reaches the row.
            (
                "connect to postgresql://alice:s3cret@db.internal/app and retry",
                "connect to postgresql://[REDACTED]@db.internal/app and retry",
            ),
        )
        for subject, expected in cases:
            with self.subTest(subject=subject):
                self.assertEqual(_redact_text(subject), expected)

    def test_c1_a_credential_free_url_is_left_alone(self) -> None:
        self.assertEqual(_redact_text("https://x/y"), "https://x/y")


@unittest.skipUnless(FASTAPI_AVAILABLE, "FastAPI service extra is not installed")
class AuditC1GateFieldBoundTests(unittest.TestCase):
    """The HTTP gate reply must bound one field the way the socket does."""

    def setUp(self) -> None:
        from fastapi.testclient import TestClient

        from brief_crew.service.app import create_app

        self.client = TestClient(create_app(synthetic=True))
        self.addCleanup(self.client.close)
        self.registry = self.client.app.state.run_registry

    def _scope_gate(self) -> tuple[str, str]:
        run_id = self.client.post(
            "/api/sessions/audit-c1/runs",
            json={
                "workflow_id": "idea-validator",
                "inputs": {"idea": "A synthetic idea for the gate bound"},
            },
        ).json()["run_id"]
        self.registry.wait(run_id, timeout=5)
        gate = self.client.get(f"/api/runs/{run_id}").json()["pending_gate"]
        self.assertEqual(gate["node_id"], "confirm_scope")
        return run_id, gate["gate_id"]

    def test_c1_an_oversized_http_gate_field_is_refused_with_422(self) -> None:
        run_id, gate_id = self._scope_gate()

        refused = self.client.post(
            f"/api/runs/{run_id}/gates/{gate_id}",
            json={
                "outcome": "approve",
                "fields": {"feedback": "a" * (WS_MAX_GATE_FIELD_CHARS + 1)},
            },
        )

        self.assertEqual(refused.status_code, 422)
        # The gate is untouched: the refusal is about the field, not the reply.
        self.assertEqual(
            self.client.get(f"/api/runs/{run_id}").json()["status"],
            "waiting",
        )

    def test_c1_a_field_exactly_at_the_bound_is_still_accepted(self) -> None:
        run_id, gate_id = self._scope_gate()

        accepted = self.client.post(
            f"/api/runs/{run_id}/gates/{gate_id}",
            json={
                "outcome": "approve",
                "fields": {"feedback": "a" * WS_MAX_GATE_FIELD_CHARS},
            },
        )

        self.assertEqual(accepted.status_code, 202)


if __name__ == "__main__":
    unittest.main()
