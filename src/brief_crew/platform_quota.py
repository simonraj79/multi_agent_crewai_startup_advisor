"""The seam between a run's owner and a tool that spends a PLATFORM key.

Audit H4. `BUILDER_PLATFORM_FIRECRAWL_DEFAULT` hands the deployment's own
Firecrawl key to every signed-in user's research tools, and the cap its
manifest comment cited as the bound had exactly one reader - its own definition
in `config.py`. `service/persistence.py::claim_platform_quota` is now the
counter; this module is how a tool reaches it without importing the service.

**Why it is a top-level module and not `builder/quota.py`.** Three importers:
`builder/tools.py`, `builder/runtime.py` and `service/credentials.py`. The
first two must stay importable without the service package - `tool_problems`
says so in its own docstring - and the third already imports
`service/persistence.py`. Putting the ContextVar under `builder/` would make
`service.credentials -> builder.__init__ -> builder.registry -> ...` an import
cycle waiting to be discovered by whoever next adds a line to that `__init__`.
This module imports `brief_crew.config` and the standard library, and nothing
else, so nobody can create that cycle by accident.

**The ContextVar carries a CALLABLE, not a user id.** The same reason
`credentials.py` scopes a store rather than a database URL: a tool must not be
able to name an account, and a claim it cannot forge is one it can only spend
against whoever the runner said. `service/credentials.py::credential_scope`
binds it - the seam is already entered around every `kickoff` and every
`resume`, and CrewAI copies the context into the worker threads a fan-out
starts, so a parallel branch charges the same account without being handed it.

**`None` means NO PLATFORM KEY, never "unlimited".** Outside a run - the CLI,
a unit test, a bare checkout - there is no account to charge, so a metered tool
refuses instead of spending. That is the whole inversion this module exists to
make: the default is off, and the run scope is what turns it on.

The refusal is an ENVELOPE, not an exception. The tools this wraps all return
the repository's JSON envelope (`status`, `tool`, `query`, `retrieved_at`,
`result_count`, `results`, `notes`) and their agents are prompted to read
`notes` when `status` is not `ok`. Raising would abort a branch over a quota,
which is a worse answer than a branch that reports it found nothing and says
why - and it is the same judgement `market_research.py` already makes for a
missing key, a rate limit and a timeout.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
import json
from typing import Any

from brief_crew import config

__all__ = [
    "PlatformQuotaClaim",
    "claim_platform_call",
    "current_platform_quota",
    "platform_daily_cap",
    "platform_metered",
    "platform_quota_scope",
    "quota_refusal_envelope",
]

#: `(provider) -> (granted, used_after)`. Bound to one account and one store by
#: `service/credentials.py`; see that module's `credential_scope`.
PlatformQuotaClaim = Callable[[str], "tuple[bool, int]"]

#: The claim for the run executing on this thread and everything it spawns.
#: `None` outside a run, and `None` for a run with no owner - both of which
#: mean "no platform key", because neither can be charged.
current_platform_quota: ContextVar[PlatformQuotaClaim | None] = ContextVar(
    "brief_crew_current_platform_quota", default=None
)


@contextmanager
def platform_quota_scope(claim: PlatformQuotaClaim | None) -> Iterator[None]:
    """Scope one account's platform allowance over everything this thread starts.

    Entered from `credential_scope`, which is already the seam a run's owner
    arrives through - one context manager rather than two that could be entered
    apart, because a run scoped for credentials and not for quota would be a
    run whose platform spend is unmetered, which is exactly the state H4 found.
    """

    token = current_platform_quota.set(claim)
    try:
        yield
    finally:
        current_platform_quota.reset(token)


def platform_daily_cap(provider: str) -> int:
    """This deployment's daily allowance for `provider`, or zero.

    Zero for a provider nobody has decided a cap for, and zero refuses - see
    `config.PLATFORM_TOOL_DAILY_CAPS`, which is a closed set for that reason.
    """

    return int(config.PLATFORM_TOOL_DAILY_CAPS.get(provider, 0))


def claim_platform_call(provider: str) -> str | None:
    """Take one unit for this run's owner. `None` on a grant, else the sentence.

    A string return rather than a raise, and rather than a bare False: the
    caller has to put a reason in front of a model, and a caller that had to
    compose that sentence itself is a caller that will compose it differently
    in the second place it is needed.
    """

    claim = current_platform_quota.get()
    if claim is None:
        return config.PLATFORM_QUOTA_UNSCOPED_NOTE.format(provider=provider)
    granted, _used = claim(provider)
    if granted:
        return None
    return config.PLATFORM_QUOTA_SPENT_NOTE.format(
        cap=platform_daily_cap(provider), provider=provider
    )


def quota_refusal_envelope(*, tool: str, query: str, notes: str) -> str:
    """The repository's tool envelope, carrying a refusal and no evidence.

    Key for key and in the order `tools/market_research.py::_envelope` writes
    them, deliberately: the guardrails parse this shape, and an envelope that
    was nearly the same shape would fail somewhere further from here.
    """

    return json.dumps(
        {
            "status": "failed",
            "tool": tool,
            "query": query,
            "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "result_count": 0,
            "results": [],
            "notes": notes,
        },
        ensure_ascii=True,
    )


def _query_of(args: tuple[Any, ...], kwargs: dict[str, Any]) -> str:
    """Whatever the caller asked for, for the envelope's `query` field.

    Best effort by design: the wrapper is generic over tool classes, so it
    reads the first positional string or a `query` keyword and otherwise
    reports an empty string rather than guessing at a schema it does not know.
    """

    for value in args:
        if isinstance(value, str):
            return value
    for key in ("query", "search_query", "url"):
        value = kwargs.get(key)
        if isinstance(value, str):
            return value
    return ""


def platform_metered(tool_cls: type, *, provider: str) -> type:
    """A subclass of `tool_cls` that claims one unit before each real call.

    Applied only where a tool falls back to a key this DEPLOYMENT owns; a tool
    built with the author's own credential is never wrapped, because their key
    is their allowance. The subclass is named after its parent for the same
    reason `builder/tools.py::_env_scoped`'s is: the class name reaches the
    agent's tool list and a `MarketResearchTool_Metered` in a prompt would be
    an implementation detail leaking into a model's context.

    Nothing about the credential or the account is stored on the instance - the
    provider is a closure cell and the account is a ContextVar - so no
    `model_dump`, repr or frame serialiser gains a field here.
    """

    class _Metered(tool_cls):  # type: ignore[misc,valid-type]
        def _run(self, *args: Any, **kwargs: Any) -> Any:
            refusal = claim_platform_call(provider)
            if refusal is not None:
                return quota_refusal_envelope(
                    tool=str(getattr(self, "name", tool_cls.__name__)),
                    query=_query_of(args, kwargs),
                    notes=refusal,
                )
            return super()._run(*args, **kwargs)

    _Metered.__name__ = tool_cls.__name__
    _Metered.__qualname__ = tool_cls.__qualname__
    return _Metered
