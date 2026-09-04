"""The server-owned tool catalogue - plan 06.

**A document names an id; the server owns the class.** That is the same
principle `BUILDER_ACTION_REFS` applies to compiled entrypoints, applied one
level down: a `tool` attachment node carries `tool_id`, `params` and an opaque
`credential_id`, and nothing else. No module path, no class name and no
callable ever reaches a document, so the answer to "can an author execute code
through a tool?" is the same closed-set answer the compiler already gives.

Three facts from the installed package decided what can ship, and each one
contradicts something a reader might expect. **Where the plan and the package
disagree, the package wins** (`docs/crewai-notes.md` section 11):

1. **`CodeInterpreterTool` no longer exists**, and `Agent.allow_code_execution`
   / `code_execution_mode` are `Field(deprecated=True)` at 1.15.18. The only
   sandboxes CrewAI ships are E2B and Daytona, each a paid third-party account.
   `code_interpreter` is therefore a catalogue entry that exists but is
   **withheld** unless `BUILDER_CODE_INTERPRETER_ENABLED` is set, and the flag
   is off (PLANS.md decision 3, provisional).
2. **Firecrawl `map` and `extract` have no `crewai_tools` class.** Only scrape,
   crawl and search exist, so only those three are listed. Inventing a class
   name would have produced a catalogue entry that raises `AttributeError` at
   the first paid run.
3. **`SerperDevTool` and `BraveSearchTool` have no `api_key` field.** They read
   `os.environ["SERPER_API_KEY"]` / `["BRAVE_API_KEY"]` *inside `_run`*, at call
   time. Plan 06 D4 says a factory "never reads `os.environ` for a user-scoped
   credential", and for those two classes that is not achievable by
   construction - so the credential is bound in a **closure** and written into
   the environment for the duration of one `_run` under a process lock
   (`_env_scoped`). The factory still never *reads* the environment, the value
   is never a pydantic field, and `model_dump` on the tool cannot emit it.
   Documented rather than hidden, because a reader who greps for `os.environ`
   in this file deserves to find the reason beside it.

**The secret is a closure cell, never a field.** Every factory here either
passes the plaintext straight into a constructor keyword the class declares
(`api_key=`, `gh_token=`, `db_uri=`, `headers=`) or captures it in `_env_scoped`.
Nothing writes it onto an attribute this module could later serialise, which is
what makes "a captured tool frame never contains the credential" a property of
the design rather than of a redaction list.
"""

from __future__ import annotations

import importlib.util
import ipaddress
import json
import os
import re
import socket
import threading
import urllib.parse
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

from brief_crew import config as project_config
from brief_crew.builder.bounds import Problem
from brief_crew.builder.document import ATTACH_TARGET_KINDS, BuilderDocument, ToolConfig

# --------------------------------------------------------------------------
# Problem codes
#
# Declared here, at module level, in the exact shape
# `frontend/tests/builderTypes.spec.ts` greps for - and this file is named in
# that spec's source list, in `tests/builder/test_problem_code_declarations.py`
# and in `scripts/emit_builder_fixtures.py`. All four move together or the
# client renders a code it has never heard of, which is section 14's defect 2.
# --------------------------------------------------------------------------
#: A `tool_id` that is neither a builtin nor one of THIS caller's custom tools.
#: One code for "no such tool" and "somebody else's tool", for the reason
#: `credential-missing` gives: a canvas that told the two apart would be an
#: oracle for other people's ids.
TOOL_UNKNOWN = "tool-unknown"
#: `params` that the entry's own schema refuses - an unknown key, a value out of
#: range, a provider outside the enum.
TOOL_PARAM_INVALID = "tool-param-invalid"
#: The entry requires a credential of some kind and the node names none. A
#: DIFFERENT repair from `credential-missing` - "add a key of this kind" rather
#: than "that id is not yours" - and therefore a different code, which is the
#: rule `compiler.py` already states for its three library codes.
TOOL_CREDENTIAL_REQUIRED = "tool-credential-required"


# --------------------------------------------------------------------------
# The entry shape
# --------------------------------------------------------------------------
ParamType = Literal["string", "integer", "boolean", "array"]


@dataclass(frozen=True, slots=True)
class ParamSpec:
    """One author-settable parameter, and every bound it is checked against.

    Rendered to a JSON Schema fragment for the inspector and checked against by
    `validate_params` here. One declaration, two consumers: a form control the
    server would refuse is exactly the "parameter rendered in the UI that the
    compiler ignores" the gauntlet forbids.
    """

    name: str
    type: ParamType
    default: Any
    description: str
    enum: tuple[str, ...] | None = None
    minimum: int | None = None
    maximum: int | None = None
    #: For `array`: the closed set its members come from.
    items_enum: tuple[str, ...] | None = None

    def wire(self) -> dict[str, Any]:
        """One row of `BuilderToolCatalogueEntry.params`, as the client reads it.

        `required` is always false and that is a property of the catalogue
        rather than an omission: every entry declares a default for every
        parameter, so there is no configuration an author can leave incomplete.
        A parameter that had no sensible default would be a tool this product
        cannot offer with zero configuration, which the idea-validator template
        depends on.
        """

        row: dict[str, Any] = {
            "name": self.name,
            "type": self.type,
            "required": False,
            "default": list(self.default) if isinstance(self.default, tuple) else self.default,
            "description": self.description,
        }
        if self.enum is not None:
            row["enum"] = list(self.enum)
        if self.items_enum is not None:
            row["enum"] = list(self.items_enum)
        if self.minimum is not None:
            row["min"] = self.minimum
        if self.maximum is not None:
            row["max"] = self.maximum
        return row

    def json_schema(self) -> dict[str, Any]:
        schema: dict[str, Any] = {"type": self.type, "description": self.description}
        if self.enum is not None:
            schema["enum"] = list(self.enum)
        if self.minimum is not None:
            schema["minimum"] = self.minimum
        if self.maximum is not None:
            schema["maximum"] = self.maximum
        if self.items_enum is not None:
            schema["items"] = {"type": "string", "enum": list(self.items_enum)}
        schema["default"] = list(self.default) if isinstance(self.default, tuple) else self.default
        return schema


#: `(params, credential, failure_policy) -> BaseTool`. `credential` is the
#: PLAINTEXT fields mapping the vault returned, or None when the entry needs
#: none. Never an id: dereferencing happens before a factory is called, so a
#: factory cannot be handed an id it might log.
ToolFactory = Callable[[Mapping[str, Any], Mapping[str, str] | None, str], Any]


