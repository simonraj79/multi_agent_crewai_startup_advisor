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

from collections.abc import Mapping
from datetime import datetime
import json
from typing import Any, Callable

from pydantic import BaseModel, ConfigDict, Field

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
    strip_for_export,
)
from brief_crew.builder.runtime import BUILDABLE_BUILDER_CREW_IDS, BUILDER_AGENT_LIBRARY
from brief_crew.builder.store import (
    BuilderDocumentStore,
    BuilderStoreError,
    DEFAULT_LIST_LIMIT,
    DocumentNotFound,
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
    """One row of the version browser."""

    model_config = ConfigDict(extra="forbid")

    version: int
    #: `published` for the version this service is running or the head that
    #: was published; `draft` for every other version. A version has no status
    #: column of its own - see `store.VersionHistory`.
    status: str
    created_at: datetime
    bytes: int


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

    from fastapi import APIRouter, Depends, HTTPException, Query, Response

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
        document = parse(
            request.document, document_id=new_document_id(), version=FIRST_VERSION
        )
        stored = _guarded(lambda: store.create(document, user_id=owner_of(user)))
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
    )
    async def import_document(
        request: BuilderImportRequest,
        response: Response,
        user: Any = Depends(current_user),
    ) -> BuilderDocumentModel:
        """A `.builder.json` becomes a NEW draft owned by the caller. Always new.

        Never an overwrite (D2): the file carries no id worth honouring - the
        export dropped it, and a hand-edited one is somebody else's row - so
        the importer mints an id the way `create` does and the version is
        `FIRST_VERSION`. The document goes through `upgrade_document` first, so
        a v1 file imports unchanged today and a v2 file imports the day C1
        lands (ruling 4), and then through `strip_for_export` AGAIN on the way
        in: the export made the file secret-free by construction, but nothing
        makes a file honest, and a `credential_id` typed into one by hand must
        not become a reference to a credential the importer does not own.

        `needs_credentials` is RE-DERIVED from that inbound strip and nothing
        else. The envelope's own list is accepted and ignored: a client may
        send `[]`, or the list the export wrote, or anything at all, and none
        of it is trusted - the file's nulled `credential_id` / `server_id`
        keys are the evidence, and the strip reads them directly. Kept to node
        ids the document actually has, once each, so the client can point at
        every one.
        """

        if request.export not in KNOWN_SCHEMAS:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"export must be one of {list(KNOWN_SCHEMAS)}; this file says "
                    f"{request.export[:64]!r}"
                ),
            )
        store = require_store()
        raw, stripped_nodes = strip_for_export(upgrade_document(request.document))
        if not raw.get("name") and request.name:
            raw["name"] = request.name
        document = parse(raw, document_id=new_document_id(), version=FIRST_VERSION)
        stored = _guarded(lambda: store.create(document, user_id=owner_of(user)))
        response.headers["Location"] = f"{BUILDER_API_PREFIX}/workflows/{stored.id}"
        node_ids = {node.id for node in document.nodes}
        needs_credentials = [
            node_id for node_id in dict.fromkeys(stripped_nodes) if node_id in node_ids
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
        source = _guarded(
            lambda: store.load(document_id, version=version, user_id=owner_of(user))
        )
        payload = source.document.model_dump(mode="json", by_alias=True)
        payload["name"] = copy_name(source.document.name)
        payload.pop("budget", None)
        document = parse(payload, document_id=new_document_id(), version=FIRST_VERSION)
        stored = _guarded(lambda: store.create(document, user_id=owner_of(user)))
        response.headers["Location"] = f"{BUILDER_API_PREFIX}/workflows/{stored.id}"
        return judged(stored)

    @router.delete(
        "/workflows/{document_id}", status_code=204, response_class=Response
    )
    async def delete_document(
        document_id: str, user: Any = Depends(current_user)
    ) -> Response:
        """Delete a graph and every version of it - unless it is launchable.

        A head that is `published` AND registered on this service is refused
        with a **409**, not unpublished on the way out (PLANS.md decision 24,
        built on the plan's recommendation). Deleting it would take the graph
        out of the registration maps and the row out of the table in one
        request, which is the one shape the boot sweep can never put back and
        the one shape a run queued a moment earlier compiles against nothing.
        The sentence says what to do instead: a save returns the head to
        `draft`, and a draft deletes.

        For a draft, or a published row this process never registered (one the
        boot sweep skipped), the order is unchanged: unregister, then delete.
        Unregistering first would leave a window in which the graph is
        unlaunchable but still stored; deleting first would leave one in which
        it is launchable but gone. The second is worse - a run would compile
        against a document nobody can read - so the store row goes last.
        """

        store = require_store()
        stored = _guarded(lambda: store.load(document_id, user_id=owner_of(user)))
        if stored.status == STATUS_PUBLISHED and registered_workflow(document_id) is not None:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"document {document_id} is published and registered as a "
                    "launchable workflow, so it cannot be deleted; save a new "
                    "version to return it to draft, then delete it"
                ),
            )
        _unregister(registry, document_id)
        _guarded(lambda: store.delete(document_id, user_id=owner_of(user)))
        return Response(status_code=204)

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
        stored = _guarded(
            lambda: store.load(document_id, version=version, user_id=owner_of(user))
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
    return f"{location}: {str(first.get('msg', 'is invalid'))[:200]}"


def copy_name(name: str) -> str:
    """`"<name> copy"`, trimmed from the front so the suffix always survives.

    `BUILDER_MAX_NAME_CHARS` bounds the schema, and a name already at the bound
    would otherwise fail `parse` on the duplicate of a perfectly valid document
    - a 422 the author cannot act on, about a field they did not type.
    """

    limit = project_config.BUILDER_MAX_NAME_CHARS
    base = str(name)
    room = limit - len(COPY_SUFFIX)
    if len(base) > room:
        base = base[:room].rstrip()
    return f"{base}{COPY_SUFFIX}"


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
    """Run a store call, translating its three refusals into HTTP.

    404 for both "no such document" and "not yours", which is one exception on
    purpose - a 403 confirms the document exists, and the whole point of the
    distinction `require_own_run` draws is that a stranger hears nothing.
    """

    from fastapi import HTTPException

    try:
        return action()
    except DocumentNotFound as exc:
        raise HTTPException(status_code=404, detail="document not found") from exc
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
