"""`upgrade_document` over every committed `builder.flow/v1` fixture - plan 15 D5.

Criterion 6: each fixture upgrades to a document `validate_document` finds
clean, and the upgrade is idempotent - `upgrade(upgrade(x)) == upgrade(x)`. In
Stage 1 the function is the hook and not the mapping (S1 ruling 5), so "clean"
today means "unchanged"; the idempotence and purity assertions are what every
later mapping inherits, which is why they are written against the fixtures now
rather than against the mapping later.

The fixtures: the one committed JSON template
(`frontend/tests/fixtures/builderValidatorTemplate.json`, Python-generated), and
the Python-side v1 documents the compiler and rehydration suites are built on.
The three gallery templates in `frontend/src/data/builderTemplates.ts` are
TypeScript literals with no JSON twin until contract C9 (plan 14, Stage 2)
lands `frontend/tests/fixtures/templates/*.json`; they are not readable from
here and are not pretended to be.
"""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any
import unittest
from unittest import mock

from brief_crew.builder import validate_document
from brief_crew.builder import upgrade as upgrade_module
from brief_crew.builder import document as document_module
from brief_crew.builder.document import (
    BuilderDocument,
    LibraryAgentConfig,
    LibraryCrewConfig,
)
from brief_crew.builder.upgrade import (
    KNOWN_SCHEMAS,
    SCHEMA_V1,
    SCHEMA_V2,
    is_known_schema,
    upgrade_document,
)
from brief_crew.config import BUILDER_DOCUMENT_SCHEMA
from tests.builder.test_compiler import fan_out_and_join, gated_loop, straight_line


REPO = Path(__file__).resolve().parents[2]
VALIDATOR_TEMPLATE = REPO / "frontend" / "tests" / "fixtures" / "builderValidatorTemplate.json"
PLACEHOLDER_ID = "ug_0123abcd"


def committed_fixtures() -> dict[str, dict[str, Any]]:
    """Every v1 document this repository commits, as the raw dict it is stored as."""

    fixtures: dict[str, dict[str, Any]] = {}
    template = json.loads(VALIDATOR_TEMPLATE.read_text(encoding="utf-8"))["document"]
    fixtures["builderValidatorTemplate.json"] = dict(template)
    for name, build in (
        ("straight_line", straight_line),
        ("fan_out_and_join", fan_out_and_join),
        ("gated_loop", gated_loop),
    ):
        fixtures[name] = build().model_dump(mode="json", by_alias=True)
    return fixtures


def parse(raw: dict[str, Any]) -> BuilderDocument:
    candidate = dict(raw)
    candidate.setdefault("id", PLACEHOLDER_ID)
    candidate.setdefault("version", 1)
    return BuilderDocument.model_validate(candidate)


