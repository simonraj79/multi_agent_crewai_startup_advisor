# Container alternative to Render's native Python runtime (feature F44).
#
# Builds the FastAPI/WebSocket API only. The Vue frontend is a separate service
# and is deliberately not baked in here - note it is a NODE WEB SERVICE now,
# not a static site: Better Auth needs a runtime a CDN cannot give it, and the
# SPA and auth must share one origin because onrender.com is on the Public
# Suffix List. See render.yaml.
#
# Build:
#   docker build -t validator-studio-api .
# Run (secrets are injected, never baked):
#   docker run --rm -p 8000:8000 --env-file .env validator-studio-api
#
# If the environment sets AUTH_BASE_URL it MUST also set CREDENTIALS_MASTER_KEY,
# or `create_app` raises at startup rather than degrading - plan 01 D3. See
# docs/deploying.md step 4 and CLAUDE.md remaining-work item 46.
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
#
# render.yaml sets "true" for the SAME variable and that is not a contradiction
# - it opts into ephemeral (unauthenticated) tracing, which
# agents/08-observability.md:196 recommends for Render. This path opts out
# entirely. Two modes, two deploy paths, one documented split.
#
# Note what is actually doing the work here: `false` is NOT a disable switch.
# CrewAI's resolver has no branch returning False for it (see
# agents/08-observability.md:128-138) - the value simply fails the ("true","1")
# test and falls through to stored consent. It reads as off in this image only
# because a fresh container has no stored trace_consent. Anything that ships a
# consent file would silently re-enable tracing with this line untouched.
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

# `data/` IS RUNTIME DATA, not documentation, and without it this image cannot
# even import. Added 2026-09-04 after reading the code rather than building the
# image, which has still never been built here.
#
#   * `data/models.json` is the model registry (plan 05, contract C3).
#     `config.MODEL_REGISTRY_PATH` resolves it as
#     `Path(config.py).resolve().parents[2] / "data" / "models.json"` - with
#     src/ at /app/src that is /app/data/models.json - and `load_model_registry`
#     RAISES at import on a missing or malformed file, deliberately: "a registry
#     that half-loads is a product that offers half a roster and prices the rest
#     at nothing". So without this line `import brief_crew.config` fails and the
#     container never serves anything.
#   * `data/skills/builtin/*/SKILL.md` are the four built-in skill packs
#     (plan 08). `SKILLS_ROOT` defaults to the CWD-relative `data/skills`, and
#     WORKDIR is /app, so they belong at /app/data/skills/builtin.
#
# ⚠️ THE SKILLS HALF IS STILL BROKEN AND THIS LINE DOES NOT FIX IT.
# `.dockerignore` excludes `*.md` wholesale, so every `SKILL.md` is stripped
# from the build context before COPY sees it - and `load_builtins()` does
# `if not path.exists(): continue`, so the image would serve ZERO built-in
# skills with no error anywhere. The fix is one negation in `.dockerignore`:
#
#     !data/skills/builtin/**/*.md
#
# That file was outside the surface of the pass that found this; it is recorded
# in CLAUDE.md's remaining work rather than half-fixed here, because a COPY that
# looks complete and silently drops four packs is worse than a known gap.
COPY --chown=appuser:appuser data ./data

USER appuser

EXPOSE 8000
STOPSIGNAL SIGTERM

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import os,sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8000')+'/healthz', timeout=4).status==200 else 1)"

# create_app is a FACTORY - --factory is required. Shell form so $PORT, which
# the platform injects, is expanded; exec so uvicorn receives SIGTERM as PID 1.
CMD ["sh", "-c", "exec uvicorn brief_crew.service.app:create_app --factory --host 0.0.0.0 --port ${PORT:-8000}"]
