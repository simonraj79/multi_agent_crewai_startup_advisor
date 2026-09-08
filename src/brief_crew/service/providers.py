"""Three upstream probes for the admin console, behind one TTL (plan 17 §4).

The owner's ruling is that nothing is duplicated: **OpenRouter** is the truth
for the account balance, **Firecrawl** for its credits, and **Langfuse** for
what a run was actually billed. So this module asks each of them, server-side,
and caches the answer for `ADMIN_PROVIDER_CACHE_SECONDS`.

FOUR RULES, AND EVERY ONE OF THEM IS A DEFECT SOMEBODY ELSE ALREADY PAID FOR
---------------------------------------------------------------------------
* **A failure is an answer, never an exception.** Every probe returns
  `{"available": False, "reason": "<one sentence>"}` on a 401, a 500, a
  timeout, malformed JSON or a missing field. A 500 from `/api/admin/providers`
  would make the dashboard's own health tile the thing that breaks the
  dashboard, at exactly the moment somebody is looking at it because something
  is wrong.
* **Keys are read from `os.environ` at CALL time and never captured.** The
  reason `HttpCostLookup` gives, verbatim in effect: the probe cache is built
  once and a deployment may set the variable afterwards, and a captured
  credential is a credential living in an object graph for the life of the
  process for no benefit.
* **No key, and no URL containing one, is ever put in a returned value.** The
  reason is `reason`: it is a sentence a browser renders, so nothing that
  came off the wire and nothing that came out of the environment goes into it.
  Every sentence below is a literal or a status code.
* **A FAILURE IS CACHED TOO.** A dead upstream must not be hammered once per
  page load by every open dashboard; the whole point of the TTL is that the
  expensive case is the one that repeats.

WHAT IS DELIBERATELY NOT HERE
-----------------------------
`GET /api/v1/activity`. The docs require a **provisioning key** for it, "to
ensure that your historic usage is not accessible to just anyone in your org
with an inference API key", and the ruling admits activity only if the
ordinary key works. It does not, so per-day OpenRouter usage is excluded and
the console's own `run_node_metrics` estimate is what the Money panel shows.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
import os
import threading
from typing import Any

from brief_crew import config

logger = logging.getLogger(__name__)

__all__ = ["ProviderProbes", "firecrawl_credits", "openrouter_balance", "unavailable"]


def unavailable(reason: str) -> dict[str, Any]:
    """The one shape every failure takes, so a client needs one branch."""

    return {"available": False, "reason": reason}


def _iso_now() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _first(data: Any, *names: str) -> Any:
    """The first of these keys the payload actually carries.

    Four lines against a whole class of silent `None`: Firecrawl's v2 response
    is camelCase (`remainingCredits`) and its v1 response is snake_case
    (`remaining_credits`), and a reader that knows one spelling reports a
    configured account as having no credits rather than reporting that it
    could not read the answer.
    """

    if not isinstance(data, dict):
        return None
    for name in names:
        if name in data and data[name] is not None:
            return data[name]
    return None


def _model_name(row: Any, metadata: Any) -> str:
    """The model this generation used, off whichever key carries it.

    `_MODEL_KEYS` in order, then the exporter's own `metadata.model`, then
    `unknown`. `unknown` rather than dropping the row: a generation whose
    model nobody can name still cost money, and a breakdown that silently
    omits it stops summing to the total printed beside it.
    """

    if isinstance(row, dict):
        for key in _MODEL_KEYS:
            value = row.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()[:120]
    if isinstance(metadata, dict):
        value = metadata.get("model")
        if isinstance(value, str) and value.strip():
            return value.strip()[:120]
    return "unknown"


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _whole(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _status_reason(vendor: str, code: int) -> str:
    """A sentence about a status code, and never about a body.

    The body of a 4xx from a credential-bearing endpoint is exactly the place
    a vendor is most likely to echo something back, so it is not read here at
    all - the code is the whole of what the console is told.
    """

    if code in (401, 403):
        return f"{vendor} refused the key (HTTP {code}); check it is the right kind of key"
    if code == 404:
        return f"{vendor} answered HTTP 404 for this endpoint"
    return f"{vendor} answered HTTP {code}"


def _client(timeout: float | None = None) -> Any:
    import httpx

    return httpx.Client(
        timeout=timeout or config.ADMIN_PROVIDER_TIMEOUT_SECONDS,
        headers={"User-Agent": "brief-crew-admin/1"},
    )


# ---------------------------------------------------------------------------
# A. OpenRouter - two rungs, and the tile says which one answered
# ---------------------------------------------------------------------------


def openrouter_balance(*, client: Any = None) -> dict[str, Any]:
    """The account balance, on whichever rung this deployment can reach.

    **`/api/v1/credits` needs a MANAGEMENT key, not the inference key.** An
    `sk-or-v1-...` key is refused there with *"Only management keys can
    perform this operation"*, which is why the probe has two rungs and reports
    `source` rather than pretending they are one measurement:

    * `OPENROUTER_MANAGEMENT_KEY` set -> `/api/v1/credits`, `source:"credits"`,
      and `remaining_usd` is `total_credits - total_usage`: the account
      balance, which is the figure the owner actually wants.
    * otherwise `OPENROUTER_API_KEY` -> `/api/v1/key`, `source:"key"`, giving
      that ONE key's `usage` against its own `limit`. `remaining_usd` is
      deliberately `None` here: a key limit is not an account balance and
      putting one in the other's field is how a tile starts lying.
    * neither -> `available: false`.

    **The `/api/v1/key` retry is the plan's one UNVERIFIED fact.** The vendor
    docs name `GET /api/v1/key`; this repository's own vault probe
    (`credentials.py`) has always used `/api/v1/auth/key`, and whether the two
    are aliases is undocumented. So a **404 and only a 404** on the first
    spelling retries the second, once. A 401 does not retry - that is a key
    problem and trying a second URL with the same key would answer the same
    thing twice. The vault probe is NOT changed here; that is a plan-01
    follow-up.
    """

    management = os.environ.get("OPENROUTER_MANAGEMENT_KEY", "").strip()
    inference = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not management and not inference:
        return unavailable(
            "OPENROUTER_MANAGEMENT_KEY and OPENROUTER_API_KEY are both unset"
        )
    owns_client = client is None
    http = client if client is not None else _client()
    try:
        if management:
            return _openrouter_credits(http, management)
        return _openrouter_key(http, inference)
    except Exception as exc:  # noqa: BLE001 - every transport failure is equal
        # The class name, never the message: a transport error's message can
        # carry the request URL, and a URL can carry a credential.
        logger.info("openrouter probe failed: %s", type(exc).__name__)
        return unavailable(
            f"the OpenRouter probe did not complete ({type(exc).__name__})"
        )
    finally:
        if owns_client:
            try:
                http.close()
            except Exception:  # pragma: no cover - closing must never raise
                pass


def _openrouter_credits(http: Any, key: str) -> dict[str, Any]:
    response = http.get(
        config.OPENROUTER_CREDITS_URL, headers={"Authorization": f"Bearer {key}"}
    )
    if response.status_code >= 400:
        return unavailable(_status_reason("OpenRouter", response.status_code))
    try:
        data = response.json().get("data") or {}
    except (ValueError, json.JSONDecodeError, AttributeError):
        return unavailable("OpenRouter's credits response was not JSON")
    total = _number(_first(data, "total_credits", "totalCredits"))
    used = _number(_first(data, "total_usage", "totalUsage"))
    if total is None or used is None:
        return unavailable(
            "OpenRouter's credits response carried no total_credits/total_usage"
        )
    return {
        "available": True,
        "reason": None,
        "source": "credits",
        "total_credits": total,
        "total_usage": used,
        "remaining_usd": round(total - used, 6),
        "usage": None,
        "limit": None,
        "limit_remaining": None,
        "is_free_tier": None,
        "label": None,
        "checked_at": _iso_now(),
        "age_seconds": 0.0,
    }


def _openrouter_key(http: Any, key: str) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {key}"}
    response = http.get(config.OPENROUTER_KEY_URL, headers=headers)
    if response.status_code == 404:
        # The UNVERIFIED alias, tried once. See the docstring above.
        response = http.get(config.OPENROUTER_KEY_URL_FALLBACK, headers=headers)
    if response.status_code >= 400:
        return unavailable(_status_reason("OpenRouter", response.status_code))
    try:
        data = response.json().get("data") or {}
    except (ValueError, json.JSONDecodeError, AttributeError):
        return unavailable("OpenRouter's key response was not JSON")
    usage = _number(_first(data, "usage"))
    if usage is None:
        return unavailable("OpenRouter's key response carried no usage figure")
    limit = _number(_first(data, "limit"))
    return {
        "available": True,
        "reason": None,
        "source": "key",
        "total_credits": None,
        "total_usage": None,
        # NOT the account balance. A key limit is a different measurement and
        # this field means the balance, so it stays null on this rung.
        "remaining_usd": None,
        "usage": usage,
        "limit": limit,
        "limit_remaining": _number(_first(data, "limit_remaining", "limitRemaining")),
        "is_free_tier": bool(_first(data, "is_free_tier", "isFreeTier")) or None,
        # The key's own LABEL, which the vendor lets a person type. Truncated
        # and passed through as-is; it is not a credential and it is the only
        # way to tell two keys apart on a tile.
        "label": (str(data["label"])[:120] if isinstance(data.get("label"), str) else None),
        "checked_at": _iso_now(),
        "age_seconds": 0.0,
    }


# ---------------------------------------------------------------------------
# B. Firecrawl - one endpoint, two spellings, one code path
# ---------------------------------------------------------------------------


def firecrawl_credits(*, client: Any = None) -> dict[str, Any]:
    """`GET /v2/team/credit-usage`, normalising camelCase AND snake_case.

    v2 answers `remainingCredits`/`planCredits`/`billingPeriodStart`/`End`;
    v1 answers the same four in snake_case. `_first` reads both, which is four
    lines against a whole class of silent `None` - the failure where a
    perfectly configured account renders as "0 credits" because the reader
    knew one spelling.

    The `credits_total`/`credits_used` trio that appears in Firecrawl's prose
    is in **neither** OpenAPI spec, so nothing here codes against it.
    """

    key = os.environ.get("FIRECRAWL_API_KEY", "").strip()
    if not key:
        return unavailable("FIRECRAWL_API_KEY is unset")
    owns_client = client is None
    http = client if client is not None else _client()
    try:
        response = http.get(
            config.FIRECRAWL_CREDIT_USAGE_URL,
            headers={"Authorization": f"Bearer {key}"},
        )
        if response.status_code >= 400:
            return unavailable(_status_reason("Firecrawl", response.status_code))
        try:
            payload = response.json()
        except (ValueError, json.JSONDecodeError):
            return unavailable("Firecrawl's credit-usage response was not JSON")
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict):
            data = payload if isinstance(payload, dict) else {}
        remaining = _whole(_first(data, "remainingCredits", "remaining_credits"))
        if remaining is None:
            return unavailable(
                "Firecrawl's credit-usage response carried no remaining credits"
            )
        return {
            "available": True,
            "reason": None,
            "remaining_credits": remaining,
            "plan_credits": _whole(_first(data, "planCredits", "plan_credits")),
            "billing_period_start": _text(
                _first(data, "billingPeriodStart", "billing_period_start")
            ),
            "billing_period_end": _text(
                _first(data, "billingPeriodEnd", "billing_period_end")
            ),
            "checked_at": _iso_now(),
            "age_seconds": 0.0,
        }
    except Exception as exc:  # noqa: BLE001
        logger.info("firecrawl probe failed: %s", type(exc).__name__)
        return unavailable(
            f"the Firecrawl probe did not complete ({type(exc).__name__})"
        )
    finally:
        if owns_client:
            try:
                http.close()
            except Exception:  # pragma: no cover
                pass


def _text(value: Any) -> str | None:
    return str(value)[:64] if isinstance(value, (str, int, float)) else None


# ---------------------------------------------------------------------------
# C. Langfuse - what one run was actually billed
# ---------------------------------------------------------------------------

#: Where the model NAME lives on a v2 GENERATION, in the order to try.
#:
#: **`model` is the RESOLVED model and it is null here**, measured on the paid
#: proof: it is Langfuse's match against its own model-definition table, and
#: nothing in that table matches an `openrouter/...` string. What the exporter
#: actually sent survives as `providedModelName`.
#:
#: Read as an ordered list rather than as one key, for the reason `_first`
#: exists on the Firecrawl arm: a reader that knows one spelling reports a
#: perfectly recorded run as having no model, and does it silently.
_MODEL_KEYS = ("model", "providedModelName", "modelId", "internalModelId")


def langfuse_billed(run_id: str, *, client: Any = None) -> dict[str, Any]:
    """Sum `costDetails.total` over one run's GENERATION observations.

    **Selected by `traceId`, NOT by a `sessionId` filter, and that correction
    cost a paid run to find.** `sessionId` is an attribute of the TRACE; on a
    v2 GENERATION row it is null. So the filter clause this function used to
    send matched nothing, always - a 200 carrying `{"data": [], "meta": {}}` -
    and the drawer said "Langfuse has no generations for this run yet" for
    ever. That is the sentence written for the ingestion lag, which makes it
    the one nobody would question: the bug wore the shape of the thing it was
    supposed to report.

    Measured on run `4681d938-427d-4e0c-be85-cc9d84153052`, nine minutes after
    it finished: the sessionId filter answered 0 rows;
    `?traceId=4681d938427d4e0cbe85cc9d84153052` answered 3, each carrying a
    `costDetails.total` - and every one of those rows had `sessionId: None`.

    The trace id comes from **`observability.backend.trace_id_for`**,
    imported, never re-derived - the same rule criterion 20 already binds the
    deep link to. It has to be that function or the console would link to one
    trace and price another, and the two would agree for exactly the UUID run
    ids everybody tests with.

    Four more facts about the v2 API decide the rest, and three of them fail
    silently rather than loudly:

    * **Auth is HTTP Basic**, public key as the username, secret as the
      password.
    * **Cost must be ASKED FOR.** `fields=core,basic,usage` - the default
      `core,basic` omits **every** cost field, so a reader that does not send
      this gets a 200 carrying observations with no costs and concludes the
      run was free.
    * **There is no `page`.** The envelope is `{"data": [...], "meta":
      {"cursor": "..."}}` and paging follows `meta.cursor`, bounded here at
      `LANGFUSE_BILLED_PAGE_LIMIT` pages so a paging bug cannot walk a whole
      project.
    * **`model` is null on these rows too** - see `_MODEL_KEYS`. It is
      Langfuse's resolved model and an `openrouter/...` string matches nothing
      in its model table; `providedModelName` carries what was sent.

    `calculatedTotalCost` was v1 and is gone; `costDetails.total` is the
    figure, with the flat `totalCost` as the fallback for an observation that
    carries one and not the other.
    """

    public = os.environ.get("LANGFUSE_PUBLIC_KEY", "").strip()
    secret = os.environ.get("LANGFUSE_SECRET_KEY", "").strip()
    if not public or not secret:
        return unavailable("LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY are not both set")
    if not config.LANGFUSE_PROJECT_ID:
        return unavailable("LANGFUSE_PROJECT_ID is unset, so there is no project to read")
    base = (config.LANGFUSE_BASE_URL or "").rstrip("/")
    if not base:
        return unavailable("LANGFUSE_BASE_URL is unset")
    # IMPORTED, never re-derived - criterion 20's rule, applied to the read as
    # well as to the link.
    from brief_crew.observability.backend import trace_id_for

    trace_id = trace_id_for(str(run_id))
    owns_client = client is None
    http = client if client is not None else _client()
    try:
        total = 0.0
        generations = 0
        sources: dict[str, int] = {}
        models: dict[str, int] = {}
        cursor: str | None = None
        for _page in range(max(1, int(config.LANGFUSE_BILLED_PAGE_LIMIT))):
            params: dict[str, Any] = {
                # The named parameter, not a `filter` clause: `sessionId` is a
                # TRACE attribute and is null on every row this asks for.
                "traceId": trace_id,
                "type": "GENERATION",
                "fields": "core,basic,usage",
                "limit": 100,
            }
            if cursor:
                params["cursor"] = cursor
            response = http.get(
                f"{base}/api/public/v2/observations",
                params=params,
                auth=(public, secret),
            )
            if response.status_code >= 400:
                return unavailable(_status_reason("Langfuse", response.status_code))
            try:
                payload = response.json()
            except (ValueError, json.JSONDecodeError):
                return unavailable("Langfuse's observations response was not JSON")
            rows = payload.get("data") if isinstance(payload, dict) else None
            if not isinstance(rows, list):
                return unavailable("Langfuse's observations response carried no data")
            for row in rows:
                if not isinstance(row, dict):
                    continue
                generations += 1
                cost = None
                details = row.get("costDetails")
                if isinstance(details, dict):
                    cost = _number(details.get("total"))
                if cost is None:
                    cost = _number(row.get("totalCost"))
                if cost is not None:
                    total += cost
                raw_metadata = row.get("metadata")
                metadata = raw_metadata if isinstance(raw_metadata, dict) else {}
                # `metadata.cost_source` is the exporter's OWN key - contract
                # section 4 - and it is what says whether this figure is
                # OpenRouter's or the app's estimate standing in for it.
                source = metadata.get("cost_source")
                name = str(source) if isinstance(source, str) and source else "unknown"
                sources[name] = sources.get(name, 0) + 1
                model = _model_name(row, metadata)
                models[model] = models.get(model, 0) + 1
            meta = payload.get("meta") if isinstance(payload, dict) else None
            cursor = meta.get("cursor") if isinstance(meta, dict) else None
            if not cursor:
                break
        if generations == 0:
            # 200 with nothing is not a failure of this probe and not proof
            # the run was free: Langfuse's ingestion lags, and a run looked up
            # too soon has no observations yet. The sentence says so, because
            # "$0.00" here would be read as a measurement.
            return {
                "available": False,
                "reason": (
                    "Langfuse has no generations for this run yet; ingestion "
                    "lags a run by up to a minute"
                ),
                "generations": 0,
                "billed_usd": None,
                "cost_source_counts": {},
                "model_counts": {},
                "fetched_at": _iso_now(),
            }
        return {
            "available": True,
            "reason": None,
            "generations": generations,
            "billed_usd": round(total, 8),
            "cost_source_counts": sources,
            "model_counts": models,
            "fetched_at": _iso_now(),
        }
    except Exception as exc:  # noqa: BLE001
        logger.info("langfuse billed lookup failed: %s", type(exc).__name__)
        return unavailable(
            f"the Langfuse billed lookup did not complete ({type(exc).__name__})"
        )
    finally:
        if owns_client:
            try:
                http.close()
            except Exception:  # pragma: no cover
                pass


# ---------------------------------------------------------------------------
# The TTL cache
# ---------------------------------------------------------------------------


class ProviderProbes:
    """The two balance probes behind `ADMIN_PROVIDER_CACHE_SECONDS`.

    Two calls inside the window make ONE HTTP request and the second carries
    an `age_seconds` saying how old the answer is - so a person reading a
    balance always knows whether they are looking at a fresh number, which is
    the whole difference between a dashboard and a screenshot.

    **A failure is cached too.** The expensive case is the one that repeats: a
    dead upstream with no negative caching is hammered once per page load by
    every open dashboard, which is how a monitoring page becomes an outage's
    amplifier.

    `/runs/{id}/billed` is deliberately NOT cached: it is fetched on an
    explicit click, one run at a time, and a person who clicks Fetch billed a
    second time is asking precisely because the first answer was too early.

    The lock is held across the call rather than only around the dictionary.
    That serialises two dashboards opening at once into one outbound request
    instead of two, which is the cheaper mistake: the alternative lets N
    dashboards make N requests to an upstream that is already slow.
    """

    def __init__(
        self,
        *,
        clock: Any = None,
        openrouter_probe: Any = None,
        firecrawl_probe: Any = None,
        billed_probe: Any = None,
    ) -> None:
        import time

        self._clock = clock or time.monotonic
        self._openrouter = openrouter_probe or openrouter_balance
        self._firecrawl = firecrawl_probe or firecrawl_credits
        self._billed = billed_probe or langfuse_billed
        self._lock = threading.Lock()
        self._cache: dict[str, tuple[float, dict[str, Any]]] = {}

    def _cached(self, name: str, probe: Any) -> dict[str, Any]:
        ttl = float(config.ADMIN_PROVIDER_CACHE_SECONDS)
        with self._lock:
            now = self._clock()
            entry = self._cache.get(name)
            if entry is not None and now - entry[0] < ttl:
                answer = dict(entry[1])
                if "age_seconds" in answer:
                    answer["age_seconds"] = round(now - entry[0], 3)
                return answer
            answer = probe()
            self._cache[name] = (now, dict(answer))
            return dict(answer)

    def openrouter(self) -> dict[str, Any]:
        return _shaped(
            self._cached("openrouter", self._openrouter),
            (
                "source",
                "total_credits",
                "total_usage",
                "remaining_usd",
                "usage",
                "limit",
                "limit_remaining",
                "is_free_tier",
                "label",
                "checked_at",
                "age_seconds",
            ),
        )

    def firecrawl(self) -> dict[str, Any]:
        return _shaped(
            self._cached("firecrawl", self._firecrawl),
            (
                "remaining_credits",
                "plan_credits",
                "billing_period_start",
                "billing_period_end",
                "checked_at",
                "age_seconds",
            ),
        )

    def langfuse_billed(self, run_id: str) -> dict[str, Any]:
        """Uncached, on purpose - see the class docstring."""

        return self._billed(run_id)

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()


def _shaped(answer: dict[str, Any], optional: tuple[str, ...]) -> dict[str, Any]:
    """One answer with every optional key present, defaulting to `None`.

    The success and failure shapes reach the client with the same key set, so
    `adminApi.ts` reads one shape and the response model can be
    `extra="forbid"` without either arm needing its own branch.
    """

    shaped: dict[str, Any] = {
        "available": bool(answer.get("available")),
        "reason": answer.get("reason"),
    }
    for name in optional:
        shaped[name] = answer.get(name)
    return shaped
