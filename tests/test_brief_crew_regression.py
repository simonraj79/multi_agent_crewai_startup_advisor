"""Executable protection for the 'Do not regress Brief Crew' platform rule.

CLAUDE.md lists that rule as non-negotiable and PRD F43 requires it, but until
this file nothing in ``tests/`` touched ``run_crew()``, ``kickoff()``,
``output/brief.md`` or ``output/last_run.json``. The rule was enforced by
nobody. Every Validator Studio change lands in the same package, so the
regression these tests guard against is not hypothetical.

No cost: the crew is a test double, the router is pure arithmetic over injected
hits, and ``persist`` is pointed at a temporary directory.

WARNING for anyone extending this file: ``brief_crew.main.OUTPUT_DIR`` is a
module-level ``Path("output")`` resolved against the process CWD. A test that
exercises ``persist`` without patching it overwrites the developer's real
``output/brief.md`` and ``output/last_run.json``. Always patch it.
"""

from __future__ import annotations

import json
import tempfile
import typing
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from brief_crew.config import (
    MAX_INDEX_AGE_DAYS,
    MIN_RERANK_HITS,
    MIN_RERANK_SCORE,
)
from brief_crew.main import (
    DEFAULT_TOPIC,
    BriefFlow,
    _age_days,
    _usage_dict,
    kickoff,
    run_crew,
)


def _hit(*, score: float = 0.9, age_days: int = 0) -> dict[str, object]:
    """One reranked retrieval hit, fresh and above threshold unless told otherwise."""
    stamp = datetime.now(timezone.utc) - timedelta(days=age_days)
    return {
        "rerank_score": score,
        "indexed_at": stamp.isoformat(),
        "text": "passage",
        "url": "https://example.test/a",
    }


def _flow_with(hits: list[dict[str, object]]) -> BriefFlow:
    flow = BriefFlow()
    flow.state.retrieved = hits
    return flow


class RouterContractTests(unittest.TestCase):
    """The cache router is the one dynamic decision in Track B. It stays LLM-free."""

    def test_all_three_conditions_met_routes_to_cache_hit(self) -> None:
        flow = _flow_with([_hit() for _ in range(MIN_RERANK_HITS)])
        self.assertEqual(flow.check_cache(), "cache_hit")
        self.assertEqual(flow.state.route, "cache_hit")

    def test_too_few_hits_routes_to_cache_miss(self) -> None:
        flow = _flow_with([_hit() for _ in range(MIN_RERANK_HITS - 1)])
        self.assertEqual(flow.check_cache(), "cache_miss")
        self.assertEqual(flow.state.route, "cache_miss")

    def test_no_hits_at_all_routes_to_cache_miss(self) -> None:
        self.assertEqual(_flow_with([]).check_cache(), "cache_miss")

    def test_top_rerank_score_below_threshold_routes_to_cache_miss(self) -> None:
        hits = [_hit(score=MIN_RERANK_SCORE - 0.01)] + [_hit() for _ in range(MIN_RERANK_HITS)]
        self.assertEqual(_flow_with(hits).check_cache(), "cache_miss")

    def test_threshold_is_on_the_rerank_score_not_a_cosine_score(self) -> None:
        # The docstring in main.py is explicit that cosine scores for a good and
        # an irrelevant match span ~0.06 on this index, so the cutoff must read
        # `rerank_score`. A hit carrying only a cosine score must not pass.
        hits = [{"score": 0.99, "indexed_at": datetime.now(timezone.utc).isoformat()}]
        hits += [_hit() for _ in range(MIN_RERANK_HITS)]
        self.assertEqual(_flow_with(hits).check_cache(), "cache_miss")

    def test_missing_indexed_at_routes_to_cache_miss(self) -> None:
        hits = [{"rerank_score": 0.99}] + [_hit() for _ in range(MIN_RERANK_HITS)]
        self.assertEqual(_flow_with(hits).check_cache(), "cache_miss")

    def test_stale_top_hit_routes_to_cache_miss(self) -> None:
        hits = [_hit(age_days=MAX_INDEX_AGE_DAYS + 1)] + [_hit() for _ in range(MIN_RERANK_HITS)]
        self.assertEqual(_flow_with(hits).check_cache(), "cache_miss")

    def test_router_makes_no_llm_call(self) -> None:
        # Routing must cost nothing. If anyone ever swaps the arithmetic for a
        # manager agent, LLM construction is where it would show up.
        with patch("crewai.LLM") as llm:
            _flow_with([_hit() for _ in range(MIN_RERANK_HITS)]).check_cache()
        llm.assert_not_called()


class GraphIntrospectionTests(unittest.TestCase):
    """PRD R-0: the annotation that makes the router statically inferable."""

    def test_check_cache_keeps_its_literal_return_annotation(self) -> None:
        # Widening this back to `-> str` silently disconnects the Brief Flow
        # graph: check_cache loses its outgoing edges, scrape_web is orphaned,
        # and the UI draws a topology that is not the system. The failure mode
        # is a logging.warning nobody reads, so it is asserted here instead.
        annotation = typing.get_type_hints(BriefFlow.check_cache)["return"]
        self.assertIs(typing.get_origin(annotation), typing.Literal)
        self.assertEqual(set(typing.get_args(annotation)), {"cache_hit", "cache_miss"})

    def test_both_router_branches_are_statically_visible(self) -> None:
        from crewai.flow import build_flow_structure

        structure = build_flow_structure(BriefFlow)
        blob = json.dumps(structure, default=str)
        self.assertIn("cache_hit", blob)
        self.assertIn("cache_miss", blob)
        # All six methods must be reachable. `scrape_web` is the one that goes
        # orphaned the moment the router annotation is widened.
        for method in (
            "retrieve_cached",
            "check_cache",
            "scrape_web",
            "index_content",
            "write_brief",
            "persist",
        ):
            self.assertIn(method, blob, f"{method} missing from the Brief Flow graph")


