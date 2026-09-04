"""The builder document - what an author draws, before anything compiles it.

`builder.flow/v1` is the ONLY authored artefact. The graph descriptor the
console renders and the `crewai.flow/v1` definition CrewAI executes are both
derived from it and cached; neither is ever written by hand, and neither is
ever a source of truth about what the author meant.

**What this module checks, and what it deliberately does not.** The models here
validate SHAPE - one object at a time, and only what that object can know about
itself: is this a node id, is this tier one of two, is this `with:` value a JSON
literal or the one resolvable state reference. Everything COUNTABLE or
CROSS-OBJECT lives in `bounds.py` and is reported rather than raised, because an
author drawing a canvas needs every problem at once with the offending node
named, not the first pydantic error out of the door. So a router with nine
branches parses cleanly here and is refused there, and that is on purpose.

The one exception is `join: "any"`, which is refused at parse time with a
message rather than counted: it is not a bound that could be relaxed, it is a
shape that was measured to end a run silently, and there is nothing to report
because there is nothing to fix except deleting it.

Every pattern, allowlist and per-field ceiling comes from `brief_crew.config`.
The compiler asserts against the same constants, and those two agreeing is the
whole of the compiled-namespace guarantee.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

from brief_crew.config import (
    BUILDER_DOCUMENT_ID_PATTERN,
    CREDENTIAL_ID_PATTERN,
    BUILDER_DOCUMENT_SCHEMA,
    BUILDER_ID_PATTERN,
    BUILDER_MAX_AGENT_ITER,
    BUILDER_MAX_GATE_MESSAGE_CHARS,
    BUILDER_MAX_GUARDRAIL_RETRIES,
    BUILDER_MAX_LABEL_CHARS,
    BUILDER_MAX_NAME_CHARS,
    BUILDER_MAX_NODE_RETRIES,
    BUILDER_MAX_PLANNING_STEPS,
    BUILDER_MAX_PROMPT_CHARS,
    BUILDER_MAX_RETRY_BACKOFF_SECONDS,
    BUILDER_ROUTER_COMPARISONS,
    BUILDER_ROUTER_OTHERWISE,
    BUILDER_STATE_REF_PATTERN,
    BUILDER_TRANSFORM_OPS,
    BUILDER_RESEARCH_TOOLS,
    MAX_RUN_INPUT_CHARS,
    MAX_RUN_INPUT_KEYS,
    RUN_RESULT_BODY_KEYS,
    VALIDATOR_BRANCH_MAX_ITER,
    VALIDATOR_GATE_TIMEOUT_SECONDS,
)

# TEN kinds in two families, and there is no eleventh (03-node-library.md D1).
# Section B of the locked spec derives each flow kind's compiled shape; `gate` is
# the only kind that compiles to two flow methods, which is a fact `bounds.py`
# has to know when it generates idents.
#
# The union is deliberately CLOSED on both sides of the wire, because closing it
# is what turns "somebody added a kind and forgot the inspector" into a compile
# error rather than a blank panel at runtime - `InspectorRail.vue`'s
# `Record<NodeKind, Component>` and `NodePalette.vue`'s tile count both fail to
# build on an unhandled kind.
#
#   FLOW kinds are steps: they take an edge in, they do something, they pass on.
#   ATTACHMENT kinds are not steps at all. They are things an agent or crew
#   HAS - a tool, an MCP server, a skill - and they reach it along an `attach`
#   edge. They never run, never bill, never appear in a cycle, and never count
#   toward the graph-size bound, because none of those things is true of a
#   possession.
NodeKind = Literal[
    # flow
    "input", "agent", "crew", "gate", "router", "transform", "output",
    # attachment
    "tool", "mcp", "skill",
]

# Which OpenRouter tier a billable node runs on. The two words are the whole
# vocabulary because `config.py` declares exactly two models; a node never
# names a model, and that is what keeps model choice in `config.py`.
Tier = Literal["cheap", "escalation"]

# What a `with:` value may be: a JSON scalar, or the one resolvable state
# reference. Lists and objects are absent deliberately - every argument shape
# the ten compiler entrypoints accept is flat, and a nested literal would be a
# place for an author to hide something the compiler never looks at.
JsonScalar = str | int | float | bool | None

NodeId = Annotated[str, StringConstraints(pattern=BUILDER_ID_PATTERN)]
DocumentId = Annotated[str, StringConstraints(pattern=BUILDER_DOCUMENT_ID_PATTERN)]
# An OPAQUE reference into the caller's vault. The parser checks the spelling
# and nothing else: whether the row exists, and whose it is, are questions
# only an identity can answer, and they are asked by `validate` with one and
# by `resolve_credential` at run time (plan 01 D6, D10).
CredentialId = Annotated[str, StringConstraints(pattern=CREDENTIAL_ID_PATTERN)]
Label = Annotated[str, StringConstraints(min_length=1, max_length=BUILDER_MAX_LABEL_CHARS)]
# One free-text prompt field on an AUTHORED node - a role, a goal, a backstory
# or a task's description. Bounded in `config.py` rather than here for the
# platform rule's reason, and non-empty because an authored agent whose role is
# the empty string is a library agent that forgot to name one.
Prompt = Annotated[str, StringConstraints(min_length=1, max_length=BUILDER_MAX_PROMPT_CHARS)]
# An OpenRouter model slug, as the model registry (C3, plan 05) spells it.
# Checked here for SHAPE only - whether this deployment can reach the model,
# and whether it is under the price ceiling, are questions only the registry
# can answer, and it answers them in `bounds.py`'s reporting half rather than
# by raising here.
ModelSlug = Annotated[str, StringConstraints(min_length=1, max_length=BUILDER_MAX_NAME_CHARS)]

# What a billable node does when its step raises.
#
# `fail` ends the run, which is the only behaviour the runtime has today.
# `route` sends the failure out of a SECOND source port named `error`, so an
# author draws the recovery path rather than losing the run to it - which is
# why this one config field is the only thing in the schema that changes a
# node's port list. `nodeKinds.ts::billableOut` reads it the same way.
NodeErrorPolicy = Literal["fail", "route"]

# `Agent.tool_failure_policy` at CrewAI 1.15.18, by its enum's own VALUES
# (`crewai.tools.tool_failure.ToolFailurePolicy`), not by its member names.
ToolFailurePolicy = Literal["ignore", "warn", "raise"]

# The types a task's declared output schema and a flow state field may take.
# Four JSON scalars and no object: the compiler turns this map into a pydantic
# class with `create_model`, and a nested schema would be a second document
# format inside the document.
ScalarType = Literal["string", "number", "integer", "boolean"]

_STATE_REF = re.compile(BUILDER_STATE_REF_PATTERN)
# What an author's near-miss looks like. Any `${` at all means they were
# reaching for a reference, so the near-miss is refused rather than accepted as
# a string literal - see `_checked_with_value`.
_EXPRESSION_MARKER = "${"


class BuilderModel(BaseModel):
    """Closed, immutable base contract for an authored builder document.

    `extra="forbid"` because a key this schema does not know is a key the
    compiler will not compile, and silently dropping it would let a canvas ship
    a feature the runtime never had.

    Deliberately NOT `strict=True`, unlike `schemas/validator.py`'s base. That
    model parses agent output, where a coerced type hides a model that answered
    the wrong question. This one parses a browser's JSON, where `{"x": 120.0}`
    for an integer position is a serialiser detail and refusing it would be a
    422 the author cannot act on.
    """

    model_config = ConfigDict(
        allow_inf_nan=False,
        extra="forbid",
        frozen=True,
        populate_by_name=True,
        str_strip_whitespace=True,
    )


def _checked_with_value(value: JsonScalar, *, where: str) -> JsonScalar:
    """A `with:` value: a JSON scalar, or exactly one resolvable state ref.

    A string carrying `${` that is not the blessed single-key shape is REFUSED
    rather than passed through as a literal. That asymmetry is the point: only
    `${state.a_value}` was ever measured resolving, so `${state.out__a.score}`
    would reach the agent as that exact text - eight characters of punctuation
    in the middle of a prompt, with nothing anywhere saying the reference did
    not resolve.
    """

    if isinstance(value, str) and _EXPRESSION_MARKER in value and not _STATE_REF.match(value):
        raise ValueError(
            f"{where} looks like a state reference but is not a resolvable one: "
            f"write ${{state.<key>}} with a single lowercase key. "
            "Nested access such as ${state.out__scoper.segment} does not resolve, "
            "and is refused here rather than passed to the agent as literal text"
        )
    return value


def _checked_with_mapping(values: dict[str, JsonScalar], *, where: str) -> dict[str, JsonScalar]:
    """Every value of a `with:`-shaped mapping, with the key named on failure."""

    for name, value in values.items():
        _checked_with_value(value, where=f"{where}[{name!r}]")
    return values


class Position(BuilderModel):
    """Where the canvas draws a node. Never compiled, never read at runtime."""

    x: int = 0
    y: int = 0


class InputConfig(BuilderModel):
    """`input` - seeds the run from one named request input.

    `field` is what `POST /api/sessions/{id}/runs` must carry in `inputs`, and
    it becomes the descriptor's declared input field. It is the reason the
    service can stop hardcoding `"idea" if validator else "topic"`.
    """

    field: NodeId
    # What the console labels the box. Distinct from the node's own label,
    # which is what the canvas draws; a node called "Idea" may reasonably ask
    # for "Describe the product in a sentence or two".
    label: Label | None = None
    # Bounded by the same constant the run endpoint enforces, so an author
    # cannot draw a graph whose own input the API would refuse.
    max_chars: int = Field(default=MAX_RUN_INPUT_CHARS, ge=1, le=MAX_RUN_INPUT_CHARS)
    required: bool = True


class TaskConfig(BuilderModel):
    """The one `Task` an authored agent runs - FD5's five `task.*` leaves.

    A composite rather than five flat fields because a Task is one CrewAI
    primitive: `description` and `expected_output` are the two halves of one
    instruction, and splitting them across the node's top level would put them
    beside `max_rpm`, which is not a thing an author edits in the same breath.
    """

    description: Prompt
    expected_output: Prompt
    # Compiles to `Task.output_json` / `Task.response_model` via `create_model`
    # (09's work). A FLAT map of field name to scalar type, deliberately: a
    # nested JSON Schema here would be a second document format inside the
    # document, and every argument shape the ten compiler entrypoints accept is
    # flat for the same reason.
    output_schema: dict[NodeId, ScalarType] | None = None
    markdown: bool = False
    async_execution: bool = False


class LlmConfig(BuilderModel):
    """`Agent.llm` - eleven leaves, and the reason FD5 counts 41 rather than 25.

    Every field is CrewAI's `LLM(...)` verbatim except that `stream` is absent:
    a builder run streams frames by construction, so there is nothing for an
    author to decide. `reasoning_effort` is here and NOT `stream` for the same
    reason 04 D2 chose that swap.
    """

    model: ModelSlug
    # OpenAI-shaped ranges, which are properties of the API rather than policy
    # of this repository - so they are literals here rather than constants.
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    top_p: float | None = Field(default=None, ge=0.0, le=1.0)
    # No ceiling. What a completion COSTS is bounded by MAX_RUN_COST_USD, which
    # is the layer that can measure money; inventing a token ceiling here would
    # be inventing a number, and it would be the wrong one for every model in
    # the registry at once.
    max_tokens: int | None = Field(default=None, ge=1)
    timeout: int | None = Field(default=None, ge=1)
    response_format: Literal["text", "json_object"] | None = None
    frequency_penalty: float | None = Field(default=None, ge=-2.0, le=2.0)
    presence_penalty: float | None = Field(default=None, ge=-2.0, le=2.0)
    # Four is the OpenAI-compatible ceiling on stop sequences.
    stop: tuple[str, ...] = ()
    seed: int | None = None
    # SILENTLY DROPPED for every OpenRouter model (`config.py`'s note on
    # `reasoning_effort`), which is why the inspector gates it and says so.
    # Kept in the schema because the drop is CrewAI's behaviour today and not a
    # property of the field, and a document that loses it on a save would lose
    # it for good.
    reasoning_effort: Literal["low", "medium", "high"] | None = None

    @field_validator("stop")
    @classmethod
    def _validate_stop(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) > 4:
            raise ValueError(
                f"{len(value)} stop sequences; the OpenAI-compatible ceiling is 4"
            )
        return value


class RetryConfig(BuilderModel):
    """Whole-node retry - the builder's own loop, inside `run_agent`.

    NOT `Task.max_retries`, which is deprecated at CrewAI 1.15.18, counts
    GUARDRAIL retries and is a different concept sharing a name. The builder's
    `guardrail_max_retries` is the field that means what CrewAI's means; this
    one re-runs the whole node.
    """

    max_retries: int = Field(default=0, ge=0, le=BUILDER_MAX_NODE_RETRIES)
    backoff_seconds: int = Field(default=0, ge=0, le=BUILDER_MAX_RETRY_BACKOFF_SECONDS)
    # The model to try on the LAST attempt, when the named one keeps failing.
    # A REFUSAL is never retried with it (PLANS.md decision 16): a refusal is a
    # decision, and asking a second model until one agrees is not a retry.
    fallback_model: ModelSlug | None = None


class PlanningConfig(BuilderModel):
    """FOUR of `crewai.agent.planning_config.PlanningConfig`'s eleven fields.

    The 00 S9 ruling: `Agent.reasoning` and `Agent.max_reasoning_attempts` are
    deprecated at 1.15.18 and are REPLACED by `Agent.planning` plus these four,
    which are the ones that bound cost and iteration.

    The seven excluded are excluded on purpose. `system_prompt`, `plan_prompt`
    and `refine_prompt` would be a THIRD place prompts live - YAML for this
    repository's crews, the document for an authored agent, and there is no
    room for a third. `llm` would silently put the planner on a different model
    from the one the node names, which is a cost surprise with no visible
    cause. `max_step_iterations`, `observe_steps` and `step_timeout` are not
    cut on principle; nobody has a reason to expose them and an unused control
    is a control an author has to decide about.
    """

    reasoning_effort: Literal["low", "medium", "high"] = "medium"
    max_attempts: int | None = Field(default=None, ge=1, le=BUILDER_MAX_NODE_RETRIES)
    max_steps: int = Field(default=BUILDER_MAX_PLANNING_STEPS, ge=1, le=BUILDER_MAX_PLANNING_STEPS)
    max_replans: int = Field(default=BUILDER_MAX_NODE_RETRIES, ge=0, le=BUILDER_MAX_NODE_RETRIES)


class _BillableConfig(BuilderModel):
    """What `agent` and `crew` share: a tier, retry ceilings and prompt inputs.

    Both ceilings bound RETRY, which is where one node's cost multiplies rather
    than adds. CrewAI counts guardrail retries PER GUARDRAIL, so an unset
    default of 3 permits eight full regenerations of a two-guardrail task - all
    on whichever tier this node names.
    """

    tier: Tier
    max_iter: int = Field(default=VALIDATOR_BRANCH_MAX_ITER, ge=1, le=BUILDER_MAX_AGENT_ITER)
    guardrail_max_retries: int = Field(
        default=BUILDER_MAX_GUARDRAIL_RETRIES, ge=0, le=BUILDER_MAX_GUARDRAIL_RETRIES
    )
    prompt_inputs: dict[str, JsonScalar] = Field(default_factory=dict)
    # The ONE config field that changes a node's port list - see
    # `NodeErrorPolicy` and `BuilderNode.out_ports`. On the shared base rather
    # than on each arm because an authored node and a library one fail the same
    # way, and the canvas draws the same second port for both.
    on_error: NodeErrorPolicy = "fail"

    @field_validator("prompt_inputs")
    @classmethod
    def _validate_prompt_inputs(cls, value: dict[str, JsonScalar]) -> dict[str, JsonScalar]:
        return _checked_with_mapping(value, where="prompt_inputs")


class LibraryAgentConfig(_BillableConfig):
    """`agent` - one allowlisted YAML agent, on one tier, with bound tools.

    `agent_id` keys into the YAML agent registry rather than carrying a role,
    goal or backstory, because THIS repository's prompts live in YAML and a
    document that carried them would be a second place they live. An author who
    wants to write their own prompt writes an `AuthoredAgentConfig` instead,
    where the document IS the only place they live - which is why the two are
    separate arms rather than one model with optional halves.
    """

    agent_id: NodeId
    tools: tuple[str, ...] = ()
    # Stage 1's stand-in for C1 v2's `llm.credential_id` (00 S1 ruling 8): the
    # author's own OpenRouter key for this node's model, by id. The compiler
    # copies the id into `with:` and the runtime resolves it inside the
    # entrypoint; no field value ever enters a document.
    credential_id: CredentialId | None = None

    @field_validator("tools")
    @classmethod
    def _validate_tools(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        unknown = [name for name in value if name not in BUILDER_RESEARCH_TOOLS]
        if unknown:
            raise ValueError(
                f"unknown tool {', '.join(sorted(unknown))}; an agent node may bind only "
                f"the registered research tools {', '.join(sorted(BUILDER_RESEARCH_TOOLS))}"
            )
        if len(set(value)) != len(value):
            raise ValueError("the same tool is bound twice; list each tool once")
        return value


class AuthoredAgentConfig(_BillableConfig):
    """`agent` - a role, a goal, a backstory and one task the author wrote.

    FD5's canonical field list, as amended by the 00 S9 deprecation ruling.
    **Four fields the older plan text names are deliberately absent**, and each
    absence is a decision rather than an oversight:

    * `multimodal` and `function_calling_llm` are CUT. Both are deprecated at
      CrewAI 1.15.18 and `multimodal`'s own message says it goes at v2.0, so a
      control for either is a trap rather than a feature.
    * `reasoning` and `max_reasoning_attempts` are REPLACED by `planning` and
      `planning_config`. CrewAI already folds the old pair into a
      `PlanningConfig` and warns; the switch an author sees should be the one
      the package keeps.

    Attachments - tools, MCP servers, skills - are NOT fields here. They arrive
    along `attach` edges (FD4) and reach the constructor through the compiled
    `with:` block (FD10), which is what keeps "what this agent has" a thing you
    can see on the canvas rather than a list buried in a form.
    """

    # --- essentials
    role: Prompt
    goal: Prompt
    backstory: Prompt
    task: TaskConfig
    llm: LlmConfig

    # --- advanced, all `Agent.*` at 1.15.18 unless marked
    max_rpm: int | None = Field(default=None, ge=1)
    max_execution_time: int | None = Field(default=None, ge=1)
    allow_delegation: bool = False
    # `Agent.memory` is UNIFIED at 1.15.18 (`bool | Memory | MemoryScope |
    # MemorySlice`) and is not three toggles. A document carries the boolean;
    # anything richer is a memory backend, which is not a thing drawn on a
    # canvas.
    memory: bool = False
    cache: bool = True
    respect_context_window: bool = True
    # Builder-only: the whole-node retry loop, and the error port's policy is
    # on `_BillableConfig` above.
    retry: RetryConfig = RetryConfig()

    # --- expert
    system_template: Prompt | None = None
    prompt_template: Prompt | None = None
    response_template: Prompt | None = None
    tool_failure_policy: ToolFailurePolicy | None = None
    planning: bool = False
    planning_config: PlanningConfig | None = None
    # As on the library arm: the id travels, the secret never does.
    credential_id: CredentialId | None = None

    @model_validator(mode="after")
    def _validate_planning(self) -> AuthoredAgentConfig:
        """`planning_config` without `planning` configures nothing.

        Raised rather than reported because it is not a fixable position on a
        canvas - it is a form that filled in four numbers under a switch that
        is off, and the inspector never writes that shape.
        """

        if self.planning_config is not None and not self.planning:
            raise ValueError(
                "planning_config is set and planning is false, so none of it would "
                "be used; turn planning on or drop planning_config"
            )
        return self


class LibraryCrewConfig(_BillableConfig):
    """`crew` - one registered `@CrewBase`, run whole.

    Identical to the library `agent` but for the id and the absence of `tools`:
    a crew's tools are declared by the crew, and letting a document override
    them would move tool binding out of `config.py`'s reach.

    `tier` is declared rather than derived because the document is priced
    before anything is constructed. An author must name the ESCALATION-most
    tier the crew's agents run on, and `bounds.py` counts it against
    MAX_ESCALATION_NODES on that word alone.
    """

    crew_id: NodeId


class AuthoredCrewConfig(_BillableConfig):
    """`crew` - a team the author assembled out of `member` agents.

    FIFTEEN fields, per the 00 S9 ruling that settled 04's count against its
    own prose: `verbose` is the fifteenth. The membership is NOT a field - it
    is the set of `member` edges arriving here, and `task_order` is the order
    those members' tasks run in, which is why the inspector renders the member
    list read-only and lets an author drag the order.
    """

    process: Literal["sequential", "hierarchical"]
    # The member node ids, in the order their tasks run. `bounds.py` checks it
    # against the `member` edges actually drawn, because only that module knows
    # both; an order naming a node that is not a member is a fixable position
    # on a canvas rather than a malformed document.
    task_order: tuple[NodeId, ...] = ()
    # `Crew.__init__` RAISES when the process is hierarchical and neither
    # manager is set (`crew.py:729`). That is a cross-field rule about this one
    # object, so it is checked here rather than reported.
    manager_llm: LlmConfig | None = None
    manager_agent: NodeId | None = None
    memory: bool = False
    cache: bool = True
    max_rpm: int | None = Field(default=None, ge=1)
    planning: bool = False
    planning_llm: LlmConfig | None = None
    retry: RetryConfig = RetryConfig()
    verbose: bool = False

    @model_validator(mode="after")
    def _validate_manager(self) -> AuthoredCrewConfig:
        if self.process == "hierarchical" and self.manager_llm is None and self.manager_agent is None:
            raise ValueError(
                "a hierarchical crew needs a manager: set manager_llm or manager_agent. "
                "CrewAI raises on this at construction, which on a builder graph means "
                "after every upstream node has already billed"
            )
        if self.process == "sequential" and (
            self.manager_llm is not None or self.manager_agent is not None
        ):
            raise ValueError(
                "a sequential crew has no manager to configure; manager_llm and "
                "manager_agent belong to the hierarchical process"
            )
        return self


# The two union arms per billable kind, discriminated by PRESENCE rather than
# by a `kind` tag. There is no tag because the two arms are not two things an
# author picks between in a dropdown - they are "I named one of yours" and "I
# wrote my own", and the field that says which is the field that does the work.
#
# `isinstance` against these aliases is legal (PEP 604 unions accept it) and is
# what every consumer outside this module does. Consumers that need ONE arm -
# `library_problems`, the compiler's `agent_id` read - name the arm, because a
# union member's attributes are not the union's.
AgentConfig = LibraryAgentConfig | AuthoredAgentConfig
CrewConfig = LibraryCrewConfig | AuthoredCrewConfig


def _one_of(
    config: object,
    *,
    library_key: str,
    authored_key: str,
    library_model: type[BuilderModel],
    authored_model: type[BuilderModel],
    kind: str,
) -> BuilderModel:
    """Pick the arm a billable config belongs to, or say why it belongs to neither.

    Both-or-neither is refused HERE, at parse, and the message names both
    fields - which is criterion 2's actual requirement and not decoration. A
    node carrying both is two agents in one box and there is no rule that could
    pick one; a node carrying neither has no prompt at all, from either source.
    Neither is a position on a canvas an author can drag, so neither is a
    `bounds.py` Problem.
    """

    if not isinstance(config, dict):
        config = {} if config is None else config
    if not isinstance(config, dict):
        return authored_model.model_validate(config)

    has_library = library_key in config
    has_authored = authored_key in config
    if has_library and has_authored:
        raise ValueError(
            f"this {kind} node names both {library_key!r} and {authored_key!r}. "
            f"{library_key!r} selects one of this deployment's registered {kind}s, whose "
            f"prompts live in YAML; {authored_key!r} means the document carries the prompt "
            f"itself. A node that names both is two {kind}s in one box and nothing here "
            "could choose between them - drop one"
        )
    if not has_library and not has_authored:
        raise ValueError(
            f"this {kind} node names neither {library_key!r} nor {authored_key!r}, so there "
            f"is nothing to run: {library_key!r} selects a registered {kind} and "
            f"{authored_key!r} authors a new one. Set exactly one"
        )
    model = library_model if has_library else authored_model
    return model.model_validate(config)


def _parse_agent_config(config: object) -> BuilderModel:
    return _one_of(
        config,
        library_key="agent_id",
        authored_key="role",
        library_model=LibraryAgentConfig,
        authored_model=AuthoredAgentConfig,
        kind="agent",
    )


def _parse_crew_config(config: object) -> BuilderModel:
    return _one_of(
        config,
        library_key="crew_id",
        authored_key="process",
        library_model=LibraryCrewConfig,
        authored_model=AuthoredCrewConfig,
        kind="crew",
    )


class ToolConfig(BuilderModel):
    """`tool` - one catalogue tool, attached to an agent or a crew.

    `tool_id` keys into the server-owned tool catalogue. It is an opaque id and
    never a module path, an import or a callable name: the whole reason a
    document cannot execute code is that every name it carries is looked up in a
    closed set the server owns, and a tool id is no exception.

    `params` is the tool's own configuration, flat like every other author-
    supplied mapping in this file. 06-tool-registry.md owns what a given
    `tool_id` accepts; this class owns only the shape.
    """

    tool_id: NodeId
    params: dict[str, JsonScalar] = Field(default_factory=dict)
    # The author's own key for tools that need one, by id. As on AgentConfig:
    # the id travels, the secret never enters a document.
    credential_id: CredentialId | None = None

    @field_validator("params")
    @classmethod
    def _validate_params(cls, value: dict[str, JsonScalar]) -> dict[str, JsonScalar]:
        return _checked_with_mapping(value, where="params")


class McpConfig(BuilderModel):
    """`mcp` - one MCP server, and WHICH of its tools this node exposes.

    `tool_names` is required to be non-empty by `bounds.py` rather than here,
    because an author who has added the server and not yet chosen its tools has
    made an incomplete graph, not an invalid document - and this file raises
    while `bounds.py` reports. The distinction is the difference between a
    problem you can see in the dock and a save that fails.

    07-mcp-client.md owns discovery, transports and which servers a deployment
    may reach at all.
    """

    server_id: NodeId
    tool_names: tuple[str, ...] = ()
    credential_id: CredentialId | None = None

    @field_validator("tool_names")
    @classmethod
    def _validate_tool_names(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("the same MCP tool is selected twice; list each once")
        return value


class SkillConfig(BuilderModel):
    """`skill` - one SKILL.md pack attached to an agent.

    A skill is knowledge, not hands: its name and description load at run start
    and its body loads only when a task matches, which is what lets an agent
    carry domain knowledge without carrying it in every prompt. 08-skills.md
    owns storage and the progressive-disclosure mechanism.
    """

    skill_id: NodeId


class GateConfig(BuilderModel):
    """`gate` - the pause an operator answers. Compiles to TWO flow methods.

    `max_turns` is a policy bound rather than a shape one, so it is checked in
    `bounds.py` against MAX_CYCLE_ITERATIONS: a revise loop through a gate IS a
    cycle, and an author who writes 9 should be told which bound they crossed
    and by how much, not handed a pydantic error.
    """

    message: str = Field(min_length=1, max_length=BUILDER_MAX_GATE_MESSAGE_CHARS)
    # The keys of the rendered payload the operator may edit. Everything else
    # is shown read-only, the way the verdict gate already prunes rather than
    # annotates a field the server would throw away.
    editable_fields: tuple[NodeId, ...] = ()
    max_turns: int = Field(default=1, ge=0)
    # Capped at the service's own gate timeout: a gate that claimed to stay
    # open longer than the service keeps it open would be a promise nothing
    # can keep.
    expiry_seconds: int = Field(
        default=VALIDATOR_GATE_TIMEOUT_SECONDS, ge=1, le=VALIDATOR_GATE_TIMEOUT_SECONDS
    )

    @field_validator("editable_fields")
    @classmethod
    def _validate_editable_fields(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("the same editable field is named twice; list each field once")
        return value


class RouterBranch(BuilderModel):
    """One declared way out of a router: a label, and one comparison.

    There is no expression here and there will not be one. `key` names a single
    state key and `op` is one of seven comparisons; an author who needs
    arithmetic writes a `transform` node whose six operations are equally
    closed. An expression surface is an evaluation surface.
    """

    label: NodeId
    op: str
    # The state key the comparison reads - a single flat key, because that is
    # the only shape measured resolving.
    key: NodeId | None = None
    value: JsonScalar = None

    @field_validator("op")
    @classmethod
    def _validate_op(cls, value: str) -> str:
        if value != BUILDER_ROUTER_OTHERWISE and value not in BUILDER_ROUTER_COMPARISONS:
            allowed = sorted(BUILDER_ROUTER_COMPARISONS | {BUILDER_ROUTER_OTHERWISE})
            raise ValueError(f"unknown router comparison {value!r}; use one of {', '.join(allowed)}")
        return value

    @model_validator(mode="after")
    def _validate_shape(self) -> RouterBranch:
        if self.op == BUILDER_ROUTER_OTHERWISE:
            if self.key is not None or self.value is not None:
                raise ValueError(
                    "the otherwise branch takes no key and no value: it is what happens "
                    "when every declared comparison missed"
                )
        elif self.key is None:
            raise ValueError(f"the {self.op} branch must name the state key it compares")
        return self

    @property
    def is_otherwise(self) -> bool:
        """Whether this is the branch an unmatched value goes forward on."""

        return self.op == BUILDER_ROUTER_OTHERWISE


class RouterConfig(BuilderModel):
    """`router` - a deterministic fork. No LLM, no author expression.

    The branch COUNT and the exactly-one-`otherwise` rule are enforced in
    `bounds.py`, not here: both are policy tied to MAX_FANOUT_WIDTH, and an
    author who drew five branches wants to be told the ceiling is four.
    """

    branches: tuple[RouterBranch, ...] = ()


class TransformConfig(BuilderModel):
    """`transform` - one of six fixed operations over `with:` data.

    Not billable, and not a code node. The six were chosen to cover what a
    canvas actually needs between two agents; there is no seventh, and no
    escape hatch, because a code node is the RCE surface the ten-ref allowlist
    exists to remove.
    """

    op: str
    args: dict[str, JsonScalar] = Field(default_factory=dict)

    @field_validator("op")
    @classmethod
    def _validate_op(cls, value: str) -> str:
        if value not in BUILDER_TRANSFORM_OPS:
            raise ValueError(
                f"unknown transform op {value!r}; the operations are "
                f"{', '.join(sorted(BUILDER_TRANSFORM_OPS))}"
            )
        return value

    @field_validator("args")
    @classmethod
    def _validate_args(cls, value: dict[str, JsonScalar]) -> dict[str, JsonScalar]:
        return _checked_with_mapping(value, where="args")


class OutputConfig(BuilderModel):
    """`output` - what the run hands back.

    `body_key` must be one of RUN_RESULT_BODY_KEYS, and that is not a formality:
    those keys are the ones that get MAX_RUN_RESULT_BODY_CHARS instead of the
    streaming frame's 4 KiB clip. A body written under any other key comes back
    truncated mid-sentence, which is exactly how the first paid run's report was
    lost.
    """

    body_key: str
    source: JsonScalar = None

    @field_validator("body_key")
    @classmethod
    def _validate_body_key(cls, value: str) -> str:
        if value not in RUN_RESULT_BODY_KEYS:
            raise ValueError(
                f"unknown result body key {value!r}; only {', '.join(RUN_RESULT_BODY_KEYS)} "
                "escapes the streaming frame clip, so a body written anywhere else is "
                "truncated before the operator sees it"
            )
        return value

    @field_validator("source")
    @classmethod
    def _validate_source(cls, value: JsonScalar) -> JsonScalar:
        return _checked_with_value(value, where="source")


NodeConfig = (
    InputConfig
    | LibraryAgentConfig
    | AuthoredAgentConfig
    | LibraryCrewConfig
    | AuthoredCrewConfig
    | GateConfig
    | RouterConfig
    | TransformConfig
    | OutputConfig
    | ToolConfig
    | McpConfig
    | SkillConfig
)

# One parser per kind. A CALLABLE rather than a class, because two kinds are
# unions whose arm is chosen by which key is present - see `_one_of`. The other
# eight parse to exactly one model and are spelled as that model's own
# `model_validate`, so the table stays a table.
_CONFIG_BY_KIND: dict[str, Callable[[object], BuilderModel]] = {
    "input": InputConfig.model_validate,
    "agent": _parse_agent_config,
    "crew": _parse_crew_config,
    "gate": GateConfig.model_validate,
    "router": RouterConfig.model_validate,
    "transform": TransformConfig.model_validate,
    "output": OutputConfig.model_validate,
    "tool": ToolConfig.model_validate,
    "mcp": McpConfig.model_validate,
    "skill": SkillConfig.model_validate,
}

# Which ports each kind offers, in the order the canvas draws them. `gate`'s
# two are the operator's decision; `router`'s are its declared branch labels
# and so are computed per node rather than listed here.
_OUT_PORTS_BY_KIND: dict[str, tuple[str, ...]] = {
    "input": ("out",),
    "agent": ("out",),
    "crew": ("out",),
    "gate": ("approve", "revise"),
    "transform": ("out",),
    "output": (),
    # An attachment has exactly one port and it is a SOURCE, which is the whole
    # asymmetry: the tool reaches toward the agent, never the other way. Drawing
    # it this way means `attach` is a property of the edge's TARGET port and the
    # edge class is a pure function of it - no second rule, no lookup of what the
    # source happened to be.
    "tool": ("attach",),
    "mcp": ("attach",),
    "skill": ("attach",),
}

# Kinds whose compiled form IS a router, and so the only kinds a back edge may
# leave from. `gate` qualifies because its second compiled method is the
# deterministic `route_gate`; the approve and revise ports are that router's
# declared labels. Everything else is a plain listener, and a plain listener
# closing a loop was MEASURED to end the run silently (the join never fires a
# second time, no exception, no warning).
ROUTING_KINDS: frozenset[str] = frozenset({"gate", "router"})

# The two families of `NodeKind`. Every kind is in exactly one, and
# `test_document.py` asserts that partition is total rather than trusting this
# comment - an eleventh kind added to only one set is the defect these exist to
# make impossible.
ATTACHMENT_KINDS: frozenset[str] = frozenset({"tool", "mcp", "skill"})
FLOW_KINDS: frozenset[str] = frozenset(
    {"input", "agent", "crew", "gate", "router", "transform", "output"}
)

# What an edge may arrive at. `in` is the flow itself; `attach` hangs a tool, an
# MCP server or a skill off an agent or crew; `member` puts an agent inside a
# crew. Only `in` existed before 03-node-library.md D1.
TARGET_PORTS: frozenset[str] = frozenset({"in", "attach", "member"})

# D1's target-port table, per kind and in the order the canvas draws them.
#
# `_OUT_PORTS_BY_KIND`'s mirror image, and the thing `GET /api/builder/vocabulary`
# publishes as `target_ports` so the client never has to hold a second copy.
# Four kinds take nothing: `input` starts the run, and the three attachments
# refuse an inbound edge because nothing flows INTO a possession.
_TARGET_PORTS_BY_KIND: dict[str, tuple[str, ...]] = {
    "input": (),
    "agent": ("in", "attach"),
    "crew": ("in", "attach", "member"),
    "gate": ("in",),
    "router": ("in",),
    "transform": ("in",),
    "output": ("in",),
    "tool": (),
    "mcp": (),
    "skill": (),
}

# Which target port class each source kind may reach along. An `attach` edge
# leaves an attachment and a `member` edge leaves an agent; `bounds.py` reports
# anything else rather than raising, because a wrongly-dropped edge is the most
# fixable position on a canvas there is.
ATTACH_SOURCE_KINDS: frozenset[str] = ATTACHMENT_KINDS
ATTACH_TARGET_KINDS: frozenset[str] = frozenset({"agent", "crew"})
MEMBER_SOURCE_KINDS: frozenset[str] = frozenset({"agent"})
MEMBER_TARGET_KINDS: frozenset[str] = frozenset({"crew"})

# Kinds that call a model, and so the ones MAX_BILLABLE_NODES counts.
BILLABLE_KINDS: frozenset[str] = frozenset({"agent", "crew"})


class BuilderNode(BuilderModel):
    """One node on the canvas: an id, a kind, a label, a position, a config."""

    id: NodeId
    kind: NodeKind
    label: Label
    position: Position = Position()
    config: NodeConfig

    @model_validator(mode="before")
    @classmethod
    def _parse_config_for_kind(cls, data: object) -> object:
        """Choose the per-kind config model from `kind` before validating it.

        A discriminated union cannot do this: the discriminator lives on the
        NODE, not inside `config`, and every config model would otherwise have
        to repeat its own kind. An unknown kind is left alone so the `kind`
        field itself reports it - naming the seven kinds is a better error than
        "no config model".
        """

        if not isinstance(data, dict):
            return data
        kind = data.get("kind")
        parse = _CONFIG_BY_KIND.get(kind) if isinstance(kind, str) else None
        config = data.get("config")
        if parse is None or isinstance(config, BuilderModel):
            return data
        return {**data, "config": parse(config if config is not None else {})}

    @property
    def is_billable(self) -> bool:
        """Whether this node calls a model, and so costs money to run."""

        return self.kind in BILLABLE_KINDS

    @property
    def tier(self) -> str | None:
        """The OpenRouter tier this node runs on, or None if it runs no model."""

        return getattr(self.config, "tier", None)

    @property
    def out_ports(self) -> tuple[str, ...]:
        """The ports an edge may leave from, in canvas order.

        Two kinds are not a table lookup. A `router`'s ports ARE its declared
        branch labels, and a billable node grows a second `error` port when its
        `on_error` says `route` - the one place in the schema where a port
        depends on a config field rather than on the kind.
        `nodeKinds.ts::outPortsOf` makes both exceptions the same way.
        """

        if self.kind == "router":
            assert isinstance(self.config, RouterConfig)
            return tuple(branch.label for branch in self.config.branches)
        ports = _OUT_PORTS_BY_KIND[self.kind]
        if getattr(self.config, "on_error", None) == "route":
            return (*ports, "error")
        return ports

    @property
    def target_ports(self) -> tuple[str, ...]:
        """The port classes an edge may arrive at, in canvas order (D1)."""

        return _TARGET_PORTS_BY_KIND[self.kind]

    @property
    def accepts_incoming(self) -> bool:
        """Whether an edge may arrive here at all.

        Four kinds refuse one, for two different reasons. `input` refuses because
        it is where the run starts. The three ATTACHMENT kinds refuse because
        nothing flows INTO a possession - an author who could draw an edge into a
        tool would be describing a step, and a tool is not a step.
        """

        return self.kind != "input" and self.kind not in ATTACHMENT_KINDS


class BuilderEdge(BuilderModel):
    """One drawn connection, from a named out port to a node's single in port."""

    id: NodeId
    source: NodeId
    # "out" for a single-output kind, "approve"/"revise" on a gate, or a
    # router's declared branch label. Checked against the SOURCE NODE's own
    # ports in `bounds.py`, which is the only place that knows both.
    source_port: NodeId = "out"
    target: NodeId
    # Every kind that accepts an edge accepts it on one port. A second inbound
    # port would be a join semantics this document deliberately does not have -
    # `joins` says how the arrivals combine, and the answer is always "all".
    # `in` is the flow edge every kind had before 03-node-library.md D1. `attach`
    # and `member` are structural: they say what a node HAS, not what happens
    # next. `bounds.py` excludes both from fan-out counting, from cycle detection
    # and from billable depth, because an agent holding three tools has not
    # branched three ways and a tool cannot be part of a loop.
    #
    # Edge CLASS is a pure function of this field and of nothing else, which is
    # what keeps the canvas's stroke rules and the server's bounds rules from
    # needing to agree about anything but one string.
    target_port: Literal["in", "attach", "member"] = "in"


