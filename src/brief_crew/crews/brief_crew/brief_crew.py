"""The three-agent brief crew - Researcher -> Analyst -> Writer.

This is the assembly layer and nothing else. Every prompt lives in
``config/agents.yaml`` and ``config/tasks.yaml``; every model name, price and
threshold lives in ``brief_crew.config``. What is left here is the wiring that
genuinely cannot be expressed as data: LLM objects, tool instances, the
guardrail list (which mixes a callable with a string), and the track switch.

Two tracks, one class - see agents/00-shared-config.md:

  Track A  the classroom crew. `Process.sequential`, and the Researcher owns the
           cache check itself via `retrieve_and_rerank`. Build this first and get
           it running end to end.
  Track B  the hosted service. The Flow in `main.py` retrieves and reranks BEFORE
           any agent runs, so the Researcher is only ever reached on a cache
           miss. It gets two tools and a task with no step 0.

The tool list and the task variant are selected together from the single
``track`` argument, because pairing them wrongly - an agent told to call a tool
it does not have - is exactly the setup that produces fabricated citations.
"""

from __future__ import annotations

from typing import Literal

from crewai import LLM, Agent, Crew, Process, Task
from crewai.agents.agent_builder.base_agent import BaseAgent
from crewai.project import CrewBase, agent, crew, task
from crewai_tools import FirecrawlSearchTool

from brief_crew.config import CHEAP_MODEL, ESCALATION_MODEL
from brief_crew.crews.brief_crew.scrape_tool import ScrapeWebsiteTool
from brief_crew.guardrails import ATTRIBUTION_GUARDRAIL, check_mechanics
from brief_crew.tools.pinecone_retrieval import PineconeRetrieveRerankTool

Track = Literal["A", "B"]


