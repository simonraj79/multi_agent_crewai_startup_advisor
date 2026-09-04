"""The two defects the first PAID end-to-end run exposed.

Run ``8b5a0a78-aa5c-4ea6-83a7-cccfbb4baae7`` completed on the deployed API with
11 LLM calls and 128,069 tokens, and produced two lies:

1. Its validation report came back cut off mid-URL, because
   ``RunRecord.mark_completed`` bounded the run's final deliverable with
   ``SerializerLimits.max_string`` - a limit that exists to size a *streaming
   frame*. ``output/validation.md`` is ephemeral container disk on Render, so a
   successful run produced no retrievable complete report at all.
2. Its ``usage`` reported ``cost_usd: 0.0``. CrewAI strips the ``openrouter/``
   prefix before a native provider ever sees the model name, so every
   ``LLMCallCompletedEvent`` said ``z-ai/glm-5.3-flash`` while ``PRICES`` said
   ``openrouter/z-ai/glm-5.3-flash`` - and ``PRICES.get(model, (0.0, 0.0))``
   turned every miss into a free call.

Everything here runs on injected runners and mocked events. Nothing costs money.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import importlib.util
import logging
import unittest

from crewai.events import LLMCallCompletedEvent, LLMCallStartedEvent
from crewai.events.types.llm_events import LLMCallType

from brief_crew.config import (
    CHEAP_MODEL,
    ESCALATION_MODEL,
    MAX_RUN_RESULT_BODY_CHARS,
    RUN_RESULT_BODY_KEYS,
    compute_cost_usd,
    resolve_price_model,
)
from brief_crew.events import FrameKind, NodeRegistry, UIEventType
from brief_crew.events.serializer import FieldBoundedSerializer, SerializerLimits
from brief_crew.schemas.validator import Evidence, ValidationReport
from brief_crew.service.graph import (
    VALIDATOR_GRAPH,
    VALIDATOR_NODE_REGISTRY,
)
from brief_crew.service.persistence import (
    MAX_STRING_LENGTH,
    PostgresFlowPersistence,
)
from brief_crew.service.registry import RunRegistry
from brief_crew.service.runner import RunExecution


FASTAPI_AVAILABLE = importlib.util.find_spec("fastapi") is not None

FRAME_LIMIT = SerializerLimits().max_string
# The bare slug CrewAI's native OpenRouter provider actually reports. Derived
# from the constant rather than hardcoded, so it tracks a model change.
BARE_CHEAP_MODEL = CHEAP_MODEL.split("/", 1)[1]
PROMPT_TOKENS = 81_282
COMPLETION_TOKENS = 46_787


def markdown_report(length: int) -> str:
    """A report body of exactly ``length`` characters, ending mid-nothing.

    The filler carries a real markdown link because the defect's signature was
    a body that stopped inside one.
    """

    filler = "See [Mentimeter](https://www.mentimeter.com/blog/education) on this. "
    body = ("# Validation brief\n\n" + filler * (length // len(filler) + 2))[:length]
    if body[-1:].isspace():
        body = body[:-1] + "."
    return body


def validation_report(body: str) -> ValidationReport:
    return ValidationReport(
        markdown_body=body,
        provisional=False,
        thin_dimensions=[],
        sources=[
            Evidence(
                claim="Teachers already pay for classroom polling.",
                url="https://www.mentimeter.com/blog/education",
                publisher="Mentimeter",
                dated="2026-02-01",
                dated_is_retrieval_time=False,
                retrieved_via="firecrawl",
            )
        ],
    )


class ReportRunner:
    """Finish with a ValidationReport, the way ValidatorFlow's `persist` does.

    It also pushes the same terminal RUN_STATE frame the real serializer emits
    for ``FlowFinishedEvent``, so the streaming copy of the result and the
    stored copy can be compared against each other in one run.
    """

    def __init__(self, report: ValidationReport) -> None:
        self.report = report

    def __call__(self, execution: RunExecution) -> ValidationReport:
        execution.capture.emit(
            kind=FrameKind.RUN_STATE,
            event_type=UIEventType.WORKFLOW_END,
            node_id="workflow",
            message="ValidatorFlow completed",
            details={"status": "completed", "result": self.report},
        )
        return self.report


class DictReportRunner:
    """A flow that returns a plain mapping rather than a pydantic model."""

    def __init__(self, body: str, note: str) -> None:
        self.payload = {"markdown_body": body, "note": note}

    def __call__(self, execution: RunExecution) -> dict[str, str]:
        return dict(self.payload)


class StringResultRunner:
    def __init__(self, body: str) -> None:
        self.body = body

    def __call__(self, execution: RunExecution) -> str:
        return self.body


class ModelCallRunner:
    """Fire one real LLMCall{Started,Completed} pair for a named model."""

    def __init__(
        self,
        model: str,
        *,
        prompt_tokens: int = PROMPT_TOKENS,
        completion_tokens: int = COMPLETION_TOKENS,
    ) -> None:
        self.model = model
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens

    def __call__(self, execution: RunExecution) -> str:
        started_at = datetime(2026, 8, 30, 4, 0, tzinfo=timezone.utc)
        execution.capture(
            None,
            LLMCallStartedEvent(
                timestamp=started_at,
                agent_role="Scoper",
                model=self.model,
                call_id="call-1",
                messages=[],
                call_type=LLMCallType.LLM_CALL,
            ),
        )
        execution.capture(
            None,
            LLMCallCompletedEvent(
                timestamp=started_at + timedelta(milliseconds=515_000),
                agent_role="Scoper",
                model=self.model,
                call_id="call-1",
                response="done",
                call_type=LLMCallType.LLM_CALL,
                usage={
                    "prompt_tokens": self.prompt_tokens,
                    "completion_tokens": self.completion_tokens,
                    "total_tokens": self.prompt_tokens + self.completion_tokens,
                    "successful_requests": 1,
                },
            ),
        )
        return "done"


def _registry(runner: object, **kwargs: object) -> RunRegistry:
    return RunRegistry(
        graph_version=VALIDATOR_GRAPH.version,
        node_registry=VALIDATOR_NODE_REGISTRY,
        runner=runner,  # type: ignore[arg-type]
        **kwargs,  # type: ignore[arg-type]
    )


class ResultBoundConstantTests(unittest.TestCase):
    """The bound is a named constant, and its value is checked, not trusted."""

    def test_the_result_bound_sits_between_the_frame_limit_and_the_row_limit(
        self,
    ) -> None:
        self.assertEqual(MAX_RUN_RESULT_BODY_CHARS, 64 * 1024)
        # Bigger than the streaming bound, or the defect is not fixed.
        self.assertGreater(MAX_RUN_RESULT_BODY_CHARS, FRAME_LIMIT)
        # Not bigger than what the durable row accepts. `_sanitize_json` RAISES
        # on an oversized string rather than truncating it, so a larger bound
        # would lose the whole run row instead of the tail of one field.
        self.assertLessEqual(MAX_RUN_RESULT_BODY_CHARS, MAX_STRING_LENGTH)
        # Bounded at all. A `None`/0 here would be an unbounded write into a
        # basic_256mb database.
        self.assertIsInstance(MAX_RUN_RESULT_BODY_CHARS, int)
        self.assertGreater(MAX_RUN_RESULT_BODY_CHARS, 0)

    def test_the_deliverable_keys_are_declared_and_name_the_report_body(self) -> None:
        self.assertIn("markdown_body", RUN_RESULT_BODY_KEYS)
        self.assertIn("markdown_body", ValidationReport.model_fields)


class RunResultRetentionTests(unittest.TestCase):
    def _completed_result(self, runner: object) -> object:
        registry = _registry(runner)
        self.addCleanup(registry.close)
        record = registry.create_run(
            session_id="session-report",
            workflow_id=VALIDATOR_GRAPH.id,
            inputs={"idea": "A classroom polling assistant"},
        )
        registry.start_run(record.run_id)
        registry.wait(record.run_id, timeout=5)
        return registry.status_payload(record.run_id)["result"]

    def test_a_report_longer_than_the_frame_limit_survives_in_full(self) -> None:
        body = markdown_report(FRAME_LIMIT * 3)
        self.assertGreater(len(body), FRAME_LIMIT)

        result = self._completed_result(ReportRunner(validation_report(body)))

        assert isinstance(result, dict)
        self.assertEqual(len(result["markdown_body"]), len(body))
        self.assertEqual(result["markdown_body"], body)
        # The rest of the contract still arrives.
        self.assertEqual(result["provisional"], False)
        self.assertEqual(len(result["sources"]), 1)

    def test_a_report_longer_than_the_result_bound_is_still_bounded(self) -> None:
        body = markdown_report(MAX_RUN_RESULT_BODY_CHARS + 5_000)

        result = self._completed_result(ReportRunner(validation_report(body)))

        assert isinstance(result, dict)
        stored = result["markdown_body"]
        self.assertEqual(len(stored), MAX_RUN_RESULT_BODY_CHARS)
        self.assertEqual(stored, body[:MAX_RUN_RESULT_BODY_CHARS])

    def test_only_the_declared_body_key_escapes_the_frame_bound(self) -> None:
        """The bypass is per-key on purpose: one big string, not sixty-four."""

        body = markdown_report(FRAME_LIMIT * 2)
        note = markdown_report(FRAME_LIMIT * 2)

        result = self._completed_result(DictReportRunner(body, note))

        assert isinstance(result, dict)
        self.assertEqual(len(result["markdown_body"]), len(body))
        self.assertEqual(len(result["note"]), FRAME_LIMIT)

    def test_a_result_that_is_itself_a_string_gets_the_result_bound(self) -> None:
        body = markdown_report(MAX_RUN_RESULT_BODY_CHARS + 1_000)

        result = self._completed_result(StringResultRunner(body))

        assert isinstance(result, str)
        self.assertEqual(len(result), MAX_RUN_RESULT_BODY_CHARS)

    def test_the_full_body_round_trips_through_durable_persistence(self) -> None:
        """The bound and `persistence.MAX_STRING_LENGTH` must not disagree."""

        store = PostgresFlowPersistence("sqlite+pysqlite:///:memory:")
        self.addCleanup(store.close)
        registry = _registry(
            ReportRunner(validation_report(markdown_report(MAX_RUN_RESULT_BODY_CHARS))),
            persistence=store,
        )
        self.addCleanup(registry.close)
        record = registry.create_run(
            session_id="session-durable",
            workflow_id=VALIDATOR_GRAPH.id,
            inputs={"idea": "A classroom polling assistant"},
        )
        registry.start_run(record.run_id)
        registry.wait(record.run_id, timeout=5)

        stored = store.get_run(record.run_id)
        assert stored is not None
        self.assertEqual(
            len(stored["result"]["markdown_body"]), MAX_RUN_RESULT_BODY_CHARS
        )


class StreamingFrameBoundTests(unittest.TestCase):
    """The streaming path must NOT inherit the terminal result's bound."""

    def test_the_frame_serializer_still_clips_a_report_at_the_frame_limit(
        self,
    ) -> None:
        body = markdown_report(FRAME_LIMIT * 3)
        clipped = FieldBoundedSerializer().clip(validation_report(body))

        assert isinstance(clipped, dict)
        self.assertEqual(len(clipped["markdown_body"]), FRAME_LIMIT)

    def test_the_terminal_run_state_frame_is_clipped_while_the_result_is_not(
        self,
    ) -> None:
        body = markdown_report(FRAME_LIMIT * 3)
        registry = _registry(ReportRunner(validation_report(body)))
        self.addCleanup(registry.close)
        record = registry.create_run(
            session_id="session-frames",
            workflow_id=VALIDATOR_GRAPH.id,
            inputs={"idea": "A classroom polling assistant"},
        )
        registry.start_run(record.run_id)
        registry.wait(record.run_id, timeout=5)

        frame = next(
            item
            for item in record.buffer.replay()
            if item.kind is FrameKind.RUN_STATE
            and item.event_type is UIEventType.WORKFLOW_END
        )
        self.assertEqual(
            len(frame.details["result"]["markdown_body"]), FRAME_LIMIT
        )
        # ...and the very same run kept the whole thing where it matters.
        self.assertEqual(len(record.result["markdown_body"]), len(body))


