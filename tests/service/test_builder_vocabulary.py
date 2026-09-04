"""`GET /api/builder/vocabulary` against contract C2 - plan 03 criterion 5.

Three claims, and the third is the one this file exists for.

**It matches the C2 shape.** Every key the contract names is present and typed
as the contract types it, checked against the response body rather than against
the pydantic model - a client reads JSON, and a field the model declares but
FastAPI drops is a field the palette never sees.

**It is unauthenticated.** `get_vocabulary` carries no `Depends(current_user)`
on purpose: it describes this BUILD, not anybody's data, and it has to resolve
before the console's three-phase auth gate does or the palette is disabled for
the whole of a sign-in. Asserted against an app with auth REQUIRED, because on
an app with auth off every endpoint answers 200 and the test would prove
nothing.

**Every list equals its owning source, byte for byte.** This is the criterion's
own wording and it is the reason the endpoint exists at all. Until 2026-09-04
`node_kinds` was a seven-element LITERAL in the handler while `document.py`
already declared ten - so the one endpoint whose whole job is to stop the client
and the server drifting had drifted inside itself, and the palette drew seven
tiles. Each assertion below reads the owning constant at run time rather than
transcribing it, so the same thing cannot happen twice.

`models` and `tools` are the two C2 keys this build does NOT serve. Their owning
sources - the model registry (C3, plan 05) and the tool catalogue (06) - do not
exist yet, and C2's own rule is that both are served verbatim from those
sources. Serving `[]` would say "this deployment has no models", which is false;
the absence is what `types/builder.ts` already reads as "the server has not got
there yet". `test_the_two_keys_this_build_cannot_serve_are_absent_not_empty`
pins that as a decision so it reads as one.

No cost: this builds a synthetic app over an in-memory SQLite and does one GET.
"""

from __future__ import annotations

import typing
import unittest

from brief_crew import config as project_config
from brief_crew.builder.document import (
    ATTACHMENT_KINDS,
    NodeKind,
    Tier,
    _TARGET_PORTS_BY_KIND,
)
from brief_crew.builder.runtime import BUILDABLE_BUILDER_CREW_IDS, BUILDER_AGENT_LIBRARY
from tests.service.builder_auth import BuilderAuthCase

try:  # pragma: no cover - the service extra is optional, as elsewhere in tests/
    from fastapi.testclient import TestClient  # noqa: F401

    FASTAPI_AVAILABLE = True
except Exception:  # pragma: no cover
    FASTAPI_AVAILABLE = False


