#!/usr/bin/env python
"""Emit the two JSON fixtures the TypeScript builder client is pinned against.

The canvas carries two mirrors of server logic, and both are the kind that rot
in silence.

* `frontend/src/utils/builderGraph.ts::backEdges` is a line-for-line copy of
  `bounds._back_edges_with_index`. It exists for STYLING - a cycle has to be
  legible on the canvas - and spec ruling R7 admits it on one condition: that a
  Python-generated fixture, regenerated in CI, is what proves it still agrees.
  Nothing about a wrong answer here raises. The edge simply stops being dashed,
  or the wrong one starts being, and the author reads a graph that is not the
  one the compiler sees.

* `frontend/src/types/builder.ts::PROBLEM_CODES` restates every code the server
  can emit, and three surfaces - node rims, `FieldProblem`, `ProblemsPanel` -
  divide the rendering between them. A code no surface claims is a problem the
  author is never shown, which is worse than an unhandled one: the document
  simply refuses to publish and nothing on screen says why.

So both fixtures are GENERATED from the real functions rather than written.
`tests/builder/test_client_fixtures.py` regenerates them and byte-compares, so
a change to `bounds.py` that moves an answer fails a Python test naming the
Python file, rather than a TypeScript test nobody runs in the same commit.

    ./.venv/Scripts/python.exe scripts/emit_builder_fixtures.py
    ./.venv/Scripts/python.exe scripts/emit_builder_fixtures.py --check

Two determinism rules make that byte-compare meaningful, and both are here
because the alternative is a gate that fails for reasons unrelated to drift:

* **Newlines are written LF, always.** `core.autocrlf` is `true` in this
  repository, so a checkout hands you CRLF and a naive comparison of the bytes
  on disk against the bytes this script produces fails on every Windows machine
  and passes on every Linux one. Both `--check` here and the Python test
  normalise the committed file before comparing, and say so where they do it.
* **Every price question is asked with an EXPLICIT ceiling.**
  `MAX_RUN_COST_USD` is `_env_non_negative_float(..., 10.0)`, so a developer or
  a CI job with that variable set would regenerate different sentences from
  identical source - a drift alarm about a shell. `CEILING_USD` below is passed
  to every call, which makes the fixture a fact about the code.

No network, no model, no credential: this reads `brief_crew.builder` and writes
two files.
"""

from __future__ import annotations

import argparse
import itertools
import json
import pathlib
import re
import sys
from typing import Any, Iterable, Sequence
from unittest import mock

REPO = pathlib.Path(__file__).resolve().parents[1]
if str(REPO / "src") not in sys.path:  # pragma: no cover - import bootstrap
    sys.path.insert(0, str(REPO / "src"))

from brief_crew.builder import back_edge_indices  # noqa: E402
from brief_crew.builder.compiler import document_problems  # noqa: E402
from brief_crew.builder.document import BuilderDocument  # noqa: E402

FIXTURES = REPO / "frontend" / "tests" / "fixtures"
BACK_EDGES_PATH = FIXTURES / "builderBackEdges.json"
PROBLEM_CODES_PATH = FIXTURES / "builderProblemCodes.json"

#: Stated rather than read from the environment. See the module docstring.
CEILING_USD = 10.0

#: A permutation set is emitted in full below this many edges and sampled above
#: it. Five is 120 orderings, a few kilobytes of two-integer rows, and it
#: exhausts the question; six is 720 and answers nothing new.
FULL_PERMUTATION_LIMIT = 5


# --------------------------------------------------------------------------
# Document construction - the WIRE spelling, so what is emitted is what a
# browser would post back, `schema` and all.
# --------------------------------------------------------------------------
def node(
    node_id: str,
    kind: str,
    config: dict[str, Any] | None = None,
    *,
    label: str | None = None,
    x: int = 0,
    y: int = 0,
) -> dict[str, Any]:
    return {
        "id": node_id,
        "kind": kind,
        "label": (label or node_id.replace("_", " "))[:40],
        "position": {"x": x, "y": y},
        "config": config or {},
    }


