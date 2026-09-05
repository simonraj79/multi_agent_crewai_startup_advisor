"""What each frame becomes, and what never reaches a frame at all (C3).

Two tables, and they answer two different questions.

`FRAME_DISPOSITIONS` answers **"this frame arrived - what is it?"**. It is keyed
on `FrameKind` and, where the kind carries more than one meaning, on the frame's
own `stage`. Nothing in it names a flow, an agent, a task or a tool: the keys
are the frame vocabulary, which is the whole reason the exporter attaches to
frames rather than to CrewAI events.

`UNMAPPED_WITH_REASON` answers **"this CrewAI event exists - why is it not
here?"**. The frame pipeline handles a subset of CrewAI 1.15.18's `BaseEvent`
subclasses and counts the rest as unhandled, so an exporter downstream of it
cannot see them however it is written. Listing them with a reason is what turns
"the trace has no retrieval spans" from a mystery into a decision somebody made.
That table is WRITTEN OUT rather than derived, for the reason the comment above
it gives: a table computed from the same enumeration a test compares it against
cannot fail that test.

The tally the frame pipeline keeps of those unhandled classes now travels. The
serializer puts its per-class counts on the run's terminal frame and the
exporter writes them onto the trace as `unhandled_event_counts`, so the gap is
readable in Langfuse and not only here: a reader who wonders why a run has no
retrieval spans can see how many retrieval events it raised.

**FOLD is not DROP.** Several frame kinds carry a fact ABOUT an observation
rather than being one - the token counts for a model call, the streamed
characters of its answer, the text it finally said, the run's coalesced totals,
which edge was taken into a node, how many thoughts an agent had. Each is folded
into the observation it describes and shows up there as a field. Making each of
them an observation of its own would multiply the size of a trace several times
over and put a run's tokens somewhere other than on the call that spent them.

That is also a **billing** decision and not only a tidiness one: a Langfuse plan
counts observations, so an exporter that turns every frame into one would spend
a month's allowance on edges. Only the contract's hierarchy, the gate events and
the frames nothing here recognises become observations.

Anything this table does not recognise becomes an EVENT observation named after
the frame's own `event_type`, carrying its redacted details. That is the last
line of `disposition_for`, and it is what C3's second half asks for.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Mapping

from brief_crew.events.models import FrameKind


# --------------------------------------------------------------------------
# Frame dispositions
# --------------------------------------------------------------------------

#: A run-level statement: it opens, revises or ends the trace and its run span.
RUN = "run"
#: Opens or closes a node span.
NODE = "node"
#: Opens or closes a task/agent span, by the identity the frame carries.
ACTOR = "actor"
#: A model call: a GENERATION observation.
GENERATION = "generation"
#: A tool call: a SPAN carrying `metadata.observation_role = "tool"`.
TOOL = "tool"
#: An EVENT observation under whatever span is innermost.
EVENT = "event"
#: A fact about an observation that already exists. See the module docstring.
FOLD = "fold"
#: A Langfuse score, on the innermost span that can carry it.
SCORE = "score"


# --------------------------------------------------------------------------
# The two `reason` values a terminal frame can carry
# --------------------------------------------------------------------------
#
# MIRRORS of `service/registry.py`'s own constants (`COST_CEILING_REASON` at
# `:97`, `INTERRUPTED_REASON` at `:84`), copied rather than imported: the
# exporter package imports `brief_crew.events.models` and its own modules and
# nothing from the service layer, so that a change to the service cannot break
# instrumentation and instrumentation cannot pull a web framework into a
# process that only wanted to write a span.
#
# They are frame VOCABULARY and not flow identity - the registry writes them
# for every workflow it runs, hand-written or authored - so mirroring them puts
# nothing at risk under row C1.
#
# `tests/observability/test_terminal_states.py` asserts both against the
# registry's own constants, which is the anti-rot half this repository's client
# mirrors are built to have: a mirror without one agreed with itself at the
# wrong number for weeks.
COST_CEILING_REASON = "cost_ceiling"
INTERRUPTED_REASON = "service_restart"


@dataclass(frozen=True, slots=True)
class Disposition:
    kind: str
    #: Why, in one sentence, for a reader of the payload rather than of this file.
    reason: str


FRAME_DISPOSITIONS: Mapping[Any, Disposition] = {
    FrameKind.RUN_STATE: Disposition(
        RUN, "the transport's own statement about the run: start, pause, end"
    ),
    FrameKind.NODE_STATE: Disposition(
        NODE, "one flow method's execution, which is the span every other one hangs off"
    ),
    FrameKind.AGENT: Disposition(
        ACTOR, "a task or an agent execution boundary, named by the identity on the frame"
    ),
    FrameKind.TOOL: Disposition(TOOL, "one tool call, with its own status and duration"),
    FrameKind.LLM: Disposition(GENERATION, "one model call"),
    FrameKind.TOKEN: Disposition(
        FOLD, "the token counts and cost of a model call, folded onto that call"
    ),
    FrameKind.METRICS: Disposition(
        FOLD, "the run's coalesced totals, folded onto the run span"
    ),
    FrameKind.GUARDRAIL: Disposition(
        SCORE, "a check on an output, recorded as a score on the task it checked"
    ),
    FrameKind.GATE_OPEN: Disposition(EVENT, "a run paused for a person; not terminal"),
    FrameKind.GATE_CLOSED: Disposition(EVENT, "a person answered; the run continues"),
    FrameKind.GATE_EXPIRED: Disposition(EVENT, "a pause outlived its deadline"),
    FrameKind.GATE_ALERT: Disposition(EVENT, "a pause nobody has answered"),
    FrameKind.EDGE_TAKEN: Disposition(
        FOLD, "which edge was taken, folded onto the node the edge arrived at"
    ),
    FrameKind.VERDICT: Disposition(
        FOLD, "a deterministic result the run computed, folded onto the run span"
    ),
    FrameKind.REASONING: Disposition(
        FOLD, "an agent's own thought line, counted onto the agent that thought it"
    ),
    FrameKind.ERROR: Disposition(
        RUN, "an error; terminal when it speaks for the run, an EVENT otherwise"
    ),
}


#: `stage` values on an LLM frame that are folded rather than made into their
#: own observation, with the reason each is folded.
LLM_FOLDED_STAGES: Mapping[str, str] = {
    "chunk": "streamed characters of one call, counted onto that call",
    "utterance": "what the call finally said, folded onto that call",
}


def disposition_for(kind: Any, stage: str | None = None) -> Disposition:
    """The disposition of one frame, defaulting to EVENT rather than to nothing.

    The default is the whole point: a frame kind added to `events/models.py`
    later, or a `stage` nobody here anticipated, produces a named EVENT
    observation carrying its details instead of vanishing.
    """

    if kind is FrameKind.LLM and stage in LLM_FOLDED_STAGES:
        return Disposition(FOLD, LLM_FOLDED_STAGES[str(stage)])
    found = FRAME_DISPOSITIONS.get(kind)
    if found is not None:
        return found
    return Disposition(EVENT, "a frame kind this exporter has never seen")


# --------------------------------------------------------------------------
# CrewAI event coverage (C3)
# --------------------------------------------------------------------------

#: The CrewAI 1.15.18 event classes the frame pipeline converts, and the
#: observation each one becomes here. Mirrors the isinstance ladder in
#: `events/serializer.py::_event_drafts`; `tests/observability/test_event_coverage.py`
#: asserts every name below is both a real CrewAI class AND named in that
#: file's source, so the two cannot drift apart in silence.
FRAME_PIPELINE_EVENTS: Mapping[str, str] = {
    "FlowStartedEvent": RUN,
    "FlowFinishedEvent": RUN,
    "FlowFailedEvent": RUN,
    "MethodExecutionStartedEvent": NODE,
    "MethodExecutionFinishedEvent": NODE,
    "MethodExecutionFailedEvent": NODE,
    "MethodExecutionPausedEvent": NODE,
    "HumanFeedbackRequestedEvent": EVENT,
    "HumanFeedbackReceivedEvent": EVENT,
    "AgentExecutionStartedEvent": ACTOR,
    "AgentExecutionCompletedEvent": ACTOR,
    "AgentExecutionErrorEvent": ACTOR,
    "TaskStartedEvent": ACTOR,
    "TaskCompletedEvent": ACTOR,
    "TaskFailedEvent": ACTOR,
    "CrewKickoffStartedEvent": ACTOR,
    "CrewKickoffCompletedEvent": ACTOR,
    "CrewKickoffFailedEvent": ACTOR,
    "LLMCallStartedEvent": GENERATION,
    "LLMCallCompletedEvent": GENERATION,
    "LLMCallFailedEvent": GENERATION,
    "LLMStreamChunkEvent": FOLD,
    "ToolUsageStartedEvent": TOOL,
    "ToolUsageFinishedEvent": TOOL,
    "ToolUsageErrorEvent": TOOL,
    "ToolValidateInputErrorEvent": TOOL,
    "ToolSelectionErrorEvent": TOOL,
    "ToolExecutionErrorEvent": TOOL,
    "LLMGuardrailStartedEvent": EVENT,
    "LLMGuardrailCompletedEvent": EVENT,
    "AgentLogsExecutionEvent": EVENT,
    "MCPConnectionFailedEvent": EVENT,
    "SkillLoadedEvent": EVENT,
    "SkillActivatedEvent": EVENT,
    "SkillUsedEvent": EVENT,
    "SkillLoadFailedEvent": EVENT,
}


#: Why each family of CrewAI events does not reach a frame, and therefore
#: cannot reach an observation. One sentence per declaring module, because the
#: decision was taken per family; the TABLE below names every class, because
#: the whole value of the table is that a class CrewAI adds tomorrow is in
#: neither half of it and fails a test.
_A2A = (
    "agent-to-agent messaging, which nothing in this application uses; "
    "exporting it would be 32 event types of noise"
)
_LITE_AGENT = (
    "the lite-agent variants, raised when an agent runs outside a crew; the "
    "frame pipeline handles the in-crew trio and no path here runs the other"
)
_CHECKPOINT = (
    "flow checkpoint, fork and restore; a resume is already one trace here "
    "because the trace is keyed on the run id, so these would add detail "
    "without adding an answer"
)
_CREW_LIFECYCLE = (
    "the test and train lifecycles, which are development commands rather "
    "than anything this service can launch"
)
_ENV = "process environment probes, which say nothing about a run"
_FLOW = (
    "flow creation, plotting, conversational turns and input requests; none "
    "is a step that happened inside a run being traced"
)
_HOOK = (
    "which interception point fired - a useful trace line and not one the "
    "frame pipeline emits today; recorded as a gap rather than a decision"
)
_KNOWLEDGE = (
    "knowledge retrieval; the frame pipeline raises none of these, so the "
    "retrieval work is absent from every dollar figure as well as from the "
    "trace. The largest single gap on this list"
)
_LLM_REASONING = (
    "the reasoning-token stream, whose sibling chunk event is handled; a "
    "per-token view the frame pipeline does not carry"
)
_GUARDRAIL_DETAIL = "the guardrail's own internal detail beyond start and result"
_LOGGING = "console formatting, which is a rendering concern"
_MCP = (
    "successful MCP connections and tool calls; only the failure is framed "
    "today, so a graph whose tools are MCP servers is traced by its errors "
    "alone. A real gap, and the second largest on this list"
)
_MEMORY = (
    "memory query, save and retrieval; same gap as knowledge above, and the "
    "same consequence for embedding spend"
)
_OBSERVATION = (
    "plan-and-execute step boundaries, which this application's flows do not use"
)
_REASONING = (
    "the planning step; a natural parent span for the tool calls under it, "
    "and not framed today"
)
_SKILL = "the skill lifecycle beyond load, activate, use and load-failure"
_SKILL_DOWNLOAD = (
    "skill download progress, declared in `crewai/skills/events.py` rather "
    "than under `crewai.events.types`; a network fetch of a pack, not a step "
    "in a run. It is on this list at all because the enumeration walks that "
    "module too - two classes lived outside every count until it did"
)
_SYSTEM = "process signals, which are not part of any run"
_TASK_EVAL = "task evaluation, which no path here runs"
_TOOL_WARN = (
    "a tool that ran and reported failure under a warn policy, which reaches "
    "the trace as the failure field of its own finished frame instead"
)


#: Every `BaseEvent` subclass the installed CrewAI declares that the frame
#: pipeline does NOT convert, with the reason. Row C3 in one object.
#:
#: **Written out, not derived, and that is the entire point.** It used to be
#: computed from the same enumeration the test compared it against, so the
#: partition assertion could not fail: a class CrewAI added would appear on
#: both sides at once and be reported as reasoned-about by a table that had
#: never seen it. Spelled out, a new class is in neither half and
#: `test_event_coverage.py` says so by name.
#:
#: Regenerate with, and paste - never edit a name by hand:
#:
#:     python -c "from brief_crew.observability import mapping; #:                print(sorted(set(mapping.crewai_event_classes()) #:                      - set(mapping.FRAME_PIPELINE_EVENTS) #:                      - set(mapping.UNMAPPED_WITH_REASON)))"
UNMAPPED_WITH_REASON: Mapping[str, str] = {
    # -- a2a_events --
    "A2AAgentCardFetchedEvent": _A2A,
    "A2AArtifactReceivedEvent": _A2A,
    "A2AAuthenticationFailedEvent": _A2A,
    "A2AConnectionErrorEvent": _A2A,
    "A2AContentTypeNegotiatedEvent": _A2A,
    "A2AContextCompletedEvent": _A2A,
    "A2AContextCreatedEvent": _A2A,
    "A2AContextExpiredEvent": _A2A,
    "A2AContextIdleEvent": _A2A,
    "A2AContextPrunedEvent": _A2A,
    "A2AConversationCompletedEvent": _A2A,
    "A2AConversationStartedEvent": _A2A,
    "A2ADelegationCompletedEvent": _A2A,
    "A2ADelegationStartedEvent": _A2A,
    "A2AEventBase": _A2A,
    "A2AMessageSentEvent": _A2A,
    "A2AParallelDelegationCompletedEvent": _A2A,
    "A2AParallelDelegationStartedEvent": _A2A,
    "A2APollingStartedEvent": _A2A,
    "A2APollingStatusEvent": _A2A,
    "A2APushNotificationReceivedEvent": _A2A,
    "A2APushNotificationRegisteredEvent": _A2A,
    "A2APushNotificationSentEvent": _A2A,
    "A2APushNotificationTimeoutEvent": _A2A,
    "A2AResponseReceivedEvent": _A2A,
    "A2AServerTaskCanceledEvent": _A2A,
    "A2AServerTaskCompletedEvent": _A2A,
    "A2AServerTaskFailedEvent": _A2A,
    "A2AServerTaskStartedEvent": _A2A,
    "A2AStreamingChunkEvent": _A2A,
    "A2AStreamingStartedEvent": _A2A,
    "A2ATransportNegotiatedEvent": _A2A,
    # -- agent_events --
    "AgentEvaluationCompletedEvent": _LITE_AGENT,
    "AgentEvaluationFailedEvent": _LITE_AGENT,
    "AgentEvaluationStartedEvent": _LITE_AGENT,
    "LiteAgentExecutionCompletedEvent": _LITE_AGENT,
    "LiteAgentExecutionErrorEvent": _LITE_AGENT,
    "LiteAgentExecutionStartedEvent": _LITE_AGENT,
    # -- checkpoint_events --
    "CheckpointBaseEvent": _CHECKPOINT,
    "CheckpointCompletedEvent": _CHECKPOINT,
    "CheckpointFailedEvent": _CHECKPOINT,
    "CheckpointForkBaseEvent": _CHECKPOINT,
    "CheckpointForkCompletedEvent": _CHECKPOINT,
    "CheckpointForkStartedEvent": _CHECKPOINT,
    "CheckpointPrunedEvent": _CHECKPOINT,
    "CheckpointRestoreBaseEvent": _CHECKPOINT,
    "CheckpointRestoreCompletedEvent": _CHECKPOINT,
    "CheckpointRestoreFailedEvent": _CHECKPOINT,
    "CheckpointRestoreStartedEvent": _CHECKPOINT,
    "CheckpointStartedEvent": _CHECKPOINT,
    # -- crew_events --
    "CrewBaseEvent": _CREW_LIFECYCLE,
    "CrewTestCompletedEvent": _CREW_LIFECYCLE,
    "CrewTestFailedEvent": _CREW_LIFECYCLE,
    "CrewTestResultEvent": _CREW_LIFECYCLE,
    "CrewTestStartedEvent": _CREW_LIFECYCLE,
    "CrewTrainCompletedEvent": _CREW_LIFECYCLE,
    "CrewTrainFailedEvent": _CREW_LIFECYCLE,
    "CrewTrainStartedEvent": _CREW_LIFECYCLE,
    # -- env_events --
    "CCEnvEvent": _ENV,
    "CodexEnvEvent": _ENV,
    "CursorEnvEvent": _ENV,
    "DefaultEnvEvent": _ENV,
    # -- flow_events --
    "ConversationMessageAddedEvent": _FLOW,
    "ConversationRouteSelectedEvent": _FLOW,
    "ConversationTurnCompletedEvent": _FLOW,
    "ConversationTurnFailedEvent": _FLOW,
    "ConversationTurnStartedEvent": _FLOW,
    "FlowCreatedEvent": _FLOW,
    "FlowEvent": _FLOW,
    "FlowInputReceivedEvent": _FLOW,
    "FlowInputRequestedEvent": _FLOW,
    "FlowPausedEvent": _FLOW,
    "FlowPlotEvent": _FLOW,
    # -- hook_events --
    "HookDispatchedEvent": _HOOK,
    # -- knowledge_events --
    "KnowledgeEventBase": _KNOWLEDGE,
    "KnowledgeQueryCompletedEvent": _KNOWLEDGE,
    "KnowledgeQueryFailedEvent": _KNOWLEDGE,
    "KnowledgeQueryStartedEvent": _KNOWLEDGE,
    "KnowledgeRetrievalCompletedEvent": _KNOWLEDGE,
    "KnowledgeRetrievalStartedEvent": _KNOWLEDGE,
    "KnowledgeSearchQueryFailedEvent": _KNOWLEDGE,
    # -- llm_events --
    "LLMEventBase": _LLM_REASONING,
    "LLMThinkingChunkEvent": _LLM_REASONING,
    # -- llm_guardrail_events --
    "LLMGuardrailBaseEvent": _GUARDRAIL_DETAIL,
    # -- logging_events --
    "AgentLogsStartedEvent": _LOGGING,
    # -- mcp_events --
    "MCPConfigFetchFailedEvent": _MCP,
    "MCPConnectionCompletedEvent": _MCP,
    "MCPConnectionStartedEvent": _MCP,
    "MCPEvent": _MCP,
    "MCPToolExecutionCompletedEvent": _MCP,
    "MCPToolExecutionFailedEvent": _MCP,
    "MCPToolExecutionStartedEvent": _MCP,
    # -- memory_events --
    "MemoryBaseEvent": _MEMORY,
    "MemoryQueryCompletedEvent": _MEMORY,
    "MemoryQueryFailedEvent": _MEMORY,
    "MemoryQueryStartedEvent": _MEMORY,
    "MemoryRetrievalCompletedEvent": _MEMORY,
    "MemoryRetrievalFailedEvent": _MEMORY,
    "MemoryRetrievalStartedEvent": _MEMORY,
    "MemorySaveCompletedEvent": _MEMORY,
    "MemorySaveFailedEvent": _MEMORY,
    "MemorySaveStartedEvent": _MEMORY,
    # -- observation_events --
    "GoalAchievedEarlyEvent": _OBSERVATION,
    "ObservationEvent": _OBSERVATION,
    "PlanRefinementEvent": _OBSERVATION,
    "PlanReplanTriggeredEvent": _OBSERVATION,
    "PlanStepCompletedEvent": _OBSERVATION,
    "PlanStepEvent": _OBSERVATION,
    "PlanStepStartedEvent": _OBSERVATION,
    "StepObservationCompletedEvent": _OBSERVATION,
    "StepObservationFailedEvent": _OBSERVATION,
    "StepObservationStartedEvent": _OBSERVATION,
    # -- reasoning_events --
    "AgentReasoningCompletedEvent": _REASONING,
    "AgentReasoningFailedEvent": _REASONING,
    "AgentReasoningStartedEvent": _REASONING,
    "ReasoningEvent": _REASONING,
    # -- skill_events --
    "SkillDiscoveryCompletedEvent": _SKILL,
    "SkillDiscoveryStartedEvent": _SKILL,
    "SkillEvent": _SKILL,
    # -- skills_package --
    "SkillDownloadCompletedEvent": _SKILL_DOWNLOAD,
    "SkillDownloadStartedEvent": _SKILL_DOWNLOAD,
    # -- system_events --
    "SigContEvent": _SYSTEM,
    "SigHupEvent": _SYSTEM,
    "SigIntEvent": _SYSTEM,
    "SigTStpEvent": _SYSTEM,
    "SigTermEvent": _SYSTEM,
    # -- task_events --
    "TaskEvaluationEvent": _TASK_EVAL,
    # -- tool_usage_events --
    "ToolFailureDetectedEvent": _TOOL_WARN,
    "ToolUsageEvent": _TOOL_WARN,
}


#: `BaseEvent` subclasses CrewAI declares OUTSIDE `crewai.events.types`, as
#: (import path, the label the enumeration reports them under). See
#: `crewai_event_classes` for what leaving this empty cost.
_EVENT_MODULES_OUTSIDE_TYPES: tuple[tuple[str, str], ...] = (
    ("crewai.skills.events", "skills_package"),
)


@lru_cache(maxsize=1)
def crewai_event_classes() -> Mapping[str, str]:
    """Every `BaseEvent` subclass CrewAI declares, as name -> declaring module.

    Enumerated from the installed package rather than listed, because a list of
    names typed into this file is a list that is wrong after the next upgrade.
    Cached: the walk imports twenty modules and the app imports them anyway.

    **`crewai.events.types` is not the whole set**, and assuming it was left two
    classes outside every count this row makes. `crewai/skills/events.py`
    declares `SkillDownloadStartedEvent` and `SkillDownloadCompletedEvent` next
    to the code that raises them, so a walk of the types package alone answered
    163 where the installed package declares 165 - and those two were absent
    from the mapped set, absent from the unmapped set, and absent from the
    partition assertion whose whole job is to notice that. Any further module
    is added to the tuple above by name; walking the whole `crewai` package
    would import the world to answer a question about events.
    """

    import importlib
    import inspect
    import pkgutil

    from crewai.events.base_events import BaseEvent
    import crewai.events.types as types_package

    def _collect(module: Any, label: str, found: dict[str, str]) -> None:
        for name, obj in vars(module).items():
            if (
                inspect.isclass(obj)
                and issubclass(obj, BaseEvent)
                and obj is not BaseEvent
                and obj.__module__ == module.__name__
            ):
                found[name] = label

    found: dict[str, str] = {}
    for module_info in pkgutil.iter_modules(types_package.__path__):
        module = importlib.import_module(f"crewai.events.types.{module_info.name}")
        _collect(module, module_info.name, found)
    for module_path, label in _EVENT_MODULES_OUTSIDE_TYPES:
        try:
            module = importlib.import_module(module_path)
        except Exception:  # pragma: no cover - a module a later SDK moved
            continue
        _collect(module, label, found)
    return found


def unmapped_reason(class_name: str, module_name: str) -> str:
    """Why one CrewAI event class produces no observation here.

    `module_name` is accepted and unused: the reason is now per class, and the
    argument is kept so the tooling that already calls this does not change.
    """

    del module_name
    if class_name in FRAME_PIPELINE_EVENTS:
        return ""
    return UNMAPPED_WITH_REASON.get(class_name, "")


def unmapped_with_reason() -> Mapping[str, str]:
    """The table above, as a function, for callers that already read it that way."""

    return UNMAPPED_WITH_REASON
