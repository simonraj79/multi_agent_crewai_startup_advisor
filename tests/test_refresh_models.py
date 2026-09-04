"""`scripts/refresh_models.py` - plan 05 criterion 2, against a recorded catalogue.

No network. `tests/fixtures/openrouter_catalogue.json` is a hand-cut eight-row
slice of the public `GET /api/v1/models` in its verbatim shape, and its own
`_note` says which predicate each row exists to exercise.

**The row that matters most is the `:batch` pair.** Plan 05's original price
table quoted `google/gemini-3.5-flash-lite` at $0.15 / $1.25 under the sentence
"both prices are already wrong against the live catalogue". Those are the
`:batch` variant's prices - exactly half the headline on both figures, which is
why the wrong pair looked plausible - and batch is a queued lane a run with
streaming frames and a human at a gate can never use. A registry seeded from
that table would have replaced two CORRECT prices with two wrong ones, and the
resulting defect has a name in this repository: a run priced at $0.00 over
128,069 real tokens. So the fixture puts the plain row and the `:batch` row of
one model side by side and this file asserts which one wins.
"""

from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import unittest

REPO = pathlib.Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:  # pragma: no cover - import bootstrap
    sys.path.insert(0, str(REPO))

from scripts.refresh_models import (  # noqa: E402
    PRESERVED_FIELDS,
    build_registry,
    derive_row,
    main,
    render,
)

CATALOGUE = REPO / "tests" / "fixtures" / "openrouter_catalogue.json"


def catalogue() -> list[dict[str, object]]:
    return json.loads(CATALOGUE.read_text(encoding="utf-8"))["data"]


def row(model_id: str) -> dict[str, object]:
    for candidate in catalogue():
        if candidate["id"] == model_id:
            return candidate
    raise AssertionError(f"{model_id} is not in the fixture")


def seeded_registry(*model_ids: str) -> dict[str, object]:
    """A registry holding the named ids with deliberately STALE derived fields.

    Every derived field is wrong on purpose - the wrong name, the wrong price,
    the wrong context - so a test asserting a refreshed value cannot pass by
    the value having been right all along. The three preserved fields carry
    distinctive values for the same reason.
    """

    return {
        "schema": "models/v1",
        "generated_at": "2020-01-01T00:00:00Z",
        "source": "https://openrouter.ai/api/v1/models",
        "ceiling_usd_per_m_input": 1.0,
        "presets": {
            "cheap": "google/gemini-3.5-flash-lite:nitro",
            "escalation": "google/gemini-3.5-flash-lite",
        },
        "models": [
            {
                "id": model_id,
                "name": "STALE NAME",
                "provider": model_id.split("/", 1)[0],
                "context_window": 1,
                "supports_tools": False,
                "supports_vision": False,
                "supports_json_mode": False,
                "supports_reasoning": False,
                "cost_in": 9.99,
                "cost_out": 9.99,
                "cost_in_max_endpoint": 0.54,
                "speed_tier": "deep",
                "recommended_for": ["a-curated-role"],
            }
            for model_id in model_ids
        ],
    }


class BatchVariantTests(unittest.TestCase):
    """The defect this script exists to make impossible."""

    def test_the_plain_row_price_wins_over_its_batch_twin(self) -> None:
        updated, departed = build_registry(
            catalogue(), seeded_registry("google/gemini-3.5-flash-lite")
        )
        self.assertEqual(departed, [])
        (refreshed,) = updated["models"]
        self.assertEqual(refreshed["cost_in"], 0.3)
        self.assertEqual(refreshed["cost_out"], 2.5)

    def test_the_batch_row_never_enters_the_registry_as_a_model(self) -> None:
        updated, _ = build_registry(
            catalogue(),
            seeded_registry("google/gemini-3.5-flash-lite"),
            keep_ids=["google/gemini-3.5-flash-lite:batch"],
        )
        ids = [model["id"] for model in updated["models"]]
        self.assertNotIn("google/gemini-3.5-flash-lite:batch", ids)

    def test_asking_for_the_batch_id_reports_it_as_departed(self) -> None:
        """Because it is not in the ADMITTED set, which is the honest answer.

        A `--keep-ids` naming something the filter refuses is a person asking
        for a model this product may not use. Silently ignoring it would leave
        them staring at a registry that never grew.
        """

        _, departed = build_registry(
            catalogue(),
            seeded_registry("google/gemini-3.5-flash-lite"),
            keep_ids=["google/gemini-3.5-flash-lite:batch"],
        )
        self.assertEqual(departed, ["google/gemini-3.5-flash-lite:batch"])


