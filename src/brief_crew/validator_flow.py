#!/usr/bin/env python
"""Headless six-agent validator orchestration."""

from __future__ import annotations

import argparse
import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar, Literal, Protocol, TypeVar

from crewai.flow import Flow, and_, listen, or_, router, start
from crewai.flow.async_feedback import (
    HumanFeedbackPending,
    HumanFeedbackProvider,
    PendingFeedbackContext,
)
from crewai.flow.human_feedback import HumanFeedbackResult, human_feedback
from pydantic import BaseModel, Field

from brief_crew.config import CHEAP_MODEL, VALIDATOR_FEASIBILITY_CACHE_ENABLED
from brief_crew.crews.validator_crew import (
    FeasibilityCrew,
    MarketCrew,
    ReportCrew,
    ScopeCrew,
    SentimentCrew,
    SynthesisCrew,
)
from brief_crew.schemas import (
    FeasibilityFindings,
    MarketFindings,
    ScopedIdea,
    SentimentFindings,
    ValidationReport,
    Verdict,
)
from brief_crew.validator_guardrails import findings_urls, parse_raw_model
from brief_crew.validator_cache import (
    BranchName,
    CapturedToolResult,
    capture_tool_results,
    format_cached_evidence,
    index_captured_evidence,
    lookup_branch_cache,
    resolve_namespace,
)

OUTPUT_PATH = Path("output") / "validation.md"
ModelT = TypeVar("ModelT", bound=BaseModel)


class KickoffRunner(Protocol):
    def kickoff(self, inputs: dict[str, Any]) -> Any: ...


def _scope_runner() -> KickoffRunner:
    return ScopeCrew().crew()


def _market_runner() -> KickoffRunner:
    return MarketCrew().crew()


def _sentiment_runner() -> KickoffRunner:
    return SentimentCrew().crew()


def _feasibility_runner() -> KickoffRunner:
    return FeasibilityCrew().crew()


def _synthesis_runner(
    market: MarketFindings,
    sentiment: SentimentFindings,
    feasibility: FeasibilityFindings,
) -> KickoffRunner:
    return SynthesisCrew(market, sentiment, feasibility).crew()


def _report_runner(verdict: Verdict, tool_urls: set[str]) -> KickoffRunner:
    return ReportCrew(verdict, tool_urls).crew()


@dataclass(frozen=True)
class ValidatorCrewFactories:
    scope: Callable[[], KickoffRunner] = _scope_runner
    market: Callable[[], KickoffRunner] = _market_runner
    sentiment: Callable[[], KickoffRunner] = _sentiment_runner
    feasibility: Callable[[], KickoffRunner] = _feasibility_runner
    synthesis: Callable[
        [MarketFindings, SentimentFindings, FeasibilityFindings], KickoffRunner
    ] = _synthesis_runner
    report: Callable[[Verdict, set[str]], KickoffRunner] = _report_runner


class ValidatorFeedbackProvider(HumanFeedbackProvider):
    """Auto-approve explicit no-gates runs; otherwise pause for native resume."""

    def request_feedback(
        self,
        context: PendingFeedbackContext,
        flow: Flow[Any],
    ) -> str:
        if getattr(flow.state, "no_gates", False):
            return json.dumps({"decision": "approve"})
        raise HumanFeedbackPending(
            context=context,
            callback_info={"gate": context.method_name},
        )


FEEDBACK_PROVIDER = ValidatorFeedbackProvider()


class ValidatorState(BaseModel):
    idea: str = ""
    no_gates: bool = False
    namespace: str = ""
    feasibility_cache_enabled: bool = VALIDATOR_FEASIBILITY_CACHE_ENABLED
    source_run_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    scope: ScopedIdea | None = None
    market: MarketFindings | None = None
    sentiment: SentimentFindings | None = None
    feasibility: FeasibilityFindings | None = None
    verdict: Verdict | None = None
    report: ValidationReport | None = None
    scope_gate_reply: str = ""
    verdict_gate_reply: str = ""
    scope_revision: str = ""
    verdict_revision: str = ""
    scope_route: str = ""
    verdict_route: str = ""


def _extract_model(result: Any, model: type[ModelT]) -> ModelT:
    if isinstance(result, model):
        return result
    structured = getattr(result, "pydantic", None)
    if isinstance(structured, model):
        return structured
    if structured is not None:
        return model.model_validate(structured)
    raw = getattr(result, "raw", result)
    return parse_raw_model(str(raw), model)


