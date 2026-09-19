"""The one model call in this plan, and everything that bounds it (T4).

Plan 21, "Ask a model to review". Three of the four Improve surfaces cost
$0.00; this is the fourth, and it sits behind one explicit admin click with a
ceiling checked at import.

Four claims:

* with `IMPROVE_DIGEST_ENABLED` off the route is **422 and constructs no
  `LLM` at all**, proved by patching the class to raise. 422 and not 403
  because the request is well formed and the caller is allowed; what is
  missing is a deployment setting.
* knob on and the model faked: the prompt comes from
  `digest_crew/config/tasks.yaml` (patch the file, the prompt changes), all
  four bounds apply, `max_tokens` is `DIGEST_MAX_OUTPUT_TOKENS`, the model is
  `CHEAP_MODEL`, the row is stored, and the cost is `compute_cost_usd` over a
  captured `LLMCallCompletedEvent` - the same function the token frame uses,
  so a review's dollars and a run's dollars mean the same thing.
* **R5**: the measured cost is compared with the cap AFTER the call, the
  answer rides the response and the stored row as `over_cap`, and a breach
  logs at WARNING. It cannot be prevented from there - the tokens are spent -
  so what matters is that it is recorded where somebody watching money looks.
* **R2**: no prompt literal in `digest.py`, and **no content in the prompt**.
  A secret planted in a tool's arguments, in an output preview and in an error
  message reaches none of it, and the test fails if the allow-list is removed.

**No test here can reach OpenRouter.** `run_digest` takes an `llm_factory`,
and the route's own tests patch the class the default factory imports, so a
forgotten patch is an `AssertionError` rather than a bill.
"""

from __future__ import annotations

import pathlib
from typing import Any
import unittest
from unittest.mock import patch

import yaml

from brief_crew import config
from brief_crew.service import digest as digest_module
from tests.service.admin_fixtures import ALICE, AdminCase


class FakeLLM:
    """What `run_digest` is given instead of a real one, in every test here."""

    def __init__(self, body: str = "## What went well\n\nThe market node.") -> None:
        self.body = body
        self.calls: list[list[dict[str, str]]] = []
        self.kwargs: dict[str, Any] = {}

    def call(self, messages: list[dict[str, str]]) -> str:
        self.calls.append(messages)
        return self.body


