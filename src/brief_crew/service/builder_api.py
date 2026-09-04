"""`/api/builder/*` - list, load, save, validate and publish a canvas graph.

A separate router rather than more routes in `create_app`, for one reason that
is measured rather than stylistic: `GET /api/workflows` must keep returning the
two literals `[BRIEF_WORKFLOW, VALIDATOR_WORKFLOW]`. That literal is the only
thing keeping `test_validator_service`'s set equality true, and relaxing it to
make room for builder graphs would be a weakening of an assertion that is
correct. Builder graphs are listed here instead, which costs nothing.

**The two request bounds, and the honest answer to the 64 KiB question.** The
ASGI-edge check refuses any body over `MAX_REQUEST_BODY_BYTES` (64 KiB), and a
24-node document with positions, labels, prompts and router rules is
legitimately bigger than that. Raising the global bound is the wrong fix - a
megabyte of `inputs` on the RUN endpoint would still be a cost - so this prefix
gets its own exemption at `MAX_BUILDER_DOCUMENT_BYTES` (256 KiB) and the
handlers below re-check the parsed document's own serialised size. Both halves
are needed: the middleware reads the declared `Content-Length`, and a chunked
request declares none.

Nothing here executes a flow. `publish` compiles and registers; the run itself
goes through the same `POST /api/sessions/{id}/runs` every other workflow uses,
with the same admission control, the same rate limit and the same ownership.
"""

# NO `from __future__ import annotations` here, and it is load-bearing rather
# than an omission - `service/app.py` leaves it out for the same reason.
# FastAPI resolves a handler's annotations with `get_type_hints` against the
# MODULE globals, and `Response`, `Query` and `Depends` are imported inside
# `create_builder_router` because FastAPI is an optional dependency. Stringised
# annotations would therefore fail to resolve those names, silently fall back
# to `Any`, and turn a 204 into an assertion about response bodies.

from collections.abc import Iterable, Mapping
from datetime import datetime
import json
import re
import typing
from typing import Any, Callable, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from brief_crew import config as project_config
from brief_crew.builder import BudgetEstimate, Problem, estimate_budget, registry_document
# `document_problems` and never `validate_document`: the second answers about
# structure and price only, and an author who names a crew this deployment
# cannot construct has to be told here rather than at the moment Publish
# refuses a document the canvas has been calling clean all afternoon.
from brief_crew.builder.compiler import (
    BuilderCompileError,
    compile_document,
    document_problems,
)
from brief_crew.builder.preview import render_preview
from brief_crew.builder.descriptor import (
    BuilderWorkflow,
    build_builder_workflow,
    builder_graph_descriptor,
    static_cost_over_ceiling,
)
from brief_crew.builder.document import (
    ATTACHMENT_KINDS,
    BuilderDocument,
    NodeKind,
    Tier,
    _TARGET_PORTS_BY_KIND as TARGET_PORTS_BY_KIND,
)
# Plans 06, 07 and 08. Imported by module-qualified alias where a bare name
# would collide with something already in this file (`catalogue`, `discover`,
# `mask_url`), because a rename inside a route body is the kind of edit that
# reads as correct and binds the wrong function.
from brief_crew.builder.mcp import (
    MCP_TRANSPORT_DISALLOWED,
    discover as mcp_discover,
    mask_url as mask_mcp_url,
    mcp_problems,
    transport_refusal,
)
from brief_crew.builder.skills import (
    SkillError,
    load_builtins as builtin_skill_packs,
    read_pack_zip,
    skill_problems,
)
from brief_crew.builder.tools import (
    CustomToolError,
    build_custom_tool,
    catalogue as tool_catalogue,
    parse_custom_tool,
    tool_problems,
)
from brief_crew.builder.export import (
    export_content_disposition,
    export_envelope,
    nulled_reference_nodes,
    strip_for_export,
)
from brief_crew.builder.runtime import BUILDABLE_BUILDER_CREW_IDS, BUILDER_AGENT_LIBRARY
from brief_crew.service.credentials import CredentialStore
from brief_crew.service.attachments import (
    AttachmentNotYours,
    CustomToolStore,
    McpServerStore,
    NameTaken,
    SkillBodyUnreadable,
    SkillStore,
    TooManyRows,
)
from brief_crew.builder.store import (
    BuilderDocumentStore,
    BuilderStoreError,
    BuilderTestInputStore,
    DEFAULT_LIST_LIMIT,
    DocumentNotFound,
    DocumentReadOnly,
    DocumentTooLarge,
    DocumentVersionConflict,
    STATUS_PUBLISHED,
    StoredDocument,
    TestInput,
    TestInputLimitReached,
    TestInputNotFound,
    VersionHistory,
    new_document_id,
)
from brief_crew.builder.upgrade import KNOWN_SCHEMAS, upgrade_document
from brief_crew.service.graph import (
    builder_workflow as registered_workflow,
    register_builder_workflow,
    unregister_builder_workflow,
)
from brief_crew.service.models import (
    GraphDescriptor,
    TestInputModel,
    TestInputRequest,
)
from brief_crew.service.registry import RunRegistry, WorkflowRuntime
from brief_crew.service.builder_runner import BuilderRunnerFactory
from brief_crew.service.runner import Runner


#: The ten kinds and the two tiers, read off the CLOSED unions themselves.
#: `typing.get_args` preserves declaration order, which is the order the
#: palette renders - flow kinds first, attachments last.
NODE_KINDS: tuple[str, ...] = typing.get_args(NodeKind)
TIERS: tuple[str, ...] = typing.get_args(Tier)

#: Every route in this module hangs off this, and so does the body-size
#: exemption in `create_app`. One constant, so the two cannot disagree.
BUILDER_API_PREFIX = "/api/builder"

#: The version a brand new document is created at. Locked spec C says the
#: version is monotonic and the ETag is derived from it, so it starts at the
#: schema's own floor rather than at zero.
FIRST_VERSION = 1

#: What a duplicate is called. Appended, and the base is trimmed to make room
#: rather than the suffix dropped, because a copy that cannot be told from its
#: source in the sidebar is the one thing a duplicate must not be.
#: Owned by config.py (S1 ruling 3); re-exported under the same name.
COPY_SUFFIX = project_config.COPY_SUFFIX
IMPORT_SUFFIX = project_config.IMPORT_SUFFIX

#: How many `needs_credentials` entries an import envelope may name. A node id
#: per graph node is the most a strip can produce; anything beyond that is a
#: file that was not written by an export. Owned by config.py.
MAX_IMPORT_NEEDS_CREDENTIALS = project_config.MAX_IMPORT_NEEDS_CREDENTIALS


class BuilderServiceUnavailable(RuntimeError):
    """This build cannot host a builder graph's runtime, so publish is refused.

    Raised in exactly one place - `_register_runtime`, when the registry is the
    older single-workflow shape with no `workflows` map to put a graph into. The
    routes are still mounted, so the refusal is a **503** naming the reason
    rather than a 404 that reads as "this feature does not exist"; the sibling
    refusal, `require_store`'s missing document store, already answers 503 and
    these two are the same sentence to whoever is holding the browser.

    It says 503 because it was NOT saying 503: nothing caught it, so a publish
    against such a registry came back as an unhandled 500 - a service defect, on
    a request the service understood perfectly and had a good reason to refuse.
    A RuntimeError rather than an HTTPException at the raise site because
    `builder_rehydrate` calls the same function at boot, where there is no
    request to answer and an HTTP exception would be a category error.
    """


# --------------------------------------------------------------------------
# Wire models
#
# Declared here rather than in `service/models.py` because every one of them is
# builder-only, and `models.py` is the boundary the two hand-written flows
# share. The one thing that DOES belong there - the per-workflow reserved-key
# check on `CreateRunRequest.inputs` - is there.
# --------------------------------------------------------------------------
class BuilderProblemModel(BaseModel):
    """One reason a document may not be published, as the canvas shows it."""

    model_config = ConfigDict(extra="forbid")

    code: str
    severity: str
    message: str
    #: The canvas selects and centres this node when the entry is clicked,
    #: which is the whole reason a Problem carries an id rather than prose.
    node_id: str | None = None
    edge_id: str | None = None
    #: C8's optional `field`: which control on the open inspector this problem
    #: is about, when the code alone cannot say. See `bounds.Problem.field`.
    field: str | None = None

    @classmethod
    def of(cls, problem: Problem) -> "BuilderProblemModel":
        return cls(
            code=problem.code,
            severity=problem.severity,
            message=problem.message,
            node_id=problem.node_id,
            edge_id=problem.edge_id,
            field=problem.field,
        )


class BuilderNodeCostModel(BaseModel):
    """One billable node's contribution to the graph's static price."""

    model_config = ConfigDict(extra="forbid")

    calls: int
    usd: float
    #: What it was priced AT, which is not always what it names: a node with a
    #: `retry.fallback_model` is priced at the dearer of the two (09 D4).
    model_id: str


class BuilderBudgetModel(BaseModel):
    """The static price of a graph, and whether it may be launched at all.

    `floor_cost_usd` sits beside the enforced figure deliberately: the enforced
    one has `NITRO_PRICE_FACTOR` applied to every cheap-tier node, so it is
    higher than any number an operator will see on an invoice, and showing only
    that would look like an error. The floor is the same graph at published
    prices, which is the figure a real run is comparable with.
    """

    model_config = ConfigDict(extra="forbid")

    static_cost_usd: float
    floor_cost_usd: float
    modelled_calls: int
    billable_nodes: int
    escalation_nodes: int
    cycles: int
    unpriced_models: list[str]
    #: `static_cost_usd * GRAPH_STATIC_BUDGET_MARGIN` against MAX_RUN_COST_USD.
    over_ceiling: bool
    ceiling_usd: float
    #: Per-node calls, dollars and the model each was priced at (C5, requested
    #: by 04 for the inspector's cost line). The SAME figures the total above
    #: sums, exposed rather than recomputed on the client: R6 stands, and two
    #: arithmetics for one number is how a meter and a refusal come to disagree.
    per_node: dict[str, "BuilderNodeCostModel"] = {}

    @classmethod
    def of(cls, estimate: BudgetEstimate) -> "BuilderBudgetModel":
        return cls(
            static_cost_usd=estimate.static_cost_usd,
            floor_cost_usd=estimate.floor_cost_usd,
            modelled_calls=estimate.modelled_calls,
            billable_nodes=estimate.billable_nodes,
            escalation_nodes=estimate.escalation_nodes,
            cycles=estimate.cycles,
            unpriced_models=list(estimate.unpriced_models),
            over_ceiling=static_cost_over_ceiling(estimate.static_cost_usd),
            ceiling_usd=float(project_config.MAX_RUN_COST_USD),
            per_node={
                node_id: BuilderNodeCostModel(
                    calls=cost.calls, usd=cost.usd, model_id=cost.model
                )
                for node_id, cost in estimate.per_node.items()
            },
        )


class BuilderDocumentRequest(BaseModel):
    """A document on its way in, with the version the author was editing.

    `document` stays an untyped mapping on purpose. `BuilderDocument` is the
    schema, and parsing it HERE would give FastAPI's own 422 - an error list
    that echoes the offending input back and names pydantic locations rather
    than nodes. The handlers parse it themselves so a bad document comes back
    as the same problem list the canvas already knows how to draw.
    """

    model_config = ConfigDict(extra="forbid")

    document: dict[str, Any]
    #: Required on a save, ignored on a create and on a validate. The server
    #: assigns the new version; this says which one it is replacing.
    expected_version: int | None = Field(default=None, ge=0)
    #: How this save came about, for the version browser (round 2, D-15-3):
    #: one of `BUILDER_VERSION_SAVE_SOURCES`, or absent, which reads as a plain
    #: save. The server composes the stored string - see `_version_source`.
    source: Literal["save", "autosave", "restore"] | None = None
    #: The version a `restore` put back, so the row can say "restored from v3".
    restored_from: int | None = Field(default=None, ge=1)