def _require(value: ModelT | None, label: str) -> ModelT:
    if value is None:
        raise RuntimeError(f"{label} is unavailable at this Flow step")
    return value


def _gate_payload(feedback: str) -> dict[str, Any]:
    try:
        payload = json.loads(feedback or "{}")
    except json.JSONDecodeError:
        payload = {"decision": feedback.strip().lower()}
    return payload if isinstance(payload, dict) else {}


class ValidatorFlow(Flow[ValidatorState]):
    """Scope, fan out three evidence crews, synthesize, review and persist."""

    _skip_auto_memory: ClassVar[bool] = True
    crew_factories: ValidatorCrewFactories = Field(
        default_factory=ValidatorCrewFactories,
        exclude=True,
    )

    @start()
    def scope_idea(self) -> ScopedIdea:
        """Turn the idea into the shared research contract."""
        result = self.crew_factories.scope().kickoff(
            inputs={"idea": self.state.idea, "human_override": ""}
        )
        self.state.scope = _extract_model(result, ScopedIdea)
        return self.state.scope

    @listen("scope_revise")
    def revise_scope(self) -> ScopedIdea:
        """Regenerate scope from the operator's requested correction."""
        result = self.crew_factories.scope().kickoff(
            inputs={
                "idea": self.state.idea,
                "human_override": self.state.scope_revision,
            }
        )
        self.state.scope = _extract_model(result, ScopedIdea)
        return self.state.scope

    @human_feedback(
        message=(
            "Confirm the parsed scope. Reply with JSON using decision=approve, or "
            "decision=revise plus feedback and an optional edited scope object."
        ),
        emit=None,
        llm=CHEAP_MODEL,
        provider=FEEDBACK_PROVIDER,
    )
    @listen(or_(scope_idea, revise_scope))
    def confirm_scope(self, _: ScopedIdea) -> str:
        """Pause after scoping so the operator can approve or revise it."""
        return _require(self.state.scope, "scope").model_dump_json(indent=2)

    @router(confirm_scope)
    def route_scope(
        self, result: HumanFeedbackResult
    ) -> Literal["scope_approved", "scope_revise"]:
        """Route the structured scope reply without an LLM call."""
        self.state.scope_gate_reply = result.feedback
        payload = _gate_payload(result.feedback)
        edited_scope = payload.get("scope")
        if isinstance(edited_scope, dict):
            self.state.scope = ScopedIdea.model_validate(edited_scope)
        decision = str(payload.get("decision", "approve")).strip().lower()
        if decision == "revise":
            self.state.scope_revision = str(
                payload.get("feedback") or result.feedback
            )
            self.state.scope_route = "scope_revise"
            return "scope_revise"
        self.state.scope_route = "scope_approved"
        return "scope_approved"

    @listen("scope_approved")
    def research_market(self) -> MarketFindings:
        """Run the market branch in a Flow-managed worker thread."""
        scope = _require(self.state.scope, "scope")
        namespace = resolve_namespace(self.state.namespace)
        cached = self._cached_evidence("market", scope, namespace)
        with capture_tool_results("market") as tool_results:
            result = self.crew_factories.market().kickoff(
                inputs={
                    "scoped_idea_json": scope.model_dump_json(indent=2),
                    "market_query": scope.market_query,
                    "cached_evidence_block": format_cached_evidence(cached),
                }
            )
        self.state.market = _extract_model(result, MarketFindings)
        self._index_evidence("market", scope, namespace, tool_results)
        return self.state.market

    @listen("scope_approved")
    def research_sentiment(self) -> SentimentFindings:
        """Run the sentiment branch in a Flow-managed worker thread."""
        scope = _require(self.state.scope, "scope")
        namespace = resolve_namespace(self.state.namespace)
        with capture_tool_results("sentiment") as tool_results:
            result = self.crew_factories.sentiment().kickoff(
                inputs={
                    "scoped_idea_json": scope.model_dump_json(indent=2),
                    "community_queries_block": "\n".join(scope.community_queries),
                }
            )
        self.state.sentiment = _extract_model(result, SentimentFindings)
        self._index_evidence("sentiment", scope, namespace, tool_results)
        return self.state.sentiment

    @listen("scope_approved")
    def research_feasibility(self) -> FeasibilityFindings:
        """Run the feasibility branch in a Flow-managed worker thread."""
        scope = _require(self.state.scope, "scope")
        namespace = resolve_namespace(self.state.namespace)
        cached = self._cached_evidence("feasibility", scope, namespace)
        with capture_tool_results("feasibility") as tool_results:
            result = self.crew_factories.feasibility().kickoff(
                inputs={
                    "scoped_idea_json": scope.model_dump_json(indent=2),
                    "tech_queries_block": "\n".join(scope.tech_queries),
                    "cached_evidence_block": format_cached_evidence(cached),
                }
            )
        self.state.feasibility = _extract_model(result, FeasibilityFindings)
        self._index_evidence("feasibility", scope, namespace, tool_results)
        return self.state.feasibility

    @listen(and_(research_market, research_sentiment, research_feasibility))
    def synthesize(self) -> Verdict:
        """Join all three branches before applying the deterministic rubric."""
        return self._run_synthesis("")

    @listen("verdict_revise")
    def revise_verdict(self) -> Verdict:
        """Re-run synthesis using the operator's requested correction."""
        return self._run_synthesis(self.state.verdict_revision)

    @human_feedback(
        message=(
            "Review the scored verdict. Reply with JSON using decision=approve, or "
            "decision=revise plus feedback and an optional edited verdict object."
        ),
        emit=None,
        llm=CHEAP_MODEL,
        provider=FEEDBACK_PROVIDER,
    )
    @listen(or_(synthesize, revise_verdict))
    def review_verdict(self, _: Verdict) -> str:
        """Pause after synthesis so the operator can approve or revise it."""
        return _require(self.state.verdict, "verdict").model_dump_json(indent=2)

    @router(review_verdict)
    def route_verdict(
        self, result: HumanFeedbackResult
    ) -> Literal["verdict_approved", "verdict_revise"]:
        """Route the structured verdict reply without an LLM call."""
        self.state.verdict_gate_reply = result.feedback
        payload = _gate_payload(result.feedback)
        edited_verdict = payload.get("verdict")
        if isinstance(edited_verdict, dict):
            self.state.verdict = Verdict.model_validate(edited_verdict)
        decision = str(payload.get("decision", "approve")).strip().lower()
        if decision == "revise":
            self.state.verdict_revision = str(
                payload.get("feedback") or result.feedback
            )
            self.state.verdict_route = "verdict_revise"
            return "verdict_revise"
        self.state.verdict_route = "verdict_approved"
        return "verdict_approved"

    @listen("verdict_approved")
    def write_report(self) -> ValidationReport:
        """Turn the deterministic verdict and its evidence into the final brief."""
        scope = _require(self.state.scope, "scope")
        market = _require(self.state.market, "market findings")
        sentiment = _require(self.state.sentiment, "sentiment findings")
        feasibility = _require(self.state.feasibility, "feasibility findings")
        verdict = _require(self.state.verdict, "verdict")
        tool_urls = set().union(
            findings_urls(market),
            findings_urls(sentiment),
            findings_urls(feasibility),
        )
        result = self.crew_factories.report(verdict, tool_urls).kickoff(
            inputs={
                "scoped_idea_json": scope.model_dump_json(indent=2),
                "market_findings_json": market.model_dump_json(indent=2),
                "sentiment_findings_json": sentiment.model_dump_json(indent=2),
                "feasibility_findings_json": feasibility.model_dump_json(indent=2),
                "verdict_json": verdict.model_dump_json(indent=2),
            }
        )
        self.state.report = _extract_model(result, ValidationReport)
        return self.state.report

    @listen(write_report)
    def persist(self) -> ValidationReport:
        """Write only the human-readable report body to output/validation.md."""
        report = _require(self.state.report, "validation report")
        OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT_PATH.write_text(report.markdown_body, encoding="utf-8")
        return report

    def _run_synthesis(self, human_override: str) -> Verdict:
        scope = _require(self.state.scope, "scope")
        market = _require(self.state.market, "market findings")
        sentiment = _require(self.state.sentiment, "sentiment findings")
        feasibility = _require(self.state.feasibility, "feasibility findings")
        result = self.crew_factories.synthesis(
            market,
            sentiment,
            feasibility,
        ).kickoff(
            inputs={
                "scoped_idea_json": scope.model_dump_json(indent=2),
                "market_findings_json": market.model_dump_json(indent=2),
                "sentiment_findings_json": sentiment.model_dump_json(indent=2),
                "feasibility_findings_json": feasibility.model_dump_json(indent=2),
                "human_override": human_override,
            }
        )
        self.state.verdict = _extract_model(result, Verdict)
        return self.state.verdict

    def _cached_evidence(
        self,
        branch: BranchName,
        scope: ScopedIdea,
        namespace: str,
    ) -> list[dict[str, Any]]:
        try:
            return lookup_branch_cache(
                scope,
                branch,
                namespace,
                feasibility_enabled=self.state.feasibility_cache_enabled,
            )
        except Exception:
            return []

    def _index_evidence(
        self,
        branch: BranchName,
        scope: ScopedIdea,
        namespace: str,
        tool_results: list[CapturedToolResult],
    ) -> None:
        try:
            index_captured_evidence(
                tool_results,
                branch=branch,
                scope=scope,
                source_run_id=self.state.source_run_id,
                namespace=namespace,
            )
        except Exception:
            pass


