"""An exported document carries no secret, no owner and no id - plan 15 D1.

The property under test is the one the rubric's forbidden list names,
"credentials in exports", and it is asserted the only way that means anything:
a raw document carrying EVERY secret-bearing key shape from S1 ruling 6 -
`credential_id`, `*_credential_id`, `server_id`, `skill_id` - at every depth a
v2 node might put one, and a JSON rendering of the export that contains none of
their values. Not "the credential field is null" - that the *bytes* of the
values are absent from the file.

Over raw dicts on purpose. No committed document carries these keys today
(`AgentConfig.credential_id` lands with plan 01 on another branch), and a test
that waited for the schema would be a test written the day it was already too
late to be wrong about.

**And that is why `raw_document()` must not be the only fixture** (D-15-30).
It is deliberately ahead of the schema, so it does not parse - seven validation
errors against `BuilderDocument` at the time of writing - which means every
assertion here is about what the strip REMOVES and none of them is about
whether what it leaves can be read back. The whole of D-15-28 lived in that
gap: `mcp` and `skill` nodes exported 200 and could then be imported by
nobody, and this file's only test of the skill path asserted over a
`skill_name` sitting on an *agent* config, a field the schema did not have.
`RoundTripEveryKindTests` at the bottom closes it, over a document
`BuilderDocument` accepts, covering every kind in `NodeKind` and failing the
day an eleventh is added.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
import unittest

from brief_crew.builder.export import (
    EXPORT_DROPPED_KEYS,
    MASKED_PATH,
    export_content_disposition,
    export_envelope,
    export_filename,
    mask_url,
    strip_for_export,
)
from brief_crew.config import BUILDER_DOCUMENT_SCHEMA


# Every value below is a secret, an owner or an id that must not leave.
CRED_TOP = "cr_11111111"
CRED_LLM = "cr_22222222"
CRED_TOOL = "cr_33333333"
CRED_HEADER = "cr_44444444"
CRED_ENV = "cr_55555555"
SERVER = "mcp_66666666"
SKILL = "skill_77777777"
OWNER = "user_ada_owner"
DOCUMENT_ID = "ug_deadbeef"
URL_SECRET = "https://svc:hunter2@mcp.example.test:8443/v1/sse?token=abc123"
SECRETS = (
    CRED_TOP,
    CRED_LLM,
    CRED_TOOL,
    CRED_HEADER,
    CRED_ENV,
    SERVER,
    SKILL,
    OWNER,
    DOCUMENT_ID,
    "hunter2",
    "token=abc123",
    "/v1/sse",
)


def raw_document() -> dict:
    """The forward-coverage fixture. It does NOT parse, and that is the point.

    It carries key shapes the schema has not learned yet, at depths a v2 node
    might put them, so the strip is pinned before the day it is too late to be
    wrong. Read `RoundTripEveryKindTests` beside it for the complementary
    claim - that what the strip LEAVES is a document that can be read back.
    """

    return {
        "schema": BUILDER_DOCUMENT_SCHEMA,
        "id": DOCUMENT_ID,
        "version": 7,
        "name": "Secrets everywhere",
        "input_field": "idea",
        "user_id": OWNER,
        "budget": {
            "static_cost_usd": 1.5,
            "billable_nodes": 2,
            "escalation_nodes": 1,
            "cycles": 0,
            "compiled_at": "2026-09-02T00:00:00Z",
        },
        "nodes": [
            {
                "id": "idea",
                "kind": "input",
                "label": "Idea",
                "config": {"field": "idea", "required": True},
            },
            {
                "id": "search",
                "kind": "agent",
                "label": "Search",
                "config": {
                    "tier": "cheap",
                    "credential_id": CRED_TOP,
                    "llm": {"model": "x/y", "credential_id": CRED_LLM},
                    "tools": [
                        {"name": "serper", "credential_id": CRED_TOOL},
                        {"name": "plain"},
                    ],
                },
            },
            {
                "id": "docs_mcp",
                "kind": "mcp",
                "label": "Docs",
                "config": {
                    "server_id": SERVER,
                    "header_credential_id": CRED_HEADER,
                    "label": "Docs MCP",
                    "transport": "sse",
                    "url": URL_SECRET,
                    "server_hint": {"url": URL_SECRET},
                },
            },
            {
                "id": "writer",
                "kind": "agent",
                "label": "Writer",
                "config": {
                    "tier": "escalation",
                    "skill_id": SKILL,
                    "skill_name": "brand-voice",
                    "env_credential_id": CRED_ENV,
                },
            },
        ],
        "edges": [
            {"id": "e1", "source": "idea", "target": "search"},
            {"id": "e2", "source": "search", "target": "docs_mcp"},
            {"id": "e3", "source": "docs_mcp", "target": "writer"},
        ],
        "joins": {},
    }


class StripTests(unittest.TestCase):
    def setUp(self) -> None:
        self.raw = raw_document()
        self.before = deepcopy(self.raw)
        self.document, self.needs = strip_for_export(self.raw)
        self.rendered = json.dumps(self.document)

    def test_no_secret_value_survives_anywhere_in_the_export(self) -> None:
        """Criterion 1, as bytes: the values are gone, not merely relabelled."""

        for secret in SECRETS:
            with self.subTest(secret=secret):
                self.assertNotIn(secret, self.rendered)

    def test_the_control_proves_the_fixture_carried_every_secret(self) -> None:
        """Without this the test above passes on a fixture that forgot one."""

        source = json.dumps(self.raw)
        for secret in SECRETS:
            with self.subTest(secret=secret):
                self.assertIn(secret, source)

    def test_needs_credentials_names_every_stripped_node_once_in_order(self) -> None:
        self.assertEqual(self.needs, ["search", "docs_mcp", "writer"])

    def test_a_node_with_nothing_to_strip_is_not_named(self) -> None:
        self.assertNotIn("idea", self.needs)

    def test_a_null_credential_key_is_the_schema_default_and_is_not_reported(self) -> None:
        """Found at integration: since S1 ruling 8 every agent node serialises
        with `credential_id: null`, so a strip that noted the node on the KEY
        alone reported every clean export as needing a credential. The key
        stays null; the node is not named."""

        document, needs = strip_for_export(
            {
                "name": "clean",
                "nodes": [
                    {"id": "scoper", "config": {"credential_id": None, "llm": {"credential_id": ""}}},
                    {"id": "docs", "config": {"server_id": None}},
                ],
            }
        )
        self.assertEqual(needs, [])
        self.assertIsNone(document["nodes"][0]["config"]["credential_id"])
        self.assertIsNone(document["nodes"][0]["config"]["llm"]["credential_id"])
        self.assertIsNone(document["nodes"][1]["config"]["server_id"])

    def test_credential_ids_become_null_at_every_depth(self) -> None:
        search = self.document["nodes"][1]["config"]
        self.assertIsNone(search["credential_id"])
        self.assertIsNone(search["llm"]["credential_id"])
        self.assertIsNone(search["tools"][0]["credential_id"])
        self.assertEqual(search["tools"][1], {"name": "plain"})
        self.assertIsNone(self.document["nodes"][2]["config"]["header_credential_id"])
        self.assertIsNone(self.document["nodes"][3]["config"]["env_credential_id"])

    def test_a_server_reference_becomes_null_plus_a_masked_hint(self) -> None:
        config = self.document["nodes"][2]["config"]
        self.assertIsNone(config["server_id"])
        self.assertEqual(
            config["server_hint"],
            {
                "label": "Docs MCP",
                "transport": "sse",
                "url": f"https://mcp.example.test:8443/{MASKED_PATH}",
            },
        )

    def test_the_address_beside_a_server_reference_leaves_only_inside_the_hint(self) -> None:
        """The first walk let `url` through with its `user:password@` intact."""

        config = self.document["nodes"][2]["config"]
        self.assertNotIn("url", config)
        self.assertEqual(config["label"], "Docs MCP")
        self.assertEqual(config["transport"], "sse")

    def test_an_inbound_hint_is_never_trusted_to_be_masked(self) -> None:
        """The fixture's own `server_hint` carried the raw URL; it does not leave."""

        self.assertNotIn("hunter2", json.dumps(self.document["nodes"][2]))

    def test_a_skill_reference_is_dropped_and_its_name_kept(self) -> None:
        config = self.document["nodes"][3]["config"]
        self.assertNotIn("skill_id", config)
        self.assertEqual(config["skill_name"], "brand-voice")

    def test_id_version_budget_and_owner_are_dropped(self) -> None:
        for key in EXPORT_DROPPED_KEYS:
            with self.subTest(key=key):
                self.assertNotIn(key, self.document)
        self.assertEqual(EXPORT_DROPPED_KEYS, ("id", "version", "budget", "user_id"))

    def test_everything_else_passes_through_unchanged(self) -> None:
        self.assertEqual(self.document["schema"], BUILDER_DOCUMENT_SCHEMA)
        self.assertEqual(self.document["name"], "Secrets everywhere")
        self.assertEqual(self.document["input_field"], "idea")
        self.assertEqual(self.document["nodes"][0], self.before["nodes"][0])
        self.assertEqual(self.document["edges"], self.before["edges"])
        self.assertEqual(self.document["joins"], {})

    def test_the_input_is_not_mutated(self) -> None:
        self.assertEqual(self.raw, self.before)

    def test_the_result_shares_no_container_with_the_input(self) -> None:
        self.document["nodes"][0]["config"]["field"] = "changed"
        self.assertEqual(self.raw["nodes"][0]["config"]["field"], "idea")

    def test_a_secret_outside_any_node_is_stripped_but_attributed_to_none(self) -> None:
        raw = raw_document()
        raw["joins"] = {"credential_id": CRED_TOP}
        document, needs = strip_for_export(raw)
        self.assertIsNone(document["joins"]["credential_id"])
        self.assertEqual(needs, ["search", "docs_mcp", "writer"])

    def test_a_document_with_no_nodes_key_still_strips(self) -> None:
        document, needs = strip_for_export({"name": "bare", "credential_id": "cr_x"})
        self.assertEqual(document, {"name": "bare", "credential_id": None})
        self.assertEqual(needs, [])

    def test_a_non_mapping_is_refused_by_name(self) -> None:
        with self.assertRaises(TypeError):
            strip_for_export(["not", "a", "document"])  # type: ignore[arg-type]

    def test_a_resolver_fills_the_hint_from_the_record(self) -> None:
        """Plan 07's table is the truth about a server; the config is a copy."""

        seen: list[str] = []

        def resolve(server_id: str) -> dict:
            seen.append(server_id)
            return {"label": "From the table", "transport": "http", "url": "http://h:9/p?k=v"}

        document, _ = strip_for_export(raw_document(), resolve_server=resolve)
        self.assertEqual(seen, [SERVER])
        self.assertEqual(
            document["nodes"][2]["config"]["server_hint"],
            {"label": "From the table", "transport": "http", "url": f"http://h:9/{MASKED_PATH}"},
        )


