"""What the canvas became, as something a person can read - 09 D8.

Two renderings of one compiled definition, and neither is executed.

**The YAML is the literal thing the runtime loads.** `builder_runner.py` calls
`Flow.from_declaration(contents=...)` with exactly this document, so a preview
that showed anything else would be a second description of the graph and would
be wrong the first time somebody changed the compiler. It is produced by dumping
the definition `compile_document` returned, not by re-deriving it.

**The Python is a READING AID and says so on its last line.** It is produced by
walking the definition - `Agent(...)`, `Task(...)`, `Crew(...)`, `LLM(...)`, the
constructors the entrypoint will build - and nothing in it is evaluated, imported
or resolved. A power user who pastes it into a script gets a working program
minus the credentials, which is the point.

**No secret reaches either one.** A `credential_id` renders as
`<credential: label>` and the vault is never opened: the renderer takes a
labelling function, so the module that draws the preview cannot read a key even
by accident. `test_preview.py` proves it by seeding a credential whose value is
a sentinel string and asserting the sentinel is absent from the whole page.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import yaml

from brief_crew.builder.compiler import CompiledFlow

__all__ = ["CompiledPreview", "PREVIEW_BANNER", "render_preview"]

#: The last line of every Python rendering. It is not decoration: the file looks
#: enough like a program to be pasted into one, and the one thing it cannot do is
#: carry the credentials, so it has to say which half is missing.
PREVIEW_BANNER = (
    "# This file is a reading aid, not the program that runs. The graph runs from "
    "the\n# YAML above, through the compiler-owned entrypoints in "
    "brief_crew.builder.runtime.\n# Every <credential: ...> is a reference the "
    "server resolves for the run's owner;\n# no key appears here, and pasting this "
    "into a script means supplying your own."
)


@dataclass(frozen=True)
class CompiledPreview:
    """One compiled graph, rendered for a person - C7's `compiled` response."""

    yaml: str
    python: str
    definition: dict[str, Any]
    generated_at: datetime
    document_version: int


def render_preview(
    compiled: CompiledFlow,
    *,
    document_version: int,
    credential_label: Callable[[str], str] | None = None,
    generated_at: datetime | None = None,
) -> CompiledPreview:
    """Both renderings of one compiled definition.

    `generated_at` is a parameter rather than a `now()` inside, for the same
    reason `as_budget(compiled_at=...)` is: a caller comparing two previews
    byte for byte must be able to pin it, and a normalisation step that stripped
    the field would be a field the test stopped checking.
    """

    label = credential_label or (lambda credential_id: credential_id)
    definition = dict(compiled.definition)
    return CompiledPreview(
        yaml=yaml.safe_dump(definition, sort_keys=True, allow_unicode=True),
        python=_render_python(definition, label),
        definition=definition,
        generated_at=generated_at or datetime.now(timezone.utc),
        document_version=document_version,
    )


# --------------------------------------------------------------------------
# The Python rendering
# --------------------------------------------------------------------------
def _render_python(definition: Mapping[str, Any], label: Callable[[str], str]) -> str:
    lines: list[str] = [
        '"""' + str(definition.get("description", "")) + '"""',
        "",
        "from crewai import LLM, Agent, Crew, Process, Task",
        "",
        f"# flow: {definition.get('name')}",
        f"# max_method_calls: {dict(definition.get('config') or {}).get('max_method_calls')}",
        "",
    ]
    for name, method in dict(definition.get("methods") or {}).items():
        lines += _render_method(name, method, label)
    lines.append(PREVIEW_BANNER)
    return "\n".join(lines) + "\n"


def _render_method(
    name: str, method: Mapping[str, Any], label: Callable[[str], str]
) -> list[str]:
    action = dict(method.get("do") or {})
    ref = str(action.get("ref", ""))
    arguments = dict(action.get("with") or {})
    header = [
        f"# --- {name}: {method.get('description', '')}",
        f"#     {_trigger(method)}",
    ]

    if ref.endswith(":run_agent") and arguments.get("role") is not None:
        return header + _render_agent(arguments, label, wrap=True) + [""]
    if ref.endswith(":run_crew") and arguments.get("process") is not None:
        return header + _render_authored_crew(arguments, label) + [""]
    if ref.endswith(":run_agent"):
        return header + _render_library_agent(arguments, label) + [""]
    if ref.endswith(":run_crew"):
        return header + _render_library_crew(arguments) + [""]
    return header + [f"# {ref.rsplit(':', 1)[-1]}({_arguments(arguments, label)})", ""]


def _trigger(method: Mapping[str, Any]) -> str:
    if method.get("start"):
        return "runs first"
    return f"listens: {json.dumps(method.get('listen'), sort_keys=True)}"