class PromptTests(unittest.TestCase):
    """The prompt is a file, not a literal."""

    def test_the_prompt_is_read_off_disk(self) -> None:
        template = digest_module.load_prompt()
        self.assertIn("system", template)
        self.assertIn("user", template)
        self.assertIn("{hotspots_json}", template["user"])

    def test_patching_the_file_changes_the_prompt(self) -> None:
        """The proof that it is a file and not a module global cached at import."""

        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "tasks.yaml"
            path.write_text(
                yaml.safe_dump(
                    {
                        digest_module.PROMPT_TASK_KEY: {
                            "system": "a different system prompt",
                            "user": "a different user prompt {hotspots_json}",
                        }
                    }
                ),
                encoding="utf-8",
            )
            template = digest_module.load_prompt(path)
        self.assertEqual("a different system prompt", template["system"])

    def test_a_missing_file_is_digest_unavailable_and_not_a_500(self) -> None:
        with self.assertRaises(digest_module.DigestUnavailable):
            digest_module.load_prompt(pathlib.Path("no-such-prompt.yaml"))

    def test_a_file_without_the_task_key_is_refused(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "tasks.yaml"
            path.write_text(yaml.safe_dump({"nothing": "useful"}), encoding="utf-8")
            with self.assertRaises(digest_module.DigestUnavailable):
                digest_module.load_prompt(path)

    def test_no_prompt_sentence_is_written_into_the_python(self) -> None:
        """A28. Sentences taken FROM the YAML, so this cannot pass by luck."""

        source = pathlib.Path(digest_module.__file__).read_text(encoding="utf-8")
        template = digest_module.load_prompt()
        for line in (template["system"] + "\n" + template["user"]).splitlines():
            sentence = line.strip()
            if len(sentence) < 25 or sentence.startswith("{"):
                continue
            with self.subTest(sentence=sentence[:50]):
                self.assertNotIn(sentence, source)

    def test_the_yaml_is_where_the_platform_rule_says(self) -> None:
        self.assertTrue(digest_module.PROMPT_PATH.exists())
        self.assertEqual("tasks.yaml", digest_module.PROMPT_PATH.name)
        self.assertIn("digest_crew", str(digest_module.PROMPT_PATH))


class RenderTests(unittest.TestCase):
    """The whitelist, and what gets shorter when the prompt will not fit."""

    def template(self) -> dict[str, str]:
        return {
            "system": "system: {workflow_name} in {window}",
            "user": "counts {hotspots_json} lessons {lessons_json} sample {sample_json}",
        }

    def test_only_the_five_whitelisted_names_are_addressed(self) -> None:
        self.assertEqual(
            ("workflow_name", "window", "hotspots_json", "lessons_json", "sample_json"),
            digest_module.PROMPT_KEYS,
        )

    def test_a_brace_inside_mined_data_survives_as_itself(self) -> None:
        """Mined data reaches the template as JSON, and JSON is full of braces.

        A plain `format` would raise on the first one and a `defaultdict`
        would blank it; this leaves the text as it was written.
        """

        system, user, _truncated = digest_module.render_prompt(
            {"system": "{workflow_name}", "user": "{unknown_key} {hotspots_json}"},
            workflow_name="a workflow",
            window="a window",
            hotspots={"query": "who said {foo}?"},
            lessons=[],
            sample=[],
        )
        self.assertEqual("a workflow", system)
        self.assertIn("{unknown_key}", user)
        self.assertIn("{foo}", user)

    def test_the_sample_is_what_gets_shorter(self) -> None:
        """A judgement, and it is the right way round: the mined counts and the
        deterministic lessons are what the review is asked to read across."""

        sample = [{"run_id": f"r-{index}", "frames": ["x" * 400]} for index in range(20)]
        system, user, truncated = digest_module.render_prompt(
            self.template(),
            workflow_name="w",
            window="win",
            hotspots={"agents": []},
            lessons=["a lesson"],
            sample=sample,
            max_chars=800,
        )
        self.assertTrue(truncated)
        self.assertLessEqual(len(system) + len(user), 800)
        self.assertIn("a lesson", user)

    def test_sample_runs_are_dropped_whole(self) -> None:
        """The model never sees half a run."""

        import json

        sample = [{"run_id": f"r-{index}", "frames": []} for index in range(10)]
        _system, user, _truncated = digest_module.render_prompt(
            self.template(),
            workflow_name="w",
            window="win",
            hotspots={},
            lessons=[],
            sample=sample,
            max_chars=200,
        )
        remaining = user.split("sample ", 1)[1]
        self.assertIsInstance(json.loads(remaining), list)


class BuildSampleTests(unittest.TestCase):
    def rows(self, count: int) -> list[dict[str, Any]]:
        return [
            {"run_id": f"r-{index}", "status": "completed", "rating": None}
            for index in range(count)
        ]

    def frames(self, run_ids: list[str], kind: str = "agent") -> list[dict[str, Any]]:
        return [
            {"run_id": run_id, "kind": kind, "node_id": "n1", "message": "m", "details": {}}
            for run_id in run_ids
        ]

    def test_the_run_cap_is_the_constant(self) -> None:
        sample, truncated = digest_module.build_sample(
            self.rows(config.DIGEST_MAX_SAMPLE_RUNS + 3), []
        )
        self.assertEqual(config.DIGEST_MAX_SAMPLE_RUNS, len(sample))
        self.assertTrue(truncated)

    def test_the_frame_cap_is_the_constant(self) -> None:
        rows = self.rows(2)
        frames = self.frames(["r-0"] * 10)
        sample, truncated = digest_module.build_sample(rows, frames, max_frames=4)
        kept = sum(len(row["frames"]) for row in sample)
        self.assertEqual(4, kept)
        self.assertTrue(truncated)

    def test_frames_are_attached_to_the_run_they_belong_to(self) -> None:
        """"Which run was that in" is the first question a reader asks."""

        rows = self.rows(2)
        frames = self.frames(["r-0", "r-1", "r-1"])
        sample, _truncated = digest_module.build_sample(rows, frames)
        by_run = {row["run_id"]: row for row in sample}
        self.assertEqual(1, len(by_run["r-0"]["frames"]))
        self.assertEqual(2, len(by_run["r-1"]["frames"]))

    def test_only_the_five_evidence_kinds_are_sampled(self) -> None:
        """Everything else is plumbing and would spend the budget saying a
        node started."""

        rows = self.rows(1)
        frames = self.frames(["r-0"], kind="node_state") + self.frames(["r-0"])
        sample, _truncated = digest_module.build_sample(rows, frames)
        self.assertEqual(1, len(sample[0]["frames"]))
        self.assertEqual("agent", sample[0]["frames"][0]["kind"])


class RunDigestTests(unittest.TestCase):
    """The function, with a fake model and a real event."""

    def run_it(self, llm: FakeLLM) -> digest_module.DigestResult:
        with patch.object(config, "IMPROVE_DIGEST_ENABLED", True):
            return digest_module.run_digest(
                workflow_name="A workflow",
                window="a window",
                hotspots={"agents": []},
                lessons=["a lesson"],
                sample=[{"run_id": "r-1", "frames": []}],
                sample_frames=0,
                llm_factory=lambda _model: llm,
            )

    def test_the_knob_off_raises_before_any_model_is_constructed(self) -> None:
        def explode(_model: str) -> None:
            raise AssertionError("an LLM was constructed with the knob off")

        with patch.object(config, "IMPROVE_DIGEST_ENABLED", False):
            with self.assertRaises(digest_module.DigestUnavailable) as caught:
                digest_module.run_digest(
                    workflow_name="w",
                    window="win",
                    hotspots={},
                    lessons=[],
                    sample=[],
                    llm_factory=explode,
                )
        self.assertIn("IMPROVE_DIGEST_ENABLED", str(caught.exception))

    def test_the_model_is_the_cheap_tier(self) -> None:
        result = self.run_it(FakeLLM())
        self.assertEqual(config.CHEAP_MODEL, result.model)

    def test_the_two_messages_are_the_system_and_the_user_halves(self) -> None:
        llm = FakeLLM()
        self.run_it(llm)
        messages = llm.calls[0]
        self.assertEqual(["system", "user"], [item["role"] for item in messages])
        self.assertIn("a lesson", messages[1]["content"])

    def test_the_body_is_the_models_answer(self) -> None:
        result = self.run_it(FakeLLM("## What is failing\n\nnothing"))
        self.assertIn("What is failing", result.body)

    def test_the_cost_is_priced_from_a_captured_token_event(self) -> None:
        """The event the frame pipeline reads, through the function it uses."""

        llm = FakeLLM()
        meter = digest_module._TokenMeter(config.CHEAP_MODEL)
        meter.absorb({"prompt_tokens": 4000, "completion_tokens": 600})
        with patch.object(digest_module, "_TokenMeter", lambda _model: meter):
            result = self.run_it(llm)
        self.assertEqual(4000, result.prompt_tokens)
        self.assertEqual(600, result.completion_tokens)
        self.assertEqual(
            config.compute_cost_usd(config.CHEAP_MODEL, 4000, 600), result.cost_usd
        )

    def test_a_call_that_raised_no_event_costs_zero_tokens_not_a_guess(self) -> None:
        result = self.run_it(FakeLLM())
        self.assertEqual(0, result.prompt_tokens)
        self.assertEqual(0, result.completion_tokens)

    def test_the_default_factory_asks_for_max_tokens(self) -> None:
        """A completion with no bound has no price, and the ceiling rests on
        this argument."""

        seen: dict[str, Any] = {}

        class Recorder:
            def __init__(self, **kwargs: Any) -> None:
                seen.update(kwargs)

        import crewai

        with patch.object(crewai, "LLM", Recorder):
            digest_module._default_llm(config.CHEAP_MODEL)
        self.assertEqual(config.DIGEST_MAX_OUTPUT_TOKENS, seen["max_tokens"])
        self.assertEqual(config.CHEAP_MODEL, seen["model"])


class DigestRouteTests(AdminCase):
    """The route a person actually clicks."""

    WORKFLOW = "ug_digest001"

    def setUp(self) -> None:
        super().setUp()
        self.seed_run("digest-run-1", user_id=ALICE.id, workflow_id=self.WORKFLOW)

    def post(self) -> Any:
        return self.client.post(
            f"/api/admin/improve/digests?workflow_id={self.WORKFLOW}",
            headers=self.as_admin(),
        )

    def test_the_knob_off_is_422_and_constructs_no_llm(self) -> None:
        import crewai

        def explode(*_args: object, **_kwargs: object) -> None:
            raise AssertionError("an LLM was constructed with the knob off")

        with patch.object(config, "IMPROVE_DIGEST_ENABLED", False), patch.object(
            crewai, "LLM", explode
        ):
            response = self.post()
        self.assertEqual(response.status_code, 422, response.text)
        self.assertIn("IMPROVE_DIGEST_ENABLED", response.text)

    def test_a_get_never_generates(self) -> None:
        """The money rule: never on page load, never on a `GET`."""

        import crewai

        def explode(*_args: object, **_kwargs: object) -> None:
            raise AssertionError("a GET generated a digest")

        with patch.object(config, "IMPROVE_DIGEST_ENABLED", True), patch.object(
            crewai, "LLM", explode
        ):
            body = self.ok(f"/improve/digests?workflow_id={self.WORKFLOW}")
        self.assertEqual([], body["rows"])
        self.assertTrue(body["enabled"])

    def test_the_get_carries_everything_needed_to_draw_the_button(self) -> None:
        body = self.ok(f"/improve/digests?workflow_id={self.WORKFLOW}")
        self.assertEqual(config.CHEAP_MODEL, body["model"])
        self.assertEqual(config.DIGEST_MAX_COST_USD, body["max_cost_usd"])
        self.assertEqual(config.DIGEST_MAX_SAMPLE_RUNS, body["max_sample_runs"])
        self.assertEqual(config.DIGEST_MAX_SAMPLE_FRAMES, body["max_sample_frames"])
        # R5: all FOUR bounds, so the panel can state the whole of what
        # one click may spend before anybody presses it.
        self.assertEqual(config.DIGEST_MAX_INPUT_CHARS, body["max_input_chars"])
        self.assertEqual(
            config.DIGEST_MAX_OUTPUT_TOKENS, body["max_output_tokens"]
        )
        self.assertFalse(body["enabled"])

    def test_a_generated_digest_is_stored_and_read_back(self) -> None:
        llm = FakeLLM("## What to change first\n\nThe market node.")
        with patch.object(config, "IMPROVE_DIGEST_ENABLED", True), patch.object(
            digest_module, "_default_llm", lambda _model: llm
        ):
            with self.assertLogs("brief_crew.service.improve_api", level="WARNING"):
                response = self.post()
        self.assertEqual(response.status_code, 200, response.text)
        created = response.json()
        self.assertIn("What to change first", created["body"])
        self.assertEqual(config.CHEAP_MODEL, created["model"])
        self.assertEqual(config.DIGEST_MAX_COST_USD, created["max_cost_usd"])

        stored = self.ok(f"/improve/digests?workflow_id={self.WORKFLOW}")
        self.assertEqual([created["id"]], [row["id"] for row in stored["rows"]])

    def test_the_stored_row_reaches_the_workflows_total(self) -> None:
        """The audit's amendment: a digest has no `run_id`, so without this it
        reaches no money figure in the product at all."""

        from datetime import datetime, timezone
        from decimal import Decimal

        self.store.save_digest(
            {
                "id": "dg_0001",
                "workflow_id": self.WORKFLOW,
                "created_by": "user_admin",
                "window_from": datetime.now(timezone.utc),
                "window_to": datetime.now(timezone.utc),
                "sample_runs": 1,
                "sample_frames": 0,
                "truncated_sample": False,
                "model": config.CHEAP_MODEL,
                "prompt_tokens": 4000,
                "completion_tokens": 600,
                "cost_usd": Decimal("0.0121"),
                "body": "a review",
                "created_at": datetime.now(timezone.utc),
            }
        )
        body = self.ok(f"/improve/digests?workflow_id={self.WORKFLOW}")
        self.assertEqual(0.0121, body["total_cost_usd"])

    def test_a_review_inside_the_cap_is_not_flagged(self) -> None:
        """The control for the two below: a flag that is always true says
        nothing."""

        llm = FakeLLM()
        with patch.object(config, "IMPROVE_DIGEST_ENABLED", True), patch.object(
            digest_module, "_default_llm", lambda _model: llm
        ):
            with self.assertLogs("brief_crew.service.improve_api", level="WARNING"):
                created = self.post().json()
        self.assertFalse(created["over_cap"])

    def test_a_review_over_the_cap_is_flagged_and_warned_about(self) -> None:
        """R5. The tokens are already spent by the time this is known, so
        the whole value of the check is that it is RECORDED - on the
        response, on the stored row, and in the log a person watching
        money reads.
        """

        llm = FakeLLM()
        with patch.object(config, "IMPROVE_DIGEST_ENABLED", True), patch.object(
            config, "DIGEST_MAX_COST_USD", 0.0
        ), patch.object(
            digest_module,
            "run_digest",
            lambda **_kwargs: digest_module.DigestResult(
                body="a review",
                model=config.CHEAP_MODEL,
                prompt_tokens=10,
                completion_tokens=5,
                cost_usd=0.9,
            ),
        ):
            with self.assertLogs(
                "brief_crew.service.improve_api", level="WARNING"
            ) as caught:
                response = self.post()
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["over_cap"])
        blob = "\n".join(caught.output)
        self.assertIn("over the", blob)
        self.assertIn("DIGEST_MAX_COST_USD", blob)
        # And it SURVIVES the round trip, so a row read back after
        # somebody lowered the cap still says what was true when it ran.
        stored = self.ok(f"/improve/digests?workflow_id={self.WORKFLOW}")
        self.assertTrue(stored["rows"][0]["over_cap"])

    def test_an_unpriced_review_is_not_flagged_over_the_cap(self) -> None:
        """`None` is "no price on file", not "more than the cap".

        Treating an unknown cost as a breach would cry wolf on every model
        that happens to be missing from `PRICES`, and treating it as zero
        is the defect that once priced 128,069 real tokens at $0.00. It is
        neither: the figure is absent and the flag is false.
        """

        with patch.object(config, "IMPROVE_DIGEST_ENABLED", True), patch.object(
            digest_module,
            "run_digest",
            lambda **_kwargs: digest_module.DigestResult(
                body="a review", model="openrouter/x/unpriced", cost_usd=None
            ),
        ):
            with self.assertLogs("brief_crew.service.improve_api", level="WARNING"):
                created = self.post().json()
        self.assertIsNone(created["cost_usd"])
        self.assertFalse(created["over_cap"])

    def test_the_route_is_404_to_a_non_admin(self) -> None:
        response = self.client.post(
            f"/api/admin/improve/digests?workflow_id={self.WORKFLOW}",
            headers=self.as_alice(),
        )
        self.assertEqual(response.status_code, 404, response.text)

    def test_generating_logs_one_warning_naming_the_actor(self) -> None:
        llm = FakeLLM()
        with patch.object(config, "IMPROVE_DIGEST_ENABLED", True), patch.object(
            digest_module, "_default_llm", lambda _model: llm
        ):
            with self.assertLogs(
                "brief_crew.service.improve_api", level="WARNING"
            ) as caught:
                self.post()
        self.assertIn("admin@example.test", "\n".join(caught.output))


