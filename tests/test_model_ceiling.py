"""No model above the price ceiling is reachable anywhere in this product.

Plan 05 D9, criteria 5 and 11; gauntlet rubric 13, whose forbidden line is *"a
model above the price ceiling anywhere in the codebase"*.

**This scans the SOURCE, not the registry.** Checking the registry against
itself would prove nothing: `config.py` already refuses an over-ceiling row at
import, so a test that read only `MODEL_REGISTRY` would be green by
construction. What can actually go wrong is a model id typed somewhere else -
a default in a Vue file, a fixture, a `render.yaml` env var, a fallback in a
script - and that is what is walked here.

THE CEILING, and which of the two price columns it reads. The owner ruled on
2026-09-04 that the ceiling is measured against the MAX ENDPOINT price rather
than the headline, and `config.py::openrouter_price_ceiling_params` enforces
exactly that at the API: every escalation request carries `provider.max_price`,
so OpenRouter filters over-ceiling endpoints *before* routing. That ruling has a
consequence this file has to state rather than paper over: **the escalation
preset's own max endpoint is $1.35**. `google/gemini-3.8-flash` is served by six
endpoints and its two `priority` ones bill $1.35/$6.75.

So the two halves of the ruling are enforced as two assertions, and neither is
the other:

* **Admission** - a model is usable only if a servable endpoint survives the
  `max_price` filter, which is `cost_in <= ceiling`, because the headline IS one
  of the slug's endpoints. `openai/o4-mini` has exactly ONE endpoint at $1.10:
  under `max_price` every candidate is filtered and the request fails rather
  than overspending, so it is refused up front. `openai/gpt-5.2` has a $0.88
  `flex` endpoint but a $1.75 headline and is refused the same way.
* **Exposure** - where a row's `cost_in_max_endpoint` is over the ceiling, the
  enforcement has to actually be in force. `test_the_max_price_block_is_what_
  makes_an_over_ceiling_endpoint_safe` asserts the `provider.max_price` body is
  built and carries this same constant, which is the only thing standing between
  "$1.35 is unreachable" and "$1.35 is unreachable because of what nobody
  happens to have set".

**THE EXEMPTIONS, and why an absolute rule is not available.** D9 asks for zero
matches of `anthropic/`. Criterion 4 asks for a test that
`compute_cost_usd("openrouter/anthropic/claude-haiku-4.5", 1, 1)` returns None -
a test that cannot be written without writing that literal. The two cannot both
be satisfied, and pretending otherwise would mean either deleting the criterion-4
test or writing a rule with a hole in it and not saying so.

The resolution is that **a literal asserted to be REFUSED is not a reachable
model**, and the exemption table below is how that claim is made checkable. Each
entry names the literal, the exact paths it may appear in, and the reason. Two
properties make the table a gate rather than a list of excuses: an entry that
matches nothing FAILS (a dead exemption cannot accumulate), and the literal
outside its allowed paths FAILS (so `openai/o4-mini` in a comment in `config.py`
is fine and `openai/o4-mini` in the client's model fixture is not). Adding a
model to the product means adding it to `data/models.json`; adding a line to
this table means arguing, in the table, that it is not a model this product can
select.

No cost: this reads files. No network, no model, no credential.
"""

from __future__ import annotations

import pathlib
import re
import unittest

from brief_crew.config import (
    EMBED_MODEL,
    MODEL_BY_ID,
    MODEL_PRICE_CEILING_IN,
    MODEL_REGISTRY,
    compute_cost_usd,
    openrouter_escalation_params,
    openrouter_price_ceiling_params,
    registry_model,
)

REPO = pathlib.Path(__file__).resolve().parents[1]

#: Everything an author, a deploy or a test can reach. `docs/`, `agents/`,
#: `PRD.md`, `benchmarks/` and `.agent/` are NOT here, deliberately: prose has
#: to be able to name a forbidden model in order to explain the rule, and this
#: plan file is itself under `.agent/`.
ROOTS = (
    "src",
    "frontend/src",
    "frontend/tests",
    "frontend/e2e",
    "tests",
    "data",
    "scripts",
    "render.yaml",
    ".env.example",
)