def _render_agent(
    arguments: Mapping[str, Any],
    label: Callable[[str], str],
    *,
    suffix: str = "",
    wrap: bool = False,
) -> list[str]:
    """One authored agent, and - when it is a STEP rather than a member - the
    single-agent `Crew` the entrypoint actually builds around it.

    `run_agent` wraps one agent and one task in a `Crew` because that is what
    `kickoff` takes, so a preview that stopped at the `Task` would be a program
    that does not run. A crew MEMBER gets no wrapper: its own crew is the
    wrapper.
    """

    node = str(arguments.get("node_id", "node"))
    ident = _identifier(node) + suffix
    advanced = dict(arguments.get("advanced") or {})
    expert = dict(arguments.get("expert") or {})
    lines = [f"{ident}_llm = {_render_llm(dict(arguments.get('llm') or {}), arguments, label)}"]
    lines.append(f"{ident} = Agent(")
    lines.append(f"    role={arguments.get('role')!r},")
    lines.append(f"    goal={arguments.get('goal')!r},")
    lines.append(f"    backstory={arguments.get('backstory')!r},")
    lines.append(f"    llm={ident}_llm,")
    lines.append(f"    tools=[{_render_tools(arguments, label)}],")
    lines.append(f"    max_iter={arguments.get('max_iter')!r},")
    for key in (
        "max_rpm",
        "max_execution_time",
        "allow_delegation",
        "memory",
        "cache",
        "respect_context_window",
    ):
        lines.append(f"    {key}={advanced.get(key)!r},")
    lines.append(f"    planning={expert.get('planning', False)!r},")
    if expert.get("planning_config"):
        lines.append(f"    planning_config={expert['planning_config']!r},")
    for key in ("system_template", "prompt_template", "response_template"):
        if expert.get(key):
            lines.append(f"    {key}={expert[key]!r},")
    if arguments.get("mcps"):
        lines.append(f"    mcps={_render_mcps(arguments, label)},")
    if arguments.get("skills"):
        lines.append(f"    skills={list(arguments['skills'])!r},")
    lines.append(")")

    task = dict(arguments.get("task") or {})
    lines.append(f"{ident}_task = Task(")
    lines.append(f"    description={task.get('description')!r},")
    lines.append(f"    expected_output={task.get('expected_output')!r},")
    lines.append(f"    agent={ident},")
    lines.append(f"    markdown={task.get('markdown', False)!r},")
    lines.append(f"    async_execution={task.get('async_execution', False)!r},")
    lines.append(f"    guardrail_max_retries={arguments.get('guardrail_max_retries')!r},")
    if task.get("output_schema"):
        lines.append(f"    # output_schema: {task['output_schema']!r}")
    lines.append(")")
    if wrap:
        advanced = dict(arguments.get("advanced") or {})
        lines.append(f"{ident}_crew = Crew(")
        lines.append(f"    agents=[{ident}],")
        lines.append(f"    tasks=[{ident}_task],")
        lines.append("    process=Process.sequential,")
        lines.append(f"    memory={advanced.get('memory', False)!r},")
        lines.append(f"    cache={advanced.get('cache', True)!r},")
        lines.append(")")
    return lines


def _render_llm(
    llm: Mapping[str, Any], arguments: Mapping[str, Any], label: Callable[[str], str]
) -> str:
    parts = [f"model={llm.get('model')!r}"]
    for key in (
        "temperature",
        "top_p",
        "max_tokens",
        "timeout",
        "response_format",
        "frequency_penalty",
        "presence_penalty",
        "seed",
        "reasoning_effort",
    ):
        if llm.get(key) is not None:
            parts.append(f"{key}={llm[key]!r}")
    if llm.get("stop"):
        parts.append(f"stop={list(llm['stop'])!r}")
    credential = llm.get("credential_id") or arguments.get("credential_id")
    if credential:
        parts.append(f"api_key={_credential(str(credential), label)!r}")
    return "LLM(" + ", ".join(parts) + ")"


def _render_tools(arguments: Mapping[str, Any], label: Callable[[str], str]) -> str:
    rendered: list[str] = []
    for entry in arguments.get("tools") or ():
        if isinstance(entry, Mapping):
            tool_id = entry.get("tool_id")
            params = dict(entry.get("params") or {})
            credential = entry.get("credential_id")
            suffix = (
                f", credential={_credential(str(credential), label)!r}" if credential else ""
            )
            rendered.append(f"tool({tool_id!r}, **{params!r}{suffix})")
        else:
            rendered.append(f"tool({entry!r})")
    for entry in arguments.get("attachments") or ():
        if isinstance(entry, Mapping) and entry.get("kind") == "tool":
            rendered.append(f"tool({entry.get('tool_id')!r})")
    return ", ".join(rendered)


def _render_mcps(arguments: Mapping[str, Any], label: Callable[[str], str]) -> str:
    rendered = []
    for entry in arguments.get("mcps") or ():
        credential = entry.get("credential_id")
        rendered.append(
            {
                "server": entry.get("server_id"),
                "tools": list(entry.get("tool_names") or ()),
                **(
                    {"credential": _credential(str(credential), label)}
                    if credential
                    else {}
                ),
            }
        )
    return repr(rendered)


