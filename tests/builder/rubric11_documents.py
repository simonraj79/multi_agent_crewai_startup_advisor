"""The twenty fixtures rubric 11 is scored on - 09 D9, criterion 10.

Twenty documents, built here in python rather than committed as JSON, because a
fixture whose shape nobody can read is a fixture nobody maintains. The GOLDENS
are committed - `tests/builder/fixtures/rubric11/` - and they are what the byte
comparison is against; these are the inputs that produce them.

**What each one is for** is in its own docstring. Between them they cover every
node kind, both families of the two billable kinds, both join types, an error
router, a retry with a fallback model, a hierarchical crew, a declared state
schema, an attachment of each kind, and two derived replay plans.

**Two things are deliberately absent, and both are determinism.** No fixture
fans out to two BILLABLE branches that run at once: CrewAI executes them with
`asyncio.gather`, and while the synthetic double is fast enough that the order
has been stable in practice, an ordering that is stable in practice is not a
golden. Where a fan-in is needed the arms are mutually exclusive router
branches, which run one at a time by construction. And nothing here names a
model outside the committed registry, so a roster change is a loud refusal
rather than a golden that quietly drifts.

No cost: every billable node is built by `SyntheticCrewFactories`, the same
object `SYNTHETIC=1` installs. No network, no model, no credential.
"""

from __future__ import annotations

from typing import Any

from brief_crew.builder.document import BuilderDocument

#: The builder's default authored model. A registry id, never a literal
#: invented here - `bounds.py` refuses a model no roster row carries.
MODEL = "google/gemini-3.8-flash"
CHEAPER = "google/gemini-3.5-flash-lite"
BODY_KEY = "markdown_body"
DOCUMENT_ID = "ug_11111111"


def _node(node_id: str, kind: str, config: dict[str, Any]) -> dict[str, Any]:
    return {"id": node_id, "kind": kind, "label": node_id, "config": config}


def _edge(
    edge_id: str,
    source: str,
    target: str,
    *,
    source_port: str = "out",
    target_port: str = "in",
) -> dict[str, Any]:
    return {
        "id": edge_id,
        "source": source,
        "source_port": source_port,
        "target": target,
        "target_port": target_port,
    }


def _input(node_id: str = "idea") -> dict[str, Any]:
    return _node(node_id, "input", {"field": "idea"})


def _output(node_id: str = "report", *, source: str) -> dict[str, Any]:
    return _node(node_id, "output", {"body_key": BODY_KEY, "source": source})


def _authored(node_id: str, *, source: str = "idea", **overrides: Any) -> dict[str, Any]:
    config: dict[str, Any] = {
        "role": f"{node_id} specialist",
        "goal": f"do the {node_id} work",
        "backstory": "years of it",
        "task": {
            "description": "work from ${state.out__" + source + "}",
            "expected_output": "a paragraph",
        },
        "llm": {"model": MODEL, "temperature": 0.2},
        "tier": "cheap",
    }
    config.update(overrides)
    return _node(node_id, "agent", config)


def _library(node_id: str, agent_id: str = "scoper", **overrides: Any) -> dict[str, Any]:
    config: dict[str, Any] = {
        "agent_id": agent_id,
        "tier": "escalation",
        "prompt_inputs": {"idea": "${state.out__idea}", "human_override": ""},
    }
    config.update(overrides)
    return _node(node_id, "agent", config)


def _document(
    name: str, nodes: list[dict[str, Any]], edges: list[dict[str, Any]], **extra: Any
) -> BuilderDocument:
    payload: dict[str, Any] = {
        "schema": "builder.flow/v1",
        "id": DOCUMENT_ID,
        "name": name,
        "version": 1,
        "input_field": "idea",
        "nodes": nodes,
        "edges": edges,
    }
    payload.update(extra)
    return BuilderDocument.model_validate(payload)