#: Directories that are build output or third-party code.
SKIP_PARTS = frozenset({"node_modules", "__pycache__", "dist", ".vite", "server-dist"})

#: Files whose bytes are not text this rule is about.
SKIP_SUFFIXES = (".png", ".jpg", ".jpeg", ".svg", ".ico", ".woff", ".woff2", ".db")

#: This file. It is the STATEMENT of the rule, so every forbidden id in it is
#: either a key of the exemption table below or a sentence explaining why that
#: id is forbidden - and a rule that has to grant itself an exemption for each
#: model it names has stopped being readable. Exactly one file, named rather
#: than pattern-matched, so nothing else can slip into the hole.
SELF = "tests/test_model_ceiling.py"

#: The provider slugs OpenRouter actually publishes, so a match is a model id
#: rather than any string with a slash in it.
PROVIDERS = (
    "openai|google|deepseek|qwen|z-ai|moonshotai|anthropic|meta-llama|mistralai"
    "|x-ai|xiaomi|minimax|nvidia|tencent|stepfun|upstage"
)

#: D9's pattern, with one addition it needed and did not have: a left boundary.
#: Without it the scan matched `openai/completion.py` out of a comment naming a
#: LiteLLM source path, and a rule that reports a filename as a frontier model
#: is a rule nobody will keep.
MODEL_LITERAL = re.compile(
    rf"(?<![A-Za-z0-9._/-])(?:openrouter/)?(?:{PROVIDERS})/[a-z0-9.\-]+(?::[a-z]+)?"
)

#: Suffixes that make a match a PATH rather than a model. `openai/completion.py`
#: and `google/generativeai.py` both look exactly like a slug otherwise.
PATH_SUFFIXES = (".py", ".ts", ".tsx", ".vue", ".js", ".json", ".md", ".yml", ".yaml")

#: Model families that must not appear even as an exemption's subject unless the
#: exemption says so explicitly. Each was measured 2026-09-04 and is over the
#: ceiling on EVERY endpoint it has: `openai/o1` $15.00, `openai/o3` $2.00,
#: `openai/gpt-4o` $2.50. `openai/gpt-5.2` is the exception worth naming - its
#: `flex` endpoint is $0.88, UNDER the ceiling, and only its $1.75 headline
#: excludes it. The plan claimed "$1.00+ on every endpoint" for it and that was
#: wrong in the direction that matters: it asserted a stronger guarantee than
#: the endpoint data supports.
#:
#: SPLIT INTO TWO because a prefix test got this wrong on its first run: with
#: `openai/gpt-4o` matched by `startswith`, `openai/gpt-4o-mini` - a ROSTER
#: MODEL at $0.15 - was reported as a forbidden frontier model. A provider is a
#: prefix; a model is an exact id.
FORBIDDEN_PROVIDERS = ("anthropic/",)
FORBIDDEN_IDS = frozenset({"openai/o1", "openai/o3", "openai/gpt-4o", "openai/gpt-5.2"})


