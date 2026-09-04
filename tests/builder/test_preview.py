"""The code preview - 09 D8, criterion 9.

Two renderings and one promise. The YAML must be the literal thing the runtime
loads, so it is round-tripped through `FlowDefinition.model_validate` rather
than eyeballed; the Python must be a reading aid, so it names the constructors
the entrypoint will build and says on its last line that it is not the program.

The promise is that no secret reaches either one, and it is tested the only way
worth testing it: a real credential is sealed into a real vault with a SENTINEL
value, the preview is rendered for a document that names its id, and the whole
page is searched for the sentinel. A test that only checked for the string
`<credential:` would pass over a renderer that printed both.

No cost: this compiles documents and formats strings. No network, no model, and
the one credential it creates never leaves an in-memory SQLite database.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timezone
from typing import Any

import yaml
from crewai.flow.flow_definition import FlowDefinition

from brief_crew.builder.compiler import compile_document
from brief_crew.builder.document import BuilderDocument
from brief_crew.builder.preview import PREVIEW_BANNER, render_preview
from brief_crew.service.credentials import CredentialStore
from brief_crew.service.persistence import PostgresFlowPersistence
from tests.builder.test_compiler import (
    AUTHORED_MODEL,
    attach_edge,
    authored_agent_node,
    authored_crew_node,
    crew_node,
    input_node,
    member_edge,
    output_node,
    straight_line,
    tool_node,
)
from tests.builder.test_document import document, edge, node

#: The value the vault seals. If this string ever appears in a preview, the
#: renderer has read a key - which is the one thing it must be unable to do.
SENTINEL = "sk-do-not-print-me-2f9a41c7"
ALICE = "user_alice"


def authored_graph(credential_id: str | None = None) -> BuilderDocument:
    agent: dict[str, Any] = {}
    if credential_id:
        agent["credential_id"] = credential_id
    return document(
        [
            input_node(),
            authored_agent_node("draft", **agent),
            tool_node(),
            output_node("report", source="${state.out__draft}"),
        ],
        [
            edge("e1", "idea", "draft"),
            edge("e2", "draft", "report"),
            attach_edge("a1", "search", "draft"),
        ],
    )


def crew_graph() -> BuilderDocument:
    return document(
        [
            input_node(),
            authored_crew_node("team", task_order=("writer", "editor")),
            authored_agent_node("writer"),
            authored_agent_node("editor"),
            output_node("report", source="${state.out__team}"),
        ],
        [
            edge("e1", "idea", "team"),
            edge("e2", "team", "report"),
            member_edge("m1", "writer", "team"),
            member_edge("m2", "editor", "team"),
        ],
    )


def preview_of(graph: BuilderDocument, **kwargs: Any) -> Any:
    return render_preview(
        compile_document(graph, **kwargs.pop("compile_with", {})),
        document_version=graph.version,
        generated_at=datetime(2026, 9, 4, tzinfo=timezone.utc),
        **kwargs,
    )


class YamlPreviewTests(unittest.TestCase):
    """The YAML is the definition, not a description of it."""

    def test_the_yaml_round_trips_through_flow_definition(self) -> None:
        for name, graph in (
            ("authored", authored_graph()),
            ("crew", crew_graph()),
            ("library", straight_line()),
        ):
            with self.subTest(graph=name):
                preview = preview_of(graph)
                FlowDefinition.model_validate(yaml.safe_load(preview.yaml))

    def test_the_yaml_is_the_definition_it_was_given(self) -> None:
        preview = preview_of(authored_graph())
        self.assertEqual(yaml.safe_load(preview.yaml), preview.definition)

    def test_the_generated_at_is_the_callers_to_pin(self) -> None:
        """The same seam `as_budget(compiled_at=...)` has, for the same reason.

        A caller comparing two previews byte for byte must be able to fix it,
        and a normalisation step that stripped the field would be a field the
        test stopped checking.
        """

        preview = preview_of(authored_graph())
        self.assertEqual(preview.generated_at, datetime(2026, 9, 4, tzinfo=timezone.utc))
        self.assertEqual(preview.document_version, 1)


class PythonPreviewTests(unittest.TestCase):
    def test_one_agent_per_authored_agent(self) -> None:
        python = preview_of(authored_graph()).python
        self.assertEqual(python.count("= Agent("), 1)
        self.assertEqual(python.count("= Task("), 1)
        self.assertEqual(python.count("= LLM("), 1)

    def test_one_crew_per_crew(self) -> None:
        """Plus the single-agent `Crew` each authored agent step really is.

        `run_agent` wraps one agent and one task in a `Crew` because that is
        what `kickoff` takes, so a preview that stopped at the `Task` would be
        a program that does not run.
        """

        python = preview_of(crew_graph()).python
        self.assertEqual(python.count("team = Crew("), 1)
        self.assertEqual(python.count("= Agent("), 2)
        self.assertEqual(python.count("= Task("), 2)
        # The members are inside their crew, so neither gets a wrapper.
        self.assertEqual(python.count("= Crew("), 1)

    def test_the_authored_agents_own_wrapper_crew_is_rendered(self) -> None:
        python = preview_of(authored_graph()).python
        self.assertIn("draft_crew = Crew(", python)

    def test_the_task_order_is_the_order_the_tasks_are_listed_in(self) -> None:
        python = preview_of(crew_graph()).python
        self.assertIn("tasks=[writer_task, editor_task]", python)

    def test_the_authors_own_prompt_is_what_is_rendered(self) -> None:
        python = preview_of(authored_graph()).python
        self.assertIn("role='draft specialist'", python)
        self.assertIn(f"model='{AUTHORED_MODEL}'", python)

    def test_a_registered_agent_is_NAMED_and_never_rendered(self) -> None:
        """This repository's prompts live in YAML and the platform rule keeps
        them there - printing them here would make the preview a second place
        they live, which is the exact thing an authored node exists to avoid."""

        python = preview_of(straight_line()).python
        self.assertIn("registered_agent(", python)
        self.assertIn("'scoper'", python)
        self.assertNotIn("= Agent(", python)

    def test_a_registered_crew_says_why_its_tier_chooses_nothing(self) -> None:
        graph = document(
            [
                input_node(),
                crew_node("scope_crew"),
                output_node("report", source="${state.out__scope_crew}"),
            ],
            [edge("e1", "idea", "scope_crew"), edge("e2", "scope_crew", "report")],
        )
        python = preview_of(graph).python
        self.assertIn("registered_crew('scope'", python)
        self.assertIn("decision 12", python)

    def test_the_banner_is_the_last_thing_in_the_file(self) -> None:
        python = preview_of(authored_graph()).python
        self.assertTrue(python.rstrip().endswith(PREVIEW_BANNER.rstrip()))
        self.assertIn("reading aid", python)

    def test_no_python_is_evaluated_to_produce_it(self) -> None:
        """A rendering, not an execution. The proof is that a document naming a
        model this deployment cannot reach still renders."""

        graph = authored_graph()
        python = preview_of(graph).python
        self.assertIn("Agent(", python)


class SecretTests(unittest.TestCase):
    """The one promise: a credential reference, never a credential."""

    def setUp(self) -> None:
        self.persistence = PostgresFlowPersistence("sqlite+pysqlite:///:memory:")
        self.addCleanup(self.persistence.close)
        self.store = CredentialStore(self.persistence)
        self.credential = self.store.create(
            ALICE, kind="openrouter", label="Alice's key", fields={"api_key": SENTINEL}
        )

    def _preview(self) -> Any:
        graph = authored_graph(self.credential.id)
        return render_preview(
            compile_document(
                graph, credential_check=lambda cid: self.store.exists(ALICE, cid)
            ),
            document_version=graph.version,
            credential_label=lambda cid: self.store.get(ALICE, cid).label,
            generated_at=datetime(2026, 9, 4, tzinfo=timezone.utc),
        )

    def test_the_sentinel_is_absent_from_every_rendering(self) -> None:
        preview = self._preview()
        for name, rendered in (
            ("yaml", preview.yaml),
            ("python", preview.python),
            ("definition", str(preview.definition)),
        ):
            with self.subTest(rendering=name):
                self.assertNotIn(SENTINEL, rendered)

    def test_the_reference_is_rendered_with_the_credentials_label(self) -> None:
        python = self._preview().python
        self.assertIn("<credential: Alice's key>", python)

    def test_the_definition_still_carries_the_opaque_id(self) -> None:
        preview = self._preview()
        self.assertIn(self.credential.id, preview.yaml)

    def test_the_renderer_holds_a_labeller_and_not_a_vault(self) -> None:
        """There is no path from the preview module to a secret, even by
        accident: what it is given is a function from id to label."""

        import inspect

        from brief_crew.builder import preview as preview_module

        source = inspect.getsource(preview_module)
        for forbidden in ("resolve_credential", "CredentialStore", "api_key\"]"):
            with self.subTest(name=forbidden):
                self.assertNotIn(forbidden, source)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
