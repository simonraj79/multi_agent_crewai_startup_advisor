"""PRD F27/F37: operator gate replies on the same socket that streams the run.

Every test here is no-cost. The app is built with ``synthetic=True``, so the
validator is ``SyntheticValidatorRunner`` - two deterministic pause/resume
rounds, an in-memory SQLite store, and no OpenRouter, Firecrawl, GitHub,
Hacker News, Pinecone or Cohere traffic.
"""

from __future__ import annotations

import importlib.util
import logging
import threading
import unittest
from typing import Any, Callable
from unittest.mock import patch

from brief_crew.config import (
    WS_MAX_GATE_FIELD_CHARS,
    WS_MAX_GATE_FIELDS,
    WS_MAX_MESSAGE_BYTES,
)
from brief_crew.events import FrameKind, UIEventType
from brief_crew.service import registry as registry_module


FASTAPI_AVAILABLE = importlib.util.find_spec("fastapi") is not None

# A socket that is also carrying the live frame stream interleaves control
# replies with frames, so nothing may assume a reply is the very next message.
MESSAGE_SCAN_LIMIT = 200


def read_until(
    websocket: Any,
    predicate: Callable[[dict[str, Any]], bool],
    *,
    limit: int = MESSAGE_SCAN_LIMIT,
) -> dict[str, Any]:
    """Return the first message matching ``predicate``, scanning past frames."""
    for _ in range(limit):
        message = websocket.receive_json()
        if predicate(message):
            return message
    raise AssertionError("no matching message arrived on the socket")


def message_of_type(expected: str) -> Callable[[dict[str, Any]], bool]:
    return lambda message: message.get("type") == expected