#: literal -> (allowed path prefixes, reason). See the module docstring.
EXEMPTIONS: dict[str, tuple[tuple[str, ...], str]] = {
    "google/gemini-3.7-flash": (
        ("src/brief_crew/config.py",),
        "The escalation tier's predecessor, named only inside measurement comments. "
        "config.py keeps them because a measurement of 3.7-flash remains a true "
        "measurement of 3.7-flash, and rewriting the model name in them would "
        "fabricate data this project never collected.",
    ),
    "openai/o4-mini": (
        (
            "src/brief_crew/config.py",
            "scripts/emit_builder_fixtures.py",
            "scripts/refresh_models.py",
            "tests/fixtures/openrouter_catalogue.json",
            "tests/test_refresh_models.py",
            "tests/builder/test_model_gating.py",
            "frontend/tests/fixtures/builderProblemCodes.json",
        ),
        "The worked example of a REFUSED model: one endpoint, $1.10/M input, so "
        "provider.max_price filters every candidate and the request fails rather "
        "than overspending. Every appearance is an assertion that it is refused.",
    ),
    "openai/gpt-4o": (
        ("tests/service/test_app.py",),
        "The non-OpenRouter constant `_assert_openrouter_startup_safety` is proved "
        "to refuse. The test's subject is the missing `openrouter/` prefix; a "
        "frontier model is what makes the refusal worth having.",
    ),
    "openrouter/anthropic/claude-sonnet-4.5": (
        ("tests/events/test_tool_frame_attribution.py",),
        "An LLMCallCompletedEvent for a model PRICES cannot price, proving a token "
        "frame contributes nothing rather than $0.00. Naming a model this product "
        "may not use is the point of the fixture.",
    ),
    "anthropic/claude-haiku-4.5": (
        (
            "tests/fixtures/openrouter_catalogue.json",
            "tests/test_refresh_models.py",
        ),
        "Criterion 4's own subject: compute_cost_usd must answer None for it, and "
        "refresh_models must refuse it by PROVIDER rather than by price - it is "
        "$0.80/M input, which passes the ceiling. Neither claim is writable "
        "without the literal.",
    ),
    "meta-llama/llama-4-scout:free": (
        ("tests/fixtures/openrouter_catalogue.json", "tests/test_refresh_models.py"),
        "A `:free` row in the recorded catalogue, present to prove the variant "
        "clause refuses it.",
    ),
    "openai/gpt-5.2": (
        ("src/brief_crew/config.py",),
        "Named in the registry loader's own comment as the model the ADMISSION "
        "predicate refuses on its $1.75 headline despite a $0.88 flex endpoint. "
        "The reasoning for a refusal has to be able to name what it refuses.",
    ),
    "mistralai/mistral-small-3.2": (
        ("tests/fixtures/openrouter_catalogue.json", "tests/test_refresh_models.py"),
        "A row with no `tools` in the recorded catalogue, present to prove the "
        "capability clause refuses it.",
    ),
}


# DERIVED rather than typed, so an embedding-model swap carries its own
# exemption with it instead of leaving a stale literal behind. This is the only
# entry in the table that is not a string somebody wrote here, and it is the one
# entry that could not go out of date.
EXEMPTIONS[EMBED_MODEL] = (
    ("src/brief_crew/config.py", "src/brief_crew/embeddings.py"),
    "The EMBEDDING model. Embeddings raise no LLM event, so `compute_cost_usd` "
    "never sees one and `budget.py`'s own docstring records them as absent from "
    "every figure this rule is about; plan 05's Scope puts embedding and rerank "
    "models out of scope in as many words.",
)


def _files() -> list[pathlib.Path]:
    found: list[pathlib.Path] = []
    for root in ROOTS:
        path = REPO / root
        if not path.exists():
            continue
        candidates = [path] if path.is_file() else sorted(path.rglob("*"))
        for candidate in candidates:
            if not candidate.is_file():
                continue
            if SKIP_PARTS & set(candidate.parts):
                continue
            if candidate.name.endswith(SKIP_SUFFIXES):
                continue
            if _relative(candidate) == SELF:
                continue
            found.append(candidate)
    return found


def _relative(path: pathlib.Path) -> str:
    return str(path.relative_to(REPO)).replace("\\", "/")


def literals() -> dict[str, set[str]]:
    """Every model-shaped literal in the scanned roots, to the files holding it."""

    found: dict[str, set[str]] = {}
    for path in _files():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for match in MODEL_LITERAL.findall(text):
            if match.endswith(PATH_SUFFIXES):
                continue
            found.setdefault(match, set()).add(_relative(path))
    return found


def _base(literal: str) -> str:
    """A literal reduced to the registry's own spelling: no prefix, no variant."""

    base = literal.removeprefix("openrouter/")
    stem, separator, _ = base.rpartition(":")
    return stem if separator and stem else base


