"""Shared plumbing for the observability reconciliation scripts.

Not a CLI. Every script under `scripts/observability/` imports this for the
four things they all need and none of them should re-implement:

* finding the repository root and loading `.env` (credentials come from the
  environment, are never accepted on the command line and are never printed);
* a small HTTP client with bounded retries;
* one aggregation bucket shape, so the app side, the Langfuse side and the
  OpenRouter side produce figures a reconciler can compare cell for cell;
* Markdown table rendering, because every DoD row's evidence is a table.

Serves: every row those scripts serve (A2, B1, B2, B4, D3, E1, E4, E5, F3).
"""

from __future__ import annotations

import json
import math
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

try:  # httpx is a hard dependency of the app; nothing here needs a fallback.
    import httpx
except ImportError:  # pragma: no cover - the venv has httpx
    httpx = None  # type: ignore[assignment]


# --- repository, environment ------------------------------------------------


def repo_root(start: Path | None = None) -> Path:
    """The directory holding `pyproject.toml`, walking up from this file."""

    here = (start or Path(__file__)).resolve()
    for candidate in [here, *here.parents]:
        if (candidate / "pyproject.toml").is_file():
            return candidate
    return here.parent


def load_env(dotenv_path: str | os.PathLike[str] | None = None) -> Path | None:
    """Load `.env` into `os.environ` WITHOUT overriding an existing value.

    `override=False` on purpose, and it is the opposite of what
    `brief_crew/__init__.py` does: a verifier who exports one credential for a
    single command must not have the file silently win. Nothing here reads a
    value back out; the loader is the only thing that touches them.
    """

    path = Path(dotenv_path) if dotenv_path else repo_root() / ".env"
    if not path.is_file():
        return None
    try:
        from dotenv import load_dotenv
    except ImportError:  # pragma: no cover - python-dotenv ships with the app
        _load_env_manually(path)
        return path
    load_dotenv(path, override=False)
    return path


def _load_env_manually(path: Path) -> None:
    quotes = ('"', "'")
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in quotes:
            value = value[1:-1]
        if key and key not in os.environ:
            os.environ[key] = value


def env_required(name: str, hint: str = "") -> str:
    """Read a credential from the environment, or die naming only the KEY."""

    value = os.environ.get(name, "").strip()
    if not value:
        suffix = f" {hint}" if hint else ""
        raise SystemExit(f"{name} is not set in the environment or .env.{suffix}")
    return value


