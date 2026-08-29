"""Pydantic contracts and deterministic scoring for the validator domain."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ToolStatus = Literal["ok", "empty", "rate_limited", "failed"]
ThreadClassification = Literal[
    "HAS_PROBLEM",
    "PAYS",
    "BUILT_WORKAROUND",
    "OPINION",
    "OFF_TOPIC",
]
RepoRelevance = Literal["SOLVES_ENTIRELY", "PARTIAL", "IRRELEVANT"]
VerdictLabel = Literal["VALIDATE", "NEEDS_WORK", "REJECT"]
ConfidenceBand = Literal["HIGH", "MODERATE", "LOW"]
DimensionCode = Literal["D", "M", "C", "F", "X"]
DecisionReason = Literal[
    "INSUFFICIENT_EVIDENCE",
    "FLOOR_NO_DEMAND",
    "FLOOR_ALREADY_FREE",
    "FLOOR_NO_MARKET",
    "FLOOR_NOT_BUILDABLE",
]


class ValidatorModel(BaseModel):
    """Closed, immutable base contract for model-produced validator data."""

    model_config = ConfigDict(
        allow_inf_nan=False,
        extra="forbid",
        frozen=True,
        strict=True,
        str_strip_whitespace=True,
    )


def _validate_url(value: str, field_name: str = "URL") -> str:
    if not value:
        raise ValueError(f"{field_name} is empty; provide the exact source URL returned by the tool")
    if any(character.isspace() for character in value):
        raise ValueError(f"{field_name} contains whitespace; copy the exact source URL returned by the tool")

    try:
        parsed = urlsplit(value)
        parsed.port
    except ValueError as exc:
        raise ValueError(f"{field_name} is malformed; provide a valid http:// or https:// URL") from exc

    if parsed.scheme not in {"http", "https"}:
        raise ValueError(f"{field_name} must start with http:// or https://")
    if not parsed.hostname:
        raise ValueError(f"{field_name} has no hostname; provide the complete source URL")
    if parsed.username or parsed.password:
        raise ValueError(f"{field_name} must not contain embedded credentials")
    return value


def _validate_urls(values: list[str], field_name: str) -> list[str]:
    validated = [_validate_url(value, f"{field_name}[{index}]") for index, value in enumerate(values)]
    if len(validated) != len(set(validated)):
        raise ValueError(f"{field_name} contains duplicate URLs; include each source URL once")
    return validated


def _validate_iso8601(value: str, field_name: str) -> str:
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(
            f"{field_name} must be an ISO 8601 date or timestamp, for example 2026-08-29 or "
            "2026-08-29T06:20:13Z"
        ) from exc
    return value


class Evidence(ValidatorModel):
    claim: str = Field(min_length=1)
    url: str
    publisher: str = Field(min_length=1)
    dated: str
    retrieved_via: Literal["firecrawl", "hn_algolia", "github", "cached"]

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        return _validate_url(value, "Evidence.url")

    @field_validator("dated")
    @classmethod
    def validate_dated(cls, value: str) -> str:
        return _validate_iso8601(value, "Evidence.dated")


class Competitor(ValidatorModel):
    name: str = Field(min_length=1)
    pricing: str = Field(min_length=1)
    vendor_owned: bool
    url: str | None = None

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str | None) -> str | None:
        return None if value is None else _validate_url(value, "Competitor.url")


class Thread(ValidatorModel):
    classification: ThreadClassification
    quote: str = Field(min_length=1)
    url: str
    date: str

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        return _validate_url(value, "Thread.url")

    @field_validator("date")
    @classmethod
    def validate_date(cls, value: str) -> str:
        return _validate_iso8601(value, "Thread.date")


class Repo(ValidatorModel):
    name: str = Field(min_length=1)
    license_permits_commercial: bool
    months_since_push: int = Field(ge=0)
    relevance: RepoRelevance
    url: str

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        return _validate_url(value, "Repo.url")


class DimensionScore(ValidatorModel):
    score: int = Field(ge=0, le=5)
    anchor_matched: str = Field(min_length=1)
    evidence_urls: list[str]
    evidence_thin: bool = False

    @field_validator("evidence_urls")
    @classmethod
    def validate_evidence_urls(cls, values: list[str]) -> list[str]:
        return _validate_urls(values, "DimensionScore.evidence_urls")

    @model_validator(mode="after")
    def compute_evidence_thin(self) -> DimensionScore:
        object.__setattr__(self, "evidence_thin", len(self.evidence_urls) < 3)
        return self


class ScopedIdea(ValidatorModel):
    startup_idea: str = Field(min_length=1)
    category: str = Field(min_length=1)
    target_user: str = Field(min_length=1)
    problem: str = Field(min_length=1)
    technology_claim: str = Field(min_length=1)
    market_query: str = Field(min_length=1)
    community_queries: list[str] = Field(min_length=1)
    tech_queries: list[str] = Field(min_length=1)
    assumptions: list[str] = Field(min_length=3, max_length=5)
    scoping_gaps: list[str] = Field(min_length=1)
    as_of: str

    @field_validator("community_queries", "tech_queries", "assumptions", "scoping_gaps")
    @classmethod
    def validate_nonempty_items(cls, values: list[str]) -> list[str]:
        if any(not value.strip() for value in values):
            raise ValueError("list entries must be non-empty strings; replace or remove each blank entry")
        return values

    @field_validator("as_of")
    @classmethod
    def validate_as_of(cls, value: str) -> str:
        return _validate_iso8601(value, "ScopedIdea.as_of")


class MarketFindings(ValidatorModel):
    sources: list[Evidence]
    source_urls: list[str]
    gaps: list[str]
    tool_status: ToolStatus
    competitors: list[Competitor]

    @field_validator("source_urls")
    @classmethod
    def validate_source_urls(cls, values: list[str]) -> list[str]:
        return _validate_urls(values, "MarketFindings.source_urls")

    @model_validator(mode="after")
    def validate_source_url_mirror(self) -> MarketFindings:
        expected = [source.url for source in self.sources]
        if self.source_urls != expected:
            raise ValueError(
                "MarketFindings.source_urls must exactly match sources[].url in the same order; "
                f"expected {expected!r}"
            )
        return self


class SentimentFindings(ValidatorModel):
    sources: list[Thread]
    source_urls: list[str]
    gaps: list[str]
    tool_status: ToolStatus

    @field_validator("source_urls")
    @classmethod
    def validate_source_urls(cls, values: list[str]) -> list[str]:
        return _validate_urls(values, "SentimentFindings.source_urls")

    @model_validator(mode="after")
    def validate_source_url_mirror(self) -> SentimentFindings:
        expected = [source.url for source in self.sources]
        if self.source_urls != expected:
            raise ValueError(
                "SentimentFindings.source_urls must exactly match sources[].url in the same order; "
                f"expected {expected!r}"
            )
        return self


class FeasibilityFindings(ValidatorModel):
    sources: list[Repo]
    source_urls: list[str]
    gaps: list[str]
    tool_status: ToolStatus

    @field_validator("source_urls")
    @classmethod
    def validate_source_urls(cls, values: list[str]) -> list[str]:
        return _validate_urls(values, "FeasibilityFindings.source_urls")

    @model_validator(mode="after")
    def validate_source_url_mirror(self) -> FeasibilityFindings:
        expected = [source.url for source in self.sources]
        if self.source_urls != expected:
            raise ValueError(
                "FeasibilityFindings.source_urls must exactly match sources[].url in the same order; "
                f"expected {expected!r}"
            )
        return self


class Verdict(ValidatorModel):
    demand: DimensionScore
    market: DimensionScore
    competitive_room: DimensionScore
    feasibility: DimensionScore
    headroom_over_free: DimensionScore
    evidence_counts: dict[str, int]
    market_coverage: float = Field(ge=0.0, le=1.0)
    sentiment_coverage: float = Field(ge=0.0, le=1.0)
    feasibility_coverage: float = Field(ge=0.0, le=1.0)
    median_market_source_age_months: float | None = Field(default=None, ge=0.0)
    branches_ok: int = Field(ge=0, le=3)
    cheapest_next_test: str = Field(min_length=1)
    kill_criteria: list[str] = Field(default_factory=list)
    composite_score: float = 0.0
    verdict: VerdictLabel = "NEEDS_WORK"
    decision_reason: DecisionReason | None = None
    confidence: float = 0.0
    confidence_band: ConfidenceBand = "LOW"
    provisional: bool = False

    @field_validator("evidence_counts")
    @classmethod
    def validate_evidence_counts(cls, values: dict[str, int]) -> dict[str, int]:
        invalid = [key for key, value in values.items() if isinstance(value, bool) or value < 0]
        if invalid:
            raise ValueError(
                "Verdict.evidence_counts values must be non-negative integers; fix keys "
                + ", ".join(sorted(invalid))
            )
        return values

    @model_validator(mode="after")
    def compute_mechanical_result(self) -> Verdict:
        scores = (
            self.demand.score,
            self.market.score,
            self.competitive_room.score,
            self.feasibility.score,
            self.headroom_over_free.score,
        )
        demand, market, competitive, feasibility, headroom = scores
        composite = round(
            2
            * (
                0.30 * demand
                + 0.20 * market
                + 0.20 * competitive
                + 0.15 * feasibility
                + 0.15 * headroom
            ),
            1,
        )

        age_months = self.median_market_source_age_months
        if age_months is not None and age_months <= 12:
            staleness = 1.00
        elif age_months is not None and age_months <= 24:
            staleness = 0.85
        else:
            staleness = 0.70

        coverage = (
            0.40 * self.market_coverage
            + 0.35 * self.sentiment_coverage
            + 0.25 * self.feasibility_coverage
        )
        branch_penalty = 0.60 if self.branches_ok < 3 else 1.00
        confidence = round(coverage * staleness * branch_penalty, 2)

        floors: list[str] = []
        if demand == 0:
            floors.append("FLOOR_NO_DEMAND")
        if headroom == 0:
            floors.append("FLOOR_ALREADY_FREE")
        if market == 0 and demand <= 2:
            floors.append("FLOOR_NO_MARKET")
        if feasibility == 0:
            floors.append("FLOOR_NOT_BUILDABLE")

        label: VerdictLabel
        reason: DecisionReason | None
        if confidence < 0.35:
            label, reason = "NEEDS_WORK", "INSUFFICIENT_EVIDENCE"
        elif demand == 0:
            label, reason = "REJECT", "FLOOR_NO_DEMAND"
        elif headroom == 0:
            label, reason = "REJECT", "FLOOR_ALREADY_FREE"
        elif market == 0 and demand <= 2:
            label, reason = "REJECT", "FLOOR_NO_MARKET"
        elif feasibility == 0:
            label, reason = "NEEDS_WORK", "FLOOR_NOT_BUILDABLE"
        elif composite >= 7.0 and min(scores) >= 3 and confidence >= 0.60:
            label, reason = "VALIDATE", None
        elif composite < 4.0:
            label, reason = "REJECT", None
        else:
            label, reason = "NEEDS_WORK", None

        if confidence >= 0.70:
            band: ConfidenceBand = "HIGH"
        elif confidence >= 0.35:
            band = "MODERATE"
        else:
            band = "LOW"

        object.__setattr__(self, "composite_score", composite)
        object.__setattr__(self, "confidence", confidence)
        object.__setattr__(self, "confidence_band", band)
        object.__setattr__(self, "verdict", label)
        object.__setattr__(self, "decision_reason", reason)
        object.__setattr__(self, "kill_criteria", floors)
        object.__setattr__(
            self,
            "provisional",
            label == "REJECT" and 0.35 <= confidence < 0.60,
        )
        return self


class ValidationReport(ValidatorModel):
    markdown_body: str = Field(min_length=1)
    provisional: bool
    thin_dimensions: list[DimensionCode]
    sources: list[Evidence]

    @model_validator(mode="after")
    def validate_unique_sources(self) -> ValidationReport:
        urls = [source.url for source in self.sources]
        if len(urls) != len(set(urls)):
            raise ValueError("ValidationReport.sources contains duplicate URLs; include each source once")
        if len(self.thin_dimensions) != len(set(self.thin_dimensions)):
            raise ValueError("ValidationReport.thin_dimensions contains duplicates")
        return self