class PriceResolutionTests(unittest.TestCase):
    """Defect 2's root cause: the model name that reaches the event."""

    def test_crewai_reports_the_model_without_its_provider_prefix(self) -> None:
        """Guards the assumption the whole fix rests on, against upstream."""

        from crewai import LLM

        self.assertEqual(LLM(model=CHEAP_MODEL).model, BARE_CHEAP_MODEL)

    def test_both_spellings_resolve_to_the_same_price_key(self) -> None:
        self.assertEqual(resolve_price_model(CHEAP_MODEL), CHEAP_MODEL)
        self.assertEqual(resolve_price_model(BARE_CHEAP_MODEL), CHEAP_MODEL)
        self.assertEqual(
            resolve_price_model(ESCALATION_MODEL.split("/", 1)[1]),
            ESCALATION_MODEL,
        )

    def test_a_routing_variant_resolves_to_its_base_price(self) -> None:
        """`:nitro` is a routing instruction, not a different model.

        CHEAP_MODEL carries `:nitro` - OpenRouter's "route to the fastest
        provider" shorthand, worth ~27x at the median against the model it
        replaced. But the provider that actually serves the request can report
        the BASE model back, with no suffix. If that spelling failed to resolve,
        `compute_cost_usd` would contribute nothing for every branch call and
        the run's cost display would quietly return to the $0.00 it used to
        show over 128,069 real tokens - the exact defect this file exists for.
        """
        base, separator, variant = CHEAP_MODEL.rpartition(":")
        if not separator:
            self.skipTest("CHEAP_MODEL carries no routing variant")
        self.assertTrue(variant, "a trailing colon is not a variant")
        # Both the prefixed and the CrewAI-reported bare spelling, minus suffix.
        self.assertEqual(resolve_price_model(base), CHEAP_MODEL)
        self.assertEqual(
            resolve_price_model(base.split("/", 1)[1]),
            CHEAP_MODEL,
        )

    def test_a_variant_stripped_model_costs_the_same_as_the_variant(self) -> None:
        base = CHEAP_MODEL.rpartition(":")[0] or CHEAP_MODEL
        with_variant = compute_cost_usd(CHEAP_MODEL, PROMPT_TOKENS, COMPLETION_TOKENS)
        without = compute_cost_usd(base, PROMPT_TOKENS, COMPLETION_TOKENS)
        self.assertIsNotNone(without)
        self.assertEqual(with_variant, without)

    def test_an_unknown_model_is_still_none_rather_than_free(self) -> None:
        """The variant fallback must not turn every unknown id into a match.

        `rpartition(":")` on a name with no colon yields an empty base, and
        looking THAT up must not resolve - otherwise "no price on file" would
        start masquerading as a priced call again, in the opposite direction.
        """
        self.assertIsNone(resolve_price_model("some/unheard-of-model"))
        self.assertIsNone(resolve_price_model("some/unheard-of-model:nitro"))
        self.assertIsNone(resolve_price_model(":nitro"))
        self.assertIsNone(compute_cost_usd("some/unheard-of-model", 100, 100))

    def test_a_known_model_costs_the_same_either_way_and_is_not_zero(self) -> None:
        prefixed = compute_cost_usd(CHEAP_MODEL, PROMPT_TOKENS, COMPLETION_TOKENS)
        bare = compute_cost_usd(BARE_CHEAP_MODEL, PROMPT_TOKENS, COMPLETION_TOKENS)
        self.assertIsNotNone(prefixed)
        self.assertEqual(prefixed, bare)
        assert prefixed is not None
        self.assertGreater(prefixed, 0.0)

    def test_zero_tokens_on_a_known_model_is_a_real_zero(self) -> None:
        self.assertEqual(compute_cost_usd(CHEAP_MODEL, 0, 0), 0.0)

    def test_an_unknown_model_is_none_not_zero(self) -> None:
        self.assertIsNone(resolve_price_model("acme/never-heard-of-it"))
        self.assertIsNone(compute_cost_usd("acme/never-heard-of-it", 1_000, 1_000))
        self.assertIsNone(compute_cost_usd("unknown", 1_000, 1_000))
        self.assertIsNone(compute_cost_usd("", 1_000, 1_000))