def edge(edge_id: str, source: str, target: str, *, port: str = "out") -> dict[str, Any]:
    return {
        "id": edge_id,
        "source": source,
        "source_port": port,
        "target": target,
        "target_port": "in",
    }


def document(
    name: str,
    nodes: Sequence[dict[str, Any]],
    edges: Sequence[dict[str, Any]],
    *,
    input_field: str = "idea",
    joins: dict[str, str] | None = None,
) -> dict[str, Any]:
    return {
        "schema": "builder.flow/v1",
        "id": "ug_0a1b2c3d",
        "name": name,
        "version": 1,
        "input_field": input_field,
        "nodes": list(nodes),
        "edges": list(edges),
        "joins": joins or {},
        "budget": None,
    }


def input_node(node_id: str = "idea", *, field: str | None = None) -> dict[str, Any]:
    return node(
        node_id,
        "input",
        {"field": field or node_id, "label": "Idea", "max_chars": 2000, "required": True},
    )


def agent_node(
    node_id: str,
    *,
    agent_id: str = "scoper",
    tier: str = "cheap",
    prompt_inputs: dict[str, Any] | None = None,
    tools: Sequence[str] = (),
    credential_id: str | None = None,
) -> dict[str, Any]:
    return node(
        node_id,
        "agent",
        {
            "tier": tier,
            "max_iter": 2,
            "guardrail_max_retries": 2,
            "prompt_inputs": dict(
                prompt_inputs
                if prompt_inputs is not None
                else {"human_override": "", "idea": "${state.idea}"}
            ),
            "agent_id": agent_id,
            "tools": list(tools),
            # Only when named, so every scenario written before the field
            # existed serialises byte-identical to what it did then.
            **({"credential_id": credential_id} if credential_id else {}),
        },
    )


def gate_node(node_id: str, *, max_turns: int = 1) -> dict[str, Any]:
    return node(
        node_id,
        "gate",
        {
            "message": "Confirm before spending.",
            "editable_fields": [],
            "max_turns": max_turns,
            "expiry_seconds": 1800,
        },
    )


def router_node(node_id: str, branches: Sequence[dict[str, Any]]) -> dict[str, Any]:
    return node(node_id, "router", {"branches": list(branches)})


def branch(
    label: str, op: str = "eq", key: str | None = "idea", value: Any = "yes"
) -> dict[str, Any]:
    if op == "otherwise":
        return {"label": label, "op": "otherwise", "key": None, "value": None}
    return {"label": label, "op": op, "key": key, "value": value}


def transform_node(node_id: str) -> dict[str, Any]:
    return node(
        node_id,
        "transform",
        {"op": "pick", "args": {"source": "${state.idea}", "key": "idea"}},
    )


def output_node(node_id: str = "report") -> dict[str, Any]:
    return node(node_id, "output", {"body_key": "markdown_body", "source": None})


