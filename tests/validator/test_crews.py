from __future__ import annotations

import unittest
from pathlib import Path

import yaml

from brief_crew.config import CHEAP_MODEL, ESCALATION_MODEL
from brief_crew.crews.validator_crew import (
    FeasibilityCrew,
    MarketCrew,
    ReportCrew,
    ScopeCrew,
    SentimentCrew,
    SynthesisCrew,
)
from brief_crew.schemas import (
    DimensionScore,
    FeasibilityFindings,
    MarketFindings,
    SentimentFindings,
    ValidationReport,
    Verdict,
)

CONFIG_DIR = (
    Path(__file__).parents[2]
    / "src"
    / "brief_crew"
    / "crews"
    / "validator_crew"
    / "config"
)


def dimension() -> DimensionScore:
    return DimensionScore(
        score=1,
        anchor_matched="Evidence does not reach this question",
        evidence_urls=[],
        evidence_thin=True,
    )


def findings() -> tuple[MarketFindings, SentimentFindings, FeasibilityFindings]:
    return (
        MarketFindings(
            sources=[],
            source_urls=[],
            gaps=["No market evidence."],
            tool_status="empty",
            competitors=[],
        ),
        SentimentFindings(
            sources=[],
            source_urls=[],
            gaps=["No sentiment evidence."],
            tool_status="empty",
        ),
        FeasibilityFindings(
            sources=[],
            source_urls=[],
            gaps=["No feasibility evidence."],
            tool_status="empty",
        ),
    )


def verdict() -> Verdict:
    score = dimension()
    return Verdict(
        demand=score,
        market=score,
        competitive_room=score,
        feasibility=score,
        headroom_over_free=score,
        evidence_counts={
            "market_sources": 0,
            "market_competitors": 0,
            "sentiment_threads": 0,
            "sentiment_problem_threads": 0,
            "sentiment_paying_threads": 0,
            "sentiment_workaround_threads": 0,
            "feasibility_repos": 0,
            "feasibility_complete_repos": 0,
            "feasibility_commercial_repos": 0,
            "branches_ok": 0,
        },
        market_coverage=0.0,
        sentiment_coverage=0.0,
        feasibility_coverage=0.0,
        median_market_source_age_months=None,
        branches_ok=0,
        cheapest_next_test="Interview five target users.",
    )


class ValidatorCrewWiringTests(unittest.TestCase):
    def test_yaml_declares_exactly_six_agents_and_six_tasks(self) -> None:
        agents = yaml.safe_load((CONFIG_DIR / "agents.yaml").read_text(encoding="utf-8"))
        tasks = yaml.safe_load((CONFIG_DIR / "tasks.yaml").read_text(encoding="utf-8"))

        self.assertEqual(
            set(agents),
            {
                "scoper",
                "market_analyst",
                "sentiment_analyst",
                "feasibility_analyst",
                "synthesist",
                "reporter",
            },
        )
        self.assertEqual(
            set(tasks),
            {
                "scoping_task",
                "market_task",
                "sentiment_task",
                "feasibility_task",
                "synthesis_task",
                "reporting_task",
            },
        )

    def test_single_agent_crews_use_expected_models_and_tool_surfaces(self) -> None:
        market, sentiment, feasibility = findings()
        wrappers = [
            (ScopeCrew(), ESCALATION_MODEL, 0),
            (MarketCrew(), CHEAP_MODEL, 1),
            (SentimentCrew(), CHEAP_MODEL, 1),
            (FeasibilityCrew(), CHEAP_MODEL, 1),
            (SynthesisCrew(market, sentiment, feasibility), ESCALATION_MODEL, 0),
            (ReportCrew(verdict(), set()), ESCALATION_MODEL, 0),
        ]

        for wrapper, expected_model, tool_count in wrappers:
            with self.subTest(wrapper=type(wrapper).__name__):
                crew = wrapper.crew()
                self.assertEqual(len(crew.agents), 1)
                self.assertEqual(len(crew.tasks), 1)
                self.assertFalse(crew.memory)
                self.assertFalse(crew.agents[0].allow_delegation)
                self.assertEqual(len(crew.agents[0].tools), tool_count)
                actual_model = (
                    f"{crew.agents[0].llm.provider}/{crew.agents[0].llm.model}"
                )
                self.assertEqual(actual_model, expected_model)

    def test_tasks_have_structured_outputs_and_report_has_no_output_file(self) -> None:
        market, sentiment, feasibility = findings()
        crews = [
            (ScopeCrew().crew(), "ScopedIdea"),
            (MarketCrew().crew(), "MarketFindings"),
            (SentimentCrew().crew(), "SentimentFindings"),
            (FeasibilityCrew().crew(), "FeasibilityFindings"),
            (SynthesisCrew(market, sentiment, feasibility).crew(), "Verdict"),
            (ReportCrew(verdict(), set()).crew(), "ValidationReport"),
        ]

        for crew, model_name in crews:
            with self.subTest(model=model_name):
                self.assertEqual(crew.tasks[0].output_pydantic.__name__, model_name)
        self.assertIsNone(crews[-1][0].tasks[0].output_file)

    def test_owned_implementation_has_no_openai_model_string(self) -> None:
        root = CONFIG_DIR.parent
        files = [*root.rglob("*.py"), *root.rglob("*.yaml")]
        forbidden = "open" + "ai/"
        for path in files:
            with self.subTest(path=path.name):
                self.assertNotIn(forbidden, path.read_text(encoding="utf-8").lower())


if __name__ == "__main__":
    unittest.main()