class ModelCeilingTests(unittest.TestCase):
    """Criteria 5 and 11."""

    def setUp(self) -> None:
        self.found = literals()

    def test_every_model_literal_is_a_registry_id_under_the_ceiling(self) -> None:
        """The whole rule, in one assertion, with the file named on failure."""

        offenders: list[str] = []
        for literal, files in sorted(self.found.items()):
            allowed = EXEMPTIONS.get(literal)
            if allowed is not None:
                outside = sorted(
                    name
                    for name in files
                    if not name.startswith(allowed[0] or ("\0",))
                )
                if outside:
                    offenders.append(
                        f"{literal} is exempt only in {list(allowed[0])} and appears in "
                        + ", ".join(outside)
                    )
                continue
            model = registry_model(_base(literal))
            if model is None:
                offenders.append(
                    f"{literal} is not in data/models.json, and appears in "
                    + ", ".join(sorted(files))
                )
            elif model.cost_in > MODEL_PRICE_CEILING_IN:
                offenders.append(
                    f"{literal} is ${model.cost_in}/M input, over the "
                    f"${MODEL_PRICE_CEILING_IN}/M ceiling, and appears in "
                    + ", ".join(sorted(files))
                )
        self.assertEqual(
            offenders,
            [],
            "a model literal in this codebase is not a roster model under the price "
            "ceiling. Add it to data/models.json with scripts/refresh_models.py, or - "
            "if it is a literal whose presence ASSERTS that it is refused - add it to "
            "EXEMPTIONS with the paths it may appear in and the reason",
        )

    def test_no_exemption_is_dead(self) -> None:
        """An exemption that matches nothing is an excuse nobody is using.

        Without this the table only ever grows: every literal removed from the
        codebase would leave its exemption behind, and the next reader would
        take the list as evidence that these models are all still somewhere.
        """

        unused = sorted(
            literal
            for literal, (paths, _reason) in EXEMPTIONS.items()
            if paths and literal not in self.found
        )
        self.assertEqual(
            unused,
            [],
            "these exemptions match nothing in the codebase any more; delete them",
        )

    def test_every_exemption_states_a_reason(self) -> None:
        for literal, (_paths, reason) in EXEMPTIONS.items():
            with self.subTest(literal=literal):
                self.assertGreater(len(reason), 60, "a reason, not a label")

    def test_a_forbidden_family_appears_only_where_an_exemption_names_it(self) -> None:
        """D9's second assertion, as strong as it can honestly be made.

        D9 asks for ZERO matches of `anthropic/`, `openai/o1`, `openai/o3`,
        `openai/gpt-4o` and `openai/gpt-5.2`. Criterion 4's own test needs one of
        them, so the achievable rule is that a forbidden family appears only as
        the subject of a named exemption - never in `src/`, never in a fixture
        the client reads, never in a default.
        """

        # The control for the split above: a roster model whose id BEGINS with a
        # forbidden one must not be caught. This is the bug the first run of this
        # file found in itself.
        self.assertIn("openai/gpt-4o-mini", MODEL_BY_ID)
        self.assertNotIn("openai/gpt-4o-mini", FORBIDDEN_IDS)

        offenders = [
            f"{literal} in {sorted(files)}"
            for literal, files in sorted(self.found.items())
            if (
                _base(literal).startswith(FORBIDDEN_PROVIDERS)
                or _base(literal) in FORBIDDEN_IDS
            )
            and literal not in EXEMPTIONS
        ]
        self.assertEqual(offenders, [], "a forbidden model family with no exemption")

    def test_the_scan_actually_finds_the_roster(self) -> None:
        """A regex that matched nothing would pass every assertion above.

        This is the control. Both preset slugs are written in `config.py` and
        both must be found, or the pattern has stopped seeing model ids and the
        whole file is green over an empty set.
        """

        for model_id in ("google/gemini-3.5-flash-lite", "google/gemini-3.8-flash"):
            with self.subTest(model_id=model_id):
                self.assertIn(model_id, self.found)
        self.assertGreater(len(self.found), 8, "far too few literals; check the pattern")

    def test_a_file_path_is_not_mistaken_for_a_model(self) -> None:
        """`openai/completion.py` is a LiteLLM source path named in a comment."""

        for path_like in ("openai/completion.py", "google/generativeai.py"):
            with self.subTest(path_like=path_like):
                self.assertTrue(MODEL_LITERAL.fullmatch(path_like))
                self.assertTrue(path_like.endswith(PATH_SUFFIXES))
                self.assertNotIn(path_like, self.found)