# --------------------------------------------------------------------------
# Fixture one: back edges, under every ordering of the same edge set
# --------------------------------------------------------------------------
#: Each case is a topology plus the reason it is here. The mirror's three
#: non-obvious behaviours - the input-first root sweep, the unknown-target skip,
#: and the per-frame cursor Python's stored iterator gives for free - each have
#: a case that fails without them.
BACK_EDGE_CASES: list[dict[str, Any]] = [
    {
        "name": "an acyclic graph closes nothing",
        "why": (
            "The negative case, and one a mirror that returned every edge would fail "
            "and a mirror that returned nothing would pass. A gate with both ports "
            "drawn forward is the shape the minimal gated template ships in, so this "
            "is also the assertion that the flagship template draws no dashed edge."
        ),
        "document": document(
            "acyclic",
            [input_node(), gate_node("confirm"), agent_node("draft"), output_node()],
            [
                edge("e1", "idea", "confirm"),
                edge("e2", "confirm", "draft", port="approve"),
                edge("e3", "confirm", "report", port="revise"),
                edge("e4", "draft", "report"),
            ],
        ),
    },
    {
        "name": "a gate's revise port closes a loop",
        "why": (
            "The revise loop, which is the only cycle most documents will ever have. "
            "A gate's second compiled method IS a router, so this is the legal shape: "
            "the client dashes it and `back-edge-not-router` never fires."
        ),
        "document": document(
            "gate revise loop",
            [input_node(), agent_node("draft"), gate_node("confirm"), output_node()],
            [
                edge("e1", "idea", "draft"),
                edge("e2", "draft", "confirm"),
                edge("e3", "confirm", "report", port="approve"),
                edge("e4", "confirm", "draft", port="revise"),
            ],
        ),
    },
    {
        "name": "two routers close two nested loops",
        "why": (
            "Two back edges whose ORDER in `edges` decides which position each is "
            "reported at. A mirror that collects edges rather than positions cannot "
            "tell these apart once the outer loop is permuted ahead of the inner one."
        ),
        "document": document(
            "nested loops",
            [
                input_node(),
                agent_node("draft"),
                router_node("inner", [branch("again"), branch("on", op="otherwise")]),
                router_node("outer", [branch("back"), branch("done", op="otherwise")]),
                output_node(),
            ],
            [
                edge("e1", "idea", "draft"),
                edge("e2", "draft", "inner"),
                edge("e3", "inner", "draft", port="again"),
                edge("e4", "inner", "outer", port="on"),
                edge("e5", "outer", "draft", port="back"),
            ],
        ),
    },
    {
        "name": "two edges between one pair, on different ports",
        "why": (
            "The case `back_edge_indices` answers in POSITIONS for. A gate's approve "
            "and revise may both land on the same node; one of them closes the loop "
            "and the other does not, and nothing but the position says which."
        ),
        "document": document(
            "parallel ports",
            [input_node(), agent_node("draft"), gate_node("confirm")],
            [
                edge("e1", "idea", "draft"),
                edge("e2", "draft", "confirm"),
                edge("e3", "confirm", "draft", port="approve"),
                edge("e4", "confirm", "draft", port="revise"),
            ],
        ),
    },
    {
        "name": "a cycle no input can reach is still counted",
        "why": (
            "The second half of the root list. The search seeds from the input nodes "
            "FIRST so the numbering matches the order a run visits them, then sweeps "
            "every remaining node - drop that sweep and a detached loop is silently "
            "free, which is exactly the graph an author has mid-edit."
        ),
        "document": document(
            "detached loop",
            [
                input_node(),
                output_node(),
                agent_node("orphan"),
                router_node("spin", [branch("round"), branch("stop", op="otherwise")]),
            ],
            [
                edge("e1", "idea", "report"),
                edge("e2", "orphan", "spin"),
                edge("e3", "spin", "orphan", port="round"),
            ],
        ),
    },
    {
        "name": "an edge to an id no node has is skipped, not descended into",
        "why": (
            "A document mid-edit routinely names a node that was just deleted. The "
            "search steps over it rather than treating it as a fresh vertex - a "
            "mirror that descends reports a loop through a node that does not exist, "
            "and `edge-unknown-endpoint` is the server's to raise, not the canvas's "
            "to guess at."
        ),
        "document": document(
            "dangling target",
            [
                input_node(),
                agent_node("draft"),
                router_node("pick", [branch("go"), branch("stop", op="otherwise")]),
            ],
            [
                edge("e1", "idea", "draft"),
                edge("e2", "draft", "pick"),
                edge("e3", "pick", "ghost", port="go"),
                edge("e4", "pick", "draft", port="stop"),
            ],
        ),
    },
    {
        "name": "a router that points at itself",
        "why": (
            "The degenerate loop, one edge long. It reaches the on-the-stack branch "
            "on the same frame that pushed it, which is the one path a mirror written "
            "with a visited SET instead of a two-colour state gets wrong."
        ),
        "document": document(
            "self loop",
            [
                input_node(),
                router_node("spin", [branch("again"), branch("stop", op="otherwise")]),
                output_node(),
            ],
            [
                edge("e1", "idea", "spin"),
                edge("e2", "spin", "spin", port="again"),
                edge("e3", "spin", "report", port="stop"),
            ],
        ),
    },
]


