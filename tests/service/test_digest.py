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

from datetime import datetime, timedelta, timezone
import pathlib
import threading
import time
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


def _emit(*, prompt: int, completion: int) -> None:
    """One REAL `LLMCallCompletedEvent` on the REAL process-wide bus."""

    from crewai.events import LLMCallCompletedEvent, crewai_event_bus

    crewai_event_bus.emit(
        None,
        LLMCallCompletedEvent.model_construct(
            type="llm_call_completed",
            messages=[],
            response="ok",
            call_type="llm",
            usage={"prompt_tokens": prompt, "completion_tokens": completion},
        ),
    )


def _handler_count() -> int:
    """How many handlers the bus holds for the event the meter listens on."""

    from crewai.events import LLMCallCompletedEvent, crewai_event_bus

    return len(
        crewai_event_bus._sync_handlers.get(LLMCallCompletedEvent, ())
    ) + len(crewai_event_bus._async_handlers.get(LLMCallCompletedEvent, ()))


class EmittingLLM(FakeLLM):
    """A fake that raises the event a real one raises, on this thread."""

    def __init__(self, *, prompt: int = 0, completion: int = 0) -> None:
        super().__init__()
        self.prompt = prompt
        self.completion = completion

    def call(self, messages: list[dict[str, str]]) -> str:
        body = super().call(messages)
        _emit(prompt=self.prompt, completion=self.completion)
        return body


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


