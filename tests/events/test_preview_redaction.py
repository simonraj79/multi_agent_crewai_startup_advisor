"""`details.*_preview` is redacted, and until 2026-09-04 it was not.

**The defect, stated as narrowly as it was found.** `FieldBoundedSerializer`
has two ways of putting a value on a frame. `clip` walks the structure under
the serializer's bounds and replaces every secret-named value with `***`;
`_preview` reduced the same value to the ≤2,048 characters a rail renders, with
`json.dumps` and no redaction at all. Both ran on the SAME value for a tool
frame, so `details.args` read `***` and `details.input_preview` beside it read
the plaintext - one frame, two walks, one of them clean.

It was not theoretical and it was not reachable only by a contrived payload.
A builder agent's Firecrawl tool holds its key as a pydantic FIELD
(`FirecrawlSearchTool.api_key`), so anything putting the tool's own dump into a
tool-usage event put a live credential into a preview - on the live socket, in
`GET /api/runs/{id}/frames`, and in both log exports. Found by plan 06
criterion 3's run against a real vault credential, not by reading the list.

**Three previews are affected and all three are asserted here**, because the
repair is one line in one method and a reader has no way to tell from the fix
which callers it covered: `input_preview` and `output_preview` on TOOL frames,
and `output_preview` on a NODE_END frame - which is the one a builder node's own
output goes through, so a node returning a mapping with a key in it was the
second path.

Nothing here calls a model or a network. It drafts frames in memory.
"""

from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone

from crewai.events.types.flow_events import (
    MethodExecutionFinishedEvent,
    MethodExecutionStartedEvent,
)
from crewai.events.types.tool_usage_events import (
    ToolUsageErrorEvent,
    ToolUsageFinishedEvent,
    ToolUsageStartedEvent,
)

from brief_crew.events import FrameBuffer, NodeRegistry, StreamSinkAdapter
from brief_crew.events.redaction import REDACTED
from brief_crew.events.serializer import FieldBoundedSerializer

TS = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)
FLOW = "BuilderFlow"
NODE = "draft"

#: Distinctive enough that a substring search cannot pass by luck. A short
#: canary is useless here: "x" appears in the word "text".
CANARY = "sk-live-PREVIEW-CANARY-0123456789abcdef"

#: Shaped like a real tool's `model_dump()`: a credential field beside the
#: ordinary configuration a person actually wants to read in a preview.
TOOL_DUMP = {
    "name": "Firecrawl web search tool",
    "api_key": CANARY,
    "config": {"limit": 5, "only_main_content": True},
}


def _adapter(buffer: FrameBuffer) -> StreamSinkAdapter:
    return StreamSinkAdapter(
        run_id="preview-redaction",
        buffer=buffer,
        registry=NodeRegistry(flow_method_nodes={NODE: NODE}),
    )


def _enter(adapter: StreamSinkAdapter) -> None:
    adapter(
        None,
        MethodExecutionStartedEvent(
            flow_name=FLOW, method_name=NODE, state={}, params=None, timestamp=TS
        ),
    )


def _rendered(buffer: FrameBuffer, kind: str) -> str:
    frames = [frame for frame in buffer.replay() if frame.kind.value == kind]
    assert frames, f"no {kind} frame was drafted"
    return json.dumps([frame.to_dict() for frame in frames], default=str)


class PreviewRedactionTests(unittest.TestCase):
    """One method, three callers, and the direct unit underneath them."""

    def test_the_preview_helper_itself_redacts(self) -> None:
        """The unit, so a failure names the method rather than a frame."""

        preview = FieldBoundedSerializer()._preview(TOOL_DUMP)
        self.assertNotIn(CANARY, preview)
        self.assertIn(REDACTED, preview)
        # And it is still a preview: what a person reads survives.
        self.assertIn("Firecrawl web search tool", preview)
        self.assertIn("only_main_content", preview)

    def test_a_plain_string_preview_is_untouched(self) -> None:
        """The other half. A preview that redacted prose would be useless."""

        self.assertEqual(
            FieldBoundedSerializer()._preview("the market looks thin"),
            "the market looks thin",
        )

    def test_input_preview_on_a_tool_frame_is_redacted(self) -> None:
        buffer = FrameBuffer(capacity=16)
        adapter = _adapter(buffer)
        _enter(adapter)
        adapter(
            None,
            ToolUsageStartedEvent(
                tool_name="firecrawl_search", tool_args=TOOL_DUMP, timestamp=TS
            ),
        )
        rendered = _rendered(buffer, "tool")
        self.assertIn("input_preview", rendered)
        self.assertNotIn(CANARY, rendered)
        self.assertIn(REDACTED, rendered)
        self.assertEqual(buffer.stats().emit_errors, 0)

    def test_output_preview_on_a_finished_tool_frame_is_redacted(self) -> None:
        buffer = FrameBuffer(capacity=16)
        adapter = _adapter(buffer)
        _enter(adapter)
        adapter(
            None,
            ToolUsageFinishedEvent(
                tool_name="firecrawl_search",
                tool_args=TOOL_DUMP,
                output=TOOL_DUMP,
                started_at=TS,
                finished_at=TS + timedelta(milliseconds=5),
                timestamp=TS,
            ),
        )
        rendered = _rendered(buffer, "tool")
        self.assertIn("output_preview", rendered)
        self.assertNotIn(CANARY, rendered)

    def test_a_failed_tool_frame_carries_no_credential_either(self) -> None:
        buffer = FrameBuffer(capacity=16)
        adapter = _adapter(buffer)
        _enter(adapter)
        adapter(
            None,
            ToolUsageErrorEvent(
                tool_name="firecrawl_search",
                tool_args=TOOL_DUMP,
                error=TOOL_DUMP,
                timestamp=TS,
            ),
        )
        self.assertNotIn(CANARY, _rendered(buffer, "tool"))

    def test_output_preview_on_a_node_end_frame_is_redacted(self) -> None:
        """The second caller, and the one a builder node's own output uses."""

        buffer = FrameBuffer(capacity=16)
        adapter = _adapter(buffer)
        _enter(adapter)
        adapter(
            None,
            MethodExecutionFinishedEvent(
                flow_name=FLOW,
                method_name=NODE,
                state={},
                result=TOOL_DUMP,
                timestamp=TS,
            ),
        )
        rendered = _rendered(buffer, "node_state")
        self.assertIn("output_preview", rendered)
        self.assertNotIn(CANARY, rendered)

    def test_the_two_walks_on_one_frame_now_AGREE(self) -> None:
        """The shape of the defect, asserted as a property rather than a value.

        `details.args` went through `clip` and `details.input_preview` did not,
        so one frame carried the same key twice and disagreed with itself. A
        future preview helper that stops consulting the redaction list fails
        here with a sentence naming both fields.
        """

        buffer = FrameBuffer(capacity=16)
        adapter = _adapter(buffer)
        _enter(adapter)
        adapter(
            None,
            ToolUsageStartedEvent(
                tool_name="firecrawl_search", tool_args=TOOL_DUMP, timestamp=TS
            ),
        )
        frame = [f for f in buffer.replay() if f.kind.value == "tool"][0]
        details = dict(frame.details)
        self.assertEqual(
            details["args"]["api_key"],
            REDACTED,
            "clip stopped redacting, which is a different defect",
        )
        self.assertNotIn(
            CANARY,
            details["input_preview"],
            "details.args is redacted and details.input_preview is not; "
            "the two walks on one frame disagree again",
        )


if __name__ == "__main__":
    unittest.main()