class BuilderBudget(BuilderModel):
    """The compiler's static estimate, stored on the document it prices.

    Written by `budget.py`, never by the author. Admission reads the stored
    figure rather than recomputing it, so it is versioned with the document -
    a republish cannot race an in-flight admission read.
    """

    static_cost_usd: float = Field(ge=0.0)
    billable_nodes: int = Field(ge=0)
    escalation_nodes: int = Field(ge=0)
    cycles: int = Field(ge=0)
    compiled_at: datetime


class FlowStateField(BuilderModel):
    """One key of the flow's declared state, and what kind of value it holds."""

    type: ScalarType
    default: JsonScalar = None
    description: Label | None = None


class FlowStateSchema(BuilderModel):
    """`BuilderDocument.state` - the state keys a document declares up front.

    Optional, and its absence is the shape every v1 document has: state keys
    arrive implicitly, one `out__<node_id>` per node plus each input's field,
    seeded by `compiler.state_default`. Declaring them is what lets a router
    compare against a key no node writes yet, and what gives the inspector
    something to offer in a `${state.x}` picker instead of a free text box.

    Bounded by MAX_RUN_INPUT_KEYS rather than a new constant: these are keys a
    run request can seed, and two ceilings on one fact would drift apart.
    """

    fields: dict[NodeId, FlowStateField] = Field(default_factory=dict)

    @field_validator("fields")
    @classmethod
    def _validate_fields(cls, value: dict[str, FlowStateField]) -> dict[str, FlowStateField]:
        if len(value) > MAX_RUN_INPUT_KEYS:
            raise ValueError(
                f"this document declares {len(value)} state keys and the ceiling is "
                f"{MAX_RUN_INPUT_KEYS} (MAX_RUN_INPUT_KEYS), which is what a run request "
                "may carry"
            )
        return value