class RoundTripEveryKindTests(unittest.TestCase):
    """D-15-30: what the strip leaves parses, for every kind there is.

    `raw_document()` above is ahead of the schema by design and therefore
    cannot answer this; the round trip is a different property from the strip
    and needs a document `BuilderDocument` accepts. The exhaustiveness
    assertion is the load-bearing half: D-15-28 was two node kinds that did not
    exist when the export was written, and the only defence against a third is
    a test that fails when one is added.
    """

    @staticmethod
    def _document() -> dict:
        """One node of every `NodeKind`, in `NodeKind`'s own order.

        Configs are minimal - each kind's required fields and the references
        the export exists to strip. `bounds.py` would have plenty to say about
        this graph and that is fine: parsing is not the layer that decides a
        graph is finished, which is the same distinction `McpConfig.tool_names`
        already rests on.
        """

        return {
            "schema": BUILDER_DOCUMENT_SCHEMA,
            "id": DOCUMENT_ID,
            "version": 3,
            "name": "one of everything",
            "input_field": "idea",
            "nodes": [
                {"id": "n_input", "kind": "input", "label": "Idea",
                 "config": {"field": "idea"},
                 "position": {"x": 0, "y": 0}},
                {"id": "n_agent", "kind": "agent", "label": "Worker",
                 "config": {"tier": "cheap", "agent_id": "scoper",
                            "credential_id": CRED_TOP},
                 "position": {"x": 0, "y": 120}},
                {"id": "n_crew", "kind": "crew", "label": "Team",
                 "config": {"tier": "cheap", "process": "sequential"},
                 "position": {"x": 0, "y": 240}},
                {"id": "n_gate", "kind": "gate", "label": "Confirm",
                 "config": {"message": "Does this look right?"},
                 "position": {"x": 0, "y": 360}},
                {"id": "n_router", "kind": "router", "label": "Decide",
                 "config": {},
                 "position": {"x": 0, "y": 480}},
                {"id": "n_transform", "kind": "transform", "label": "Default",
                 "config": {"op": "default",
                            "args": {"value": "${state.out__n_agent}",
                                     "default": "nothing"}},
                 "position": {"x": 0, "y": 600}},
                {"id": "n_output", "kind": "output", "label": "Report",
                 "config": {"body_key": "markdown_body"},
                 "position": {"x": 0, "y": 720}},
                {"id": "n_tool", "kind": "tool", "label": "Search",
                 "config": {"tool_id": "serper_search",
                            "credential_id": CRED_TOOL},
                 "position": {"x": 300, "y": 120}},
                {"id": "n_mcp", "kind": "mcp", "label": "Docs",
                 "config": {"server_id": SERVER, "tool_names": ["alpha"],
                            "credential_id": CRED_HEADER},
                 "position": {"x": 300, "y": 240}},
                {"id": "n_skill", "kind": "skill", "label": "House style",
                 "config": {"skill_id": SKILL, "skill_name": "House style"},
                 "position": {"x": 300, "y": 360}},
            ],
            "edges": [
                {"id": "e1", "source": "n_input", "target": "n_agent"},
                {"id": "e2", "source": "n_agent", "target": "n_crew"},
                {"id": "e3", "source": "n_crew", "target": "n_gate"},
                {"id": "e4", "source": "n_gate", "target": "n_router"},
                {"id": "e5", "source": "n_router", "target": "n_transform"},
                {"id": "e6", "source": "n_transform", "target": "n_output"},
                {"id": "e7", "source": "n_tool", "source_port": "attach",
                 "target": "n_agent", "target_port": "attach"},
                {"id": "e8", "source": "n_mcp", "source_port": "attach",
                 "target": "n_agent", "target_port": "attach"},
                {"id": "e9", "source": "n_skill", "source_port": "attach",
                 "target": "n_agent", "target_port": "attach"},
            ],
        }

    @staticmethod
    def _reimported(raw: dict) -> tuple[dict, list[str]]:
        """Export, then restore the two keys the ENVELOPE carries, not the file.

        `id` and `version` are the importer's to supply - a file does not
        choose the id it lands under - so putting them back is what makes this
        a test of the document shape rather than of the route's bookkeeping.
        """

        stripped, needs = strip_for_export(raw)
        stripped["id"] = raw["id"]
        stripped["version"] = raw["version"]
        return stripped, needs

    def test_the_fixture_covers_every_kind_and_fails_when_one_is_added(self) -> None:
        from typing import get_args

        from brief_crew.builder.document import NodeKind

        kinds = [node["kind"] for node in self._document()["nodes"]]
        self.assertEqual(len(kinds), len(set(kinds)), "one node per kind, no repeats")
        self.assertEqual(
            list(get_args(NodeKind)),
            kinds,
            "a kind was added to the schema and not to this fixture; D-15-28 is "
            "what happens when the export never meets one",
        )

    def test_the_fixture_itself_parses_which_raw_document_deliberately_does_not(
        self,
    ) -> None:
        from brief_crew.builder.document import BuilderDocument

        document = BuilderDocument.model_validate(self._document())
        self.assertEqual(10, len(document.nodes))

    def test_the_stripped_document_re_parses_for_every_kind(self) -> None:
        """The assertion that would have caught D-15-28, one round trip.

        It failed for `mcp` (`server_id - Input should be a valid string`, then
        `server_hint - Extra inputs are not permitted`) and for `skill`
        (`skill_id - Field required`) until 2026-09-04.
        """

        from brief_crew.builder.document import BuilderDocument

        stripped, _ = self._reimported(self._document())
        document = BuilderDocument.model_validate(stripped)

        self.assertEqual(
            [node["kind"] for node in self._document()["nodes"]],
            [node.kind for node in document.nodes],
        )

    def test_the_round_trip_still_carries_no_reference_and_says_who_lost_one(
        self,
    ) -> None:
        """Stripping is the point; the round trip must not be bought by keeping one."""

        # The FILE, before `id` and `version` are handed back by the envelope:
        # what leaves the service is what must carry nothing.
        stripped, needs = strip_for_export(self._document())
        rendered = json.dumps(stripped)
        for secret in (CRED_TOP, CRED_TOOL, CRED_HEADER, SERVER, SKILL, DOCUMENT_ID):
            with self.subTest(secret=secret):
                self.assertNotIn(secret, rendered)
        # Every node that lost a credential or a server reference is named; the
        # skill node is not, because `skill_name` survives and resolves it.
        self.assertEqual(["n_agent", "n_tool", "n_mcp"], needs)