class AgeHelperTests(unittest.TestCase):
    """Undated material must never be served as current."""

    def test_missing_or_unparseable_stamps_are_not_treated_as_fresh(self) -> None:
        for value in (None, "", "not-a-date"):
            with self.subTest(value=value):
                self.assertIsNone(_age_days(value))

    def test_naive_timestamps_are_read_as_utc(self) -> None:
        naive = (datetime.now(timezone.utc) - timedelta(days=3)).replace(tzinfo=None)
        self.assertEqual(_age_days(naive.isoformat()), 3)

    def test_trailing_z_is_accepted(self) -> None:
        stamp = (datetime.now(timezone.utc) - timedelta(days=2)).replace(microsecond=0)
        self.assertEqual(_age_days(stamp.isoformat().replace("+00:00", "Z")), 2)


class UsageContractTests(unittest.TestCase):
    """`last_run.json` field shape - 07-deployment.md maps these to run_metrics."""

    def test_usage_dict_carries_the_upper_bound_cost_key(self) -> None:
        usage = MagicMock(
            prompt_tokens=1000,
            completion_tokens=500,
            total_tokens=1500,
            successful_requests=7,
        )
        record = _usage_dict(MagicMock(token_usage=usage))

        # `cost_usd_upper_bound` is the exact key persist's print statement
        # reads. A rename here reintroduces the fixed bug where every run
        # printed cost=$0.000000 while the file carried the real figure.
        self.assertEqual(
            set(record),
            {
                "successful_requests",
                "prompt_tokens",
                "completion_tokens",
                "total_tokens",
                "cost_usd_upper_bound",
            },
        )
        self.assertGreater(record["cost_usd_upper_bound"], 0)

    def test_absent_token_usage_degrades_to_an_empty_record(self) -> None:
        self.assertEqual(_usage_dict(MagicMock(token_usage=None)), {})


class PersistOutputTests(unittest.TestCase):
    """`output/brief.md` and `output/last_run.json` are the Track A/B contract."""

    def test_persist_writes_markdown_and_a_run_record(self) -> None:
        flow = BriefFlow()
        flow.state.topic = "cashless payments in Singapore"
        flow.state.brief = "# Brief\n\nBody text.\n"
        flow.state.route = "cache_hit"
        flow.state.usage = {
            "successful_requests": 3,
            "prompt_tokens": 10,
            "completion_tokens": 20,
            "total_tokens": 30,
            "cost_usd_upper_bound": 0.000123,
        }

        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "output"
            with patch("brief_crew.main.OUTPUT_DIR", out):
                flow.persist()

            brief = out / "brief.md"
            record_path = out / "last_run.json"
            self.assertTrue(brief.is_file())
            self.assertTrue(record_path.is_file())

            # Markdown, not a JSON blob. PRD R-14: output_file plus
            # output_pydantic writes JSON into a .md with no warning.
            self.assertEqual(brief.read_text(encoding="utf-8"), flow.state.brief)

            record = json.loads(record_path.read_text(encoding="utf-8"))
            self.assertEqual(record["topic"], flow.state.topic)
            self.assertEqual(record["route"], "cache_hit")
            self.assertEqual(record["run_id"], flow.state.run_id)
            self.assertEqual(record["successful_requests"], 3)
            self.assertEqual(record["cost_usd_upper_bound"], 0.000123)
            datetime.fromisoformat(record["completed_at"])

    def test_persist_creates_the_output_directory_when_absent(self) -> None:
        flow = BriefFlow()
        flow.state.brief = "# Brief\n"
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "nested" / "output"
            with patch("brief_crew.main.OUTPUT_DIR", out.parent):
                flow.persist()
            self.assertTrue((out.parent / "brief.md").is_file())


class EntryPointTests(unittest.TestCase):
    """`run_crew()` and `kickoff()` are the two documented entry points."""

    def test_run_crew_builds_the_track_a_crew_and_passes_the_topic(self) -> None:
        crew = MagicMock()
        crew.kickoff.return_value = MagicMock(token_usage="usage")
        with patch("brief_crew.main.BriefCrew") as brief_crew:
            brief_crew.return_value.crew.return_value = crew
            result = run_crew("a topic")

        brief_crew.assert_called_once_with(track="A")
        crew.kickoff.assert_called_once_with(inputs={"topic": "a topic"})
        self.assertIs(result, crew.kickoff.return_value)

    def test_run_crew_defaults_to_the_documented_topic(self) -> None:
        crew = MagicMock()
        crew.kickoff.return_value = MagicMock(token_usage="usage")
        with patch("brief_crew.main.BriefCrew") as brief_crew:
            brief_crew.return_value.crew.return_value = crew
            run_crew()
        crew.kickoff.assert_called_once_with(inputs={"topic": DEFAULT_TOPIC})

    def test_kickoff_runs_the_flow_with_the_topic(self) -> None:
        with patch.object(BriefFlow, "kickoff", return_value="done") as flow_kickoff:
            self.assertEqual(kickoff("another topic"), "done")
        flow_kickoff.assert_called_once_with(inputs={"topic": "another topic"})


if __name__ == "__main__":
    unittest.main()