class BuilderDocumentSummaryModel(BaseModel):
    """One row of the sidebar: enough to pick a graph, nothing to parse."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    version: int
    status: str
    created_at: datetime
    updated_at: datetime


class BuilderDocumentModel(BaseModel):
    """One document, with everything the canvas needs to draw and judge it."""

    model_config = ConfigDict(extra="forbid")

    id: str
    #: The document exactly as stored, by its wire spelling - `schema`, not
    #: `document_schema`. What goes out is what may be sent back.
    document: dict[str, Any]
    status: str
    version: int
    head_version: int
    created_at: datetime
    updated_at: datetime
    problems: list[BuilderProblemModel]
    budget: BuilderBudgetModel
    #: The graph as the console renders it. Included on a load so the canvas
    #: has one request rather than two, and so a DRAFT can be drawn at all -
    #: `GET /api/workflows/{id}/graph` only answers for a published graph.
    graph: GraphDescriptor
    #: True when this exact version is the one registered on this service.
    published: bool


class BuilderImportedDocumentModel(BuilderDocumentModel):
    """A `create` response plus the nodes the file said lost a credential.

    The same shape as `POST /workflows` on purpose (S1 ruling 7): the client
    already knows how to open that, and an import IS a create with one extra
    fact attached. The extra fact is a list of node ids rather than a problem
    code, because C8's union is a Python-generated mirror and the only
    server-side `credential-missing` belongs to `validate` (plan 01 D10).
    """

    needs_credentials: list[str]


class BuilderImportRequest(BaseModel):
    """A `.builder.json` on its way in - the D1 envelope, verbatim.

    `document` is untyped for the reason `BuilderDocumentRequest` gives; the
    handler parses it so the refusal is a sentence naming a node rather than
    pydantic's echo of a quarter-megabyte file. `export` is checked by name
    against the two schema strings this service reads or will read (ruling 4);
    everything else on the envelope is informational and the importer minted
    its own id, version and owner before any of it is looked at. In particular
    `needs_credentials` is accepted so the file the export wrote round-trips
    unchanged, and then IGNORED: the answer's list is re-derived from the
    document itself, never copied from the client.
    """

    model_config = ConfigDict(extra="forbid")

    export: str = Field(min_length=1, max_length=64)
    document: dict[str, Any]
    exported_at: str | None = Field(default=None, max_length=64)
    name: str | None = Field(default=None, max_length=project_config.BUILDER_MAX_NAME_CHARS)
    source_version: int | None = Field(default=None, ge=0)
    needs_credentials: list[str] = Field(
        default_factory=list, max_length=MAX_IMPORT_NEEDS_CREDENTIALS
    )


class BuilderVersionModel(BaseModel):
    """One row of the version browser.

    Round 1 (D-15-3) found two rows that read "3 Sept, 00:19 · DRAFT" and
    differed by 0.2 KB in 11px text, so choosing which to restore was
    guesswork. Three facts were added: `name` and `node_count` read leniently
    off the stored row (the label), and `source` from the column of the same
    round (how the row came to be). The relative time is the client's, from
    `created_at`, which already carried seconds.
    """

    model_config = ConfigDict(extra="forbid")

    version: int
    #: `published` for the version this service is running or the head that
    #: was published; `draft` for every other version. A version has no status
    #: column of its own - see `store.VersionHistory`.
    status: str
    created_at: datetime
    bytes: int
    #: `created`, `saved`, `autosaved`, `restored from v3`, `imported`,
    #: `duplicated` - or `stored`, for a row older than the column.
    source: str
    #: The document's name at that version; None when the row cannot say.
    name: str | None
    #: How many nodes that version has; None when the row cannot say.
    node_count: int | None
    #: How many edges that version has; None when the row cannot say. The
    #: browser subtracts adjacent rows into `+2 nodes, -1 edge` (D-15-24); a
    #: delta over nodes alone would report a rewiring as no change at all.
    edge_count: int | None


class BuilderValidationModel(BaseModel):
    """What a document would be told if it were saved right now."""

    model_config = ConfigDict(extra="forbid")

    valid: bool
    problems: list[BuilderProblemModel]
    budget: BuilderBudgetModel
    #: False when the caller had no identity to check credential references
    #: against (plan 01 D10), so `credential-missing` may still appear at
    #: publish. Reported rather than passed off as a clean answer.
    identity_checked: bool


class BuilderPublishModel(BaseModel):
    """What was registered, and under what terms it may be launched."""

    model_config = ConfigDict(extra="forbid")

    workflow_id: str
    graph_version: str
    version: int
    input_field: str
    static_cost_usd: float
    #: False when a billable node is reachable from the input without passing a
    #: gate. An anonymous launch of such a graph is refused unless
    #: BUILDER_ALLOW_GATELESS_GRAPHS is set - see `create_run`.
    gated_before_spend: bool
    reserved_input_keys: list[str]


class CompiledPreviewModel(BaseModel):
    """C7's `compiled` response - 09 D8's two renderings, plus the definition.

    All three, rather than a choice, because they answer three questions and a
    round trip per question is a round trip too many on a panel an author opens
    to check one thing: the YAML is what runs, the Python is what it means, and
    the definition is what a client would diff against a previous version.
    """

    model_config = ConfigDict(extra="forbid")

    document_id: str
    version: int
    generated_at: datetime
    yaml: str
    python: str
    definition: dict[str, Any]


class BuilderVocabularyModel(BaseModel):
    """Everything the palette and the config panel are allowed to offer - C2.

    Served rather than duplicated in TypeScript, for the reason
    `data/serverLimits.ts` already documents about `MAX_RUN_INPUT_CHARS`: a
    canvas offering a transform op the compiler does not have is a 422 the
    author cannot act on, and a canvas missing one is a feature nobody can
    reach.

    **Every list here is DERIVED, never a literal.** `node_kinds` was a
    seven-element literal until 2026-09-04 and the ten-kind vocabulary had
    already landed in `document.py`, so the palette drew seven tiles against a
    server that understood ten - the exact class of drift this endpoint exists
    to remove, committed inside the endpoint itself. Everything below reads its
    own owning source.
    """

    model_config = ConfigDict(extra="forbid")

    schema_id: str
    node_kinds: list[str]
    #: The three kinds that are possessions rather than steps. A subset of
    #: `node_kinds`, sent separately because "is this an attachment" is the
    #: first question the canvas asks about a kind and deriving it client-side
    #: would be a fourth copy of the partition.
    attachment_kinds: list[str]
    #: D1's target-port table, per kind. Four kinds map to an empty list, which
    #: is not the same as absent: `input` starts the run and the three
    #: attachments refuse an inbound edge.
    target_ports: dict[str, list[str]]
    tiers: list[str]
    #: The model each tier resolves to, WITHOUT the `openrouter/` prefix and
    #: without a `:nitro` variant - the slug a registry entry (C3) is keyed by,
    #: so `tier_models[t]` can be looked up in `models` once plan 05 lands.
    tier_models: dict[str, str]
    agent_ids: list[str]
    crew_ids: list[str]
    research_tools: list[str]
    #: Plan 06 D1's catalogue, served so the palette and the inspector never
    #: hold a copy (cut-list 17). `research_tools` above stays exactly as it
    #: was: it is the three repo tools an `agent` node's own checklist binds,
    #: and the attachment model is additive to it rather than a replacement.
    #: Plan 06's Status asks for that field to GO AWAY; that is a C2 change, and
    #: removing a key the client already reads is the Integrator's call.
    tools: list[dict[str, Any]]
    transform_ops: list[str]
    router_comparisons: list[str]
    router_otherwise: str
    result_body_keys: list[str]
    #: C8's union, read from the three modules that DECLARE the codes rather
    #: than transcribed. The client mirrors it in `types/builder.ts` and
    #: `tests/builder/test_problem_code_declarations.py` is what keeps the two
    #: equal; serving it as well is what lets a runtime check notice a mirror
    #: that went stale between deploys.
    problem_codes: list[str]
    warning_codes: list[str]
    bounds: dict[str, float]


class BuilderRegistryModel(BaseModel):
    """One roster row, C3 verbatim - plan 05.

    Every field is a catalogue fact measured by `scripts/refresh_models.py`, and
    the two price columns are both here on purpose. `cost_in` is what a run is
    PRICED at. `cost_in_max_endpoint` is the dearest endpoint serving the same
    slug, and it is the figure that says how much exposure `provider.max_price`
    is filtering away - `google/gemini-3.8-flash` bills $0.75 on its headline
    and $1.35 on its two `priority` endpoints. Reporting one column without the
    other is what let a `:batch` price be read as a headline once already.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    provider: str
    context_window: int
    supports_tools: bool
    supports_vision: bool
    supports_json_mode: bool
    supports_reasoning: bool
    cost_in: float
    cost_out: float
    cost_in_max_endpoint: float
    speed_tier: str
    recommended_for: list[str]


class BuilderModelsModel(BaseModel):
    """`GET /api/builder/models` - the roster, its ceiling and its two presets.

    `generated_at` and `source` are served with the rows because they are what a
    stale client is diagnosed FROM. A browser holding a session-cached roster can
    say when the copy it has was measured; comparing prices would only ever tell
    it that two numbers differ, never which one is old.
    """

    model_config = ConfigDict(extra="forbid")

    schema_id: str = Field(alias="schema")
    generated_at: str
    source: str
    ceiling_usd_per_m_input: float
    #: Tier name to the model id that tier resolves to, WITH its routing variant
    #: - `google/gemini-3.5-flash-lite:nitro`. The variant is part of how the
    #: cheap preset is billed (nitro routes on speed, so its published rate is a
    #: floor), so stripping it here would hide the one fact the picker needs to
    #: explain why the cheap preset's enforced price is above its headline.
    presets: dict[str, str]
    models: list[BuilderRegistryModel]


def _problem_code_union() -> tuple[list[str], list[str]]:
    """Every problem code and every warning code, from their owning modules.

    FOUR modules since 2026-09-04: `registry.py` joined with plan 05's three
    model codes. A module missing here is a code the runtime never advertises,
    which is how a canvas ends up rendering nothing for a refusal the server
    keeps sending.

    Imported rather than grepped. `test_problem_code_declarations.py` already
    guarantees the two agree - it parses the same modules with the frontend's
    own regex and compares against the AST - so importing here is reading the
    same set by the cheaper route, and it cannot go stale relative to a
    constant that was renamed.
    """

    from brief_crew.builder import bounds as bounds_module
    from brief_crew.builder import budget as budget_module
    from brief_crew.builder import compiler as compiler_module
    from brief_crew.builder import registry as registry_module

    from brief_crew.builder import mcp as mcp_module
    from brief_crew.builder import skills as skills_module
    from brief_crew.builder import tools as tools_module

    codes: set[str] = set()
    # Plans 06, 07 and 08 declare their own codes in their own modules, in the
    # module-level shape the client's grep looks for. Every declaring file is
    # named in `test_problem_code_declarations.py`, `builderTypes.spec.ts` and
    # `scripts/emit_builder_fixtures.py`; they all move together, or the canvas
    # renders a code it has never heard of.
    for module in (bounds_module, budget_module, compiler_module, registry_module, tools_module, mcp_module, skills_module):
        for name, value in vars(module).items():
            if name.isupper() and isinstance(value, str) and _PROBLEM_CODE.match(value):
                codes.add(value)
    warnings = {
        bounds_module.ROUTER_BRANCH_UNCONNECTED,
        bounds_module.NO_OUTPUT_NODE,
        bounds_module.JOIN_SINGLE_PREDECESSOR,
        bounds_module.ATTACHMENT_UNATTACHED,
        # The fifth: a discovered MCP tool description that matched one of the
        # thirteen injection patterns. A warning and not an error because the
        # list has false positives by design - "act as" is ordinary English -
        # and PLANS.md decision 8 rules that the author decides with eyes open.
        mcp_module.MCP_TOOL_DESCRIPTION_SUSPICIOUS,
    }
    return sorted(codes), sorted(warnings)


def _models_etag() -> str:
    """A strong ETag for the roster: the SHA-256 of `data/models.json`.

    Of the FILE, not of the response body. The file is the thing
    `refresh_models.py` rewrites and the thing a commit shows a diff of, so a
    tag taken from it moves exactly when the roster moves - where a hash of the
    serialised response would also move if a key order changed, inventing a
    cache miss out of a refactor.

    Read per request rather than computed once at import, because both Render
    services carry `autoDeploy: yes` and a process can outlive the file it
    started with. It is a few kilobytes off the page cache.
    """

    import hashlib

    digest = hashlib.sha256(project_config.MODEL_REGISTRY_PATH.read_bytes()).hexdigest()
    return f'"{digest}"'


#: A problem code, by the shape the frontend's own grep looks for. The
#: `isupper()` filter above would otherwise sweep up every unrelated string
#: constant in three modules.
_PROBLEM_CODE = re.compile(r"^[a-z]+(?:-[a-z]+)+$")


