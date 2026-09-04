"""MCP servers: the record, the discovery, and the sanitiser - plan 07.

MCP turns a finite tool catalogue into an open surface, and CrewAI 1.15.18
already carries the whole client: `Agent.mcps` takes `MCPServerStdio`,
`MCPServerHTTP` or `MCPServerSSE`, and `MCPToolResolver` connects, discovers,
reads each tool's JSON schema and cleans up. So the work here is a record, a
discovery route, a node - and the security posture Flowise arrived at only
after shipping without one.

**One package fact shapes everything.** A bare `str` in `Agent.mcps` is a
CrewAI AMP *marketplace reference* unless it starts with `https://`
(`crewai/mcp/tool_resolver.py`, `_parse_amp_ref`). User input is therefore
never passed as a string: `server_config` always returns one of the three
config objects, and there is no branch in this module that hands a raw string
to CrewAI.

**The second is that a tool description is a prompt.** A discovered
description lands verbatim in the agent's tool list, so it is untrusted text
authored by a third party and reaching a model - the same category as a report
body, which is why `frontend/src/utils/markdown.ts` escapes first. Here the
rules are Flowise's `MCP/core.ts`: normalise the name, strip controls and
zero-width characters from the description, truncate, and test it against
thirteen injection patterns. A match marks the tool `suspicious` and names the
pattern. **It does not hide the tool** (PLANS.md decision 8, provisional): `act
as` is ordinary English, and a picker that quietly drops rows is exactly the
quietly-divergent double this repository keeps warning about.

**The third is that stdio is a process.** An arbitrary stdio command would let
an author's record name a program to run on this server, which is the one thing
`BUILDER_ACTION_REFS`' closed set exists to prevent. Production is remote-only:
`MCP_STDIO_ENABLED` is off, and even lifted, the command must be on
`MCP_ALLOWED_COMMANDS`, which is empty by default (PLANS.md decision 7,
provisional).
"""

from __future__ import annotations

import re
import unicodedata
import urllib.parse
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from brief_crew import config as project_config
from brief_crew.builder.bounds import Problem
from brief_crew.builder.document import BuilderDocument, McpConfig
from brief_crew.builder.tools import HostResolver, refuse_private_target

# --------------------------------------------------------------------------
# Problem codes - declared at module level in the shape the client's grep finds
# --------------------------------------------------------------------------
#: A `server_id` that is not one of this caller's rows. One code for absent and
#: foreign, the `credential-missing` rule again.
MCP_SERVER_UNAVAILABLE = "mcp-server-unavailable"
#: A checked tool name the server's last discovery does not carry. This is the
#: expected outcome of a server RENAMING a tool, which is why it is a validate
#: problem and not an exception: `tool_filter` simply fails to match and the
#: agent runs without it.
MCP_TOOL_UNKNOWN = "mcp-tool-unknown"
#: An `mcp` node that names a server and checks none of its tools. An empty
#: selection is an incomplete graph rather than an invalid document, so
#: `document.py` allows it and this reports it.
MCP_NO_TOOLS_SELECTED = "mcp-no-tools-selected"
#: A stored server whose transport this deployment no longer permits - the shape
#: a document takes after `MCP_STDIO_ENABLED` is turned back off, which is the
#: whole reason the check runs at validate and not only at create.
MCP_TRANSPORT_DISALLOWED = "mcp-transport-disallowed"
#: A checked tool whose description matched an injection pattern. A WARNING, not
#: an error: the author is told and decides.
MCP_TOOL_DESCRIPTION_SUSPICIOUS = "mcp-tool-description-suspicious"


# --------------------------------------------------------------------------
# Sanitising what a server says about itself - D3
# --------------------------------------------------------------------------
_NAME_ILLEGAL = re.compile(r"[^a-zA-Z0-9_-]")
#: The zero-width and bidirectional-override characters D3 names, plus the
#: word joiner and the BOM. They are invisible in a panel and meaningful to a
#: tokeniser, which is the whole trick: a description that reads as harmless
#: and tokenises as an instruction.
_INVISIBLE = re.compile(
    "[​-‏‪-‮⁠-⁤⁦-⁩﻿]"
)
_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (source, re.compile(source, re.IGNORECASE))
    for source in project_config.MCP_INJECTION_PATTERNS
)