@dataclass(frozen=True, slots=True)
class ToolCatalogueEntry:
    """One catalogue row. `factory` is server-side only and never serialised."""

    id: str
    label: str
    category: str
    description: str
    docs_url: str
    factory: ToolFactory
    #: The credential kind this entry needs, or None for a keyless tool.
    credential_kind: str | None = None
    #: When the kind depends on a parameter - `web_search`'s `provider`, and
    #: nothing else today. `{"param": "provider", "map": {...}}`.
    credential_kind_by_param: dict[str, Any] | None = None
    #: True when the entry runs without a credential but does better with one.
    credential_optional: bool = False
    params: tuple[ParamSpec, ...] = ()
    owner: str = "builtin"
    #: Withheld from `GET /api/builder/tools` unless its flag is set. The entry
    #: still EXISTS, so it is priced, tested and one boolean from shipping.
    flag: str | None = None
    #: Importable module names this entry needs, keyed by the value of
    #: `packages_param` that selects them; `""` is what every configuration
    #: needs. Checked with `find_spec`, never imported - `crewai_tools` is 107
    #: classes and importing them all to draw a palette is not a trade.
    packages: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    #: The parameter whose value chooses a row of `packages`. Only `web_search`
    #: has one, and only because two of its four providers ship as separate
    #: distributions.
    packages_param: str | None = None

    def required_packages(self, params: Mapping[str, Any]) -> tuple[str, ...]:
        needed = list(self.packages.get("", ()))
        if self.packages_param is not None:
            chosen = params.get(
                self.packages_param, self.default_params().get(self.packages_param)
            )
            needed += list(self.packages.get(str(chosen), ()))
        return tuple(needed)

    def missing_packages(self, params: Mapping[str, Any]) -> tuple[str, ...]:
        return tuple(
            name
            for name in self.required_packages(params)
            if importlib.util.find_spec(name) is None
        )

    def kind_for(self, params: Mapping[str, Any]) -> str | None:
        """The credential kind this configuration needs, params considered."""

        if self.credential_kind_by_param is not None:
            param = str(self.credential_kind_by_param["param"])
            chosen = params.get(param, self.default_params().get(param))
            return self.credential_kind_by_param["map"].get(str(chosen))
        return self.credential_kind

    def default_params(self) -> dict[str, Any]:
        return {
            spec.name: (list(spec.default) if isinstance(spec.default, tuple) else spec.default)
            for spec in self.params
        }

    def param_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {spec.name: spec.json_schema() for spec in self.params},
            "additionalProperties": False,
        }

    def serialisable(self) -> dict[str, Any]:
        """The wire shape. `factory` is absent, and that absence is asserted.

        **The key is `tool_id`, not `id`, and that is a correction to plan 06's
        own Interfaces section.** Three client files already read `tool_id` -
        `NodePalette.vue`, `BuilderNode.vue` and `inspectors/ToolForm.vue`, all
        written against `types/builder.ts::BuilderToolCatalogueEntry` before this
        catalogue existed - and two of the three are outside this plan's
        surfaces. Serving the plan's spelling would have meant either editing
        files this plan may not touch or shipping a palette that renders an
        empty label for every tool. The client's shape is the contract; the
        plan's extra fields are added to it rather than replacing it.

        `params` is the LIST the client's form control reads.
        `ToolCatalogueEntry.param_schema()` still renders the JSON-Schema view
        for anything that wants one, and both come off the same `ParamSpec`
        tuple, so the two cannot describe a parameter differently.
        """

        return {
            "tool_id": self.id,
            "label": self.label,
            "category": self.category,
            "credential_kind": self.credential_kind,
            "credential_kind_by_param": self.credential_kind_by_param,
            "credential_optional": self.credential_optional,
            # Every kind an `attach` edge may ARRIVE at, read from the document
            # schema rather than written down here - `bounds.py` refuses any
            # other target with `attach-target-not-agent`, so a client offering
            # a third would be offering a drop the server refuses.
            "attaches_to": sorted(ATTACH_TARGET_KINDS),
            "params": [spec.wire() for spec in self.params],
            "description": self.description,
            "docs_url": self.docs_url,
            "owner": self.owner,
            # What this DEPLOYMENT can actually build, not what the catalogue
            # describes. `tavily-python` and `exa_py` are separate distributions
            # and neither is installed here, so an inspector that offered all
            # four providers alike would be offering two that abort at run time.
            "available": not self.missing_packages(self.default_params()),
            "requires_packages": {
                key: list(value) for key, value in sorted(self.packages.items()) if value
            },
            "packages_param": self.packages_param,
        }


class ToolBuildError(RuntimeError):
    """A tool that cannot be constructed from what the document said."""


# --------------------------------------------------------------------------
# Binding a credential to a class that reads the environment
# --------------------------------------------------------------------------
#: Serialises the environment window. Three research branches run concurrently
#: in worker threads, and `os.environ` is process-global: without this, two
#: branches using two different Serper keys could read each other's. The window
#: is one `_run` call, which is one HTTP request.
_ENV_LOCK = threading.RLock()


def _env_scoped(tool_cls: type, env_values: Mapping[str, str]) -> type:
    """A subclass of `tool_cls` whose `_run` sees `env_values` and nothing else.

    Used only for the two `crewai_tools` classes that read `os.environ` inside
    `_run` and expose no field to inject through. The values live in this
    closure's cell - not in a pydantic field, not on the instance - so no
    `model_dump`, no repr and no frame serialiser can reach them.
    """

    values = dict(env_values)

    class _Scoped(tool_cls):  # type: ignore[misc,valid-type]
        def _run(self, *args: Any, **kwargs: Any) -> Any:
            with _ENV_LOCK:
                previous = {key: os.environ.get(key) for key in values}
                os.environ.update(values)
                try:
                    return super()._run(*args, **kwargs)
                finally:
                    for key, was in previous.items():
                        if was is None:
                            os.environ.pop(key, None)
                        else:
                            os.environ[key] = was

    _Scoped.__name__ = tool_cls.__name__
    _Scoped.__qualname__ = tool_cls.__qualname__
    return _Scoped


@contextmanager
def _forced_env(values: Mapping[str, str]) -> Iterator[None]:
    """The same window as `_env_scoped`, for a class that reads at CONSTRUCTION.

    `NL2SQLTool.model_post_init` is the case: scoping `_run` would be too late,
    because the field it overrides is already set by then.
    """

    with _ENV_LOCK:
        previous = {key: os.environ.get(key) for key in values}
        os.environ.update(values)
        try:
            yield
        finally:
            for key, was in previous.items():
                if was is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = was