class FilterTests(unittest.TestCase):
    """Each clause proved by a row that fails only that clause."""

    def test_a_model_over_the_ceiling_is_refused(self) -> None:
        _, departed = build_registry(catalogue(), seeded_registry("openai/o4-mini"))
        self.assertEqual(departed, ["openai/o4-mini"])

    def test_anthropic_is_refused_by_provider_and_not_by_price(self) -> None:
        """$0.80/M input passes the ceiling, so only the provider clause refuses it."""

        haiku = row("anthropic/claude-haiku-4.5")
        self.assertLess(float(haiku["pricing"]["prompt"]) * 1_000_000, 1.0)
        _, departed = build_registry(
            catalogue(), seeded_registry("anthropic/claude-haiku-4.5")
        )
        self.assertEqual(departed, ["anthropic/claude-haiku-4.5"])

    def test_a_free_variant_is_refused(self) -> None:
        _, departed = build_registry(
            catalogue(), seeded_registry("meta-llama/llama-4-scout:free")
        )
        self.assertEqual(departed, ["meta-llama/llama-4-scout:free"])

    def test_a_model_without_tools_is_refused(self) -> None:
        _, departed = build_registry(
            catalogue(), seeded_registry("mistralai/mistral-small-3.2")
        )
        self.assertEqual(departed, ["mistralai/mistral-small-3.2"])


class DerivationTests(unittest.TestCase):
    """The catalogue's own fields, turned into C3's."""

    def test_per_token_prices_become_per_million(self) -> None:
        """A factor of a million, which is the one conversion that is loud."""

        derived = derive_row(row("google/gemini-3.5-flash-lite"))
        self.assertEqual((derived["cost_in"], derived["cost_out"]), (0.3, 2.5))

    def test_json_mode_is_response_format_or_structured_outputs(self) -> None:
        self.assertTrue(derive_row(row("openai/gpt-4o-mini"))["supports_json_mode"])

    def test_vision_reads_the_input_modalities(self) -> None:
        self.assertTrue(derive_row(row("openai/gpt-4o-mini"))["supports_vision"])
        self.assertFalse(derive_row(row("deepseek/deepseek-r1"))["supports_vision"])

    def test_reasoning_reads_supported_parameters_not_supported_efforts(self) -> None:
        """The departure from C3 as written, and it is a measurement.

        `deepseek/deepseek-r1` publishes `reasoning: {mandatory: true}` and no
        `supported_efforts` at all. C3's rule - "`supported_efforts` non-empty"
        - computes FALSE for it, and r1 is on the roster *for* reasoning,
        mandatorily. `reasoning in supported_parameters` agrees with all ten.
        """

        self.assertTrue(derive_row(row("deepseek/deepseek-r1"))["supports_reasoning"])
        self.assertFalse(derive_row(row("openai/gpt-4o-mini"))["supports_reasoning"])

    def test_tools_is_read_rather_than_assumed_from_the_filter(self) -> None:
        self.assertTrue(derive_row(row("google/gemini-3.5-flash-lite"))["supports_tools"])


class PreservationTests(unittest.TestCase):
    """The three fields the public catalogue cannot supply."""

    def test_the_curated_fields_survive_a_refresh(self) -> None:
        updated, _ = build_registry(
            catalogue(), seeded_registry("google/gemini-3.5-flash-lite")
        )
        (refreshed,) = updated["models"]
        self.assertEqual(refreshed["cost_in_max_endpoint"], 0.54)
        self.assertEqual(refreshed["speed_tier"], "deep")
        self.assertEqual(refreshed["recommended_for"], ["a-curated-role"])

    def test_every_preserved_field_is_actually_preserved(self) -> None:
        """The list and the behaviour, checked against each other.

        A field added to `PRESERVED_FIELDS` and not carried across would be a
        silently-recomputed curated value, which is the failure preservation
        exists to prevent.
        """

        seeded = seeded_registry("google/gemini-3.5-flash-lite")
        updated, _ = build_registry(catalogue(), seeded)
        for field in PRESERVED_FIELDS:
            with self.subTest(field=field):
                self.assertEqual(
                    updated["models"][0][field], seeded["models"][0][field]
                )

    def test_a_stale_max_endpoint_is_lifted_to_a_risen_headline(self) -> None:
        """`config.py` refuses `max < headline`, so a refresh must not write one.

        The registry asserts at import that the dearest endpoint is at least the
        headline, because the headline IS one of the slug's endpoints. A price
        rise past a stale measured maximum would otherwise produce a file that
        cannot be loaded at all - a boot failure standing in for what should be
        a number in a diff.
        """

        seeded = seeded_registry("deepseek/deepseek-r1")
        seeded["models"][0]["cost_in_max_endpoint"] = 0.01
        updated, _ = build_registry(catalogue(), seeded)
        self.assertEqual(updated["models"][0]["cost_in_max_endpoint"], 0.7)