class CommittedFixtureTests(unittest.TestCase):
    def test_every_committed_fixture_really_is_v1(self) -> None:
        """The control: a fixture already at some later schema proves nothing."""

        for name, raw in committed_fixtures().items():
            with self.subTest(fixture=name):
                self.assertEqual(raw.get("schema", SCHEMA_V1), SCHEMA_V1)

    def test_every_committed_fixture_upgrades_to_a_clean_document(self) -> None:
        for name, raw in committed_fixtures().items():
            with self.subTest(fixture=name):
                document = parse(upgrade_document(raw))
                self.assertEqual(document.document_schema, BUILDER_DOCUMENT_SCHEMA)
                problems = validate_document(document)
                self.assertEqual(
                    [problem for problem in problems if problem.severity == "error"], []
                )

    def test_the_validator_template_upgrades_with_zero_problems_of_any_severity(self) -> None:
        raw = committed_fixtures()["builderValidatorTemplate.json"]
        self.assertEqual(validate_document(parse(upgrade_document(raw))), [])

    def test_the_upgrade_is_idempotent(self) -> None:
        for name, raw in committed_fixtures().items():
            with self.subTest(fixture=name):
                once = upgrade_document(raw)
                self.assertEqual(upgrade_document(once), once)

    def test_v1_passes_through_while_the_service_still_compiles_v1(self) -> None:
        """The mapping is registered and INERT, and this is what says so.

        `upgrade_document` walks `_UPGRADES` only while the document's schema
        differs from `config.BUILDER_DOCUMENT_SCHEMA`, which is still
        `builder.flow/v1` because moving it is a two-suite contract change the
        client half has not made. `V1ToV2MappingTests` below proves the walk
        with the constant patched, so this assertion is about today's wiring
        rather than about the mapping's correctness.
        """

        self.assertEqual(BUILDER_DOCUMENT_SCHEMA, SCHEMA_V1)
        for name, raw in committed_fixtures().items():
            with self.subTest(fixture=name):
                self.assertEqual(upgrade_document(raw), raw)

    def test_the_input_is_never_mutated_and_never_shared(self) -> None:
        for name, raw in committed_fixtures().items():
            with self.subTest(fixture=name):
                before = deepcopy(raw)
                upgraded = upgrade_document(raw)
                self.assertEqual(raw, before)
                self.assertIsNot(upgraded, raw)
                upgraded["nodes"][0]["id"] = "tampered"
                self.assertEqual(raw, before)


class HookTests(unittest.TestCase):
    def test_the_two_schema_strings_the_importer_accepts(self) -> None:
        self.assertEqual(KNOWN_SCHEMAS, (SCHEMA_V1, SCHEMA_V2))
        self.assertTrue(is_known_schema("builder.flow/v1"))
        self.assertTrue(is_known_schema("builder.flow/v2"))
        self.assertFalse(is_known_schema("builder.flow/v3"))
        self.assertFalse(is_known_schema(None))

    def test_a_v2_document_passes_through_for_the_schema_to_refuse(self) -> None:
        """S1 ruling 4: a v2 file imports the day 03 lands. Until then the
        refusal is the schema's own sentence, not a second one from here."""

        raw = straight_line().model_dump(mode="json", by_alias=True)
        raw["schema"] = SCHEMA_V2
        upgraded = upgrade_document(raw)
        self.assertEqual(upgraded["schema"], SCHEMA_V2)
        with self.assertRaises(ValueError) as caught:
            parse(upgraded)
        self.assertIn("unknown document schema", str(caught.exception))

    def test_an_unknown_schema_passes_through_untouched(self) -> None:
        raw = {"schema": "builder.flow/v9", "name": "x"}
        self.assertEqual(upgrade_document(raw), raw)

    def test_a_document_with_no_schema_key_keeps_none(self) -> None:
        """The model's default fills it in; the upgrade must not, or a stored
        row that never spelled it would stop round-tripping byte for byte."""

        raw = straight_line().model_dump(mode="json", by_alias=True)
        del raw["schema"]
        upgraded = upgrade_document(raw)
        self.assertNotIn("schema", upgraded)
        self.assertEqual(parse(upgraded).document_schema, BUILDER_DOCUMENT_SCHEMA)

    def test_a_non_mapping_is_refused_by_name(self) -> None:
        with self.assertRaises(TypeError) as caught:
            upgrade_document(["nodes"])  # type: ignore[arg-type]
        self.assertIn("list", str(caught.exception))


