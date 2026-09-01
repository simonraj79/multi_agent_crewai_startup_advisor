"""Zero-cost guardrails for validator task outputs.

The one-argument ``check_*`` functions match CrewAI's callable guardrail
contract. Factories add run-scoped evidence when a check needs tool results or
upstream findings, while the ``*_problems`` helpers remain framework-free.

Every threshold and every line of rubric text lives in ``brief_crew.config``:
the Synthesist prompt in ``crews/validator_crew/config/tasks.yaml`` quotes the
same anchors, and a constant with two copies is a constant that drifts.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import datetime, timezone
from typing import Any, Literal, NamedTuple, Protocol, TypeVar

from pydantic import BaseModel, ValidationError

from brief_crew.config import (
    ANCHOR_MATCH_THRESHOLD,
    COMPETITIVE_ROOM_ANCHORS,
    DEMAND_ANCHORS,
    FEASIBILITY_ANCHORS,
    HEADROOM_ANCHORS,
    LEVEL_ONE_ANCHOR,
    MARKET_ANCHORS,
    RUBRIC_ANCHORS,
    RUBRIC_FLOOR_MIN_MARKET_SOURCES,
    RUBRIC_FLOOR_MIN_USABLE_THREADS,
    RUBRIC_RECENCY_GRACE_MONTHS,
    RUBRIC_RECENCY_MONTHS,
    RUBRIC_REUSABLE_MAX_PUSH_MONTHS,
    VALIDATOR_COVERAGE_TARGET_SOURCES,
    VALIDATOR_DAYS_PER_MONTH,
)
from brief_crew.schemas import (
    DimensionScore,
    Evidence,
    FeasibilityFindings,
    MarketFindings,
    Repo,
    ScopedIdea,
    SentimentFindings,
    Thread,
    ValidationReport,
    Verdict,
    staleness_multiplier,
)

BranchName = Literal["market", "sentiment", "feasibility"]
Findings = MarketFindings | SentimentFindings | FeasibilityFindings
GuardrailResult = tuple[bool, str]

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
_PROBLEM_CLASSIFICATIONS = frozenset({"HAS_PROBLEM", "PAYS", "BUILT_WORKAROUND"})
_ACTED_CLASSIFICATIONS = frozenset({"PAYS", "BUILT_WORKAROUND"})
_RELEVANT_RELEVANCE = frozenset({"SOLVES_ENTIRELY", "PARTIAL"})
# A dimension whose branch returned nothing the ladder can score above the
# reserved level 1. Not 0: level 0 is a fatal floor with its own anchor and its
# own precondition, so "no level is reachable" and "the floor fired" must stay
# different answers.
NO_LEVEL_ABOVE_ONE = 1
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
        if isinstance(findings, MarketFindings) and findings.paying_segments:
            problems.append(
                f"STATUS_HONESTY: tool_status is {findings.tool_status!r}, so paying_segments "
                "must be empty"
            )
        if not findings.gaps:
            problems.append(
                f"STATUS_HONESTY: tool_status is {findings.tool_status!r}; add a gap explaining "
                "what evidence could not be obtained"
            )
    return problems


def is_reusable_repository(repo: Repo) -> bool:
    """The Feasibility ladder's "reusable repository" - a component to build WITH.

    Unknown activity is not recent activity: a `months_since_push` of `None`
    means GitHub reported no `pushed_at`, and "pushed within 12 months" is a
    claim nobody can make about it.
    """
    return (
        repo.relevance in _RELEVANT_RELEVANCE
        and repo.license_permits_commercial
        and repo.months_since_push is not None
        and repo.months_since_push <= RUBRIC_REUSABLE_MAX_PUSH_MONTHS
    )


def is_live_free_substitute(repo: Repo) -> bool:
    """The X=0 kill, exactly: a free substitute that is alive and usable.

    A "free substitute" is a repository marked SOLVES_ENTIRELY - it covers the
    whole core job on its own. This adds the three conditions X=0 states, and
    `archived is not True` is deliberate rather than `archived is False`: the
    flag is tri-state, and an unreported flag must score exactly as it did
    before the field existed rather than letting a possibly-dead project kill
    an idea.
    """
    return (
        repo.relevance == "SOLVES_ENTIRELY"
        and repo.archived is not True
        and repo.license_permits_commercial
        and repo.months_since_push is not None
        and repo.months_since_push <= RUBRIC_REUSABLE_MAX_PUSH_MONTHS
    )


def compute_evidence_counts(
    market: MarketFindings,
    sentiment: SentimentFindings,
    feasibility: FeasibilityFindings,
) -> dict[str, int]:
    """Recompute all synthesis counts from branch lists, never model claims.

    Every counter here is a pure function of the branch lists and carries no
    date, because `Verdict.evidence_counts` is enforced by exact equality and
    the model has to be able to reproduce it. Recency-dependent quantities live
    in `score_support_problems`, which owns its own tolerance.
    """
    return {
        "market_sources": len(market.sources),
        "market_competitors": len(market.competitors),
        "sentiment_threads": len(sentiment.sources),
        # F16. The D=0/D=1 boundary is "the branch reached the question and
        # found nobody with this problem" versus "the branch found nothing" -
        # and D=0 is a REJECT floor. Nothing could recompute it without a count
        # of the threads that were on topic at all.
        "sentiment_usable_threads": sum(
            thread.classification != "OFF_TOPIC" for thread in sentiment.sources
        ),
        "sentiment_problem_threads": sum(
            thread.classification in _PROBLEM_CLASSIFICATIONS for thread in sentiment.sources
        ),
        "sentiment_paying_threads": sum(
            thread.classification == "PAYS" for thread in sentiment.sources
        ),
        "sentiment_workaround_threads": sum(
            thread.classification == "BUILT_WORKAROUND" for thread in sentiment.sources
        ),
        "feasibility_repos": len(feasibility.sources),
        "feasibility_relevant_repos": sum(
            repo.relevance in _RELEVANT_RELEVANCE for repo in feasibility.sources
        ),
        "feasibility_complete_repos": sum(
            repo.relevance == "SOLVES_ENTIRELY" for repo in feasibility.sources
        ),
        "feasibility_commercial_repos": sum(
            repo.license_permits_commercial for repo in feasibility.sources
        ),
        # F16. F=3/4/5 count reusable repositories and X=0/2 turn on whether a
        # free substitute is live; neither was recomputable before.
        "feasibility_reusable_repos": sum(
            is_reusable_repository(repo) for repo in feasibility.sources
        ),
        "feasibility_live_substitutes": sum(
            is_live_free_substitute(repo) for repo in feasibility.sources
        ),
        "market_paying_segments": len(market.paying_segments),
        "branches_ok": sum(
            findings.tool_status == "ok" for findings in (market, sentiment, feasibility)
        ),
    }


def _age_months(dated: str, now: datetime) -> float | None:
    """Age of an ISO 8601 date in months, or ``None`` when it is unusable."""
    normalized = dated[:-1] + "+00:00" if dated.endswith("Z") else dated
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    elapsed_days = (now - parsed.astimezone(timezone.utc)).total_seconds() / 86400.0
    return max(0.0, elapsed_days) / VALIDATOR_DAYS_PER_MONTH


def _market_source_age_months(source: Evidence, now: datetime) -> float | None:
    """Age of one market source, or ``None`` when its recency is unknown.

    Two things make an age unknown, and they are the same claim: `dated` will
    not parse, or `dated` is the retrieval timestamp the tool substituted
    because the page published no date. Neither is evidence of freshness.
    """
    if source.dated_is_retrieval_time:
        return None
    return _age_months(source.dated, now)


def median_market_source_age_months(
    sources: Sequence[Evidence],
    now: datetime,
) -> float | None:
    """Median market-source age, with unknown-age sources held at the stale end.

    Confidence consumes this figure only through `staleness_multiplier`, whose
    unknown case - ``None`` - is already the worst band. So sources of unknown
    recency keep the oldest positions in the ordering instead of being dropped
    from it: the result is a real, published age whenever one sits in the
    middle, and ``None`` as soon as unknown recency reaches the middle. In one
    line, the figure is non-null exactly when strictly more than half of the
    market sources carry a usable publication date.

    The two alternatives were rejected for the same reason. Dropping undated
    sources from the median would leave one fresh page among nine unknowns at a
    1.00 multiplier while all ten still counted towards `market_coverage` -
    confidence highest where recency is least known. Substituting a sentinel age
    would report a month count nobody measured. This repository's rule is that
    undated material must never be served as current (`main._age_days` applies
    the same rule to the cache, where missing metadata is a miss, not a hit),
    and only withholding the number honours it without inventing one.
    """
    ages = [_market_source_age_months(source, now) for source in sources]
    known = sorted(age for age in ages if age is not None)
    if len(known) * 2 <= len(ages):
        return None

    middle = len(ages) // 2
    if len(ages) % 2:
        return round(known[middle], 1)
    return round((known[middle - 1] + known[middle]) / 2, 1)


def compute_confidence_inputs(
    market: MarketFindings,
    sentiment: SentimentFindings,
    feasibility: FeasibilityFindings,
    *,
    now: datetime | None = None,
) -> dict[str, float | int | None]:
    """Recompute every input the confidence formula consumes (PRD §10.3, F11).

    PRD §10.3 calls confidence "separate, mechanical, gating both directions".
    Mechanical means computed: an LLM-asserted coverage ratio is not a ratio,
    exactly as an LLM-asserted count is not a count. Every value here comes
    from the branch lists, so `Verdict` stays deterministic given inputs that
    are themselves derived rather than claimed.
    """
    reference = now or datetime.now(timezone.utc)
    counts = compute_evidence_counts(market, sentiment, feasibility)
    target = VALIDATOR_COVERAGE_TARGET_SOURCES

    return {
        "market_coverage": min(1.0, counts["market_sources"] / target),
        # RATIFICATION C6 (2026-09-01). Coverage measures how much the branch
        # RETRIEVED, never which way the finding came out.
        #
        # Counting PROBLEM threads made confidence a function of the answer's
        # direction: D=0 requires no problem thread, so this term was 0.0 BY
        # CONSTRUCTION exactly when the demand floor fired, and the confidence
        # attached to "nobody wants this" was computed entirely from the market
        # and feasibility branches - the two with nothing to say about demand.
        # Measured: 3 OPINION threads and 40 OPINION threads returned the
        # identical REJECT at confidence 0.65, because the branch that did the
        # looking contributed nothing either time.
        #
        # PRD §10.3 requires composite_score and confidence to measure
        # different things. This is the error F4 removed from the tools, one
        # layer up.
        "sentiment_coverage": min(1.0, counts["sentiment_usable_threads"] / target),
        "feasibility_coverage": min(1.0, counts["feasibility_relevant_repos"] / target),
        "branches_ok": counts["branches_ok"],
        "median_market_source_age_months": median_market_source_age_months(
            market.sources, reference
        ),
    }


def confidence_problems(
    verdict: Verdict,
    market: MarketFindings,
    sentiment: SentimentFindings,
    feasibility: FeasibilityFindings,
    *,
    now: datetime | None = None,
) -> list[str]:
    """Reject model-asserted confidence inputs that disagree with the evidence."""
    expected = compute_confidence_inputs(market, sentiment, feasibility, now=now)
    problems: list[str] = []

    for field_name in ("market_coverage", "sentiment_coverage", "feasibility_coverage"):
        actual = float(getattr(verdict, field_name))
        wanted = expected[field_name]
        assert wanted is not None
        if round(actual, 2) != round(float(wanted), 2):
            problems.append(
                f"COVERAGE_{field_name.split('_')[0].upper()}: set {field_name} to the recomputed "
                f"{float(wanted):.2f}, not {actual:.2f}"
            )

    actual_age = verdict.median_market_source_age_months
    wanted_age = expected["median_market_source_age_months"]
    if (actual_age is None) != (wanted_age is None):
        problems.append(
            "MEDIAN_SOURCE_AGE: set median_market_source_age_months to "
            f"{wanted_age!r}; it is null unless strictly more than half of the market "
            "sources carry a real publication date, and a retrieval-time fallback is "
            "not one"
        )
    elif staleness_multiplier(actual_age) != staleness_multiplier(wanted_age):
        # Only the staleness band is enforced: the model cannot reproduce a
        # float age to the hour, but it must not land in a kinder band than the
        # dated evidence supports.
        problems.append(
            "MEDIAN_SOURCE_AGE: the market sources give a recomputed median age of "
            f"{wanted_age} months, a different staleness band from the asserted {actual_age}"
        )
    return problems



def _within_recency_window(dated: str, is_retrieval_time: bool, now: datetime) -> bool:
    """Whether one source counts as "dated within 24 months" for the ladders.

    A retrieval-time fallback never does. That is the whole point of the two
    flags: a page or a thread carrying no date of its own is not evidence that
    anything happened recently, and a fallback date always sits inside any
    backward-looking window.
    """
    if is_retrieval_time:
        return False
    age = _age_months(dated, now)
    return age is not None and age <= RUBRIC_RECENCY_MONTHS + RUBRIC_RECENCY_GRACE_MONTHS


def _recent_threads(
    threads: Sequence[Thread],
    classifications: frozenset[str],
    now: datetime,
) -> int:
    return sum(
        thread.classification in classifications
        and _within_recency_window(thread.date, thread.date_is_retrieval_time, now)
        for thread in threads
    )


class DimensionSupport(NamedTuple):
    """What the counted evidence can carry on one dimension."""

    ceiling: int
    zero_ok: bool
    one_ok: bool
    forbidden: frozenset[int]
    summary: str


def rubric_support(
    market: MarketFindings,
    sentiment: SentimentFindings,
    feasibility: FeasibilityFindings,
    *,
    now: datetime | None = None,
) -> dict[str, DimensionSupport]:
    """Per dimension, the highest level the counted evidence can carry (F16).

    Only clauses that are fully countable contribute. Where an anchor adds a
    judgement clause on top - F=5's "together cover the separable parts of the
    scoped v1", X=4's "covers most of the core job", M=2's "names a buyer
    segment", C=3's "states an axis on which a named competitor is beatable" -
    the judgement half is dropped, which can only raise the ceiling. That is
    the safe direction: a ceiling that is too generous lets an honest score
    through, while one that is too tight fails an honest run, after which
    somebody deletes the guardrail.
    """
    reference = now or datetime.now(timezone.utc)
    counts = compute_evidence_counts(market, sentiment, feasibility)

    usable = counts["sentiment_usable_threads"]
    problems = counts["sentiment_problem_threads"]
    acted = counts["sentiment_paying_threads"] + counts["sentiment_workaround_threads"]
    segments = counts["market_paying_segments"]
    sources = counts["market_sources"]
    competitors = counts["market_competitors"]
    repos = counts["feasibility_repos"]
    relevant = counts["feasibility_relevant_repos"]
    complete = counts["feasibility_complete_repos"]
    reusable = counts["feasibility_reusable_repos"]
    live = counts["feasibility_live_substitutes"]
    partial = relevant - complete
    # RATIFICATION C5: `is True` / `is None`, never truthiness. An
    # unestablished ownership is not a negative finding, and counting it as one
    # awarded C=5 for evidence nobody gathered.
    vendor_true = sum(
        competitor.vendor_owned is True for competitor in market.competitors
    )
    vendor_unknown = sum(
        competitor.vendor_owned is None for competitor in market.competitors
    )
    # The X ladder's product half, counted here rather than in
    # `compute_evidence_counts` for the same reason `vendor_owned` is: that
    # dict is enforced against the Synthesist by exact equality, so every key
    # added to it is another number an honest run can be failed for
    # mistyping. A counter only the ceiling reads belongs to the ceiling.
    # `None` is counted nowhere on purpose - an unanswered question is not a
    # free product and is not evidence that none exists.
    free_whole = sum(
        competitor.free_core_coverage == "WHOLE_JOB" for competitor in market.competitors
    )
    free_most = sum(
        competitor.free_core_coverage == "MOST_OF_JOB" for competitor in market.competitors
    )
    free_part = sum(
        competitor.free_core_coverage == "SEPARABLE_PART" for competitor in market.competitors
    )
    free_named = free_whole + free_most + free_part
    # RATIFICATION C3 (2026-09-01). "Nothing is free" and "nobody asked" were
    # the same state to the ceiling, and the difference decides the TOP of this
    # ladder.
    #
    # `free_named` counts neither `None` nor `"NONE"`, so the ceiling read the
    # ABSENCE of a coverage answer as the premise of X=4 and X=5 ("no free
    # product"). Measured: two competitors with `free_core_coverage` unset,
    # five sources and three PARTIAL repos produced X ceiling 5 and a VALIDATE
    # at composite 10.0, confidence 0.90, with zero guardrail complaints - and
    # the all-"NONE" state produced a byte-identical DimensionSupport. The
    # distinction F1 introduced, which `Competitor`'s docstring and
    # `market_task` each defend at length, was erased at the one place it
    # decides a score, in the direction that manufactures a VALIDATE.
    free_unsettled = sum(
        competitor.free_core_coverage is None for competitor in market.competitors
    )
    # RATIFICATION C1 (2026-09-01). The floor's PRODUCT route must be as
    # closeable as its repository route, and it was not.
    #
    # `FLOOR_ALREADY_FREE` is a REJECT - the most consequential output this
    # system produces. Its repository route demands four machine-checked
    # conditions on a URL a tool actually returned (`is_live_free_substitute`).
    # Its product route demanded one enum on a `Competitor`, and
    # `Competitor.url` is OPTIONAL while `findings_urls` skips a null one - so
    # an unsourced name carrying `free_core_coverage="WHOLE_JOB"`, written by a
    # cheap-tier agent, entered NO closure check and still returned
    # REJECT at confidence 0.90 HIGH with `provisional=False` and zero
    # guardrail complaints. That is finding F1's own failure shape one level up.
    #
    # The CEILING deliberately keeps reading the unattributed `free_whole`:
    # capping X at 2 on an unsourced claim is the safe direction, and refusing
    # to reject on one is the other. A claim nobody can check may lower a score;
    # it may not kill an idea.
    free_whole_attributed = sum(
        competitor.free_core_coverage == "WHOLE_JOB" and competitor.url is not None
        for competitor in market.competitors
    )

    recent_problems = _recent_threads(sentiment.sources, _PROBLEM_CLASSIFICATIONS, reference)
    recent_acted = _recent_threads(sentiment.sources, _ACTED_CLASSIFICATIONS, reference)
    recent_sources = sum(
        _within_recency_window(source.dated, source.dated_is_retrieval_time, reference)
        for source in market.sources
    )

    if problems == 0:
        demand = NO_LEVEL_ABOVE_ONE
    elif problems >= 3 and recent_problems >= 1:
        if acted == 0:
            demand = 3
        elif recent_problems >= 5 and recent_acted >= 2 and segments >= 1:
            demand = 5
        else:
            demand = 4
    else:
        demand = 2

    if sources == 0:
        money = NO_LEVEL_ABOVE_ONE
    elif recent_sources >= 3 and segments >= 1:
        money = 5
    elif recent_sources >= 2:
        money = 4
    else:
        money = 3

    # RATIFICATION C5. C=1 now mirrors M=1 - "the branch returned nothing" -
    # instead of "the branch named no competitor", which was a false sentence
    # about a branch that worked and forced a compulsory 1 on an uncontested
    # market. C=2 absorbs "looked, named nobody" and every unknown-ownership
    # state, or the ladder deadlocks the way D's did.
    if sources == 0:
        room = NO_LEVEL_ABOVE_ONE
    elif competitors == 0:
        room = 2
    elif competitors >= 2 and recent_sources >= 1:
        room = (
            5
            if recent_sources >= 2 and vendor_true == 0 and vendor_unknown == 0
            else 4
        )
    else:
        room = 3

    # RATIFICATION C4: the F ceiling turns on whether the branch RETURNED
    # anything, not on whether it marked anything relevant. All-irrelevant is a
    # real level-2 finding, not an absence of evidence.
    if repos == 0:
        build = NO_LEVEL_ABOVE_ONE
    elif reusable >= 3:
        build = 5
    elif reusable >= 2:
        build = 4
    elif reusable >= 1:
        build = 3
    else:
        build = 2

    # X reads two evidence lists that answer one question - is the core
    # already free? - so a repository marked SOLVES_ENTIRELY and a competitor
    # giving the whole job away are the same finding and enter the same
    # ladder. X=3, X=4 and X=5 all open with "No free substitute", so a single
    # SOLVES_ENTIRELY repository caps the dimension at 2 outright; a free
    # product covering most of the core job caps it at 2 as well, and one
    # covering the whole job goes further, through `zero_ok` and `forbidden`
    # below.
    if complete >= 1 or free_whole >= 1 or free_most >= 1:
        headroom = 2
    elif free_part >= 1:
        headroom = 3
    elif partial >= 1:
        # An unsettled competitor caps this at 3: the top two rungs both assert
        # "no free product", which is a claim about evidence nobody gathered.
        headroom = 3 if free_unsettled >= 1 else 5
    else:
        # No relevant repository and no free product: nothing in the evidence
        # reaches this question. The ceiling was 3 here, which let a
        # Synthesist quote the X=3 anchor - which now requires a named free
        # product - over evidence that names none.
        headroom = NO_LEVEL_ABOVE_ONE

    return {
        "D": DimensionSupport(
            ceiling=demand,
            # The REJECT floor fires only on a branch that reached the
            # question. One on-topic comment in which nobody states a problem
            # is not "nobody has this problem", and `sentiment_coverage`
            # counts problem threads, so confidence is 0 exactly here and the
            # low-confidence override cannot intervene (review F2).
            zero_ok=usable >= RUBRIC_FLOOR_MIN_USABLE_THREADS and problems == 0,
            # Level 1 absorbs what the floor gives up. Without this the states
            # 1-2 usable threads with no problem thread match no anchor and no
            # bound: every score 0-5 would be rejected and the task could
            # never pass. A branch with a problem thread still cannot claim 1.
            one_ok=usable < RUBRIC_FLOOR_MIN_USABLE_THREADS and problems == 0,
            forbidden=frozenset(),
            summary=(
                f"{usable} usable thread(s), {problems} problem thread(s), "
                f"{recent_problems} of them dated within {RUBRIC_RECENCY_MONTHS} months, "
                f"{acted} classified BUILT_WORKAROUND or PAYS ({recent_acted} of those recent), "
                f"{segments} paying segment(s)"
            ),
        ),
        "M": DimensionSupport(
            ceiling=money,
            # "None of them names a buyer segment" needs the sources read, so
            # this floor is not fully countable (review F3). One necessary
            # condition is: a recorded paying segment IS a source naming a
            # buyer segment, per `market_task`'s definition of the field, so
            # it contradicts the anchor outright.
            # RATIFICATION C2: a floor needs the branch to have LOOKED.
            # `sources >= 1` fired a final REJECT on one web page.
            zero_ok=sources >= RUBRIC_FLOOR_MIN_MARKET_SOURCES and segments == 0,
            # The disjunct is not redundant. A branch reporting no source but a
            # recorded segment satisfies neither `sources == 0` alone nor the
            # widened clause, and its ceiling is 1 - so it would deadlock with
            # no legal score at all. This is the same trap D's repair hit.
            one_ok=(
                sources == 0
                or (sources < RUBRIC_FLOOR_MIN_MARKET_SOURCES and segments == 0)
            ),
            forbidden=frozenset(),
            summary=(
                f"{sources} market source(s), {recent_sources} dated within "
                f"{RUBRIC_RECENCY_MONTHS} months, {segments} paying segment(s)"
            ),
        ),
        "C": DimensionSupport(
            ceiling=room,
            zero_ok=competitors >= 1 and vendor_true == competitors,
            one_ok=sources == 0,
            forbidden=frozenset(),
            summary=(
                f"{competitors} competitor(s) of which {vendor_true} vendor owned, {vendor_unknown} unestablished, "
                f"{recent_sources} market source(s) dated within {RUBRIC_RECENCY_MONTHS} months"
            ),
        ),
        "F": DimensionSupport(
            ceiling=build,
            # RATIFICATION C4 (2026-09-01). F HAS NO LEVEL 0, and
            # FLOOR_NOT_BUILDABLE is retired.
            #
            # Three measured facts killed it. The floor was COMPULSORY: at
            # `relevant == 0` the ceiling was 1, `zero_ok` true and `one_ok`
            # false, so every score 1-5 was rejected and an honest Synthesist
            # could not decline it. The state that triggered it is the MODAL
            # outcome for an ordinary v1 - `limit` is `le=5`, the search is
            # stars-ranked, and five generic top-starred matches are correctly
            # marked IRRELEVANT. And the branch was NON-MONOTONE: at D2 M2 C2
            # X2, F=1 gives REJECT at composite 3.7 while F=0 gives NEEDS_WORK
            # at 3.4, because `elif feasibility == 0` sits above
            # `elif composite < 4.0`. Strictly worse evidence, strictly better
            # label.
            #
            # "No open-source prior art" is evidence about GitHub's top five by
            # stars. It is not evidence that two or three engineers cannot ship,
            # and it must not reject an idea. That state is now F=2.
            #
            # `anchor_problems` returns [] for an absent level, so `zero_ok` is
            # the enforcement point: a claimed F=0 fails SCORE_FLOOR_F.
            zero_ok=False,
            one_ok=repos == 0,
            forbidden=frozenset(),
            summary=(
                f"{repos} repository(ies), {relevant} marked SOLVES_ENTIRELY or PARTIAL, "
                f"{reusable} reusable"
            ),
        ),
        "X": DimensionSupport(
            ceiling=headroom,
            # A free product that covers the whole core job is the same kill
            # as a live free substitute repository, and until it could be
            # counted the floor could not see the commonest form of the thing
            # it exists to catch (review F1).
            # RATIFICATION C1: `free_whole_attributed`, not `free_whole`. The
            # REJECT route must rest on a URL a tool returned.
            zero_ok=live >= 1 or free_whole_attributed >= 1,
            one_ok=relevant == 0 and free_named == 0,
            # The only lower bound above level 1. X=2 asserts that every free
            # substitute is archived, non-commercial or stale, and that no
            # free product covers more than most of the core job; a live
            # substitute or a whole-job free product makes that false with no
            # judgement clause left over, and X=0 - the REJECT the PRD calls
            # this system's most valuable output - is then the only level
            # left. Without this the X floor is evadable by scoring 2.
            forbidden=(
                frozenset({2})
                if live >= 1 or free_whole_attributed >= 1
                else frozenset()
            ),
            summary=(
                f"{complete} free substitute(s) of which {live} live, "
                f"{partial} repository(ies) marked PARTIAL, "
                f"{free_whole} free product(s) covering the whole core job "
                f"({free_whole_attributed} with an attributed URL), "
                f"{free_most} covering most of it, {free_part} a separable part"
            ),
        ),
    }


def score_support_problems(
    verdict: Verdict,
    market: MarketFindings,
    sentiment: SentimentFindings,
    feasibility: FeasibilityFindings,
    *,
    now: datetime | None = None,
) -> list[str]:
    """Reject a score the counted evidence cannot carry (F16).

    `anchor_problems` checks that `anchor_matched` is the TEXT of the anchor for
    the score claimed. Nothing checked that the EVIDENCE satisfies that text, so
    a Synthesist could quote the D=5 anchor verbatim over two stale threads and
    pass every mechanical check in the system.

    Where the line is drawn, and why:

    * Every dimension is bounded from ABOVE. Over-claiming is the failure this
      exists to stop, and PRD §10.2's "partial satisfaction of anchor N scores
      N-1" is respected by construction - a ceiling permits N-1 and everything
      under it, so an honest downgrade never trips.
    * Only levels 0 and 1 are bounded from BELOW, because those are the two
      levels where a LOW score is itself a strong claim rather than a cautious
      one. Level 0 is a fatal floor (D, M and X reject on it; F caps the run at
      NEEDS_WORK) and level 1 says "the evidence does not reach this question"
      about a branch that may demonstrably have answered it. Everywhere else,
      scoring under what the evidence supports is caution, and caution cannot
      manufacture a false VALIDATE.
    * Judgement clauses are never enforced. "Names a buyer segment", "states an
      axis of beatability", "covers most of the core job", "together cover the
      separable parts of the scoped v1" are prose about prose; each is dropped
      from the bound, which only ever makes the bound more permissive.

    Between them, three of the four hard floors become arithmetic rather than
    wording: D=0, F=0 and X=0 are fully determined by the counters. M=0 stays a
    judgement call, because "none of them names a buyer segment" cannot be
    settled without reading the sources; it is bounded only by the one
    structured fact that contradicts it, a recorded paying segment.

    Every floor also carries a PRECONDITION on the branch having reached the
    question at all, because "we looked and found nothing" and "we did not
    look" are different claims and only the first is a finding about the
    world. D=0 needs `RUBRIC_FLOOR_MIN_USABLE_THREADS` on-topic threads, F=0
    needs a repository to have come back, X=0 needs a live free substitute or
    a whole-job free product. Whatever a precondition excludes has to land
    somewhere: for D that is level 1, whose lower bound widens to match, and
    the two edits are one edit - separated, they deadlock the ladder.
    """
    support = rubric_support(market, sentiment, feasibility, now=now)
    problems: list[str] = []

    for code, field_name in _DIMENSIONS:
        score = getattr(verdict, field_name).score
        limits = support[code]

        if score == 1:
            if not limits.one_ok:
                problems.append(
                    f"SCORE_LEVEL_ONE_{code}: score 1 claims the evidence does not reach this "
                    f"question, but the branch answered it - {limits.summary}"
                )
            continue

        if score == 0 and not limits.zero_ok:
            problems.append(
                f"SCORE_FLOOR_{code}: the {code}=0 anchor is not satisfied by the findings - "
                f"{limits.summary}"
            )
            continue

        if score in limits.forbidden:
            problems.append(
                f"SCORE_FLOOR_{code}: the {code}={score} anchor is contradicted by the findings - "
                f"{limits.summary}"
            )
            continue

        if score > limits.ceiling:
            supported = (
                "no score above the reserved level 1"
                if limits.ceiling == NO_LEVEL_ABOVE_ONE
                else f"at most {code}={limits.ceiling}"
            )
            problems.append(
                f"SCORE_SUPPORT_{code}: the findings support {supported}, not {code}={score} - "
                f"{limits.summary}"
            )
    return problems

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
    now: datetime | None = None,
) -> list[str]:
    problems: list[str] = []
    for code, field_name in _DIMENSIONS:
        problems.extend(anchor_problems(code, getattr(verdict, field_name), anchors))

    if not verdict.kill_criteria:
        problems.append(
            "KILL_CRITERIA: name at least one observation that would falsify this idea; "
            "the schema no longer substitutes the computed floor list"
        )

    if findings is None:
        return problems

    market, sentiment, feasibility = findings
    problems.extend(confidence_problems(verdict, market, sentiment, feasibility, now=now))
    problems.extend(score_support_problems(verdict, market, sentiment, feasibility, now=now))
    expected_counts = compute_evidence_counts(market, sentiment, feasibility)
    # `evidence_counts` is deliberately NOT rejected on mismatch. It is repaired
    # in `make_rubric_guardrail` instead, because rejecting it here was an
    # unwinnable demand:
    #
    #   CrewAI renders `dict[str, int]` into the prompt's injected JSON schema as
    #     {"additionalProperties": false, "properties": {}, "required": []}
    #
    # - a schema for an object that may contain NOTHING. The model is instructed
    # to emit `{}`, then judged by exact equality against fifteen recomputed
    # keys that `tasks.yaml` never names.
    #
    # MEASURED (2026-09-01, `generate_model_description(Verdict)`): the injected
    # schema really does render as `{"properties": {}, "required": []}`, and
    # `test_the_injected_schema_really_does_ask_for_an_empty_object` pins it.
    # INFERRED, not measured: that a model following that instruction fails this
    # check every time. No live run was observed - but a check the prompt tells
    # the model how to fail is not worth keeping either way.
    #
    # The cost of losing the first evaluation is one fewer chance at the anchor,
    # score-support and confidence checks that are the POINT of this guardrail.
    # `guardrail_max_retries: 2` allows THREE evaluations, not two - CrewAI
    # raises at `attempt >= guardrail_max_retries` (`crewai/task.py:1382`), so
    # attempts 0 and 1 retry and attempt 2 raises. On exhaustion
    # `_run_synthesis` has no try/except, so the run dies with no report at all.
    #
    # Repair is also strictly safer than rejection. These counts are read by
    # nothing else in the codebase - `confidence_problems` and
    # `score_support_problems` recompute from the findings themselves - so
    # overwriting cannot influence a score. It makes the field always correct
    # rather than usually correct.
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
    now: datetime | None = None,
) -> Callable[[TaskOutputLike], GuardrailResult]:
    findings = (market, sentiment, feasibility)

    expected_counts = compute_evidence_counts(*findings)

    def guardrail(output: TaskOutputLike) -> GuardrailResult:
        raw = output.raw or ""
        verdict, error = _parse_for_guardrail(raw, Verdict)
        if error:
            return False, error
        assert verdict is not None
        problems = rubric_problems(
            verdict, anchors=anchors, findings=findings, now=now
        )
        if problems:
            return False, " | ".join(problems)
        if verdict.evidence_counts == expected_counts:
            return True, raw
        # Repair rather than reject - see the long note in `rubric_problems`.
        # CrewAI accepts a `(True, str)` return as the task's NEW output, so
        # handing back corrected JSON is a supported way to fix a field the
        # model was never told how to fill.
        #
        # `model_validate` on a full dump, NOT `model_copy(update=...)`:
        # `model_copy` bypasses validators, and `Verdict`'s are what recompute
        # the composite score, the floors, the confidence band and
        # `provisional`. Copying would produce a Verdict whose arithmetic had
        # never been re-derived - the exact class of defect the schema's
        # overwrite-the-model design exists to prevent.
        repaired = Verdict.model_validate(
            {**verdict.model_dump(mode="json"), "evidence_counts": expected_counts}
        )
        return True, repaired.model_dump_json(indent=2)

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
    # Re-exported from config so the guardrail stays the single import point
    # for callers that need the rubric text; config.py owns the values.
    "ANCHOR_MATCH_THRESHOLD",
    "CITATION_GUARDRAIL",
    "COMPETITIVE_ROOM_ANCHORS",
    "DEMAND_ANCHORS",
    "FEASIBILITY_ANCHORS",
    "HEADROOM_ANCHORS",
    "LEVEL_ONE_ANCHOR",
    "MARKET_ANCHORS",
    "RUBRIC_ANCHORS",
    "anchor_problems",
    "check_findings",
    "check_report_mechanics",
    "check_rubric",
    "check_scope",
    "compute_confidence_inputs",
    "compute_evidence_counts",
    "confidence_problems",
    "findings_problems",
    "findings_urls",
    "is_live_free_substitute",
    "is_reusable_repository",
    "make_report_guardrail",
    "make_rubric_guardrail",
    "median_market_source_age_months",
    "parse_raw_model",
    "report_mechanics_problems",
    "rubric_problems",
    "rubric_support",
    "scope_problems",
    "score_support_problems",
    "token_overlap",
]