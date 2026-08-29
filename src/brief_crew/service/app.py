"""FastAPI application factory for M1 HTTP and WebSocket transport.

FastAPI is an optional dependency. Importing this module is safe without it;
calling ``create_app`` reports the exact installation blocker.
"""

import asyncio
from collections.abc import Mapping, Sequence
from contextlib import asynccontextmanager
from io import BytesIO
import json
import os
from pathlib import Path
from typing import Any
import zipfile

import yaml

from brief_crew import config as project_config

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
    GateReplyRequest,
    GateReplyResponse,
    GraphDescriptor,
    HealthResponse,
    RunStatusResponse,
    WorkflowSummary,
)
from brief_crew.service.registry import RunRecord, RunRegistry, WorkflowRuntime
from brief_crew.service.runner import (
    BriefFlowRunner,
    Runner,
    SyntheticRunner,
    SyntheticValidatorRunner,
    ValidatorFlowRunner,
)


class ServiceDependencyError(RuntimeError):
    pass


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
) -> Any:
    """Create the API; inject a runner to keep tests and local demos unmetered."""

    _assert_openrouter_startup_safety()

    try:
        from fastapi import FastAPI, HTTPException, Query, Response, WebSocket
        from fastapi import WebSocketDisconnect
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
            registry.close()
        if owned_store is not None:
            owned_store.close()

    app = FastAPI(title="Validator Studio Service", version="1", lifespan=lifespan)
    app.state.run_registry = registry

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
        return {"status": status, "dependencies": dependencies}, (
            200 if status == "ok" else 503
        )

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
        responses={404: {"model": ErrorResponse}},
    )
    async def create_run(
        session_id: str, request: CreateRunRequest
    ) -> CreateRunResponse:
        if request.workflow_id not in WORKFLOWS:
            raise HTTPException(status_code=404, detail="workflow not found")
        input_name = "idea" if request.workflow_id == VALIDATOR_GRAPH.id else "topic"
        input_value = request.inputs.get(input_name)
        if not isinstance(input_value, str) or not input_value.strip():
            raise HTTPException(
                status_code=422,
                detail=f"inputs.{input_name} must contain non-whitespace text",
            )
        record = registry.create_run(
            session_id=session_id,
            workflow_id=request.workflow_id,
            inputs=request.inputs,
        )
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

    @app.post(
        "/api/runs/{run_id}/gates/{gate_id}",
        response_model=GateReplyResponse,
        status_code=202,
        responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
    )
    async def answer_gate(
        run_id: str,
        gate_id: str,
        request: GateReplyRequest,
    ) -> GateReplyResponse:
        require_run(run_id)
        try:
            registry.answer_gate(
                run_id,
                gate_id,
                outcome=request.outcome,
                fields=request.fields,
            )
        except FileExistsError as exc:
            raise HTTPException(status_code=409, detail="gate already answered") from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="gate not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return GateReplyResponse(
            run_id=run_id,
            gate_id=gate_id,
            status=require_run(run_id).status,
        )

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

        async def incoming() -> None:
            while True:
                message = await websocket.receive_json()
                if message == "ping" or (
                    isinstance(message, dict) and message.get("type") == "ping"
                ):
                    await send({"type": "pong", "data": {"after": sent_seq}})

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


def serve() -> None:
    """Run the Validator Studio API using environment-configurable binding."""
    try:
        import uvicorn
    except ModuleNotFoundError as exc:
        raise ServiceDependencyError(
            "Uvicorn is not installed; install the existing project service extra"
        ) from exc

    uvicorn.run(
        "brief_crew.service.app:create_app",
        factory=True,
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "8000")),
    )
