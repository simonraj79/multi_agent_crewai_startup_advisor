"""Pydantic contracts and deterministic scoring for the validator domain."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from brief_crew.config import (
    VALIDATOR_MAX_BRANCH_QUERIES,
    VALIDATOR_MAX_EVIDENCE_CLAIM_CHARS,
)

ToolStatus = Literal["ok", "empty", "rate_limited", "failed"]
FloorCode = Literal[
    "FLOOR_NO_DEMAND",
    "FLOOR_ALREADY_FREE",
    "FLOOR_NO_MARKET",
    "FLOOR_NOT_BUILDABLE",
]
ThreadClassification = Literal[
    "HAS_PROBLEM",
    "PAYS",
    "BUILT_WORKAROUND",
    "OPINION",
    "OFF_TOPIC",
]
RepoRelevance = Literal["SOLVES_ENTIRELY", "PARTIAL", "IRRELEVANT"]
# How much of the scoped core job a competitor gives away at no cost. It is
# deliberately NOT `RepoRelevance`: that vocabulary collapses "covers most of
# the job" and "covers a separable part" into one PARTIAL, and the X ladder
# turns on exactly that distinction - the first blocks VALIDATE, the second
# does not. Reusing it would have reopened the dead band it exists to close.
FreeCoreCoverage = Literal["WHOLE_JOB", "MOST_OF_JOB", "SEPARABLE_PART", "NONE"]
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


def staleness_multiplier(median_source_age_months: float | None) -> float:
    """The PRD §10.3 staleness band for a median market-source age.

    Exported so the guardrail that recomputes `median_market_source_age_months`
    can check the model's figure against the only thing confidence actually
    consumes it for, instead of duplicating the two boundaries.
    """
    if median_source_age_months is not None and median_source_age_months <= 12:
        return 1.00
    if median_source_age_months is not None and median_source_age_months <= 24:
        return 0.85
    return 0.70


class Evidence(ValidatorModel):
    # Bounded above because claim text is the single most expensive thing this
    # pipeline generates: it is billed six times per run - twice as COMPLETION
    # tokens, once of those at escalation tier - and read by no guardrail at
    # all. `MAX_CLAIM_CHARS` bounds what the TOOL emits; this bounds what the
    # MODEL emits, which is the half that actually costs time.
    claim: str = Field(min_length=1, max_length=VALIDATOR_MAX_EVIDENCE_CLAIM_CHARS)
    url: str
    publisher: str = Field(min_length=1)
    dated: str = Field(
        description=(
            "The source's own publication date when it reports one; otherwise the "
            "retrieval timestamp, which must be accompanied by "
            "dated_is_retrieval_time=true."
        )
    )
    # F12. The market tool falls back to the retrieval timestamp when Firecrawl
    # reports no publication date, so `dated` alone cannot distinguish a page
    # published today from a page of unknown age. Confidence consumes market
    # source age only through `staleness_multiplier`, so an unflagged fallback
    # scores as maximally fresh - the system is most confident exactly where it
    # knows least about recency. Copy the tool row's flag; it is what keeps
    # undated material from being served as current.
    dated_is_retrieval_time: bool = Field(
        default=False,
        description=(
            "True when `dated` is the retrieval time because the source published "
            "no date. Copy the value from the tool row; never set it to false for "
            "a row the tool flagged true."
        ),
    )
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
    # RATIFICATION C5 (2026-09-01): TRI-STATE, like `Repo.archived`,
    # `Thread.points` and `Evidence.dated_is_retrieval_time`. It was the sole
    # two-state flag on this model carrying a three-state question.
    #
    # Measured: three competitors whose ownership no source establishes became
    # three `False`s, `vendor_owned == 0`, and the C ceiling was 5 - so the top
    # of the competitive ladder was awarded for an ABSENCE of evidence. A
    # two-state flag forces a guess, and the guess defaulted to the flattering
    # answer.
    vendor_owned: bool | None = Field(
        default=None,
        description=(
            "True when a source shows this competitor is delivered as part of a "
            "larger platform vendor's product or subscription; false when a "
            "source shows it is sold and bought on its own. Leave it null "
            "when no source settles the question; null is not False."
        ),
    )
    url: str | None = None
    # The X floor used to be blind to the commonest free substitute there is.
    # `FLOOR_ALREADY_FREE` counts repositories marked SOLVES_ENTIRELY, so a
    # free PRODUCT that already does the whole job - Google Calendar, Notion,
    # somebody's free tier - could not reach X=0 whatever the market branch
    # found, because nothing on this model could say so. `pricing` is free
    # text ("not published", "$12/seat", "free"), and a floor cannot be read
    # off prose. One enum answers the only question the ladder asks: how much
    # of the scoped core job does this competitor give away?
    #
    # `None` is "the market branch did not establish this", exactly as with
    # `Repo.archived` and `Thread.points`, and it is NOT "NONE". "NONE" is a
    # claim - an attributed source shows nothing here is free - and X=4 and
    # X=5 rest on "no free product is named", which no unanswered question
    # should ever satisfy on its own. Defaulted rather than required so an
    # unanswered question stays representable; `market_task` asks for it on
    # every competitor.
    free_core_coverage: FreeCoreCoverage | None = Field(
        default=None,
        description=(
            "How much of the scoped core job this competitor covers at no cost: "
            "WHOLE_JOB, MOST_OF_JOB, SEPARABLE_PART, or NONE when an attributed "
            "source shows nothing is free. Leave it null when no source settles "
            "the question; null is not NONE."
        ),
    )

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str | None) -> str | None:
        return None if value is None else _validate_url(value, "Competitor.url")


class Thread(ValidatorModel):
    classification: ThreadClassification
    quote: str = Field(min_length=1)
    url: str
    date: str = Field(
        description=(
            "The comment's own date when Algolia reports one; otherwise the "
            "retrieval timestamp, which must be accompanied by "
            "date_is_retrieval_time=true."
        )
    )
    # F16, and the exact twin of `Evidence.dated_is_retrieval_time`. The HN
    # tool falls back to the retrieval timestamp for an item Algolia dates
    # neither way, so `date` alone cannot separate a thread posted this week
    # from a thread of unknown age. This one does not touch confidence - only
    # market sources feed staleness - it touches something heavier: the Demand
    # ladder, weight 0.30, turns on "dated within 24 months", and a thread
    # dated today is always within 24 months. Undated threads could therefore
    # carry D's top anchors on evidence of no known age.
    date_is_retrieval_time: bool = Field(
        default=False,
        description=(
            "True when `date` is the retrieval time because the source carried "
            "no date of its own. Copy the value from the tool row. A thread "
            "flagged true is never 'dated within 24 months'."
        ),
    )
    # F06. A missing count must stay distinguishable from a genuine zero, so
    # neither defaults to 0. Never a demand signal on its own (see the Demand
    # ladder, which uses neither on purpose) - they exist so a reader can weigh
    # how public a quoted thread was.
    points: int | None = Field(default=None, ge=0)
    num_comments: int | None = Field(default=None, ge=0)

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
    # F16. Required but nullable, not optional: the model must always answer,
    # and `None` is the honest answer when GitHub reported no `pushed_at`. It
    # was `int` with `ge=0` while the tool emitted -1 for unknown activity and
    # said so in its own notes, so an honest copy failed validation and the
    # only ways through were to drop the repository or invent an age. Every
    # ladder clause that reads this field ("pushed within 12 months") treats
    # `None` as not satisfied: unknown activity is not recent activity.
    months_since_push: Annotated[int, Field(ge=0)] | None
    relevance: RepoRelevance
    url: str
    # F07. PRD §10.2 makes archived state load-bearing for the X floor: "a
    # maintained, permissively licensed, popular project that already does the
    # whole thing" is the X=0 kill, and an archived project is not maintained.
    # `None` means "not reported", which is not the same claim as `False`, so
    # X=0 asks for "not marked archived" (which a `None` satisfies) and never
    # lets an unreported flag kill an idea.
    archived: bool | None = None

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
    # Bounded above as well as below: each keyword branch now calls its tool
    # once, so a second query would be written, shown at the gate, and then
    # silently never run. The prompt says "exactly one" - but prompts are
    # advisory and drift, and a schema bound does not.
    community_queries: list[str] = Field(
        min_length=1, max_length=VALIDATOR_MAX_BRANCH_QUERIES
    )
    tech_queries: list[str] = Field(
        min_length=1, max_length=VALIDATOR_MAX_BRANCH_QUERIES
    )
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
    # F05. The Demand ladder's top anchor requires that "the market branch
    # independently names a paying segment", and the Market question is "is
    # there money, and can you name whose?" - neither was expressible before.
    # Empty is the honest default: no segment was established.
    paying_segments: list[str] = Field(default_factory=list)

    @field_validator("paying_segments")
    @classmethod
    def validate_paying_segments(cls, values: list[str]) -> list[str]:
        if any(not value.strip() for value in values):
            raise ValueError(
                "MarketFindings.paying_segments entries must be non-empty; name the segment "
                "or omit it"
            )
        if len(values) != len({value.casefold() for value in values}):
            raise ValueError("MarketFindings.paying_segments contains duplicates; name each once")
        return values

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
        # Checked BEFORE the mirror comparison, because the mirror's own error
        # used to hand back a repair instruction that could not be satisfied.
        #
        # Measured on a live run: the model returned 5 Threads from 3 stories
        # with `source_urls` deduplicated to 3. The mirror failed and its
        # message said `expected [<5 urls, two pairs identical>]`. The model did
        # exactly as told - and `_validate_urls` then rejected the duplicates.
        # Two attempts, both "wrong", the second one obedient. The branch was
        # abandoned and a weight-0.30 dimension collapsed to "evidence does not
        # reach this question".
        #
        # So the duplicate is named FIRST, with the rule rather than a list to
        # copy. `sources` is the side that must change, and this says so.
        duplicates = [url for url in set(expected) if expected.count(url) > 1]
        if duplicates:
            raise ValueError(
                "SentimentFindings.sources must hold at most one Thread per URL - "
                "several comments from one discussion are one thread of evidence, "
                f"not several; {duplicates[0]} appears {expected.count(duplicates[0])} "
                "times. Keep the single most representative comment per URL."
            )
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
    # JUDGEMENT, kept. The model's answer to "what would falsify this idea?" is
    # qualitative and unreproducible by arithmetic, so overwriting it destroys
    # the only thing the Synthesist can say here that a formula cannot. It is
    # validated for shape and left alone (F09).
    kill_criteria: list[str] = Field(default_factory=list)
    # ARITHMETIC, overwritten. The fatal dimensions follow from the five
    # integers alone, so they are recomputed on every validation and any
    # model-supplied value is discarded (PRD §10.2).
    fatal_floors: list[FloorCode] = Field(default_factory=list)
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

    @field_validator("fatal_floors", mode="before")
    @classmethod
    def discard_supplied_floors(cls, _values: object) -> list[str]:
        """Drop whatever the model sent before it can fail validation.

        PRD §10.1: overwriting rather than validating is deliberate - a model
        that miscomputes should produce a correct verdict, not a failed run.
        `compute_mechanical_result` fills this field from the five scores.
        """
        return []

    @field_validator("kill_criteria")
    @classmethod
    def validate_kill_criteria(cls, values: list[str]) -> list[str]:
        """Shape only. The content is the model's judgement and is preserved."""
        if any(not value.strip() for value in values):
            raise ValueError(
                "Verdict.kill_criteria entries must be non-empty; state each falsifying "
                "observation or omit it"
            )
        seen = {value.strip().casefold() for value in values}
        if len(seen) != len(values):
            raise ValueError("Verdict.kill_criteria contains duplicates; state each criterion once")
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

        staleness = staleness_multiplier(self.median_market_source_age_months)

        coverage = (
            0.40 * self.market_coverage
            + 0.35 * self.sentiment_coverage
            + 0.25 * self.feasibility_coverage
        )
        branch_penalty = 0.60 if self.branches_ok < 3 else 1.00
        confidence = round(coverage * staleness * branch_penalty, 2)

        floors: list[FloorCode] = []
        if demand == 0:
            floors.append("FLOOR_NO_DEMAND")
        if headroom == 0:
            floors.append("FLOOR_ALREADY_FREE")
        if market == 0 and demand <= 2:
            floors.append("FLOOR_NO_MARKET")
        # RATIFICATION C4 (2026-09-01): FLOOR_NOT_BUILDABLE is RETIRED and F
        # has no level 0. It was compulsory at `relevant == 0`, that state is
        # the modal outcome for an ordinary v1, and the branch was
        # NON-MONOTONE - F=0 produced NEEDS_WORK/3.4 where the strictly better
        # F=1 produced REJECT/3.7, because this `elif` sat above the
        # `composite < 4.0` test. The code stays in `FloorCode` so rows already
        # written still parse.

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
        object.__setattr__(self, "fatal_floors", floors)
        # PRD §10.3 makes a REJECT between 0.35 and 0.60 provisional: "the
        # difference between we looked and found nothing and there is
        # nothing". Read literally that rule is non-monotonic in the one
        # quantity it keys on - a REJECT at 0.36 is labelled provisional and
        # the LOWEST-confidence verdicts the system can produce, the ones the
        # override below 0.35 relabels NEEDS_WORK / INSUFFICIENT_EVIDENCE, are
        # not. The first real paid run landed there: composite 4.2 at
        # confidence 0.17, two of three branches empty, two dimensions scored
        # 1 for "we did not reach the question", and `provisional` false. The
        # flag exists to make the report say out loud that the verdict is not
        # final, and that is needed strictly more at 0.17 than at 0.50, so the
        # PRD's rule is kept and widened rather than replaced: provisional now
        # means "this run's confidence cannot support a final answer", of
        # which the PRD's clause is the REJECT case.
        object.__setattr__(
            self,
            "provisional",
            (label == "REJECT" and 0.35 <= confidence < 0.60)
            or reason == "INSUFFICIENT_EVIDENCE",
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