class AuthoredCompletionBoundTests(unittest.TestCase):
    """10 criterion 2: the priced call and the real call finally agree.

    `budget.py` prices every model call at `GRAPH_BUDGET_CALL_COMPLETION_TOKENS`
    completion tokens, and until 10 D1 nothing capped a completion at all - so
    the one bound the $10 ceiling was measured against did not exist at run
    time. Constructing an `LLM` calls no model, so this costs nothing.
    """

    def _llm(self, **fields: object) -> object:
        from brief_crew.builder.runtime import _authored_llm

        return _authored_llm(
            {"model": "google/gemini-3.8-flash", **fields}, node_id="draft"
        )

    def test_the_default_is_the_number_the_budget_priced_with(self) -> None:
        from brief_crew.config import GRAPH_BUDGET_CALL_COMPLETION_TOKENS

        self.assertEqual(
            self._llm().max_tokens, GRAPH_BUDGET_CALL_COMPLETION_TOKENS
        )

    def test_the_estimate_and_the_cap_are_ONE_constant(self) -> None:
        """Not two numbers that happen to match - the same name in both places.

        A restated figure is how this repository has published a wrong count six
        times; here the two would drift into an estimate that no longer bounds
        anything.
        """

        import brief_crew.builder.budget as budget_module
        import brief_crew.builder.runtime as runtime_module
        from brief_crew.config import GRAPH_BUDGET_CALL_COMPLETION_TOKENS

        self.assertIs(
            runtime_module.GRAPH_BUDGET_CALL_COMPLETION_TOKENS,
            GRAPH_BUDGET_CALL_COMPLETION_TOKENS,
        )
        self.assertIs(
            budget_module.GRAPH_BUDGET_CALL_COMPLETION_TOKENS,
            GRAPH_BUDGET_CALL_COMPLETION_TOKENS,
        )

    def test_an_authored_model_is_priced_from_the_registry_table(self) -> None:
        """Per registry model, and `None` - never `0.0` - for one not in it."""

        from brief_crew.builder.registry import registry_document

        priced = [
            model["id"]
            for model in registry_document()["models"]
        ]
        self.assertTrue(priced)
        for model_id in priced:
            with self.subTest(model=model_id):
                self.assertIsNotNone(compute_cost_usd(model_id, 1_000, 1_000))
        self.assertIsNone(compute_cost_usd("acme/model-that-was-retired", 1_000, 1_000))