class PromptCeilingTests(unittest.TestCase):
    """D4: the rendered prompt NEVER exceeds `DIGEST_MAX_INPUT_CHARS`.

    It was measured at **51,533 characters against a 40,000 ceiling, with
    `truncated=False`** - because only `sample` was shrinking. The figure is
    not cosmetic: `worst_case_digest_cost()` prices exactly that ceiling, so a
    prompt over it is a bill over the cap checked at import.
    """

    def big_hotspots(self) -> dict[str, Any]:
        return {
            "workflow_id": "ug_big00001",
            "agents": [
                {
                    "agent_role": f"role number {index}",
                    "node_id": f"node_{index}",
                    "node_label": f"A node called {index}",
                    "runs": index,
                    "executions": index,
                    "llm_calls": index * 3,
                    "cost_usd": 0.01 * index,
                    "error_classes": [f"ErrorClass{index}"] * 6,
                }
                for index in range(400)
            ],
            "tools": [
                {"tool": f"tool_{index}", "node_id": f"node_{index}", "calls": index}
                for index in range(400)
            ],
        }

    def render(self, **overrides: Any) -> tuple[str, str, bool]:
        return digest_module.render_prompt(
            digest_module.load_prompt(),
            workflow_name="a workflow",
            window="a window",
            hotspots=overrides.pop("hotspots", self.big_hotspots()),
            lessons=[],
            sample=overrides.pop("sample", []),
            **overrides,
        )

    def test_a_large_payload_is_cut_to_the_ceiling(self) -> None:
        system, user, truncated = self.render()
        self.assertLessEqual(len(system) + len(user), config.DIGEST_MAX_INPUT_CHARS)
        self.assertTrue(truncated)

    def test_the_control_a_small_payload_is_untouched(self) -> None:
        """Without this the assertion above would pass on a renderer that
        always clipped, and every review would be made over a stub."""

        system, user, truncated = self.render(hotspots={"agents": [{"runs": 1}]})
        self.assertFalse(truncated)
        self.assertIn("MINED COUNTS", user)

    def test_the_sample_goes_before_the_counts_do(self) -> None:
        """The order is a judgement: the counts are what the review reads
        across, and raw frames are the cheapest thing to lose."""

        sample = [
            {"run_id": f"r-{index}", "frames": [{"kind": "agent"}] * 900}
            for index in range(12)
        ]
        _system, user, truncated = self.render(
            hotspots={"agents": [{"node_id": "n1", "runs": 1}]}, sample=sample
        )
        self.assertTrue(truncated)
        self.assertIn('"node_id":"n1"', user)

    def test_it_holds_even_against_a_ceiling_smaller_than_the_template(self) -> None:
        """The last-resort clip. A clipped prompt is worth more than a
        refusal at the moment somebody clicks."""

        system, user, truncated = self.render(max_chars=200)
        self.assertLessEqual(len(system) + len(user), 200)
        self.assertTrue(truncated)


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
        """A REAL event on the REAL bus, raised from inside the call.

        Not `meter.absorb(...)` from the outside: the meter is now inert
        outside its own block, and a test that poked it directly would pass
        over a meter that never registered a handler at all.
        """

        result = self.run_it(EmittingLLM(prompt=4000, completion=600))
        self.assertEqual(4000, result.prompt_tokens)
        self.assertEqual(600, result.completion_tokens)
        self.assertEqual(
            config.compute_cost_usd(config.CHEAP_MODEL, 4000, 600), result.cost_usd
        )

    def test_the_bus_is_left_exactly_as_it_was_found(self) -> None:
        """D1, and it was MEASURED wrong: 1 -> 2 -> 3 -> 4 over three reviews.

        The bus is a process-wide singleton, so a listener left behind is not
        a slow leak - it is a permanent one, and every later review paid a
        little more of somebody else's usage.
        """

        before = _handler_count()
        for _ in range(3):
            self.run_it(EmittingLLM(prompt=10, completion=5))
        self.assertEqual(before, _handler_count())

    def test_an_event_after_the_block_is_not_counted(self) -> None:
        """The exited meter absorbed one, measured. Now it is inert."""

        llm = EmittingLLM(prompt=10, completion=5)
        result = self.run_it(llm)
        self.assertEqual(10, result.prompt_tokens)
        _emit(prompt=999, completion=999)
        self.assertEqual(10, result.prompt_tokens)

    def test_another_threads_completion_is_not_counted(self) -> None:
        """A paid run in a registry worker must not be billed to a review.

        The event is delivered on the thread that emitted it, so the
        discriminator is the thread identity taken at `__enter__`. Without it
        a concurrent run inflated `cost_usd` and could set a false
        `over_cap` - a money figure made wrong by something the review had
        nothing to do with.
        """

        import threading

        class ConcurrentLLM(EmittingLLM):
            def call(self, messages: list[dict[str, str]]) -> str:
                worker = threading.Thread(
                    target=_emit, kwargs={"prompt": 50_000, "completion": 50_000}
                )
                worker.start()
                worker.join()
                return super().call(messages)

        result = self.run_it(ConcurrentLLM(prompt=10, completion=5))
        self.assertEqual(10, result.prompt_tokens)
        self.assertEqual(5, result.completion_tokens)

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

    def test_a_key_planted_in_a_node_label_is_scrubbed(self) -> None:
        """D8: a label is the ONE string here a person typed.

        Every other key on these payloads is a name this program chose, a code
        or a number. A label is carried because a review that cannot name a
        node is useless, so it is bounded and scrubbed rather than dropped.
        """

        secret = "sk-or-v1-0123456789abcdef-IN-A-NODE-LABEL"
        rendered = self.prompt(
            hotspots={
                "agents": [
                    {"node_id": "n1", "node_label": f"Market ({secret})", "runs": 1}
                ],
                "node_models": [
                    {"node_id": "n1", "label": f"Market ({secret})", "models": ["m"]}
                ],
            }
        )
        self.assertNotIn(secret, rendered)
        self.assertIn("Market", rendered)

    def test_a_node_label_is_bounded_before_it_is_scrubbed(self) -> None:
        """Bounded first so the scrub runs over a short string; scrubbed after
        so a key inside the first forty characters is still found."""

        long_label = "L" * (config.MAX_PROMPT_LABEL_CHARS + 60)
        cleaned = digest_module.structural_hotspots(
            {"agents": [{"node_label": long_label}]}, ()
        )
        self.assertEqual(
            config.MAX_PROMPT_LABEL_CHARS,
            len(cleaned["agents"][0]["node_label"]),
        )

    def test_a_key_planted_in_a_sampled_frames_label_is_scrubbed(self) -> None:
        """The other door: `node_label` is in the frame allow-list too."""

        secret = "sk-or-v1-0123456789abcdef-IN-A-FRAME-LABEL"
        runs = [{"run_id": "r-0", "status": "completed", "rating": None}]
        frames = [
            {
                "run_id": "r-0",
                "kind": "agent",
                "node_id": "n1",
                "message": "m",
                "details": {"stage": "before", "task": "t", "node_label": secret},
            }
        ]
        sample, _truncated = digest_module.build_sample(runs, frames)
        self.assertNotIn(secret, repr(sample))

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