def _policy(failure_policy: str) -> Any:
    from crewai.tools.tool_failure import ToolFailurePolicy

    return ToolFailurePolicy(failure_policy)


def _require_packages(tool_id: str, names: Sequence[str]) -> None:
    """Refuse before constructing anything that would ASK to install itself.

    `TavilySearchTool.__init__` calls `click.confirm("... would you like to
    install it?")` when `tavily-python` is absent. In a service process there is
    nobody to answer, so `click` raises `Abort` - measured - and an author gets
    a stack trace instead of a sentence. Checking with `find_spec` costs no
    import and turns that into a refusal that names the package.
    """

    missing = [name for name in names if importlib.util.find_spec(name) is None]
    if missing:
        raise ToolBuildError(
            f"{tool_id!r} needs {', '.join(missing)}, which this deployment does "
            "not have installed"
        )


# --------------------------------------------------------------------------
# The eleven v1 builtins - plan 06 D2
# --------------------------------------------------------------------------
def _market_research(
    params: Mapping[str, Any], credential: Mapping[str, str] | None, policy: str
) -> Any:
    from brief_crew.tools.market_research import MarketResearchTool

    cls = MarketResearchTool
    if credential is not None:
        cls = _env_scoped(cls, {"FIRECRAWL_API_KEY": credential["api_key"]})
    return cls(tool_failure_policy=_policy(policy))


def _hn_sentiment(
    params: Mapping[str, Any], credential: Mapping[str, str] | None, policy: str
) -> Any:
    from brief_crew.tools.hn_sentiment import HackerNewsSentimentTool

    return HackerNewsSentimentTool(tool_failure_policy=_policy(policy))


def _github_feasibility(
    params: Mapping[str, Any], credential: Mapping[str, str] | None, policy: str
) -> Any:
    from brief_crew.tools.github_feasibility import GitHubFeasibilityTool

    cls = GitHubFeasibilityTool
    if credential is not None:
        cls = _env_scoped(cls, {"GITHUB_TOKEN": credential["token"]})
    return cls(tool_failure_policy=_policy(policy))


def _firecrawl(name: str) -> ToolFactory:
    def factory(
        params: Mapping[str, Any], credential: Mapping[str, str] | None, policy: str
    ) -> Any:
        import crewai_tools

        cls = getattr(crewai_tools, name)
        if credential is None:
            raise ToolBuildError(
                f"{name} needs a firecrawl credential and none was resolved"
            )
        return cls(api_key=credential["api_key"], tool_failure_policy=_policy(policy))

    return factory


def _web_search(
    params: Mapping[str, Any], credential: Mapping[str, str] | None, policy: str
) -> Any:
    """One tool name, four providers - plan 06 D5.

    The agent sees `web_search` whichever provider backs it, so swapping the
    provider changes no prompt. Each class names its own count field, and two of
    the four read the environment rather than accepting a key.
    """

    import crewai_tools

    provider = str(params.get("provider", "serper"))
    count = int(params.get("n_results", 5))
    if credential is None:
        raise ToolBuildError(f"web_search via {provider} needs a {provider} credential")
    _require_packages(f"web_search via {provider}", _WEB_SEARCH_PACKAGES.get(provider, ()))
    if provider == "serper":
        cls = _env_scoped(crewai_tools.SerperDevTool, {"SERPER_API_KEY": credential["api_key"]})
        return cls(n_results=count, tool_failure_policy=_policy(policy), name=WEB_SEARCH_NAME)
    if provider == "tavily":
        return crewai_tools.TavilySearchTool(
            api_key=credential["api_key"],
            max_results=count,
            tool_failure_policy=_policy(policy),
            name=WEB_SEARCH_NAME,
        )
    if provider == "exa":
        # Exa takes no count; `highlights` is what makes its rows usable as
        # evidence rather than as bare links.
        return crewai_tools.EXASearchTool(
            api_key=credential["api_key"],
            highlights=True,
            tool_failure_policy=_policy(policy),
            name=WEB_SEARCH_NAME,
        )
    if provider == "brave":
        # Brave checks the variable at CONSTRUCTION as well as reading it in
        # `_run`, so the window has to cover both or the constructor raises
        # "BRAVE_API_KEY environment variable is required" with the key in hand.
        cls = _env_scoped(crewai_tools.BraveSearchTool, {"BRAVE_API_KEY": credential["api_key"]})
        with _forced_env({"BRAVE_API_KEY": credential["api_key"]}):
            return cls(
                n_results=count, tool_failure_policy=_policy(policy), name=WEB_SEARCH_NAME
            )
    raise ToolBuildError(f"unknown web_search provider {provider!r}")


#: The one name the agent sees for `web_search`, whichever of the four classes
#: is behind it. Pinned as a constant because two prompts and four constructors
#: have to agree about it.
WEB_SEARCH_NAME = "web_search"

#: Two of the four providers ship as separate distributions, and neither is
#: installed here (measured 2026-09-04). `SerperDevTool` and `BraveSearchTool`
#: need nothing beyond `requests`, which is already a dependency.
_WEB_SEARCH_PACKAGES: dict[str, tuple[str, ...]] = {
    "serper": (),
    "tavily": ("tavily",),
    "exa": ("exa_py",),
    "brave": (),
}


def _http_request(
    params: Mapping[str, Any], credential: Mapping[str, str] | None, policy: str
) -> Any:
    import crewai_tools

    headers = (
        {credential["name"]: credential["header_value"]} if credential else None
    )
    return crewai_tools.URLReadTool(
        timeout=int(params.get("timeout", 15)),
        max_bytes=int(params.get("max_bytes", 1048576)),
        **({"headers": headers} if headers else {}),
        tool_failure_policy=_policy(policy),
    )


def _scrape_website(
    params: Mapping[str, Any], credential: Mapping[str, str] | None, policy: str
) -> Any:
    import crewai_tools

    return crewai_tools.ScrapeWebsiteTool(tool_failure_policy=_policy(policy))


