# Container alternative to Render's native Python runtime (feature F44).
#
# Builds the FastAPI/WebSocket API only. The Vue frontend is a separate static
# site (see render.yaml) and is deliberately not baked in here.
#
# Build:
#   docker build -t validator-studio-api .
# Run (secrets are injected, never baked):
#   docker run --rm -p 8000:8000 --env-file .env validator-studio-api
#
# NOTE: this image has not been built on this machine - the Docker daemon was
# not running when it was written.

# ---------------------------------------------------------------------------
# Stage 1 - build the virtualenv with uv, from the committed lockfile
# ---------------------------------------------------------------------------
FROM python:3.13-slim-bookworm AS builder

# Pinned so an image rebuild is reproducible.
COPY --from=ghcr.io/astral-sh/uv:0.7.19 /uv /uvx /usr/local/bin/

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /app

# Dependency layer first, so editing src/ does not re-resolve the world.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --extra service --no-dev --no-install-project

# `--extra service` is mandatory: fastapi, sqlalchemy and psycopg[binary] are
# in the optional `service` extra, and a bare `uv sync` would leave the image
# importable but unable to construct the app.
COPY src ./src
RUN uv sync --frozen --extra service --no-dev

# ---------------------------------------------------------------------------
# Stage 2 - runtime
# ---------------------------------------------------------------------------
FROM python:3.13-slim-bookworm AS runtime

# libgomp1 is required by onnxruntime, which arrives transitively through
# chromadb via crewai[tools]. python:*-slim does not ship it.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# CREWAI_TRACING_ENABLED stays false: authenticated tracing needs tokens.enc,
# which is a secret, expires, and is excluded by .dockerignore.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH" \
    CREWAI_DISABLE_TELEMETRY=true \
    CREWAI_TRACING_ENABLED=false \
    CREWAI_STORAGE_DIR=/tmp/crewai \
    PORT=8000

WORKDIR /app

RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /app/output /tmp/crewai \
    && chown -R appuser:appuser /app /tmp/crewai

# The project is installed editable, so src/ must sit at the same absolute
# path it occupied during the build (/app/src).
COPY --from=builder --chown=appuser:appuser /app/.venv /app/.venv
COPY --chown=appuser:appuser src ./src
COPY --chown=appuser:appuser pyproject.toml uv.lock ./

USER appuser

EXPOSE 8000
STOPSIGNAL SIGTERM

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import os,sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8000')+'/healthz', timeout=4).status==200 else 1)"

# create_app is a FACTORY - --factory is required. Shell form so $PORT, which
# the platform injects, is expanded; exec so uvicorn receives SIGTERM as PID 1.
CMD ["sh", "-c", "exec uvicorn brief_crew.service.app:create_app --factory --host 0.0.0.0 --port ${PORT:-8000}"]