class SlowLLM(FakeLLM):
    """A fake that takes a second, the way a real generation does."""

    def __init__(self, seconds: float, started: "threading.Event") -> None:
        super().__init__()
        self.seconds = seconds
        self.started = started

    def call(self, messages: list[dict[str, str]]) -> str:
        self.started.set()
        time.sleep(self.seconds)
        return super().call(messages)


class TheLoopIsNotParkedTests(AdminCase):
    """D2: every Improve handler is `def`, so FastAPI threadpools it.

    Measured elsewhere in this repository at **2.012 s against 0.112 s** for a
    concurrent `GET /healthz` when a blocking handler was spelled `async def`.
    The POST is the worst of the four: it makes a network call to a model, so
    on the loop it parks every other request in the process for the length of
    somebody else's generation.

    A `TestClient` used as a CONTEXT MANAGER runs one event loop for its
    lifetime - which is the whole question here. Used per request it spins a
    fresh portal each time and two separate loops could not show this either
    way.
    """

    SLEEP_SECONDS = 1.0
    #: Well under the sleep, and far above what an in-process GET costs.
    RESPONSIVE_SECONDS = 0.5

    WORKFLOW = "ug_loop00001"

    def setUp(self) -> None:
        super().setUp()
        self.seed_run("loop-run-1", user_id=ALICE.id, workflow_id=self.WORKFLOW)

    def test_a_concurrent_request_is_served_while_a_review_is_running(self) -> None:
        from fastapi.testclient import TestClient

        started = threading.Event()
        llm = SlowLLM(self.SLEEP_SECONDS, started)
        with patch.object(config, "IMPROVE_DIGEST_ENABLED", True), patch.object(
            digest_module, "_default_llm", lambda _model: llm
        ):
            with TestClient(self.app) as client:
                outcome: list[object] = []

                def review() -> None:
                    outcome.append(
                        client.post(
                            f"/api/admin/improve/digests?workflow_id={self.WORKFLOW}",
                            headers=self.as_admin(),
                        )
                    )

                worker = threading.Thread(target=review, daemon=True)
                worker.start()
                self.assertTrue(
                    started.wait(timeout=10), "the model was never called"
                )
                began = time.monotonic()
                health = client.get("/healthz")
                elapsed = time.monotonic() - began
                worker.join(timeout=30)

        self.assertEqual(200, health.status_code, health.text)
        self.assertLess(
            elapsed,
            self.RESPONSIVE_SECONDS,
            f"the loop was parked: GET /healthz took {elapsed:.2f}s while one "
            f"review held the model for {self.SLEEP_SECONDS}s",
        )
        self.assertEqual(200, outcome[0].status_code, outcome[0].text)

    def test_every_improve_handler_is_a_sync_def(self) -> None:
        """The property, read off the app rather than off the source.

        A route added later as `async def` would pass the timing test above
        whenever its own work happened to be fast, and fail production the
        first time it was not.
        """

        import inspect

        def walk(routes: object) -> list[object]:
            found: list[object] = []
            for route in routes:  # type: ignore[union-attr]
                # An included router is a node, not a leaf: FastAPI wraps it
                # in an `_IncludedRouter` whose own `routes` is EMPTY and
                # whose `original_router` holds them, so a flat scan of
                # `app.routes` finds none of these paths and the assertion
                # would pass on zero - which the `checked` count below is the
                # guard against.
                nested = getattr(
                    getattr(route, "original_router", None), "routes", None
                ) or getattr(route, "routes", None)
                if nested:
                    found.extend(walk(nested))
                if hasattr(route, "endpoint"):
                    found.append(route)
            return found

        checked = 0
        for route in walk(self.app.routes):
            path = getattr(route, "path", "")
            if "/improve/" not in path and not path.endswith("/export/evalset"):
                continue
            checked += 1
            with self.subTest(path=path, method=sorted(route.methods)):
                self.assertFalse(
                    inspect.iscoroutinefunction(route.endpoint),
                    f"{path} is async and does blocking work",
                )
        self.assertEqual(5, checked)