@unittest.skipUnless(FASTAPI_AVAILABLE, "FastAPI service extra is not installed")
class WebSocketGateReplyTests(unittest.TestCase):
    """F27/F37 acceptance: the WS path is the HTTP path, over a socket."""

    def setUp(self) -> None:
        from fastapi.testclient import TestClient

        from brief_crew.service.app import create_app

        self.client = TestClient(create_app(synthetic=True))
        self.addCleanup(self.client.close)
        self.registry = self.client.app.state.run_registry

    # -- helpers ---------------------------------------------------------

    def start_run(self, session_id: str = "ws-session") -> str:
        response = self.client.post(
            f"/api/sessions/{session_id}/runs",
            json={
                "workflow_id": "idea-validator",
                "inputs": {"idea": "A synthetic idea answered over the socket"},
            },
        )
        self.assertEqual(response.status_code, 202)
        run_id = response.json()["run_id"]
        self.registry.wait(run_id, timeout=5)
        return run_id

    def pending_gate(self, run_id: str) -> dict[str, Any]:
        payload = self.client.get(f"/api/runs/{run_id}").json()
        self.assertEqual(payload["status"], "waiting")
        self.assertIsNotNone(payload["pending_gate"])
        return payload["pending_gate"]

    def frames(self, run_id: str) -> list[dict[str, Any]]:
        page = self.client.get(f"/api/runs/{run_id}/frames?after=0&limit=500").json()
        return [envelope["data"] for envelope in page["frames"]]

    def connect(self, run_id: str, *, session_id: str = "ws-session", after: int = 0):
        return self.client.websocket_connect(
            f"/ws?session_id={session_id}&run_id={run_id}&after={after}"
        )

    def latest_seq(self, run_id: str) -> int:
        return self.client.get(f"/api/runs/{run_id}").json()["frames"]["last_seq"] or 0

    # -- acceptance criterion 1 ------------------------------------------

    def test_gate_reply_over_the_socket_resumes_the_run(self) -> None:
        run_id = self.start_run()
        gate = self.pending_gate(run_id)
        self.assertEqual(gate["node_id"], "confirm_scope")

        with self.connect(run_id, after=self.latest_seq(run_id)) as websocket:
            websocket.send_json(
                {
                    "type": "gate_reply",
                    "request_id": "req-1",
                    "data": {
                        "gate_id": gate["gate_id"],
                        "outcome": "approve",
                        "fields": {"category": "Design tooling"},
                    },
                }
            )
            ack = read_until(websocket, message_of_type("gate_ack"))

        self.assertEqual(ack["data"]["run_id"], run_id)
        self.assertEqual(ack["data"]["gate_id"], gate["gate_id"])
        self.assertEqual(ack["data"]["request_id"], "req-1")
        self.assertIn(ack["data"]["status"], {"running", "waiting"})

        self.registry.wait(run_id, timeout=5)

        # Same effect as the HTTP route: the gate closed with the operator's
        # edit recorded, and the flow advanced to the second gate.
        closed = [
            frame
            for frame in self.frames(run_id)
            if frame["kind"] == FrameKind.GATE_CLOSED.value
        ]
        self.assertEqual(len(closed), 1)
        self.assertEqual(closed[0]["details"]["gate_id"], gate["gate_id"])
        self.assertEqual(closed[0]["details"]["outcome"], "approve")
        self.assertEqual(
            closed[0]["details"]["fields"], {"category": "Design tooling"}
        )
        self.assertFalse(closed[0]["details"]["late"])

        second_gate = self.pending_gate(run_id)
        self.assertEqual(second_gate["node_id"], "review_verdict")
        self.assertNotEqual(second_gate["gate_id"], gate["gate_id"])

        # Acceptance criterion 5: the HTTP endpoint is untouched, and the two
        # transports interoperate inside one run.
        http_reply = self.client.post(
            f"/api/runs/{run_id}/gates/{second_gate['gate_id']}",
            json={"outcome": "approve", "fields": {}},
        )
        self.assertEqual(http_reply.status_code, 202)
        self.registry.wait(run_id, timeout=5)
        self.assertEqual(
            self.client.get(f"/api/runs/{run_id}").json()["status"],
            "completed",
        )

    def test_websocket_and_http_replies_produce_the_same_frames(self) -> None:
        """Both transports go through one code path, so the record matches."""
        socket_run = self.start_run(session_id="ws-parity")
        socket_gate = self.pending_gate(socket_run)
        with self.connect(
            socket_run, session_id="ws-parity", after=self.latest_seq(socket_run)
        ) as websocket:
            websocket.send_json(
                {
                    "type": "gate_reply",
                    "data": {
                        "gate_id": socket_gate["gate_id"],
                        "outcome": "approve",
                        "fields": {"category": "Parity"},
                    },
                }
            )
            read_until(websocket, message_of_type("gate_ack"))
        self.registry.wait(socket_run, timeout=5)

        http_run = self.start_run(session_id="http-parity")
        http_gate = self.pending_gate(http_run)
        self.client.post(
            f"/api/runs/{http_run}/gates/{http_gate['gate_id']}",
            json={"outcome": "approve", "fields": {"category": "Parity"}},
        )
        self.registry.wait(http_run, timeout=5)

        def shape(run_id: str) -> list[tuple[str, str]]:
            return [
                (frame["kind"], frame["node_id"]) for frame in self.frames(run_id)
            ]

        self.assertEqual(shape(socket_run), shape(http_run))

        def closed_details(run_id: str) -> dict[str, Any]:
            frame = next(
                frame
                for frame in self.frames(run_id)
                if frame["kind"] == FrameKind.GATE_CLOSED.value
            )
            return {key: frame["details"][key] for key in ("outcome", "fields", "late")}

        self.assertEqual(closed_details(socket_run), closed_details(http_run))

    # -- per-field editability -------------------------------------------

    def _verdict_gate(self, session_id: str) -> tuple[str, dict[str, Any]]:
        run_id = self.start_run(session_id=session_id)
        scope_gate = self.pending_gate(run_id)
        self.client.post(
            f"/api/runs/{run_id}/gates/{scope_gate['gate_id']}",
            json={"outcome": "approve", "fields": {}},
        )
        self.registry.wait(run_id, timeout=5)
        gate = self.pending_gate(run_id)
        self.assertEqual(gate["node_id"], "review_verdict")
        return run_id, gate

    def test_the_verdict_gate_offers_no_derived_field_on_this_transport(self) -> None:
        """The socket serves the same split the HTTP snapshot does.

        A field the operator's edit cannot reach - `Verdict` recomputes the
        composite score, confidence, floors and label from the five dimension
        scores and discards whatever it was sent - is carried as read-only
        detail on both transports, never as something to type into.
        """
        run_id, gate = self._verdict_gate("ws-derived")

        with self.connect(run_id, session_id="ws-derived", after=0) as websocket:
            opened = read_until(
                websocket,
                lambda message: (
                    message.get("type") == "frame"
                    and message["data"]["kind"] == FrameKind.GATE_OPEN.value
                    and message["data"]["details"]["node_id"] == "review_verdict"
                ),
            )

        streamed = opened["data"]["details"]
        self.assertEqual(list(streamed["fields"]), ["feedback"])
        self.assertEqual(
            [item["key"] for item in streamed["derived"]],
            [item["key"] for item in gate["derived"]],
        )
        self.assertIn("verdict", {item["key"] for item in streamed["derived"]})

    def test_a_derived_edit_over_the_socket_is_refused_like_the_http_route(
        self,
    ) -> None:
        """Acceptance 4 on the socket: refused, named, and still answerable."""
        run_id, gate = self._verdict_gate("ws-refusal")

        with self.connect(
            run_id, session_id="ws-refusal", after=self.latest_seq(run_id)
        ) as websocket:
            websocket.send_json(
                {
                    "type": "gate_reply",
                    "request_id": "derived-edit",
                    "data": {
                        "gate_id": gate["gate_id"],
                        "outcome": "approve",
                        "fields": {"verdict": "VALIDATE", "composite_score": "9.9"},
                    },
                }
            )
            error = read_until(websocket, message_of_type("error"))
            self.assertEqual(error["data"]["code"], "gate_field_not_editable")
            self.assertEqual(error["data"]["status"], 422)
            self.assertEqual(error["data"]["request_id"], "derived-edit")
            self.assertEqual(error["data"]["gate_id"], gate["gate_id"])
            self.assertIn("composite_score, verdict", error["data"]["message"])

            # The gate is untouched: the refusal is about the field, and a
            # refused reply must never cost the operator their gate.
            self.assertEqual(self.pending_gate(run_id)["gate_id"], gate["gate_id"])
            websocket.send_json(
                {
                    "type": "gate_reply",
                    "request_id": "note-only",
                    "data": {
                        "gate_id": gate["gate_id"],
                        "outcome": "approve",
                        "fields": {"feedback": "Reads right."},
                    },
                }
            )
            read_until(websocket, message_of_type("gate_ack"))

        self.registry.wait(run_id, timeout=5)
        self.assertEqual(
            self.client.get(f"/api/runs/{run_id}").json()["status"],
            "completed",
        )

    def test_both_transports_refuse_a_derived_edit_identically(self) -> None:
        socket_run, socket_gate = self._verdict_gate("ws-refusal-parity")
        http_run, http_gate = self._verdict_gate("http-refusal-parity")

        with self.connect(
            socket_run,
            session_id="ws-refusal-parity",
            after=self.latest_seq(socket_run),
        ) as websocket:
            websocket.send_json(
                {
                    "type": "gate_reply",
                    "data": {
                        "gate_id": socket_gate["gate_id"],
                        "outcome": "approve",
                        "fields": {"confidence": "0.99"},
                    },
                }
            )
            socket_error = read_until(websocket, message_of_type("error"))

        http_error = self.client.post(
            f"/api/runs/{http_run}/gates/{http_gate['gate_id']}",
            json={"outcome": "approve", "fields": {"confidence": "0.99"}},
        )

        self.assertEqual(socket_error["data"]["status"], http_error.status_code)
        self.assertEqual(socket_error["data"]["message"], http_error.json()["detail"])

    # -- acceptance criterion 2 ------------------------------------------

    def test_duplicate_reply_is_refused_and_the_socket_stays_usable(self) -> None:
        run_id = self.start_run()
        gate = self.pending_gate(run_id)

        with self.connect(run_id, after=self.latest_seq(run_id)) as websocket:
            reply = {
                "type": "gate_reply",
                "request_id": "first",
                "data": {"gate_id": gate["gate_id"], "outcome": "approve"},
            }
            websocket.send_json(reply)
            read_until(websocket, message_of_type("gate_ack"))
            self.registry.wait(run_id, timeout=5)

            websocket.send_json({**reply, "request_id": "duplicate"})
            error = read_until(websocket, message_of_type("error"))
            # The same refusal the HTTP route answers with 409.
            self.assertEqual(error["data"]["code"], "gate_conflict")
            self.assertEqual(error["data"]["status"], 409)
            self.assertEqual(error["data"]["request_id"], "duplicate")
            self.assertEqual(error["data"]["gate_id"], gate["gate_id"])

            # Still open, still streaming, still answering.
            websocket.send_json({"type": "ping"})
            pong = read_until(websocket, message_of_type("pong"))
            self.assertIsInstance(pong["data"]["after"], int)

            second_gate = self.pending_gate(run_id)
            websocket.send_json(
                {
                    "type": "gate_reply",
                    "request_id": "second",
                    "data": {"gate_id": second_gate["gate_id"], "outcome": "approve"},
                }
            )
            second_ack = read_until(websocket, message_of_type("gate_ack"))
            self.assertEqual(second_ack["data"]["request_id"], "second")

        self.registry.wait(run_id, timeout=5)
        self.assertEqual(
            self.client.get(f"/api/runs/{run_id}").json()["status"],
            "completed",
        )

    # -- acceptance criterion 3 ------------------------------------------

    def test_malformed_messages_are_refused_without_killing_socket_or_run(
        self,
    ) -> None:
        run_id = self.start_run()
        gate = self.pending_gate(run_id)
        oversized_value = "x" * (WS_MAX_GATE_FIELD_CHARS + 1)

        hostile: list[tuple[Any, str]] = [
            ({"type": "gate_reply"}, "invalid_gate_reply"),
            ({"type": "gate_reply", "data": {}}, "invalid_gate_reply"),
            (
                {"type": "gate_reply", "data": {"gate_id": gate["gate_id"]}},
                "invalid_gate_reply",
            ),
            (
                {
                    "type": "gate_reply",
                    "data": {"gate_id": 17, "outcome": "approve"},
                },
                "invalid_gate_reply",
            ),
            (
                {
                    "type": "gate_reply",
                    "data": {
                        "gate_id": gate["gate_id"],
                        "outcome": "approve",
                        "fields": {"category": ["not", "a", "string"]},
                    },
                },
                "invalid_gate_reply",
            ),
            (
                {
                    "type": "gate_reply",
                    "data": {
                        "gate_id": gate["gate_id"],
                        "outcome": "approve",
                        "smuggled": True,
                    },
                },
                "invalid_gate_reply",
            ),
            (
                {
                    "type": "gate_reply",
                    "data": {"gate_id": gate["gate_id"], "outcome": "obliterate"},
                },
                "invalid_outcome",
            ),
            (
                {
                    "type": "gate_reply",
                    "data": {
                        "run_id": "some-other-run",
                        "gate_id": gate["gate_id"],
                        "outcome": "approve",
                    },
                },
                "run_mismatch",
            ),
            (
                {
                    "type": "gate_reply",
                    "data": {
                        "gate_id": "00000000-0000-0000-0000-000000000000",
                        "outcome": "approve",
                    },
                },
                "gate_not_found",
            ),
            (
                {
                    "type": "gate_reply",
                    "data": {
                        "gate_id": gate["gate_id"],
                        "outcome": "approve",
                        "fields": {
                            str(index): "value"
                            for index in range(WS_MAX_GATE_FIELDS + 1)
                        },
                    },
                },
                "gate_fields_too_many",
            ),
            (
                {
                    "type": "gate_reply",
                    "data": {
                        "gate_id": gate["gate_id"],
                        "outcome": "approve",
                        "fields": {"category": oversized_value},
                    },
                },
                "gate_field_too_long",
            ),
            ({"type": "cancel_everything"}, "unknown_message_type"),
            ({"type": None}, "unknown_message_type"),
            ({"no_type_at_all": True}, "unknown_message_type"),
            (["not", "an", "object"], "invalid_message"),
            (42, "invalid_message"),
            (None, "invalid_message"),
        ]

        with self.connect(run_id, after=self.latest_seq(run_id)) as websocket:
            for payload, expected_code in hostile:
                websocket.send_json(payload)
                error = read_until(websocket, message_of_type("error"))
                self.assertEqual(
                    error["data"]["code"],
                    expected_code,
                    msg=f"payload {payload!r}",
                )
                self.assertIsInstance(error["data"]["message"], str)
                self.assertIsInstance(error["data"]["status"], int)

            # Not JSON at all.
            websocket.send_text("}{ this is not json")
            self.assertEqual(
                read_until(websocket, message_of_type("error"))["data"]["code"],
                "invalid_json",
            )

            # Bigger than the configured cap, so it is never handed to a parser.
            websocket.send_text(" " * (WS_MAX_MESSAGE_BYTES + 1))
            oversized = read_until(websocket, message_of_type("error"))
            self.assertEqual(oversized["data"]["code"], "payload_too_large")
            self.assertEqual(oversized["data"]["status"], 413)

            websocket.send_bytes(b"\xff\xfe\x00 not utf-8")
            self.assertEqual(
                read_until(websocket, message_of_type("error"))["data"]["code"],
                "invalid_encoding",
            )

            websocket.send_bytes(b"\x00" * (WS_MAX_MESSAGE_BYTES + 1))
            self.assertEqual(
                read_until(websocket, message_of_type("error"))["data"]["code"],
                "payload_too_large",
            )

            # The run never moved, and the socket still answers.
            self.assertEqual(
                self.client.get(f"/api/runs/{run_id}").json()["status"],
                "waiting",
            )
            self.assertEqual(
                self.pending_gate(run_id)["gate_id"],
                gate["gate_id"],
            )
            websocket.send_json({"type": "ping"})
            read_until(websocket, message_of_type("pong"))

            # And a valid reply on the very same socket still works.
            websocket.send_json(
                {
                    "type": "gate_reply",
                    "data": {"gate_id": gate["gate_id"], "outcome": "approve"},
                }
            )
            read_until(websocket, message_of_type("gate_ack"))

        self.registry.wait(run_id, timeout=5)
        self.assertEqual(
            self.pending_gate(run_id)["node_id"],
            "review_verdict",
        )

    # -- acceptance criterion 4 ------------------------------------------

    def test_ping_replay_and_after_cursor_survive_a_gate_reply(self) -> None:
        run_id = self.start_run()
        gate = self.pending_gate(run_id)
        before_reply = self.latest_seq(run_id)

        with self.connect(run_id, after=0) as websocket:
            # Ordered replay from the very beginning, gapless.
            replayed = [
                websocket.receive_json()["data"]["seq"]
                for _ in range(before_reply)
            ]
            self.assertEqual(replayed, list(range(1, before_reply + 1)))

            websocket.send_json({"type": "ping"})
            first_pong = read_until(websocket, message_of_type("pong"))
            self.assertEqual(first_pong["data"]["after"], before_reply)

            websocket.send_json(
                {
                    "type": "gate_reply",
                    "data": {"gate_id": gate["gate_id"], "outcome": "approve"},
                }
            )
            read_until(websocket, message_of_type("gate_ack"))
            self.registry.wait(run_id, timeout=5)

            # Ping/pong still works after the reply, and the cursor advanced.
            websocket.send_json({"type": "ping"})
            second_pong = read_until(websocket, message_of_type("pong"))
            self.assertGreater(second_pong["data"]["after"], before_reply)

        # The reconnect cursor still resumes exactly where it left off.
        expected = [
            frame["seq"]
            for frame in self.frames(run_id)
            if frame["seq"] > before_reply
        ]
        self.assertTrue(expected)
        with self.connect(run_id, after=before_reply) as websocket:
            resumed = [
                websocket.receive_json()["data"]["seq"] for _ in expected
            ]
            self.assertEqual(resumed, expected)
            websocket.send_json("ping")
            read_until(websocket, message_of_type("pong"))

        # And a duplicate cursor replays nothing it already sent.
        newest = self.latest_seq(run_id)
        with self.connect(run_id, after=newest) as websocket:
            websocket.send_json({"type": "ping"})
            pong = read_until(websocket, message_of_type("pong"))
            self.assertEqual(pong["data"]["after"], newest)

    # -- the event loop is not stalled by a blocking reply ---------------

    def test_the_stream_keeps_flowing_while_a_reply_is_being_applied(self) -> None:
        """``answer_gate`` blocks; the socket must not.

        The reply is held open in the registry, and a frame emitted while it is
        held still reaches the client. If the WebSocket handler ran
        ``answer_gate`` on the event loop, nothing could be delivered until it
        returned.
        """
        run_id = self.start_run()
        gate = self.pending_gate(run_id)
        release = threading.Event()
        self.addCleanup(release.set)
        original = self.registry.answer_gate

        def blocking_answer(*args: Any, **kwargs: Any) -> Any:
            record = self.registry.require(run_id)
            record.capture.emit(
                kind=FrameKind.NODE_STATE,
                event_type=UIEventType.NODE_START,
                node_id="confirm_scope",
                message="gate reply in flight",
            )
            self.assertTrue(release.wait(timeout=10))
            return original(*args, **kwargs)

        with patch.object(self.registry, "answer_gate", blocking_answer):
            with self.connect(run_id, after=self.latest_seq(run_id)) as websocket:
                websocket.send_json(
                    {
                        "type": "gate_reply",
                        "data": {"gate_id": gate["gate_id"], "outcome": "approve"},
                    }
                )
                in_flight = read_until(
                    websocket,
                    lambda message: message.get("type") == "frame"
                    and message["data"]["message"] == "gate reply in flight",
                )
                self.assertEqual(in_flight["data"]["kind"], FrameKind.NODE_STATE.value)
                # Delivered while the worker thread is still parked.
                self.assertFalse(release.is_set())

                release.set()
                read_until(websocket, message_of_type("gate_ack"))

        self.registry.wait(run_id, timeout=5)
        self.assertEqual(self.pending_gate(run_id)["node_id"], "review_verdict")


