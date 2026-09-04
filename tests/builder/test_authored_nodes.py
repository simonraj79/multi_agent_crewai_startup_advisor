"""The two union arms - 03-node-library.md D3, criterion 2.

`AgentConfig` and `CrewConfig` stopped being models on 2026-09-04 and became
unions discriminated by PRESENCE: a **library** node names one of this
deployment's registered ids and carries no prose, an **authored** node carries
the prompt itself. What this module pins is the seam between them, and it pins
three things a reader of the schema would not otherwise be able to check:

1. **Both-or-neither is refused at parse, and the message names BOTH fields.**
   That is the criterion's own wording and it is not decoration - the sentence
   is what an author is shown, and "validation error" over a node they cannot
   see the shape of is the failure this replaces. A node naming both is two
   agents in one box; a node naming neither has no prompt from either source.

2. **The deprecation ruling is enforced by absence.** `BuilderModel` is
   `extra="forbid"`, so `multimodal` and `function_calling_llm` being cut and
   `reasoning` / `max_reasoning_attempts` being replaced are all one testable
   fact: sending any of the four is a 422 naming the key. That is a stronger
   guarantee than "the field is not rendered", which is what a form-level cut
   would have given.

3. **The two arms do not leak into each other.** An authored agent has no
   `agent_id` and a library one has no `role`, and every consumer that reads
   one of those attributes narrows to the arm rather than to the union -
   `library_problems`, the compiler's dispatch and `budget._calls_for` all do,
   and the assertions below are what stop that quietly reverting to the union.

No cost: this parses dicts. No network, no model, no credential.
"""

from __future__ import annotations

import unittest

from pydantic import ValidationError

from brief_crew.builder import (
    AgentConfig,
    AuthoredAgentConfig,
    AuthoredCrewConfig,
    BuilderDocument,
    BuilderNode,
    CrewConfig,
    FlowStateSchema,
    LibraryAgentConfig,
    LibraryCrewConfig,
)
from brief_crew.builder.document import _TARGET_PORTS_BY_KIND
from brief_crew.config import (
    BUILDER_MAX_NODE_RETRIES,
    BUILDER_MAX_PROMPT_CHARS,
    MAX_RUN_INPUT_KEYS,
)
from tests.builder.test_document import BODY_KEY, DOCUMENT_ID, node


ESCALATION_MODEL_SLUG = "google/gemini-3.8-flash"


def authored_agent_config(**overrides: object) -> dict[str, object]:
    """The smallest authored agent that parses: five essentials and a tier."""

    config: dict[str, object] = {
        "tier": "escalation",
        "role": "Market analyst",
        "goal": "Find who already sells this",
        "backstory": "You have priced twenty categories and been wrong about three.",
        "task": {
            "description": "Research the market for ${state.idea}",
            "expected_output": "Three competitors with URLs",
        },
        "llm": {"model": ESCALATION_MODEL_SLUG},
    }
    config.update(overrides)
    return config


def authored_crew_config(**overrides: object) -> dict[str, object]:
    config: dict[str, object] = {"tier": "cheap", "process": "sequential"}
    config.update(overrides)
    return config


def agent(node_id: str = "analyst", **overrides: object) -> dict[str, object]:
    return node(node_id, "agent", authored_agent_config(**overrides))


def crew(node_id: str = "team", **overrides: object) -> dict[str, object]:
    return node(node_id, "crew", authored_crew_config(**overrides))