def _tier_models() -> dict[str, str]:
    """`cheap` and `escalation` as the REGISTRY spells them (C3).

    Two transformations, and both are the reason this is derived rather than
    written down: `config.py` carries `openrouter/google/gemini-3.5-flash-lite:nitro`,
    where `openrouter/` is the provider prefix CrewAI strips for a native
    provider and `:nitro` is a routing variant rather than a different model.
    A registry keyed on either spelling would miss.
    """

    def slug(model: str) -> str:
        return model.removeprefix("openrouter/").split(":", 1)[0]

    return {
        "cheap": slug(project_config.CHEAP_MODEL),
        "escalation": slug(project_config.ESCALATION_MODEL),
    }


def _vocabulary() -> BuilderVocabularyModel:
    problem_codes, warning_codes = _problem_code_union()
    return BuilderVocabularyModel(
        # Derived, so the day `BUILDER_DOCUMENT_SCHEMA` becomes v2 the palette
        # follows without an edit here. The client refuses a `schema_id` it does
        # not write, which is what makes serving anything but this constant a
        # console that disables itself.
        schema_id=project_config.BUILDER_DOCUMENT_SCHEMA,
        # `typing.get_args(NodeKind)`, in the ORDER the Python declares - flow
        # kinds first, attachments last - because the palette renders the list
        # as it arrives. Never a literal: see the class docstring.
        node_kinds=list(NODE_KINDS),
        attachment_kinds=[kind for kind in NODE_KINDS if kind in ATTACHMENT_KINDS],
        target_ports={kind: list(ports) for kind, ports in TARGET_PORTS_BY_KIND.items()},
        tiers=list(TIERS),
        tier_models=_tier_models(),
        problem_codes=problem_codes,
        warning_codes=warning_codes,
        agent_ids=sorted(BUILDER_AGENT_LIBRARY),
        # The BUILDABLE ones, not every registered class: `synthesis` and
        # `report` are refused by `library_problems`, so offering them in a
        # picker would be advertising a document that cannot publish.
        crew_ids=sorted(BUILDABLE_BUILDER_CREW_IDS),
        research_tools=sorted(project_config.BUILDER_RESEARCH_TOOLS),
        # Declaration order, not sorted: the palette groups by `category` and
        # renders each group in arrival order, so the catalogue's own ordering
        # is a decision and alphabetising it would silently discard one.
        tools=[entry.serialisable() for entry in tool_catalogue()],
        transform_ops=sorted(project_config.BUILDER_TRANSFORM_OPS),
        router_comparisons=sorted(project_config.BUILDER_ROUTER_COMPARISONS),
        router_otherwise=project_config.BUILDER_ROUTER_OTHERWISE,
        result_body_keys=list(project_config.RUN_RESULT_BODY_KEYS),
        bounds={
            "max_graph_nodes": project_config.MAX_GRAPH_NODES,
            "max_billable_nodes": project_config.MAX_BILLABLE_NODES,
            "max_escalation_nodes": project_config.MAX_ESCALATION_NODES,
            "max_fanout_width": project_config.MAX_FANOUT_WIDTH,
            "min_router_branches": project_config.MIN_ROUTER_BRANCHES,
            "max_cycles": project_config.MAX_CYCLES,
            "max_cycle_iterations": project_config.MAX_CYCLE_ITERATIONS,
            "max_agent_iter": project_config.BUILDER_MAX_AGENT_ITER,
            "max_guardrail_retries": project_config.BUILDER_MAX_GUARDRAIL_RETRIES,
            "max_label_chars": project_config.BUILDER_MAX_LABEL_CHARS,
            "max_name_chars": project_config.BUILDER_MAX_NAME_CHARS,
            "max_gate_message_chars": project_config.BUILDER_MAX_GATE_MESSAGE_CHARS,
            "max_input_chars": project_config.MAX_RUN_INPUT_CHARS,
            "max_document_bytes": project_config.MAX_BUILDER_DOCUMENT_BYTES,
            "run_cost_ceiling_usd": project_config.MAX_RUN_COST_USD,
            # C2 v2's five additions. The first three are the attachment
            # family's own bounds; the last two bound what an AUTHORED node may
            # write, and both are a document bound rather than a money one -
            # what a graph costs is `run_cost_ceiling_usd` and it is measured.
            "max_attachment_nodes": project_config.MAX_ATTACHMENT_NODES,
            "max_attachments_per_node": project_config.MAX_ATTACHMENTS_PER_NODE,
            "max_crew_members": project_config.MAX_CREW_MEMBERS,
            "max_prompt_chars": project_config.BUILDER_MAX_PROMPT_CHARS,
            "max_retries": project_config.BUILDER_MAX_NODE_RETRIES,
            # The owner's price ceiling, measured against a model's MAX endpoint
            # rather than its headline (MISSION §6a). Served so the model picker
            # can grey out an unusable entry rather than offering one the API
            # refuses at `provider.max_price`.
            "ceiling_usd_per_m_input": project_config.MODEL_PRICE_CEILING_IN,
        },
    )


#: The refusal a zip carrying a `scripts/` entry is answered with (plan 08 C8).
#: Declared HERE rather than in `builder/skills.py` on purpose: every kebab-case
#: module-level constant in the builder package is swept into the canvas
#: problem-code union by three separate greps, and this is not a canvas problem
#: - it never lands on a node and the problems dock has nothing to anchor it to.
SKILL_IMPORT_SCRIPTS_CODE = "skill-contains-scripts"


