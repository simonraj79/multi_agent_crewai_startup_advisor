"""FastAPI application factory for M1 HTTP and WebSocket transport.

FastAPI is an optional dependency. Importing this module is safe without it;
calling ``create_app`` reports the exact installation blocker.
"""

import asyncio
from collections import OrderedDict
from collections.abc import Mapping, Sequence
from contextlib import asynccontextmanager
from io import BytesIO
import json
import os
from pathlib import Path
import re
from threading import Lock
from time import monotonic
from types import MappingProxyType
from typing import Any, Callable
import zipfile

import yaml

from pydantic import ValidationError

from brief_crew import config as project_config
from brief_crew.config import (
    RUN_RATE_LIMIT_KEY_MAX_CHARS,
    WS_MAX_GATE_FIELD_CHARS,
    WS_MAX_GATE_FIELDS,
    WS_MAX_MESSAGE_BYTES,
)

from brief_crew.events import FrameKind, MAX_REPLAY_LIMIT
from brief_crew.service.auth import (
    AuthenticatedUser,
    AuthError,
    auth_is_required,
    bearer_token_from_header,
    verify_token,
)
from brief_crew.service.graph import (
    BRIEF_GRAPH,
    BRIEF_NODE_REGISTRY,
    BRIEF_WORKFLOW,
    BUILDER_WORKFLOWS,
    GRAPHS,
    NODE_REGISTRIES,
    VALIDATOR_GRAPH,
    VALIDATOR_NODE_REGISTRY,
    VALIDATOR_WORKFLOW,
    WORKFLOWS,
    workflow_visible_to,
)
from brief_crew.service.models import (
    CancelRunResponse,
    CreateRunRequest,
    CreateRunResponse,
    ErrorResponse,
    FramePage,
    GateReplyMessage,
    GateReplyRequest,
    GateReplyResponse,
    GraphDescriptor,
    HealthResponse,
    RunStatusResponse,
    WorkflowSummary,
    RunHistoryEntry,
    RunHistoryPage,
)
from brief_crew.service.registry import (
    GateFieldError,
    RunAdmissionError,
    RunBusyError,
    RunRecord,
    RunRegistry,
    UnknownWorkflowError,
    WorkflowRuntime,
)
from brief_crew.service.runner import (
    BriefFlowRunner,
    Runner,
    SyntheticRunner,
    SyntheticValidatorRunner,
    ValidatorFlowRunner,
)
# Module scope rather than inside `create_app`, unlike the store and the router
# below it: `create_app`'s signature annotates a parameter with
# `BuilderRunnerFactory`, this module has no `from __future__ import
# annotations` (see the note above `create_builder_router` for why that
# omission is load-bearing for FastAPI), so the name must resolve at import.
# It costs nothing extra - this pulls in no service extra, only `crewai` and
# `yaml`, both of which `service.registry` above already required.
from brief_crew.service.builder_runner import (
    BuilderFlowRunner,
    BuilderRunnerFactory,
    synthetic_builder_runner,
)


class ServiceDependencyError(RuntimeError):
    pass


# `builder_runner_unavailable` used to stand here: a placeholder runner that
# raised, so a published graph could be launched, admitted and rate limited and
# then fail with a sentence saying no runner had been injected yet. One exists
# now (`service/builder_runner.py`), which makes the placeholder unreachable -
# and an unreachable fallback is dead code that reads like a supported mode.


# The request-input key each BUILT-IN workflow reads, for a registry whose
# ``WorkflowRuntime`` predates ``input_field`` - which is every one constructed
# by hand in ``tests/`` and by any caller passing ``registry=`` to
# ``create_app``. ``create_app``'s own registration declares the field on the
# runtime; this is the compatibility half, not the source of truth, and it is
# deliberately NOT a default: an id in neither is refused by name rather than
# quietly asked for ``topic``.
BUILTIN_WORKFLOW_INPUT_FIELDS: Mapping[str, str] = MappingProxyType(
    {
        BRIEF_GRAPH.id: "topic",
        VALIDATOR_GRAPH.id: "idea",
    }
)


def workflow_input_field(workflow_id: str, runtime: WorkflowRuntime) -> str | None:
    """The request-input key ``workflow_id`` reads, or ``None`` if undeclared.

    The runtime's own declaration wins; the built-in table answers for a
    runtime that predates the field. Returning ``None`` rather than a fallback
    string is the point of the whole function: ``create_run`` derived this as
    ``"idea" if workflow_id == VALIDATOR_GRAPH.id else "topic"``, so a third
    workflow was told ``inputs.topic must contain non-whitespace text`` about a
    field it had never heard of, and no reply the operator could send would
    have satisfied it.
    """

    if runtime.input_field is not None:
        return runtime.input_field
    return BUILTIN_WORKFLOW_INPUT_FIELDS.get(workflow_id)


def run_history_label(registry: RunRegistry, workflow_id: str, inputs: Mapping[str, Any]) -> str:
    """The one line of prose the history sidebar shows for a run.

    It reads the key the WORKFLOW declares. `inputs.get("idea") or
    inputs.get("topic")` is the same two-literal guess `create_run` used to
    make and that `workflow_input_field` was written to retire: it is right for
    exactly the two built-in workflows and blank for every other, so a builder
    graph whose input field is anything else drew an EMPTY row - which reads as
    a run that lost its inputs rather than as a sidebar asking the wrong key.

    The two literals survive only as the fallback, for a row whose workflow
    declares nothing. And an unknown workflow is answered rather than raised:
    a builder graph published before the process restarted still has rows in
    this table, and a history page must not fail whole because one of its rows
    names a workflow this process has never heard of.
    """

    field: str | None = None
    try:
        runtime = registry.workflow_runtime(workflow_id)
    except UnknownWorkflowError:
        pass
    else:
        field = workflow_input_field(workflow_id, runtime)
    if field is not None:
        declared = inputs.get(field)
        if declared:
            return str(declared)
    return str(inputs.get("idea") or inputs.get("topic") or "")


def workflow_has_gates(workflow_id: str) -> bool:
    """Whether this workflow has a human gate there is any point skipping.

    Read off the descriptor, which gets ``human_feedback`` from CrewAI's own
    ``FlowDefinition`` rather than from anybody's opinion (``graph.py``'s
    ``_human_feedback_methods``) - so this asks the workflow instead of
    comparing its id to the validator's, and a third workflow that really does
    declare ``@human_feedback`` is no longer refused with a sentence its own
    graph contradicts.

    An id with no descriptor answers False, which is the fail-closed direction:
    ``gates="auto"`` runs a whole pipeline unattended, and a workflow the
    service cannot describe is not one to run that way.
    """

    descriptor = GRAPHS.get(workflow_id)
    if descriptor is None:
        return False
    return any(node.human_feedback for node in descriptor.nodes)


class RequestBodySizeLimitMiddleware:
    """Refuse an oversized request body before anything parses it.

    This endpoint is public and unauthenticated, and a 1 MB body reached the
    application with no 413 from any layer: Starlette read it, pydantic parsed
    it, and whatever survived became the prompt of an escalation-tier model.
    The check is on the declared ``Content-Length``, so it costs one header
    lookup and rejects before the body is read at all.

    Pure ASGI rather than ``BaseHTTPMiddleware`` so that WebSocket and lifespan
    scopes pass through untouched, and so the refusal can be written without
    building a request object for a request being thrown away.

    WARNING, and it is why the per-field bounds in ``models.py`` exist as well:
    a chunked request declares no ``Content-Length`` and is NOT caught here.

    ``overrides`` raises the bound for one path prefix and nothing else. There
    is exactly one: a builder document is legitimately bigger than any gate
    reply or idea will ever be - 24 nodes with positions, labels, prompts and
    router rules - and raising the GLOBAL bound to fit it would also raise it
    on the endpoint that spends money, where a quarter of a megabyte of
    ``inputs`` is a cost rather than a drawing. The longest matching prefix
    wins, so a nested route cannot accidentally inherit a looser bound from a
    shorter one.
    """

    def __init__(
        self,
        app: Any,
        *,
        max_bytes: int,
        overrides: Sequence[tuple[str, int]] = (),
    ) -> None:
        self.app = app
        self.max_bytes = int(max_bytes)
        # Longest prefix first, so the lookup is the first match rather than a
        # scan that has to compare lengths.
        self.overrides: tuple[tuple[str, int], ...] = tuple(
            sorted(
                ((str(prefix), int(limit)) for prefix, limit in overrides),
                key=lambda entry: len(entry[0]),
                reverse=True,
            )
        )

    def limit_for(self, path: str) -> int:
        for prefix, limit in self.overrides:
            if path.startswith(prefix):
                return limit
        return self.max_bytes

    @staticmethod
    def _declared_length(scope: Mapping[str, Any]) -> int | None:
        for name, value in scope.get("headers", ()):
            if name == b"content-length":
                try:
                    return int(value)
                except ValueError:
                    return None
        return None

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope.get("type") == "http":
            declared = self._declared_length(scope)
            limit = self.limit_for(str(scope.get("path", "")))
            if declared is not None and declared > limit:
                body = json.dumps(
                    {
                        "detail": (
                            "the request body is limited to "
                            f"{limit} bytes"
                        )
                    }
                ).encode("utf-8")
                await send(
                    {
                        "type": "http.response.start",
                        "status": 413,
                        "headers": [
                            (b"content-type", b"application/json"),
                            (b"content-length", str(len(body)).encode("ascii")),
                        ],
                    }
                )
                await send({"type": "http.response.body", "body": body})
                return
        await self.app(scope, receive, send)