class BothOrNeitherTests(unittest.TestCase):
    """Criterion 2's sentence, for both kinds and in both directions."""

    def test_an_agent_naming_both_agent_id_and_role_is_refused_by_name(self) -> None:
        with self.assertRaises(ValidationError) as caught:
            BuilderNode.model_validate(agent(agent_id="scoper"))
        message = str(caught.exception)
        self.assertIn("agent_id", message)
        self.assertIn("role", message)

    def test_an_agent_naming_neither_is_refused_by_name(self) -> None:
        with self.assertRaises(ValidationError) as caught:
            BuilderNode.model_validate(node("a", "agent", {"tier": "cheap"}))
        message = str(caught.exception)
        self.assertIn("agent_id", message)
        self.assertIn("role", message)

    def test_a_crew_naming_both_crew_id_and_process_is_refused_by_name(self) -> None:
        with self.assertRaises(ValidationError) as caught:
            BuilderNode.model_validate(crew(crew_id="scope"))
        message = str(caught.exception)
        self.assertIn("crew_id", message)
        self.assertIn("process", message)

    def test_a_crew_naming_neither_is_refused_by_name(self) -> None:
        with self.assertRaises(ValidationError) as caught:
            BuilderNode.model_validate(node("c", "crew", {"tier": "cheap"}))
        message = str(caught.exception)
        self.assertIn("crew_id", message)
        self.assertIn("process", message)

    def test_each_alone_parses_to_its_own_arm(self) -> None:
        library = BuilderNode.model_validate(
            node("a", "agent", {"tier": "cheap", "agent_id": "scoper"})
        )
        authored = BuilderNode.model_validate(agent())
        self.assertIsInstance(library.config, LibraryAgentConfig)
        self.assertIsInstance(authored.config, AuthoredAgentConfig)

        library_crew = BuilderNode.model_validate(
            node("c", "crew", {"tier": "cheap", "crew_id": "scope"})
        )
        authored_crew = BuilderNode.model_validate(crew())
        self.assertIsInstance(library_crew.config, LibraryCrewConfig)
        self.assertIsInstance(authored_crew.config, AuthoredCrewConfig)

    def test_both_arms_are_the_union_and_isinstance_still_answers_yes(self) -> None:
        """Every consumer outside `document.py` narrows on the union alias."""

        for raw in (node("a", "agent", {"tier": "cheap", "agent_id": "scoper"}), agent()):
            self.assertIsInstance(BuilderNode.model_validate(raw).config, AgentConfig)
        for raw in (node("c", "crew", {"tier": "cheap", "crew_id": "scope"}), crew()):
            self.assertIsInstance(BuilderNode.model_validate(raw).config, CrewConfig)

    def test_the_arms_do_not_leak_each_others_fields(self) -> None:
        authored = BuilderNode.model_validate(agent()).config
        self.assertFalse(hasattr(authored, "agent_id"))
        self.assertFalse(hasattr(authored, "tools"))
        library = BuilderNode.model_validate(
            node("a", "agent", {"tier": "cheap", "agent_id": "scoper"})
        ).config
        self.assertFalse(hasattr(library, "role"))
        self.assertFalse(hasattr(library, "llm"))


class DeprecationRulingTests(unittest.TestCase):
    """00's S9 ruling, enforced by `extra="forbid"` rather than by a form."""

    def test_the_two_cut_fields_are_refused_by_name(self) -> None:
        for cut in ("multimodal", "function_calling_llm"):
            with self.subTest(field=cut):
                with self.assertRaises(ValidationError) as caught:
                    BuilderNode.model_validate(agent(**{cut: True}))
                self.assertIn(cut, str(caught.exception))

    def test_the_two_replaced_fields_are_refused_by_name(self) -> None:
        for replaced, value in (("reasoning", True), ("max_reasoning_attempts", 2)):
            with self.subTest(field=replaced):
                with self.assertRaises(ValidationError) as caught:
                    BuilderNode.model_validate(agent(**{replaced: value}))
                self.assertIn(replaced, str(caught.exception))

    def test_planning_and_four_of_planning_configs_eleven_fields_replace_them(self) -> None:
        parsed = BuilderNode.model_validate(
            agent(
                planning=True,
                planning_config={
                    "reasoning_effort": "high",
                    "max_attempts": 2,
                    "max_steps": 5,
                    "max_replans": 1,
                },
            )
        )
        config = parsed.config
        assert isinstance(config, AuthoredAgentConfig)
        assert config.planning_config is not None
        self.assertTrue(config.planning)
        self.assertEqual(config.planning_config.reasoning_effort, "high")
        self.assertEqual(
            sorted(type(config.planning_config).model_fields),
            ["max_attempts", "max_replans", "max_steps", "reasoning_effort"],
        )

    def test_the_seven_excluded_planning_fields_are_refused_by_name(self) -> None:
        for excluded in (
            "llm",
            "system_prompt",
            "plan_prompt",
            "refine_prompt",
            "max_step_iterations",
            "observe_steps",
            "step_timeout",
        ):
            with self.subTest(field=excluded):
                with self.assertRaises(ValidationError) as caught:
                    BuilderNode.model_validate(
                        agent(planning=True, planning_config={excluded: 1})
                    )
                self.assertIn(excluded, str(caught.exception))

    def test_planning_config_without_planning_configures_nothing_and_says_so(self) -> None:
        with self.assertRaises(ValidationError) as caught:
            BuilderNode.model_validate(agent(planning_config={"max_steps": 4}))
        self.assertIn("planning", str(caught.exception))

    def test_task_max_retries_is_not_a_field_and_guardrail_max_retries_is(self) -> None:
        """The name collision FD5 warns about, asserted rather than commented."""

        with self.assertRaises(ValidationError) as caught:
            BuilderNode.model_validate(agent(task={"max_retries": 2}))
        self.assertIn("max_retries", str(caught.exception))
        parsed = BuilderNode.model_validate(agent(guardrail_max_retries=1))
        self.assertEqual(parsed.config.guardrail_max_retries, 1)

    def test_the_builders_own_retry_is_a_separate_object_at_node_level(self) -> None:
        parsed = BuilderNode.model_validate(
            agent(retry={"max_retries": BUILDER_MAX_NODE_RETRIES, "backoff_seconds": 5})
        )
        config = parsed.config
        assert isinstance(config, AuthoredAgentConfig)
        self.assertEqual(config.retry.max_retries, BUILDER_MAX_NODE_RETRIES)
        with self.assertRaises(ValidationError):
            BuilderNode.model_validate(
                agent(retry={"max_retries": BUILDER_MAX_NODE_RETRIES + 1})
            )


