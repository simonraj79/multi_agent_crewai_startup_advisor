from __future__ import annotations

import itertools
import unittest
from pathlib import Path

import yaml
from crewai import LLM

from brief_crew.config import (
    ANCHOR_MATCH_THRESHOLD,
    CHEAP_MODEL,
    ESCALATION_MODEL,
    LEVEL_ONE_ANCHOR,
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
from brief_crew.validator_guardrails import (
    CITATION_GUARDRAIL,
    compute_evidence_counts,
    token_overlap,
)

CONFIG_DIR = (
    Path(__file__).parents[2]
    / "src"
    / "brief_crew"
    / "crews"
    / "validator_crew"
    / "config"
)


def dimension(code: str) -> DimensionScore:
    """A score-1 dimension carrying that ladder's own level-1 anchor.

    `anchor_problems` compares a score of 1 against `RUBRIC_ANCHORS[code][1]`
    verbatim, and the five level-1 anchors are no longer the same string, so a
    fixture that hard-codes the shared prefix would be testing nothing.
    """
    return DimensionScore(
        score=1,
        anchor_matched=RUBRIC_ANCHORS[code][1],
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
    return Verdict(
        demand=dimension("D"),
        market=dimension("M"),
        competitive_room=dimension("C"),
        feasibility=dimension("F"),
        headroom_over_free=dimension("X"),
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
                    # Exactly once: a second copy is a stale ladder the model
                    # can still read, and `assertIn` alone would not see it.
                    self.assertEqual(description.count(text), 1)

    def test_adjacent_anchors_cannot_be_confused_by_the_guardrail(self) -> None:
        """The anchor check is only binding if the ladders are separable.

        `anchor_problems` accepts `anchor_matched` at >= ANCHOR_MATCH_THRESHOLD
        token overlap with the anchor for the claimed score. If two anchors in
        one ladder overlap at or above that threshold, the Synthesist can quote
        either and pass at either score - the rubric would still be binding on
        paper and unbinding in fact. Margin matters too: a real answer drops or
        adds a word, so a pair sitting just under the threshold can cross it.
        """
        worst = 0.0
        for code, ladder in RUBRIC_ANCHORS.items():
            for low, high in itertools.combinations(sorted(ladder), 2):
                with self.subTest(dimension=code, pair=(low, high)):
                    overlap = token_overlap(ladder[low], ladder[high])
                    worst = max(worst, overlap)
                    self.assertLess(overlap, ANCHOR_MATCH_THRESHOLD)
        self.assertLess(worst, 0.75, "anchors are separable but with no margin")

    def test_every_level_one_anchor_names_the_branch_condition(self) -> None:
        """PRD §10.2 reserves 1 for "the evidence does not reach this question".

        A bare reserved phrase says when 1 means, not when it FIRES, and three
        of the four hard floors (M=0, F=0, X=0) are decided on exactly that
        boundary. Every ladder therefore states the branch condition, and the
        five differ - `anchor_problems` matches a score of 1 verbatim per
        dimension, so identical strings would make that check dimensionless.
        """
        level_ones = {code: ladder[1] for code, ladder in RUBRIC_ANCHORS.items()}

        for code, text in level_ones.items():
            with self.subTest(dimension=code):
                self.assertTrue(text.startswith(LEVEL_ONE_ANCHOR))
                self.assertGreater(len(text), len(LEVEL_ONE_ANCHOR) + 10)
        self.assertEqual(len(set(level_ones.values())), len(level_ones))

    def test_no_anchor_scores_on_popularity(self) -> None:
        """PRD §10.2's substantive improvement, asserted rather than trusted.

        `Thread.points` and `Thread.num_comments` ARE populated now, so nothing
        but this test stops a future edit anchoring Demand on upvotes - which
        is precisely the tutorial failure the rubric exists to fix: "a single
        ReAct agent reads HN sentiment as approval of the idea rather than
        evidence of the problem".
        """
        forbidden = ("points", "num_comments", "comment count", "star", "upvote", "popular")
        for code, ladder in RUBRIC_ANCHORS.items():
            for value, text in ladder.items():
                for term in forbidden:
                    with self.subTest(dimension=code, score=value, term=term):
                        self.assertNotIn(term, text.casefold())

    def test_the_archived_flag_is_used_only_where_a_null_is_harmless(self) -> None:
        """`Repo.archived` is tri-state: None means "GitHub did not report it".

        It earns its place in the X floor (PRD: an archived project is not
        maintained, so it is not the free thing that already does the whole
        job), but only phrased so an unreported flag scores exactly as it did
        before the field existed. X=0 requires "not marked archived", which a
        None satisfies; X=2 requires "marked archived" as one disjunct among
        licence and staleness, which a None simply does not trigger.
        """
        users = {
            (code, score)
            for code, ladder in RUBRIC_ANCHORS.items()
            for score, text in ladder.items()
            if "archived" in text.casefold()
        }

        self.assertEqual(users, {("X", 0), ("X", 2)})
        self.assertIn("is not marked archived", RUBRIC_ANCHORS["X"][0])
        self.assertIn("marked archived,", RUBRIC_ANCHORS["X"][2])

    def test_shorthand_terms_in_the_anchors_are_defined_for_the_synthesist(self) -> None:
        """The anchors are short so they stay separable; the prompt carries the
        definitions that make them countable. A term used and never defined is
        a judgement call wearing a countable term's clothes."""
        tasks = yaml.safe_load((CONFIG_DIR / "tasks.yaml").read_text(encoding="utf-8"))
        description = tasks["synthesis_task"]["description"]
        # Defined term -> the fragment an anchor must actually contain, which
        # differs where the anchors inflect the term ("is reusable").
        terms = {
            "usable thread": "usable thread",
            "problem thread": "problem thread",
            "reusable repository": "reusable",
            "free substitute": "free substitute",
            "free product": "free product",
            "vendor owned": "vendor owned",
            "dated within 24 months": "dated within 24 months",
        }
        anchors = [text.casefold() for ladder in RUBRIC_ANCHORS.values() for text in ladder.values()]

        for term, fragment in terms.items():
            with self.subTest(term=term):
                self.assertIn(f"{term} - ", description)
                self.assertTrue(
                    any(fragment in text for text in anchors),
                    f"{term} is defined for the Synthesist but no anchor uses it",
                )

    def test_market_task_defines_the_flag_the_competitive_ladder_scores_on(self) -> None:
        """C=0, C=2 and C=5 all turn on `Competitor.vendor_owned`, which no
        prompt used to define - the model set a bool nobody had specified."""
        tasks = yaml.safe_load((CONFIG_DIR / "tasks.yaml").read_text(encoding="utf-8"))

        self.assertIn("vendor_owned", tasks["market_task"]["description"])

    def test_prompts_request_the_spec_fields_and_a_risks_section(self) -> None:
        """F05, F06, F07 and F13 - a schema field nothing asks for stays null."""
        tasks = yaml.safe_load((CONFIG_DIR / "tasks.yaml").read_text(encoding="utf-8"))
        expected = {
            "market_task": ["paying_segments", "dated_is_retrieval_time"],
            "sentiment_task": ["points", "num_comments", "date_is_retrieval_time"],
            "feasibility_task": ["archived", "months_since_push"],
            "reporting_task": ["Risks", "kill criteria", "cheapest next test"],
        }

        for name, fragments in expected.items():
            description = tasks[name]["description"]
            for fragment in fragments:
                with self.subTest(task=name, fragment=fragment):
                    self.assertIn(fragment, description)

    def test_the_recency_clause_excludes_a_retrieval_time_fallback(self) -> None:
        """F16. Six anchors across D, M and C turn on "dated within 24 months",
        and a retrieval-time fallback is always inside that window. The
        Synthesist has to be told what the guardrail already enforces, or the
        first thing it learns about the rule is a rejection."""
        tasks = yaml.safe_load((CONFIG_DIR / "tasks.yaml").read_text(encoding="utf-8"))
        description = tasks["synthesis_task"]["description"]
        definition = next(
            line for line in description.splitlines() if "dated within 24 months - " in line
        )

        self.assertIn("dated_is_retrieval_time", definition)
        self.assertIn("date_is_retrieval_time", definition)
        self.assertIn("never dated within 24 months", definition)

    def test_the_synthesist_is_warned_that_scores_are_checked_against_counts(self) -> None:
        """A guardrail the prompt does not mention is a guardrail the model
        discovers by failing. It also has to know the bound is two-sided at 0
        and 1, or it will reach for a low score to dodge a floor."""
        tasks = yaml.safe_load((CONFIG_DIR / "tasks.yaml").read_text(encoding="utf-8"))
        description = tasks["synthesis_task"]["description"]

        self.assertIn("rejects a score the evidence cannot carry", description)
        self.assertIn("in both directions", description)

    def test_every_countable_anchor_term_is_recomputed_by_a_counter(self) -> None:
        """F16. The ladders were rewritten to score on countable terms; this
        asserts the counters that make each one enforceable actually exist,
        because an anchor whose term nothing recomputes is scored by the model
        alone."""
        counts = compute_evidence_counts(
            MarketFindings(
                sources=[], source_urls=[], gaps=[], tool_status="empty", competitors=[]
            ),
            SentimentFindings(sources=[], source_urls=[], gaps=[], tool_status="empty"),
            FeasibilityFindings(sources=[], source_urls=[], gaps=[], tool_status="empty"),
        )
        required = {
            "usable thread": "sentiment_usable_threads",
            "problem thread": "sentiment_problem_threads",
            "reusable": "feasibility_reusable_repos",
            "free substitute": "feasibility_live_substitutes",
            "paying segment": "market_paying_segments",
        }

        for term, counter in required.items():
            with self.subTest(term=term):
                self.assertIn(counter, counts)

    def test_owned_implementation_has_no_openai_model_string(self) -> None:
        root = CONFIG_DIR.parent
        files = [*root.rglob("*.py"), *root.rglob("*.yaml")]
        forbidden = "open" + "ai/"
        for path in files:
            with self.subTest(path=path.name):
                self.assertNotIn(forbidden, path.read_text(encoding="utf-8").lower())


if __name__ == "__main__":
    unittest.main()