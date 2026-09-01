"""YAML-first single-agent crews used by the validator Flow."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, Literal, TypeVar

from crewai import LLM, Agent, Crew, Process, Task
from crewai.agents.agent_builder.base_agent import BaseAgent
from crewai.project import CrewBase, agent, crew, task
from pydantic import BaseModel, PrivateAttr

from brief_crew.config import (
    CHEAP_MODEL,
    ESCALATION_MODEL,
    VALIDATOR_BRANCH_MAX_ITER,
    VALIDATOR_BRANCH_MAX_TOKENS,
    VALIDATOR_BRANCH_TEMPERATURE,
    VALIDATOR_MARKET_SEARCH_LIMIT,
    VALIDATOR_SENTIMENT_STORY_LIMIT,
    VALIDATOR_SYNTHESIST_REASONING_EFFORT,
    openrouter_reasoning_params,
)
from brief_crew.schemas import (
    FeasibilityFindings,
    MarketFindings,
    ScopedIdea,
    SentimentFindings,
    ValidationReport,
    Verdict,
)
from brief_crew.tools.github_feasibility import GitHubFeasibilityTool
from brief_crew.tools.hn_sentiment import HackerNewsSentimentTool
from brief_crew.tools.market_research import MarketResearchTool
from brief_crew.validator_guardrails import (
    CITATION_GUARDRAIL,
    check_scope,
    findings_problems,
    make_report_guardrail,
    make_rubric_guardrail,
    parse_raw_model,
)

BranchName = Literal["market", "sentiment", "feasibility"]
FindingsModel = MarketFindings | SentimentFindings | FeasibilityFindings
FindingsT = TypeVar("FindingsT", bound=FindingsModel)
Guardrail = Callable[[Any], tuple[bool, str]]


def _capture_urls(raw: str, urls: set[str]) -> None:
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return
    if not isinstance(payload, dict):
        return
    for result in payload.get("results", []):
        if isinstance(result, dict) and isinstance(result.get("url"), str):
            urls.add(result["url"])


class _RecordingMarketTool(MarketResearchTool):
    _captured_urls: set[str] = PrivateAttr(default_factory=set)

    @property
    def captured_urls(self) -> frozenset[str]:
        return frozenset(self._captured_urls)

    # These defaults MUST track the tool's own. A subclass that re-declares the
    # signature re-declares the default with it, so leaving `5` here would have
    # silently restored the five-scrape call the constant exists to bound - and
    # nothing would have failed, the branch would just still be slow.
    def _run(self, query: str, limit: int = VALIDATOR_MARKET_SEARCH_LIMIT) -> str:
        raw = super()._run(query=query, limit=limit)
        _capture_urls(raw, self._captured_urls)
        return raw


class _RecordingSentimentTool(HackerNewsSentimentTool):
    _captured_urls: set[str] = PrivateAttr(default_factory=set)

    @property
    def captured_urls(self) -> frozenset[str]:
        return frozenset(self._captured_urls)

    def _run(
        self,
        query: str,
        story_limit: int = VALIDATOR_SENTIMENT_STORY_LIMIT,
        comments_per_story: int = 5,
    ) -> str:
        raw = super()._run(
            query=query,
            story_limit=story_limit,
            comments_per_story=comments_per_story,
        )
        _capture_urls(raw, self._captured_urls)
        return raw


class _RecordingFeasibilityTool(GitHubFeasibilityTool):
    _captured_urls: set[str] = PrivateAttr(default_factory=set)

    @property
    def captured_urls(self) -> frozenset[str]:
        return frozenset(self._captured_urls)

    def _run(self, query: str, limit: int = 5) -> str:
        raw = super()._run(query=query, limit=limit)
        _capture_urls(raw, self._captured_urls)
        return raw


def _dynamic_findings_guardrail(
    branch: BranchName,
    model: type[FindingsT],
    tool: _RecordingMarketTool | _RecordingSentimentTool | _RecordingFeasibilityTool,
) -> Guardrail:
    def guardrail(output: Any) -> tuple[bool, str]:
        raw = output.raw or ""
        try:
            findings = parse_raw_model(raw, model)
        except ValueError as exc:
            return False, f"SCHEMA: {exc}"
        problems = findings_problems(findings, tool.captured_urls)
        return (False, " | ".join(problems)) if problems else (True, raw)

    guardrail.__name__ = f"check_{branch}_findings"
    return guardrail


def _branch_llm() -> LLM:
    """The model the three research branches share, with sampling pinned.

    A bare `LLM(model=...)` sends NO temperature, so the PROVIDER's default
    applies - measured at 1.0 for the model this replaced. The branch tasks are
    verbatim extraction (copy this claim, copy this URL, copy this date), and
    the cost of a sampling wobble is not a differently-worded sentence: each
    branch has a guardrail binding its output to URLs the tool actually
    returned, and `guardrail_max_retries: 2` re-runs the ENTIRE task on a
    rejection. That is what happened to the sentiment branch on the last live
    run - twice - before it gave up and contributed nothing.

    Temperature measured flat for latency (1.25s vs 1.31s at T=0), so this is a
    correctness setting that happens to save the time a retry would have cost.

    `max_tokens` is a real latency bound, because generation is the slow half of
    a call. `top_p` is deliberately left unset: it is redundant at T=0, and one
    knob doing the job is easier to reason about than two.
    """

    return LLM(
        model=CHEAP_MODEL,
        temperature=VALIDATOR_BRANCH_TEMPERATURE,
        max_tokens=VALIDATOR_BRANCH_MAX_TOKENS,
    )


def _single_agent_crew(agent_instance: BaseAgent, task_instance: Task) -> Crew:
    return Crew(
        agents=[agent_instance],
        tasks=[task_instance],
        process=Process.sequential,
        memory=False,
        # `Crew.cache` defaults to False in CrewAI 1.15.18, and `Agent.cache`
        # defaults True but is INERT without it: `Crew` only hands the agent a
        # cache handler under `if self.cache` (crew.py:760-761). So a
        # byte-identical repeat query - which a guardrail retry produces almost
        # by definition, since the retry re-runs the whole task - was paying
        # full price for a Firecrawl scrape it had already done.
        #
        # This caches TOOL results within one crew run only. It is not the
        # Pinecone warm cache and does not cross runs.
        cache=True,
        verbose=True,
    )


@CrewBase
class ScopeCrew:
    agents: list[BaseAgent]
    tasks: list[Task]
    agents_config = "config/agents.yaml"
    tasks_config = "config/tasks.yaml"

    @agent
    def scoper(self) -> Agent:
        return Agent(
            config=self.agents_config["scoper"],  # type: ignore[index]
            tools=[],
            llm=LLM(model=ESCALATION_MODEL),
            allow_delegation=False,
        )

    @task
    def scoping_task(self) -> Task:
        return Task(
            config=self.tasks_config["scoping_task"],  # type: ignore[index]
            agent=self.scoper(),
            output_pydantic=ScopedIdea,
            guardrails=[check_scope],
        )

    @crew
    def crew(self) -> Crew:
        return _single_agent_crew(self.scoper(), self.scoping_task())


@CrewBase
class MarketCrew:
    agents: list[BaseAgent]
    tasks: list[Task]
    agents_config = "config/agents.yaml"
    tasks_config = "config/tasks.yaml"

    def __init__(self) -> None:
        self.tool = _RecordingMarketTool()

    @agent
    def market_analyst(self) -> Agent:
        return Agent(
            config=self.agents_config["market_analyst"],  # type: ignore[index]
            tools=[self.tool],
            llm=_branch_llm(),
            allow_delegation=False,
            max_iter=VALIDATOR_BRANCH_MAX_ITER,
        )

    @task
    def market_task(self) -> Task:
        return Task(
            config=self.tasks_config["market_task"],  # type: ignore[index]
            agent=self.market_analyst(),
            output_pydantic=MarketFindings,
            guardrails=[
                _dynamic_findings_guardrail("market", MarketFindings, self.tool)
            ],
        )

    @crew
    def crew(self) -> Crew:
        return _single_agent_crew(self.market_analyst(), self.market_task())


@CrewBase
class SentimentCrew:
    agents: list[BaseAgent]
    tasks: list[Task]
    agents_config = "config/agents.yaml"
    tasks_config = "config/tasks.yaml"

    def __init__(self) -> None:
        self.tool = _RecordingSentimentTool()

    @agent
    def sentiment_analyst(self) -> Agent:
        return Agent(
            config=self.agents_config["sentiment_analyst"],  # type: ignore[index]
            tools=[self.tool],
            llm=_branch_llm(),
            allow_delegation=False,
            max_iter=VALIDATOR_BRANCH_MAX_ITER,
        )

    @task
    def sentiment_task(self) -> Task:
        return Task(
            config=self.tasks_config["sentiment_task"],  # type: ignore[index]
            agent=self.sentiment_analyst(),
            output_pydantic=SentimentFindings,
            guardrails=[
                _dynamic_findings_guardrail(
                    "sentiment", SentimentFindings, self.tool
                )
            ],
        )

    @crew
    def crew(self) -> Crew:
        return _single_agent_crew(self.sentiment_analyst(), self.sentiment_task())


@CrewBase
class FeasibilityCrew:
    agents: list[BaseAgent]
    tasks: list[Task]
    agents_config = "config/agents.yaml"
    tasks_config = "config/tasks.yaml"

    def __init__(self) -> None:
        self.tool = _RecordingFeasibilityTool()

    @agent
    def feasibility_analyst(self) -> Agent:
        return Agent(
            config=self.agents_config["feasibility_analyst"],  # type: ignore[index]
            tools=[self.tool],
            llm=_branch_llm(),
            allow_delegation=False,
            max_iter=VALIDATOR_BRANCH_MAX_ITER,
        )

    @task
    def feasibility_task(self) -> Task:
        return Task(
            config=self.tasks_config["feasibility_task"],  # type: ignore[index]
            agent=self.feasibility_analyst(),
            output_pydantic=FeasibilityFindings,
            guardrails=[
                _dynamic_findings_guardrail(
                    "feasibility", FeasibilityFindings, self.tool
                )
            ],
        )

    @crew
    def crew(self) -> Crew:
        return _single_agent_crew(
            self.feasibility_analyst(), self.feasibility_task()
        )


@CrewBase
class SynthesisCrew:
    agents: list[BaseAgent]
    tasks: list[Task]
    agents_config = "config/agents.yaml"
    tasks_config = "config/tasks.yaml"

    def __init__(
        self,
        market: MarketFindings,
        sentiment: SentimentFindings,
        feasibility: FeasibilityFindings,
    ) -> None:
        self.market = market
        self.sentiment = sentiment
        self.feasibility = feasibility

    @agent
    def synthesist(self) -> Agent:
        # F09: the rubric call gets an explicit reasoning effort instead of the
        # provider default. `LLM(reasoning_effort=...)` is a no-op on
        # OpenRouter in CrewAI 1.15.18 - see config.openrouter_reasoning_params
        # for why the setting has to travel in `extra_body`.
        return Agent(
            config=self.agents_config["synthesist"],  # type: ignore[index]
            tools=[],
            llm=LLM(
                model=ESCALATION_MODEL,
                additional_params=openrouter_reasoning_params(
                    VALIDATOR_SYNTHESIST_REASONING_EFFORT
                ),
            ),
            allow_delegation=False,
        )

    @task
    def synthesis_task(self) -> Task:
        return Task(
            config=self.tasks_config["synthesis_task"],  # type: ignore[index]
            agent=self.synthesist(),
            output_pydantic=Verdict,
            guardrails=[
                make_rubric_guardrail(
                    self.market,
                    self.sentiment,
                    self.feasibility,
                )
            ],
        )

    @crew
    def crew(self) -> Crew:
        return _single_agent_crew(self.synthesist(), self.synthesis_task())


@CrewBase
class ReportCrew:
    agents: list[BaseAgent]
    tasks: list[Task]
    agents_config = "config/agents.yaml"
    tasks_config = "config/tasks.yaml"

    def __init__(self, verdict: Verdict, tool_urls: set[str]) -> None:
        self.verdict = verdict
        self.tool_urls = tool_urls

    @agent
    def reporter(self) -> Agent:
        return Agent(
            config=self.agents_config["reporter"],  # type: ignore[index]
            tools=[],
            llm=LLM(model=ESCALATION_MODEL),
            allow_delegation=False,
        )

    @task
    def reporting_task(self) -> Task:
        task_config = dict(self.tasks_config["reporting_task"])  # type: ignore[index]
        citation_guardrail = str(task_config.pop("citation_guardrail"))
        if citation_guardrail.strip() != CITATION_GUARDRAIL.strip():
            raise ValueError(
                "reporting_task.citation_guardrail must match CITATION_GUARDRAIL"
            )
        return Task(
            config=task_config,
            agent=self.reporter(),
            output_pydantic=ValidationReport,
            guardrails=[
                make_report_guardrail(self.verdict, self.tool_urls),
                citation_guardrail,
            ],
        )

    @crew
    def crew(self) -> Crew:
        return _single_agent_crew(self.reporter(), self.reporting_task())


__all__ = [
    "FeasibilityCrew",
    "MarketCrew",
    "ReportCrew",
    "ScopeCrew",
    "SentimentCrew",
    "SynthesisCrew",
]