def _render_authored_crew(
    arguments: Mapping[str, Any], label: Callable[[str], str]
) -> list[str]:
    node = str(arguments.get("node_id", "crew"))
    ident = _identifier(node)
    members: Sequence[Mapping[str, Any]] = tuple(arguments.get("members") or ())
    by_id = {str(member.get("node_id")): member for member in members}
    order = [item for item in arguments.get("task_order") or () if item in by_id]
    order += [item for item in by_id if item not in order]

    lines: list[str] = []
    for member_id in order:
        lines += _render_agent(by_id[member_id], label)
        lines.append("")
    agents = ", ".join(_identifier(member_id) for member_id in order)
    tasks = ", ".join(f"{_identifier(member_id)}_task" for member_id in order)
    process = "Process.hierarchical" if arguments.get("process") == "hierarchical" else "Process.sequential"
    lines.append(f"{ident} = Crew(")
    lines.append(f"    agents=[{agents}],")
    lines.append(f"    tasks=[{tasks}],")
    lines.append(f"    process={process},")
    for key in ("memory", "cache", "planning", "verbose"):
        lines.append(f"    {key}={arguments.get(key)!r},")
    if arguments.get("max_rpm"):
        lines.append(f"    max_rpm={arguments['max_rpm']!r},")
    if arguments.get("manager_agent"):
        lines.append(f"    manager_agent={_identifier(str(arguments['manager_agent']))},")
    elif arguments.get("manager_llm"):
        lines.append(
            f"    manager_llm={_render_llm(dict(arguments['manager_llm']), arguments, label)},"
        )
    if arguments.get("planning_llm"):
        lines.append(
            f"    planning_llm={_render_llm(dict(arguments['planning_llm']), arguments, label)},"
        )
    lines.append(")")
    return lines


def _render_library_agent(
    arguments: Mapping[str, Any], label: Callable[[str], str]
) -> list[str]:
    """A registered agent: named, never rendered.

    Its role, goal and backstory live in `config/agents.yaml` and the platform
    rule keeps them there, so printing them here would make this file a second
    place they live - the exact thing an authored node exists to avoid. What the
    reader needs is which agent, on which tier, with what bound to it.
    """

    node = str(arguments.get("node_id", "node"))
    ident = _identifier(node)
    credential = arguments.get("credential_id")
    lines = [
        f"# {ident}: the registered agent {arguments.get('agent_id')!r}, whose role, goal",
        "# and backstory live in config/agents.yaml - this product's prompts stay there.",
        f"{ident} = registered_agent(",
        f"    {arguments.get('agent_id')!r},",
        f"    tier={arguments.get('tier')!r},",
        f"    tools={list(arguments.get('tools') or ())!r},",
        f"    max_iter={arguments.get('max_iter')!r},",
        f"    guardrail_max_retries={arguments.get('guardrail_max_retries')!r},",
    ]
    if credential:
        lines.append(f"    api_key={_credential(str(credential), label)!r},")
    if arguments.get("attachments"):
        lines.append(f"    attachments={_render_attachments(arguments, label)},")
    lines.append(")")
    return lines


def _render_attachments(
    arguments: Mapping[str, Any], label: Callable[[str], str]
) -> str:
    rendered: list[dict[str, Any]] = []
    for entry in arguments.get("attachments") or ():
        row = {key: value for key, value in dict(entry).items() if key != "credential_id"}
        credential = dict(entry).get("credential_id")
        if credential:
            row["credential"] = _credential(str(credential), label)
        rendered.append(row)
    return repr(rendered)


def _render_library_crew(arguments: Mapping[str, Any]) -> list[str]:
    ident = _identifier(str(arguments.get("node_id", "crew")))
    return [
        f"# {ident}: the registered crew {arguments.get('crew_id')!r}. It builds its own",
        f"# agents and its own LLMs in python, so tier={arguments.get('tier')!r} prices and",
        "# bounds this node and does not choose its models (decision 12).",
        f"{ident} = registered_crew({arguments.get('crew_id')!r}, "
        f"max_iter={arguments.get('max_iter')!r}, "
        f"guardrail_max_retries={arguments.get('guardrail_max_retries')!r})",
    ]


def _arguments(arguments: Mapping[str, Any], label: Callable[[str], str]) -> str:
    rendered = []
    for key, value in arguments.items():
        if key.endswith("credential_id") and value:
            value = _credential(str(value), label)
        rendered.append(f"{key}={value!r}")
    return ", ".join(rendered)


def _credential(credential_id: str, label: Callable[[str], str]) -> str:
    """A credential reference, never its value.

    The renderer holds a LABELLING FUNCTION and not a vault, so there is no path
    from here to a secret even if somebody later asks this module for one.
    """

    return f"<credential: {label(credential_id)}>"


def _identifier(node_id: str) -> str:
    """A node id as a python name. Node ids are already `[a-z0-9_]`."""

    safe = "".join(char if char.isalnum() or char == "_" else "_" for char in node_id)
    return safe if safe and not safe[0].isdigit() else f"n_{safe}"