def _permutation_orders(count: int) -> Iterable[tuple[int, ...]]:
    """Every ordering of `count` edges, or a deterministic stride over them."""

    orders = itertools.permutations(range(count))
    if count <= FULL_PERMUTATION_LIMIT:
        return list(orders)
    # A stride rather than a sample: a fixture regenerated in CI has to be
    # byte-identical, and `random` - seeded or not - is one more thing to get
    # wrong for no gain.
    return list(itertools.islice(orders, 0, None, 7))


def build_back_edges() -> dict[str, Any]:
    cases: list[dict[str, Any]] = []
    for case in BACK_EDGE_CASES:
        base = case["document"]
        edges = base["edges"]
        permutations: list[dict[str, Any]] = []
        for order in _permutation_orders(len(edges)):
            permuted = {**base, "edges": [edges[index] for index in order]}
            parsed = BuilderDocument.model_validate(permuted)
            permutations.append(
                {"order": list(order), "back_edge_indices": list(back_edge_indices(parsed))}
            )
        cases.append(
            {
                "name": case["name"],
                "why": case["why"],
                "document": base,
                "permutations": permutations,
            }
        )
    return {
        "generator": "scripts/emit_builder_fixtures.py",
        "source": "brief_crew.builder.bounds.back_edge_indices",
        "mirror": "frontend/src/utils/builderGraph.ts::backEdges",
        "note": (
            "Every `permutations` row is the answer the REAL function gave for the "
            "base document with its edges reordered by `order`. The mirror is fed the "
            "same reordering and must return the same positions."
        ),
        "cases": cases,
    }


# --------------------------------------------------------------------------
# Fixture two: one real instance of every problem code
# --------------------------------------------------------------------------
def _long_gate_id() -> str:
    """Thirty-six characters: legal as a node id, illegal as a GATE's.

    A gate compiles to two methods and the second is prefixed `route_`, so
    BUILDER_METHOD_IDENT_PATTERN leaves a gate six characters less room than any
    other kind. This id is inside the id pattern's forty and outside that.
    """

    return "g" + "a" * 35