def create_builder_router(
    *,
    store_factory: Callable[[], BuilderDocumentStore | None],
    registry: RunRegistry,
    current_user: Callable[..., Any],
    runner_factory: BuilderRunnerFactory,
    credential_store_factory: Callable[[], Any] | None = None,
) -> Any:
    """The `/api/builder` router, closed over the app's own dependencies.

    `credential_store_factory` answers the vault for a validate or a publish
    that has an identity (plan 01 D10); None - the shape a dozen test modules
    build - means no credential reference is ever checked, and `validate`
    says so with `identity_checked: false`.

    `runner_factory` is a factory rather than a runner because `RunExecution`
    carries no `workflow_id` - the registry hands the runner an execution and
    nothing that says which graph it is. `publish` therefore builds one runner
    per graph, closed over the definition it has just compiled, and that
    closure is also where the `FlowDefinition` a resume must reuse lives.

    A factory rather than a module-level `APIRouter`, matching how `create_app`
    already builds its routes: the store, the registry and the user dependency
    are per-application, and a module-level router would need a global to reach
    them.

    `store_factory` is called per request rather than resolved once, so an
    application built before its persistence existed still works and a test can
    swap the store without rebuilding the app.
    """

    from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response

    router = APIRouter(prefix=BUILDER_API_PREFIX, tags=["builder"])

    def require_store() -> BuilderDocumentStore:
        store = store_factory()
        if store is None:
            raise HTTPException(
                status_code=503,
                detail=(
                    "this service has no durable store, so builder graphs cannot "
                    "be saved"
                ),
            )
        return store

    def owner_of(user: Any) -> str | None:
        return getattr(user, "id", None)

    def owner_for_new_row(user: Any) -> str | None:
        """The owner a create, an import or a duplicate writes - or a 401.

        Round 2, D-15-7: on a backend with an auth server configured, no
        caller may create an UNOWNED row. `current_user` already refuses an
        anonymous caller when `VALIDATOR_REQUIRE_AUTH` is on, which is that
        flag's default the moment `AUTH_BASE_URL` is set; this is the second
        lock for the one shape that reaches a handler with nobody in hand -
        auth configured, requirement switched off by hand. An unowned row on
        such a deployment is writable by nobody (`store._writable_by`), so
        minting one would hand the caller a graph they could read and never
        edit. Without an auth server there is no identity to record and
        creation stays open, which is what keeps `SYNTHETIC=1` and a bare
        local checkout working.
        """

        owner = owner_of(user)
        if owner is None and project_config.AUTH_BASE_URL:
            raise HTTPException(
                status_code=401,
                detail="sign in to create a graph; every graph on this service has an owner",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return owner

    def credential_check_for(user: Any) -> Callable[[str], bool] | None:
        """This caller's vault as a predicate over credential ids, or None.

        None when there is nobody to check for or nowhere to look - and the two
        are deliberately the same answer, because a check that could not run
        must not be reported as a check that passed. An unconfigured vault is
        NOT None: it holds no rows, so every reference is missing, which is
        exactly what a run on this deployment would find.
        """

        owner = owner_of(user)
        if owner is None or credential_store_factory is None:
            return None
        vault = credential_store_factory()
        if vault is None:
            return None
        return lambda credential_id: bool(vault.exists(owner, credential_id))

    def attachment_problems(document: BuilderDocument, user: Any) -> list[Problem]:
        """Tool, MCP and skill problems for THIS caller - plans 06, 07 and 08.

        Each check takes a lookup scoped to the caller, and `None` where there
        is nobody to ask. `None` is not "clean": a builtin tool id and a
        built-in skill are still checked, because neither depends on an
        identity, and only the per-user references are left alone. That is the
        same distinction `credential_check_for` draws, and for the same reason -
        a check that could not run must never be reported as one that passed.
        """

        owner = owner_of(user)
        tools = custom_tool_store()
        servers = mcp_server_store()
        skills = skill_store()
        return (
            tool_problems(
                document,
                custom_tools=(
                    (lambda tool_id: tools.exists(owner, tool_id))
                    if owner is not None and tools is not None
                    else None
                ),
            )
            + mcp_problems(
                document,
                servers=(
                    servers.lookup(owner)
                    if owner is not None and servers is not None
                    else None
                ),
            )
            + skill_problems(
                document,
                skills=(
                    skills.lookup(owner)
                    if owner is not None and skills is not None
                    else None
                ),
            )
        )

    def parse(payload: Mapping[str, Any], *, document_id: str, version: int) -> BuilderDocument:
        """Parse an author's JSON into a document, or 422 with the reason.

        The id and version are the SERVER's, always. A client that could choose
        either could make two different graphs share one ETag, and the ETag is
        what the stored budget is versioned against.
        """

        candidate = dict(payload)
        candidate["id"] = document_id
        candidate["version"] = version
        encoded = len(json.dumps(candidate, separators=(",", ":")).encode("utf-8"))
        if encoded > project_config.MAX_BUILDER_DOCUMENT_BYTES:
            # 413 rather than 422: the document may be perfectly well formed and
            # simply too big, and the middleware would have said the same thing
            # had the request declared its length.
            raise HTTPException(
                status_code=413,
                detail=(
                    f"a builder document is limited to "
                    f"{project_config.MAX_BUILDER_DOCUMENT_BYTES} bytes; this one is "
                    f"{encoded}"
                ),
            )
        try:
            return BuilderDocument.model_validate(candidate)
        except Exception as exc:  # pydantic ValidationError, and nothing else
            raise HTTPException(
                status_code=422, detail=_first_schema_error(exc, payload=candidate)
            ) from exc

    def judged(
        stored: StoredDocument,
        *,
        model: type[BuilderDocumentModel] = BuilderDocumentModel,
        **extra: Any,
    ) -> BuilderDocumentModel:
        """A stored document plus its problems, price and drawn graph.

        `model` lets `import_document` answer with the same fields plus one,
        built once rather than dumped and re-parsed through a subclass.
        """

        problems = document_problems(stored.document)
        live = registered_workflow(stored.id)
        return model(
            **extra,
            id=stored.id,
            document=stored.document.model_dump(mode="json", by_alias=True),
            status=stored.status,
            version=stored.document.version,
            head_version=stored.head_version,
            created_at=stored.created_at,
            updated_at=stored.updated_at,
            problems=[BuilderProblemModel.of(problem) for problem in problems],
            budget=BuilderBudgetModel.of(estimate_budget(stored.document)),
            graph=builder_graph_descriptor(stored.document),
            published=(
                live is not None
                and live.document.version == stored.document.version
            ),
        )

    @router.get("/vocabulary", response_model=BuilderVocabularyModel)
    async def get_vocabulary() -> BuilderVocabularyModel:
        """Every kind, op, tool and bound the canvas may offer. No auth: it is
        a description of this build, not of anybody's data."""

        return _vocabulary()

    @router.get(
        "/models",
        response_model=BuilderModelsModel,
        response_model_by_alias=True,
        responses={304: {}},
    )
    async def get_models(
        response: Response,
        if_none_match: str = Header(default="", alias="If-None-Match"),
    ) -> Any:
        """The model roster, with a conditional GET that is actually conditional.

        NO AUTH, for the same reason `/vocabulary` has none: this is a
        description of THIS BUILD, not of anybody's data, and it has to resolve
        before the three-phase auth gate does or the inspector's model picker
        would be empty for the whole of a sign-in.

        The `ETag` is the SHA-256 of `data/models.json` itself rather than a hash
        of the serialised response, and the difference is worth a sentence: the
        file is what `refresh_models.py` rewrites, so a tag derived from it moves
        exactly when the roster does and never when a serialiser changes its
        key order. The comparison is RFC 9110 WEAK, shared with `get_graph` -
        a proxy is entitled to weaken a tag in transit, and refusing the match
        then would silently turn every 304 back into a 200 with nothing in the
        logs to say why.
        """

        # Imported here rather than at module scope: `service/app.py` imports
        # this module, so a top-level import of it would close the cycle.
        from brief_crew.service.app import _etag_matches

        etag = _models_etag()
        if if_none_match and _etag_matches(if_none_match, etag):
            # 304 carries no body, and RFC 9110 requires the tag be repeated so
            # a cache can refresh its own freshness record from the response.
            return Response(status_code=304, headers={"ETag": etag})
        response.headers["ETag"] = etag
        return registry_document()

    @router.get("/workflows", response_model=list[BuilderDocumentSummaryModel])
    async def list_documents(
        limit: int = Query(default=DEFAULT_LIST_LIMIT, ge=1, le=200),
        user: Any = Depends(current_user),
    ) -> list[BuilderDocumentSummaryModel]:
        store = require_store()
        return [
            BuilderDocumentSummaryModel(
                id=row.id,
                name=row.name,
                version=row.version,
                status=row.status,
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
            for row in store.list(user_id=owner_of(user), limit=limit)
        ]

    @router.post("/workflows", response_model=BuilderDocumentModel, status_code=201)
    async def create_document(
        request: BuilderDocumentRequest,
        response: Response,
        user: Any = Depends(current_user),
    ) -> BuilderDocumentModel:
        """Save a brand new graph as a draft. A draft need not be valid.

        Deliberately: an author drawing a graph has an incomplete one for most
        of the session, and a save endpoint that refused it would make the
        canvas unusable exactly when it is most useful. The problem list comes
        back with the document, and `publish` is where the refusals live.
        """

        store = require_store()
        owner = owner_for_new_row(user)
        document = parse(
            request.document, document_id=new_document_id(), version=FIRST_VERSION
        )
        stored = _guarded(lambda: store.create(document, user_id=owner))
        response.headers["Location"] = f"{BUILDER_API_PREFIX}/workflows/{stored.id}"
        return judged(stored)

    # Declared BEFORE every `/workflows/{document_id}` route. FastAPI matches in
    # declaration order, and `import` is a perfectly good-looking path segment
    # - declared below them it would be answered by `get_document` as a lookup
    # of a document called "import", which is a 404 that reads as a missing
    # feature.
    @router.post(
        "/workflows/import",
        response_model=BuilderImportedDocumentModel,
        status_code=201,
        # The body is read by hand below, so the schema is declared here for
        # the docs rather than inferred from a typed parameter.
        openapi_extra={
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": BuilderImportRequest.model_json_schema()
                    }
                },
            }
        },
    )
    async def import_document(
        http_request: Request,
        response: Response,
        user: Any = Depends(current_user),
    ) -> BuilderDocumentModel:
        """A `.builder.json` becomes a NEW draft owned by the caller. Always new.

        The envelope is parsed HERE, by `_import_envelope`, and not by FastAPI
        (round 2, D-15-9). A typed `BuilderImportRequest` parameter handed a
        malformed file to FastAPI's default 422, which is pydantic's full
        error list with the offending `input` echoed back - the whole document
        for a file with no envelope, all five hundred entries for an oversized
        `needs_credentials`. An uploaded file can carry anything, including
        somebody else's secrets, and the module's own docstring already
        refused that reflection for `document`; the envelope now gets the
        same treatment: one sentence naming the first problem, never the body.

        Never an overwrite (D2): the file carries no id worth honouring - the
        export dropped it, and a hand-edited one is somebody else's row - so
        the importer mints an id the way `create` does and the version is
        `FIRST_VERSION`. The document goes through `upgrade_document` first, so
        a v1 file imports unchanged today and a v2 file imports the day C1
        lands (ruling 4), and then through `strip_for_export` AGAIN on the way
        in: the export made the file secret-free by construction, but nothing
        makes a file honest, and a `credential_id` typed into one by hand must
        not become a reference to a credential the importer does not own.

        `needs_credentials` is the INTERSECTION of the envelope's list and the
        nodes whose credential or server key is present and empty in the file
        (round 3, D-15-19 / D-15-20).

        The paragraph this replaces said the list was re-derived from the
        inbound strip and the envelope ignored, and it was wrong in a way no
        test caught for two rounds: the EXPORT nulls the key and records the
        node in the envelope, so on re-import the strip finds nothing left to
        strip and reported an empty list for the exact file that had just said
        three nodes lost a credential. The notice built for that case was
        unreachable and the graph silently dropped from the author's key to
        the platform key.

        Neither half is trustworthy alone, and that is why it is an
        intersection rather than either one:

        * the envelope is a claim by a file, and a file can say anything, so a
          name with no empty key behind it is dropped - a hand-written
          envelope cannot talk a node into a notice;
        * an empty key is not a claim at all, so a node that never had a
          credential is not flagged - otherwise every clean export would open
          under a problem group, which is the defect the `if item not in
          (None, "")` guard in `_scrub` was added to fix.

        ONE CASE SITS OUTSIDE THAT INTERSECTION, and it is here deliberately:
        a node whose key arrives NON-empty, which the inbound strip removes.
        The ruling as written drops it - the key is not empty, so the first
        rule applies - and dropping it would silently undo the very harm this
        row is about, because such a node really did lose a credential on the
        way in and nobody would be told. It is also not a file's claim in the
        first place: `stripped_nodes` is this server's own report of a value
        it removed, and a file cannot inject a name into it without actually
        carrying a credential for a node of its own document, which is
        harmless. `tests/service/test_builder_import.py`'s
        `test_a_hand_typed_credential_id_never_becomes_a_reference` pins that
        case and predates this row; honouring the intersection alone turns it
        red. So the answer is the intersection OR the strip's own report,
        which keeps both of the ruling's stated reasons exactly:
        a name alone still buys nothing, and an empty key alone still buys
        nothing.

        Ordered by the document's own nodes rather than by the envelope, so
        the list reads in canvas order whatever order the file listed, and
        kept to ids the document actually has, once each.
        """

        request = _import_envelope(await http_request.body())
        if request.export not in KNOWN_SCHEMAS:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"export must be one of {list(KNOWN_SCHEMAS)}; this file says "
                    f"{request.export[:64]!r}"
                ),
            )
        store = require_store()
        owner = owner_for_new_row(user)
        incoming = upgrade_document(request.document)
        # The file's own empty keys, read BEFORE the strip: afterwards every
        # such key is null and the two cases are indistinguishable.
        empty_in_file = set(nulled_reference_nodes(incoming))
        # The strip still runs, and it is still what makes the file safe -
        # nothing makes a file honest. What it reports is no longer the
        # answer's only source, but it is still A source: see below.
        raw, stripped_nodes = strip_for_export(incoming)
        if not raw.get("name") and request.name:
            raw["name"] = request.name
        # Distinct in the caller's own library (D-15-4). The file's name is kept
        # when nothing of theirs already carries it; otherwise it gets the
        # import suffix, then a number, so two rows never read identically.
        if isinstance(raw.get("name"), str):
            raw["name"] = import_name(raw["name"], _names_of(store, owner))
        document = parse(raw, document_id=new_document_id(), version=FIRST_VERSION)
        stored = _guarded(lambda: store.create(document, user_id=owner, source="imported"))
        response.headers["Location"] = f"{BUILDER_API_PREFIX}/workflows/{stored.id}"
        declared = {name for name in request.needs_credentials if isinstance(name, str)}
        removed_here = set(stripped_nodes)
        needs_credentials = [
            node.id
            for node in document.nodes
            if node.id in removed_here or (node.id in declared and node.id in empty_in_file)
        ]
        return judged(
            stored,
            model=BuilderImportedDocumentModel,
            needs_credentials=needs_credentials,
        )

    @router.get("/workflows/{document_id}", response_model=BuilderDocumentModel)
    async def get_document(
        document_id: str,
        version: int | None = Query(default=None, ge=1),
        user: Any = Depends(current_user),
    ) -> BuilderDocumentModel:
        store = require_store()
        return judged(
            _guarded(
                lambda: store.load(
                    document_id, version=version, user_id=owner_of(user)
                )
            )
        )

    @router.put("/workflows/{document_id}", response_model=BuilderDocumentModel)
    async def save_document(
        document_id: str,
        request: BuilderDocumentRequest,
        user: Any = Depends(current_user),
    ) -> BuilderDocumentModel:
        """Write the next version, if nobody else wrote one first.

        `expected_version` is required rather than optional-with-a-default. A
        save with no version to compare against is a lost update waiting to
        happen, and defaulting to "whatever is stored" would make the conflict
        unreachable rather than rare.
        """

        if request.expected_version is None:
            raise HTTPException(
                status_code=422,
                detail=(
                    "expected_version is required on a save; send the version you "
                    "loaded so a concurrent edit is a conflict rather than a "
                    "silent overwrite"
                ),
            )
        store = require_store()
        document = parse(
            request.document,
            document_id=document_id,
            # Provisional: `store.save` stamps `expected_version + 1`. Parsing
            # against the version the author loaded keeps the schema's `ge=1`
            # satisfied without pretending the client chose the new number.
            version=max(FIRST_VERSION, request.expected_version),
        )
        stored = _guarded(
            lambda: store.save(
                document,
                expected_version=request.expected_version,
                user_id=owner_of(user),
                source=_version_source(request),
            )
        )
        return judged(stored)

    @router.get("/workflows/{document_id}/compiled", response_model=CompiledPreviewModel)
    async def compiled_preview(
        document_id: str,
        version: int | None = Query(default=None, ge=1),
        user: Any = Depends(current_user),
    ) -> CompiledPreviewModel:
        """C7's `compiled`: what this canvas became, as something a person reads.

        `preview.py` shipped with plan 09 and had no route; this is it. Two
        renderings of ONE compiled definition - the literal YAML
        `Flow.from_declaration` loads, and a Python reading aid that names the
        constructors the entrypoints will build.

        NO SECRET REACHES EITHER, and the mechanism is that this route hands the
        renderer a LABELLING function rather than the vault: `render_preview`
        cannot open a credential even by accident, because it was never given
        anything that could. The label is the credential's own name where the
        caller owns it, and the bare id where they do not - a document naming
        somebody else's row still renders, saying only that it names one.

        Visibility is `store.load`'s, so somebody else's document is the same
        404 as an id that does not exist. A document that no longer COMPILES is
        a 422 carrying the compiler's own problem list, exactly as publish
        answers: a preview that silently showed the last version that worked
        would be the most misleading thing on the page.
        """

        store = require_store()
        stored = _guarded(
            lambda: store.load(document_id, version=version, user_id=owner_of(user))
        )
        try:
            compiled = compile_document(stored.document)
        except BuilderCompileError as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "message": str(exc),
                    "problems": [
                        BuilderProblemModel.of(problem).model_dump(mode="json")
                        for problem in exc.problems
                    ],
                },
            ) from exc
        preview = render_preview(
            compiled,
            document_version=stored.document.version,
            credential_label=_credential_label(user),
        )
        return CompiledPreviewModel(
            document_id=stored.document.id,
            version=preview.document_version,
            generated_at=preview.generated_at,
            yaml=preview.yaml,
            python=preview.python,
            definition=preview.definition,
        )

    def _credential_label(user: Any) -> Callable[[str], str]:
        """A credential id to the caller's own name for it, or back to the id.

        A closure over the caller and the store, handed to the renderer, which
        is the whole of the containment: the module that draws the preview holds
        no vault, no persistence and no key, so `<credential: ...>` can only
        ever be a label.
        """

        persistence = _persistence()
        owner = owner_of(user)
        if persistence is None or owner is None:
            return lambda credential_id: str(credential_id)

        def label(credential_id: str) -> str:
            try:
                summaries = CredentialStore(persistence).list(owner)
            except Exception:  # noqa: BLE001 - a preview must not 500 on a label
                return str(credential_id)
            for summary in summaries:
                if summary.id == credential_id:
                    return summary.label
            return str(credential_id)

        return label

    # ----------------------------------------------------------------------
    # Saved test inputs - .agent/plans/13-flow-testing.md D3, contract C10.
    #
    # Three routes over `builder_test_inputs`. They hang off the DOCUMENT and
    # not off a workflow id, deliberately: an author saves an input while
    # drawing, long before anything is published, and a route keyed on the
    # published workflow would be unreachable at exactly the moment the panel
    # is most useful. The two ids happen to be the same string
    # (`builder_workflow_id` returns the document's own id) and that is a fact
    # about registration, not a licence to key a draft's rows on it.
    #
    # Visibility is asked ONCE, of the document, through the same `store.load`
    # every other route on this router uses - so somebody else's document is
    # the same 404 as an id that does not exist, and the rows underneath it are
    # never queried at all.
    # ----------------------------------------------------------------------
    def _test_input_store() -> BuilderTestInputStore:
        persistence = _persistence()
        if persistence is None:
            raise HTTPException(
                status_code=503,
                detail="this service has no store, so it has no saved test inputs",
            )
        return BuilderTestInputStore(persistence)

    def _visible_document(document_id: str, user: Any) -> StoredDocument:
        """The document these rows belong to, or 404. Head version only.

        Head and not a named version, because a saved input is a fact about the
        GRAPH rather than about one of its versions: an author who saves a topic
        for their pipeline means it for the pipeline, and pinning it to v7 would
        lose it on the next save.
        """

        store = require_store()
        return _guarded(lambda: store.load(document_id, user_id=owner_of(user)))

    def _test_input_payload(row: TestInput) -> TestInputModel:
        return TestInputModel(
            id=row.id,
            document_id=row.document_id,
            label=row.label,
            inputs=row.inputs,
            node_mocks=row.node_mocks,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    def _mocks_from_run(run_id: str, user: Any) -> dict[str, Any]:
        """A finished run's `out__*` slots, keyed by the author's own node id.

        D3's *"use last run's outputs as mocks"*. Read off the last `flow_states`
        row rather than off the run's result, for `app.py::_saved_outputs`'s own
        reason: the result is ONE node's output and a replay needs every node's.

        The run must be the caller's. The refusal is 404 rather than 403, the
        same rule `require_own_run` states: a 403 confirms the run exists.
        """

        try:
            record = registry.require(run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc
        owner = owner_of(user)
        if record.user_id is not None and record.user_id != owner:
            raise HTTPException(status_code=404, detail="run not found")
        persistence = _persistence()
        if persistence is None or not record.flow_id:
            return {}
        state = persistence.load_state(record.flow_id) or {}
        prefix = project_config.BUILDER_STATE_OUTPUT_PREFIX
        return {
            key[len(prefix):]: value
            for key, value in state.items()
            if isinstance(key, str) and key.startswith(prefix)
        }

    @router.get(
        "/workflows/{document_id}/test-inputs",
        response_model=list[TestInputModel],
    )
    async def list_test_inputs(
        document_id: str,
        user: Any = Depends(current_user),
    ) -> list[TestInputModel]:
        """This caller's saved inputs for one document, newest first."""

        stored = _visible_document(document_id, user)
        rows = _test_input_store().list(stored.id, user_id=owner_of(user))
        return [_test_input_payload(row) for row in rows]

    @router.post(
        "/workflows/{document_id}/test-inputs",
        response_model=TestInputModel,
        status_code=201,
    )
    async def create_test_input(
        document_id: str,
        request: TestInputRequest,
        user: Any = Depends(current_user),
    ) -> TestInputModel:
        """Save one input set, optionally seeded from a finished run's state.

        A saved input is NOT validated against the document's `input_field`, and
        that is a decision rather than an omission. The two move independently -
        an author renames the field, or saves the input before the input node
        exists - and a row refused for naming yesterday's field would be a row
        the author cannot repair from the panel. The run endpoint is where an
        input meets a workflow, and it already answers for a key that does not
        fit.
        """

        stored = _visible_document(document_id, user)
        mocks = dict(request.node_mocks)
        if request.from_run_id:
            # The explicit values win: an author who typed one meant it.
            mocks = {**_mocks_from_run(request.from_run_id, user), **mocks}
        try:
            row = _test_input_store().create(
                stored.id,
                user_id=owner_of(user),
                label=request.label,
                inputs=request.inputs,
                node_mocks=mocks,
            )
        except TestInputLimitReached as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return _test_input_payload(row)

    @router.delete(
        "/workflows/{document_id}/test-inputs/{test_input_id}",
        status_code=204,
    )
    async def delete_test_input(
        document_id: str,
        test_input_id: str,
        user: Any = Depends(current_user),
    ) -> Response:
        """Gone, for this caller's own row and nobody else's."""

        _visible_document(document_id, user)
        try:
            _test_input_store().delete(test_input_id, user_id=owner_of(user))
        except TestInputNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return Response(status_code=204)

    @router.get("/workflows/{document_id}/export")
    async def export_document(
        document_id: str,
        version: int | None = Query(default=None, ge=1),
        user: Any = Depends(current_user),
    ) -> Response:
        """The D1 envelope as a download: secret-free, owner-free, id-free.

        Visibility is `store.load`'s, so somebody else's document is the same
        404 every other route answers. The body is built by `export_envelope`
        from the parsed document's own dump rather than from the raw row, so a
        row this service can no longer read is a 422 naming the document, not
        a file that will not import anywhere.
        """

        store = require_store()
        stored = _guarded(
            lambda: store.load(document_id, version=version, user_id=owner_of(user))
        )
        envelope = export_envelope(
            stored.document.model_dump(mode="json", by_alias=True),
            source_version=stored.document.version,
            name=stored.document.name,
        )
        return Response(
            content=json.dumps(envelope, indent=2, ensure_ascii=False),
            media_type="application/json",
            headers={
                "Content-Disposition": export_content_disposition(stored.document.name)
            },
        )

    @router.get(
        "/workflows/{document_id}/versions",
        response_model=list[BuilderVersionModel],
    )
    async def list_versions(
        document_id: str, user: Any = Depends(current_user)
    ) -> list[BuilderVersionModel]:
        """Every stored version, newest first, sized and dated. Same visibility."""

        store = require_store()
        history = _guarded(lambda: store.history(document_id, user_id=owner_of(user)))
        live = registered_workflow(document_id)
        live_version = live.document.version if live is not None else None
        return [
            BuilderVersionModel(
                version=entry.version,
                status=_version_status(entry.version, history, live_version),
                created_at=entry.created_at,
                bytes=entry.bytes,
                source=entry.source or "stored",
                name=entry.name,
                node_count=entry.node_count,
                edge_count=entry.edge_count,
            )
            for entry in history.entries
        ]

    @router.post(
        "/workflows/{document_id}/duplicate",
        response_model=BuilderDocumentModel,
        status_code=201,
    )
    async def duplicate_document(
        document_id: str,
        response: Response,
        version: int | None = Query(default=None, ge=1),
        user: Any = Depends(current_user),
    ) -> BuilderDocumentModel:
        """A new draft, version 1, `"<name> copy"`, owned by the caller (D3).

        Goes through `parse` and `store.create` exactly as a fresh document
        does, so the copy gets a server-minted id and a recomputed price - the
        source's `budget` is dropped because it was measured against the
        ceiling of the day it was published, not today's.
        """

        store = require_store()
        owner = owner_for_new_row(user)
        source = _guarded(
            lambda: store.load(document_id, version=version, user_id=owner_of(user))
        )
        payload = source.document.model_dump(mode="json", by_alias=True)
        # `<name> copy`, and `<name> copy 2` for the second copy of the same
        # source (D-15-4): a duplicate that reads exactly like the last
        # duplicate is the one thing a duplicate must not be.
        payload["name"] = distinct_name(source.document.name, COPY_SUFFIX, _names_of(store, owner))
        payload.pop("budget", None)
        document = parse(payload, document_id=new_document_id(), version=FIRST_VERSION)
        stored = _guarded(lambda: store.create(document, user_id=owner, source="duplicated"))
        response.headers["Location"] = f"{BUILDER_API_PREFIX}/workflows/{stored.id}"
        return judged(stored)

    @router.delete(
        "/workflows/{document_id}", status_code=204, response_class=Response
    )
    async def delete_document(
        document_id: str, user: Any = Depends(current_user)
    ) -> Response:
        """Delete a graph and every version of it - unless ANY version is launchable.

        A document with a version registered on this service is refused with a
        **409**, not unpublished on the way out (PLANS.md decision 24, built on
        the plan's recommendation). Deleting it would take the graph out of the
        registration maps and the row out of the table in one request, which
        is the one shape the boot sweep can never put back and the one shape a
        run queued a moment earlier compiles against nothing. The sentence
        says what to do instead, in the words the docked confirm uses:
        unpublish it first, then delete it.

        Round 1 (D-15-10) found the guard one save deep. It read
        `stored.status == STATUS_PUBLISHED and registered_workflow(...)`, and
        its own sentence told the author to save - which returned the HEAD to
        `draft` while the older version stayed registered and launchable, so
        the very next delete passed the guard and unregistered a live graph.
        The condition is now the registration alone, and the remedy is a route
        the server honours: `POST .../unpublish`.

        For a draft, or a published row this process never registered (one the
        boot sweep skipped), the order is unchanged: unregister, then delete.
        Unregistering first would leave a window in which the graph is
        unlaunchable but still stored; deleting first would leave one in which
        it is launchable but gone. The second is worse - a run would compile
        against a document nobody can read - so the store row goes last.
        """

        store = require_store()
        # `writable=True` BEFORE `_unregister`: a refusal must leave the graph
        # exactly as registered as it was (D-15-7).
        stored = _guarded(
            lambda: store.load(document_id, user_id=owner_of(user), writable=True)
        )
        live = registered_workflow(document_id)
        if live is not None:
            # NAMED, ONCE (round 3, D-15-18). The sentence said
            # "document ug_309cd317 is published - v1 is registered as a
            # launchable workflow - and cannot be deleted", which put the
            # internal id in front of a person who has never seen one and said
            # published twice in different words. The server is the only layer
            # that holds the name and the live version together, so it is the
            # only layer that can say this once and say it well; the id stays
            # in the request that carries it and in the log.
            raise HTTPException(
                status_code=409,
                detail=(
                    f"“{stored.document.name}” is live as v{live.document.version} "
                    "and cannot be deleted; unpublish it first, then delete it"
                ),
            )
        _unregister(registry, document_id)
        _guarded(lambda: store.delete(document_id, user_id=owner_of(user)))
        return Response(status_code=204)

    @router.post("/workflows/{document_id}/unpublish", response_model=BuilderDocumentModel)
    async def unpublish(
        document_id: str, user: Any = Depends(current_user)
    ) -> BuilderDocumentModel:
        """Take this graph out of service and return its head to `draft`.

        The remedy the delete 409 names, and the route that makes decision 24
        honest (D-15-10): "refuse to delete a published graph" is only a rule
        an author can act on if unpublishing is something the server does.

        The row moves FIRST, then the registration. A crash between the two
        leaves a draft that is still registered until the next restart, which
        then does not re-register it - the right end state, one restart late.
        The other order would leave a `published` row with no registration,
        and the boot sweep would put the graph back into service on the next
        deploy: the author's unpublish, silently undone. Idempotent, and a
        graph that was never published answers 200 with nothing changed - the
        author asked for a state, and that is the state.

        Same visibility as every other write: a stranger's document is 404,
        an unowned one is 403 naming Duplicate.
        """

        store = require_store()
        stored = _guarded(
            lambda: store.mark_unpublished(document_id, user_id=owner_of(user))
        )
        _unregister(registry, document_id)
        return judged(stored)

    @router.post("/validate", response_model=BuilderValidationModel)
    async def validate(
        request: BuilderDocumentRequest, user: Any = Depends(current_user)
    ) -> BuilderValidationModel:
        """Every problem with a document nobody has saved.

        The canvas calls this on every meaningful edit, so it registers nothing
        and touches the database only to ask the caller's vault whether a
        `credential_id` is theirs (plan 01 D10) - with an identity. Without
        one that check is skipped and `identity_checked` is false, so the
        client can say why a problem may still appear at publish.
        `document_problems` never raises; a document that does not even PARSE
        is the 422 from `parse` above, and one that cannot say which version it
        was edited from is the 422 from `_requested_version`.
        """

        document = parse(
            request.document,
            document_id=str(request.document.get("id") or new_document_id()),
            version=_requested_version(request.document),
        )
        credential_check = credential_check_for(user)
        problems = document_problems(document, credential_check=credential_check)
        # The three attachment checks, after the structural ones and in the
        # same list. They are separate functions rather than part of
        # `document_problems` because each one needs a STORE, and the compiler
        # is deliberately importable without the service package - the shape
        # `credential_problems` already established with its injected predicate.
        problems = problems + attachment_problems(document, user)
        return BuilderValidationModel(
            valid=not any(problem.severity == "error" for problem in problems),
            problems=[BuilderProblemModel.of(problem) for problem in problems],
            budget=BuilderBudgetModel.of(estimate_budget(document)),
            identity_checked=credential_check is not None,
        )

    @router.post("/workflows/{document_id}/publish", response_model=BuilderPublishModel)
    async def publish(
        document_id: str,
        version: int | None = Query(default=None, ge=1),
        user: Any = Depends(current_user),
    ) -> BuilderPublishModel:
        """Compile this version and register it as a launchable workflow.

        The refusals live here and not on save, and the compiler is the only
        thing that decides: `compile_document` runs `document_problems` first,
        so a graph that is miswired, over a bound or over budget comes back as
        the same problem list the canvas drew, with a 422.

        Registration is two halves that must not come apart - the four module
        maps in `service/graph.py`, and this application's own runtime map -
        and if the second fails the first is rolled back, because a workflow in
        `WORKFLOWS` with no runtime is the 404 that reads as a service defect.
        """

        store = require_store()
        # `writable=True` BEFORE the compile: an unowned row is 403 here, in
        # one query, rather than after a compile and a registration that
        # `mark_published` would then have to roll back (D-15-7).
        stored = _guarded(
            lambda: store.load(
                document_id, version=version, user_id=owner_of(user), writable=True
            )
        )
        try:
            # Owned by the DOCUMENT's owner, not the publisher (plan 01 D1): a
            # document nobody owns stays a graph anybody may launch. The
            # publisher's own vault is what the credential references are
            # re-validated against (D10); anonymous publishes check nothing,
            # and a run nobody owns resolves nothing at its first agent.
            workflow = build_builder_workflow(
                stored.document,
                user_id=stored.user_id,
                credential_check=credential_check_for(user),
            )
        except BuilderCompileError as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "message": str(exc),
                    "problems": [
                        BuilderProblemModel.of(problem).model_dump(mode="json")
                        for problem in exc.problems
                    ],
                },
            ) from exc

        register_builder_workflow(workflow)
        try:
            # Inside the try, so a factory that refuses this graph rolls the
            # module maps back with everything else rather than leaving a
            # workflow registered with no runtime behind it - which is the 404
            # on launch that reads as a service defect.
            _register_runtime(registry, workflow, runner_factory(workflow))
            _guarded(
                lambda: store.mark_published(
                    stored.id, stored.document.version, user_id=owner_of(user)
                )
            )
        except Exception as exc:
            unregister_builder_workflow(workflow.workflow_id)
            _unregister_runtime(registry, workflow.workflow_id)
            if isinstance(exc, BuilderServiceUnavailable):
                # Translated here rather than at the raise site: the rollback
                # has to happen first either way, and `_register_runtime` is
                # also called by the boot sweep, which has no response to write.
                # Without this the refusal its own docstring describes arrived
                # as a 500 - the one status that says the fault is ours.
                raise HTTPException(status_code=503, detail=str(exc)) from exc
            raise
        return BuilderPublishModel(
            workflow_id=workflow.workflow_id,
            graph_version=workflow.graph_version,
            version=stored.document.version,
            input_field=workflow.input_field,
            static_cost_usd=workflow.static_cost_usd,
            gated_before_spend=workflow.gated_before_spend,
            reserved_input_keys=sorted(workflow.reserved_input_keys),
        )


    # ----------------------------------------------------------------------
    # Attachments: tools, MCP servers and skills - plans 06, 07 and 08
    #
    # Appended rather than woven in. Every route below is authenticated the way
    # `/credentials` is, answers 404 and never 403 for somebody else's row, and
    # reaches its table through `service/attachments.py`, which holds the SQL
    # and no decisions. Nothing above this comment changed except `_vocabulary`
    # gaining a derived `tools` list and the two validation paths gaining the
    # three attachment checks.
    # ----------------------------------------------------------------------
    def _persistence() -> Any:
        return getattr(registry, "persistence", None)

    def custom_tool_store() -> Any:
        persistence = _persistence()
        return None if persistence is None else CustomToolStore(persistence)

    def mcp_server_store() -> Any:
        persistence = _persistence()
        return None if persistence is None else McpServerStore(persistence)

    def skill_store() -> Any:
        persistence = _persistence()
        return None if persistence is None else SkillStore(persistence)

    def require_owner(user: Any) -> str:
        """An identity, or 401. Every attachment row has an owner.

        Unlike a document - which may be unowned, and is then readable by
        everybody so a local checkout works - a tool, a server and a skill are
        per-user by construction (15 C10 makes `user_id` NOT NULL on all three).
        The one thing an anonymous caller may do is READ the built-in skills and
        the built-in tool catalogue, and those two routes say so themselves.
        """

        owner = owner_of(user)
        if owner is None:
            raise HTTPException(
                status_code=401,
                detail="sign in first; tools, MCP servers and skills belong to somebody",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return owner

    def _attachment(action: Callable[[], Any]) -> Any:
        """Translate the three store exceptions into the statuses they mean."""

        try:
            return action()
        except AttachmentNotYours as exc:
            raise HTTPException(status_code=404, detail=str(exc) or "no such row") from exc
        except NameTaken as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except TooManyRows as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except (CustomToolError, SkillError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except SkillBodyUnreadable as exc:
            # 500 and it names the path. The alternative - the empty body this
            # branch used to hand back - is what let a path bug live in a
            # shipped default behind 2,420 green tests.
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    def _no_store() -> HTTPException:
        return HTTPException(
            status_code=503,
            detail="this build has nowhere to keep tools, servers or skills",
        )

    # ------------------------------------------------------------ 06: tools
    @router.get("/tools")
    async def list_tools(user: Any = Depends(current_user)) -> dict[str, Any]:
        """The catalogue: this deployment's builtins, then the caller's own.

        No auth for the builtins - it is a description of this build, like the
        vocabulary - and a signed-in caller additionally sees their custom
        tools. `class_ref` is not a key of the wire shape and never has been:
        `ToolCatalogueEntry.serialisable()` builds the dictionary field by
        field, so a factory cannot leak into it by being added to the dataclass.
        """

        entries = [entry.serialisable() for entry in tool_catalogue()]
        owner = owner_of(user)
        store = custom_tool_store()
        if owner is not None and store is not None:
            for spec in store.list(owner):
                entries.append(spec.as_entry().serialisable())
        return {"tools": entries}

    @router.post("/tools/custom", status_code=201)
    async def create_custom_tool(
        request: Request, user: Any = Depends(current_user)
    ) -> dict[str, Any]:
        """A schema grid and an HTTPS request template. Never a function.

        Flowise's `ToolDialog` is the reference and its `func` field is the one
        thing deliberately not copied: a JavaScript function stored per user is
        an evaluation surface, and the six closed `BUILDER_TRANSFORM_OPS` are
        this repository's standing answer to that trade.
        """

        owner = require_owner(user)
        store = custom_tool_store()
        if store is None:
            raise _no_store()
        payload = await _json_body(request)
        spec = _attachment(lambda: parse_custom_tool(payload))
        created = _attachment(lambda: store.create(owner, spec))
        return _custom_tool_body(created)

    @router.put("/tools/custom/{tool_id}")
    async def update_custom_tool(
        tool_id: str, request: Request, user: Any = Depends(current_user)
    ) -> dict[str, Any]:
        owner = require_owner(user)
        store = custom_tool_store()
        if store is None:
            raise _no_store()
        payload = await _json_body(request)
        spec = _attachment(lambda: parse_custom_tool(payload, tool_id=tool_id))
        updated = _attachment(lambda: store.update(owner, tool_id, spec))
        return _custom_tool_body(updated)

    @router.delete("/tools/custom/{tool_id}", status_code=204)
    async def delete_custom_tool(
        tool_id: str, user: Any = Depends(current_user)
    ) -> Response:
        """Gone. A document that still names it validates `tool-unknown`.

        Deliberately not refused for a document that references it, unlike a
        published graph (decision 24): a tool is an attachment, a graph without
        one is a graph with a problem the author can see and repair, and
        refusing the delete would make an unused tool undeletable because some
        old draft still mentions it.
        """

        owner = require_owner(user)
        store = custom_tool_store()
        if store is None:
            raise _no_store()
        _attachment(lambda: store.delete(owner, tool_id))
        return Response(status_code=204)

    @router.post("/tools/custom/{tool_id}/test")
    async def test_custom_tool(
        tool_id: str, request: Request, user: Any = Depends(current_user)
    ) -> dict[str, Any]:
        """Run the call once and hand back the envelope, billed to nobody.

        The author needs to see the shape their agent will see, and the only
        honest way to show it is to make the call. It goes through the same
        `_run` the agent's tool would, so the SSRF refusal, the redirect
        refusal and the response cap are the real ones rather than a preview
        of them.
        """

        owner = require_owner(user)
        store = custom_tool_store()
        if store is None:
            raise _no_store()
        spec = _attachment(lambda: store.get(owner, tool_id))
        payload = await _json_body(request)
        arguments = payload.get("args") if isinstance(payload, Mapping) else None
        credential = None
        if spec.credential_id:
            vault = credential_store_factory() if credential_store_factory else None
            if vault is None:
                raise HTTPException(
                    status_code=503, detail="credential vault is not configured"
                )
            try:
                credential = dict(vault.resolve(owner, spec.credential_id).fields)
            except Exception as exc:  # the vault's own refusal, by id only
                raise HTTPException(status_code=404, detail=str(exc)) from exc
        tool = build_custom_tool(spec, credential=credential)
        return {"envelope": json.loads(tool._run(**dict(arguments or {})))}

    def _custom_tool_body(spec: Any) -> dict[str, Any]:
        """The wire shape of one custom tool. The credential travels as an ID."""

        return {
            "id": spec.id,
            "name": spec.name,
            "description": spec.description,
            "properties": [
                {
                    "name": prop.name,
                    "type": prop.type,
                    "description": prop.description,
                    "required": prop.required,
                }
                for prop in spec.properties
            ],
            "request": {
                "method": spec.request.method,
                "url": spec.request.url,
                "header_name": spec.request.header_name,
                "header_template": spec.request.header_template,
                "body_template": spec.request.body_template,
                "timeout_seconds": spec.request.timeout_seconds,
                "max_response_bytes": spec.request.max_response_bytes,
            },
            "credential_id": spec.credential_id,
            "entry": spec.as_entry().serialisable(),
        }

    # -------------------------------------------------------------- 07: MCP
    @router.get("/mcp/servers")
    async def list_mcp_servers(user: Any = Depends(current_user)) -> dict[str, Any]:
        owner = require_owner(user)
        store = mcp_server_store()
        if store is None:
            raise _no_store()
        return {"servers": [_mcp_body(record) for record in store.list(owner)]}

    @router.post("/mcp/servers", status_code=201)
    async def create_mcp_server(
        request: Request, user: Any = Depends(current_user)
    ) -> dict[str, Any]:
        """Add a server. A transport this deployment will not dial is a 422.

        Refused at create AND at validate, because the stdio flag can be turned
        off after a row exists and a stored row whose transport is no longer
        permitted has to say so on the canvas rather than at the first run.
        """

        owner = require_owner(user)
        store = mcp_server_store()
        if store is None:
            raise _no_store()
        payload = await _json_body(request)
        fields = _mcp_fields(payload)
        refusal = transport_refusal(
            transport=fields["transport"],
            url=fields["url"],
            command=fields["command"],
            args=fields["args"],
        )
        if refusal is not None:
            raise HTTPException(
                status_code=422,
                detail={"code": MCP_TRANSPORT_DISALLOWED, "message": refusal},
            )
        record = _attachment(lambda: store.create(owner, **fields))
        return _mcp_body(record)

    @router.put("/mcp/servers/{server_id}")
    async def update_mcp_server(
        server_id: str, request: Request, user: Any = Depends(current_user)
    ) -> dict[str, Any]:
        owner = require_owner(user)
        store = mcp_server_store()
        if store is None:
            raise _no_store()
        payload = await _json_body(request)
        fields = _mcp_fields(payload)
        refusal = transport_refusal(
            transport=fields["transport"],
            url=fields["url"],
            command=fields["command"],
            args=fields["args"],
        )
        if refusal is not None:
            raise HTTPException(
                status_code=422,
                detail={"code": MCP_TRANSPORT_DISALLOWED, "message": refusal},
            )
        record = _attachment(lambda: store.update(owner, server_id, **fields))
        return _mcp_body(record)

    @router.delete("/mcp/servers/{server_id}", status_code=204)
    async def delete_mcp_server(
        server_id: str, user: Any = Depends(current_user)
    ) -> Response:
        owner = require_owner(user)
        store = mcp_server_store()
        if store is None:
            raise _no_store()
        _attachment(lambda: store.delete(owner, server_id))
        return Response(status_code=204)

    @router.post("/mcp/servers/{server_id}/discover")
    def discover_mcp_server(
        server_id: str, user: Any = Depends(current_user)
    ) -> dict[str, Any]:
        """Connect, list the tools, sanitise them, store them. 200 either way.

        A `def` rather than an `async def` deliberately: the resolver blocks on
        a socket, and FastAPI runs a sync route in its threadpool - the same
        shape `current_user` uses to absorb a JWKS fetch. An `async def` here
        would park the event loop for up to
        `MCP_DISCOVERY_TIMEOUT_SECONDS` and stall every other request.

        A failure is 200 with `status: error` and one sentence. The author
        needs the sentence in the panel; a 502 would put a stack trace in a
        toast and tell them nothing they can act on.
        """

        owner = require_owner(user)
        store = mcp_server_store()
        if store is None:
            raise _no_store()
        record = _attachment(lambda: store.get(owner, server_id))
        header, env = _mcp_credentials(owner, record)
        result = mcp_discover(record, header=header, env=env)
        stored = _attachment(lambda: store.record_discovery(owner, server_id, result))
        return {
            "status": stored.status,
            "tools": [tool.as_dict() for tool in stored.discovered_tools],
            "discovered_at": (
                stored.discovered_at.isoformat() if stored.discovered_at else None
            ),
            "error": stored.last_error,
        }

    def _mcp_credentials(owner: str, record: Any) -> tuple[Any, Any]:
        """Resolve the header and env credentials, or None for each.

        An `mcp_header` credential's two fields ARE the header's `name` and
        its `header_value`, so there is no `header_name` column and none is
        missing. A
        credential that is gone resolves to nothing rather than failing the
        discovery: the row's own `last_error` is a better place for that than a
        500, and `credential-missing` reports it on the canvas.
        """

        vault = credential_store_factory() if credential_store_factory else None
        if vault is None:
            return None, None

        def fields(credential_id: Any) -> dict[str, str] | None:
            if not credential_id:
                return None
            try:
                return dict(vault.resolve(owner, str(credential_id)).fields)
            except Exception:
                return None

        header_fields = fields(record.header_credential_id)
        env_fields = fields(record.env_credential_id)
        header = (
            {header_fields["name"]: header_fields["header_value"]}
            if header_fields
            else None
        )
        env = (
            {env_fields["name"]: env_fields["header_value"]} if env_fields else None
        )
        return header, env

    def _mcp_body(record: Any) -> dict[str, Any]:
        """The list shape: the URL MASKED, and no credential id echoed back.

        Flowise masks a custom server's URL in its list for the reason that
        applies here too - plenty of hosted MCP servers put a token in the path,
        so a panel showing the whole URL publishes a credential to anyone who
        can see the screen.
        """

        return {
            "id": record.id,
            "label": record.label,
            "transport": record.transport,
            "url": mask_mcp_url(record.url),
            "command": record.command,
            "args": list(record.args),
            "has_header_credential": bool(record.header_credential_id),
            "has_env_credential": bool(record.env_credential_id),
            "status": record.status,
            "stale": record.stale(),
            "tools": [tool.as_dict() for tool in record.discovered_tools],
            "discovered_at": (
                record.discovered_at.isoformat() if record.discovered_at else None
            ),
            "last_error": record.last_error,
        }

    def _mcp_fields(payload: Any) -> dict[str, Any]:
        if not isinstance(payload, Mapping):
            raise HTTPException(status_code=422, detail="expected an object")
        label = str(payload.get("label", "")).strip()
        if not 1 <= len(label) <= 80:
            raise HTTPException(
                status_code=422, detail="a server needs a label of 1 to 80 characters"
            )
        transport = str(payload.get("transport", "")).strip()
        args = payload.get("args") or []
        if not isinstance(args, (list, tuple)) or any(
            not isinstance(item, str) for item in args
        ):
            raise HTTPException(status_code=422, detail="args is a list of strings")
        return {
            "label": label,
            "transport": transport,
            "url": (str(payload["url"]).strip() if payload.get("url") else None),
            "command": (
                str(payload["command"]).strip() if payload.get("command") else None
            ),
            "args": [str(item) for item in args],
            "header_credential_id": payload.get("header_credential_id") or None,
            "env_credential_id": payload.get("env_credential_id") or None,
        }

    # ----------------------------------------------------------- 08: skills
    @router.get("/skills")
    async def list_skills(user: Any = Depends(current_user)) -> dict[str, Any]:
        """The four built-ins for everybody, plus this caller's own packs.

        Anonymous is allowed here, and only here among the attachment routes:
        the built-ins are committed files describing how to use this product,
        and a `SYNTHETIC=1` instance or a bare checkout has to be able to draw
        the palette. A signed-in caller additionally sees their own.
        """

        store = skill_store()
        owner = owner_of(user)
        if store is None:
            return {"skills": [pack.summary() for pack in builtin_skill_packs()]}
        # Through `_attachment` so an unreadable body answers 500 with its path
        # rather than an anonymous 500 with nothing an author can act on.
        return {
            "skills": [
                pack.summary() for pack in _attachment(lambda: store.list(owner))
            ]
        }

    @router.get("/skills/{skill_id}")
    async def get_skill(
        skill_id: str, user: Any = Depends(current_user)
    ) -> dict[str, Any]:
        store = skill_store()
        if store is None:
            for pack in builtin_skill_packs():
                if pack.id == skill_id:
                    return pack.detail()
            raise _no_store()
        return _attachment(lambda: store.get(owner_of(user), skill_id)).detail()

    @router.post("/skills", status_code=201)
    async def create_skill(
        request: Request, user: Any = Depends(current_user)
    ) -> dict[str, Any]:
        """Parse with CrewAI's own parser and refuse with CrewAI's own sentence.

        There is no second validator here on purpose: `SkillFrontmatter` owns
        the name pattern and the description ceiling, so a pack this service
        accepts is exactly a pack the package will load, and there is no
        wording of ours to drift away from theirs.
        """

        owner = require_owner(user)
        store = skill_store()
        if store is None:
            raise _no_store()
        payload = await _json_body(request)
        body = payload.get("body") if isinstance(payload, Mapping) else None
        if not isinstance(body, str) or not body.strip():
            raise HTTPException(
                status_code=422, detail="post the SKILL.md text as `body`"
            )
        return _attachment(lambda: store.create(owner, body)).detail()

    @router.put("/skills/{skill_id}")
    async def update_skill(
        skill_id: str, request: Request, user: Any = Depends(current_user)
    ) -> dict[str, Any]:
        owner = require_owner(user)
        store = skill_store()
        if store is None:
            raise _no_store()
        payload = await _json_body(request)
        body = payload.get("body") if isinstance(payload, Mapping) else None
        if not isinstance(body, str) or not body.strip():
            raise HTTPException(
                status_code=422, detail="post the SKILL.md text as `body`"
            )
        return _attachment(lambda: store.update(owner, skill_id, body)).detail()

    @router.delete("/skills/{skill_id}", status_code=204)
    async def delete_skill(skill_id: str, user: Any = Depends(current_user)) -> Response:
        owner = require_owner(user)
        store = skill_store()
        if store is None:
            raise _no_store()
        _attachment(lambda: store.delete(owner, skill_id))
        return Response(status_code=204)

    @router.post("/skills/import", status_code=201)
    async def import_skill(
        request: Request, user: Any = Depends(current_user)
    ) -> dict[str, Any]:
        """A zip holding one `SKILL.md`, and no `scripts/` directory.

        The archive is refused on its COMPRESSED size before anything is
        expanded, because a zip bomb is small until it is read. A `scripts/`
        entry is refused by name: a skill is knowledge, `AGENTS.md:67` stands,
        and nothing a user uploads executes here - so a pack that ships a script
        is a pack whose author expects something this product will not do, and
        importing it silently minus the scripts would be worse than refusing it.
        """

        owner = require_owner(user)
        store = skill_store()
        if store is None:
            raise _no_store()
        raw = await _archive_bytes(request)
        try:
            body = read_pack_zip(raw)
        except SkillError as exc:
            # The scripts refusal carries a CODE as well as a sentence, because
            # plan 08's C8 request names one and a client that wants to say
            # something specific about it needs to recognise it. It is not a
            # canvas problem code and is deliberately not declared beside them:
            # an import-time refusal never lands on a node, so the problems dock
            # has nothing to anchor it to and the client mirror nothing to draw.
            code = (
                SKILL_IMPORT_SCRIPTS_CODE
                if "scripts directory" in str(exc)
                else None
            )
            raise HTTPException(
                status_code=422,
                detail=(
                    {"code": code, "message": str(exc)} if code else str(exc)
                ),
            ) from exc
        return _attachment(lambda: store.create(owner, body)).detail()

    async def _archive_bytes(request: Request) -> bytes:
        """The zip, whether it arrived multipart or as a raw body.

        Both, because the plan says multipart and a raw `application/zip` POST
        is what every command-line client will send; accepting one and refusing
        the other would be a route that works only from the browser we happened
        to write.
        """

        content_type = request.headers.get("content-type", "")
        if content_type.startswith("multipart/form-data"):
            form = await request.form()
            for value in form.values():
                read = getattr(value, "read", None)
                if read is not None:
                    return await read()
            raise HTTPException(status_code=422, detail="attach the zip as a file")
        return await request.body()

    async def _json_body(request: Request) -> Mapping[str, Any]:
        try:
            payload = await request.json()
        except Exception as exc:
            raise HTTPException(status_code=422, detail="expected a JSON object") from exc
        if not isinstance(payload, Mapping):
            raise HTTPException(status_code=422, detail="expected a JSON object")
        return payload

    return router


#: How much of an author's own label a refusal may quote back. Labels are
#: bounded by `BUILDER_MAX_LABEL_CHARS` already; this is the sentence's bound,
#: not the schema's, and it is short because the label is the subject of the
#: sentence rather than its content.
_REFUSAL_LABEL_CHARS = 48


def _named_subject(location: tuple[Any, ...], payload: Mapping[str, Any] | None) -> str:
    """`nodes.3` -> `the "Docs" mcp node`, when the payload can say so.

    D-15-29. A refusal reading `nodes.3.skill_id: Field required` names an
    array index for a node the canvas calls Skill, and a field the author never
    typed. Every other refusal in this feature names something the author can
    see - the delete 409 says `"Deletable" is live as v1 and cannot be deleted;
    unpublish it first` - and the location is the one thing standing between
    this one and the same standard.

    The label is the author's own text and is quoted back deliberately: it is
    the whole point, it is already bounded by the schema, and it is bounded
    again here. Nothing else from the payload is echoed - the module's rule
    against reflecting an uploaded body is unchanged, and the VALUE that failed
    is still never named.

    Returns "" when the payload cannot identify the entry, which is what puts
    the raw dotted location back: an ugly location beats an invented one.
    """

    if not isinstance(payload, Mapping) or len(location) < 2:
        return ""
    collection, index = location[0], location[1]
    if collection not in ("nodes", "edges") or not isinstance(index, int):
        return ""
    entries = payload.get(collection)
    if not isinstance(entries, (list, tuple)) or not 0 <= index < len(entries):
        return ""
    entry = entries[index]
    if not isinstance(entry, Mapping):
        return ""
    if collection == "edges":
        source, target = entry.get("source"), entry.get("target")
        if isinstance(source, str) and isinstance(target, str):
            return f"the edge from {_quoted(source)} to {_quoted(target)}"
        return f"edge {index + 1} of {len(entries)}"
    label = entry.get("label")
    kind = entry.get("kind")
    named = _quoted(label) if isinstance(label, str) and label.strip() else ""
    kinded = f"{kind} " if isinstance(kind, str) and kind.strip() else ""
    if named:
        return f"the {named} {kinded}node".replace("  ", " ")
    return f"{kinded}node {index + 1} of {len(entries)}".strip()


def _quoted(text: str) -> str:
    """One bounded, control-character-free quotation of author text."""

    cleaned = "".join(character for character in text if character >= " ")
    return f'"{cleaned[:_REFUSAL_LABEL_CHARS].strip()}"'


def _first_schema_error(
    exc: Exception, *, payload: Mapping[str, Any] | None = None
) -> str:
    """One location and one message, never the offending input.

    The same reasoning as `_validation_detail` in `app.py`: pydantic's full
    error list is unbounded and echoes what was sent, which is the last thing
    to reflect back at a client that may have sent a quarter of a megabyte.

    `payload` is optional and is used only to turn an array index into a name
    the author can see - see `_named_subject`. Without it the sentence is
    exactly what it was, which is what every caller that has no payload to hand
    still gets.
    """

    errors = getattr(exc, "errors", None)
    if not callable(errors):
        return "document failed validation"
    reported = errors()
    if not reported:
        return "document failed validation"
    first = reported[0]
    raw_location = tuple(first.get("loc", ()))
    location = ".".join(str(part) for part in raw_location) or "document"
    message = str(first.get("msg", "is invalid"))[:200]
    subject = _named_subject(raw_location, payload)
    if subject:
        # The dotted location is KEPT, in brackets. It is the only thing a
        # developer reading a bug report can act on, and dropping it would
        # trade one unreadable audience for another.
        field = ".".join(str(part) for part in raw_location[2:]) or "this entry"
        return f"{subject}: {field[:80]} - {message} ({location[:120]})"
    # The location can name a key the CLIENT chose (`extra_forbidden` reports
    # the extra key), so it is bounded like the message is.
    return f"{location[:120]}: {message}"


def _import_envelope(raw: bytes) -> "BuilderImportRequest":
    """The D1 envelope out of an uploaded file, or a 422 that echoes none of it.

    Three refusals, each one sentence (D-15-9):

    * over `MAX_BUILDER_DOCUMENT_BYTES` - **413**, the same figure `parse`
      quotes, measured on the bytes rather than on the declared length so a
      chunked upload meets the same ceiling;
    * not JSON, or JSON that is not an object - **422** naming what it is;
    * an object the envelope schema refuses - **422** with
      `_first_schema_error`'s one location and one message.

    `json.loads` is called on the bytes here rather than letting FastAPI do it
    for a typed parameter, because FastAPI's refusal is pydantic's whole error
    list with the offending `input` reflected back, and the input is a file
    somebody uploaded.
    """

    from fastapi import HTTPException

    limit = project_config.MAX_BUILDER_DOCUMENT_BYTES
    if len(raw) > limit:
        raise HTTPException(
            status_code=413,
            detail=f"a builder document is limited to {limit} bytes; this file is {len(raw)}",
        )
    try:
        payload = json.loads(raw)
    except ValueError as exc:
        # `JSONDecodeError.msg` is the decoder's own phrase ("Expecting value")
        # and the position; neither quotes the file.
        where = (
            f" ({exc.msg} at line {exc.lineno} column {exc.colno})"
            if isinstance(exc, json.JSONDecodeError)
            else ""
        )
        raise HTTPException(
            status_code=422, detail=f"the file is not JSON{where}"
        ) from exc
    if not isinstance(payload, Mapping):
        raise HTTPException(
            status_code=422,
            detail=(
                "an import is a JSON object carrying `export` and `document`; "
                f"this file is a JSON {type(payload).__name__}"
            ),
        )
    try:
        return BuilderImportRequest.model_validate(payload)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=_first_schema_error(exc)) from exc


def _with_tail(base: str, tail: str) -> str:
    """`base + tail`, the base trimmed from the front so the tail survives.

    `BUILDER_MAX_NAME_CHARS` bounds the schema, and a name already at the bound
    would otherwise fail `parse` on the duplicate of a perfectly valid document
    - a 422 the author cannot act on, about a field they did not type. The
    tail is the distinguishing word, so it is the part that must not go.
    """

    limit = project_config.BUILDER_MAX_NAME_CHARS
    room = limit - len(tail)
    if len(base) > room:
        base = base[:room].rstrip()
    return f"{base}{tail}"


def copy_name(name: str) -> str:
    """`"<name> copy"`, trimmed from the front so the suffix always survives."""

    return _with_tail(str(name), COPY_SUFFIX)


def distinct_name(base: str, suffix: str, taken: Iterable[str]) -> str:
    """`base + suffix`, or `base + suffix + " 2"`, `" 3"`, ... - the first not in `taken`.

    Round 2, D-15-4. The library is a flat list with no folder and no id on
    show, so a name is the only thing an author picks a row by, and two rows
    that read the same are two rows nobody can tell apart at the moment they
    are choosing which to delete. The base is what gets trimmed for the bound;
    the suffix and the number are the distinguishing words and always survive
    - `_with_tail` is applied to the whole tail, never to a candidate that
    already carries it, or `imported` would come back as `importe 2`.
    """

    used = set(taken)
    candidate = _with_tail(base, suffix)
    if candidate not in used:
        return candidate
    number = 2
    while True:
        attempt = _with_tail(base, f"{suffix} {number}")
        if attempt not in used:
            return attempt
        number += 1


def import_name(name: str, taken: Iterable[str]) -> str:
    """The file's own name, unless the caller already has one; then `<name> imported`, numbered."""

    used = set(taken)
    if name not in used:
        return name
    return distinct_name(name, IMPORT_SUFFIX, used)


def _names_of(store: BuilderDocumentStore, owner: str | None) -> list[str]:
    """Every name in the caller's library, for `distinct_name` to avoid."""

    from brief_crew.builder.store import MAX_LIST_LIMIT

    return [row.name for row in store.list(user_id=owner, limit=MAX_LIST_LIMIT)]


def _version_source(request: BuilderDocumentRequest) -> str:
    """The stored provenance of a save, composed from what the client declared.

    The client says WHICH gesture (`save`, `autosave`, `restore`) and, for a
    restore, which version it put back; the server writes the sentence, so
    the vocabulary in the browser is the server's and a stale client cannot
    invent a fourth kind of row.
    """

    if request.source == "restore":
        return f"restored from v{request.restored_from}" if request.restored_from else "restored"
    if request.source == "autosave":
        return "autosaved"
    return "saved"


def _version_status(version: int, history: VersionHistory, live_version: int | None) -> str:
    """`published` for the version running or the published head; else `draft`.

    Two versions can legitimately be `published` at once: the head, after a
    publish, and an OLDER version this service is still running because the
    head was edited afterwards - `store.save` returns the head to draft while
    the registered workflow keeps the version whose budget was priced. The
    browser has to show both, or an author sees `draft` on the graph that is
    answering launches.
    """

    if live_version is not None and version == live_version:
        return STATUS_PUBLISHED
    if version == history.head_version and history.status == STATUS_PUBLISHED:
        return STATUS_PUBLISHED
    return "draft"


def _requested_version(payload: Mapping[str, Any]) -> int:
    """The version an unsaved document says it was edited from, or a 422.

    `/validate` is the only endpoint that reads a version off the request BODY
    rather than off a typed field - `save` has `expected_version: int | None`
    and `publish` has a `Query(ge=1)`, both of which pydantic refuses before
    the handler runs - so it was the one place a bare `int(...)` had nothing
    standing in front of it. `{"version": "soon"}` raised ValueError inside the
    handler and came back a **500**, and the canvas treats every 5xx as
    `unreachable`: the symptom was a document that mysteriously would not
    validate, pointing at the network rather than at a field.

    Refusing beats guessing even though the number barely matters here - `parse`
    overwrites it and the server owns the real one. A body that cannot say
    which version it was editing is malformed, and one sentence saying so costs
    nothing.
    """

    # Imported here, the way `_guarded` does it: FastAPI is an optional
    # dependency and the module-level import lives inside the router factory.
    from fastapi import HTTPException

    raw = payload.get("version")
    if not raw:
        # 0, "", None and a missing key all mean "the author did not say", and
        # FIRST_VERSION is what `parse` would have clamped them to anyway.
        return FIRST_VERSION
    try:
        return max(FIRST_VERSION, int(raw))
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=422,
            detail=f"version must be a whole number; this document carries {raw!r}",
        ) from None