# --------------------------------------------------------------------------
# The twenty
# --------------------------------------------------------------------------
def straight_authored() -> BuilderDocument:
    """input -> authored agent -> output. The thing the gauntlet is about."""

    return _document(
        "Straight authored",
        [_input(), _authored("draft"), _output(source="${state.out__draft}")],
        [_edge("e1", "idea", "draft"), _edge("e2", "draft", "report")],
    )


def straight_library() -> BuilderDocument:
    """The other arm: a registered agent whose prompt lives in YAML."""

    return _document(
        "Straight library",
        [_input(), _library("scoper"), _output(source="${state.out__scoper}")],
        [_edge("e1", "idea", "scoper"), _edge("e2", "scoper", "report")],
    )


def library_crew() -> BuilderDocument:
    """A registered `@CrewBase`, run whole."""

    return _document(
        "Library crew",
        [
            _input(),
            _node("scope_crew", "crew", {"crew_id": "scope", "tier": "escalation"}),
            _output(source="${state.out__scope_crew}"),
        ],
        [_edge("e1", "idea", "scope_crew"), _edge("e2", "scope_crew", "report")],
    )


def authored_crew_sequential() -> BuilderDocument:
    """A team the author assembled: two members, one task each, in order."""

    return _document(
        "Authored crew, sequential",
        [
            _input(),
            _node(
                "team",
                "crew",
                {"process": "sequential", "tier": "cheap", "task_order": ["writer", "editor"]},
            ),
            _authored("writer"),
            _authored("editor"),
            _output(source="${state.out__team}"),
        ],
        [
            _edge("e1", "idea", "team"),
            _edge("e2", "team", "report"),
            _edge("m1", "writer", "team", target_port="member"),
            _edge("m2", "editor", "team", target_port="member"),
        ],
    )


def authored_crew_hierarchical() -> BuilderDocument:
    """A manager delegating to two members - the process that adds a call per task."""

    return _document(
        "Authored crew, hierarchical",
        [
            _input(),
            _node(
                "team",
                "crew",
                {
                    "process": "hierarchical",
                    "tier": "cheap",
                    "task_order": ["writer", "editor"],
                    "manager_llm": {"model": MODEL},
                },
            ),
            _authored("writer"),
            _authored("editor"),
            _output(source="${state.out__team}"),
        ],
        [
            _edge("e1", "idea", "team"),
            _edge("e2", "team", "report"),
            _edge("m1", "writer", "team", target_port="member"),
            _edge("m2", "editor", "team", target_port="member"),
        ],
    )


def with_a_tool() -> BuilderDocument:
    """A `tool` node folded into the agent that holds it."""

    return _document(
        "With a tool",
        [
            _input(),
            _authored("draft"),
            _node("search", "tool", {"tool_id": "serper_search", "params": {"n_results": 5}}),
            _output(source="${state.out__draft}"),
        ],
        [
            _edge("e1", "idea", "draft"),
            _edge("e2", "draft", "report"),
            _edge("a1", "search", "draft", source_port="attach", target_port="attach"),
        ],
    )


def with_an_mcp() -> BuilderDocument:
    """An `mcp` node: a server id and which of its tools this node exposes."""

    return _document(
        "With an MCP server",
        [
            _input(),
            _authored("draft"),
            _node(
                "files",
                "mcp",
                {"server_id": "mcp_a1b2c3d4", "tool_names": ["search", "fetch"]},
            ),
            _output(source="${state.out__draft}"),
        ],
        [
            _edge("e1", "idea", "draft"),
            _edge("e2", "draft", "report"),
            _edge("a1", "files", "draft", source_port="attach", target_port="attach"),
        ],
    )


def with_a_skill() -> BuilderDocument:
    """A `skill` node - knowledge, not hands."""

    return _document(
        "With a skill",
        [
            _input(),
            _authored("draft"),
            _node("style", "skill", {"skill_id": "sk_house", "skill_name": "House style"}),
            _output(source="${state.out__draft}"),
        ],
        [
            _edge("e1", "idea", "draft"),
            _edge("e2", "draft", "report"),
            _edge("a1", "style", "draft", source_port="attach", target_port="attach"),
        ],
    )