class AuthoredAgentFieldTests(unittest.TestCase):
    def test_a_prompt_field_is_bounded_and_may_not_be_empty(self) -> None:
        BuilderNode.model_validate(agent(role="r" * BUILDER_MAX_PROMPT_CHARS))
        with self.assertRaises(ValidationError):
            BuilderNode.model_validate(agent(role="r" * (BUILDER_MAX_PROMPT_CHARS + 1)))
        with self.assertRaises(ValidationError):
            BuilderNode.model_validate(agent(role=""))

    def test_the_llm_block_carries_eleven_leaves_and_not_stream(self) -> None:
        from brief_crew.builder import LlmConfig

        self.assertEqual(
            sorted(LlmConfig.model_fields),
            [
                "frequency_penalty",
                "max_tokens",
                "model",
                "presence_penalty",
                "reasoning_effort",
                "response_format",
                "seed",
                "stop",
                "temperature",
                "timeout",
                "top_p",
            ],
        )
        with self.assertRaises(ValidationError) as caught:
            BuilderNode.model_validate(
                agent(llm={"model": ESCALATION_MODEL_SLUG, "stream": True})
            )
        self.assertIn("stream", str(caught.exception))

    def test_the_llm_ranges_are_the_apis_own(self) -> None:
        BuilderNode.model_validate(agent(llm={"model": "m", "temperature": 2.0}))
        with self.assertRaises(ValidationError):
            BuilderNode.model_validate(agent(llm={"model": "m", "temperature": 2.1}))
        with self.assertRaises(ValidationError):
            BuilderNode.model_validate(agent(llm={"model": "m", "top_p": 1.5}))
        with self.assertRaises(ValidationError):
            BuilderNode.model_validate(
                agent(llm={"model": "m", "stop": ["a", "b", "c", "d", "e"]})
            )

    def test_a_task_output_schema_is_a_flat_map_of_scalar_types(self) -> None:
        parsed = BuilderNode.model_validate(
            agent(
                task={
                    "description": "d",
                    "expected_output": "e",
                    "output_schema": {"segment": "string", "score": "number"},
                }
            )
        )
        config = parsed.config
        assert isinstance(config, AuthoredAgentConfig)
        self.assertEqual(config.task.output_schema, {"segment": "string", "score": "number"})
        with self.assertRaises(ValidationError):
            BuilderNode.model_validate(
                agent(task={"description": "d", "expected_output": "e",
                            "output_schema": {"nested": {"a": "string"}}})
            )

    def test_prompt_inputs_keep_the_state_ref_discipline(self) -> None:
        BuilderNode.model_validate(agent(prompt_inputs={"idea": "${state.idea}"}))
        with self.assertRaises(ValidationError) as caught:
            BuilderNode.model_validate(
                agent(prompt_inputs={"idea": "${state.out__scoper.segment}"})
            )
        self.assertIn("state reference", str(caught.exception))


class AuthoredCrewFieldTests(unittest.TestCase):
    def test_a_hierarchical_crew_with_no_manager_is_refused_where_crewai_would_raise(self) -> None:
        with self.assertRaises(ValidationError) as caught:
            BuilderNode.model_validate(crew(process="hierarchical"))
        message = str(caught.exception)
        self.assertIn("manager_llm", message)
        self.assertIn("manager_agent", message)

    def test_a_hierarchical_crew_with_either_manager_parses(self) -> None:
        for manager in ({"manager_agent": "boss"}, {"manager_llm": {"model": "m"}}):
            with self.subTest(manager=sorted(manager)[0]):
                parsed = BuilderNode.model_validate(crew(process="hierarchical", **manager))
                self.assertIsInstance(parsed.config, AuthoredCrewConfig)

    def test_a_sequential_crew_may_not_configure_a_manager(self) -> None:
        with self.assertRaises(ValidationError):
            BuilderNode.model_validate(crew(manager_agent="boss"))

    def test_the_fifteenth_field_is_verbose(self) -> None:
        """00's S9 ruling, asserted so it cannot be dropped by the next edit."""

        self.assertIn("verbose", AuthoredCrewConfig.model_fields)
        parsed = BuilderNode.model_validate(crew(verbose=True))
        config = parsed.config
        assert isinstance(config, AuthoredCrewConfig)
        self.assertTrue(config.verbose)

    def test_membership_is_edges_and_task_order_is_the_only_list_stored(self) -> None:
        self.assertNotIn("members", AuthoredCrewConfig.model_fields)
        self.assertIn("task_order", AuthoredCrewConfig.model_fields)
        parsed = BuilderNode.model_validate(crew(task_order=["a", "b"]))
        config = parsed.config
        assert isinstance(config, AuthoredCrewConfig)
        self.assertEqual(config.task_order, ("a", "b"))