@unittest.skipUnless(FASTAPI_AVAILABLE, "FastAPI service extra is not installed")
class WebSocketLateGateReplyTests(unittest.TestCase):
    """PRD F03 over the socket: expiry is advisory, a late reply still lands."""

    def setUp(self) -> None:
        logger = logging.getLogger("brief_crew.service.registry")
        previous = logger.level
        logger.setLevel(logging.CRITICAL)
        self.addCleanup(logger.setLevel, previous)

    # -- acceptance criterion 6 ------------------------------------------

    def test_late_reply_over_the_socket_is_accepted_and_resumes_the_run(self) -> None:
        from fastapi.testclient import TestClient

        from brief_crew.service.app import create_app

        with TestClient(create_app(synthetic=True)) as client:
            registry = client.app.state.run_registry

            # A gate that is already past its deadline the moment it opens.
            with patch.object(registry_module, "VALIDATOR_GATE_TIMEOUT_SECONDS", 0):
                run_id = client.post(
                    "/api/sessions/late-session/runs",
                    json={
                        "workflow_id": "idea-validator",
                        "inputs": {"idea": "Nobody answers this one in time"},
                    },
                ).json()["run_id"]
                registry.wait(run_id, timeout=5)

            waiting = client.get(f"/api/runs/{run_id}").json()
            gate = waiting["pending_gate"]
            self.assertEqual(waiting["status"], "waiting")
            self.assertTrue(gate["expired"])

            # Let the sweeper publish the advisory frames the UI renders.
            registry.sweep_gates()
            kinds = [
                frame["data"]["kind"]
                for frame in client.get(
                    f"/api/runs/{run_id}/frames?after=0&limit=500"
                ).json()["frames"]
            ]
            self.assertEqual(kinds.count(FrameKind.GATE_EXPIRED.value), 1)
            self.assertEqual(kinds.count(FrameKind.GATE_CLOSED.value), 0)

            last_seq = client.get(f"/api/runs/{run_id}").json()["frames"]["last_seq"]
            with client.websocket_connect(
                f"/ws?session_id=late-session&run_id={run_id}&after={last_seq}"
            ) as websocket:
                websocket.send_json(
                    {
                        "type": "gate_reply",
                        "request_id": "late",
                        "data": {
                            "gate_id": gate["gate_id"],
                            "outcome": "approve",
                            "fields": {"category": "Answered late"},
                        },
                    }
                )
                ack = read_until(websocket, message_of_type("gate_ack"))
                self.assertEqual(ack["data"]["request_id"], "late")
                self.assertEqual(ack["data"]["gate_id"], gate["gate_id"])

            registry.wait(run_id, timeout=5)

            closed = next(
                envelope["data"]
                for envelope in client.get(
                    f"/api/runs/{run_id}/frames?after=0&limit=500"
                ).json()["frames"]
                if envelope["data"]["kind"] == FrameKind.GATE_CLOSED.value
            )
            # Recorded as late - and accepted anyway.
            self.assertTrue(closed["details"]["late"])
            self.assertEqual(closed["details"]["outcome"], "approve")

            resumed = client.get(f"/api/runs/{run_id}").json()
            self.assertEqual(resumed["status"], "waiting")
            self.assertEqual(resumed["pending_gate"]["node_id"], "review_verdict")


if __name__ == "__main__":
    unittest.main()