def _postgres_query(
    params: Mapping[str, Any], credential: Mapping[str, str] | None, policy: str
) -> Any:
    """`NL2SQLTool` with `allow_dml` LOCKED FALSE - by three mechanisms, not one.

    `allow_dml` is not a parameter, is not in `params`, and is written as a
    literal here. A document cannot reach it by any route, which is the whole
    point: a canvas that could turn an author's read-only database question into
    a DELETE would be a canvas that ships a data-loss surface.

    **The literal alone is not enough, and this is a package fact plan 06 did
    not have.** `NL2SQLTool.model_post_init` reads
    `CREWAI_NL2SQL_ALLOW_DML=true` from the environment and *overrides* the
    constructor argument. A deployment with that variable set - or a process
    that inherited it - would silently get a writable tool through a
    constructor that says `allow_dml=False`. So the variable is forced to
    `false` across construction, and the constructed instance is then ASSERTED
    read-only. Three mechanisms because the failure is irreversible.
    """

    import crewai_tools

    if credential is None:
        raise ToolBuildError("postgres_query needs a postgres credential")
    tables = params.get("tables") or []
    with _forced_env({"CREWAI_NL2SQL_ALLOW_DML": "false"}):
        tool = crewai_tools.NL2SQLTool(
            db_uri=credential["dsn"],
            tables=list(tables),
            allow_dml=False,
            tool_failure_policy=_policy(policy),
        )
    if getattr(tool, "allow_dml", False):
        raise ToolBuildError(
            "postgres_query was constructed writable; this deployment offers "
            "read-only database access and nothing else"
        )
    return tool


def _code_interpreter(
    params: Mapping[str, Any], credential: Mapping[str, str] | None, policy: str
) -> Any:
    """E2B, BYO key, behind a flag that is OFF - PLANS.md decision 3.

    Built so that turning the flag on is one boolean rather than a feature.
    `sandbox_timeout` is E2B's own cap and is not author-settable: the resource
    caps are the sandbox provider's, which is the entire argument for using one.
    """

    import crewai_tools

    if credential is None:
        raise ToolBuildError("code_interpreter needs an e2b credential")
    return crewai_tools.E2BPythonTool(
        api_key=credential["api_key"],
        sandbox_timeout=project_config.E2B_SANDBOX_TIMEOUT_SECONDS,
        tool_failure_policy=_policy(policy),
    )


TOOL_CATALOGUE: tuple[ToolCatalogueEntry, ...] = (
    ToolCatalogueEntry(
        id="research_market_landscape",
        label="Market landscape",
        category="research",
        description=(
            "Search and scrape the web for market evidence, returning the "
            "repository's JSON envelope with a source URL per row."
        ),
        docs_url="https://docs.firecrawl.dev/api-reference/endpoint/search",
        factory=_market_research,
        credential_kind="firecrawl",
        credential_optional=project_config.BUILDER_PLATFORM_FIRECRAWL_DEFAULT,
        params=(
            ParamSpec(
                name="limit",
                type="integer",
                default=3,
                description="Full page fetches per query. Each one is a Firecrawl credit.",
                minimum=1,
                maximum=3,
            ),
        ),
    ),
    ToolCatalogueEntry(
        id="analyze_community_sentiment",
        label="Community sentiment",
        category="research",
        description=(
            "Search Hacker News stories and walk their comment trees, citing "
            "the HN item URL for every thread."
        ),
        docs_url="https://hn.algolia.com/api",
        factory=_hn_sentiment,
        params=(
            ParamSpec(
                name="story_limit",
                type="integer",
                default=5,
                description="Distinct threads to retrieve. One story is one URL.",
                minimum=1,
                maximum=5,
            ),
            ParamSpec(
                name="comments_per_story",
                type="integer",
                default=5,
                description="Comments walked per story.",
                minimum=1,
                maximum=20,
            ),
        ),
    ),
    ToolCatalogueEntry(
        id="assess_technical_feasibility",
        label="Technical feasibility",
        category="research",
        description=(
            "Search GitHub repositories and report what exists, with the shared "
            "rate limiter this deployment already runs."
        ),
        docs_url="https://docs.github.com/en/rest/search",
        factory=_github_feasibility,
        credential_kind="github",
        credential_optional=True,
        params=(
            ParamSpec(
                name="limit",
                type="integer",
                default=5,
                description="Repositories to inspect.",
                minimum=1,
                maximum=5,
            ),
        ),
    ),
    ToolCatalogueEntry(
        id="firecrawl_scrape",
        label="Scrape a page (Firecrawl)",
        category="web",
        description="Fetch one URL as clean markdown, JavaScript rendered.",
        docs_url="https://docs.crewai.com/en/tools/web-scraping/firecrawlscrapewebsitetool",
        factory=_firecrawl("FirecrawlScrapeWebsiteTool"),
        packages={"": ("firecrawl",)},
        credential_kind="firecrawl",
        params=(
            ParamSpec(
                name="only_main_content",
                type="boolean",
                default=True,
                description="Strip navigation, headers and footers.",
            ),
            ParamSpec(
                name="formats",
                type="array",
                default=("markdown",),
                description="What to return for each page.",
                items_enum=("markdown", "links"),
            ),
        ),
    ),
    ToolCatalogueEntry(
        id="firecrawl_crawl",
        label="Crawl a site (Firecrawl)",
        category="web",
        description=(
            "Follow links from one URL and return every page. Bounded, because "
            "a crawl is a bill."
        ),
        docs_url="https://docs.crewai.com/en/tools/web-scraping/firecrawlcrawlwebsitetool",
        factory=_firecrawl("FirecrawlCrawlWebsiteTool"),
        packages={"": ("firecrawl",)},
        credential_kind="firecrawl",
        params=(
            ParamSpec(
                name="limit",
                type="integer",
                default=10,
                description="Pages to fetch at most.",
                minimum=1,
                maximum=20,
            ),
            ParamSpec(
                name="max_depth",
                type="integer",
                default=1,
                description="Link hops from the starting URL.",
                minimum=1,
                maximum=2,
            ),
        ),
    ),
    ToolCatalogueEntry(
        id="firecrawl_search",
        label="Search the web (Firecrawl)",
        category="web",
        description="Semantic web search returning scraped page content.",
        docs_url="https://docs.crewai.com/en/tools/search-research/firecrawlsearchtool",
        factory=_firecrawl("FirecrawlSearchTool"),
        packages={"": ("firecrawl",)},
        credential_kind="firecrawl",
        params=(
            ParamSpec(
                name="limit",
                type="integer",
                default=5,
                description="Results to return.",
                minimum=1,
                maximum=5,
            ),
        ),
    ),
    ToolCatalogueEntry(
        id="web_search",
        label="Web search",
        category="web",
        description=(
            "Search the web through one of four providers; the agent sees a "
            "single tool called web_search whichever one is chosen."
        ),
        docs_url="https://docs.crewai.com/en/tools/search-research/serperdevtool",
        factory=_web_search,
        packages=_WEB_SEARCH_PACKAGES,
        packages_param="provider",
        credential_kind_by_param={
            "param": "provider",
            "map": {"serper": "serper", "tavily": "tavily", "exa": "exa", "brave": "brave"},
        },
        params=(
            ParamSpec(
                name="provider",
                type="string",
                default="serper",
                description="Which search back end runs the query.",
                enum=("serper", "tavily", "exa", "brave"),
            ),
            ParamSpec(
                name="n_results",
                type="integer",
                default=5,
                description="Results to return. Exa ignores this and returns highlights.",
                minimum=1,
                maximum=10,
            ),
        ),
    ),
    ToolCatalogueEntry(
        id="http_request",
        label="HTTP request",
        category="data",
        description=(
            "Read one URL. Already refuses private, loopback and link-local "
            "targets, so an agent cannot use it to reach this network."
        ),
        docs_url="https://docs.crewai.com/en/tools/web-scraping/urlreadtool",
        factory=_http_request,
        credential_kind="http_header",
        credential_optional=True,
        params=(
            ParamSpec(
                name="timeout",
                type="integer",
                default=15,
                description="Seconds before the request is abandoned.",
                minimum=1,
                maximum=project_config.CUSTOM_TOOL_MAX_TIMEOUT_SECONDS,
            ),
            ParamSpec(
                name="max_bytes",
                type="integer",
                default=1048576,
                description="Response bytes read at most.",
                minimum=1024,
                maximum=5242880,
            ),
        ),
    ),
    ToolCatalogueEntry(
        id="scrape_website",
        label="Scrape a page",
        category="web",
        description="Keyless page fetch for sites that do not need Firecrawl.",
        docs_url="https://docs.crewai.com/en/tools/web-scraping/scrapewebsitetool",
        factory=_scrape_website,
    ),
    ToolCatalogueEntry(
        id="postgres_query",
        label="Ask a Postgres database",
        category="data",
        description=(
            "Turn a question into SQL against your own database. Reads only - "
            "writes are locked off and are not a setting."
        ),
        docs_url="https://docs.crewai.com/en/tools/database-data/nl2sqltool",
        factory=_postgres_query,
        credential_kind="postgres",
        params=(
            ParamSpec(
                name="tables",
                type="array",
                default=(),
                description="Tables the agent may see. Empty means every table.",
            ),
        ),
    ),
    ToolCatalogueEntry(
        id="code_interpreter",
        label="Run Python (sandboxed)",
        category="data",
        description=(
            "Execute Python in an E2B sandbox on your own E2B key. Off by "
            "default: it runs code, and the sandbox is a third-party account."
        ),
        docs_url="https://docs.crewai.com/en/tools/automation/e2bpythontool",
        factory=_code_interpreter,
        credential_kind="e2b",
        packages={"": ("e2b_code_interpreter",)},
        flag="BUILDER_CODE_INTERPRETER_ENABLED",
    ),
)