class BoundTests(unittest.TestCase):
    def test_more_than_ten_models_is_refused(self) -> None:
        seeded = seeded_registry("google/gemini-3.5-flash-lite")
        with self.assertRaises(SystemExit) as caught:
            build_registry(catalogue(), seeded, max_models=0)
        self.assertIn("at most 0", str(caught.exception))


class CommandLineTests(unittest.TestCase):
    """Criterion 2's three sentences, run as the command line runs them."""

    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.registry = pathlib.Path(self._temp.name) / "models.json"

    def write(self, payload: dict[str, object]) -> None:
        self.registry.write_text(render(payload), encoding="utf-8")

    def argv(self, *extra: str) -> list[str]:
        return [
            "--catalogue",
            str(CATALOGUE),
            "--registry",
            str(self.registry),
            *extra,
        ]

    def test_a_stale_registry_prints_a_diff_and_writes_nothing(self) -> None:
        self.write(seeded_registry("google/gemini-3.5-flash-lite"))
        before = self.registry.read_text(encoding="utf-8")
        self.assertEqual(main(self.argv()), 1)
        self.assertEqual(self.registry.read_text(encoding="utf-8"), before)

    def test_write_changes_the_file(self) -> None:
        self.write(seeded_registry("google/gemini-3.5-flash-lite"))
        self.assertEqual(main(self.argv("--write")), 1)
        refreshed = json.loads(self.registry.read_text(encoding="utf-8"))
        self.assertEqual(refreshed["models"][0]["cost_in"], 0.3)
        self.assertEqual(refreshed["models"][0]["name"], "Google: Gemini 3.5 Flash Lite")

    def test_a_second_run_after_write_is_a_no_op(self) -> None:
        self.write(seeded_registry("google/gemini-3.5-flash-lite"))
        main(self.argv("--write"))
        self.assertEqual(main(self.argv()), 0)

    def test_a_kept_id_that_left_the_catalogue_exits_two(self) -> None:
        """Two, not one: a roster that no longer exists is not a price change."""

        self.write(seeded_registry("google/gemini-3.5-flash-lite", "openai/o4-mini"))
        self.assertEqual(main(self.argv()), 2)

    def test_a_departed_id_still_exits_two_when_nothing_else_moved(self) -> None:
        """The no-diff path has to carry the news too, or it reports success."""

        self.write(seeded_registry("openai/o4-mini"))
        main(self.argv("--write"))
        self.assertEqual(main(self.argv()), 2)


class CommittedRegistryTests(unittest.TestCase):
    """The registry this build actually ships, against C3's own rules."""

    def test_the_committed_registry_parses_and_is_within_its_bounds(self) -> None:
        from brief_crew.config import (
            MODEL_PRESETS,
            MODEL_REGISTRY,
            MODEL_REGISTRY_CEILING_IN,
            registry_model,
        )

        self.assertLessEqual(len(MODEL_REGISTRY), 10)
        self.assertGreaterEqual(len(MODEL_REGISTRY), 1)
        for model in MODEL_REGISTRY:
            with self.subTest(model=model.id):
                self.assertLessEqual(model.cost_in, MODEL_REGISTRY_CEILING_IN)
                self.assertGreaterEqual(model.cost_in_max_endpoint, model.cost_in)
        for tier, spelling in MODEL_PRESETS.items():
            with self.subTest(tier=tier):
                self.assertIsNotNone(registry_model(spelling))


if __name__ == "__main__":
    unittest.main()
