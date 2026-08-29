from __future__ import annotations

import unittest
from pathlib import Path

import yaml
from crewai import LLM

from brief_crew.config import (
    CHEAP_MODEL,
    ESCALATION_MODEL,
    RUBRIC_ANCHORS,
    VALIDATOR_SYNTHESIST_REASONING_EFFORT,
    openrouter_reasoning_params,
)
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
from brief_crew.validator_guardrails import CITATION_GUARDRAIL, compute_evidence_counts

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
        evidence_counts=compute_evidence_counts(*findings()),
        market_coverage=0.0,
        sentiment_coverage=0.0,
        feasibility_coverage=0.0,
        median_market_source_age_months=None,
        branches_ok=0,
        cheapest_next_test="Interview five target users.",
        kill_criteria=["No clinic keeps a manual rota."],
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

    def test_synthesist_declares_an_explicit_reasoning_effort(self) -> None:
        """F09: the judgement step must not inherit the provider default."""
        market, sentiment, feasibility = findings()
        crew = SynthesisCrew(market, sentiment, feasibility).crew()
        llm = crew.agents[0].llm

        self.assertEqual(
            llm.additional_params,
            openrouter_reasoning_params(VALIDATOR_SYNTHESIST_REASONING_EFFORT),
        )
        self.assertNotIn(VALIDATOR_SYNTHESIST_REASONING_EFFORT, {"minimal", "none"})

    def test_reasoning_effort_reaches_the_openrouter_request_body(self) -> None:
        """⚠️ `LLM(reasoning_effort=...)` is silently dropped for OpenRouter.

        CrewAI 1.15.18 forwards the field only when `is_o1_model`, so the
        setting has to travel in `extra_body`. This asserts the request params
        CrewAI would send; it makes no call and costs nothing.
        """
        market, sentiment, feasibility = findings()
        crew = SynthesisCrew(market, sentiment, feasibility).crew()
        message = [{"role": "user", "content": "score this"}]

        wired = crew.agents[0].llm._prepare_completion_params(message)
        ignored = LLM(
            model=ESCALATION_MODEL, reasoning_effort="high"
        )._prepare_completion_params(message)

        self.assertEqual(
            wired.get("extra_body"),
            {"reasoning": {"effort": VALIDATOR_SYNTHESIST_REASONING_EFFORT}},
        )
        self.assertNotIn("reasoning_effort", wired)
        self.assertNotIn("reasoning_effort", ignored)
        self.assertNotIn("extra_body", ignored)

    def test_guardrail_sets_are_exactly_as_specified(self) -> None:
        """F16: count, type and order, asserted rather than read."""
        market, sentiment, feasibility = findings()
        expected: dict[str, list[type]] = {
            "scoping_task": [type(lambda: None)],
            "market_task": [type(lambda: None)],
            "sentiment_task": [type(lambda: None)],
            "feasibility_task": [type(lambda: None)],
            "synthesis_task": [type(lambda: None)],
            "reporting_task": [type(lambda: None), str],
        }
        tasks = {
            task.name: task
            for crew in (
                ScopeCrew().crew(),
                MarketCrew().crew(),
                SentimentCrew().crew(),
                FeasibilityCrew().crew(),
                SynthesisCrew(market, sentiment, feasibility).crew(),
                ReportCrew(verdict(), set()).crew(),
            )
            for task in crew.tasks
        }

        self.assertEqual(set(tasks), set(expected))
        for name, kinds in expected.items():
            with self.subTest(task=name):
                guardrails = list(tasks[name].guardrails or [])
                self.assertEqual(len(guardrails), len(kinds))
                for position, (guardrail, kind) in enumerate(zip(guardrails, kinds)):
                    if kind is str:
                        self.assertIsInstance(guardrail, str, f"position {position}")
                    else:
                        self.assertTrue(callable(guardrail), f"position {position}")
                        self.assertNotIsInstance(guardrail, str)
                # The single-guardrail `guardrail=` field stays unused so the
                # ordered `guardrails=` list is the whole contract.
                self.assertIsNone(tasks[name].guardrail)

    def test_exactly_one_llm_guardrail_and_it_is_last_on_the_report(self) -> None:
        """F16: three parallel string guardrails would be three paid calls."""
        market, sentiment, feasibility = findings()
        crews = [
            ScopeCrew().crew(),
            MarketCrew().crew(),
            SentimentCrew().crew(),
            FeasibilityCrew().crew(),
            SynthesisCrew(market, sentiment, feasibility).crew(),
            ReportCrew(verdict(), set()).crew(),
        ]

        string_guardrails = [
            (task.name, position, guardrail)
            for crew in crews
            for task in crew.tasks
            for position, guardrail in enumerate(task.guardrails or [])
            if isinstance(guardrail, str)
        ]

        self.assertEqual(len(string_guardrails), 1)
        name, position, text = string_guardrails[0]
        self.assertEqual(name, "reporting_task")
        self.assertEqual(position, 1)
        self.assertEqual(text.strip(), CITATION_GUARDRAIL.strip())

    def test_rubric_anchors_are_quoted_verbatim_in_the_synthesis_prompt(self) -> None:
        """F15: the guardrail text and the prompt text cannot drift apart."""
        tasks = yaml.safe_load((CONFIG_DIR / "tasks.yaml").read_text(encoding="utf-8"))
        description = tasks["synthesis_task"]["description"]

        for code, ladder in RUBRIC_ANCHORS.items():
            for value, text in ladder.items():
                with self.subTest(dimension=code, score=value):
                    self.assertIn(text, description)

    def test_prompts_request_the_spec_fields_and_a_risks_section(self) -> None:
        """F05, F06, F07 and F13 - a schema field nothing asks for stays null."""
        tasks = yaml.safe_load((CONFIG_DIR / "tasks.yaml").read_text(encoding="utf-8"))
        expected = {
            "market_task": ["paying_segments"],
            "sentiment_task": ["points", "num_comments"],
            "feasibility_task": ["archived"],
            "reporting_task": ["Risks", "kill criteria", "cheapest next test"],
        }

        for name, fragments in expected.items():
            description = tasks[name]["description"]
            for fragment in fragments:
                with self.subTest(task=name, fragment=fragment):
                    self.assertIn(fragment, description)

    def test_owned_implementation_has_no_openai_model_string(self) -> None:
        root = CONFIG_DIR.parent
        files = [*root.rglob("*.py"), *root.rglob("*.yaml")]
        forbidden = "open" + "ai/"
        for path in files:
            with self.subTest(path=path.name):
                self.assertNotIn(forbidden, path.read_text(encoding="utf-8").lower())


if __name__ == "__main__":
    unittest.main()