@dataclass(frozen=True, slots=True)
class DiscoveredTool:
    """One tool a server offered, after sanitising. The stored form."""

    name: str
    description: str
    input_schema: dict[str, Any] = field(default_factory=dict)
    suspicious: bool = False
    matched_pattern: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
            "suspicious": self.suspicious,
            "matched_pattern": self.matched_pattern,
        }

    @classmethod
    def of(cls, row: Mapping[str, Any]) -> "DiscoveredTool":
        return cls(
            name=str(row.get("name", "")),
            description=str(row.get("description", "")),
            input_schema=dict(row.get("input_schema") or {}),
            suspicious=bool(row.get("suspicious", False)),
            matched_pattern=(
                str(row["matched_pattern"]) if row.get("matched_pattern") else None
            ),
        )


def sanitise_name(name: str) -> str:
    """`[^a-zA-Z0-9_-] -> _`, truncated. The name a `tool_filter` matches on.

    The sanitised form is what is stored, what the card shows and what the run
    filters by - all three, deliberately. A server that renames a tool between
    discovery and run therefore fails to match rather than silently binding
    something the author never checked.
    """

    return _NAME_ILLEGAL.sub("_", str(name))[: project_config.MCP_TOOL_NAME_MAX_CHARS]


def sanitise_description(description: str) -> str:
    """Controls and zero-width characters out, then truncate.

    C0 controls are stripped rather than escaped, and tab/newline with them: a
    tool description is one line in a tool list, and a newline in it is a way to
    forge the end of that list.
    """

    # Zero-width characters are DELETED and control characters become a SPACE,
    # and the asymmetry is deliberate. A zero-width joiner sits between two
    # halves of one word and deleting it restores the word; a newline separates
    # two words and deleting it would glue them into a third that appears in no
    # source - which is a sanitiser inventing text.
    text = _INVISIBLE.sub("", str(description))
    text = "".join(
        " " if unicodedata.category(character) == "Cc" else character
        for character in text
    )
    text = re.sub(r"\s+", " ", text).strip()
    return text[: project_config.MCP_TOOL_DESCRIPTION_MAX_CHARS]


def matched_injection_pattern(text: str) -> str | None:
    """The first of the thirteen this text matches, or None."""

    for source, pattern in _PATTERNS:
        if pattern.search(text):
            return source
    return None


def sanitise_tool(
    *, name: str, description: str, input_schema: Mapping[str, Any] | None = None
) -> DiscoveredTool:
    clean_name = sanitise_name(name)
    clean_description = sanitise_description(description)
    matched = matched_injection_pattern(clean_description)
    return DiscoveredTool(
        name=clean_name,
        description=clean_description,
        input_schema=dict(input_schema or {}),
        suspicious=matched is not None,
        matched_pattern=matched,
    )


# --------------------------------------------------------------------------
# The record, and what a deployment will dial
# --------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class McpServerRecord:
    """One row of `mcp_servers`, as this module reasons about it.

    The row holds the address and REFERENCES to credentials, never a secret.
    `header_credential_id` names an `mcp_header` credential, whose two fields
    are the header's `name` and `value` - so there is no separate `header_name`
    column and none is needed. `env_credential_id` is the same pair used as an
    environment key and value for a stdio server.
    """

    id: str
    user_id: str
    label: str
    transport: str
    url: str | None = None
    command: str | None = None
    args: tuple[str, ...] = ()
    header_credential_id: str | None = None
    env_credential_id: str | None = None
    status: str = "pending"
    discovered_tools: tuple[DiscoveredTool, ...] = ()
    discovered_at: datetime | None = None
    last_error: str | None = None

    def tool(self, name: str) -> DiscoveredTool | None:
        for candidate in self.discovered_tools:
            if candidate.name == name:
                return candidate
        return None

    def stale(self, *, now: datetime | None = None) -> bool:
        if self.discovered_at is None:
            return True
        moment = now or datetime.now(timezone.utc)
        age = moment - self.discovered_at
        return age > timedelta(seconds=project_config.MCP_DISCOVERY_STALE_SECONDS)


#: Anything a shell would treat as more than one word. `args` are passed to a
#: process, not to a shell, but an author who needs a pipe in an argument is an
#: author writing a shell command, and that is the surface this refuses.
_SHELL_METACHARACTERS = set(";|&$`><\n\r\\\"'*?()[]{}!#~")