class RunRateLimiter:
    """A thread-safe per-client token bucket over run creation only.

    Read the ``RUN_RATE_LIMIT_*`` block in ``config.py`` before relying on
    this. In one sentence: it is in-process and single-instance, its key is a
    client-writable header behind Render's proxy, and it therefore stops a
    runaway loop or a casual script but not somebody who is actually trying.
    The bound that holds against that is ``MAX_QUEUED_RUNS``, which is keyless.

    ``clock`` is injectable so the tests can prove refill and recovery without
    sleeping. Capacity 0 disables the limiter outright, which is the documented
    escape hatch for load testing.
    """

    __slots__ = (
        "_buckets",
        "_capacity",
        "_clock",
        "_lock",
        "_max_clients",
        "_refill_per_second",
    )

    def __init__(
        self,
        *,
        max_runs: int | None = None,
        window_seconds: float | None = None,
        max_clients: int | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        capacity = (
            project_config.RUN_RATE_LIMIT_MAX_RUNS
            if max_runs is None
            else int(max_runs)
        )
        window = (
            project_config.RUN_RATE_LIMIT_WINDOW_SECONDS
            if window_seconds is None
            else float(window_seconds)
        )
        if capacity < 0:
            raise ValueError("max_runs cannot be negative")
        if window <= 0:
            raise ValueError("window_seconds must be positive")
        self._capacity = float(capacity)
        self._refill_per_second = capacity / window
        self._max_clients = (
            project_config.RUN_RATE_LIMIT_MAX_CLIENTS
            if max_clients is None
            else int(max_clients)
        )
        if self._max_clients < 1:
            raise ValueError("max_clients must be positive")
        self._clock = monotonic if clock is None else clock
        # LRU by insertion order: the map is keyed by attacker-supplied text,
        # so it is bounded and the least recently seen client is evicted first.
        self._buckets: OrderedDict[str, tuple[float, float]] = OrderedDict()
        self._lock = Lock()

    @property
    def enabled(self) -> bool:
        return self._capacity >= 1.0

    def acquire(self, key: str) -> float:
        """Spend one token. Returns 0.0 when allowed, else seconds to wait."""
        if not self.enabled:
            return 0.0
        now = self._clock()
        with self._lock:
            tokens, last_seen = self._buckets.get(key, (self._capacity, now))
            elapsed = now - last_seen
            if elapsed > 0:
                tokens = min(
                    self._capacity, tokens + elapsed * self._refill_per_second
                )
            allowed = tokens >= 1.0
            if allowed:
                tokens -= 1.0
            self._buckets[key] = (tokens, now)
            self._buckets.move_to_end(key)
            while len(self._buckets) > self._max_clients:
                self._buckets.popitem(last=False)
        if allowed:
            return 0.0
        return (1.0 - tokens) / self._refill_per_second


def client_rate_limit_key(request: Any) -> str:
    """The identity a run-creation request is rate limited under.

    Advisory by construction. Behind Render's proxy the socket peer is the
    proxy, so X-Forwarded-For is the only thing that distinguishes one visitor
    from another - and the client writes it. Keying on the peer instead would
    put every visitor on earth in one bucket, which breaks the demo for the
    second person to click Launch; that trade is made in ``config.py`` under
    RUN_RATE_LIMIT_TRUST_FORWARDED_FOR.
    """
    if project_config.RUN_RATE_LIMIT_TRUST_FORWARDED_FOR:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            first = forwarded.split(",", 1)[0].strip()
            if first:
                return first[:RUN_RATE_LIMIT_KEY_MAX_CHARS]
    host = getattr(getattr(request, "client", None), "host", None)
    return (host or "unknown")[:RUN_RATE_LIMIT_KEY_MAX_CHARS]


def _etag_matches(if_none_match: str, etag: str) -> bool:
    """RFC 9110 §13.1.2 weak comparison of an ``If-None-Match`` list.

    Three things here are not obvious and each one silently turns every 304 back
    into a 200 if it is skipped:

    * The header is a **list**. A client that has seen two versions of a
      resource may send both, comma-separated.
    * Comparison is **weak** even when the tags are strong, so ``W/"abc"`` from
      a proxy that weakened the tag in transit must still match ``"abc"``. This
      is the opposite of ``If-Match``, which is strong.
    * ``*`` matches any existing representation.

    Anything unparseable simply fails to match, which degrades to the previous
    behaviour - a normal 200 with the full body - rather than to an error. A
    malformed cache header must never fail a request.
    """

    candidate = if_none_match.strip()
    if candidate == "*":
        return True
    for raw in candidate.split(","):
        tag = raw.strip()
        if tag.startswith(("W/", "w/")):
            tag = tag[2:].strip()
        if tag and tag == etag:
            return True
    return False


def _retry_after_header(seconds: float) -> dict[str, str]:
    """Retry-After is whole seconds, and never 0 - that reads as "now"."""
    return {"Retry-After": str(max(1, int(seconds) + (1 if seconds % 1 else 0)))}


class GateReplyError(Exception):
    """One refusal reason for one gate reply, shared by HTTP and the WebSocket.

    PRD F27/F37 requires both transports to reach ``registry.answer_gate``
    through a single code path, so they must also refuse for the same reasons.
    ``status_code`` is what the HTTP route returns; ``code`` is the machine
    token the socket sends. They are defined together here so the two surfaces
    cannot drift - in particular so a duplicate reply is a 409 on one and
    ``gate_conflict`` on the other, never a silent no-op on either.
    """

    __slots__ = ("code", "detail", "status_code")

    def __init__(self, *, code: str, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.status_code = status_code
        self.detail = detail


def _validation_detail(error: ValidationError) -> str:
    """A short, bounded description of the first schema failure.

    Pydantic's full error list is unbounded and echoes the offending input,
    which is exactly what a hostile client would like reflected back. One
    location plus one message is enough for a buggy client to fix itself.
    """
    errors = error.errors()
    if not errors:
        return "message failed validation"
    first = errors[0]
    location = ".".join(str(part) for part in first.get("loc", ())) or "message"
    return f"{location}: {str(first.get('msg', 'is invalid'))[:200]}"


def _model_from_config(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        model = value.get("model")
        return str(model) if model is not None else None
    return None


def _load_agent_configs() -> list[Mapping[str, Any]]:
    crews_directory = Path(__file__).resolve().parents[1] / "crews"
    configs: list[Mapping[str, Any]] = []
    for path in sorted(crews_directory.glob("*/config/agents.yaml")):
        loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(loaded, Mapping):
            raise RuntimeError(f"agent config must be a mapping: {path.name}")
        configs.append(loaded)
    return configs


def _assert_openrouter_startup_safety(
    agent_configs: Sequence[Mapping[str, Any]] | None = None,
) -> None:
    configured_models = {
        "CHEAP_MODEL": project_config.CHEAP_MODEL,
        "ESCALATION_MODEL": project_config.ESCALATION_MODEL,
    }
    for name, model in configured_models.items():
        if not isinstance(model, str) or not model.startswith("openrouter/"):
            raise RuntimeError(f"{name} must use the openrouter/ provider prefix")

    for config in agent_configs if agent_configs is not None else _load_agent_configs():
        for agent_name, value in config.items():
            if not isinstance(value, Mapping):
                continue
            for field_name in ("llm", "function_calling_llm"):
                model = _model_from_config(value.get(field_name))
                if model is not None and not model.startswith("openrouter/"):
                    raise RuntimeError(
                        f"agent {agent_name}.{field_name} must use openrouter/"
                    )


def _assert_auth_startup_safety() -> None:
    """Refuse to start in a security posture nobody chose.

    Two states are refused, and both are silent misconfigurations rather than
    typos - each one starts cleanly, serves traffic, and is wrong.

    1. Auth REQUIRED with no auth server to verify against. Every request would
       fail closed with a 401 nobody could fix from the client side. Failing at
       startup names the missing variable instead.
    2. Auth required while CORS is the "*" escape hatch. `config.py` states the
       rule this enforces: the wildcard is survivable only because
       CORS_ALLOW_CREDENTIALS is False and there is nothing to steal. Once an
       Authorization header is meaningful here, "*" invites every origin on the
       internet to spend this deployment's money with a borrowed token.
    """
    if not project_config.VALIDATOR_REQUIRE_AUTH:
        return
    if not project_config.AUTH_BASE_URL:
        raise RuntimeError(
            "VALIDATOR_REQUIRE_AUTH is on but AUTH_BASE_URL is empty; set it to "
            "the origin of the Better Auth service, e.g. "
            "https://agentic-crew-ai-studio.onrender.com"
        )
    if "*" in project_config.CORS_ALLOW_ORIGINS:
        raise RuntimeError(
            "CORS_ALLOW_ORIGINS is '*' while authentication is required; name "
            "the origins that may carry an Authorization header instead"
        )


#: Plan 01 D8: the header a zero-cost test sets to BE somebody. Honoured only
#: when the app was built `synthetic=True` AND `AUTH_BASE_URL` is unset - the
#: same fail-closed shape as `expose_docs` - and ignored everywhere else.
# TODO(integrator): move to config.py
SYNTHETIC_USER_HEADER = "X-Synthetic-User"
# TODO(integrator): move to config.py
SYNTHETIC_USER_PATTERN = r"^[a-z0-9_-]{1,64}$"
_SYNTHETIC_USER = re.compile(SYNTHETIC_USER_PATTERN)


def _assert_credential_vault_startup_safety() -> None:
    """Refuse to start with people signed in and nowhere to keep their keys.

    Plan 01 D3, the same shape as `_assert_auth_startup_safety` above and for
    the same reason: it starts cleanly, serves traffic, and is wrong. A
    deployment that can sign people in and cannot keep their keys is
    misconfigured; a bare checkout running `SYNTHETIC=1` with no key is merely
    keyless, and its credential routes answer 503 naming the knob. A key that
    is SET and malformed is refused in every configuration - `load_master_key`
    raises with the knob's name and the command that mints a good one -
    because that is a typo, not a decision.

    Imported inside the function: the vault module pulls in SQLAlchemy through
    the persistence module, and importing `app` must stay safe without it.
    """
    from brief_crew.service.credentials import load_master_key

    if load_master_key() is None and project_config.AUTH_BASE_URL:
        raise RuntimeError(
            "AUTH_BASE_URL is set but CREDENTIALS_MASTER_KEY is empty; people can "
            "sign in and the credential vault has no key to keep theirs with. Mint "
            "one with python -c \"import base64, secrets; "
            "print(base64.b64encode(secrets.token_bytes(32)).decode())\" and set it"
        )


def create_app(
    *,
    registry: RunRegistry | None = None,
    runner: Runner | None = None,
    validator_runner: Runner | None = None,
    synthetic: bool = False,
    ping_interval: float = 15.0,
    database_url: str | None = None,
    expose_docs: bool | None = None,
    rate_limiter: RunRateLimiter | None = None,
    builder_runner_factory: BuilderRunnerFactory | None = None,
) -> Any:
    """Create the API; inject a runner to keep tests and local demos unmetered.

    ``builder_runner_factory`` is a *factory* and not a runner, because
    ``RunExecution`` carries no ``workflow_id``: the registry hands a runner an
    execution and nothing that says which graph it belongs to. One runner is
    therefore built per published graph, closed over that graph's compiled
    definition, and ``publish`` and the boot rehydration both call this to get
    it. The default builds the real thing; ``synthetic=True`` builds the same
    runner over the same compiled definition with the crew factories swapped,
    so a free run exercises the real engine rather than a second implementation
    of it.
    """

    _assert_openrouter_startup_safety()
    _assert_auth_startup_safety()
    _assert_credential_vault_startup_safety()

    try:
        from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response
        from fastapi import WebSocket, WebSocketDisconnect
        from fastapi.middleware.cors import CORSMiddleware
    except ModuleNotFoundError as exc:
        raise ServiceDependencyError(
            "FastAPI is not installed; install the existing project service extra"
        ) from exc

    # Imported here rather than at module scope for the reason this module's
    # own docstring gives: importing `app` must stay safe without the service
    # extras, and the builder pulls in SQLAlchemy (the document store) and the
    # CrewAI flow runtime (the compiler). Both are needed only once an app is
    # actually being built.
    from brief_crew.builder.descriptor import static_cost_over_ceiling
    from brief_crew.builder.store import BuilderDocumentStore
    from brief_crew.service.builder_api import (
        BUILDER_API_PREFIX,
        create_builder_router,
    )
    from brief_crew.service.builder_rehydrate import rehydrate_published_workflows
    from brief_crew.service.credentials import CredentialStore
    from brief_crew.service.credentials_api import create_credentials_router

    if registry is not None and (
        runner is not None or validator_runner is not None or synthetic
    ):
        raise ValueError(
            "pass either registry or runner/validator_runner/synthetic, not both"
        )
    if ping_interval <= 0:
        raise ValueError("ping_interval must be positive")
    owns_registry = registry is None
    owned_store = None
    if registry is None:
        from brief_crew.service.persistence import PostgresFlowPersistence

        if database_url is None:
            database_url = os.getenv("DATABASE_URL")
        if database_url is None:
            if synthetic:
                database_url = "sqlite+pysqlite:///:memory:"
            else:
                database_path = (Path("output") / "validator-studio.db").resolve()
                database_path.parent.mkdir(parents=True, exist_ok=True)
                database_url = f"sqlite+pysqlite:///{database_path.as_posix()}"
        if database_url.startswith("postgres://"):
            database_url = database_url.replace(
                "postgres://", "postgresql+psycopg://", 1
            )
        elif database_url.startswith("postgresql://"):
            database_url = database_url.replace(
                "postgresql://", "postgresql+psycopg://", 1
            )
        owned_store = PostgresFlowPersistence(database_url)

        brief_runner = SyntheticRunner() if synthetic else runner or BriefFlowRunner()
        idea_runner = (
            SyntheticValidatorRunner()
            if synthetic
            else validator_runner or ValidatorFlowRunner()
        )
        registry = RunRegistry(
            graph_version=BRIEF_GRAPH.version,
            node_registry=BRIEF_NODE_REGISTRY,
            runner=brief_runner,
            workflows={
                BRIEF_GRAPH.id: WorkflowRuntime(
                    graph_version=BRIEF_GRAPH.version,
                    node_registry=BRIEF_NODE_REGISTRY,
                    runner=brief_runner,
                    input_field=BUILTIN_WORKFLOW_INPUT_FIELDS[BRIEF_GRAPH.id],
                ),
                VALIDATOR_GRAPH.id: WorkflowRuntime(
                    graph_version=VALIDATOR_GRAPH.version,
                    node_registry=VALIDATOR_NODE_REGISTRY,
                    runner=idea_runner,
                    input_field=BUILTIN_WORKFLOW_INPUT_FIELDS[VALIDATOR_GRAPH.id],
                ),
            },
            persistence=owned_store,
        )

    @asynccontextmanager
    async def lifespan(app: Any):
        yield
        if owns_registry:
            # registry.close() stops and joins the human-gate expiry sweeper
            # before shutting the executor down, so nothing outlives the app.
            registry.close()
        if owned_store is not None:
            owned_store.close()

    # /docs, /redoc and /openapi.json publish the exact body shape of the
    # endpoint that spends money. Off by default on a paid instance, on for a
    # synthetic one, which is what local development and the E2E suite run.
    # Obscurity, not a control - see EXPOSE_API_DOCS in config.py.
    if expose_docs is None:
        expose_docs = bool(project_config.EXPOSE_API_DOCS) or synthetic
    app = FastAPI(
        title="Validator Studio Service",
        version="1",
        lifespan=lifespan,
        docs_url="/docs" if expose_docs else None,
        redoc_url="/redoc" if expose_docs else None,
        openapi_url="/openapi.json" if expose_docs else None,
    )

    # Added BEFORE the CORS middleware so CORS ends up outermost and a 413
    # still carries the allow-origin header a browser needs to show it.
    app.add_middleware(
        RequestBodySizeLimitMiddleware,
        max_bytes=project_config.MAX_REQUEST_BODY_BYTES,
        # The one exemption, and it is scoped to the prefix that needs it.
        # `config.py` argues for this shape rather than a raised global bound;
        # the handlers behind it re-check the parsed document's own size,
        # because a chunked request declares no Content-Length and reaches them
        # regardless.
        overrides=(
            (BUILDER_API_PREFIX, project_config.MAX_BUILDER_DOCUMENT_BYTES),
        ),
    )

    # Cross-origin access. In development Vite proxies /api and /ws to this
    # process, so every request is same-origin and none of this is reached; in
    # production the Vue app is a separate static site on its own origin and
    # the browser drops every response that is not opted into by name. The
    # policy is read from config at construction time - an empty
    # CORS_ALLOW_ORIGINS is the default and means no cross-origin caller at
    # all, which leaves local behaviour exactly as it was.
    #
    # This does NOT cover /ws. A WebSocket handshake is not subject to CORS,
    # and Starlette's CORSMiddleware passes non-HTTP scopes straight through,
    # so any page can open the socket. What it cannot do is guess the uuid4
    # run_id and the session_id that /ws demands before it sends a frame.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=project_config.CORS_ALLOW_ORIGINS,
        allow_credentials=project_config.CORS_ALLOW_CREDENTIALS,
        allow_methods=project_config.CORS_ALLOW_METHODS,
        allow_headers=project_config.CORS_ALLOW_HEADERS,
        expose_headers=project_config.CORS_EXPOSE_HEADERS,
    )

    app.state.run_registry = registry
    run_rate_limiter = RunRateLimiter() if rate_limiter is None else rate_limiter
    # Exposed for monitoring and for the tests; nothing reads it to decide.
    app.state.run_rate_limiter = run_rate_limiter
    app.state.expose_docs = expose_docs

    def require_run(run_id: str) -> RunRecord:
        try:
            return registry.require(run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc

    def synthetic_identity(header_value: str | None) -> AuthenticatedUser | None:
        """Plan 01 D8: `X-Synthetic-User`, so two users cost nothing.

        Honoured under exactly two conditions - this app was built
        `synthetic=True` AND `AUTH_BASE_URL` is unset - and ignored, not
        refused, everywhere else: the same fail-closed shape as `expose_docs`
        (CLAUDE.md section 9). With an auth server configured the bearer path
        is the only identity there is, and a header a stranger can type must
        not be able to become one. A malformed value under the two conditions
        is a 400 naming the header, because a typo in a test fixture that
        silently reads as anonymous costs an afternoon.
        """
        if header_value is None or not synthetic or project_config.AUTH_BASE_URL:
            return None
        if not _SYNTHETIC_USER.match(header_value):
            raise HTTPException(
                status_code=400,
                detail=f"{SYNTHETIC_USER_HEADER} must match {SYNTHETIC_USER_PATTERN}",
            )
        return AuthenticatedUser(
            id=header_value, email=f"{header_value}@synthetic", name=header_value
        )

    def optional_user(
        authorization: str | None = Header(default=None),
        x_synthetic_user: str | None = Header(default=None, alias=SYNTHETIC_USER_HEADER),
    ) -> AuthenticatedUser | None:
        """Who is calling, or None - never a 401 for a MISSING credential.

        Resolution order is plan 01 D2's: bearer JWT when ``AUTH_BASE_URL`` is
        set, then the synthetic header under D8's two conditions, then None.
        A token that is OFFERED is verified and a bad one is refused, exactly
        as in ``current_user``; what differs is that nobody is sent away for
        offering nothing. This is the dependency for the reads that were
        public before ownership existed - the workflow list and the graph - so
        a signed-out console still probes the transport and draws the fixed
        topology, while a graph somebody owns collapses to 404 for everybody
        else.

        Declared with ``def`` rather than ``async def`` deliberately. FastAPI
        runs a sync dependency in its threadpool, and the JWKS cache can make a
        blocking HTTP call on a miss; the same code as ``async def`` would stall
        the event loop for every other connection, including live run streams.
        """
        token = bearer_token_from_header(authorization)
        if token is not None and project_config.AUTH_BASE_URL:
            try:
                return verify_token(token)
            except AuthError as exc:
                raise HTTPException(
                    status_code=401,
                    detail="your session has expired; sign in again",
                    headers={"WWW-Authenticate": 'Bearer error="invalid_token"'},
                ) from exc
        return synthetic_identity(x_synthetic_user)

    def current_user(
        authorization: str | None = Header(default=None),
        x_synthetic_user: str | None = Header(default=None, alias=SYNTHETIC_USER_HEADER),
    ) -> AuthenticatedUser | None:
        """Resolve the caller, refusing nobody-at-all when auth is required.

        ``optional_user`` does the resolving; this adds the one refusal. A
        token that is offered IS verified - silently ignoring a credential the
        client believed in is not an answer. But only when there is something
        to verify it against: with no ``AUTH_BASE_URL`` this service has no
        keys, no issuer and no audience, so it cannot judge a token at all.
        Answering 401 there would tell a client its credential was bad when the
        truth is that nobody asked for one, and it is also what
        ``stream_frames`` already does for the WebSocket - the two paths must
        not disagree about who is signed in.
        """
        user = optional_user(authorization, x_synthetic_user)
        if user is None and auth_is_required():
            raise HTTPException(
                status_code=401,
                detail="sign in to use this endpoint",
                # RFC 9110: a 401 MUST carry this, and it is what tells a
                # client the credential is a bearer token rather than
                # cookies or basic auth.
                headers={"WWW-Authenticate": "Bearer"},
            )
        return user

    def require_user(user: AuthenticatedUser | None) -> AuthenticatedUser:
        """Plan 01 D2, rule 1: an owned route with nobody on it is a 401.

        A function a route calls on what ``current_user`` resolved rather than
        a dependency of its own, so a route that needs an identity and a route
        that merely uses one share a single resolver. The 401 is the one
        ``current_user`` writes, header and sentence both.
        """
        if user is None:
            raise HTTPException(
                status_code=401,
                detail="sign in to use this endpoint",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return user

    def require_own_run(run_id: str, user: AuthenticatedUser | None) -> RunRecord:
        """Fetch a run, refusing one that belongs to somebody else.

        The refusal is **404, not 403**, and the difference is deliberate. A 403
        confirms the run exists, turning this endpoint into an oracle that
        answers "is this a real run id" for an unauthenticated-ish caller. 404
        tells someone who is not the owner exactly what a stranger should hear:
        nothing. The owner never sees it, because the UI only ever asks for ids
        it was given.

        A run with no ``user_id`` is readable by anyone who can reach the
        service. That covers rows written before authentication existed and runs
        created while auth is off, and it is why the check keys on the RUN's
        owner rather than on whether the caller is signed in.
        """
        record = require_run(run_id)
        if record.user_id is None:
            return record
        if user is None or user.id != record.user_id:
            raise HTTPException(status_code=404, detail="run not found")
        return record

    def health_payload(*, readiness: bool) -> tuple[dict[str, Any], int]:
        dependencies = registry.dependency_status()
        ready = all(
            dependency.get("status") == "ok"
            for dependency in dependencies.values()
        )
        status = "ok" if not readiness or ready else "not_ready"
        # PRD R-2 is a monitoring signal, not a readiness one: a gate nobody has
        # answered means a human is late, not that the service is unhealthy.
        return {
            "status": status,
            "dependencies": dependencies,
            "gates": registry.gate_watch_status(),
        }, (200 if status == "ok" else 503)

    @app.get("/healthz", response_model=HealthResponse)
    async def healthz() -> HealthResponse:
        payload, _ = health_payload(readiness=False)
        return HealthResponse.model_validate(payload)

    @app.get("/readyz", response_model=HealthResponse)
    async def readyz(response: Response) -> HealthResponse:
        payload, status_code = health_payload(readiness=True)
        response.status_code = status_code
        return HealthResponse.model_validate(payload)

    @app.get("/api/workflows", response_model=list[WorkflowSummary])
    async def list_workflows(
        user: AuthenticatedUser | None = Depends(optional_user),
    ) -> list[WorkflowSummary]:
        """The two hand-written flows, plus the builder graphs THIS caller owns.

        Plan 01 D1. The two literals stay public and stay first, which is what
        every set-equality assertion in the suite reads. A builder graph is
        listed to its owner alone; one nobody owns is launchable by anybody
        (decision 26) but listed to nobody HERE - its home is
        `GET /api/builder/workflows` - because an anonymous caller must keep
        reading exactly the two literals, or this list becomes an index of
        every graph ever published.
        """
        owner = user.id if user is not None else None
        owned = [
            WORKFLOWS[workflow_id]
            for workflow_id, builder in sorted(BUILDER_WORKFLOWS.items())
            if owner is not None
            and builder.user_id == owner
            and workflow_id in WORKFLOWS
        ]
        return [BRIEF_WORKFLOW, VALIDATOR_WORKFLOW, *owned]

    @app.get(
        "/api/workflows/{workflow_id}/graph",
        response_model=GraphDescriptor,
        responses={304: {}, 404: {"model": ErrorResponse}},
    )
    async def get_graph(
        workflow_id: str,
        response: Response,
        if_none_match: str | None = Header(default=None, alias="If-None-Match"),
        user: AuthenticatedUser | None = Depends(optional_user),
    ) -> GraphDescriptor | Response:
        """The topology, with a conditional GET that is actually conditional.

        The `ETag` was written and never read: a request carrying back the exact
        tag the server had just issued got a fresh 200 and the whole descriptor
        again. That is decoration, not caching, and it is the sort of thing that
        looks implemented in a code review.

        The graph is a genuinely good candidate for it. It is fixed for the life
        of a deploy, every page load fetches it, and the client already stores
        `version`, so a reconnecting UI on a slow connection re-downloads 14
        nodes and 16 edges it demonstrably already has.

        `version` is a content hash, so the tag is strong. RFC 9110 says
        `If-None-Match` uses **weak** comparison, which means a `W/` prefix on
        an otherwise identical tag must still match - a proxy is entitled to
        weaken a tag in transit, and refusing the match then would silently turn
        every 304 back into a 200 with nothing in the logs to say why.
        """

        # Plan 01 D1: somebody else's graph is not distinguishable from one
        # that does not exist. Asked before the map is read, so not even the
        # ETag of an owned graph reaches a stranger.
        if not workflow_visible_to(workflow_id, user.id if user is not None else None):
            raise HTTPException(status_code=404, detail="workflow not found")
        graph = GRAPHS.get(workflow_id)
        if graph is None:
            raise HTTPException(status_code=404, detail="workflow not found")
        etag = f'"{graph.version}"'
        if if_none_match and _etag_matches(if_none_match, etag):
            # 304 carries no body, and per RFC 9110 it must repeat the ETag so a
            # cache can refresh its own freshness record from the response.
            return Response(status_code=304, headers={"ETag": etag})
        response.headers["ETag"] = etag
        return graph

    def builder_store_factory() -> Any:
        """The document store, or None when this service has nowhere to save.

        Resolved per call rather than once, because a dozen test modules build
        an app around an injected registry with no persistence at all, and the
        builder routes must answer 503 naming that rather than 404 - which
        would read as "this build has no builder".
        """

        persistence = getattr(registry, "persistence", None)
        if persistence is None:
            return None
        return BuilderDocumentStore(persistence)

    # `synthetic` reaches the builder here and nowhere else. It picks the crew
    # factories and NOTHING else: same compiled definition, same CrewAI engine,
    # same durable gates, same routers, same cancellation. A separate synthetic
    # runner would be a double free to drift from its subject, which is how the
    # missing report body and the missing `status` key each survived a green
    # suite (CLAUDE.md closed items 33 and 20).
    resolved_builder_runner_factory = builder_runner_factory or (
        synthetic_builder_runner if synthetic else BuilderFlowRunner
    )

    # A publish registers into six process-local places and nothing else, so
    # before this call every restart silently unpublished every user graph -
    # the document still said `published` and the launch answered 404. Run here
    # rather than in the lifespan: `registry` exists, the store factory can
    # answer, and no request has been served, so no client can ever observe the
    # window where a published graph is not registered. It cannot raise; see
    # `builder_rehydrate` for why a row that will not compile is a log line
    # rather than a boot failure.
    rehydrate_published_workflows(
        store=builder_store_factory(),
        registry=registry,
        runner_factory=resolved_builder_runner_factory,
    )

    # Mounted on its own prefix, and `GET /api/workflows` above is deliberately
    # untouched: it returns the two literals, which is the only reason the
    # existing set-equality assertions still hold. Builder graphs list on
    # `GET /api/builder/workflows` instead, which costs nothing.
    def credential_store_factory() -> Any:
        """The vault over the same persistence, or None with nowhere to keep it.

        Per call, like `builder_store_factory` and for the same reason. A store
        whose `configured` is False - no master key - is returned rather than
        hidden, so the routes can answer the 503 that names the knob instead of
        the one that says this build has no store.
        """

        persistence = getattr(registry, "persistence", None)
        if persistence is None:
            return None
        return CredentialStore(persistence)

    app.include_router(
        create_builder_router(
            store_factory=builder_store_factory,
            registry=registry,
            current_user=current_user,
            runner_factory=resolved_builder_runner_factory,
            credential_store_factory=credential_store_factory,
        )
    )
    # `/api/builder/credentials` (plan 01 C4). Under the builder prefix, so the
    # body-size exemption above applies and the client reaches it through the
    # same `authedFetch` path; a probe is charged to the RUN limiter under the
    # caller's own key, because it is a user-initiated call to a third party
    # and that bucket is the one that already means "spend per person".
    app.include_router(
        create_credentials_router(
            store_factory=credential_store_factory,
            current_user=current_user,
            require_user=require_user,
            rate_limiter=run_rate_limiter,
            limit_key=lambda user: f"user:{user.id}",
        )
    )

    @app.post(
        "/api/sessions/{session_id}/runs",
        response_model=CreateRunResponse,
        status_code=202,
        responses={
            404: {"model": ErrorResponse},
            413: {"model": ErrorResponse},
            422: {"model": ErrorResponse},
            429: {"model": ErrorResponse},
        },
    )
    async def create_run(
        session_id: str,
        request: CreateRunRequest,
        http_request: Request,
        user: AuthenticatedUser | None = Depends(current_user),
    ) -> CreateRunResponse:
        """The only endpoint that spends money, and it is unauthenticated.

        Three refusals guard it, in the order a hostile request meets them: a
        per-client rate limit, the input bounds, then the server-wide admission
        cap. Only the last two are load-bearing - see ``config.py``.

        The rate limit runs FIRST, before the workflow and input checks, so a
        flood of deliberately malformed bodies is throttled too. It is the only
        endpoint that is limited: /healthz, /readyz and every read-only GET are
        left alone so monitoring and a reconnecting UI are never affected.
        """
        # Keyed on the AUTHENTICATED user when there is one, and on the client
        # address only when there is not. An address is a poor proxy for a
        # person in both directions: behind Render's proxy a shared
        # X-Forwarded-For puts strangers in one bucket, while a single user on a
        # phone changes address mid-session and gets a fresh allowance. A
        # verified user id is neither shared nor changeable, so the limit finally
        # bounds what it was always meant to bound - spend per person.
        limit_key = (
            f"user:{user.id}" if user is not None
            else client_rate_limit_key(http_request)
        )
        retry_after = run_rate_limiter.acquire(limit_key)
        if retry_after > 0:
            raise HTTPException(
                status_code=429,
                detail="too many runs from this client; wait and try again",
                headers=_retry_after_header(retry_after),
            )
        if request.workflow_id not in WORKFLOWS:
            raise HTTPException(status_code=404, detail="workflow not found")
        # Plan 01 D1: a builder graph somebody else owns answers the same 404
        # as an unknown id - BEFORE admission, so a stranger's probe holds no
        # slot and learns nothing. The rate limiter above has already charged
        # the probe, and deliberately: a flood of guessed ids is throttled too.
        if not workflow_visible_to(
            request.workflow_id, user.id if user is not None else None
        ):
            raise HTTPException(status_code=404, detail="workflow not found")
        # Registration takes four places - GRAPHS, NODE_REGISTRIES, WORKFLOWS
        # and the `workflows=` runtime map above - and three of them are one
        # import away from each other, so omitting the fourth is the natural
        # mistake. It used to answer 500 from an uncaught KeyError deep in
        # `create_run`; it is a 404 naming the workflow now, because the
        # request is not malformed and the service is not broken.
        try:
            runtime = registry.workflow_runtime(request.workflow_id)
        except UnknownWorkflowError as exc:
            raise HTTPException(
                status_code=404,
                detail=(
                    f"workflow {request.workflow_id} is declared but has no "
                    "runtime on this service"
                ),
            ) from exc
        input_name = workflow_input_field(request.workflow_id, runtime)
        if input_name is None:
            # Better than the old `else "topic"`: a workflow that declares no
            # input key is a registration defect, and saying so with its own id
            # is actionable where being asked for `inputs.topic` was not.
            raise HTTPException(
                status_code=422,
                detail=(
                    f"workflow {request.workflow_id} declares no request input "
                    "field, so there is nothing to launch it with"
                ),
            )
        # The other half of the reserved-key check, and it is deliberately
        # NARROWER than the sentence that used to sit here claimed.
        #
        # `CreateRunRequest` refuses the three keys CrewAI's runtime reads on
        # any flow - that much needs no registry - and it can go no further,
        # because it holds a workflow id and nothing else: it cannot tell a
        # workflow it has never heard of from one that does not exist, and
        # failing closed to the union at that layer told a third workflow's
        # author that `brief`, their own declared prompt, was Brief Crew's
        # reserved result slot.
        #
        # Here the workflow is resolved, so `reserved_run_input_keys` answers
        # THIS workflow's own control keys - every state field its flow declares
        # - and the one key that is its public prompt is subtracted from them.
        # For a DECLARED workflow both layers then read the same map entry and
        # the schema gets there first, so this line refuses nothing the request
        # had not already been refused; its work is the fallback below.
        # What that does NOT do is refuse every OTHER workflow's control keys,
        # and the claim that it did was the lie: for `brief-flow` and
        # `idea-validator` the union is never consulted at all, so `verdict` on
        # a Brief Crew run is a 202 rather than the 422 the old comment
        # promised.
        #
        # Kept narrow rather than repaired to match the prose, because the prose
        # was asking for something worth less than it cost. `route`, `brief` and
        # `usage` are Brief Crew's state names and ordinary English words on
        # anybody else's graph; a key belonging to a flow that is not the one
        # running reaches nothing, while refusing it refuses an author a word
        # they had every right to. Each workflow's own keys are still refused,
        # which is the half that protects anything.
        #
        # The union has not been abandoned - it is the FALLBACK, and that is why
        # this asks `reserved_run_input_keys` rather than reading one map entry
        # itself. A workflow in `WORKFLOWS` that never declared its state names
        # is a registration defect, and it is the one shape where "this
        # workflow's own keys" would otherwise answer the empty set: it gets
        # every reserved key of every workflow instead, minus its own prompt.
        # An invented id buys nothing either way - it is a 404 above, before
        # this line - and `no_gates` stays unsettable for every id, declared or
        # not, which is what keeps the 403-versus-422 distinction meaningful.
        smuggled = sorted(
            (
                project_config.reserved_run_input_keys(request.workflow_id)
                - {input_name}
            ).intersection(request.inputs)
        )
        if smuggled:
            raise HTTPException(
                status_code=422,
                detail=(
                    "inputs may not carry the reserved control "
                    f"{'keys' if len(smuggled) > 1 else 'key'} "
                    f"{', '.join(smuggled)}; workflow {request.workflow_id} is "
                    f"launched from inputs.{input_name}"
                ),
            )
        input_value = request.inputs.get(input_name)
        if not isinstance(input_value, str) or not input_value.strip():
            raise HTTPException(
                status_code=422,
                detail=f"inputs.{input_name} must contain non-whitespace text",
            )
        # The prompt bound. CreateRunRequest bounds the SHAPE of `inputs` (key
        # count, total JSON size); this bounds the LENGTH of the one value that
        # becomes a model prompt - which is the whole token-amplification
        # vector, and the only attacker-controlled term in the cost of an
        # anonymous request. It lives here rather than in the schema because
        # only here is the workflow's input name known, so the operator gets a
        # sentence naming their own field instead of a schema error list that
        # would quote their entire payload back at them.
        if len(input_value) > project_config.MAX_RUN_INPUT_CHARS:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"inputs.{input_name} is limited to "
                    f"{project_config.MAX_RUN_INPUT_CHARS} characters; "
                    f"this one is {len(input_value)}"
                ),
            )
        # --- the two questions only a USER-DRAWN graph raises ---------------
        #
        # Both are answered from the record registered beside the descriptor,
        # never recomputed here: the estimate is versioned with the graph ETag
        # precisely so a republish cannot race an in-flight admission read.
        # `brief-flow` and `idea-validator` are not in this map, so neither
        # check can change what they do.
        builder = BUILDER_WORKFLOWS.get(request.workflow_id)
        if builder is not None:
            if not builder.gated_before_spend and not (
                user or project_config.BUILDER_ALLOW_GATELESS_GRAPHS
            ):
                # The same shape, and the same argument, as the `gates="auto"`
                # refusal below: while nobody is signed in, human inaction IS
                # the spend cap, and a graph with no gate above its first
                # billable node has removed it. 403 rather than 422 because the
                # request is well formed and would be honoured for a signed-in
                # caller - "I sent this wrong" and "this server will not do
                # that" must not be the same status.
                raise HTTPException(
                    status_code=403,
                    detail=(
                        f"workflow {request.workflow_id} reaches a billable node "
                        "before any human gate; sign in, or add a gate above the "
                        "first agent"
                    ),
                )
            if static_cost_over_ceiling(builder.static_cost_usd):
                # Belt to the compiler's braces. `compile_document` already
                # refuses an unpriceable graph, so this is only reachable when
                # MAX_RUN_COST_USD was LOWERED after the graph was published -
                # at which point the stored estimate is still right and the
                # ceiling it was measured against is not.
                raise HTTPException(
                    status_code=422,
                    detail=(
                        f"workflow {request.workflow_id} is estimated at "
                        f"${builder.static_cost_usd:.2f}, over the "
                        f"${project_config.MAX_RUN_COST_USD:.2f} run ceiling with "
                        f"{project_config.GRAPH_STATIC_BUDGET_MARGIN:g}x margin; "
                        "republish it with fewer billable nodes"
                    ),
                )
        run_inputs = dict(request.inputs)
        if request.gates == "auto":
            # An AUTHENTICATED caller may run unattended. An anonymous one may
            # not, unless the deployment has opted in.
            #
            # The gates were never a safety feature - they were a SPEND cap, and
            # a cap of a very specific shape: while this endpoint was
            # unauthenticated, human inaction was the only thing standing
            # between a stranger's click and a full six-agent pipeline. Nobody
            # could be billed, throttled per-person, or asked afterwards what
            # they were doing.
            #
            # Authentication removed all three conditions. A signed-in caller is
            # a known person, their runs are OWNED (`user_id` on the row), the
            # rate limiter keys on their id rather than a shared proxy address,
            # and `MAX_RUN_COST_USD` (default $10) is a real ceiling enforced by
            # `HookAborted` at the step boundary. Forcing that person through
            # two gates is not protecting anyone - it is making the owner of the
            # deployment click twice to use their own tool.
            #
            # The flag survives for the anonymous case, which is the one it was
            # actually written for: a public demo where the Launch button is
            # reachable by anyone. There, human inaction is still the cap.
            if not (user or project_config.VALIDATOR_ALLOW_AUTO_GATES):
                raise HTTPException(
                    status_code=403,
                    detail=(
                        "unattended runs require a signed-in account on this "
                        "deployment; sign in, omit gates, or set gates=human"
                    ),
                )
            # "Has this workflow got gates?" is a question its descriptor
            # answers - CrewAI reports which methods carry @human_feedback -
            # and comparing the id to the validator's only answered it by
            # coincidence, for as long as the validator was the only gated
            # workflow. A third gated workflow was refused here with a sentence
            # its own graph contradicts.
            if not workflow_has_gates(request.workflow_id):
                raise HTTPException(
                    status_code=422,
                    detail=f"workflow {request.workflow_id} has no gates to skip",
                )
            # The reserved-key check on CreateRunRequest guarantees the caller
            # did not smuggle this in, so setting it here is the ONLY way it can
            # become true - which is what makes the 403 above meaningful.
            run_inputs["no_gates"] = True
        try:
            record = registry.create_run(
                session_id=session_id,
                workflow_id=request.workflow_id,
                inputs=run_inputs,
                user_id=user.id if user is not None else None,
            )
        except RunAdmissionError as exc:
            # 429, not 503: nothing is broken and the service is not down for
            # anyone else. The queue is full and this caller should come back.
            raise HTTPException(
                status_code=429,
                detail="the service is at capacity; try again shortly",
                headers=_retry_after_header(exc.retry_after_seconds),
            ) from exc
        registry.start_run(record.run_id)
        return CreateRunResponse(
            run_id=record.run_id,
            status="queued",
            graph_version=record.graph_version,
        )

    @app.get(
        "/api/runs",
        response_model=RunHistoryPage,
        responses={401: {"model": ErrorResponse}},
    )
    async def list_my_runs(
        limit: int = Query(default=25, ge=1, le=100),
        user: AuthenticatedUser | None = Depends(current_user),
    ) -> RunHistoryPage:
        """The caller's own runs, newest first.

        Note the route is registered BEFORE `/api/runs/{run_id}`. Starlette
        matches in declaration order, and while `/api/runs` and
        `/api/runs/{run_id}` do not actually collide, keeping the literal path
        first is the habit that stops the day one of them gains a default.

        Returns an EMPTY list rather than 401 when nobody is signed in, and that
        is the deliberate choice: on a deployment running without auth there is
        no "your runs" to speak of, and every run in the table belongs to
        nobody. Answering "you have none" is true in both cases. Answering with
        the whole table would be a data leak dressed as a convenience.
        """
        if user is None or registry.persistence is None:
            return RunHistoryPage(runs=[])

        rows = registry.persistence.list_runs_for_user(user.id, limit=limit)
        entries: list[RunHistoryEntry] = []
        for row in rows:
            inputs = row.get("inputs") or {}
            raw_label = run_history_label(registry, row["workflow_id"], inputs)
            usage = row.get("usage") or {}
            entries.append(
                RunHistoryEntry(
                    run_id=row["id"],
                    workflow_id=row["workflow_id"],
                    status=row["status"],
                    created_at=row["created_at"],
                    completed_at=row.get("completed_at"),
                    # Clipped here rather than in CSS. The idea is bounded at
                    # MAX_RUN_INPUT_CHARS (2000), and 25 of those is 50 KB of
                    # payload to draw a sidebar that shows one line each.
                    label=str(raw_label)[:160],
                    total_tokens=int(usage.get("total_tokens") or 0),
                    cost_usd=float(usage.get("cost_usd") or 0.0),
                )
            )
        return RunHistoryPage(runs=entries)

    @app.get(
        "/api/runs/{run_id}",
        response_model=RunStatusResponse,
        responses={404: {"model": ErrorResponse}},
    )
    async def get_run(
        run_id: str,
        user: AuthenticatedUser | None = Depends(current_user),
    ) -> RunStatusResponse:
        require_own_run(run_id, user)
        return RunStatusResponse.model_validate(registry.status_payload(run_id))

    @app.get(
        "/api/runs/{run_id}/frames",
        response_model=FramePage,
        responses={404: {"model": ErrorResponse}},
    )
    async def get_frames(
        run_id: str,
        after: int = Query(default=0, ge=0),
        limit: int = Query(default=100, ge=1, le=MAX_REPLAY_LIMIT),
        kinds: str | None = None,
        user: AuthenticatedUser | None = Depends(current_user),
    ) -> FramePage:
        record = require_own_run(run_id, user)
        kind_filter: set[FrameKind] | None = None
        if kinds:
            try:
                kind_filter = {
                    FrameKind(value.strip())
                    for value in kinds.split(",")
                    if value.strip()
                }
            except ValueError as exc:
                raise HTTPException(status_code=400, detail="unknown frame kind") from exc
        frames = registry.replay_frames(
            run_id,
            after=after,
            limit=limit,
            kinds=kind_filter,
        )
        next_after = int(frames[-1]["seq"]) if frames else after
        return FramePage(
            run_id=run_id,
            after=after,
            next_after=next_after,
            count=len(frames),
            frames=[{"type": "frame", "data": frame} for frame in frames],
        )

    def submit_gate_reply(
        run_id: str,
        gate_id: str,
        *,
        outcome: str,
        fields: Mapping[str, str],
    ) -> GateReplyResponse:
        """The one gate-reply code path. Synchronous, transport-agnostic.

        ``registry.answer_gate`` resumes a CrewAI Flow, so this blocks: the
        HTTP route is already dispatched off the event loop by Starlette and
        the WebSocket handler hands it to a worker thread. Both call exactly
        this, so lateness handling, option validation, the durable
        compare-and-set and the duplicate refusal are identical on both.
        """
        try:
            registry.require(run_id)
        except KeyError as exc:
            raise GateReplyError(
                code="run_not_found",
                status_code=404,
                detail="run not found",
            ) from exc
        try:
            registry.answer_gate(
                run_id,
                gate_id,
                outcome=outcome,
                fields=fields,
            )
        except FileExistsError as exc:
            raise GateReplyError(
                code="gate_conflict",
                status_code=409,
                detail="gate already answered",
            ) from exc
        except RunBusyError as exc:
            # 503, not 500: the reply was well formed and the run is intact -
            # answer_gate rolled the durable answer back and reopened the gate,
            # so the same reply sent again is the fix. A 500 would tell the
            # client the opposite.
            raise GateReplyError(
                code="run_busy",
                status_code=503,
                detail="run is still executing; retry the reply",
            ) from exc
        except KeyError as exc:
            raise GateReplyError(
                code="gate_not_found",
                status_code=404,
                detail="gate not found",
            ) from exc
        except GateFieldError as exc:
            # A distinct code from invalid_outcome: the outcome was fine, the
            # reply tried to set a value this gate does not accept. Both
            # transports refuse it identically because both arrive here.
            raise GateReplyError(
                code="gate_field_not_editable",
                status_code=422,
                detail=str(exc),
            ) from exc
        except ValueError as exc:
            raise GateReplyError(
                code="invalid_outcome",
                status_code=422,
                detail=str(exc),
            ) from exc
        return GateReplyResponse(
            run_id=run_id,
            gate_id=gate_id,
            status=registry.require(run_id).status,
        )

    @app.post(
        "/api/runs/{run_id}/gates/{gate_id}",
        response_model=GateReplyResponse,
        status_code=202,
        responses={
            404: {"model": ErrorResponse},
            409: {"model": ErrorResponse},
            503: {"model": ErrorResponse},
        },
    )
    async def answer_gate(
        run_id: str,
        gate_id: str,
        request: GateReplyRequest,
        user: AuthenticatedUser | None = Depends(current_user),
    ) -> GateReplyResponse:
        require_own_run(run_id, user)
        try:
            return submit_gate_reply(
                run_id,
                gate_id,
                outcome=request.outcome,
                fields=request.fields,
            )
        except GateReplyError as exc:
            raise HTTPException(
                status_code=exc.status_code,
                detail=exc.detail,
            ) from exc

    @app.post(
        "/api/runs/{run_id}/cancel",
        response_model=CancelRunResponse,
        status_code=202,
        responses={404: {"model": ErrorResponse}},
    )
    async def cancel_run(
        run_id: str,
        user: AuthenticatedUser | None = Depends(current_user),
    ) -> CancelRunResponse:
        require_own_run(run_id, user)
        return CancelRunResponse.model_validate(registry.cancel(run_id))

    @app.get(
        "/api/runs/{run_id}/logs",
        responses={404: {"model": ErrorResponse}},
    )
    async def download_logs(
        run_id: str,
        format: str = "ndjson",
        user: AuthenticatedUser | None = Depends(current_user),
    ) -> Response:
        require_own_run(run_id, user)
        if format not in {"ndjson", "zip"}:
            raise HTTPException(status_code=400, detail="format must be ndjson or zip")
        frames_content = "".join(
            json.dumps({"type": "frame", "data": frame}, separators=(",", ":"))
            + "\n"
            for frame in registry.all_frames(run_id)
        ).encode("utf-8")
        if format == "zip":
            status = RunStatusResponse.model_validate(
                registry.status_payload(run_id)
            ).model_dump(mode="json")
            archive_buffer = BytesIO()
            with zipfile.ZipFile(
                archive_buffer,
                mode="w",
                compression=zipfile.ZIP_DEFLATED,
            ) as archive:
                archive.writestr("frames.ndjson", frames_content)
                archive.writestr(
                    "run.json",
                    json.dumps(status, ensure_ascii=False, indent=2).encode("utf-8"),
                )
                archive.writestr(
                    "node-metrics.json",
                    json.dumps(
                        status["node_usage"], ensure_ascii=False, indent=2
                    ).encode("utf-8"),
                )
            return Response(
                content=archive_buffer.getvalue(),
                media_type="application/zip",
                headers={
                    "Content-Disposition": f'attachment; filename="run-{run_id}.zip"'
                },
            )
        return Response(
            content=frames_content,
            media_type="application/x-ndjson",
            headers={
                "Content-Disposition": f'attachment; filename="run-{run_id}.ndjson"'
            },
        )

    @app.websocket("/ws")
    async def stream_frames(
        websocket: WebSocket,
        session_id: str,
        run_id: str,
        after: int = 0,
        access_token: str | None = None,
    ) -> None:
        """Stream a run's frames.

        The credential arrives as a QUERY PARAMETER rather than a header, and
        that is forced rather than chosen: the browser WebSocket API offers no
        way to set request headers on the handshake, so `Authorization` is not
        available here the way it is on every other endpoint.

        The cost is real and worth naming - a URL is logged by proxies in a way
        a header is not, and Render logs request lines. What bounds it is that
        this token is not the session: it is the 15-minute JWT from
        `frontend/server/auth.ts`, so a leaked access log yields a credential
        that is already expired by the time anyone reads it. The durable
        session cookie never leaves the auth origin.

        Item 13 in CLAUDE.md's remaining work notes that /ws has no Origin
        check, because CORS does not apply to a handshake. This does not close
        that item, but it narrows it considerably: a hostile page could always
        open the socket, and now it also needs a valid token for the right user.
        """
        ws_user: AuthenticatedUser | None = None
        try:
            if access_token and project_config.AUTH_BASE_URL:
                # Verified whenever one is offered, exactly as on the HTTP path.
                # Ignoring a credential the client believed in is never right,
                # even on a deployment that would have let it through anonymous.
                ws_user = verify_token(access_token)
            elif auth_is_required():
                raise AuthError("no token on the socket handshake")
            else:
                # Plan 01 D8 on the handshake. The browser WebSocket API cannot
                # set a header, but the E2E proxy can and does forward this one
                # on the upgrade as on every other request; a run launched under
                # a synthetic identity is OWNED, so without this its own console
                # would be closed with 4404. Same two conditions as the HTTP
                # path - `synthetic_identity` answers None everywhere else.
                try:
                    ws_user = synthetic_identity(
                        websocket.headers.get(SYNTHETIC_USER_HEADER.lower())
                    )
                except HTTPException as exc:
                    await websocket.accept()
                    await websocket.close(code=4400, reason=str(exc.detail)[:120])
                    return
        except AuthError:
            # accept() first, then close with a reason. A handshake REJECTED
            # outright surfaces in the browser as an opaque failure with no
            # readable code, which is indistinguishable from the edge blocking
            # the connection - see CLAUDE.md on probing /ws by hand, where
            # exactly that misled a diagnosis.
            await websocket.accept()
            await websocket.close(code=4401, reason="unauthorized")
            return

        try:
            record = registry.require(run_id)
        except KeyError:
            await websocket.accept()
            await websocket.close(code=4404, reason="run not found")
            return

        # Same 404-shaped answer as the HTTP path: someone else's run is not
        # distinguishable from a run that does not exist.
        if record.user_id is not None and (
            ws_user is None or ws_user.id != record.user_id
        ):
            await websocket.accept()
            await websocket.close(code=4404, reason="run not found")
            return
        if record.session_id != session_id:
            await websocket.accept()
            await websocket.close(code=4403, reason="session mismatch")
            return
        if after < 0:
            await websocket.accept()
            await websocket.close(code=4400, reason="after cannot be negative")
            return

        await websocket.accept()
        subscription_id, subscription = record.subscribe(asyncio.get_running_loop())
        send_lock = asyncio.Lock()
        sent_seq = after

        async def send(payload: dict[str, Any]) -> None:
            async with send_lock:
                await websocket.send_json(payload)

        replay = registry.replay_frames(run_id, after=after, limit=MAX_REPLAY_LIMIT)
        first_seq = int(replay[0]["seq"]) if replay else None
        status = registry.status_payload(run_id)
        if first_seq is not None and after < first_seq - 1:
            await send(
                {
                    "type": "replay_gap",
                    "data": {
                        "requested_after": after,
                        "first_available": first_seq,
                        "dropped": status["frames"]["dropped"],
                    },
                }
            )
        for frame in replay:
            await send({"type": "frame", "data": frame})
            sent_seq = int(frame["seq"])
        latest_seq = status["frames"]["last_seq"]
        if latest_seq is not None and sent_seq < latest_seq:
            await send(
                {
                    "type": "replay_truncated",
                    "data": {"next_after": sent_seq, "latest_seq": latest_seq},
                }
            )

        async def outgoing() -> None:
            nonlocal sent_seq
            while True:
                try:
                    frame = await asyncio.wait_for(
                        subscription.queue.get(), timeout=ping_interval
                    )
                except TimeoutError:
                    await send({"type": "ping", "data": {"after": sent_seq}})
                    continue
                if frame.seq <= sent_seq:
                    continue
                await send(frame.envelope())
                sent_seq = frame.seq

        async def send_error(
            code: str,
            detail: str,
            *,
            status: int,
            request_id: str | None = None,
            gate_id: str | None = None,
        ) -> None:
            """Refuse one message without touching the connection or the run."""
            data: dict[str, Any] = {
                "code": code,
                "message": detail,
                "status": status,
            }
            if request_id is not None:
                data["request_id"] = request_id
            if gate_id is not None:
                data["gate_id"] = gate_id
            await send({"type": "error", "data": data})

        async def handle_gate_reply(message: Mapping[str, Any]) -> None:
            # Echoed back on every reply so a client with several in flight can
            # match an ack or an error to the message that caused it.
            raw_request_id = message.get("request_id")
            request_id = raw_request_id if isinstance(raw_request_id, str) else None
            try:
                parsed = GateReplyMessage.model_validate(message)
            except ValidationError as exc:
                await send_error(
                    "invalid_gate_reply",
                    _validation_detail(exc),
                    status=422,
                    request_id=request_id,
                )
                return
            payload = parsed.data
            request_id = parsed.request_id
            # The socket is already bound to one authorised run; a reply naming
            # a different one is refused rather than forwarded.
            if payload.run_id is not None and payload.run_id != run_id:
                await send_error(
                    "run_mismatch",
                    "gate_reply run_id does not match this connection",
                    status=409,
                    request_id=request_id,
                    gate_id=payload.gate_id,
                )
                return
            if len(payload.fields) > WS_MAX_GATE_FIELDS:
                await send_error(
                    "gate_fields_too_many",
                    f"a gate reply carries at most {WS_MAX_GATE_FIELDS} fields",
                    status=422,
                    request_id=request_id,
                    gate_id=payload.gate_id,
                )
                return
            if any(
                len(value) > WS_MAX_GATE_FIELD_CHARS
                for value in payload.fields.values()
            ):
                await send_error(
                    "gate_field_too_long",
                    f"a gate field holds at most {WS_MAX_GATE_FIELD_CHARS} characters",
                    status=422,
                    request_id=request_id,
                    gate_id=payload.gate_id,
                )
                return

            try:
                # answer_gate resumes a CrewAI Flow and touches the durable
                # store, so it runs on a worker thread: the outgoing stream and
                # the ping timer keep running while the reply is applied.
                response = await asyncio.to_thread(
                    submit_gate_reply,
                    run_id,
                    payload.gate_id,
                    outcome=payload.outcome,
                    fields=payload.fields,
                )
            except GateReplyError as exc:
                await send_error(
                    exc.code,
                    exc.detail,
                    status=exc.status_code,
                    request_id=request_id,
                    gate_id=payload.gate_id,
                )
                return
            except Exception:
                # A failed reply must not take the socket or the run with it;
                # the operator can look at the stream and try again.
                await send_error(
                    "gate_reply_failed",
                    "the gate reply could not be applied",
                    status=500,
                    request_id=request_id,
                    gate_id=payload.gate_id,
                )
                return

            acknowledgement = response.model_dump(mode="json")
            acknowledgement["request_id"] = request_id
            await send({"type": "gate_ack", "data": acknowledgement})

        async def incoming() -> None:
            while True:
                raw = await websocket.receive()
                if raw["type"] == "websocket.disconnect":
                    raise WebSocketDisconnect(
                        raw.get("code", 1000), raw.get("reason")
                    )
                text = raw.get("text")
                if text is None:
                    binary = raw.get("bytes")
                    if binary is None:
                        await send_error(
                            "empty_message",
                            "the message carried no text or binary payload",
                            status=400,
                        )
                        continue
                    if len(binary) > WS_MAX_MESSAGE_BYTES:
                        await send_error(
                            "payload_too_large",
                            f"messages are limited to {WS_MAX_MESSAGE_BYTES} bytes",
                            status=413,
                        )
                        continue
                    try:
                        text = binary.decode("utf-8")
                    except UnicodeDecodeError:
                        await send_error(
                            "invalid_encoding",
                            "the message is not valid UTF-8",
                            status=400,
                        )
                        continue
                # A UTF-8 byte count is never below the character count, so
                # this rejects everything over the cap without paying to encode
                # the string first.
                elif len(text) > WS_MAX_MESSAGE_BYTES:
                    await send_error(
                        "payload_too_large",
                        f"messages are limited to {WS_MAX_MESSAGE_BYTES} bytes",
                        status=413,
                    )
                    continue

                try:
                    message = json.loads(text)
                except ValueError:
                    await send_error(
                        "invalid_json",
                        "the message body is not valid JSON",
                        status=400,
                    )
                    continue

                if message == "ping":
                    await send({"type": "pong", "data": {"after": sent_seq}})
                    continue
                if not isinstance(message, dict):
                    await send_error(
                        "invalid_message",
                        "the message must be a JSON object",
                        status=400,
                    )
                    continue
                message_type = message.get("type")
                if message_type == "ping":
                    await send({"type": "pong", "data": {"after": sent_seq}})
                    continue
                if message_type == "gate_reply":
                    await handle_gate_reply(message)
                    continue
                await send_error(
                    "unknown_message_type",
                    f"unsupported message type: {str(message_type)[:64]!r}",
                    status=400,
                )

        outgoing_task = asyncio.create_task(outgoing())
        incoming_task = asyncio.create_task(incoming())
        try:
            done, pending = await asyncio.wait(
                {outgoing_task, incoming_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in done:
                try:
                    task.result()
                except (WebSocketDisconnect, asyncio.CancelledError):
                    pass
        except (WebSocketDisconnect, asyncio.CancelledError):
            pass
        finally:
            for task in (outgoing_task, incoming_task):
                task.cancel()
            try:
                await asyncio.gather(
                    outgoing_task,
                    incoming_task,
                    return_exceptions=True,
                )
            except asyncio.CancelledError:
                pass
            record.unsubscribe(subscription_id)

    return app


def _truthy(value: str | None) -> bool:
    """Read a boolean from the environment the way an operator would write one."""
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def app_from_env() -> Any:
    """Build the app for ``serve()``, honouring ``SYNTHETIC``.

    ``uvicorn.run`` can only import a factory by name, so it cannot pass
    ``synthetic=True``. Without this indirection the registered console script
    could *only* build the paid runners, and anyone starting the service to
    look at the UI would spend real money on OpenRouter and Firecrawl the
    moment they pressed Launch. ``SYNTHETIC=1`` selects the same no-cost
    doubles the integration tests use.
    """
    return create_app(synthetic=_truthy(os.getenv("SYNTHETIC")))


def serve() -> None:
    """Run the Validator Studio API using environment-configurable binding."""
    try:
        import uvicorn
    except ModuleNotFoundError as exc:
        raise ServiceDependencyError(
            "Uvicorn is not installed; install the existing project service extra"
        ) from exc

    uvicorn.run(
        "brief_crew.service.app:app_from_env",
        factory=True,
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "8000")),
    )
