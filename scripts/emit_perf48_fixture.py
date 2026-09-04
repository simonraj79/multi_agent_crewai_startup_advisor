"""Generate `frontend/tests/fixtures/perf48.json` - the bound-maximum graph.

Run it with the free backend up, from the repository root:

    $env:SYNTHETIC = "1"; $env:PORT = "8099"; ./.venv/Scripts/serve.exe
    python scripts/emit_perf48_fixture.py

The document is POSTed to `/api/builder/validate` BEFORE it is written, so a
fixture that the schema would refuse never reaches the repository - and the
problems it does carry are printed, so the one it is expected to carry
(`library-missing-prompt-input`, thirteen times, because a prompt input cannot
be guessed) is a decision rather than a surprise.

24 flow nodes (`MAX_GRAPH_NODES`) and 24 attachments (`MAX_ATTACHMENT_NODES`),
laid out on a grid wide enough that a fit-view has real work to do. Written by a
script rather than by hand because the shape has to satisfy several bounds at
once and a hand-typed 48-node document is a document nobody can re-derive.
"""

import json
import pathlib
import urllib.request

GRID_X = 320
GRID_Y = 220

nodes = []
edges = []


def add_node(node_id, kind, label, x, y, config):
    nodes.append(
        {
            "id": node_id,
            "label": label,
            "position": {"x": x, "y": y},
            "kind": kind,
            "config": config,
        }
    )


def add_edge(source, port, target, target_port="in"):
    edges.append(
        {
            "id": f"e{len(edges) + 1}",
            "source": source,
            "source_port": port,
            "target": target,
            "target_port": target_port,
        }
    )


def agent_config():
    return {
        "tier": "cheap",
        "max_iter": 2,
        "guardrail_max_retries": 2,
        "prompt_inputs": {},
        "agent_id": "scoper",
        "tools": [],
        "credential_id": None,
    }


# --- the spine -------------------------------------------------------------
# input -> gate -> [4 agents] -> transform -> gate -> [4 agents] -> router
#       -> [4 agents] -> transform -> gate -> output
# 1 input + 3 gates + 12 agents + 2 transforms + 1 router + 1 output = 20,
# plus 4 more agents behind the router's second branch = 24 flow nodes,
# of which 16 would be billable - one over MAX_BILLABLE_NODES=13. So the last
# rank is transforms and gates instead.

add_node("idea", "input", "Idea", 0, 0, {"field": "idea", "label": None, "max_chars": 2000, "required": True})

gate_config = {
    "message": "Review this step before the run continues.",
    "editable_fields": [],
    "max_turns": 1,
    "expiry_seconds": 1800,
}

add_node("gate_a", "gate", "Confirm scope", 0, GRID_Y, gate_config)
add_edge("idea", "out", "gate_a")

# Rank 1: four agents off the gate's approve port (MAX_FANOUT_WIDTH = 4).
rank1 = [f"agent_{i}" for i in range(1, 5)]
for index, node_id in enumerate(rank1):
    add_node(node_id, "agent", f"Analyst {index + 1}", (index - 1) * GRID_X, GRID_Y * 2, agent_config())
    add_edge("gate_a", "approve", node_id)

add_node("merge_1", "transform", "Merge one", 0, GRID_Y * 3, {"op": "pick", "args": {}})
for node_id in rank1:
    add_edge(node_id, "out", "merge_1")

add_node("gate_b", "gate", "Confirm findings", 0, GRID_Y * 4, gate_config)
add_edge("merge_1", "out", "gate_b")

# Rank 2: four more agents.
rank2 = [f"agent_{i}" for i in range(5, 9)]
for index, node_id in enumerate(rank2):
    add_node(node_id, "agent", f"Writer {index + 1}", (index - 1) * GRID_X, GRID_Y * 5, agent_config())
    add_edge("gate_b", "approve", node_id)

add_node(
    "route",
    "router",
    "Route",
    0,
    GRID_Y * 6,
    {
        "branches": [
            {"label": "hot", "op": "eq", "key": "decision", "value": "hot"},
            {"label": "cold", "op": "eq", "key": "decision", "value": "cold"},
            {"label": "otherwise", "op": "otherwise", "key": None, "value": None},
        ]
    },
)
for node_id in rank2:
    add_edge(node_id, "out", "route")

