"""App-side Langfuse instrumentation, built on this repository's frame spine.

`docs/observability/TRACE-CONTRACT.md` is the contract; this package implements
it and owns nothing else. Three sentences are worth having before reading any
of it:

* **It attaches to frames, not to CrewAI.** The frame pipeline has already
  solved attribution, bounding, redaction and ordering, and its vocabulary
  names no flow, agent, task or tool. Everything here is therefore generic by
  construction rather than by discipline.
* **It cannot fail a run.** Every path is total, every queue is bounded, every
  request is timed out, and the one callback on the capture thread does queue
  operations and nothing else. A misconfigured or unreachable backend produces
  one log line and a run that behaves identically.
* **It sends no content by default.** Fingerprints, key lists, counts and
  character lengths go instead. `LANGFUSE_CAPTURE_CONTENT=1` turns text on, and
  even then every string passes the redaction rules already in force plus a
  key-shape scrubber.

`build_exporter` is the only thing the service calls.
"""

from __future__ import annotations

import logging
import os

from brief_crew.observability.langfuse_exporter import (
    LangfuseExporter,
    NullExporter,
    RunFacts,
)
from brief_crew.observability.policy import (
    ENVIRONMENT_LIVE,
    ENVIRONMENT_SYNTHETIC,
    ExporterPolicy,
    policy_from_config,
)


logger = logging.getLogger(__name__)

__all__ = [
    "ExporterPolicy",
    "LangfuseExporter",
    "NullExporter",
    "RunFacts",
    "build_exporter",
    "exporter_state",
    "policy_from_config",
]


def exporter_state(exporter: object, *, synthetic: bool = False) -> dict[str, object]:
    """What the exporter is doing, for `/readyz`. Never a key, never a URL.

    Row D5 in one function. The startup line says this once, into a log nobody
    reading a deployed service can see - measured: a bare `serve.exe` printed
    uvicorn's four lines and then nothing, so the only way to find out whether
    anything was being exported was to launch a run and go and look in
    Langfuse. On a PAID run that is the wrong order: the money is spent before
    the answer arrives.

    Five values, and each is a question somebody asks before pressing Launch:
    is it on, why not, will this land in the synthetic or the live view, is
    prompt text being sent, and will provider costs be looked up. Deliberately
    NOT here: the base URL and either key. A URL can carry credentials in its
    userinfo, `/readyz` is unauthenticated, and neither is a thing this answer
    needs - "which project" is a question for the person who set the variable.
    """

    policy = getattr(exporter, "policy", None)
    if policy is None:
        return {
            "exporter": "disabled",
            "reason": str(getattr(exporter, "reason", "") or "not configured"),
            "environment": ENVIRONMENT_SYNTHETIC if synthetic else ENVIRONMENT_LIVE,
            "capture_content": False,
            "resolve_billed_cost": False,
        }
    return {
        "exporter": "enabled",
        "reason": None,
        "environment": policy.environment,
        "capture_content": bool(policy.capture_content),
        # The effective answer, not the knob, and it now includes the KEY.
        #
        # `GET /api/v1/generation?id=` answers only for the key that made the
        # request - the same id returns 401 with no `Authorization` header,
        # measured - so with `OPENROUTER_API_KEY` unset the lookup returns
        # `None` on every call and the feature cannot work however the flag is
        # set. Reporting the knob said `true` for a process that would never
        # resolve anything, which is exactly the state row D5 exists to make
        # visible before money is spent. The lookup is also skipped outright on
        # a synthetic run, whose ids are fabricated.
        "resolve_billed_cost": bool(
            policy.resolve_billed_cost
            and not policy.synthetic
            and os.environ.get("OPENROUTER_API_KEY", "").strip()
        ),
    }


def _log_off(policy: ExporterPolicy, reason: str) -> None:
    """The one startup line for an exporter that is off, at a level that fits.

    WARNING when the process HOLDS Langfuse credentials and is exporting
    nothing anyway, INFO otherwise, and the difference is the whole point. A
    deployment with no keys has made a choice and does not need telling twice;
    a deployment that carries keys and exports nothing is a misconfiguration,
    and it is invisible - the measured symptom is a bare `serve.exe` whose
    startup line went to `logging.lastResort`, which is fixed at WARNING, so an
    INFO record about the exporter being off reached nobody at all. That is the
    same trap the per-run summary line already carries a comment about, met a
    second time on the line that would have prevented the first.

    The reason names a VARIABLE, never a value: `ExporterPolicy.reason_unusable`
    is written to that rule and this only passes it through.
    """

    has_keys = bool(policy.public_key and policy.secret_key)
    logger.log(
        logging.WARNING if has_keys else logging.INFO,
        "langfuse export is off: %s",
        reason,
    )


def build_exporter(*, synthetic: bool = False, policy: ExporterPolicy | None = None):
    """The exporter for this process, or a no-op that says why, once.

    Never raises. An observability backend that is missing, misconfigured or
    unreachable must not stop a service starting, which is why nothing here
    joins the three startup assertions in `service/app.py` - those guard money
    and secrets.

    `synthetic=True` does NOT disable it. A synthetic run is the only run this
    package can be proved on without spending money, and it is marked as
    `environment=synthetic` so its fabricated usage never lands in a cost view
    beside a run that was actually billed.
    """

    try:
        resolved = policy if policy is not None else policy_from_config(synthetic=synthetic)
    except Exception:
        logger.info("langfuse export is off: its configuration could not be read")
        return NullExporter("configuration unreadable")
    if not resolved.usable:
        _log_off(resolved, resolved.reason_unusable())
        return NullExporter(resolved.reason_unusable())
    try:
        exporter = LangfuseExporter(resolved)
    except Exception as exc:
        _log_off(
            resolved,
            f"the exporter could not be built ({type(exc).__name__})",
        )
        return NullExporter("could not be built")
    logger.info(
        "langfuse export is on: environment=%s content=%s billed-cost=%s",
        resolved.environment,
        "on" if resolved.capture_content else "off",
        "on" if resolved.resolve_billed_cost and not resolved.synthetic else "off",
    )
    return exporter