def transport_refusal(
    *,
    transport: str,
    url: str | None = None,
    command: str | None = None,
    args: Sequence[str] = (),
    env_keys: Sequence[str] = (),
    resolve: HostResolver | None = None,
) -> str | None:
    """Why this deployment will not dial this server, or None - D4.

    Run at create AND at validate. Once is not enough: the stdio flag can be
    turned off after a row exists, and a stored row whose transport is no longer
    permitted has to say so on the canvas rather than at the first run.
    """

    if transport not in project_config.MCP_TRANSPORTS:
        return (
            f"{transport!r} is not a transport; this service speaks "
            f"{', '.join(project_config.MCP_TRANSPORTS)}"
        )
    if transport in {"http", "sse"}:
        if not url:
            return f"a {transport} server needs a url"
        return refuse_private_target(
            url,
            resolve=resolve,
            allow_insecure_local=project_config.MCP_ALLOW_INSECURE_LOCAL,
        )
    if not project_config.MCP_STDIO_ENABLED:
        return (
            "this deployment connects to remote MCP servers only; a stdio server "
            "would be a process started on the server by a document, and that is "
            "off by default"
        )
    if not command:
        return "a stdio server needs a command"
    if command not in project_config.MCP_ALLOWED_COMMANDS:
        allowed = ", ".join(project_config.MCP_ALLOWED_COMMANDS) or "nothing"
        return (
            f"{command!r} is not on this deployment's MCP command allow-list, "
            f"which permits {allowed}"
        )
    for argument in args:
        if set(str(argument)) & _SHELL_METACHARACTERS:
            return f"{argument!r} contains shell metacharacters and will not be passed"
    for key in env_keys:
        if key not in project_config.MCP_ALLOWED_ENV_VARS:
            allowed = ", ".join(project_config.MCP_ALLOWED_ENV_VARS) or "nothing"
            return (
                f"{key!r} is not on this deployment's MCP environment allow-list, "
                f"which permits {allowed}"
            )
    return None


