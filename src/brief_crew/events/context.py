"""Per-run capture scope propagated by CrewAI across worker threads."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Iterator

from crewai.events.stream_context import add_stream_sink, reset_stream_sinks

from brief_crew.events.adapter import StreamSinkAdapter
from brief_crew.events.registry import current_node_scope


ui_run_id: ContextVar[str | None] = ContextVar("brief_crew_ui_run_id", default=None)


@dataclass(frozen=True, slots=True)
class CaptureContext:
    run_id: str
    adapter: StreamSinkAdapter


current_capture: ContextVar[CaptureContext | None] = ContextVar(
    "brief_crew_capture", default=None
)


@contextmanager
def capture_events(context: CaptureContext) -> Iterator[CaptureContext]:
    """Install one run-local sink and restore all ContextVars on exit."""

    run_token = ui_run_id.set(context.run_id)
    capture_token = current_capture.set(context)
    # A run begins inside no node of its own. The service executes runs on a
    # pooled worker thread, and `asyncio.run` copies that thread's context into
    # the flow, so without this a second run on a reused thread would inherit
    # the last node the previous run entered and mis-attribute anything raised
    # before its own first flow method starts.
    scope_token = current_node_scope.set(None)
    sink_token = add_stream_sink(context.adapter)
    try:
        yield context
    finally:
        reset_stream_sinks(sink_token)
        current_node_scope.reset(scope_token)
        current_capture.reset(capture_token)
        ui_run_id.reset(run_token)
