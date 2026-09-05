"""Turning the app's cost ESTIMATE into what was actually billed (section 4).

Every dollar figure this application produces is `tokens x a local price table`
- the provider's own per-generation cost never reaches the process, because the
provider layer whitelists five token keys out of the response and discards the
rest. What DOES survive is the generation id, which the frame pipeline already
records on every completed model call.

So the resolution is out of band and after the fact: once a generation has been
sent, ask the provider what that id cost, and UPDATE the observation. Four
bounds, and each one exists because this runs on a telemetry thread:

* it never runs at all for a synthetic run, whose ids are fabricated;
* it never runs for a call with no id, which is every streamed-but-unfinished
  call and every no-cost double;
* it is capped per run, so a long run cannot spend its export thread on lookups;
* every request carries the exporter's own timeout.

A failure is not an error. The observation keeps the estimate and says so:
`metadata.cost_source` reads `app-estimate (lookup failed)`, which is a
different statement from `app-estimate` and is the one a reconciliation needs.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
import os
from typing import Any, Protocol


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class BilledCost:
    """What the provider says one generation cost, and who served it.

    It also carries the two token splits the frame pipeline drops. The frame
    serializer normalises usage through an alias table that whitelists the five
    ordinary counts, so reasoning and cached tokens - the two that decide what
    an escalation-tier call actually cost - never reach a frame. They are read
    here instead. That is a deliberate division: the serializer is on the
    capture path of every run and is not being changed for a figure only the
    provider knows.
    """

    total_usd: float
    provider: str | None = None
    upstream_usd: float | None = None
    reasoning_tokens: int | None = None
    cached_tokens: int | None = None


class CostLookup(Protocol):
    def lookup(self, response_id: str) -> BilledCost | None: ...

    def close(self) -> None: ...


class NullCostLookup:
    """Answers nothing. Used when the resolution is off or the run is synthetic."""

    def lookup(self, response_id: str) -> BilledCost | None:
        return None

    def close(self) -> None:
        return None


class HttpCostLookup:
    """One GET per generation id, with the key read at call time and never logged.

    The key is read from the environment on each call rather than captured at
    construction, because the exporter is built once at startup and a
    deployment may set the variable afterwards; and because a captured
    credential is a credential living in an object graph for the life of the
    process for no benefit.
    """

    def __init__(self, *, url: str, timeout: float) -> None:
        import httpx

        self._url = url
        self._client = httpx.Client(
            timeout=timeout,
            headers={"User-Agent": "brief-crew-observability/1"},
        )

    def lookup(self, response_id: str) -> BilledCost | None:
        key = os.environ.get("OPENROUTER_API_KEY", "").strip()
        if not key:
            return None
        response = self._client.get(
            self._url,
            params={"id": response_id},
            headers={"Authorization": f"Bearer {key}"},
        )
        if response.status_code >= 400:
            raise RuntimeError(f"generation lookup answered {response.status_code}")
        return parse_generation(response.json())

    def close(self) -> None:
        try:
            self._client.close()
        except Exception:  # pragma: no cover - closing must never raise
            pass


def parse_generation(payload: Any) -> BilledCost | None:
    """Read a cost out of the provider's generation record, or answer nothing.

    Written against the shape rather than against a schema: the record is
    `{"data": {...}}` with `total_cost` in credits-as-dollars, and a payload
    that does not carry a number is not an error - it is a lookup that did not
    answer, which the caller records as such.
    """

    if not isinstance(payload, dict):
        return None
    data = payload.get("data")
    if not isinstance(data, dict):
        data = payload
    total = data.get("total_cost")
    if total is None:
        total = data.get("cost")
    try:
        total_usd = float(total)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    upstream = data.get("cache_discount")
    try:
        upstream_usd = float(upstream) if upstream is not None else None
    except (TypeError, ValueError):
        upstream_usd = None
    provider = data.get("provider_name") or data.get("provider")
    if not provider:
        responses = data.get("provider_responses")
        if isinstance(responses, list) and responses:
            head = responses[0]
            if isinstance(head, dict):
                provider = head.get("provider_name") or head.get("provider")
    return BilledCost(
        total_usd=total_usd,
        provider=str(provider)[:120] if provider else None,
        upstream_usd=upstream_usd,
        reasoning_tokens=_as_int(data.get("native_tokens_reasoning")),
        cached_tokens=_as_int(data.get("native_tokens_cached")),
    )


def _as_int(value: Any) -> int | None:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