def _guarded(action: Callable[[], Any]) -> Any:
    """Run a store call, translating its four refusals into HTTP.

    404 for both "no such document" and "not yours", which is one exception on
    purpose - a 403 confirms the document exists, and the whole point of the
    distinction `require_own_run` draws is that a stranger hears nothing.

    The ONE 403 is `DocumentReadOnly`, for an unowned row a signed-in caller
    tried to write (D-15-7). It confirms nothing a stranger could not already
    read: an unowned row is visible to everyone, so the only fact the status
    adds is "and it is not yours to change", with Duplicate named as the way
    to own one.
    """

    from fastapi import HTTPException

    try:
        return action()
    except DocumentNotFound as exc:
        # The constant when the DOCUMENT is absent or not this caller's. The
        # store's own sentence when the document is visible and the VERSION is
        # not (D-15-8): `_guarded` used to flatten that too, so an author
        # looking at v2 who asked for `?version=99` was told "document not
        # found" about a document on their screen, and went looking for the
        # wrong thing. The store sets `version` only after the visibility
        # check has passed, which is what makes reading it here safe.
        detail = "document not found" if exc.version is None else str(exc)
        raise HTTPException(status_code=404, detail=detail) from exc
    except DocumentReadOnly as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except DocumentVersionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except DocumentTooLarge as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except BuilderStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _register_runtime(
    registry: RunRegistry, workflow: BuilderWorkflow, runner: Runner
) -> None:
    """The SIXTH registration site: this application's own runtime map.

    Sixth, not fourth - it said fourth until 2026-09-02, and the count has three
    different right answers depending on what you are counting, which is how it
    drifted. `graph.register_builder_workflow` writes FIVE (`GRAPHS`,
    `NODE_REGISTRIES`, `WORKFLOWS`, `BUILDER_WORKFLOWS`, and the reserved-key
    map in `config`); a PUBLISH writes those five plus this one, which is the
    six `config.py` enumerates beside `BUILDER_REHYDRATE_PUBLISHED`. This is the
    only one that lives on the app rather than on a module, which is exactly why
    it is the one a count keeps leaving out.

    `registry.workflows` is a plain mutable dict, which is what makes a runtime
    registration possible at all after `create_app` has returned. A registry
    built WITHOUT a workflow map is the older single-workflow shape - it answers
    for any id from one default runtime - and adding an entry to it would change
    what every OTHER workflow resolves to, so that shape is refused rather than
    quietly upgraded.
    """

    if not registry.workflows:
        raise BuilderServiceUnavailable(
            "this service was built with a single-workflow registry, which has no "
            "map to register a builder graph into"
        )
    registry.workflows[workflow.workflow_id] = WorkflowRuntime(
        graph_version=workflow.graph_version,
        node_registry=workflow.node_registry,
        runner=runner,
        input_field=workflow.input_field,
    )


def _unregister_runtime(registry: RunRegistry, workflow_id: str) -> None:
    if registry.workflows:
        registry.workflows.pop(workflow_id, None)


def _unregister(registry: RunRegistry, workflow_id: str) -> None:
    """Take a builder graph out of both halves, tolerating an unpublished one."""

    try:
        unregister_builder_workflow(workflow_id)
    except ValueError:
        # A built-in id. Unreachable from these routes - `BUILDER_ID_PATTERN`
        # cannot spell `idea-validator` - and refused rather than trusted.
        raise
    _unregister_runtime(registry, workflow_id)