# Rank 3: four agents. Only THREE hang off the router, because
# `MAX_FANOUT_WIDTH` is 4 and it counts a node's outgoing edges rather than one
# port's - the `otherwise` branch is the fourth. The fourth agent sits behind
# the third instead, which is a shape an author really draws.
rank3 = [f"agent_{i}" for i in range(9, 13)]
for index, node_id in enumerate(rank3):
    add_node(node_id, "agent", f"Reviewer {index + 1}", (index - 1) * GRID_X, GRID_Y * 7, agent_config())
for index, node_id in enumerate(rank3[:3]):
    add_edge("route", "hot" if index < 2 else "cold", node_id)
add_edge(rank3[2], "out", rank3[3])

add_node("merge_2", "transform", "Merge two", 0, GRID_Y * 8, {"op": "pick", "args": {}})
for node_id in [rank3[0], rank3[1], rank3[3]]:
    add_edge(node_id, "out", "merge_2")
add_edge("route", "otherwise", "merge_2")

# The tail: one more agent - 13 billable, exactly MAX_BILLABLE_NODES - and
# three transforms, which cost nothing and take the flow count to its own
# ceiling. Transforms rather than a fourteenth agent, because the two bounds
# are different bounds and the fixture has to sit on both at once.
add_node("agent_13", "agent", "Editor", 0, GRID_Y * 9, agent_config())
add_edge("merge_2", "out", "agent_13")

add_node("shape_1", "transform", "Shape one", -GRID_X, GRID_Y * 10, {"op": "pick", "args": {}})
add_edge("agent_13", "out", "shape_1")
add_node("shape_2", "transform", "Shape two", 0, GRID_Y * 10, {"op": "pick", "args": {}})
add_edge("shape_1", "out", "shape_2")
add_node("shape_3", "transform", "Shape three", GRID_X, GRID_Y * 10, {"op": "pick", "args": {}})
add_edge("shape_2", "out", "shape_3")

add_node("gate_c", "gate", "Confirm result", 0, GRID_Y * 11, gate_config)
add_edge("shape_3", "out", "gate_c")

add_node("result", "output", "Result", 0, GRID_Y * 12, {"body_key": "markdown_body", "source": None})
add_edge("gate_c", "approve", "result")

flow_count = len(nodes)
assert flow_count == 24, flow_count

# --- 24 attachments, two per agent ----------------------------------------
agents = [node["id"] for node in nodes if node["kind"] == "agent"]
assert len(agents) == 13, len(agents)

for index, host in enumerate(agents[:12]):
    host_node = next(node for node in nodes if node["id"] == host)
    for slot, kind in enumerate(("tool", "skill")):
        node_id = f"{kind}_{index + 1}"
        config = (
            {"tool_id": "tool", "params": {}, "credential_id": None}
            if kind == "tool"
            else {"skill_id": "skill"}
        )
        add_node(
            node_id,
            kind,
            f"{kind.capitalize()} {index + 1}",
            host_node["position"]["x"] - 200,
            host_node["position"]["y"] + slot * 60,
            config,
        )
        add_edge(node_id, "attach", host, "attach")

assert len(nodes) == 48, len(nodes)

document = {
    "schema": "builder.flow/v1",
    "id": "ug_00abcdef",
    "name": "Perf 48",
    "version": 1,
    "input_field": "idea",
    "nodes": nodes,
    "edges": edges,
    "joins": {},
    "budget": None,
}

request = urllib.request.Request(
    "http://127.0.0.1:8099/api/builder/validate",
    data=json.dumps({"document": document}).encode(),
    headers={"Content-Type": "application/json"},
)
try:
    answer = json.loads(urllib.request.urlopen(request).read().decode())
    print("nodes", len(nodes), "edges", len(edges))
    print("valid", answer["valid"])
    seen = {}
    for problem in answer["problems"]:
        seen[problem["code"]] = seen.get(problem["code"], 0) + 1
    print("problems", seen)
    print("budget", answer["budget"])
except urllib.error.HTTPError as error:  # noqa: F821
    print("HTTP", error.code)
    print(error.read().decode()[:3000])
    raise SystemExit(1)

out = pathlib.Path(
    r"D:\MultiAgentSystem-wt\integration\frontend\tests\fixtures\perf48.json"
)
out.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8", newline="\n")
print("wrote", out)