def mask_url(url: str | None) -> str | None:
    """Origin plus a masked path, the way Flowise lists a custom server.

    A path can carry a token - plenty of hosted MCP servers put one there - so a
    list that showed the whole URL would publish a credential to anyone who
    could see the panel.
    """

    if not url:
        return None
    parsed = urllib.parse.urlsplit(url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    if not parsed.path or parsed.path == "/":
        return origin
    return f"{origin}/************"


def server_config(
    record: McpServerRecord,
    *,
    tool_names: Sequence[str] = (),
    header: Mapping[str, str] | None = None,
    env: Mapping[str, str] | None = None,
) -> Any:
    """The CrewAI config object for this record - never a string.

    `tool_filter` is a static filter over the SANITISED names, which is what
    makes the checked subset the thing that actually reaches the agent.
    `cache_tools_list=True` so the agent's own discovery is served from CrewAI's
    cache rather than costing a second round trip per run.
    """

    from crewai.mcp.config import MCPServerHTTP, MCPServerSSE, MCPServerStdio
    from crewai.mcp.filters import create_static_tool_filter

    tool_filter = (
        create_static_tool_filter(allowed_tool_names=list(tool_names))
        if tool_names
        else None
    )
    headers = dict(header) if header else None
    if record.transport == "http":
        return MCPServerHTTP(
            url=str(record.url),
            headers=headers,
            streamable=True,
            tool_filter=tool_filter,
            cache_tools_list=True,
        )
    if record.transport == "sse":
        return MCPServerSSE(
            url=str(record.url),
            headers=headers,
            tool_filter=tool_filter,
            cache_tools_list=True,
        )
    if record.transport == "stdio":
        refusal = transport_refusal(
            transport="stdio",
            command=record.command,
            args=record.args,
            env_keys=tuple(env or ()),
        )
        if refusal is not None:
            raise McpUnavailable(refusal)
        return MCPServerStdio(
            command=str(record.command),
            args=list(record.args),
            env=dict(env) if env else None,
            tool_filter=tool_filter,
            cache_tools_list=True,
        )
    raise McpUnavailable(f"{record.transport!r} is not a transport this service speaks")


#: The C6 `error_class` on the `node_error` frame a failed CONNECTION produces
#: (07 D7, criterion 8). Spelled with underscores rather than hyphens, exactly
#: as `skills.SKILL_LOAD_ERROR_CLASS` is and for the same reason: three greps
#: sweep every module-level `NAME = "kebab-case"` under `brief_crew/builder/`
#: into the canvas problem-code union, and this is a FRAME discriminator rather
#: than a problem an author can repair on a node.
MCP_CONNECTION_ERROR_CLASS = "mcp_connection_failed"


class McpUnavailable(RuntimeError):
    """A server this run cannot reach, with the sentence the author gets."""


# --------------------------------------------------------------------------
# Discovery - D2
# --------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class DiscoveryResult:
    status: str
    tools: tuple[DiscoveredTool, ...] = ()
    error: str | None = None
    discovered_at: datetime | None = None


#: `(config) -> [BaseTool, ...]` plus a cleanup. Injectable so the whole of
#: discovery is testable without a server: the default builds a real
#: `MCPToolResolver`, and a test hands in a fake that answers with two tools.
Resolver = Callable[[Any], Iterable[Any]]


def _default_resolver(config: Any) -> Iterable[Any]:
    """The real CrewAI resolver, for discovery against a real server.

    **`MCPToolResolver` takes `agent` and `logger` POSITIONALLY, and this
    function called it with neither until 2026-09-04.** Every test injected a
    fake resolver - which is the seam's whole purpose - so nothing ever
    constructed the real one, and discovery against any real server answered
    `status: error` with `MCPToolResolver.__init__() missing 2 required
    positional arguments` in the sentence where an author expected to read why
    their server would not connect. Found by plan 07 criterion 1's live
    loopback server, and by nothing else that could have existed.

    `agent=None` is correct rather than a stand-in: the resolver reads
    `self._agent` in exactly one place, building a `ToolFilterContext` for a
    CALLABLE `tool_filter`, and discovery passes no filter at all - the filter
    belongs to the run, where `server_config` builds it from the author's
    checked names. A `Logger` is real, and `verbose=False`, because its only
    caller here logs a warning about a server that offered no tools and this
    module reports that as a result rather than as console output.
    """

    from crewai.mcp.tool_resolver import MCPToolResolver
    from crewai.utilities.logger import Logger

    resolver = MCPToolResolver(agent=None, logger=Logger(verbose=False))
    try:
        return list(resolver.resolve([config]))
    finally:
        # `cleanup()` in a `finally`, always: a client that outlives the request
        # is a socket this process forgot it opened.
        resolver.cleanup()


def discover(
    record: McpServerRecord,
    *,
    header: Mapping[str, str] | None = None,
    env: Mapping[str, str] | None = None,
    resolver: Resolver | None = None,
    resolve: HostResolver | None = None,
    now: Callable[[], datetime] | None = None,
) -> DiscoveryResult:
    """Connect, read every tool's name, description and schema, sanitise, stop.

    A failure is a RESULT, not an exception: the route answers 200 with
    `status: error` and one sentence, because the author needs the sentence in
    the panel rather than a stack trace in a toast. The caller runs this in a
    sync route so FastAPI's threadpool absorbs the block, the way `current_user`
    already absorbs a JWKS fetch.
    """

    clock = now or (lambda: datetime.now(timezone.utc))
    # `resolve` is the DNS seam, injected for the same reason `resolver` is: a
    # test asserting the transport policy must not depend on a name existing.
    refusal = transport_refusal(
        transport=record.transport,
        url=record.url,
        command=record.command,
        args=record.args,
        env_keys=tuple(env or ()),
        resolve=resolve,
    )
    if refusal is not None:
        return DiscoveryResult(status="error", error=refusal, discovered_at=clock())
    try:
        config = server_config(record, header=header, env=env)
        raw = list((resolver or _default_resolver)(config))
    except Exception as exc:  # noqa: BLE001 - every failure is one sentence
        return DiscoveryResult(
            status="error",
            error=f"could not connect: {_one_sentence(exc)}",
            discovered_at=clock(),
        )
    tools: list[DiscoveredTool] = []
    for tool in raw[: project_config.MCP_MAX_TOOLS_PER_SERVER]:
        tools.append(
            sanitise_tool(
                name=getattr(tool, "name", ""),
                description=getattr(tool, "description", "") or "",
                input_schema=_schema_of(tool),
            )
        )
    note = None
    if len(raw) > project_config.MCP_MAX_TOOLS_PER_SERVER:
        note = (
            f"this server offers {len(raw)} tools and the first "
            f"{project_config.MCP_MAX_TOOLS_PER_SERVER} were kept"
        )
    return DiscoveryResult(
        status="authorized", tools=tuple(tools), error=note, discovered_at=clock()
    )


def _schema_of(tool: Any) -> dict[str, Any]:
    schema = getattr(tool, "args_schema", None)
    if schema is None:
        return {}
    try:
        return dict(schema.model_json_schema())
    except Exception:  # noqa: BLE001 - a malformed schema degrades, never raises
        return {}


def _one_sentence(exc: BaseException) -> str:
    text = str(exc).strip().splitlines()
    first = text[0] if text else type(exc).__name__
    return first[:200]


# --------------------------------------------------------------------------
# Validation over a document - the `credential_problems` shape
# --------------------------------------------------------------------------
#: `(server_id) -> McpServerRecord | None`, scoped to the caller. `None` from
#: the LOOKUP means absent or foreign; `None` for the whole callable means there
#: is nobody to ask, and the check is skipped rather than reported as passed.
ServerLookup = Callable[[str], McpServerRecord | None]


def mcp_problems(
    document: BuilderDocument,
    *,
    servers: ServerLookup | None = None,
    resolve: HostResolver | None = None,
) -> list[Problem]:
    """Every `mcp` node this run could not honour, and why."""

    problems: list[Problem] = []
    for node in document.nodes:
        if node.kind != "mcp":
            continue
        config = node.config
        if not isinstance(config, McpConfig):  # pragma: no cover - schema guarantees it
            continue
        if not config.tool_names:
            problems.append(
                Problem(
                    code=MCP_NO_TOOLS_SELECTED,
                    severity="error",
                    message=(
                        f"{node.id} names a server and checks none of its tools; pick "
                        "at least one, or the agent gains nothing from the attachment"
                    ),
                    node_id=node.id,
                )
            )
        if servers is None:
            continue
        record = servers(config.server_id)
        if record is None:
            problems.append(
                Problem(
                    code=MCP_SERVER_UNAVAILABLE,
                    severity="error",
                    message=(
                        f"{node.id} names the MCP server {config.server_id}, which is "
                        "not one of yours; add it in the MCP panel first"
                    ),
                    node_id=node.id,
                )
            )
            continue
        refusal = transport_refusal(
            transport=record.transport,
            url=record.url,
            command=record.command,
            args=record.args,
            resolve=resolve,
        )
        if refusal is not None:
            problems.append(
                Problem(
                    code=MCP_TRANSPORT_DISALLOWED,
                    severity="error",
                    message=f"{node.id} uses {record.label!r}, and {refusal}",
                    node_id=node.id,
                )
            )
            continue
        for name in config.tool_names:
            tool = record.tool(name)
            if tool is None:
                problems.append(
                    Problem(
                        code=MCP_TOOL_UNKNOWN,
                        severity="error",
                        message=(
                            f"{node.id} checks {name!r} and {record.label!r}'s last "
                            "discovery does not carry it; re-discover the server"
                        ),
                        node_id=node.id,
                    )
                )
                continue
            if tool.suspicious:
                problems.append(
                    Problem(
                        code=MCP_TOOL_DESCRIPTION_SUSPICIOUS,
                        severity="warning",
                        message=(
                            f"{node.id} checks {name!r}, whose description matches "
                            f"{tool.matched_pattern!r}. That is often innocent - the "
                            "pattern list has false positives - but the description "
                            "reaches the agent's prompt, so read it before you ship"
                        ),
                        node_id=node.id,
                    )
                )
    return problems


__all__ = [
    "MCP_CONNECTION_ERROR_CLASS",
    "MCP_NO_TOOLS_SELECTED",
    "MCP_SERVER_UNAVAILABLE",
    "MCP_TOOL_DESCRIPTION_SUSPICIOUS",
    "MCP_TOOL_UNKNOWN",
    "MCP_TRANSPORT_DISALLOWED",
    "DiscoveredTool",
    "DiscoveryResult",
    "McpServerRecord",
    "McpUnavailable",
    "discover",
    "mask_url",
    "matched_injection_pattern",
    "mcp_problems",
    "sanitise_description",
    "sanitise_name",
    "sanitise_tool",
    "server_config",
    "transport_refusal",
]
