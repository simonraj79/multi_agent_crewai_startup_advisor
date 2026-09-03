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
from typing import Any, Callable, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from brief_crew import config as project_config
from brief_crew.builder import BudgetEstimate, Problem, estimate_budget
# `document_problems` and never `validate_document`: the second answers about
# structure and price only, and an author who names a crew this deployment
# cannot construct has to be told here rather than at the moment Publish
# refuses a document the canvas has been calling clean all afternoon.
from brief_crew.builder.compiler import BuilderCompileError, document_problems
from brief_crew.builder.descriptor import (
    BuilderWorkflow,
    build_builder_workflow,
    builder_graph_descriptor,
    static_cost_over_ceiling,
)
from brief_crew.builder.document import BuilderDocument
from brief_crew.builder.export import (
    export_content_disposition,
    export_envelope,
    nulled_reference_nodes,
    strip_for_export,
)
from brief_crew.builder.runtime import BUILDABLE_BUILDER_CREW_IDS, BUILDER_AGENT_LIBRARY
from brief_crew.builder.store import (
    BuilderDocumentStore,
    BuilderStoreError,
    DEFAULT_LIST_LIMIT,
    DocumentNotFound,
    DocumentReadOnly,
    DocumentTooLarge,
    DocumentVersionConflict,
    STATUS_PUBLISHED,
    StoredDocument,
    VersionHistory,
    new_document_id,
)
from brief_crew.builder.upgrade import KNOWN_SCHEMAS, upgrade_document
from brief_crew.service.graph import (
    builder_workflow as registered_workflow,
    register_builder_workflow,
    unregister_builder_workflow,
)
from brief_crew.service.models import GraphDescriptor
from brief_crew.service.registry import RunRegistry, WorkflowRuntime
from brief_crew.service.builder_runner import BuilderRunnerFactory
from brief_crew.service.runner import Runner


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

    @classmethod
    def of(cls, problem: Problem) -> "BuilderProblemModel":
        return cls(
            code=problem.code,
            severity=problem.severity,
            message=problem.message,
            node_id=problem.node_id,
            edge_id=problem.edge_id,
        )


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


class BuilderVocabularyModel(BaseModel):
    """Everything the palette and the config panel are allowed to offer.

    Served rather than duplicated in TypeScript, for the reason
    `data/serverLimits.ts` already documents about `MAX_RUN_INPUT_CHARS`: a
    canvas offering a transform op the compiler does not have is a 422 the
    author cannot act on, and a canvas missing one is a feature nobody can
    reach.
    """

    model_config = ConfigDict(extra="forbid")

    schema_id: str
    node_kinds: list[str]
    tiers: list[str]
    agent_ids: list[str]
    crew_ids: list[str]
    research_tools: list[str]
    transform_ops: list[str]
    router_comparisons: list[str]
    router_otherwise: str
    result_body_keys: list[str]
    bounds: dict[str, float]


def _vocabulary() -> BuilderVocabularyModel:
    return BuilderVocabularyModel(
        schema_id=project_config.BUILDER_DOCUMENT_SCHEMA,
        node_kinds=["input", "agent", "crew", "gate", "router", "transform", "output"],
        tiers=["cheap", "escalation"],
        agent_ids=sorted(BUILDER_AGENT_LIBRARY),
        # The BUILDABLE ones, not every registered class: `synthesis` and
        # `report` are refused by `library_problems`, so offering them in a
        # picker would be advertising a document that cannot publish.
        crew_ids=sorted(BUILDABLE_BUILDER_CREW_IDS),
        research_tools=sorted(project_config.BUILDER_RESEARCH_TOOLS),
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
        },
    )


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

    from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

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
                status_code=422, detail=_first_schema_error(exc)
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

    return router


def _first_schema_error(exc: Exception) -> str:
    """One location and one message, never the offending input.

    The same reasoning as `_validation_detail` in `app.py`: pydantic's full
    error list is unbounded and echoes what was sent, which is the last thing
    to reflect back at a client that may have sent a quarter of a megabyte.
    """

    errors = getattr(exc, "errors", None)
    if not callable(errors):
        return "document failed validation"
    reported = errors()
    if not reported:
        return "document failed validation"
    first = reported[0]
    location = ".".join(str(part) for part in first.get("loc", ())) or "document"
    # The location can name a key the CLIENT chose (`extra_forbidden` reports
    # the extra key), so it is bounded like the message is.
    return f"{location[:120]}: {str(first.get('msg', 'is invalid'))[:200]}"


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