def all_three_attachments() -> BuilderDocument:
    """One agent holding one of each kind, in the order they were drawn."""

    return _document(
        "All three attachments",
        [
            _input(),
            _authored("draft"),
            _node("search", "tool", {"tool_id": "serper_search", "params": {}}),
            _node("files", "mcp", {"server_id": "mcp_a1b2c3d4", "tool_names": ["search"]}),
            _node("style", "skill", {"skill_id": "sk_house"}),
            _output(source="${state.out__draft}"),
        ],
        [
            _edge("e1", "idea", "draft"),
            _edge("e2", "draft", "report"),
            _edge("a1", "search", "draft", source_port="attach", target_port="attach"),
            _edge("a2", "files", "draft", source_port="attach", target_port="attach"),
            _edge("a3", "style", "draft", source_port="attach", target_port="attach"),
        ],
    )


def a_transform() -> BuilderDocument:
    """The one non-billable step that does work, and its `default` op."""

    return _document(
        "A transform",
        [
            _input(),
            _authored("draft"),
            _node(
                "tidy",
                "transform",
                {"op": "default", "args": {"value": "${state.out__draft}", "default": "nothing"}},
            ),
            _output(source="${state.out__tidy}"),
        ],
        [
            _edge("e1", "idea", "draft"),
            _edge("e2", "draft", "tidy"),
            _edge("e3", "tidy", "report"),
        ],
    )


def a_router() -> BuilderDocument:
    """A deterministic fork, and the `otherwise` branch it falls through to."""

    return _document(
        "A router",
        [
            _input(),
            _authored("draft"),
            _node(
                "fork",
                "router",
                {
                    "branches": [
                        {"label": "known", "op": "eq", "key": "out__missing", "value": "x"},
                        {"label": "unknown", "op": "otherwise"},
                    ]
                },
            ),
            _authored("guess", source="draft"),
            _authored("cite", source="draft"),
            _output(source="${state.out__guess}"),
        ],
        [
            _edge("e1", "idea", "draft"),
            _edge("e2", "draft", "fork"),
            _edge("e3", "fork", "cite", source_port="known"),
            _edge("e4", "fork", "guess", source_port="unknown"),
            _edge("e5", "guess", "report"),
            _edge("e6", "cite", "report"),
        ],
    )


def a_gate() -> BuilderDocument:
    """The pause. It compiles to TWO methods and this fixture never answers it.

    A run that stops at a gate is a run whose frames stop at the gate, and that
    is a perfectly good golden - it is the shape an operator sees before they
    reply, and it is the one shape a determinism harness can capture without a
    human in it.
    """

    return _document(
        "A gate",
        [
            _input(),
            _node("confirm", "gate", {"message": "Does this look right?", "max_turns": 1}),
            _authored("draft", source="confirm"),
            _output(source="${state.out__draft}"),
        ],
        [
            _edge("e1", "idea", "confirm"),
            _edge("e2", "confirm", "draft", source_port="approve"),
            _edge("e3", "draft", "report"),
        ],
    )


def an_all_join() -> BuilderDocument:
    """`joins: 'all'` - `{"and": [...]}`, and every arrival has to come.

    The two arms are IN SEQUENCE (`a` feeds `b`, and both feed `merge`) rather
    than in parallel, and that is the determinism decision this module's
    docstring describes: an `and` over two concurrent branches is a genuine
    join, but CrewAI runs them with `asyncio.gather` and the frame order is then
    the scheduler's rather than the graph's. Chaining them keeps the compiled
    shape exactly the same - `merge` still waits for both - while making the
    order a property of the document.
    """

    return _document(
        "An all join",
        [
            _input(),
            _authored("a", source="idea"),
            _authored("b", source="a"),
            _node("merge", "transform", {"op": "default", "args": {"value": "${state.out__b}"}}),
            _output(source="${state.out__merge}"),
        ],
        [
            _edge("e1", "idea", "a"),
            _edge("e2", "a", "b"),
            _edge("e3", "a", "merge"),
            _edge("e4", "b", "merge"),
            _edge("e5", "merge", "report"),
        ],
        joins={"merge": "all"},
    )


