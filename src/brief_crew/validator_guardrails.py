"""Zero-cost guardrails for validator task outputs.

The one-argument ``check_*`` functions match CrewAI's callable guardrail
contract. Factories add run-scoped evidence when a check needs tool results or
upstream findings, while the ``*_problems`` helpers remain framework-free.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable, Mapping
from typing import Any, Literal, Protocol, TypeVar

from pydantic import BaseModel, ValidationError

from brief_crew.schemas import (
    DimensionScore,
    FeasibilityFindings,
    MarketFindings,
    ScopedIdea,
    SentimentFindings,
    ValidationReport,
    Verdict,
)

BranchName = Literal["market", "sentiment", "feasibility"]
Findings = MarketFindings | SentimentFindings | FeasibilityFindings
GuardrailResult = tuple[bool, str]

ANCHOR_MATCH_THRESHOLD = 0.85
LEVEL_ONE_ANCHOR = "Evidence does not reach this question"
DEMAND_ANCHORS: dict[int, str] = {
    0: "Every retrieved thread is ADJACENT. Nobody in the evidence describes having this problem.",
    1: (
        "Evidence does not reach this question \u2014 the branch returned nothing, "
        "or fewer than 3 usable threads."
    ),
    2: "1\u20132 threads state the problem, or all such threads are older than 36 months.",
    3: (
        "\u22653 threads state it, \u22651 within 24 months, but nobody describes a workaround "
        "or a price paid."
    ),
    4: (
        "Anchor 3, and \u22651 describes a manual workaround they maintain, or names a tool "
        "they pay for."
    ),
    5: (
        "\u22655 threads within 24 months, \u22652 naming a workaround or a price, and the market "
        "branch independently names a paying segment."
    ),
}
RUBRIC_ANCHORS: dict[str, dict[int, str]] = {"D": DEMAND_ANCHORS}

_MODEL_BY_BRANCH: dict[BranchName, type[Findings]] = {
    "market": MarketFindings,
    "sentiment": SentimentFindings,
    "feasibility": FeasibilityFindings,
}
_DIMENSIONS: tuple[tuple[str, str], ...] = (
    ("D", "demand"),
    ("M", "market"),
    ("C", "competitive_room"),
    ("F", "feasibility"),
    ("X", "headroom_over_free"),
)
_URL_RE = re.compile(r"https?://[^\s\)\]<>\"']+")
_TOKEN_RE = re.compile(r"[a-z0-9]+")
_LOW_CONFIDENCE_CLAIMS = ("clearly", "no demand", "proven", "confirms")

ModelT = TypeVar("ModelT", bound=BaseModel)


class TaskOutputLike(Protocol):
    raw: str


def parse_raw_model(raw: str, model: type[ModelT]) -> ModelT:
    """Parse plain or fenced JSON into ``model`` without changing the raw text."""
    text = (raw or "").strip()
    if not text:
        raise ValueError(f"return one JSON object matching {model.__name__}; the output was empty")

    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) < 3 or lines[-1].strip() != "```":
            raise ValueError("close the JSON code fence or return the JSON object without a fence")
        text = "\n".join(lines[1:-1]).strip()

    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"return one valid JSON object matching {model.__name__}; JSON error at "
            f"line {exc.lineno}, column {exc.colno}: {exc.msg}"
        ) from exc

    if not isinstance(payload, dict):
        raise ValueError(f"return one JSON object matching {model.__name__}, not a JSON {type(payload).__name__}")

    try:
        return model.model_validate(payload)
    except ValidationError as exc:
        details = []
        for error in exc.errors(include_url=False):
            location = ".".join(str(part) for part in error["loc"])
            details.append(f"{location}: {error['msg']}")
        raise ValueError(f"fix the {model.__name__} fields: " + " | ".join(details)) from exc


def scope_problems(scope: ScopedIdea) -> list[str]:
    problems: list[str] = []
    if not 3 <= len(scope.assumptions) <= 5:
        problems.append(
            f"SCOPE_ASSUMPTIONS: list 3 to 5 assumptions; found {len(scope.assumptions)}"
        )
    if not scope.scoping_gaps:
        problems.append("SCOPE_GAPS: name at least one unresolved scoping gap")
    return problems


def findings_urls(findings: Findings) -> set[str]:
    urls = set(findings.source_urls)
    if isinstance(findings, MarketFindings):
        urls.update(competitor.url for competitor in findings.competitors if competitor.url)
    return urls


def findings_problems(findings: Findings, allowed_urls: Iterable[str]) -> list[str]:
    problems: list[str] = []
    allowed = set(allowed_urls)
    fabricated = findings_urls(findings) - allowed
    if fabricated:
        problems.append(
            "URL_CLOSURE: remove URLs that were not returned by a tool in this run: "
            + ", ".join(sorted(fabricated))
        )

    if findings.tool_status != "ok":
        if findings.sources:
            problems.append(
                f"STATUS_HONESTY: tool_status is {findings.tool_status!r}, so sources must be empty"
            )
        if not findings.gaps:
            problems.append(
                f"STATUS_HONESTY: tool_status is {findings.tool_status!r}; add a gap explaining "
                "what evidence could not be obtained"
            )
    return problems


def compute_evidence_counts(
    market: MarketFindings,
    sentiment: SentimentFindings,
    feasibility: FeasibilityFindings,
) -> dict[str, int]:
    """Recompute all synthesis counts from branch lists, never model claims."""
    return {
        "market_sources": len(market.sources),
        "market_competitors": len(market.competitors),
        "sentiment_threads": len(sentiment.sources),
        "sentiment_problem_threads": sum(
            thread.classification in {"HAS_PROBLEM", "PAYS", "BUILT_WORKAROUND"}
            for thread in sentiment.sources
        ),
        "sentiment_paying_threads": sum(
            thread.classification == "PAYS" for thread in sentiment.sources
        ),
        "sentiment_workaround_threads": sum(
            thread.classification == "BUILT_WORKAROUND" for thread in sentiment.sources
        ),
        "feasibility_repos": len(feasibility.sources),
        "feasibility_complete_repos": sum(
            repo.relevance == "SOLVES_ENTIRELY" for repo in feasibility.sources
        ),
        "feasibility_commercial_repos": sum(
            repo.license_permits_commercial for repo in feasibility.sources
        ),
        "branches_ok": sum(
            findings.tool_status == "ok" for findings in (market, sentiment, feasibility)
        ),
    }


def token_overlap(actual: str, expected: str) -> float:
    """Return symmetric unique-token overlap in the closed interval 0..1."""
    actual_tokens = set(_TOKEN_RE.findall(actual.casefold()))
    expected_tokens = set(_TOKEN_RE.findall(expected.casefold()))
    if not actual_tokens and not expected_tokens:
        return 1.0
    if not actual_tokens or not expected_tokens:
        return 0.0
    return len(actual_tokens & expected_tokens) / max(len(actual_tokens), len(expected_tokens))


def anchor_problems(
    code: str,
    dimension: DimensionScore,
    anchors: Mapping[str, Mapping[int, str]] = RUBRIC_ANCHORS,
) -> list[str]:
    expected = anchors.get(code, {}).get(dimension.score)
    if dimension.score == 1:
        expected = expected or LEVEL_ONE_ANCHOR
        if " ".join(dimension.anchor_matched.split()).casefold() != " ".join(expected.split()).casefold():
            return [
                f"ANCHOR_{code}: score 1 must use the level-1 anchor verbatim: {expected!r}"
            ]
        return []

    if expected is None:
        return []

    overlap = token_overlap(dimension.anchor_matched, expected)
    if overlap < ANCHOR_MATCH_THRESHOLD:
        return [
            f"ANCHOR_{code}: score {dimension.score} matches {overlap:.0%} of its rubric anchor; "
            f"at least {ANCHOR_MATCH_THRESHOLD:.0%} is required"
        ]
    return []


def rubric_problems(
    verdict: Verdict,
    *,
    anchors: Mapping[str, Mapping[int, str]] = RUBRIC_ANCHORS,
    findings: tuple[MarketFindings, SentimentFindings, FeasibilityFindings] | None = None,
) -> list[str]:
    problems: list[str] = []
    for code, field_name in _DIMENSIONS:
        problems.extend(anchor_problems(code, getattr(verdict, field_name), anchors))

    if findings is None:
        return problems

    market, sentiment, feasibility = findings
    expected_counts = compute_evidence_counts(market, sentiment, feasibility)
    if verdict.evidence_counts != expected_counts:
        problems.append(
            "EVIDENCE_COUNTS: replace model-asserted counts with the recomputed values "
            f"{expected_counts!r}"
        )
    if verdict.branches_ok != expected_counts["branches_ok"]:
        problems.append(
            "BRANCH_COUNT: branches_ok must equal the number of branches with tool_status='ok'; "
            f"expected {expected_counts['branches_ok']}"
        )

    available_urls = set().union(*(findings_urls(item) for item in findings))
    scored_urls = set().union(
        *(getattr(verdict, field_name).evidence_urls for _, field_name in _DIMENSIONS)
    )
    fabricated = scored_urls - available_urls
    if fabricated:
        problems.append(
            "RUBRIC_URL_CLOSURE: remove evidence URLs absent from the branch findings: "
            + ", ".join(sorted(fabricated))
        )
    return problems


def report_mechanics_problems(
    report: ValidationReport,
    *,
    verdict: Verdict | None = None,
    allowed_urls: Iterable[str] | None = None,
) -> list[str]:
    problems: list[str] = []
    source_urls = {source.url for source in report.sources}
    body_urls = set(_URL_RE.findall(report.markdown_body))

    unlisted = body_urls - source_urls
    if unlisted:
        problems.append(
            "REPORT_URL_CLOSURE: remove body URLs absent from ValidationReport.sources: "
            + ", ".join(sorted(unlisted))
        )
    uncited = source_urls - body_urls
    if uncited:
        problems.append(
            "REPORT_SOURCES: cite every ValidationReport source in markdown_body: "
            + ", ".join(sorted(uncited))
        )
    if allowed_urls is not None:
        fabricated = source_urls - set(allowed_urls)
        if fabricated:
            problems.append(
                "REPORT_SOURCE_CLOSURE: remove sources absent from this run's tool results: "
                + ", ".join(sorted(fabricated))
            )

    nonempty_lines = [line.strip() for line in report.markdown_body.splitlines() if line.strip()]
    title = nonempty_lines[0] if nonempty_lines else ""
    summary = next((line for line in nonempty_lines[1:] if not line.startswith("#")), "")
    if not title.startswith("# "):
        problems.append("REPORT_TITLE: start markdown_body with one '# ' title line")

    provisional = verdict.provisional if verdict is not None else report.provisional
    if verdict is not None and report.provisional != verdict.provisional:
        problems.append(
            f"PROVISIONAL_FLAG: report.provisional must be {verdict.provisional!r} to match the verdict"
        )
    if provisional:
        if "provisional" not in title.casefold():
            problems.append("PROVISIONAL_TITLE: include 'Provisional' in the report title")
        if "provisional" not in summary.casefold():
            problems.append("PROVISIONAL_SUMMARY: include 'provisional' in the first summary line")

    if verdict is not None:
        expected_thin = [
            code
            for code, field_name in _DIMENSIONS
            if getattr(verdict, field_name).evidence_thin
        ]
        if report.thin_dimensions != expected_thin:
            problems.append(
                "THIN_DIMENSIONS: list exactly the dimensions with evidence_thin=true in D/M/C/F/X "
                f"order; expected {expected_thin!r}"
            )
        if verdict.confidence_band == "LOW":
            lowered = report.markdown_body.casefold()
            found = [phrase for phrase in _LOW_CONFIDENCE_CLAIMS if phrase in lowered]
            if found:
                problems.append(
                    "LOW_CONFIDENCE_CALIBRATION: remove certainty language at LOW confidence: "
                    + ", ".join(repr(phrase) for phrase in found)
                )
    return problems


def _guardrail_result(raw: str, problems: list[str]) -> GuardrailResult:
    if problems:
        return False, " | ".join(problems)
    return True, raw


def _parse_for_guardrail(raw: str, model: type[ModelT]) -> tuple[ModelT | None, str | None]:
    try:
        return parse_raw_model(raw, model), None
    except ValueError as exc:
        return None, f"SCHEMA: {exc}"


def check_scope(output: TaskOutputLike) -> GuardrailResult:
    raw = output.raw or ""
    scope, error = _parse_for_guardrail(raw, ScopedIdea)
    if error:
        return False, error
    assert scope is not None
    return _guardrail_result(raw, scope_problems(scope))


def check_findings(
    branch: BranchName,
    tool_urls: Iterable[str],
) -> Callable[[TaskOutputLike], GuardrailResult]:
    """Build a one-argument branch guardrail closed over this run's tool URLs."""
    model = _MODEL_BY_BRANCH[branch]
    allowed_urls = frozenset(tool_urls)

    def guardrail(output: TaskOutputLike) -> GuardrailResult:
        raw = output.raw or ""
        findings, error = _parse_for_guardrail(raw, model)
        if error:
            return False, error
        assert findings is not None
        return _guardrail_result(raw, findings_problems(findings, allowed_urls))

    return guardrail