class MoneyBrakeTests(AdminCase):
    """D3: three server-side brakes on the one route that spends.

    MEASURED without them: **twenty POSTs produced twenty model calls and no
    refusal.** `IMPROVE_DIGEST_ENABLED` is a deployment switch, not a rate
    limit, and `RUN_RATE_LIMIT_MAX_RUNS` is on a different endpoint.
    """

    WORKFLOW = "ug_brake00001"

    def setUp(self) -> None:
        super().setUp()
        self.seed_run("brake-run-1", user_id=ALICE.id, workflow_id=self.WORKFLOW)

    def post(self, workflow_id: str | None = None) -> Any:
        return self.client.post(
            f"/api/admin/improve/digests?workflow_id={workflow_id or self.WORKFLOW}",
            headers=self.as_admin(),
        )

    def review(self, workflow_id: str | None = None) -> Any:
        with patch.object(config, "IMPROVE_DIGEST_ENABLED", True), patch.object(
            digest_module, "_default_llm", lambda _model: FakeLLM()
        ):
            with self.assertLogs("brief_crew.service.improve_api", level="WARNING"):
                return self.post(workflow_id)

    def seed_attempts(self, count: int, *, workflow_id: str = "ug_other00001") -> None:
        """Rows straight into the table - the brake counts rows, not calls."""

        moment = datetime.now(timezone.utc) - timedelta(minutes=1)
        for index in range(count):
            self.store.save_digest(
                {
                    "id": f"dg_seed{index:04d}",
                    "workflow_id": workflow_id,
                    "created_by": "user_admin",
                    "window_from": moment,
                    "window_to": moment,
                    "model": config.CHEAP_MODEL,
                    "cost_usd": 0.004,
                    "over_cap": False,
                    "error": None,
                    "body": "a review",
                    "created_at": moment,
                }
            )

    # -- (a) one at a time --------------------------------------------------

    def test_a_second_review_while_one_runs_is_429(self) -> None:
        from brief_crew.service import improve_api

        improve_api._DIGEST_IN_FLIGHT.acquire()
        self.addCleanup(improve_api._DIGEST_IN_FLIGHT.release)
        with patch.object(config, "IMPROVE_DIGEST_ENABLED", True):
            response = self.post()
        self.assertEqual(429, response.status_code, response.text)
        self.assertIn("a review is already running", response.json()["detail"])

    def test_the_lock_is_released_when_the_review_finishes(self) -> None:
        """A brake that never lets go is an outage, not a brake."""

        from brief_crew.service import improve_api

        self.assertEqual(200, self.review().status_code)
        self.assertTrue(improve_api._DIGEST_IN_FLIGHT.acquire(blocking=False))
        improve_api._DIGEST_IN_FLIGHT.release()

    # -- (b) the day's allowance -------------------------------------------

    def test_the_day_limit_refuses_with_a_count_and_a_time(self) -> None:
        self.seed_attempts(config.DIGEST_MAX_PER_DAY)
        with patch.object(config, "IMPROVE_DIGEST_ENABLED", True):
            response = self.post()
        self.assertEqual(429, response.status_code, response.text)
        detail = response.json()["detail"]
        self.assertIn(f"{config.DIGEST_MAX_PER_DAY} reviews in the last 24 hours", detail)
        self.assertIn(f"the limit is {config.DIGEST_MAX_PER_DAY}", detail)
        self.assertIn("try again after", detail)

    def test_the_day_limit_counts_the_whole_deployment(self) -> None:
        """A per-workflow count would multiply the bill by the library."""

        self.seed_attempts(config.DIGEST_MAX_PER_DAY, workflow_id="ug_somebody_else")
        with patch.object(config, "IMPROVE_DIGEST_ENABLED", True):
            self.assertEqual(429, self.post().status_code)

    def test_a_failed_attempt_counts_toward_the_day(self) -> None:
        """A model call that raised may still have been billed."""

        moment = datetime.now(timezone.utc)
        for index in range(config.DIGEST_MAX_PER_DAY):
            self.store.save_digest(
                {
                    "id": f"dg_fail{index:04d}",
                    "workflow_id": "ug_other00001",
                    "created_by": None,
                    "window_from": moment,
                    "window_to": moment,
                    "model": config.CHEAP_MODEL,
                    "cost_usd": None,
                    "over_cap": False,
                    "error": "TimeoutError: it did not answer",
                    "body": "",
                    "created_at": moment,
                }
            )
        with patch.object(config, "IMPROVE_DIGEST_ENABLED", True):
            self.assertEqual(429, self.post().status_code)

    def test_a_failing_model_call_writes_an_attempt_and_answers_502(self) -> None:
        class Exploding:
            def call(self, _messages: list[dict[str, str]]) -> str:
                raise RuntimeError("the provider hung up")

        with patch.object(config, "IMPROVE_DIGEST_ENABLED", True), patch.object(
            digest_module, "_default_llm", lambda _model: Exploding()
        ):
            with self.assertLogs("brief_crew.service.improve_api", level="WARNING"):
                response = self.post()
        self.assertEqual(502, response.status_code, response.text)
        rows = self.store.list_digests(self.WORKFLOW)
        self.assertEqual(1, len(rows))
        self.assertIn("the provider hung up", rows[0]["error"])
        self.assertIsNone(rows[0]["cost_usd"])

    def test_the_knob_being_off_costs_nobody_an_attempt(self) -> None:
        """It raises before an `LLM` is constructed, so nothing was billed."""

        with patch.object(config, "IMPROVE_DIGEST_ENABLED", False):
            self.assertEqual(422, self.post().status_code)
        self.assertEqual([], self.store.list_digests(self.WORKFLOW))

    def test_the_page_says_what_is_left_before_the_press(self) -> None:
        body = self.ok(f"/improve/digests?workflow_id={self.WORKFLOW}")
        self.assertEqual(config.DIGEST_MAX_PER_DAY, body["max_per_day"])
        self.assertEqual(config.DIGEST_MAX_PER_DAY, body["remaining_today"])
        self.seed_attempts(4)
        body = self.ok(f"/improve/digests?workflow_id={self.WORKFLOW}")
        self.assertEqual(config.DIGEST_MAX_PER_DAY - 4, body["remaining_today"])

    def test_remaining_today_never_goes_negative(self) -> None:
        self.seed_attempts(config.DIGEST_MAX_PER_DAY + 3)
        body = self.ok(f"/improve/digests?workflow_id={self.WORKFLOW}")
        self.assertEqual(0, body["remaining_today"])

    # -- (c) the interval ---------------------------------------------------

    def test_a_second_review_of_one_workflow_too_soon_is_429(self) -> None:
        self.assertEqual(200, self.review().status_code)
        with patch.object(config, "IMPROVE_DIGEST_ENABLED", True):
            response = self.post()
        self.assertEqual(429, response.status_code, response.text)
        detail = response.json()["detail"]
        self.assertIn(
            f"less than {config.DIGEST_MIN_INTERVAL_SECONDS} seconds ago", detail
        )
        self.assertIn("try again in", detail)

    def test_the_interval_is_per_workflow(self) -> None:
        """Two DIFFERENT workflows back to back is a normal thing to do."""

        self.seed_run("brake-run-2", user_id=ALICE.id, workflow_id="ug_second00001")
        self.assertEqual(200, self.review().status_code)
        self.assertEqual(200, self.review("ug_second00001").status_code)

    def test_the_interval_expires(self) -> None:
        """The control: a brake that never clears is an outage."""

        self.assertEqual(200, self.review().status_code)
        old = datetime.now(timezone.utc) - timedelta(
            seconds=config.DIGEST_MIN_INTERVAL_SECONDS + 5
        )
        with patch.object(
            digest_module, "utcnow", lambda: old
        ):  # the NEXT row is irrelevant; the stored one is what is read
            pass
        from brief_crew.service import improve_api

        self.assertEqual(
            0,
            improve_api._seconds_until_next(
                self.store,
                self.WORKFLOW,
                now=datetime.now(timezone.utc)
                + timedelta(seconds=config.DIGEST_MIN_INTERVAL_SECONDS + 1),
            ),
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
