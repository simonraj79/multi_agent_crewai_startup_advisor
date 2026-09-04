"""A server the run cannot reach says so - plan 07 criterion 8, first half.

Plan 07 recorded this criterion as *"not reached, and it is honestly two
things"*: the frame mapping for MCP events, and the error edge. The edge is
proved in `tests/builder/test_failure_modes.py::McpUnreachableTests`, which is
the file criterion 8 names; this is the mapping.

**What was there before was a counter.** The sink receives *every* CrewAI event
and the ladder handles about thirty of roughly a hundred and fifty; the rest
reach `record_unhandled`, which tallies the type name and emits nothing. So an
MCP server going down was COUNTED and invisible. Every test here asserts the
frame AND that the tally stopped moving, because those are two claims and only
the pair rules out a branch that drafts a frame and falls through anyway.

No model, no network: these are event objects.
"""

from __future__ import annotations

import unittest

from crewai.events.types.mcp_events import MCPConnectionFailedEvent

from brief_crew.builder.mcp import MCP_CONNECTION_ERROR_CLASS
from tests.events.frame_case import NODE, TS, FrameCase


class McpConnectionFrameTests(FrameCase):
    """07 criterion 8: a connection failure becomes a `node_error` frame."""

    def _event(self, **overrides: object) -> MCPConnectionFailedEvent:
        fields: dict = {
            "server_name": "docs.example.test",
            "server_url": "https://docs.example.test/mcp",
            "transport_type": "streamable-http",
            "error": "connection refused",
            "error_type": "MCPConnectionError",
            "timestamp": TS,
        }
        fields.update(overrides)
        return MCPConnectionFailedEvent(**fields)  # type: ignore[arg-type]

    def test_it_produces_one_error_frame_on_the_failing_node(self) -> None:
        frames = self.emit(self._event())
        self.assertEqual(len(frames), 1)
        frame = frames[0]
        self.assertEqual(frame.kind.value, "error")
        self.assertEqual(frame.level.value, "ERROR")
        self.assertEqual(frame.node_id, NODE)
        self.assertHandled("mcp_connection_failed")

    def test_the_frame_is_C6s_node_error_shape(self) -> None:
        details = dict(self.emit(self._event())[0].details)
        self.assertEqual(details["stage"], "error")
        self.assertEqual(details["error_class"], MCP_CONNECTION_ERROR_CLASS)
        self.assertEqual(details["message"], "connection refused")

    def test_it_names_WHICH_server_which_is_the_point(self) -> None:
        """An author with three servers attached cannot use "a node failed".

        The step-level `node_error` frame the runtime writes when the failure
        propagates carries the exception and the retry state; it cannot carry
        the server, because by then the failure is just an exception. This one
        can, so both exist rather than one replacing the other.
        """

        details = dict(self.emit(self._event())[0].details)
        self.assertEqual(details["server"], "docs.example.test")
        self.assertEqual(details["transport"], "streamable-http")
        self.assertEqual(details["error_type"], "MCPConnectionError")

    def test_an_http_status_survives_when_the_server_sent_one(self) -> None:
        """401 and 403 are the two an author can actually act on."""

        details = dict(self.emit(self._event(status_code=401))[0].details)
        self.assertEqual(details["status_code"], 401)

    def test_a_url_in_the_message_is_not_the_frames_business(self) -> None:
        """`server_url` is deliberately NOT copied onto the frame.

        A hosted MCP server can carry a token in its path - `mask_url` exists
        for exactly that - so putting the raw URL on a frame would publish a
        credential to every viewer of the run console. The server's NAME is
        what identifies it here.
        """

        details = dict(self.emit(self._event())[0].details)
        self.assertNotIn("server_url", details)
        self.assertNotIn("docs.example.test/mcp", str(details))


class McpRegressionTests(FrameCase):
    """Counted and discarded until 2026-09-04."""

    def test_the_fallback_no_longer_swallows_a_connection_failure(self) -> None:
        self.adapter(
            None,
            MCPConnectionFailedEvent(server_name="s", error="e", timestamp=TS),
        )
        self.assertEqual(self.adapter.serializer.unhandled, {})
        self.assertIn("error", [frame.kind.value for frame in self.buffer.replay()])
        self.assertEqual(self.buffer.stats().emit_errors, 0)


if __name__ == "__main__":
    unittest.main()