@CrewBase
class BriefCrew:
    """One topic in, one one-page brief out."""

    agents: list[BaseAgent]
    tasks: list[Task]

    agents_config = "config/agents.yaml"
    tasks_config = "config/tasks.yaml"

    def __init__(
        self,
        track: Track = "A",
        writer_model: str | None = None,
        from_notes: bool = False,
    ) -> None:
        self.track: Track = track
        # from_notes is the Flow's cache_hit branch: the Researcher never runs,
        # so there is no upstream task output for the Analyst to inherit and the
        # material arrives as a {research_notes} kickoff input instead. The crew
        # is then two agents, not three.
        self.from_notes = from_notes
        # 03-writer.md nominates the Writer as the crew's A/B candidate for the
        # cheap tier: its task is the most heavily templated, so most of the
        # difficulty is solved by task design rather than model capability. That
        # is a 15x difference on completion tokens, applied to the crew's most
        # output-heavy agent. Pass writer_model=CHEAP_MODEL to run the arm.
        self.writer_model = writer_model or ESCALATION_MODEL

    # ---------------------------------------------------------------- agents

    @agent
    def researcher(self) -> Agent:
        """The only agent with tools, and the only one touching the outside world."""
        tools = [
            FirecrawlSearchTool(config={"limit": 5}),
            # Not crewai_tools' scrape tool directly: that one declares no
            # result_schema, so CrewAI hands both this agent and main.py's
            # capture sink `str(Document)` - a pydantic repr with the page's
            # newlines escaped, which chunks on character counts rather than on
            # headings. See scrape_tool.py.
            ScrapeWebsiteTool(),
        ]
        if self.track == "A":
            # Track A only. Under the Flow, retrieval has already run and already
            # failed the staleness gate before this agent is reached - leaving the
            # tool on would re-issue the query that just failed and pay for a
            # second embed and rerank to get the same miss.
            tools.insert(0, PineconeRetrieveRerankTool())

        return Agent(
            config=self.agents_config["researcher"],  # type: ignore[index]
            tools=tools,
            # Cheap tier on purpose: this agent's context is dominated by scraped
            # markdown, so input price is the dominant term. 10x cheaper on input
            # than the escalation tier, with a larger context window.
            llm=LLM(model=CHEAP_MODEL),
        )

    @agent
    def analyst(self) -> Agent:
        """No tools - deliberate. See 02-analyst.md 'Why no tools'.

        The empty tool surface is what makes every claim here traceable back to
        the Researcher's notes: anything new that appears is unambiguously
        invented, and it sits in the trace one hand-off after its source. A
        retrieval tool now exists in this codebase; do not give it to this agent.
        """
        return Agent(
            config=self.agents_config["analyst"],  # type: ignore[index]
            tools=[],
            # The one real judgement step in the crew. Do not run it on the cheap
            # tier - selection and framing is where the brief's quality is decided.
            llm=LLM(model=ESCALATION_MODEL),
        )

    @agent
    def writer(self) -> Agent:
        return Agent(
            config=self.agents_config["writer"],  # type: ignore[index]
            tools=[],
            llm=LLM(model=self.writer_model),
        )

    # ----------------------------------------------------------------- tasks

    @task
    def research_task(self) -> Task:
        key = "research_task" if self.track == "A" else "research_task_scrape_only"
        return Task(config=self.tasks_config[key])  # type: ignore[index]

    @task
    def analysis_task(self) -> Task:
        if self.from_notes:
            # No context: there is no prior task on this branch. The material is
            # interpolated into the description from kickoff inputs instead.
            return Task(config=self.tasks_config["analysis_task_from_notes"])  # type: ignore[index]
        return Task(
            config=self.tasks_config["analysis_task"],  # type: ignore[index]
            context=[self.research_task()],
        )

    @task
    def writing_task(self) -> Task:
        if self.from_notes:
            return Task(
                config=self.tasks_config["writing_task_from_notes"],  # type: ignore[index]
                context=[self.analysis_task()],
                guardrails=[check_mechanics, ATTRIBUTION_GUARDRAIL],
            )
        return Task(
            config=self.tasks_config["writing_task"],  # type: ignore[index]
            # The Writer needs the Analyst's argument for structure AND the
            # Researcher's notes for the source URLs, which the Analyst
            # compresses away. Naming both is not optional documentation:
            # Crew._get_context treats an explicit list as a REPLACEMENT for the
            # implicit all-prior aggregation, not an addition to it. Drop
            # research_task from this list and the Writer silently loses every URL.
            context=[self.research_task(), self.analysis_task()],
            # Cheapest check first: check_mechanics is arithmetic and costs
            # nothing, so it rejects on length or missing sources before the
            # string guardrail - which is a real LLM call on every evaluation -
            # is ever reached.
            guardrails=[check_mechanics, ATTRIBUTION_GUARDRAIL],
        )

    # ------------------------------------------------------------------ crew

    @crew
    def crew(self) -> Crew:
        """Assemble the crew. Construct a fresh one per run, never share one.

        The agent and task lists are built explicitly rather than taken from the
        decorator-collected ``self.agents`` / ``self.tasks``, because the
        cache-hit branch is a two-agent crew: including the Researcher and its
        task there would run a live scrape on exactly the path whose whole point
        is not scraping.
        """
        if self.from_notes:
            agents: list[BaseAgent] = [self.analyst(), self.writer()]
            tasks: list[Task] = [self.analysis_task(), self.writing_task()]
        else:
            agents = [self.researcher(), self.analyst(), self.writer()]
            tasks = [self.research_task(), self.analysis_task(), self.writing_task()]

        return Crew(
            agents=agents,
            tasks=tasks,
            process=Process.sequential,
            # Keeps CrewAI's default OpenAI embedder unreachable, which is why
            # this project needs no OPENAI_API_KEY. It also means CrewAI writes
            # nothing durable, so Render's ephemeral disk is a non-issue.
            memory=False,
            # Not decoration: this is the trace, and the only view you have of
            # who handed off to whom.
            verbose=True,
        )