class NoContentReachesThePromptTests(unittest.TestCase):
    """R2, and it is the test `tasks.yaml`'s own sentence rests on.

    The prompt file tells the model it is seeing structural facts only and
    that anything a person or a model typed was withheld before the prompt
    was built. That was a hope until `build_sample` grew an allow-list;
    this is what makes it a claim.

    Three plants, in the three places content actually lives on a frame:
    a tool's ARGUMENTS, a task's OUTPUT PREVIEW, and an error MESSAGE. The
    first two must vanish entirely. The third is the one free-text field
    the ruling permits, so it survives - BOUNDED and scrubbed - and a
    separate test proves the scrub rather than leaving it to inspection.

    **It fails if the allow-list is removed**, which is asserted here
    rather than believed: the last test widens `SAMPLE_DETAIL_KEYS` to
    everything and watches the secret arrive.
    """

    PLANTED_ARG = "an-argument-nobody-should-see"
    PLANTED_ANSWER = "the answer the model wrote out in full"
    PLANTED_ERROR_SECRET = "sk-or-v1-0123456789abcdef-NEVER-IN-A-PROMPT"

    def world(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        runs = [{"run_id": "r-0", "status": "failed", "rating": "bad"}]
        frames = [
            {
                "run_id": "r-0",
                "kind": "tool",
                "node_id": "n1",
                "message": f"searched for {self.PLANTED_ARG}",
                "details": {
                    "stage": "after",
                    "tool": "market_research",
                    "tool_status": "empty",
                    "result_count": 0,
                    "query": self.PLANTED_ARG,
                    "args": {"q": self.PLANTED_ARG},
                    "output": self.PLANTED_ARG,
                },
            },
            {
                "run_id": "r-0",
                "kind": "agent",
                "node_id": "n1",
                "message": "a task completed",
                "details": {
                    "stage": "after",
                    "task": "verify",
                    "task_name": "verify",
                    "tool_failure_count": 2,
                    "output_preview": self.PLANTED_ANSWER,
                    "output_json": {"body": self.PLANTED_ANSWER},
                    "expected_output_preview": self.PLANTED_ANSWER,
                },
            },
            {
                "run_id": "r-0",
                "kind": "error",
                "node_id": "n1",
                "message": "it failed",
                "details": {
                    "stage": "error",
                    "error_class": "BadRequestError",
                    "error": (
                        "the provider refused, key "
                        + self.PLANTED_ERROR_SECRET
                        + " "
                        + "x" * 4000
                    ),
                },
            },
        ]
        return runs, frames

    def prompt(self, **overrides: Any) -> str:
        """The RENDERED prompt, both halves, as the model would see it."""

        runs, frames = self.world()
        sample, _truncated = digest_module.build_sample(runs, frames)
        hotspots = overrides.pop(
            "hotspots",
            {
                "tools": [
                    {
                        "tool": "market_research",
                        "calls": 1,
                        "queries_sample": [self.PLANTED_ARG],
                    }
                ]
            },
        )
        system, user, _cut = digest_module.render_prompt(
            digest_module.load_prompt(),
            workflow_name="a workflow",
            window="a window",
            hotspots=hotspots,
            lessons=[],
            sample=sample,
        )
        return system + user

    def test_a_tools_arguments_reach_no_part_of_the_prompt(self) -> None:
        self.assertNotIn(self.PLANTED_ARG, self.prompt())

    def test_the_models_own_answer_reaches_no_part_of_the_prompt(self) -> None:
        self.assertNotIn(self.PLANTED_ANSWER, self.prompt())

    def test_the_frames_message_is_not_carried_at_all(self) -> None:
        """The serializer writes it as a sentence for a person, and a
        sentence about a tool can hold the tool's own words."""

        self.assertNotIn("searched for", self.prompt())

    def test_a_queries_sample_in_the_mined_counts_is_dropped_too(self) -> None:
        """The one non-structural key a hotspots payload carries.

        A query is a tool argument by another name, and the panel showing
        an author their own workflow's queries is not the same act as
        sending them to an inference provider.
        """

        self.assertNotIn("queries_sample", self.prompt())

    def test_the_structural_counts_DO_reach_it(self) -> None:
        """The control. A `build_sample` that dropped everything would pass
        every assertion above and produce a review about nothing."""

        rendered = self.prompt()
        for fragment in (
            "market_research",
            "tool_status",
            "tool_failure_count",
            "BadRequestError",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, rendered)

    def test_node_models_reaches_the_prompt_and_is_only_names(self) -> None:
        """It is structural, so it stays - and that is checked, not assumed.

        A node id, the author's label and model slugs are names; a count
        is a count. A review blind to which tier a node ran on cannot say
        anything useful about cost, so the exemption is worth having - but
        only while the field really carries nothing else.
        """

        hotspots = {
            "node_models": [
                {
                    "node_id": "market_research",
                    "label": "Market research",
                    "models": ["openrouter/a/cheap", "openrouter/b/dear"],
                    "runs": 9,
                }
            ]
        }
        rendered = self.prompt(hotspots=hotspots)
        self.assertIn("openrouter/a/cheap", rendered)
        self.assertIn("Market research", rendered)
        self.assertNotIn(self.PLANTED_ARG, rendered)
        self.assertNotIn(self.PLANTED_ANSWER, rendered)

    def test_the_error_message_survives_bounded_and_scrubbed(self) -> None:
        """The one free text the ruling permits, on its two conditions.

        An error a person cannot read is an error nobody can act on, so it
        is carried - and it is exactly where a credential tends to hide,
        so it is bounded and passed through the same scrub the eval-set
        export uses.
        """

        runs, frames = self.world()
        sample, _truncated = digest_module.build_sample(runs, frames)
        errors = [
            frame
            for frame in sample[0]["frames"]
            if frame["kind"] == "error"
        ]
        message = errors[0]["details"]["error"]
        self.assertLessEqual(len(message), digest_module.SAMPLE_ERROR_CHARS)
        self.assertNotIn(self.PLANTED_ERROR_SECRET, message)
        self.assertIn("the provider refused", message)

    def test_it_fails_when_the_allow_list_is_removed(self) -> None:
        """The assertion that makes the six above mean something.

        Widen the list to everything and the planted argument arrives. A
        privacy test that cannot be made to fail is a comment.
        """

        everything = frozenset(
            digest_module.SAMPLE_DETAIL_KEYS
            | {"query", "args", "output", "output_preview"}
        )
        with patch.object(digest_module, "SAMPLE_DETAIL_KEYS", everything):
            self.assertIn(self.PLANTED_ARG, self.prompt())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