#: Each scenario declares the codes it exists to produce. A scenario that fails
#: to produce one of its declared codes, or claims one another scenario has
#: already taken, ABORTS the emit naming the code - so this list cannot drift
#: into covering twenty-seven of thirty while still looking complete, which is
#: precisely how the counts in CLAUDE.md went wrong five separate times.
PROBLEM_SCENARIOS: list[dict[str, Any]] = [
    {
        "name": "more nodes than the graph ceiling",
        "expects": ["node-count"],
        "document": document(
            "too many nodes",
            [input_node(), *[transform_node(f"n{index}") for index in range(25)]],
            [edge("e1", "idea", "n0")],
        ),
    },
    {
        "name": "more model-calling nodes than the billable ceiling",
        "expects": ["billable-count"],
        "document": document(
            "too many billable",
            [input_node(), *[agent_node(f"a{index}") for index in range(14)]],
            [edge("e1", "idea", "a0")],
        ),
    },
    {
        "name": "more escalation-tier nodes than the escalation ceiling",
        "expects": ["escalation-count"],
        "document": document(
            "too much escalation",
            [
                input_node(),
                *[agent_node(f"a{index}", tier="escalation") for index in range(9)],
            ],
            [edge("e1", "idea", "a0")],
        ),
    },
    {
        "name": "two nodes and two edges sharing an id",
        "expects": ["duplicate-node-id", "duplicate-edge-id"],
        "document": document(
            "duplicate ids",
            [input_node(), transform_node("step"), transform_node("step"), output_node()],
            [edge("e1", "idea", "step"), edge("e1", "step", "report")],
        ),
    },
    {
        "name": "an edge naming a node that was deleted",
        "expects": ["edge-unknown-endpoint"],
        "document": document(
            "dangling edge",
            [input_node(), output_node()],
            [edge("e1", "idea", "report"), edge("e2", "idea", "ghost")],
        ),
    },
    {
        "name": "an edge leaving an agent by a gate's port",
        "expects": ["edge-unknown-port"],
        "document": document(
            "wrong port",
            [input_node(), agent_node("draft"), output_node()],
            [edge("e1", "idea", "draft"), edge("e2", "draft", "report", port="approve")],
        ),
    },
    {
        "name": "an edge arriving at the input node",
        "expects": ["edge-target-refuses-incoming"],
        "document": document(
            "edge into the input",
            [input_node(), agent_node("draft"), output_node()],
            [
                edge("e1", "idea", "draft"),
                edge("e2", "draft", "idea"),
                edge("e3", "draft", "report"),
            ],
        ),
    },
    {
        "name": "one node fanning out wider than the concurrency ceiling",
        "expects": ["fanout-width"],
        "document": document(
            "too wide",
            [input_node(), *[transform_node(f"t{index}") for index in range(5)], output_node()],
            [
                *[edge(f"e{index}", "idea", f"t{index}") for index in range(5)],
                edge("e9", "t0", "report"),
            ],
        ),
    },
    {
        "name": "a router with five branches and no otherwise",
        "expects": ["router-branch-count", "router-otherwise", "router-branch-unconnected"],
        "document": document(
            "router shape",
            [
                input_node(),
                router_node(
                    "wide",
                    [
                        branch("one"),
                        branch("two", value="two"),
                        branch("three", value="three"),
                        branch("four", value="four"),
                        branch("five", value="five"),
                    ],
                ),
                output_node(),
            ],
            [edge("e1", "idea", "wide"), edge("e2", "wide", "report", port="one")],
        ),
    },
    {
        "name": "a router declaring the same branch label twice",
        "expects": ["router-duplicate-branch", "ident-collision"],
        "why": (
            "The two codes come from one mistake, and `ident-collision` comes from "
            "nothing else. Method idents are n<index>_<id> and event labels "
            "e<index>_<port>, and the index is unique per node, so the ONLY way two "
            "compiled names collide is a router emitting one label twice - which is "
            "what a duplicate branch is."
        ),
        "document": document(
            "duplicate branch",
            [
                input_node(),
                router_node(
                    "pick",
                    [
                        branch("same"),
                        branch("same", value="other"),
                        branch("rest", op="otherwise"),
                    ],
                ),
                output_node(),
            ],
            [
                edge("e1", "idea", "pick"),
                edge("e2", "pick", "report", port="same"),
                edge("e3", "pick", "report", port="rest"),
            ],
        ),
    },
    {
        "name": "four loops against the cycle ceiling, one of them from a plain agent",
        "expects": ["cycle-count", "back-edge-not-router"],
        "why": (
            "`back-edge-not-router` is the measured one: with a plain node closing "
            "the loop the join fires once, the second arrival is suppressed, and the "
            "run ends normally having produced nothing - no exception, no warning."
        ),
        "document": document(
            "too many loops",
            [
                input_node(),
                agent_node("a"),
                gate_node("g1"),
                gate_node("g2"),
                gate_node("g3"),
                agent_node("b"),
                output_node(),
            ],
            [
                edge("e1", "idea", "a"),
                edge("e2", "a", "g1"),
                edge("e3", "g1", "g2", port="approve"),
                edge("e4", "g1", "a", port="revise"),
                edge("e5", "g2", "g3", port="approve"),
                edge("e6", "g2", "a", port="revise"),
                edge("e7", "g3", "b", port="approve"),
                edge("e8", "g3", "a", port="revise"),
                edge("e9", "b", "a"),
                edge("e10", "b", "report"),
            ],
        ),
    },
    {
        "name": "a gate allowing more revise turns than the cycle-iteration ceiling",
        "expects": ["cycle-iterations"],
        "document": document(
            "too many turns",
            [input_node(), agent_node("draft"), gate_node("confirm", max_turns=4), output_node()],
            [
                edge("e1", "idea", "draft"),
                edge("e2", "draft", "confirm"),
                edge("e3", "confirm", "report", port="approve"),
                edge("e4", "confirm", "draft", port="revise"),
            ],
        ),
    },
    {
        "name": "a graph with nothing to seed it",
        "expects": ["no-input-node"],
        "document": document(
            "no input",
            [transform_node("step"), output_node()],
            [edge("e1", "step", "report")],
        ),
    },
    {
        "name": "an input node asking for a different key than the document declares",
        "expects": ["input-field-undeclared", "no-output-node"],
        "document": document(
            "undeclared field",
            [input_node("topic", field="topic"), transform_node("step")],
            [edge("e1", "topic", "step")],
        ),
    },
    {
        "name": "two input nodes asking for the same key",
        "expects": ["input-field-ambiguous"],
        "document": document(
            "ambiguous field",
            [input_node("idea"), input_node("second", field="idea"), output_node()],
            [edge("e1", "idea", "report"), edge("e2", "second", "report")],
        ),
    },
    {
        "name": "a node nothing leads to",
        "expects": ["node-unreachable"],
        "document": document(
            "orphan",
            [input_node(), transform_node("step"), transform_node("stranded"), output_node()],
            [edge("e1", "idea", "step"), edge("e2", "step", "report")],
        ),
    },
    {
        "name": "joins naming a node that is not there, and one with a single arrival",
        "expects": ["join-unknown-node", "join-single-predecessor"],
        "document": document(
            "join shapes",
            [input_node(), transform_node("step"), output_node()],
            [edge("e1", "idea", "step"), edge("e2", "step", "report")],
            joins={"step": "all", "ghost": "all"},
        ),
    },
    {
        "name": "a gate whose id leaves no room for its compiled router",
        "expects": ["ident-pattern"],
        "document": document(
            "long gate id",
            [input_node(), gate_node(_long_gate_id()), output_node()],
            [
                edge("e1", "idea", _long_gate_id()),
                edge("e2", _long_gate_id(), "report", port="approve"),
                edge("e3", _long_gate_id(), "report", port="revise"),
            ],
        ),
    },
    {
        "name": "an agent naming a library id this deployment does not register",
        "expects": ["library-unknown-id"],
        "document": document(
            "unknown agent",
            [input_node(), agent_node("draft", agent_id="nobody"), output_node()],
            [edge("e1", "idea", "draft"), edge("e2", "draft", "report")],
        ),
    },
    {
        "name": "an agent whose task placeholders are left unfilled",
        "expects": ["library-missing-prompt-input"],
        "document": document(
            "missing prompt inputs",
            [input_node(), agent_node("draft", prompt_inputs={}), output_node()],
            [edge("e1", "idea", "draft"), edge("e2", "draft", "report")],
        ),
    },
    {
        "name": "a crew that is registered but cannot be constructed",
        "expects": ["library-unbuildable-crew"],
        "why": (
            "`SynthesisCrew` takes typed findings at construction, so a document "
            "naming it once compiled, published and priced cleanly and then raised a "
            "bare TypeError at the first PAID run - after the scoper and all three "
            "research branches had billed."
        ),
        "document": document(
            "unbuildable crew",
            [
                input_node(),
                node(
                    "combine",
                    "crew",
                    {
                        "tier": "escalation",
                        "max_iter": 2,
                        "guardrail_max_retries": 2,
                        "prompt_inputs": {},
                        "crew_id": "synthesis",
                    },
                ),
                output_node(),
            ],
            [edge("e1", "idea", "combine"), edge("e2", "combine", "report")],
        ),
    },
    {
        "name": "a graph whose worst case prices past the per-run ceiling",
        "expects": ["budget-over-ceiling"],
        "document": document(
            "expensive",
            [
                input_node(),
                *[
                    agent_node(
                        f"a{index}",
                        tier="escalation",
                        agent_id="synthesist",
                        prompt_inputs={},
                        tools=["research_market_landscape"],
                    )
                    for index in range(8)
                ],
                gate_node("confirm", max_turns=3),
                output_node(),
            ],
            [
                edge("e1", "idea", "a0"),
                *[edge(f"e{index + 2}", f"a{index}", f"a{index + 1}") for index in range(7)],
                edge("e9", "a7", "confirm"),
                edge("e10", "confirm", "report", port="approve"),
                edge("e11", "confirm", "a0", port="revise"),
            ],
        ),
    },
    {
        "name": "a tier pointed at a model PRICES cannot price",
        "expects": ["budget-unpriced-model"],
        "why": (
            "Provoked by pointing the cheap tier at a slug with no PRICES entry, "
            "which is the shape a model swap without a matching price commit takes. "
            "The failure it stands against is the one that reported a 128,069-token "
            "run at $0.00: `PRICES.get(model, (0.0, 0.0))` turning 'no price on file' "
            "into 'this call was free'."
        ),
        "patch_cheap_model": "openrouter/example/unpriced-preview",
        "document": document(
            "unpriced",
            [input_node(), agent_node("draft"), output_node()],
            [edge("e1", "idea", "draft"), edge("e2", "draft", "report")],
        ),
    },
    {
        "name": "an agent naming a credential that is not in the caller's vault",
        "expects": ["credential-missing"],
        "why": (
            "Plan 01 D10: absent and foreign are ONE code, because the vault answers "
            "both with one exception and a canvas that could tell them apart would "
            "be an oracle for other people's ids. Only produced when the caller has "
            "an identity; this fixture validates as somebody whose vault is empty."
        ),
        "credential_check": "empty-vault",
        "document": document(
            "foreign credential",
            [input_node(), agent_node("draft", credential_id="cr_0badc0de"), output_node()],
            [edge("e1", "idea", "draft"), edge("e2", "draft", "report")],
        ),
    },
]