def _print_result(result: ValidationReport | HumanFeedbackPending) -> None:
    if isinstance(result, HumanFeedbackPending):
        print(
            json.dumps(
                {
                    "status": "pending_human_feedback",
                    "flow_id": result.context.flow_id,
                    "gate": result.context.method_name,
                    "message": result.context.message,
                    "output": result.context.method_output,
                },
                indent=2,
            )
        )
        return
    print(result.markdown_body)


def validate(
    idea: str | None = None,
    *,
    no_gates: bool = False,
    namespace: str | None = None,
    feasibility_cache_enabled: bool | None = None,
    crew_factories: ValidatorCrewFactories | None = None,
) -> ValidationReport | HumanFeedbackPending:
    """Run or start the validator without requiring the web studio."""
    if idea is None:
        return _run_cli()
    if not idea.strip():
        raise ValueError("idea must contain non-whitespace text")
    flow = ValidatorFlow(
        crew_factories=crew_factories or ValidatorCrewFactories(),
    )
    inputs: dict[str, Any] = {
        "idea": idea.strip(),
        "no_gates": no_gates,
        "namespace": namespace or "",
    }
    if feasibility_cache_enabled is not None:
        inputs["feasibility_cache_enabled"] = feasibility_cache_enabled
    result = flow.kickoff(inputs=inputs)
    if isinstance(result, HumanFeedbackPending):
        return result
    return _extract_model(result, ValidationReport)