def an_any_join() -> BuilderDocument:
    """`joins: 'any'` - the first arrival runs it and the rest never fire."""

    return _document(
        "An any join",
        [
            _input(),
            _node(
                "fork",
                "router",
                {
                    "branches": [
                        {"label": "left", "op": "otherwise"},
                        {"label": "right", "op": "eq", "key": "out__missing", "value": "x"},
                    ]
                },
            ),
            _authored("a", source="idea"),
            _authored("b", source="idea"),
            _output(source="${state.out__a}"),
        ],
        [
            _edge("e1", "idea", "fork"),
            _edge("e2", "fork", "a", source_port="left"),
            _edge("e3", "fork", "b", source_port="right"),
            _edge("e4", "a", "report"),
            _edge("e5", "b", "report"),
        ],
        joins={"report": "any"},
    )


def an_error_router() -> BuilderDocument:
    """`on_error: route` - a step that can fail without failing the run."""

    return _document(
        "An error router",
        [
            _input(),
            _authored("draft", on_error="route"),
            _authored("apology", source="idea"),
            _output(source="${state.out__draft}"),
        ],
        [
            _edge("e1", "idea", "draft"),
            _edge("e2", "draft", "report"),
            _edge("e3", "draft", "apology", source_port="error"),
            _edge("e4", "apology", "report"),
        ],
    )


def a_retry_with_fallback() -> BuilderDocument:
    """A whole-node retry, priced at the DEARER of the two models."""

    return _document(
        "A retry with a fallback",
        [
            _input(),
            _authored(
                "draft",
                llm={"model": CHEAPER, "temperature": 0.2},
                retry={"max_retries": 2, "backoff_seconds": 0, "fallback_model": MODEL},
            ),
            _output(source="${state.out__draft}"),
        ],
        [_edge("e1", "idea", "draft"), _edge("e2", "draft", "report")],
    )


def a_declared_state() -> BuilderDocument:
    """`document.state` - the compiled `json_schema` state (09 D6)."""

    return _document(
        "A declared state",
        [_input(), _authored("draft"), _output(source="${state.out__draft}")],
        [_edge("e1", "idea", "draft"), _edge("e2", "draft", "report")],
        state={
            "fields": {
                "turns": {"type": "integer", "default": 0},
                "topic": {"type": "string", "default": "unset"},
            }
        },
    )


def a_revise_loop() -> BuilderDocument:
    """A cycle closed through a router, and the re-arm it compiles with."""

    return _document(
        "A revise loop",
        [
            _input(),
            _node("seed", "transform", {"op": "default", "args": {"value": "${state.out__idea}"}}),
            _node(
                "fork",
                "router",
                {
                    "branches": [
                        {"label": "first", "op": "eq", "key": "out__decide", "value": None},
                        {"label": "second", "op": "otherwise"},
                    ]
                },
            ),
            _authored("left", source="seed"),
            _authored("right", source="seed"),
            _node("merge", "transform", {"op": "default", "args": {"value": "${state.out__seed}"}}),
            _node(
                "decide",
                "router",
                {
                    "branches": [
                        {"label": "again", "op": "eq", "key": "out__decide", "value": None},
                        {"label": "done", "op": "otherwise"},
                    ]
                },
            ),
            _output(source="${state.out__merge}"),
        ],
        [
            _edge("e1", "idea", "seed"),
            _edge("e2", "seed", "fork"),
            _edge("e3", "fork", "left", source_port="first"),
            _edge("e4", "fork", "right", source_port="second"),
            _edge("e5", "left", "merge"),
            _edge("e6", "right", "merge"),
            _edge("e7", "merge", "decide"),
            _edge("e8", "decide", "seed", source_port="again"),
            _edge("e9", "decide", "report", source_port="done"),
        ],
    )