def _problems_for(scenario: dict[str, Any]) -> list[Any]:
    parsed = BuilderDocument.model_validate(scenario["document"])
    # A scenario that names `credential_check` is validated AS somebody whose
    # vault holds nothing - the identity plan 01 D10 checks references against,
    # with no rows. None is the anonymous caller, for whom the check is skipped
    # and `credential-missing` can never fire.
    credential_check = (
        (lambda _credential_id: False) if scenario.get("credential_check") else None
    )
    slug = scenario.get("patch_cheap_model")
    if slug is None:
        return document_problems(
            parsed, ceiling_usd=CEILING_USD, credential_check=credential_check
        )

    from brief_crew.builder import budget as budget_module

    with mock.patch.dict(budget_module._MODEL_BY_TIER, {"cheap": slug}):
        return document_problems(
            parsed, ceiling_usd=CEILING_USD, credential_check=credential_check
        )


def _declared_codes() -> set[str]:
    """Every code the three declaring modules carry, read the way the mirror does.

    The same regex `frontend/tests/builderTypes.spec.ts` greps with, and
    `tests/builder/test_problem_code_declarations.py` is what guarantees no code
    can hide from it. Reading the source rather than importing the constants is
    deliberate: this is the set the CLIENT can discover, and covering exactly
    that set is the point.
    """

    pattern = re.compile(r'^([A-Z][A-Z0-9_]*) = "([a-z]+(?:-[a-z]+)+)"$', re.MULTILINE)
    builder = REPO / "src" / "brief_crew" / "builder"
    codes: set[str] = set()
    for name in ("bounds.py", "budget.py", "compiler.py"):
        text = (builder / name).read_text(encoding="utf-8")
        codes |= {match.group(2) for match in pattern.finditer(text)}
    return codes