def _run_cli() -> ValidationReport | HumanFeedbackPending:
    parser = argparse.ArgumentParser(description="Validate a startup idea.")
    parser.add_argument("--idea", help="One-line startup idea to validate.")
    parser.add_argument("--resume", metavar="FLOW_ID", help="Resume a pending gate.")
    parser.add_argument(
        "--feedback",
        default=json.dumps({"decision": "approve"}),
        help="Structured JSON feedback supplied when resuming.",
    )
    parser.add_argument(
        "--no-gates",
        "--auto-approve",
        action="store_true",
        dest="no_gates",
        help="Approve both gates without pausing; intended for tests and CI.",
    )
    parser.add_argument(
        "--namespace",
        help="Non-sensitive user/session namespace seed for cache isolation.",
    )
    parser.add_argument(
        "--feasibility-cache",
        action="store_true",
        default=None,
        help="Use feasibility cache as a GitHub rate-limit shock absorber.",
    )
    args = parser.parse_args()

    if args.resume:
        flow = ValidatorFlow.from_pending(args.resume)
        flow.state.no_gates = args.no_gates
        resumed = flow.resume(args.feedback)
        result = (
            resumed
            if isinstance(resumed, HumanFeedbackPending)
            else _extract_model(resumed, ValidationReport)
        )
    else:
        if not args.idea:
            parser.error("--idea is required unless --resume is supplied")
        result = validate(
            args.idea,
            no_gates=args.no_gates,
            namespace=args.namespace,
            feasibility_cache_enabled=args.feasibility_cache,
        )

    _print_result(result)
    return result


if __name__ == "__main__":
    validate()