def both_families() -> BuilderDocument:
    """A library agent and an authored one in the same chain."""

    return _document(
        "Both families",
        [
            _input(),
            _library("scoper"),
            _authored("draft", source="scoper"),
            _output(source="${state.out__draft}"),
        ],
        [
            _edge("e1", "idea", "scoper"),
            _edge("e2", "scoper", "draft"),
            _edge("e3", "draft", "report"),
        ],
    )


def every_expert_control() -> BuilderDocument:
    """One authored agent with every optional control set.

    The S9 ruling's survivors: `planning` plus four of `planning_config`'s
    eleven, the three templates, `tool_failure_policy`. What is NOT here is
    `multimodal`, `function_calling_llm`, `reasoning` and
    `max_reasoning_attempts` - the schema is `extra="forbid"`, so this fixture
    would fail to parse if any of the four came back.
    """

    return _document(
        "Every expert control",
        [
            _input(),
            _authored(
                "draft",
                max_rpm=30,
                max_execution_time=120,
                allow_delegation=False,
                memory=False,
                cache=True,
                respect_context_window=True,
                system_template="You are {role}.",
                prompt_template="{input}",
                response_template="{output}",
                tool_failure_policy="raise",
                planning=True,
                planning_config={
                    "reasoning_effort": "low",
                    "max_attempts": 2,
                    "max_steps": 3,
                    "max_replans": 1,
                },
                llm={
                    "model": MODEL,
                    "temperature": 0.1,
                    "top_p": 0.9,
                    "max_tokens": 2048,
                    "seed": 7,
                    "stop": ["END"],
                    "response_format": "text",
                },
                task={
                    "description": "work from ${state.out__idea}",
                    "expected_output": "a JSON object",
                    "output_schema": {"headline": "string", "score": "integer"},
                    "markdown": False,
                    "async_execution": False,
                },
            ),
            _output(source="${state.out__draft}"),
        ],
        [_edge("e1", "idea", "draft"), _edge("e2", "draft", "report")],
    )


def a_long_chain() -> BuilderDocument:
    """Four authored agents nose to tail - depth, which is what prices a graph."""

    ids = ["one", "two", "three", "four"]
    nodes = [_input()]
    previous = "idea"
    for node_id in ids:
        nodes.append(_authored(node_id, source=previous))
        previous = node_id
    nodes.append(_output(source="${state.out__four}"))
    edges = [_edge("e0", "idea", "one")]
    edges += [
        _edge(f"e{index + 1}", source, target)
        for index, (source, target) in enumerate(zip(ids, ids[1:]))
    ]
    edges.append(_edge("e_out", "four", "report"))
    return _document("A long chain", nodes, edges)


#: The twenty, in a fixed order. A dict rather than a list because the golden
#: file is named for the key, and a golden nobody can trace back to its fixture
#: is a golden nobody will ever repair.
FIXTURES: dict[str, Any] = {
    "straight_authored": straight_authored,
    "straight_library": straight_library,
    "library_crew": library_crew,
    "authored_crew_sequential": authored_crew_sequential,
    "authored_crew_hierarchical": authored_crew_hierarchical,
    "with_a_tool": with_a_tool,
    "with_an_mcp": with_an_mcp,
    "with_a_skill": with_a_skill,
    "all_three_attachments": all_three_attachments,
    "a_transform": a_transform,
    "a_router": a_router,
    "a_gate": a_gate,
    "an_all_join": an_all_join,
    "an_any_join": an_any_join,
    "an_error_router": an_error_router,
    "a_retry_with_fallback": a_retry_with_fallback,
    "a_declared_state": a_declared_state,
    "a_revise_loop": a_revise_loop,
    "both_families": both_families,
    "every_expert_control": every_expert_control,
}

#: Two DERIVED plans (09 D7), compiled from a fixture rather than authored.
#: They are part of the twenty's coverage and not extras: a replay plan is a
#: compiled artefact like any other and has to be as reproducible.
REPLAYS: dict[str, tuple[Any, str, str]] = {
    "replay_resume_from": (a_long_chain, "three", "resume_from"),
    "replay_node_test": (a_long_chain, "three", "node_test"),
}