def env_optional(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


# --- HTTP -------------------------------------------------------------------


class HttpError(RuntimeError):
    def __init__(self, status: int, body: str, url: str) -> None:
        super().__init__(f"HTTP {status} from {url}: {body[:400]}")
        self.status = status
        self.body = body
        self.url = url


class Http:
    """A bounded HTTP helper.

    Retries only what is worth retrying (429 and 5xx) and never logs a header.
    """

    RETRY_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})

    def __init__(
        self,
        base_url: str = "",
        *,
        auth: tuple[str, str] | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: float = 30.0,
        retries: int = 3,
        backoff: float = 1.5,
        max_retry_wait: float = 90.0,
    ) -> None:
        if httpx is None:  # pragma: no cover
            raise SystemExit("httpx is not installed in this interpreter")
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            auth=auth,
            headers=dict(headers or {}),
            timeout=timeout,
            follow_redirects=True,
        )
        self.retries = max(1, retries)
        self.backoff = backoff
        self.max_retry_wait = max_retry_wait

    def __enter__(self) -> "Http":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def get(
        self,
        path: str,
        params: Mapping[str, Any] | None = None,
        *,
        allow_status: Iterable[int] = (),
    ) -> tuple[int, Any]:
        """GET returning `(status, parsed-json-or-text)`.

        A status in `allow_status` is returned rather than raised, which is how
        callers handle a 404 (no such session; a generation not yet indexed)
        without a try/except at every call site.
        """

        allowed = set(allow_status)
        for attempt in range(1, self.retries + 1):
            try:
                response = self._client.get(path, params=dict(params or {}))
            except Exception:  # network-level
                if attempt == self.retries:
                    raise
                time.sleep(self.backoff * attempt)
                continue
            if response.status_code in self.RETRY_STATUS and attempt < self.retries:
                time.sleep(self._retry_wait(response, attempt))
                continue
            body = _parse(response)
            if response.status_code >= 400 and response.status_code not in allowed:
                raise HttpError(response.status_code, response.text, str(response.url))
            return response.status_code, body
        raise RuntimeError("unreachable")

    def _retry_wait(self, response: Any, attempt: int) -> float:
        """How long to wait before retrying, asking the SERVER first.

        Langfuse's public API rate-limits `/api/public/observations` at 15
        requests per window and answers 429 with
        `details.retryAfterSeconds: 42` - a figure the previous backoff
        (1.5 s, 3 s, 6 s) could not reach, so a limited caller retried three
        times inside one window and raised. A limiter that tells you when to
        come back is answering the question; ignoring it and guessing shorter
        is how a rate limit becomes a crash.
        """

        wait = self.backoff * attempt
        server = None
        header = ""
        try:
            header = str(response.headers.get("Retry-After") or "").strip()
        except Exception:  # pragma: no cover - a response without headers
            header = ""
        if header:
            try:
                server = float(header)
            except ValueError:
                server = None
        if server is None:
            body = _parse(response)
            if isinstance(body, Mapping):
                details = body.get("details")
                if isinstance(details, Mapping):
                    try:
                        server = float(details.get("retryAfterSeconds"))
                    except (TypeError, ValueError):
                        server = None
        if server is not None and server > 0:
            # +1 s so the retry lands after the window resets rather than on it.
            wait = max(wait, min(server + 1.0, self.max_retry_wait))
        return wait

    def post(
        self,
        path: str,
        payload: Mapping[str, Any] | None = None,
        *,
        allow_status: Iterable[int] = (),
    ) -> tuple[int, Any]:
        allowed = set(allow_status)
        response = self._client.post(path, json=dict(payload or {}))
        body = _parse(response)
        if response.status_code >= 400 and response.status_code not in allowed:
            raise HttpError(response.status_code, response.text, str(response.url))
        return response.status_code, body

    def get_text(self, path: str, params: Mapping[str, Any] | None = None) -> str:
        response = self._client.get(path, params=dict(params or {}))
        if response.status_code >= 400:
            raise HttpError(response.status_code, response.text, str(response.url))
        return response.text


def _parse(response: Any) -> Any:
    try:
        return response.json()
    except Exception:
        return response.text


# --- output -----------------------------------------------------------------


def ensure_dir(path: str | os.PathLike[str]) -> Path:
    directory = Path(path)
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def write_json(out_dir: Path, name: str, data: Any) -> Path:
    path = Path(out_dir) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )
    return path


def write_text(out_dir: Path, name: str, text: str) -> Path:
    path = Path(out_dir) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    if not text.endswith("\n"):
        text += "\n"
    path.write_text(text, encoding="utf-8")
    return path


def read_json(path: str | os.PathLike[str]) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


# --- formatting -------------------------------------------------------------