class ErrorPortTests(unittest.TestCase):
    """`on_error` is the one config field that changes a node's port list."""

    def test_a_billable_node_grows_an_error_port_only_when_it_routes(self) -> None:
        for kind, raw in (
            ("library agent", node("a", "agent", {"tier": "cheap", "agent_id": "scoper"})),
            ("authored agent", agent()),
            ("library crew", node("c", "crew", {"tier": "cheap", "crew_id": "scope"})),
            ("authored crew", crew()),
        ):
            with self.subTest(kind=kind):
                plain = BuilderNode.model_validate(raw)
                self.assertEqual(plain.out_ports, ("out",))
                routed = BuilderNode.model_validate(
                    {**raw, "config": {**raw["config"], "on_error": "route"}}
                )
                self.assertEqual(routed.out_ports, ("out", "error"))

    def test_a_non_billable_kind_has_no_such_field_to_set(self) -> None:
        with self.assertRaises(ValidationError):
            BuilderNode.model_validate(
                node("t", "transform", {"op": "pick", "on_error": "route"})
            )

    def test_an_unknown_policy_is_refused(self) -> None:
        with self.assertRaises(ValidationError):
            BuilderNode.model_validate(agent(on_error="retry"))


class TargetPortTableTests(unittest.TestCase):
    """D1's target-port column, which `GET /api/builder/vocabulary` publishes."""

    def test_every_kind_has_a_row_and_the_table_is_d1s(self) -> None:
        self.assertEqual(
            _TARGET_PORTS_BY_KIND,
            {
                "input": (),
                "agent": ("in", "attach"),
                "crew": ("in", "attach", "member"),
                "gate": ("in",),
                "router": ("in",),
                "transform": ("in",),
                "output": ("in",),
                "tool": (),
                "mcp": (),
                "skill": (),
            },
        )

    def test_a_node_reports_its_own_row(self) -> None:
        self.assertEqual(BuilderNode.model_validate(crew()).target_ports, ("in", "attach", "member"))
        self.assertEqual(BuilderNode.model_validate(agent()).target_ports, ("in", "attach"))


class DocumentStateTests(unittest.TestCase):
    """`BuilderDocument.state` - D3's new document-level field."""

    def _document(self, **extra: object) -> dict[str, object]:
        return {
            "schema": BuilderDocument.model_fields["document_schema"].default,
            "id": DOCUMENT_ID,
            "name": "authored",
            "version": 1,
            "input_field": "idea",
            "nodes": [
                node("idea", "input", {"field": "idea"}),
                node("report", "output", {"body_key": BODY_KEY}),
            ],
            "edges": [
                {"id": "e1", "source": "idea", "target": "report", "source_port": "out"}
            ],
            **extra,
        }

    def test_a_document_with_no_state_key_keeps_none(self) -> None:
        parsed = BuilderDocument.model_validate(self._document())
        self.assertIsNone(parsed.state)
        self.assertNotIn("state", self._document())

    def test_a_declared_state_field_carries_a_type_and_an_optional_default(self) -> None:
        parsed = BuilderDocument.model_validate(
            self._document(
                state={"fields": {"decision": {"type": "string", "default": "approve"}}}
            )
        )
        assert parsed.state is not None
        self.assertEqual(parsed.state.fields["decision"].type, "string")
        self.assertEqual(parsed.state.fields["decision"].default, "approve")

    def test_a_non_scalar_state_type_is_refused(self) -> None:
        with self.assertRaises(ValidationError):
            BuilderDocument.model_validate(
                self._document(state={"fields": {"decision": {"type": "object"}}})
            )

    def test_the_state_key_ceiling_is_the_run_requests_own(self) -> None:
        fields = {f"k{index}": {"type": "string"} for index in range(MAX_RUN_INPUT_KEYS)}
        FlowStateSchema.model_validate({"fields": fields})
        fields["one_too_many"] = {"type": "string"}
        with self.assertRaises(ValidationError) as caught:
            FlowStateSchema.model_validate({"fields": fields})
        self.assertIn("MAX_RUN_INPUT_KEYS", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