def check_rubric(output: TaskOutputLike) -> GuardrailResult:
    raw = output.raw or ""
    verdict, error = _parse_for_guardrail(raw, Verdict)
    if error:
        return False, error
    assert verdict is not None
    return _guardrail_result(raw, rubric_problems(verdict))


def make_rubric_guardrail(
    market: MarketFindings,
    sentiment: SentimentFindings,
    feasibility: FeasibilityFindings,
    *,
    anchors: Mapping[str, Mapping[int, str]] = RUBRIC_ANCHORS,
) -> Callable[[TaskOutputLike], GuardrailResult]:
    findings = (market, sentiment, feasibility)

    def guardrail(output: TaskOutputLike) -> GuardrailResult:
        raw = output.raw or ""
        verdict, error = _parse_for_guardrail(raw, Verdict)
        if error:
            return False, error
        assert verdict is not None
        return _guardrail_result(raw, rubric_problems(verdict, anchors=anchors, findings=findings))

    return guardrail


def check_report_mechanics(output: TaskOutputLike) -> GuardrailResult:
    raw = output.raw or ""
    report, error = _parse_for_guardrail(raw, ValidationReport)
    if error:
        return False, error
    assert report is not None
    return _guardrail_result(raw, report_mechanics_problems(report))


def make_report_guardrail(
    verdict: Verdict,
    tool_urls: Iterable[str],
) -> Callable[[TaskOutputLike], GuardrailResult]:
    allowed_urls = frozenset(tool_urls)

    def guardrail(output: TaskOutputLike) -> GuardrailResult:
        raw = output.raw or ""
        report, error = _parse_for_guardrail(raw, ValidationReport)
        if error:
            return False, error
        assert report is not None
        return _guardrail_result(
            raw,
            report_mechanics_problems(report, verdict=verdict, allowed_urls=allowed_urls),
        )

    return guardrail


CITATION_GUARDRAIL = """\
Reject the validation report unless BOTH rules hold:
  1. ATTRIBUTION - every factual, numeric, competitor, thread, repository and
     named-entity claim in markdown_body is attributable to a URL in the
     report's own sources list.
  2. FAITHFULNESS - markdown_body contains no fact, number, example or conclusion
     absent from the scoped idea, branch findings and deterministic verdict it
     was given.
On rejection, name the failed rule and quote the exact unsupported sentence.
Do not rewrite the report and do not judge style or persuasiveness. An honest
statement that evidence is thin is a PASS."""


__all__ = [
    "ANCHOR_MATCH_THRESHOLD",
    "CITATION_GUARDRAIL",
    "DEMAND_ANCHORS",
    "LEVEL_ONE_ANCHOR",
    "RUBRIC_ANCHORS",
    "anchor_problems",
    "check_findings",
    "check_report_mechanics",
    "check_rubric",
    "check_scope",
    "compute_evidence_counts",
    "findings_problems",
    "findings_urls",
    "make_report_guardrail",
    "make_rubric_guardrail",
    "parse_raw_model",
    "report_mechanics_problems",
    "rubric_problems",
    "scope_problems",
    "token_overlap",
]