class BuilderDocument(BuilderModel):
    """One authored graph, at one version.

    Stored as a row keyed by `(id, version)`. The descriptor and the compiled
    `crewai.flow/v1` definition are derived from this and cached; nothing else
    is authoritative about what the author drew.
    """

    # `schema` is the wire spelling; the python name differs because a field
    # called `schema` shadows a BaseModel attribute and pydantic refuses the
    # model outright.
    document_schema: str = Field(default=BUILDER_DOCUMENT_SCHEMA, alias="schema")
    id: DocumentId
    name: str = Field(min_length=1, max_length=BUILDER_MAX_NAME_CHARS)
    # Monotonic. The graph ETag is derived from it, which is what lets a stored
    # budget and an in-flight admission read refer to the same graph.
    version: int = Field(ge=1)
    # Must equal exactly one `input` node's `field`. Cross-object, so
    # `bounds.py` checks it.
    input_field: NodeId
    nodes: tuple[BuilderNode, ...] = ()
    edges: tuple[BuilderEdge, ...] = ()
    joins: dict[str, str] = Field(default_factory=dict)
    # The declared state keys, or None for the implicit shape every v1 document
    # has. Optional rather than defaulted to an empty schema, so a stored row
    # that never carried the key round-trips byte-identical - the same reason
    # `upgrade_document` leaves a missing `schema` missing.
    state: FlowStateSchema | None = None
    budget: BuilderBudget | None = None

    @field_validator("document_schema")
    @classmethod
    def _validate_schema(cls, value: str) -> str:
        if value != BUILDER_DOCUMENT_SCHEMA:
            raise ValueError(
                f"unknown document schema {value!r}; this service compiles "
                f"{BUILDER_DOCUMENT_SCHEMA}"
            )
        return value

    @field_validator("joins")
    @classmethod
    def _validate_joins(cls, value: dict[str, str]) -> dict[str, str]:
        """`joins` values are "all" or "any", and nothing else (D3, FD5).

        **"any" was refused by name until 03-node-library.md D3**, and the
        reason it is admitted now is worth reading before anybody re-tightens
        it. The measured failure was real: a multi-event `or_()` listener is
        added to `_fired_or_listeners` the first time it fires and skipped
        forever after, so the second arrival ends the run silently. But that is
        a fact about `or_()` over a MULTI-EVENT condition, and it is not what
        `"any"` compiles to here - `compiler._listen_for` builds the
        alternatives shape, where each alternative is a router label, only one
        fires per pass, and CrewAI re-arms an or-listener whose condition names
        the label a router just emitted. That is precisely what "the first
        arrival wins" means, and it is what lets a router's mutually exclusive
        branches converge on one node instead of waiting forever for the branch
        that was not taken.

        So the two words mean two different compiled shapes and both are safe:
        `"all"` is `{"and": [...]}`, `"any"` is the alternatives. A third word
        is neither, and is still refused here rather than reported, because
        there is nothing on the canvas to drag.
        """

        for node_id, mode in value.items():
            if mode not in ("all", "any"):
                raise ValueError(
                    f"joins[{node_id!r}] is {mode!r}; a join is \"all\" - every incoming "
                    "edge must arrive before the node runs - or \"any\", where the first "
                    "arrival runs it and the rest are alternatives that never fire"
                )
        return value

    def nodes_by_id(self) -> dict[str, BuilderNode]:
        """Nodes keyed by id, last one winning on a duplicate.

        A plain method rather than a cached property: the model is frozen and a
        duplicate id is a Problem `bounds.py` reports rather than an error this
        raises, so callers need a map that exists even when the document is
        wrong.
        """

        return {node.id: node for node in self.nodes}