class RunCostAccumulationTests(unittest.TestCase):
    def _run(self, runner: object) -> tuple[RunRegistry, str]:
        registry = _registry(runner)
        self.addCleanup(registry.close)
        record = registry.create_run(
            session_id="session-cost",
            workflow_id=VALIDATOR_GRAPH.id,
            inputs={"idea": "A classroom polling assistant"},
        )
        registry.start_run(record.run_id)
        registry.wait(record.run_id, timeout=5)
        return registry, record.run_id

    @staticmethod
    def _token_frame(registry: RunRegistry, run_id: str) -> object:
        record = registry.require(run_id)
        return next(
            frame for frame in record.buffer.replay() if frame.kind is FrameKind.TOKEN
        )

    def test_the_bare_model_name_from_a_real_run_is_now_priced(self) -> None:
        registry, run_id = self._run(ModelCallRunner(BARE_CHEAP_MODEL))
        usage = registry.status_payload(run_id)["usage"]
        expected = compute_cost_usd(CHEAP_MODEL, PROMPT_TOKENS, COMPLETION_TOKENS)

        self.assertEqual(usage["prompt_tokens"], PROMPT_TOKENS)
        self.assertEqual(usage["completion_tokens"], COMPLETION_TOKENS)
        self.assertGreater(usage["cost_usd"], 0.0)
        self.assertAlmostEqual(usage["cost_usd"], expected, places=12)

    def test_the_prefixed_model_name_is_priced_identically(self) -> None:
        registry, run_id = self._run(ModelCallRunner(CHEAP_MODEL))
        bare_registry, bare_run_id = self._run(ModelCallRunner(BARE_CHEAP_MODEL))

        self.assertAlmostEqual(
            registry.status_payload(run_id)["usage"]["cost_usd"],
            bare_registry.status_payload(bare_run_id)["usage"]["cost_usd"],
            places=12,
        )

    def test_the_token_frame_carries_cost_where_the_client_reads_it(self) -> None:
        """`usageFromDetails` narrows to `details.usage` and never looks up."""

        registry, run_id = self._run(ModelCallRunner(BARE_CHEAP_MODEL))
        frame = self._token_frame(registry, run_id)

        expected = compute_cost_usd(CHEAP_MODEL, PROMPT_TOKENS, COMPLETION_TOKENS)
        details = frame.details  # type: ignore[attr-defined]
        self.assertAlmostEqual(details["usage"]["cost_usd"], expected, places=12)
        self.assertAlmostEqual(details["cost_usd"], expected, places=12)

    def test_the_nested_cost_is_not_double_counted_into_the_totals(self) -> None:
        registry, run_id = self._run(ModelCallRunner(BARE_CHEAP_MODEL))
        usage = registry.status_payload(run_id)["usage"]

        self.assertEqual(usage["call_count"], 1)
        self.assertEqual(
            usage["total_tokens"], PROMPT_TOKENS + COMPLETION_TOKENS
        )
        self.assertAlmostEqual(
            usage["cost_usd"],
            compute_cost_usd(CHEAP_MODEL, PROMPT_TOKENS, COMPLETION_TOKENS),
            places=12,
        )

    def test_per_node_usage_is_priced_too(self) -> None:
        registry, run_id = self._run(ModelCallRunner(BARE_CHEAP_MODEL))
        nodes = registry.status_payload(run_id)["node_usage"]

        self.assertEqual(len(nodes), 1)
        self.assertEqual(nodes[0]["model"], BARE_CHEAP_MODEL)
        self.assertGreater(nodes[0]["cost_usd"], 0.0)

    def test_an_unpriced_model_reports_none_rather_than_a_free_call(self) -> None:
        with self.assertLogs("brief_crew.service.registry", level=logging.WARNING) as logs:
            registry, run_id = self._run(ModelCallRunner("acme/never-heard-of-it"))

        frame = self._token_frame(registry, run_id)
        details = frame.details  # type: ignore[attr-defined]
        # The frame is where "unknown" is representable, and it says so.
        self.assertIsNone(details["cost_usd"])
        self.assertIsNone(details["usage"]["cost_usd"])
        # Tokens were still spent, so a 0.0 total is visibly a partial sum...
        usage = registry.status_payload(run_id)["usage"]
        self.assertEqual(usage["total_tokens"], PROMPT_TOKENS + COMPLETION_TOKENS)
        self.assertEqual(usage["cost_usd"], 0.0)
        # ...and the operator is told, by name, that it is one.
        self.assertTrue(
            any("acme/never-heard-of-it" in message for message in logs.output),
            logs.output,
        )

    def test_the_unpriced_warning_is_emitted_once_per_model_per_run(self) -> None:
        class TwoCallRunner:
            def __call__(self, execution: RunExecution) -> str:
                ModelCallRunner("acme/never-heard-of-it")(execution)
                ModelCallRunner("acme/never-heard-of-it")(execution)
                return "done"

        with self.assertLogs("brief_crew.service.registry", level=logging.WARNING) as logs:
            self._run(TwoCallRunner())

        unpriced = [
            message for message in logs.output if "acme/never-heard-of-it" in message
        ]
        self.assertEqual(len(unpriced), 1, logs.output)