BUILTIN_TOOL_IDS: tuple[str, ...] = tuple(entry.id for entry in TOOL_CATALOGUE)
_BY_ID: dict[str, ToolCatalogueEntry] = {entry.id: entry for entry in TOOL_CATALOGUE}


def entry_enabled(entry: ToolCatalogueEntry) -> bool:
    """Whether a flagged entry's flag is set. Unflagged entries are always on."""

    return entry.flag is None or bool(getattr(project_config, entry.flag, False))


def catalogue(*, include_disabled: bool = False) -> tuple[ToolCatalogueEntry, ...]:
    """The builtins this deployment offers, in declaration order."""

    if include_disabled:
        return TOOL_CATALOGUE
    return tuple(entry for entry in TOOL_CATALOGUE if entry_enabled(entry))


def builtin(tool_id: str) -> ToolCatalogueEntry | None:
    return _BY_ID.get(tool_id)


# --------------------------------------------------------------------------
# Parameter validation - one declaration, checked the same way twice
# --------------------------------------------------------------------------
def validate_params(entry: ToolCatalogueEntry, params: Mapping[str, Any]) -> list[str]:
    """Every reason this configuration is refused, as sentences an author reads."""

    problems: list[str] = []
    known = {spec.name: spec for spec in entry.params}
    for key in sorted(params):
        if key not in known:
            problems.append(
                f"{key!r} is not a setting of {entry.id!r}; it takes "
                + (", ".join(sorted(known)) if known else "no settings")
            )
    for name, spec in known.items():
        if name not in params:
            continue
        value = params[name]
        if spec.type == "boolean":
            if not isinstance(value, bool):
                problems.append(f"{name!r} is true or false, not {value!r}")
            continue
        if spec.type == "integer":
            if isinstance(value, bool) or not isinstance(value, int):
                problems.append(f"{name!r} is a whole number, not {value!r}")
                continue
            if spec.minimum is not None and value < spec.minimum:
                problems.append(f"{name!r} is at least {spec.minimum}; this is {value}")
            if spec.maximum is not None and value > spec.maximum:
                problems.append(f"{name!r} is at most {spec.maximum}; this is {value}")
            continue
        if spec.type == "array":
            values = value if isinstance(value, (list, tuple)) else None
            if values is None:
                problems.append(f"{name!r} is a list, not {value!r}")
                continue
            if spec.items_enum is not None:
                for item in values:
                    if item not in spec.items_enum:
                        problems.append(
                            f"{name!r} takes {', '.join(spec.items_enum)}; not {item!r}"
                        )
            continue
        if not isinstance(value, str):
            problems.append(f"{name!r} is text, not {value!r}")
            continue
        if spec.enum is not None and value not in spec.enum:
            problems.append(f"{name!r} is one of {', '.join(spec.enum)}; not {value!r}")
    return problems


# --------------------------------------------------------------------------
# The declarative custom HTTP tool - plan 06 D7
# --------------------------------------------------------------------------
_PROPERTY_TYPES: tuple[str, ...] = ("string", "integer", "number", "boolean")
_PLACEHOLDER = re.compile(r"\{([a-z][a-z0-9_]{0,39})\}")


class CustomToolError(ValueError):
    """A custom tool document that cannot become a tool. Carries the sentence."""


@dataclass(frozen=True, slots=True)
class CustomToolProperty:
    name: str
    type: str
    description: str
    required: bool = False


@dataclass(frozen=True, slots=True)
class CustomToolRequest:
    method: str
    url: str
    header_name: str | None = None
    header_template: str | None = None
    body_template: str | None = None
    timeout_seconds: int = 15
    max_response_bytes: int = 1048576