class MaskUrlTests(unittest.TestCase):
    def test_origin_survives_and_the_rest_is_asterisks(self) -> None:
        self.assertEqual(
            mask_url("https://mcp.example.test/v1/sse?token=abc"),
            f"https://mcp.example.test/{MASKED_PATH}",
        )

    def test_the_port_is_part_of_the_origin(self) -> None:
        self.assertEqual(mask_url("http://h:8080/x"), f"http://h:8080/{MASKED_PATH}")

    def test_userinfo_is_not_part_of_the_origin(self) -> None:
        """`netloc` would have kept `user:pass@`; `hostname` does not."""

        masked = mask_url("https://user:pass@h.test/x")
        self.assertEqual(masked, f"https://h.test/{MASKED_PATH}")
        self.assertNotIn("pass", masked)

    def test_something_that_is_not_a_url_is_fully_masked(self) -> None:
        for value in ("", None, 7, "not a url", "/relative/only", "h.test/no-scheme"):
            with self.subTest(value=value):
                self.assertEqual(mask_url(value), MASKED_PATH)


class EnvelopeTests(unittest.TestCase):
    def test_the_keys_are_the_plan_s_in_the_plan_s_order(self) -> None:
        envelope = export_envelope(raw_document(), source_version=7)
        self.assertEqual(
            list(envelope),
            ["export", "exported_at", "name", "source_version", "needs_credentials", "document"],
        )

    def test_export_is_the_document_s_own_schema_string(self) -> None:
        """S1 ruling 4: not a constant, the document's `schema`."""

        raw = raw_document()
        raw["schema"] = "builder.flow/v2"
        self.assertEqual(export_envelope(raw, source_version=1)["export"], "builder.flow/v2")
        self.assertEqual(
            export_envelope(raw_document(), source_version=1)["export"], BUILDER_DOCUMENT_SCHEMA
        )

    def test_a_document_that_never_spelled_its_schema_exports_today_s(self) -> None:
        raw = raw_document()
        del raw["schema"]
        self.assertEqual(export_envelope(raw, source_version=1)["export"], BUILDER_DOCUMENT_SCHEMA)

    def test_source_version_name_and_needs_are_carried(self) -> None:
        envelope = export_envelope(raw_document(), source_version=7)
        self.assertEqual(envelope["source_version"], 7)
        self.assertEqual(envelope["name"], "Secrets everywhere")
        self.assertEqual(envelope["needs_credentials"], ["search", "docs_mcp", "writer"])

    def test_exported_at_is_utc_iso_8601(self) -> None:
        stamp = datetime(2026, 9, 3, 12, 30, tzinfo=timezone.utc)
        envelope = export_envelope(raw_document(), source_version=1, exported_at=stamp)
        self.assertEqual(envelope["exported_at"], "2026-09-03T12:30:00+00:00")
        naive = export_envelope(raw_document(), source_version=1, exported_at=datetime(2026, 9, 3))
        self.assertTrue(naive["exported_at"].endswith("+00:00"))

    def test_the_whole_envelope_carries_no_secret(self) -> None:
        rendered = json.dumps(export_envelope(raw_document(), source_version=7))
        for secret in SECRETS:
            with self.subTest(secret=secret):
                self.assertNotIn(secret, rendered)


