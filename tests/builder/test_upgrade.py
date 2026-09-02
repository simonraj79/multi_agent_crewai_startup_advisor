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

from brief_crew.builder import validate_document
from brief_crew.builder.document import BuilderDocument
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

    def test_stage_one_passes_v1_through_unchanged(self) -> None:
        """S1 ruling 5. When the mapping lands this assertion goes with it."""

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