def md_table(headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
    """A GitHub Markdown table. An empty table still renders its header.

    An empty table with its header is evidence ("we looked and there were
    none"); no table at all is indistinguishable from a script that failed.
    """

    head = "| " + " | ".join(str(h) for h in headers) + " |"
    rule = "| " + " | ".join("---" for _ in headers) + " |"
    body = [
        "| " + " | ".join("" if cell is None else str(cell) for cell in row) + " |"
        for row in rows
    ]
    if not body:
        body = ["| " + " | ".join("-" for _ in headers) + " |"]
    return "\n".join([head, rule, *body])


def usd(value: Any) -> str:
    if value is None:
        return "n/a"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "n/a"
    if not math.isfinite(number):
        return "n/a"
    return f"${number:.6f}"


def secs(value: Any) -> str:
    if value is None:
        return "n/a"
    try:
        return f"{float(value):.3f}"
    except (TypeError, ValueError):
        return "n/a"


def parse_ts(value: Any) -> datetime | None:
    """Parse an ISO-8601 timestamp from either side (`Z` or `+00:00`)."""

    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def duration_seconds(start: Any, end: Any) -> float | None:
    a, b = parse_ts(start), parse_ts(end)
    if a is None or b is None:
        return None
    return max(0.0, (b - a).total_seconds())


# --- aggregation ------------------------------------------------------------

BUCKET_KEYS = (
    "calls",
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "cost_usd",
    "calls_without_cost",
)


def new_bucket() -> dict[str, Any]:
    """One row of every per-agent / per-task / per-node table in this tree.

    `calls_without_cost` exists because `compute_cost_usd` returns `None` for a
    model with no price on file and this repository is emphatic that `None` is
    not `0.0`. A bucket that silently added zero would report a free run.
    """

    return {
        "calls": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "cost_usd": 0.0,
        "calls_without_cost": 0,
    }


def add_call(
    bucket: dict[str, Any],
    *,
    input_tokens: Any = 0,
    output_tokens: Any = 0,
    total_tokens: Any = None,
    cost_usd: Any = None,
) -> None:
    bucket["calls"] += 1
    inp = int(input_tokens or 0)
    out = int(output_tokens or 0)
    bucket["input_tokens"] += inp
    bucket["output_tokens"] += out
    bucket["total_tokens"] += (
        int(total_tokens) if total_tokens is not None else inp + out
    )
    if cost_usd is None:
        bucket["calls_without_cost"] += 1
    else:
        try:
            bucket["cost_usd"] += float(cost_usd)
        except (TypeError, ValueError):
            bucket["calls_without_cost"] += 1


def bucket_for(mapping: dict[str, dict[str, Any]], key: str) -> dict[str, Any]:
    return mapping.setdefault(key, new_bucket())


def sum_buckets(mapping: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    total = new_bucket()
    for bucket in mapping.values():
        for key in BUCKET_KEYS:
            total[key] = total[key] + bucket.get(key, 0)
    return total


def bucket_table(
    mapping: Mapping[str, Mapping[str, Any]],
    *,
    label: str,
    total_label: str = "**SUM**",
) -> str:
    """A per-<label> table with its own sum row - B1's "summing to the run total".

    The sum is rendered, not asserted: a verifier reads the last row against the
    run total printed in the same file rather than trusting a script's own
    equality check.
    """

    rows: list[list[Any]] = []
    for key in sorted(mapping):
        bucket = mapping[key]
        rows.append(
            [
                key or "(none)",
                bucket.get("calls", 0),
                bucket.get("input_tokens", 0),
                bucket.get("output_tokens", 0),
                bucket.get("total_tokens", 0),
                usd(bucket.get("cost_usd")),
                bucket.get("calls_without_cost", 0) or "",
            ]
        )
    total = sum_buckets(mapping)
    rows.append(
        [
            total_label,
            total["calls"],
            total["input_tokens"],
            total["output_tokens"],
            total["total_tokens"],
            usd(total["cost_usd"]),
            total["calls_without_cost"] or "",
        ]
    )
    return md_table(
        [label, "calls", "input", "output", "total", "cost", "no price"],
        rows,
    )


def now_iso() -> str:
    return (
        datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    )


def eprint(*args: Any) -> None:
    print(*args, file=sys.stderr)


# --- redaction at write time (F3) -------------------------------------------
#
# Langfuse's public API returns `metadata.scope.attributes.public_key` on every
# trace, observation and session object: the ingesting SDK's public key, i.e.
# the exact value of LANGFUSE_PUBLIC_KEY. Saving a response verbatim therefore
# writes a credential to disk, 36 times per run, and `secret_scan.py` reports
# FAIL over the directory - DoD F3's own instrument, failing on files the
# tooling wrote. So every script that saves an API response redacts on the way
# to disk rather than leaving a verifier to fix it up by hand afterwards.
#
# Three rules, applied recursively, and each is deliberately broader than the
# one leak that was measured:
#
# 1. a mapping key named `public_key` / `secret_key` / anything `*_key` /
#    `authorization` - the value is replaced whatever it looks like, because
#    the NAME is the evidence, not the shape;
# 2. a string carrying one of the credential prefixes `secret_scan.py` scans
#    for - the matched token is replaced, the rest of the string kept;
# 3. a string carrying, anywhere inside it, the value of one of this process's
#    own credential environment variables.
#
# Nothing here ever prints, logs or returns a credential value: the caller gets
# a count, and the count is what goes to stderr.

REDACTED = "<redacted>"

CREDENTIAL_PREFIXES = (
    "sk-or-",
    "sk-lf-",
    "pk-lf-",
    "fc-",
    "ghp_",
    "github_pat_",
    "pcsk_",
    "AIza",
)

_CREDENTIAL_PREFIX_PATTERN = re.compile(
    "(?:" + "|".join(re.escape(p) for p in CREDENTIAL_PREFIXES) + r")[A-Za-z0-9_\-]+"
)

# Same rule `secret_scan.py` uses, so the redactor and the scanner cannot
# disagree about what counts as a credential variable.
_CREDENTIAL_NAME = re.compile(r"(_KEY|_TOKEN|_SECRET\w*)$")

# A key whose NAME says it holds a credential. `*_keys` (plural) is excluded on
# purpose: `arg_keys` is a list of argument NAMES the frame pipeline writes and
# redacting it would destroy evidence rather than protect anything.
_CREDENTIAL_KEY_NAME = re.compile(r"(^|[._-])(public_key|secret_key|api_key|authorization)$|_key$")

# Below this a variable is a flag or a name, not a credential, and substring
# matching on it would redact the word "true" out of every artifact.
_MIN_SECRET_LENGTH = 12


def credential_env_values() -> list[str]:
    """Every credential-shaped value this process holds, longest first.

    Longest first matters: if two variables share a prefix, replacing the long
    one first cannot leave the tail of the short one behind.
    """

    values = {
        value
        for name, value in os.environ.items()
        if _CREDENTIAL_NAME.search(name) and value and len(value) >= _MIN_SECRET_LENGTH
    }
    return sorted(values, key=len, reverse=True)


def redact_string(text: str, values: Sequence[str]) -> tuple[str, int]:
    count = 0
    for value in values:
        if value and value in text:
            count += text.count(value)
            text = text.replace(value, REDACTED)
    replaced = _CREDENTIAL_PREFIX_PATTERN.subn(REDACTED, text)
    if replaced[1]:
        count += replaced[1]
        text = replaced[0]
    return text, count


def redact_for_disk(payload: Any, values: Sequence[str] | None = None) -> tuple[Any, int]:
    """Return `(redacted copy, number of redactions)`; the input is unchanged.

    Recursive over mappings and sequences. A key that names a credential has
    its value replaced outright - including a nested container, which is what
    makes `metadata.scope.attributes.public_key` unreachable rather than merely
    scrubbed.
    """

    secrets = list(values) if values is not None else credential_env_values()
    total = 0

    def walk(node: Any) -> Any:
        nonlocal total
        if isinstance(node, Mapping):
            out: dict[Any, Any] = {}
            for key, value in node.items():
                key_text = str(key)
                if _CREDENTIAL_KEY_NAME.search(key_text.lower()):
                    if value not in (None, "", [], {}):
                        total += 1
                        out[key] = REDACTED
                    else:
                        out[key] = value
                    continue
                out[key] = walk(value)
            return out
        if isinstance(node, (list, tuple)):
            return [walk(item) for item in node]
        if isinstance(node, str):
            text, count = redact_string(node, secrets)
            total += count
            return text
        return node

    result = walk(payload)
    return result, total


def write_json_redacted(out_dir: Path, name: str, data: Any) -> tuple[Path, int]:
    """`write_json`, with every credential value replaced BEFORE `json.dump`."""

    redacted, count = redact_for_disk(data)
    return write_json(out_dir, name, redacted), count


def write_text_redacted(out_dir: Path, name: str, text: str) -> tuple[Path, int]:
    cleaned, count = redact_string(text, credential_env_values())
    return write_text(out_dir, name, cleaned), count