@unittest.skipUnless(FASTAPI_AVAILABLE, "FastAPI service extra is not installed")
class VocabularyShapeTests(unittest.TestCase):
    def setUp(self) -> None:
        from fastapi.testclient import TestClient

        from brief_crew.service.app import create_app

        self.app = create_app(synthetic=True, database_url="sqlite+pysqlite:///:memory:")
        self.client = TestClient(self.app, raise_server_exceptions=False)
        self.addCleanup(self.client.close)
        response = self.client.get("/api/builder/vocabulary")
        self.assertEqual(response.status_code, 200, response.text)
        self.payload = response.json()

    # ---------------------------------------------------------------- shape
    def test_it_carries_every_key_c2_names_that_this_build_can_answer(self) -> None:
        self.assertEqual(
            sorted(self.payload),
            sorted(
                [
                    "schema_id",
                    "node_kinds",
                    "attachment_kinds",
                    "target_ports",
                    "tiers",
                    "tier_models",
                    "agent_ids",
                    "crew_ids",
                    "research_tools",
                    "transform_ops",
                    "router_comparisons",
                    "router_otherwise",
                    "result_body_keys",
                    "problem_codes",
                    "warning_codes",
                    "bounds",
                ]
            ),
        )

    def test_the_two_keys_this_build_cannot_serve_are_absent_not_empty(self) -> None:
        """A DECISION: `models` is 05's and `tools` is 06's, verbatim or not at all.

        An empty list would say this deployment has no models and no tools,
        which is false. `types/builder.ts` already reads the absence as "the
        server has not got there yet" and renders no sub-list, which is cut-list
        item 17 applied honestly.
        """

        self.assertNotIn("models", self.payload)
        self.assertNotIn("tools", self.payload)

    def test_the_schema_id_is_the_one_this_service_actually_compiles(self) -> None:
        """Derived, never a literal: the client refuses a mismatch outright."""

        self.assertEqual(self.payload["schema_id"], project_config.BUILDER_DOCUMENT_SCHEMA)

    # -------------------------------------------------- byte-for-byte sources
    def test_node_kinds_is_the_NodeKind_union_in_declaration_order(self) -> None:
        """The one that was WRONG until 2026-09-04, as a seven-item literal."""

        self.assertEqual(self.payload["node_kinds"], list(typing.get_args(NodeKind)))
        self.assertEqual(len(self.payload["node_kinds"]), 10)

    def test_attachment_kinds_is_the_declared_partition_and_a_real_subset(self) -> None:
        self.assertEqual(set(self.payload["attachment_kinds"]), set(ATTACHMENT_KINDS))
        for kind in self.payload["attachment_kinds"]:
            self.assertIn(kind, self.payload["node_kinds"])

    def test_target_ports_is_d1s_table_with_a_row_for_every_kind(self) -> None:
        self.assertEqual(
            self.payload["target_ports"],
            {kind: list(ports) for kind, ports in _TARGET_PORTS_BY_KIND.items()},
        )
        self.assertEqual(sorted(self.payload["target_ports"]), sorted(self.payload["node_kinds"]))

    def test_tiers_is_the_Tier_union_and_tier_models_names_both(self) -> None:
        self.assertEqual(self.payload["tiers"], list(typing.get_args(Tier)))
        self.assertEqual(sorted(self.payload["tier_models"]), sorted(self.payload["tiers"]))

    def test_tier_models_are_registry_slugs_with_no_prefix_and_no_variant(self) -> None:
        """C3 keys on the bare slug; `config.py` carries `openrouter/...:nitro`."""

        for tier, slug in self.payload["tier_models"].items():
            with self.subTest(tier=tier):
                self.assertNotIn("openrouter/", slug)
                self.assertNotIn(":", slug)
        source = {
            "cheap": project_config.CHEAP_MODEL,
            "escalation": project_config.ESCALATION_MODEL,
        }
        for tier, model in source.items():
            self.assertIn(self.payload["tier_models"][tier], model)

    def test_agent_ids_and_crew_ids_are_the_registries_own(self) -> None:
        self.assertEqual(self.payload["agent_ids"], sorted(BUILDER_AGENT_LIBRARY))
        self.assertEqual(self.payload["crew_ids"], sorted(BUILDABLE_BUILDER_CREW_IDS))

    def test_the_four_config_owned_lists_are_config_pys_own(self) -> None:
        for key, source in (
            ("research_tools", project_config.BUILDER_RESEARCH_TOOLS),
            ("transform_ops", project_config.BUILDER_TRANSFORM_OPS),
            ("router_comparisons", project_config.BUILDER_ROUTER_COMPARISONS),
        ):
            with self.subTest(key=key):
                self.assertEqual(self.payload[key], sorted(source))
        self.assertEqual(
            self.payload["result_body_keys"], list(project_config.RUN_RESULT_BODY_KEYS)
        )
        self.assertEqual(
            self.payload["router_otherwise"], project_config.BUILDER_ROUTER_OTHERWISE
        )

    def test_problem_codes_equal_the_three_declaring_modules_exactly(self) -> None:
        """The same set `test_problem_code_declarations.py` holds the client to.

        Read here by the frontend's own grep - the shape a code must be written
        in for the mirror to see it - rather than by importing the constants, so
        this is an independent measurement of the same claim and not the same
        code twice.
        """

        import pathlib
        import re

        pattern = re.compile(r'^([A-Z][A-Z0-9_]*) = "([a-z]+(?:-[a-z]+)+)"$', re.MULTILINE)
        builder = pathlib.Path(__file__).resolve().parents[2] / "src" / "brief_crew" / "builder"
        declared: set[str] = set()
        for name in ("bounds.py", "budget.py", "compiler.py"):
            declared |= {
                match.group(2)
                for match in pattern.finditer((builder / name).read_text(encoding="utf-8"))
            }
        self.assertEqual(self.payload["problem_codes"], sorted(declared))

    def test_every_warning_code_is_also_a_problem_code(self) -> None:
        for code in self.payload["warning_codes"]:
            self.assertIn(code, self.payload["problem_codes"])

    def test_the_warnings_are_the_four_sites_that_write_severity_warning(self) -> None:
        from brief_crew.builder import bounds as bounds_module

        self.assertEqual(
            self.payload["warning_codes"],
            sorted(
                [
                    bounds_module.ROUTER_BRANCH_UNCONNECTED,
                    bounds_module.NO_OUTPUT_NODE,
                    bounds_module.JOIN_SINGLE_PREDECESSOR,
                    bounds_module.ATTACHMENT_UNATTACHED,
                ]
            ),
        )

    # --------------------------------------------------------------- bounds
    def test_every_bound_is_the_constant_it_names(self) -> None:
        expected = {
            "max_graph_nodes": project_config.MAX_GRAPH_NODES,
            "max_billable_nodes": project_config.MAX_BILLABLE_NODES,
            "max_escalation_nodes": project_config.MAX_ESCALATION_NODES,
            "max_fanout_width": project_config.MAX_FANOUT_WIDTH,
            "min_router_branches": project_config.MIN_ROUTER_BRANCHES,
            "max_cycles": project_config.MAX_CYCLES,
            "max_cycle_iterations": project_config.MAX_CYCLE_ITERATIONS,
            "max_agent_iter": project_config.BUILDER_MAX_AGENT_ITER,
            "max_guardrail_retries": project_config.BUILDER_MAX_GUARDRAIL_RETRIES,
            "max_label_chars": project_config.BUILDER_MAX_LABEL_CHARS,
            "max_name_chars": project_config.BUILDER_MAX_NAME_CHARS,
            "max_gate_message_chars": project_config.BUILDER_MAX_GATE_MESSAGE_CHARS,
            "max_input_chars": project_config.MAX_RUN_INPUT_CHARS,
            "max_document_bytes": project_config.MAX_BUILDER_DOCUMENT_BYTES,
            "run_cost_ceiling_usd": project_config.MAX_RUN_COST_USD,
            "max_attachment_nodes": project_config.MAX_ATTACHMENT_NODES,
            "max_attachments_per_node": project_config.MAX_ATTACHMENTS_PER_NODE,
            "max_crew_members": project_config.MAX_CREW_MEMBERS,
            "max_prompt_chars": project_config.BUILDER_MAX_PROMPT_CHARS,
            "max_retries": project_config.BUILDER_MAX_NODE_RETRIES,
            "ceiling_usd_per_m_input": project_config.MODEL_PRICE_CEILING_IN,
        }
        self.assertEqual(self.payload["bounds"], {k: float(v) for k, v in expected.items()})

    def test_the_five_c2_v2_bounds_the_palette_had_nothing_to_read(self) -> None:
        """The client build's own finding: the counters had no source."""

        for key in (
            "max_attachment_nodes",
            "max_attachments_per_node",
            "max_crew_members",
            "max_prompt_chars",
            "max_retries",
        ):
            with self.subTest(bound=key):
                self.assertGreater(self.payload["bounds"][key], 0)


@unittest.skipUnless(FASTAPI_AVAILABLE, "FastAPI service extra is not installed")
class VocabularyIsUnauthenticatedTests(BuilderAuthCase):
    """Asserted against an app that REQUIRES auth, or it proves nothing.

    On a synthetic app with no auth server every route answers anonymously, so
    a 200 there is not evidence. `BuilderAuthCase` is the shape every other
    builder-route test uses - authentication on, `verify_token` stubbed - and it
    is what makes the control below meaningful.
    """

    def test_it_answers_200_with_no_bearer_token(self) -> None:
        response = self.client.get("/api/builder/vocabulary")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(response.json()["node_kinds"]), 10)

    def test_a_route_that_reads_data_still_refuses_the_same_caller(self) -> None:
        """The control: proves the auth gate is genuinely armed on this app."""

        response = self.client.get("/api/builder/workflows")
        self.assertEqual(response.status_code, 401, response.text)


if __name__ == "__main__":
    unittest.main()
