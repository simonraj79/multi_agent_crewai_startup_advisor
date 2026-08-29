from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest

from crewai.events import LLMCallCompletedEvent, LLMCallStartedEvent
from crewai.events.types.llm_events import LLMCallType

from brief_crew.config import CHEAP_MODEL, compute_cost_usd
from brief_crew.events import UIEventType
from brief_crew.events import NodeRegistry
from brief_crew.service.graph import (
    BRIEF_GRAPH,
    BRIEF_NODE_REGISTRY,
    build_graph_descriptor,
)
from brief_crew.service.persistence import PostgresFlowPersistence
from brief_crew.service.models import RunStatus
from brief_crew.service.registry import RunRegistry
from brief_crew.service.runner import RunExecution, SyntheticRunner


class UsageRunner:
    def __init__(self, *, flow_prompt_tokens: int = 1_000) -> None:
        self.flow_prompt_tokens = flow_prompt_tokens

    def __call__(self, execution: RunExecution) -> object:
        started_at = datetime(2026, 8, 29, 12, 0, tzinfo=timezone.utc)
        execution.capture(
            None,
            LLMCallStartedEvent(
                timestamp=started_at,
                agent_role="Market evidence analyst",
                model=CHEAP_MODEL,
                call_id="call-1",
                messages=[],
                call_type=LLMCallType.LLM_CALL,
            ),
        )
        execution.capture(
            None,
            LLMCallCompletedEvent(
                timestamp=started_at + timedelta(milliseconds=1_250),
                agent_role="Market evidence analyst",
                model=CHEAP_MODEL,
                call_id="call-1",
                response="done",
                call_type=LLMCallType.LLM_CALL,
                usage={
                    "provider_response": {
                        "usage": {
                            "input_tokens": "1000",
                            "output_tokens": 500,
                            "total_token_count": 1_500,
                        }
                    },
                    "successful_requests": 1,
                },
            ),
        )

        class Result:
            token_usage = {
                "prompt_tokens": self.flow_prompt_tokens,
                "completion_tokens": 500,
                "total_tokens": self.flow_prompt_tokens + 500,
                "successful_requests": 1,
            }

        return Result()


class GraphDescriptorTests(unittest.TestCase):
    def test_brief_flow_graph_has_both_router_branches(self) -> None:
        graph = build_graph_descriptor()
        routes = {(edge.source, edge.route, edge.target) for edge in graph.edges}
        self.assertIn(("check_cache", "cache_hit", "write_brief"), routes)
        self.assertIn(("check_cache", "cache_miss", "scrape_web"), routes)
        self.assertEqual(graph.version, build_graph_descriptor().version)


class RunRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = RunRegistry(
            graph_version=BRIEF_GRAPH.version,
            node_registry=BRIEF_NODE_REGISTRY,
            runner=SyntheticRunner(),
        )

    def tearDown(self) -> None:
        self.registry.close()

    def test_synthetic_run_completes_with_gapless_frames(self) -> None:
        record = self.registry.create_run(
            session_id="session-a",
            workflow_id=BRIEF_GRAPH.id,
            inputs={"topic": "test only"},
        )
        self.registry.start_run(record.run_id)
        result = self.registry.wait(record.run_id, timeout=2)

        frames = record.buffer.replay()
        self.assertEqual(result, {"synthetic": True, "topic": "test only"})
        self.assertEqual(record.status, RunStatus.COMPLETED)
        self.assertEqual(
            [frame.seq for frame in frames], list(range(1, len(frames) + 1))
        )
        self.assertEqual(frames[0].event_type, UIEventType.WORKFLOW_START)
        self.assertEqual(frames[-1].event_type, UIEventType.WORKFLOW_END)
        self.assertEqual(record.buffer.stats().emit_errors, 0)

    def test_status_and_replay_are_bounded(self) -> None:
        registry = RunRegistry(
            graph_version=BRIEF_GRAPH.version,
            node_registry=BRIEF_NODE_REGISTRY,
            runner=SyntheticRunner(),
            ring_capacity=3,
        )
        self.addCleanup(registry.close)
        record = registry.create_run(
            session_id="session-b",
            workflow_id=BRIEF_GRAPH.id,
            inputs={},
        )
        registry.start_run(record.run_id)
        registry.wait(record.run_id, timeout=2)

        status = record.status_payload()
        self.assertEqual(status["frames"]["count"], 3)
        self.assertGreater(status["frames"]["dropped"], 0)
        self.assertEqual(len(record.buffer.replay(limit=2)), 2)

    def test_llm_usage_is_priced_persisted_and_exposed_by_node_and_model(self) -> None:
        store = PostgresFlowPersistence("sqlite+pysqlite:///:memory:")
        registry = RunRegistry(
            graph_version="usage-v1",
            node_registry=NodeRegistry(
                agent_role_prefixes={"Market evidence": "research_market"}
            ),
            runner=UsageRunner(),
            persistence=store,
        )
        self.addCleanup(store.close)
        self.addCleanup(registry.close)
        record = registry.create_run(
            session_id="session-usage",
            workflow_id="brief-flow",
            inputs={"topic": "usage"},
        )

        registry.start_run(record.run_id)
        registry.wait(record.run_id, timeout=2)

        expected_cost = compute_cost_usd(CHEAP_MODEL, 1_000, 500)
        status = registry.status_payload(record.run_id)
        self.assertEqual(
            status["usage"],
            {
                "successful_requests": 1,
                "prompt_tokens": 1_000,
                "completion_tokens": 500,
                "total_tokens": 1_500,
                "call_count": 1,
                "elapsed_ms": 1_250,
                "cost_usd": expected_cost,
            },
        )
        self.assertEqual(len(status["node_usage"]), 1)
        self.assertEqual(status["node_usage"][0]["node_id"], "research_market")
        self.assertEqual(status["node_usage"][0]["model"], CHEAP_MODEL)
        self.assertEqual(status["node_usage"][0]["cost_usd"], expected_cost)

        stored = store.get_node_metrics(record.run_id)
        self.assertEqual(len(stored), 1)
        self.assertEqual(stored[0]["node_id"], "research_market")
        self.assertEqual(stored[0]["model"], CHEAP_MODEL)
        self.assertEqual(stored[0]["elapsed_ms"], 1_250)
        self.assertEqual(float(stored[0]["cost_usd"]), expected_cost)

        token_frame = next(
            frame for frame in record.buffer.replay() if frame.kind.value == "token"
        )
        self.assertEqual(token_frame.details["usage"]["prompt_tokens"], 1_000)
        self.assertEqual(token_frame.details["cost_usd"], expected_cost)

    def test_flow_usage_mismatch_is_logged_without_failing_the_run(self) -> None:
        registry = RunRegistry(
            graph_version="usage-v1",
            node_registry=NodeRegistry(
                agent_role_prefixes={"Market evidence": "research_market"}
            ),
            runner=UsageRunner(flow_prompt_tokens=999),
        )
        self.addCleanup(registry.close)
        record = registry.create_run(
            session_id="session-mismatch",
            workflow_id="brief-flow",
            inputs={"topic": "usage"},
        )

        with self.assertLogs("brief_crew.service.registry", level="WARNING") as logs:
            registry.start_run(record.run_id)
            registry.wait(record.run_id, timeout=2)

        self.assertEqual(record.status, RunStatus.COMPLETED)
        self.assertTrue(any("usage totals differ" in message for message in logs.output))

    def test_default_executor_uses_configured_run_concurrency(self) -> None:
        from unittest.mock import patch

        with patch("brief_crew.service.registry.RUN_CONCURRENCY", 3):
            registry = RunRegistry(
                graph_version=BRIEF_GRAPH.version,
                node_registry=BRIEF_NODE_REGISTRY,
                runner=SyntheticRunner(),
            )
        self.addCleanup(registry.close)

        self.assertEqual(registry.max_workers, 3)


if __name__ == "__main__":
    unittest.main()