class FilenameTests(unittest.TestCase):
    def test_a_plain_name_gets_the_suffix(self) -> None:
        self.assertEqual(export_filename("Idea validator"), "Idea validator.builder.json")

    def test_header_breaking_and_path_characters_are_removed(self) -> None:
        name = 'a"b\\c/d:e*f?g<h>i|j\r\nk'
        rendered = export_filename(name)
        for forbidden in '"\\/:*?<>|\r\n':
            self.assertNotIn(forbidden, rendered)
        self.assertTrue(rendered.endswith(".builder.json"))

    def test_non_ascii_is_dropped_rather_than_escaped(self) -> None:
        self.assertEqual(export_filename("Idée validée"), "Ide valide.builder.json")

    def test_a_name_that_sanitises_to_nothing_gets_a_stable_default(self) -> None:
        for name in ("", "   ", "///", "...", None, 7):
            with self.subTest(name=name):
                self.assertEqual(export_filename(name), "workflow.builder.json")

    def test_a_long_name_is_bounded(self) -> None:
        rendered = export_filename("x" * 500)
        self.assertLessEqual(len(rendered), 100 + len(".builder.json"))


class ContentDispositionTests(unittest.TestCase):
    """RFC 6266: an ASCII `filename=` beside an exact `filename*=UTF-8''`."""

    def test_a_plain_name_appears_in_both_forms(self) -> None:
        self.assertEqual(
            export_content_disposition("Idea validator"),
            'attachment; filename="Idea validator.builder.json"; '
            "filename*=UTF-8''Idea%20validator.builder.json",
        )

    def test_the_exact_form_keeps_what_the_ascii_form_had_to_drop(self) -> None:
        value = export_content_disposition('Idée "v2"/final')
        self.assertIn('filename="Ide v2 final.builder.json"', value)
        self.assertIn("filename*=UTF-8''Id%C3%A9e%20%22v2%22%2Ffinal.builder.json", value)

    def test_nothing_unencoded_can_break_the_header(self) -> None:
        value = export_content_disposition('a"b\r\nc;d')
        self.assertNotIn("\r", value)
        self.assertNotIn("\n", value)
        # Exactly three parameters: the disposition and the two filenames.
        self.assertEqual(len(value.split("; ")), 3)
        self.assertIn("filename*=UTF-8''a%22bc%3Bd.builder.json", value)

    def test_an_empty_name_gets_the_default_in_both_forms(self) -> None:
        for name in ("", "   ", None, "\x01\x02"):
            with self.subTest(name=name):
                value = export_content_disposition(name)
                self.assertIn('filename="workflow.builder.json"', value)
                self.assertIn("filename*=UTF-8''workflow.builder.json", value)

    def test_the_exact_form_is_bounded_too(self) -> None:
        value = export_content_disposition("y" * 500)
        exact = value.split("filename*=UTF-8''")[1]
        self.assertLessEqual(len(exact), 100 + len(".builder.json"))


if __name__ == "__main__":
    unittest.main()