@dataclass(frozen=True, slots=True)
class CustomToolSpec:
    """Flowise's schema grid with an HTTPS call where the function used to be.

    The function is what makes Flowise's custom tool an evaluation surface.
    Replacing it with a request template keeps the shape - name, description, a
    grid of typed properties - and removes the interpreter, which is the same
    trade `BUILDER_TRANSFORM_OPS` makes for the six transform operations.
    """

    name: str
    description: str
    properties: tuple[CustomToolProperty, ...]
    request: CustomToolRequest
    id: str = ""
    credential_id: str | None = None

    def json_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                prop.name: {"type": prop.type, "description": prop.description}
                for prop in self.properties
            },
            "required": [prop.name for prop in self.properties if prop.required],
            "additionalProperties": False,
        }

    def as_entry(self) -> ToolCatalogueEntry:
        """The catalogue row a custom tool appears as, for its owner only.

        The id is the ROW id (`ut_` + 12 hex), not plan 06's `custom_http:<id>`:
        `ToolConfig.tool_id` is a `NodeId` and `NodeId` has no colon in it, so
        the plan's spelling is not expressible in the document schema 03 owns.
        Recorded as a departure rather than worked around, because the fix is a
        C1 change and C1 is not this plan's to make.
        """

        return ToolCatalogueEntry(
            id=self.id,
            label=self.name,
            category="custom",
            description=self.description,
            docs_url="",
            factory=_custom_factory(self),
            credential_kind="http_header" if self.request.header_name else None,
            credential_optional=False,
            params=(),
            owner="user",
        )


def parse_custom_tool(payload: Mapping[str, Any], *, tool_id: str = "") -> CustomToolSpec:
    """An author's JSON into a spec, or `CustomToolError` with one sentence.

    Every refusal here is a refusal the author can act on, which is why they are
    sentences rather than pydantic locations: this is a form with a grid in it,
    and "properties.3.type: Input should be..." is not a repair instruction.
    """

    name = str(payload.get("name", "")).strip()
    if not re.fullmatch(project_config.CUSTOM_TOOL_NAME_PATTERN, name):
        raise CustomToolError(
            f"a tool name is lowercase letters, digits and underscores, up to 40 "
            f"characters, starting with a letter; {name!r} is not"
        )
    description = str(payload.get("description", "")).strip()
    if not description:
        raise CustomToolError(
            "a tool needs a description: it is what the agent reads to decide "
            "whether to call it, and an agent will not call a tool it cannot judge"
        )
    if len(description) > project_config.MAX_CUSTOM_TOOL_DESCRIPTION_CHARS:
        raise CustomToolError(
            f"a description is at most "
            f"{project_config.MAX_CUSTOM_TOOL_DESCRIPTION_CHARS} characters; "
            f"this one is {len(description)}"
        )

    raw_properties = payload.get("properties") or []
    if not isinstance(raw_properties, (list, tuple)):
        raise CustomToolError("properties is a list of typed arguments")
    if len(raw_properties) > project_config.MAX_CUSTOM_TOOL_PROPERTIES:
        raise CustomToolError(
            f"a tool takes at most {project_config.MAX_CUSTOM_TOOL_PROPERTIES} "
            f"arguments; this one declares {len(raw_properties)}"
        )
    properties: list[CustomToolProperty] = []
    seen: set[str] = set()
    for row in raw_properties:
        if not isinstance(row, Mapping):
            raise CustomToolError("every property is an object with a name and a type")
        prop_name = str(row.get("name", "")).strip()
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,39}", prop_name):
            raise CustomToolError(
                f"a property name is lowercase letters, digits and underscores; "
                f"{prop_name!r} is not"
            )
        if prop_name in seen:
            raise CustomToolError(f"the property {prop_name!r} is declared twice")
        seen.add(prop_name)
        prop_type = str(row.get("type", "string"))
        if prop_type not in _PROPERTY_TYPES:
            raise CustomToolError(
                f"{prop_name!r} is typed {prop_type!r}; the types are "
                f"{', '.join(_PROPERTY_TYPES)}"
            )
        properties.append(
            CustomToolProperty(
                name=prop_name,
                type=prop_type,
                description=str(row.get("description", "")).strip()[:200],
                required=bool(row.get("required", False)),
            )
        )

    raw_request = payload.get("request")
    if not isinstance(raw_request, Mapping):
        raise CustomToolError("request is an object naming a method and a url")
    method = str(raw_request.get("method", "GET")).upper()
    if method not in project_config.CUSTOM_TOOL_METHODS:
        raise CustomToolError(
            f"a custom tool may only {' or '.join(project_config.CUSTOM_TOOL_METHODS)}; "
            f"{method!r} is not one of those, because a tool an agent chose to "
            "call should not be able to destroy anything"
        )
    url = str(raw_request.get("url", "")).strip()
    if not url.lower().startswith("https://"):
        raise CustomToolError(
            f"a custom tool calls https:// only; {url!r} is not encrypted, and a "
            "credential in a header would travel in clear"
        )
    for placeholder in _PLACEHOLDER.findall(url):
        if placeholder not in seen and placeholder != "credential":
            raise CustomToolError(
                f"the url names {{{placeholder}}} and no property declares it"
            )
    timeout = int(raw_request.get("timeout_seconds", 15) or 15)
    if not 1 <= timeout <= project_config.CUSTOM_TOOL_MAX_TIMEOUT_SECONDS:
        raise CustomToolError(
            f"timeout_seconds is 1 to "
            f"{project_config.CUSTOM_TOOL_MAX_TIMEOUT_SECONDS}; this is {timeout}"
        )
    max_bytes = int(
        raw_request.get("max_response_bytes", project_config.CUSTOM_TOOL_MAX_RESPONSE_BYTES)
        or project_config.CUSTOM_TOOL_MAX_RESPONSE_BYTES
    )
    if not 1 <= max_bytes <= project_config.CUSTOM_TOOL_MAX_RESPONSE_BYTES:
        raise CustomToolError(
            f"max_response_bytes is 1 to "
            f"{project_config.CUSTOM_TOOL_MAX_RESPONSE_BYTES}; this is {max_bytes}"
        )
    header_name = raw_request.get("header_name") or None
    header_template = raw_request.get("header_template") or None
    if bool(header_name) != bool(header_template):
        raise CustomToolError(
            "header_name and header_template travel together: a header with no "
            "value, or a value with no header, is a request nothing can send"
        )
    credential_id = payload.get("credential_id") or None
    if credential_id is not None and not re.fullmatch(
        project_config.CREDENTIAL_ID_PATTERN, str(credential_id)
    ):
        raise CustomToolError(f"{credential_id!r} is not a credential id")

    return CustomToolSpec(
        id=tool_id,
        name=name,
        description=description,
        properties=tuple(properties),
        request=CustomToolRequest(
            method=method,
            url=url,
            header_name=str(header_name) if header_name else None,
            header_template=str(header_template) if header_template else None,
            body_template=(
                str(raw_request["body_template"])
                if raw_request.get("body_template")
                else None
            ),
            timeout_seconds=timeout,
            max_response_bytes=max_bytes,
        ),
        credential_id=str(credential_id) if credential_id else None,
    )


