"""Optional async event-bus adapter for hosts that cannot install a stream sink."""

from __future__ import annotations

from typing import Any

from crewai.events import (
    AgentExecutionCompletedEvent,
    AgentExecutionErrorEvent,
    AgentExecutionStartedEvent,
    BaseEventListener,
    CrewKickoffCompletedEvent,
    CrewKickoffFailedEvent,
    CrewKickoffStartedEvent,
    FlowFailedEvent,
    FlowFinishedEvent,
    FlowStartedEvent,
    HumanFeedbackReceivedEvent,
    HumanFeedbackRequestedEvent,
    LLMCallCompletedEvent,
    LLMCallFailedEvent,
    LLMCallStartedEvent,
    LLMStreamChunkEvent,
    MethodExecutionFailedEvent,
    MethodExecutionFinishedEvent,
    MethodExecutionStartedEvent,
    TaskCompletedEvent,
    TaskFailedEvent,
    TaskStartedEvent,
    ToolUsageErrorEvent,
    ToolUsageFinishedEvent,
    ToolUsageStartedEvent,
)
from crewai.events.event_bus import CrewAIEventsBus

from brief_crew.events.context import current_capture


PUBLIC_CAPTURE_EVENTS = (
    FlowStartedEvent,
    FlowFinishedEvent,
    FlowFailedEvent,
    MethodExecutionStartedEvent,
    MethodExecutionFinishedEvent,
    MethodExecutionFailedEvent,
    HumanFeedbackRequestedEvent,
    HumanFeedbackReceivedEvent,
    ToolUsageStartedEvent,
    ToolUsageFinishedEvent,
    ToolUsageErrorEvent,
    LLMCallStartedEvent,
    LLMCallCompletedEvent,
    LLMCallFailedEvent,
    LLMStreamChunkEvent,
    AgentExecutionStartedEvent,
    AgentExecutionCompletedEvent,
    AgentExecutionErrorEvent,
    TaskStartedEvent,
    TaskCompletedEvent,
    TaskFailedEvent,
    CrewKickoffStartedEvent,
    CrewKickoffCompletedEvent,
    CrewKickoffFailedEvent,
)


class UIEventListener(BaseEventListener):
    """Opt-in safety net; do not combine with the primary stream sink."""

    def setup_listeners(self, crewai_event_bus: CrewAIEventsBus) -> None:
        async def capture(source: Any, event: Any) -> None:
            context = current_capture.get()
            if context is not None:
                context.adapter(source, event)

        for event_type in PUBLIC_CAPTURE_EVENTS:
            crewai_event_bus.on(event_type)(capture)