class RegistryCeilingTests(unittest.TestCase):
    """The registry's own rows, and the enforcement behind the ruling."""

    def test_every_roster_row_is_under_the_ceiling_on_admission(self) -> None:
        for model in MODEL_REGISTRY:
            with self.subTest(model=model.id):
                self.assertLessEqual(model.cost_in, MODEL_PRICE_CEILING_IN)

    def test_the_max_price_block_is_what_makes_an_over_ceiling_endpoint_safe(self) -> None:
        """The other half of the owner's ruling, asserted rather than assumed.

        `google/gemini-3.8-flash` - the escalation preset - bills $1.35/M input
        on its two `priority` endpoints. It is admissible only because
        `provider.max_price` filters them before routing. If that block ever
        stops being sent, or stops carrying THIS constant, a roster row's
        recorded exposure becomes real spend with nothing failing.
        """

        exposed = [
            model.id
            for model in MODEL_REGISTRY
            if model.cost_in_max_endpoint > MODEL_PRICE_CEILING_IN
        ]
        self.assertIn(
            "google/gemini-3.8-flash",
            exposed,
            "the escalation preset's $1.35 priority endpoints are the reason this "
            "assertion exists; if the registry no longer records them, re-measure "
            "rather than delete the test",
        )
        self.assertEqual(
            openrouter_price_ceiling_params(), {"prompt": MODEL_PRICE_CEILING_IN}
        )
        body = openrouter_escalation_params(None)["extra_body"]
        self.assertEqual(body["provider"]["max_price"], {"prompt": MODEL_PRICE_CEILING_IN})

    def test_the_recorded_maximum_is_never_below_the_headline(self) -> None:
        """The headline is one of the slug's endpoints, so max >= headline.

        This is what makes `cost_in <= ceiling` a witness that a servable
        endpoint survives the `max_price` filter, which is the ruling's
        "refused when its CHEAPEST endpoint exceeds the ceiling" read from the
        other side.
        """

        for model in MODEL_REGISTRY:
            with self.subTest(model=model.id):
                self.assertGreaterEqual(model.cost_in_max_endpoint, model.cost_in)

    def test_unknown_model_is_unpriced(self) -> None:
        """Criterion 4. `None`, never 0.0 - the two are different facts.

        "No price on file" reported as "this call was free" is the whole of the
        defect that priced a 128,069-token run at $0.00.
        """

        self.assertIsNone(
            compute_cost_usd("openrouter/anthropic/claude-haiku-4.5", 1, 1)
        )
        self.assertIsNotNone(compute_cost_usd("google/gemini-3.5-flash-lite", 1, 1))

    def test_the_embedding_model_is_deliberately_outside_this_rule(self) -> None:
        """`EMBED_MODEL` is not an LLM and is in no figure this plan produces.

        It raises no LLM event, so `compute_cost_usd` never sees it and the
        budget model cannot include it - `budget.py`'s own docstring says so.
        Exempted by DERIVATION rather than by a literal in the table above, so a
        model swap moves it here automatically.
        """

        self.assertNotIn(EMBED_MODEL, MODEL_BY_ID)
        self.assertIsNone(compute_cost_usd(EMBED_MODEL, 1, 1))


if __name__ == "__main__":
    unittest.main()
