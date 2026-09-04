"""An output node follows its incoming edge when the author names no source.

**Found by the first paid run of an authored graph, 2026-09-04**, and by
nothing else. `input → gate → agent → output`, composed on the canvas:

```text
save      201
validate  200   problems=0
publish   200
launch    202   → gate → approve → completed in 19s
usage     1 real call, 896 completion tokens, $0.0035
result    {"markdown_body": "", "node_id": "out"}
```

A run that succeeded, cost money, and handed back nothing. `OutputConfig.source`
defaults to `None`, the compiler passed that straight through, and
`emit_output` did `_as_text(None) → ""`.

**This is the drag-and-drop case, not an edge case.** An author who connects an
agent to an output has already said where the body comes from; requiring them to
*also* hand-type `${state.out__writer}` is exactly the redundancy a visual
builder exists to remove — and the penalty for omitting it was silent, after
validation reported zero problems.

Every layer behaved as written, which is why no test caught it: the schema says
`source` is optional, the compiler passed what it was given, `emit_output`
rendered `None` as empty, and `bounds.py` had no rule saying otherwise. The
defect lived in the space between four correct components.
"""

from __future__ import annotations

import unittest

from brief_crew.builder.compiler import compile_document
from brief_crew.builder.document import BuilderDocument


def _authored(role: str) -> dict:
    """An AUTHORED agent, because that is the arm the defect appeared on.

    A library agent would need `prompt_inputs` for the YAML task it keys into,
    which is a different subject and would make this fixture about that.
    """

    return {
        "role": role,
        "goal": "Explain the topic to a curious beginner.",
        "backstory": "You have taught this for a decade.",
        "task": {"description": "Explain it.", "expected_output": "Three paragraphs."},
        "llm": {"model": "google/gemini-3.8-flash"},
        "tier": "cheap",
    }


def _document(*, source: str | None = None, second_agent: bool = False) -> BuilderDocument:
    nodes = [
        {"id": "seed", "kind": "input", "label": "Topic",
         "config": {"field": "topic"}, "position": {"x": 0, "y": 0}},
        {"id": "writer", "kind": "agent", "label": "Explainer",
         "config": _authored("Patient explainer"),
         "position": {"x": 0, "y": 120}},
        {"id": "out", "kind": "output", "label": "Explanation",
         "config": {"body_key": "markdown_body",
                    **({"source": source} if source is not None else {})},
         "position": {"x": 0, "y": 260}},
    ]
    edges = [
        {"id": "e1", "source": "seed", "source_port": "out", "target": "writer"},
        {"id": "e2", "source": "writer", "source_port": "out", "target": "out"},
    ]
    if second_agent:
        nodes.insert(2, {"id": "editor", "kind": "agent", "label": "Editor",
                         "config": _authored("Careful editor"),
                         "position": {"x": 200, "y": 120}})
        edges.append({"id": "e3", "source": "seed", "source_port": "out", "target": "editor"})
        edges.append({"id": "e4", "source": "editor", "source_port": "out", "target": "out"})
    return BuilderDocument.model_validate({
        "schema": "builder.flow/v1", "id": "ug_0123abcd", "version": 1,
        "name": "output source", "input_field": "topic",
        "nodes": nodes, "edges": edges,
        **({"joins": {"out": "all"}} if second_agent else {}),
    })


def _output_with(document: BuilderDocument) -> dict:
    definition = compile_document(document).definition
    method = next(m for name, m in definition["methods"].items() if name.endswith("_out"))
    return method["do"]["with"]


class OutputSourceDefaultTests(unittest.TestCase):
    def test_an_unset_source_follows_the_one_incoming_edge(self) -> None:
        """The defect, in one assertion. Before the fix this was `None`."""

        self.assertEqual("${state.out__writer}", _output_with(_document())["source"])

    def test_an_explicit_source_still_wins(self) -> None:
        """An author who names one means it.

        The default exists because an unset field meant nothing; it must not
        start overriding a field somebody set.
        """

        with_block = _output_with(_document(source="${state.out__writer}"))
        self.assertEqual("${state.out__writer}", with_block["source"])

    def test_two_predecessors_give_an_ordered_list_not_a_guess(self) -> None:
        """Where the answer is ambiguous, the compiler does not pick one.

        `_inbound_source` is the same function the gate and the router already
        use, so all three read a graph's edges one way rather than three. Several
        predecessors give an ordered list the runtime resolves last-with-a-value
        — it does not silently choose the first, which would make a join's result
        depend on edge order.
        """

        source = _output_with(_document(second_agent=True))["source"]
        self.assertIsInstance(source, list)
        self.assertEqual(
            ["${state.out__writer}", "${state.out__editor}"],
            source,
        )

    def test_the_body_key_is_still_a_result_body_key(self) -> None:
        """The neighbouring guarantee, so this fix cannot quietly break it.

        `RUN_RESULT_BODY_KEYS` is what gets `MAX_RUN_RESULT_BODY_CHARS` instead
        of the streaming frame's 4 KiB clip — the mechanism by which the FIRST
        paid run's report was lost mid-sentence.
        """

        from brief_crew.config import RUN_RESULT_BODY_KEYS

        self.assertIn(_output_with(_document())["body_key"], RUN_RESULT_BODY_KEYS)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