@unittest.skipUnless(
    FASTAPI_AVAILABLE,
    "FastAPI is not installed; install the existing project service extra",
)
class RunResultOverHttpTests(unittest.TestCase):
    """The report has to be reachable through the API, not just in memory."""

    def _client(self, runner: object) -> object:
        from fastapi.testclient import TestClient

        from brief_crew.service.app import create_app

        store = PostgresFlowPersistence("sqlite+pysqlite:///:memory:")
        self.addCleanup(store.close)
        registry = _registry(runner, persistence=store)
        self.addCleanup(registry.close)
        client = TestClient(create_app(registry=registry))
        self.addCleanup(client.close)
        self.registry = registry
        return client

    def test_get_run_returns_the_untruncated_report_body(self) -> None:
        body = markdown_report(FRAME_LIMIT * 4)
        client = self._client(ReportRunner(validation_report(body)))

        created = client.post(  # type: ignore[attr-defined]
            "/api/sessions/session-http/runs",
            json={
                "workflow_id": VALIDATOR_GRAPH.id,
                "inputs": {"idea": "A classroom polling assistant"},
            },
        )
        self.assertEqual(created.status_code, 202)
        run_id = created.json()["run_id"]
        self.registry.wait(run_id, timeout=5)

        status = client.get(f"/api/runs/{run_id}").json()  # type: ignore[attr-defined]
        self.assertEqual(status["status"], "completed")
        self.assertEqual(len(status["result"]["markdown_body"]), len(body))
        self.assertEqual(status["result"]["markdown_body"], body)
        # The whole final link is intact - the acceptance criterion the
        # truncated report made unassessable.
        self.assertIn(
            "https://www.mentimeter.com/blog/education",
            status["result"]["markdown_body"],
        )

    def test_get_run_reports_a_non_zero_cost_for_a_real_model_call(self) -> None:
        client = self._client(ModelCallRunner(BARE_CHEAP_MODEL))

        created = client.post(  # type: ignore[attr-defined]
            "/api/sessions/session-http-cost/runs",
            json={
                "workflow_id": VALIDATOR_GRAPH.id,
                "inputs": {"idea": "A classroom polling assistant"},
            },
        )
        run_id = created.json()["run_id"]
        self.registry.wait(run_id, timeout=5)

        usage = client.get(f"/api/runs/{run_id}").json()["usage"]  # type: ignore[attr-defined]
        self.assertEqual(usage["total_tokens"], PROMPT_TOKENS + COMPLETION_TOKENS)
        self.assertGreater(usage["cost_usd"], 0.0)


if __name__ == "__main__":
    unittest.main()
