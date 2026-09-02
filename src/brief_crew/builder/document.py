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
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

from brief_crew.config import (
    BUILDER_DOCUMENT_ID_PATTERN,
    BUILDER_DOCUMENT_SCHEMA,
    BUILDER_ID_PATTERN,
    BUILDER_MAX_AGENT_ITER,
    BUILDER_MAX_GATE_MESSAGE_CHARS,
    BUILDER_MAX_GUARDRAIL_RETRIES,
    BUILDER_MAX_LABEL_CHARS,
    BUILDER_MAX_NAME_CHARS,
    BUILDER_ROUTER_COMPARISONS,
    BUILDER_ROUTER_OTHERWISE,
    BUILDER_STATE_REF_PATTERN,
    BUILDER_TRANSFORM_OPS,
    BUILDER_RESEARCH_TOOLS,
    MAX_RUN_INPUT_CHARS,
    RUN_RESULT_BODY_KEYS,
    VALIDATOR_BRANCH_MAX_ITER,
    VALIDATOR_GATE_TIMEOUT_SECONDS,
)

# The seven kinds, and there is no eighth. Section B of the locked spec derives
# each one's compiled shape; `gate` is the only kind that compiles to two flow
# methods, which is a fact `bounds.py` has to know when it generates idents.
NodeKind = Literal["input", "agent", "crew", "gate", "router", "transform", "output"]

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
Label = Annotated[str, StringConstraints(min_length=1, max_length=BUILDER_MAX_LABEL_CHARS)]

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

    @field_validator("prompt_inputs")
    @classmethod
    def _validate_prompt_inputs(cls, value: dict[str, JsonScalar]) -> dict[str, JsonScalar]:
        return _checked_with_mapping(value, where="prompt_inputs")


class AgentConfig(_BillableConfig):
    """`agent` - one allowlisted YAML agent, on one tier, with bound tools.

    `agent_id` keys into the YAML agent registry rather than carrying a role,
    goal or backstory, because prompts live in YAML and a document that carried
    them would be a second place they live.
    """

    agent_id: NodeId
    tools: tuple[str, ...] = ()

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


class CrewConfig(_BillableConfig):
    """`crew` - one registered `@CrewBase`, run whole.

    Identical to `agent` but for the id and the absence of `tools`: a crew's
    tools are declared by the crew, and letting a document override them would
    move tool binding out of `config.py`'s reach.

    `tier` is declared rather than derived because the document is priced
    before anything is constructed. An author must name the ESCALATION-most
    tier the crew's agents run on, and `bounds.py` counts it against
    MAX_ESCALATION_NODES on that word alone.
    """

    crew_id: NodeId


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
    | AgentConfig
    | CrewConfig
    | GateConfig
    | RouterConfig
    | TransformConfig
    | OutputConfig
)

_CONFIG_BY_KIND: dict[str, type[BuilderModel]] = {
    "input": InputConfig,
    "agent": AgentConfig,
    "crew": CrewConfig,
    "gate": GateConfig,
    "router": RouterConfig,
    "transform": TransformConfig,
    "output": OutputConfig,
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
}

# Kinds whose compiled form IS a router, and so the only kinds a back edge may
# leave from. `gate` qualifies because its second compiled method is the
# deterministic `route_gate`; the approve and revise ports are that router's
# declared labels. Everything else is a plain listener, and a plain listener
# closing a loop was MEASURED to end the run silently (the join never fires a
# second time, no exception, no warning).
ROUTING_KINDS: frozenset[str] = frozenset({"gate", "router"})

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
        model = _CONFIG_BY_KIND.get(kind) if isinstance(kind, str) else None
        config = data.get("config")
        if model is None or isinstance(config, BuilderModel):
            return data
        return {**data, "config": model.model_validate(config if config is not None else {})}

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
        """The ports an edge may leave from, in canvas order."""

        if self.kind == "router":
            assert isinstance(self.config, RouterConfig)
            return tuple(branch.label for branch in self.config.branches)
        return _OUT_PORTS_BY_KIND[self.kind]

    @property
    def accepts_incoming(self) -> bool:
        """Whether an edge may arrive here at all. Only `input` refuses one."""

        return self.kind != "input"


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
    target_port: Literal["in"] = "in"


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
        """`joins` values must be "all", and "any" is refused by name.

        This is the one policy rule enforced at parse time rather than reported
        as a Problem, because there is nothing for the author to adjust. A
        multi-event `or_()` listener is added to `_fired_or_listeners` the first
        time it fires and skipped forever after, so the SECOND time a branch
        completes the flow ends normally having produced nothing: no exception,
        no warning, no frame. Measured, both ways round.
        """

        for node_id, mode in value.items():
            if mode == "any":
                raise ValueError(
                    f"joins[{node_id!r}] is \"any\", which this schema does not have. "
                    "A multi-event or_() listener fires once per kickoff and is suppressed "
                    "afterwards, so the second arrival ends the run silently having produced "
                    "nothing. Use \"all\", and close a loop with a router instead"
                )
            if mode != "all":
                raise ValueError(
                    f"joins[{node_id!r}] is {mode!r}; the only supported join is \"all\", "
                    "meaning every incoming edge must arrive before the node runs"
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