def custom_tool_from_row(row: Mapping[str, Any]) -> CustomToolSpec:
    """A stored row back into a spec, re-validated on the way OUT.

    A row is not trusted because it was validated on the way in: the schema
    moves, and a row that no longer parses must fail where its id is known
    rather than deep inside a run. Same rule `builder/store.py` already applies
    to a stored document.
    """

    schema = row.get("input_schema") or {}
    required = set(schema.get("required") or ())
    properties = tuple(
        CustomToolProperty(
            name=str(name),
            type=str(spec.get("type", "string")),
            description=str(spec.get("description", "")),
            required=str(name) in required,
        )
        for name, spec in (schema.get("properties") or {}).items()
    )
    return parse_custom_tool(
        {
            "name": row.get("name"),
            "description": row.get("description"),
            "properties": [
                {
                    "name": prop.name,
                    "type": prop.type,
                    "description": prop.description,
                    "required": prop.required,
                }
                for prop in properties
            ],
            "request": row.get("request") or {},
            "credential_id": row.get("credential_id"),
        },
        tool_id=str(row.get("id", "")),
    )


# --------------------------------------------------------------------------
# The SSRF rule, shared by the custom tool and by 07's remote transports
# --------------------------------------------------------------------------
#: `(host) -> [address, ...]`. Injectable so a test never touches DNS - the
#: same seam `service/credentials.py` opened for the postgres probe.
HostResolver = Callable[[str], list[str]]


def _default_resolver(host: str) -> list[str]:
    return sorted({info[4][0] for info in socket.getaddrinfo(host, None)})


def refuse_private_target(
    url: str,
    *,
    resolve: HostResolver | None = None,
    allow_insecure_local: bool = False,
) -> str | None:
    """The reason this URL may not be dialled, or None.

    The rule `URLReadTool` already applies, restated here because a custom tool
    and an MCP server both need it and neither goes through that class: resolve
    the name, and refuse every private, loopback, link-local, reserved or
    multicast address it answers with. Resolution happens BEFORE the request, so
    a DNS name pointing at 169.254.169.254 is refused by address rather than by
    spelling.
    """

    parsed = urllib.parse.urlsplit(url)
    scheme = parsed.scheme.lower()
    host = parsed.hostname or ""
    if not host:
        return f"{url!r} names no host"
    local = host in {"127.0.0.1", "localhost", "::1"}
    if scheme != "https" and not (allow_insecure_local and local and scheme == "http"):
        return f"{url!r} is not https, and only https targets are dialled"
    if local and allow_insecure_local:
        return None
    resolver = resolve or _default_resolver
    try:
        addresses = resolver(host)
    except OSError as exc:  # pragma: no cover - depends on the resolver
        return f"{host!r} does not resolve ({exc})"
    if not addresses:
        return f"{host!r} resolves to nothing"
    for address in addresses:
        try:
            parsed_address = ipaddress.ip_address(address)
        except ValueError:
            return f"{host!r} resolved to {address!r}, which is not an address"
        if (
            parsed_address.is_private
            or parsed_address.is_loopback
            or parsed_address.is_link_local
            or parsed_address.is_reserved
            or parsed_address.is_multicast
            or parsed_address.is_unspecified
        ):
            return (
                f"{host!r} resolves to {address}, which is on this network; a tool "
                "reaches the public internet and nothing else"
            )
    return None


def _envelope(
    *,
    tool: str,
    query: str,
    status: str,
    results: Sequence[Any] = (),
    notes: str = "",
) -> str:
    """The repository's own tool envelope, so a custom tool looks like a builtin.

    The guardrails read `status`, `result_count` and `results`; a custom tool
    whose output had a different shape would be evidence the URL-closure checks
    could not see, which is the same failure as an invented citation.
    """

    return json.dumps(
        {
            "status": status,
            "tool": tool,
            "query": query,
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "result_count": len(results),
            "results": list(results),
            "notes": notes,
        }
    )


def _custom_factory(spec: CustomToolSpec) -> ToolFactory:
    def factory(
        params: Mapping[str, Any], credential: Mapping[str, str] | None, policy: str
    ) -> Any:
        return build_custom_tool(spec, credential=credential, failure_policy=policy)

    return factory


def build_custom_tool(
    spec: CustomToolSpec,
    *,
    credential: Mapping[str, str] | None = None,
    failure_policy: str = project_config.BUILDER_DEFAULT_TOOL_FAILURE_POLICY,
    resolve: HostResolver | None = None,
    transport: Callable[..., Any] | None = None,
) -> Any:
    """A `BaseTool` whose `args_schema` is generated from the property grid.

    `transport` is the seam a test replaces; the default is `httpx`, which
    CrewAI already depends on, so this adds no dependency.
    """

    from crewai.tools import BaseTool
    from pydantic import Field as PydanticField
    from pydantic import create_model

    fields: dict[str, Any] = {}
    python_type = {"string": str, "integer": int, "number": float, "boolean": bool}
    for prop in spec.properties:
        annotation = python_type[prop.type]
        if prop.required:
            fields[prop.name] = (annotation, PydanticField(..., description=prop.description))
        else:
            fields[prop.name] = (
                annotation | None,
                PydanticField(default=None, description=prop.description),
            )
    # NOT named `args_schema`: a class body assigning `args_schema = args_schema`
    # resolves the right-hand side in the CLASS namespace, where the annotation
    # has already bound the name, and raises NameError. Measured, not reasoned.
    generated_schema = create_model(f"{spec.name}_args", **fields)  # type: ignore[call-overload]

    secret = dict(credential or {})
    request = spec.request

    def render(template: str, values: Mapping[str, Any], *, quote: bool) -> str:
        def replace(match: re.Match[str]) -> str:
            key = match.group(1)
            if key == "credential":
                return secret.get("header_value", "")
            raw = values.get(key)
            text = "" if raw is None else str(raw)
            return urllib.parse.quote(text, safe="") if quote else text

        return _PLACEHOLDER.sub(replace, template)

    class _CustomHttpTool(BaseTool):
        name: str = spec.name
        description: str = spec.description
        args_schema: type = generated_schema

        def _run(self, **kwargs: Any) -> str:
            url = render(request.url, kwargs, quote=True)
            refusal = refuse_private_target(url, resolve=resolve)
            if refusal is not None:
                return _envelope(
                    tool=spec.name, query=url, status="failed", notes=refusal
                )
            headers: dict[str, str] = {}
            if request.header_name and request.header_template:
                headers[request.header_name] = render(
                    request.header_template, kwargs, quote=False
                )
            body = (
                render(request.body_template, kwargs, quote=False)
                if request.body_template
                else None
            )
            send = transport or _default_transport
            try:
                status_code, text = send(
                    request.method,
                    url,
                    headers,
                    body,
                    request.timeout_seconds,
                    request.max_response_bytes,
                )
            except _ResponseTooLarge as exc:
                return _envelope(
                    tool=spec.name, query=url, status="failed", notes=str(exc)
                )
            except Exception as exc:  # noqa: BLE001 - a tool reports, never raises
                return _envelope(
                    tool=spec.name,
                    query=url,
                    status="failed",
                    notes=f"{type(exc).__name__}: {exc}",
                )
            if status_code >= 400:
                return _envelope(
                    tool=spec.name,
                    query=url,
                    status="rate_limited" if status_code == 429 else "failed",
                    notes=f"the server answered {status_code}",
                )
            return _envelope(
                tool=spec.name,
                query=url,
                status="ok",
                results=[{"url": url, "status_code": status_code, "body": text}],
            )

    return _CustomHttpTool(tool_failure_policy=_policy(failure_policy))