class V1ToV2MappingTests(unittest.TestCase):
    """03 D4's mapping, run as it will run the day the constant moves.

    `BUILDER_DOCUMENT_SCHEMA` is patched where `upgrade.py` READ it - the module
    does `from ... import BUILDER_DOCUMENT_SCHEMA`, so patching `config` would
    change nothing and this test would pass by not running the walk at all. The
    control for that is `test_the_walk_really_ran`, which asserts the schema
    actually moved rather than merely that two dicts are equal.

    **Idempotence is tested by running it TWICE**, which is the criterion's own
    wording and not a formality: a mapping that filled in fields the model would
    default - `"state": null` on every document, `"on_error": "fail"` on every
    node - differs from its input on the first pass and agrees with itself on
    the second, so a one-pass test would pass while a stored row silently
    stopped round-tripping.
    """

    def _upgraded(self, raw: dict[str, Any]) -> dict[str, Any]:
        with mock.patch.object(upgrade_module, "BUILDER_DOCUMENT_SCHEMA", SCHEMA_V2):
            return upgrade_document(raw)

    def test_the_walk_really_ran(self) -> None:
        for name, raw in committed_fixtures().items():
            with self.subTest(fixture=name):
                self.assertEqual(raw.get("schema", SCHEMA_V1), SCHEMA_V1)
                self.assertEqual(self._upgraded(raw)["schema"], SCHEMA_V2)

    def test_every_committed_fixture_is_byte_identical_after_a_SECOND_pass(self) -> None:
        for name, raw in committed_fixtures().items():
            with self.subTest(fixture=name):
                once = self._upgraded(raw)
                twice = self._upgraded(once)
                self.assertEqual(
                    json.dumps(twice, sort_keys=True), json.dumps(once, sort_keys=True)
                )

    def test_the_first_pass_changes_the_schema_STRING_and_nothing_else(self) -> None:
        """The property idempotence alone would not catch (see the class note)."""

        for name, raw in committed_fixtures().items():
            with self.subTest(fixture=name):
                once = self._upgraded(raw)
                self.assertEqual(
                    {key: value for key, value in once.items() if key != "schema"},
                    {key: value for key, value in raw.items() if key != "schema"},
                )

    def test_a_v1_document_parses_as_v2_with_no_field_rewritten(self) -> None:
        """D4's reason the mapping is one line: v2 grew by ADDITION only.

        A v1 agent carries `agent_id`, so presence-discrimination puts it on the
        library arm - the arm it always was. Nothing needed a value it did not
        already have.
        """

        raw = self._upgraded(committed_fixtures()["builderValidatorTemplate.json"])
        # `_validate_schema` reads the name out of `document.py`'s own module
        # namespace at call time, which is the only thing that has to move for
        # a v2 document to parse. The model's FIELD default is irrelevant here
        # because this document spells its schema.
        with mock.patch.object(document_module, "BUILDER_DOCUMENT_SCHEMA", SCHEMA_V2):
            parsed = parse(raw)
        self.assertEqual(parsed.document_schema, SCHEMA_V2)
        self.assertIsNone(parsed.state)
        for node in parsed.nodes:
            if node.kind in ("agent", "crew"):
                self.assertIsInstance(node.config, (LibraryAgentConfig, LibraryCrewConfig))
        self.assertEqual(validate_document(parsed), [])

    def test_a_document_already_at_v2_is_left_alone(self) -> None:
        raw = straight_line().model_dump(mode="json", by_alias=True)
        raw["schema"] = SCHEMA_V2
        self.assertEqual(self._upgraded(raw), raw)

    def test_the_mapping_never_mutates_or_shares_its_input(self) -> None:
        raw = committed_fixtures()["straight_line"]
        before = deepcopy(raw)
        upgraded = self._upgraded(raw)
        self.assertEqual(raw, before)
        upgraded["nodes"][0]["id"] = "tampered"
        self.assertEqual(raw, before)


class StoreIntegrationTests(unittest.TestCase):
    """The hook is on the store's read path, not beside it."""

    def test_the_store_re_validation_path_runs_the_upgrade(self) -> None:
        from unittest.mock import patch

        from brief_crew.builder import store as store_module

        document = straight_line()
        seen: list[dict[str, Any]] = []

        def spy(raw: dict[str, Any]) -> dict[str, Any]:
            seen.append(dict(raw))
            return upgrade_document(raw)

        with patch.object(store_module, "upgrade_document", spy):
            parsed = store_module._parse(document.id, document.model_dump(mode="json", by_alias=True))
        self.assertEqual(parsed, document)
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0]["schema"], SCHEMA_V1)


if __name__ == "__main__":
    unittest.main()