def build_problem_codes() -> dict[str, Any]:
    captured: dict[str, dict[str, Any]] = {}
    claimed_by: dict[str, str] = {}

    for scenario in PROBLEM_SCENARIOS:
        produced = {problem.code: problem for problem in _problems_for(scenario)}
        for code in scenario["expects"]:
            if code in claimed_by:
                raise SystemExit(
                    f"{scenario['name']!r} claims {code!r}, already claimed by "
                    f"{claimed_by[code]!r}; one instance per code, so drop one claim"
                )
            problem = produced.get(code)
            if problem is None:
                raise SystemExit(
                    f"{scenario['name']!r} declares {code!r} and the real "
                    f"document_problems did not produce it; it produced {sorted(produced)}"
                )
            claimed_by[code] = scenario["name"]
            captured[code] = {
                "code": problem.code,
                "scenario": scenario["name"],
                "why": scenario.get("why", ""),
                "problem": {
                    "code": problem.code,
                    "severity": problem.severity,
                    "message": problem.message,
                    "node_id": problem.node_id,
                    "edge_id": problem.edge_id,
                },
            }

    declared = _declared_codes()
    missing = sorted(declared - set(captured))
    if missing:
        raise SystemExit(
            "no scenario produces "
            + ", ".join(missing)
            + "; every code the server can emit needs one instance here, or the "
            "client's rendering of it is untested"
        )
    unknown = sorted(set(captured) - declared)
    if unknown:
        raise SystemExit(
            "captured "
            + ", ".join(unknown)
            + ", which no module-level constant declares; see "
            "tests/builder/test_problem_code_declarations.py"
        )

    return {
        "generator": "scripts/emit_builder_fixtures.py",
        "source": "brief_crew.builder.compiler.document_problems",
        "mirror": "frontend/src/types/builder.ts::PROBLEM_CODES",
        "ceiling_usd": CEILING_USD,
        "note": (
            "One real instance of every problem code, produced by running the named "
            "function over a document that provokes it. The `message` strings are "
            "verbatim: the canvas renders them unaltered, so a client test asserting "
            "against a paraphrase would be asserting about a fiction."
        ),
        "codes": sorted(captured),
        "instances": [captured[code] for code in sorted(captured)],
        # The document each scenario ran over, keyed by scenario name, so a client
        # test can index a REAL problem against the REAL node it anchors to.
        # Without these the anchors are dangling strings and `problemsByNode` can
        # be asserted against a graph that has no such node - which is a test that
        # passes over an index nobody could ever build.
        "documents": {
            scenario["name"]: scenario["document"]
            for scenario in PROBLEM_SCENARIOS
            if any(code in claimed_by for code in scenario["expects"])
        },
    }


