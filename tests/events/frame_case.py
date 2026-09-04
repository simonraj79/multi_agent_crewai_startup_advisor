"""One adapter, one node in scope, and the frames a single event produced.

Shared by `test_skill_frames.py` and `test_mcp_frames.py`, which assert two
event families the ladder used to discard. It is a module rather than a copy in
each file because of `assertHandled`: both files have to make the SAME pair of
claims - a frame appeared, *and* `record_unhandled` stopped counting the event -
and a harness copied twice is a harness that will make the pair only once.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timezone
from typing import Any

from crewai.events.types.flow_events import MethodExecutionStartedEvent

from brief_crew.events import FrameBuffer, NodeRegistry, StreamSinkAdapter

TS = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)
FLOW = "BuilderFlow"
NODE = "draft"


class FrameCase(unittest.TestCase):
    """A real `StreamSinkAdapter` writing into a real `FrameBuffer`."""

    def setUp(self) -> None:
        self.buffer = FrameBuffer(capacity=64)
        self.adapter = StreamSinkAdapter(
            run_id="frame-case",
            buffer=self.buffer,
            registry=NodeRegistry(flow_method_nodes={NODE: NODE}),
        )
        # Enter the node the way CrewAI does, so attribution is production's
        # rather than the `unattributed` quarantine.
        self.adapter(
            None,
            MethodExecutionStartedEvent(
                flow_name=FLOW, method_name=NODE, state={}, params=None, timestamp=TS
            ),
        )
        self.assertEqual(self.adapter.serializer.unhandled, {})

    def emit(self, event: Any) -> list:
        """The frames THIS event added, and no earlier ones."""

        before = len(self.buffer.replay())
        self.adapter(None, event)
        return self.buffer.replay()[before:]

    def assertHandled(self, event_type: str) -> None:
        """The second claim, and the one a frame alone does not make.

        The ladder handles about thirty of CrewAI's ~150 event classes and every
        other one falls through to `record_unhandled`, which counts it and emits
        nothing. A branch that drafts a frame and then falls through anyway would
        satisfy every assertion about the frame and still leave the event on the
        unhandled tally - so both are checked, every time.
        """

        self.assertNotIn(
            event_type,
            self.adapter.serializer.unhandled,
            "the ladder drafted a frame and still counted the event as unhandled",
        )
