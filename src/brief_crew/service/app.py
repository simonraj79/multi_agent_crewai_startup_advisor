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
from threading import Lock
from time import monotonic
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
from brief_crew.service.graph import (
    BRIEF_GRAPH,
    BRIEF_NODE_REGISTRY,
    BRIEF_WORKFLOW,
    GRAPHS,
    NODE_REGISTRIES,
    VALIDATOR_GRAPH,
    VALIDATOR_NODE_REGISTRY,
    VALIDATOR_WORKFLOW,
    WORKFLOWS,
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
)
from brief_crew.service.registry import (
    GateFieldError,
    RunAdmissionError,
    RunBusyError,
    RunRecord,
    RunRegistry,
    WorkflowRuntime,
)
from brief_crew.service.runner import (
    BriefFlowRunner,
    Runner,
    SyntheticRunner,
    SyntheticValidatorRunner,
    ValidatorFlowRunner,
)


class ServiceDependencyError(RuntimeError):
    pass


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
    """

    def __init__(self, app: Any, *, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = int(max_bytes)

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
            if declared is not None and declared > self.max_bytes:
                body = json.dumps(
                    {
                        "detail": (
                            "the request body is limited to "
                            f"{self.max_bytes} bytes"
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
) -> Any:
    """Create the API; inject a runner to keep tests and local demos unmetered."""

    _assert_openrouter_startup_safety()

    try:
        from fastapi import FastAPI, HTTPException, Query, Request, Response
        from fastapi import WebSocket, WebSocketDisconnect
        from fastapi.middleware.cors import CORSMiddleware
    except ModuleNotFoundError as exc:
        raise ServiceDependencyError(
            "FastAPI is not installed; install the existing project service extra"
        ) from exc

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
                ),
                VALIDATOR_GRAPH.id: WorkflowRuntime(
                    graph_version=VALIDATOR_GRAPH.version,
                    node_registry=VALIDATOR_NODE_REGISTRY,
                    runner=idea_runner,
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
    async def list_workflows() -> list[WorkflowSummary]:
        return [BRIEF_WORKFLOW, VALIDATOR_WORKFLOW]

    @app.get(
        "/api/workflows/{workflow_id}/graph",
        response_model=GraphDescriptor,
        responses={404: {"model": ErrorResponse}},
    )
    async def get_graph(workflow_id: str, response: Response) -> GraphDescriptor:
        graph = GRAPHS.get(workflow_id)
        if graph is None:
            raise HTTPException(status_code=404, detail="workflow not found")
        response.headers["ETag"] = f'"{graph.version}"'
        return graph

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
        retry_after = run_rate_limiter.acquire(client_rate_limit_key(http_request))
        if retry_after > 0:
            raise HTTPException(
                status_code=429,
                detail="too many runs from this client; wait and try again",
                headers=_retry_after_header(retry_after),
            )
        if request.workflow_id not in WORKFLOWS:
            raise HTTPException(status_code=404, detail="workflow not found")
        input_name = "idea" if request.workflow_id == VALIDATOR_GRAPH.id else "topic"
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
        run_inputs = dict(request.inputs)
        if request.gates == "auto":
            # Refused unless this deployment has opted in. 403, not 422: the
            # request is well formed and would be honoured elsewhere - what is
            # missing is permission, and saying so lets a client tell "I sent
            # this wrong" apart from "this server will not do that".
            if not project_config.VALIDATOR_ALLOW_AUTO_GATES:
                raise HTTPException(
                    status_code=403,
                    detail=(
                        "unattended runs are disabled on this deployment; "
                        "omit gates or set gates=human"
                    ),
                )
            if request.workflow_id != VALIDATOR_GRAPH.id:
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
        "/api/runs/{run_id}",
        response_model=RunStatusResponse,
        responses={404: {"model": ErrorResponse}},
    )
    async def get_run(run_id: str) -> RunStatusResponse:
        require_run(run_id)
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
    ) -> FramePage:
        record = require_run(run_id)
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
    ) -> GateReplyResponse:
        require_run(run_id)
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
    async def cancel_run(run_id: str) -> CancelRunResponse:
        require_run(run_id)
        return CancelRunResponse.model_validate(registry.cancel(run_id))

    @app.get(
        "/api/runs/{run_id}/logs",
        responses={404: {"model": ErrorResponse}},
    )
    async def download_logs(run_id: str, format: str = "ndjson") -> Response:
        require_run(run_id)
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
    ) -> None:
        try:
            record = registry.require(run_id)
        except KeyError:
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