# --------------------------------------------------------------------------
# Emit
# --------------------------------------------------------------------------
def render(payload: dict[str, Any]) -> bytes:
    """The exact bytes a fixture file holds. LF, two-space, trailing newline."""

    return (json.dumps(payload, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def committed(path: pathlib.Path) -> bytes | None:
    """A fixture's bytes with CRLF normalised away, or None if it is absent.

    The normalisation is the whole reason this is a function. `core.autocrlf` is
    `true` here, so the file on disk is CRLF in a working tree and LF in the
    object store; comparing raw bytes would fail on every Windows checkout and
    pass on every Linux one, which is a gate that reports the platform rather
    than the drift it was built for.
    """

    if not path.exists():
        return None
    return path.read_bytes().replace(b"\r\n", b"\n")


def targets() -> tuple[tuple[pathlib.Path, bytes], ...]:
    return (
        (BACK_EDGES_PATH, render(build_back_edges())),
        (PROBLEM_CODES_PATH, render(build_problem_codes())),
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Emit the builder client fixtures.")
    parser.add_argument(
        "--check",
        action="store_true",
        help="report whether the committed fixtures are current; write nothing",
    )
    args = parser.parse_args(argv)

    stale: list[str] = []
    for path, content in targets():
        if committed(path) == content:
            continue
        stale.append(str(path.relative_to(REPO)).replace("\\", "/"))
        if not args.check:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)

    if args.check:
        if stale:
            print("stale: " + ", ".join(stale))
            return 1
        print("fixtures are current")
        return 0

    print("rewrote: " + ", ".join(stale) if stale else "unchanged")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