class _ResponseTooLarge(RuntimeError):
    """The body passed `max_response_bytes` and was abandoned mid-stream."""


def _default_transport(
    method: str,
    url: str,
    headers: Mapping[str, str],
    body: str | None,
    timeout: int,
    max_bytes: int,
) -> tuple[int, str]:
    """One HTTPS call, no redirects, capped mid-stream.

    `follow_redirects=False` is load-bearing: a 302 to `http://169.254.169.254`
    would walk straight past the SSRF check, which ran against the URL the
    author wrote. The cap is applied while iterating rather than on
    `response.text`, so a 2 GiB body is abandoned rather than read.
    """

    import httpx

    with httpx.Client(timeout=timeout, follow_redirects=False) as client:
        with client.stream(
            method, url, headers=dict(headers), content=body
        ) as response:
            chunks: list[bytes] = []
            size = 0
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > max_bytes:
                    raise _ResponseTooLarge(
                        f"the response passed {max_bytes} bytes and was abandoned"
                    )
                chunks.append(chunk)
            return response.status_code, b"".join(chunks).decode("utf-8", "replace")


# --------------------------------------------------------------------------
# Validation over a document - the `credential_problems` shape
# --------------------------------------------------------------------------
def tool_nodes(document: BuilderDocument) -> list[Any]:
    return [node for node in document.nodes if node.kind == "tool"]


def tool_problems(
    document: BuilderDocument,
    *,
    custom_tools: Callable[[str], bool] | None = None,
) -> list[Problem]:
    """Every `tool` node this deployment could not build, and why.

    `custom_tools` is the caller's own rows as a predicate over ids - the same
    injected-predicate shape `compiler.credential_problems` uses, and for the
    same reason: this module stays importable without the service package, and a
    test can prove the check with a lambda.

    `None` means there is nobody to ask. A builtin id is still checked - it does
    not depend on an identity - and a `ut_` id is left alone, because reporting
    somebody's own tool as unknown to an anonymous validate would be worse than
    reporting nothing.
    """

    problems: list[Problem] = []
    for node in tool_nodes(document):
        config = node.config
        if not isinstance(config, ToolConfig):  # pragma: no cover - schema guarantees it
            continue
        entry = builtin(config.tool_id)
        if entry is None:
            if config.tool_id.startswith("ut_"):
                if custom_tools is None or custom_tools(config.tool_id):
                    continue
            problems.append(
                Problem(
                    code=TOOL_UNKNOWN,
                    severity="error",
                    message=(
                        f"{node.id} names the tool {config.tool_id!r}, which is not in "
                        f"this deployment's catalogue and is not one of yours; the "
                        f"builtins are {', '.join(e.id for e in catalogue())}"
                    ),
                    node_id=node.id,
                )
            )
            continue
        if not entry_enabled(entry):
            problems.append(
                Problem(
                    code=TOOL_UNKNOWN,
                    severity="error",
                    message=(
                        f"{node.id} names {entry.id!r}, which this deployment has "
                        f"turned off; it is behind {entry.flag} and that flag is not set"
                    ),
                    node_id=node.id,
                )
            )
            continue
        for sentence in validate_params(entry, config.params):
            problems.append(
                Problem(
                    code=TOOL_PARAM_INVALID,
                    severity="error",
                    message=f"{node.id}: {sentence}",
                    node_id=node.id,
                )
            )
        kind = entry.kind_for(config.params)
        if kind is not None and not entry.credential_optional and not config.credential_id:
            problems.append(
                Problem(
                    code=TOOL_CREDENTIAL_REQUIRED,
                    severity="error",
                    message=(
                        f"{node.id} runs {entry.label!r}, which needs a {kind} key, and "
                        f"names none; add a {kind} credential and pick it here"
                    ),
                    node_id=node.id,
                )
            )
    return problems


def resolved_tool(
    tool_id: str,
    *,
    params: Mapping[str, Any],
    credential: Mapping[str, str] | None,
    failure_policy: str = project_config.BUILDER_DEFAULT_TOOL_FAILURE_POLICY,
    custom: CustomToolSpec | None = None,
) -> Any:
    """Build one tool from what a document said and what the vault answered."""

    entry = builtin(tool_id)
    if entry is None:
        if custom is None:
            raise ToolBuildError(
                f"unknown tool {tool_id!r}; this deployment offers "
                f"{', '.join(e.id for e in catalogue())}"
            )
        entry = custom.as_entry()
    elif not entry_enabled(entry):
        raise ToolBuildError(
            f"{tool_id!r} is behind {entry.flag}, which this deployment does not set"
        )
    settings = {**entry.default_params(), **dict(params)}
    return entry.factory(settings, credential, failure_policy)


__all__ = [
    "BUILTIN_TOOL_IDS",
    "CustomToolError",
    "CustomToolProperty",
    "CustomToolRequest",
    "CustomToolSpec",
    "ParamSpec",
    "TOOL_CATALOGUE",
    "TOOL_CREDENTIAL_REQUIRED",
    "TOOL_PARAM_INVALID",
    "TOOL_UNKNOWN",
    "ToolBuildError",
    "ToolCatalogueEntry",
    "build_custom_tool",
    "builtin",
    "catalogue",
    "custom_tool_from_row",
    "entry_enabled",
    "parse_custom_tool",
    "refuse_private_target",
    "resolved_tool",
    "tool_problems",
    "validate_params",
]
