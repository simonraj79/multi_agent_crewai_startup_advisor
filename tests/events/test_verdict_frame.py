"""The `verdict` frame contract - pinned to both sides.

`Verdict.compute_mechanical_result` is the one place in this product where the
answer is derived rather than generated, and until the `VerdictComputedEvent`
existed it reached an operator through exactly one door: the read-only `derived`
block of the verdict gate. That door does not exist under `gates: "auto"`, which
is the mode built to produce a verdict without a human, and it was never on
`GET /api/runs/{run_id}` in any mode. This module covers the second door.

It is the sibling of `test_run_state_status.py` and works the same way: it
builds frames from the real event through the real serializer, asserts the
contract in Python, and writes those same frames to a JSON fixture the frontend
suite feeds to its real client. Change the shape on either side and one of the
two suites fails. Regenerate the fixture deliberately with:

    .\\.venv\\Scripts\\python.exe tests\\events\\test_verdict_frame.py --write
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import unittest

from crewai.flow import build_flow_structure

from brief_crew.events import (
    FrameBuffer,
    FrameData,
    NodeRegistry,
    QUARANTINE_NODE_ID,
    StreamSinkAdapter,
    VerdictComputedEvent,
)
from brief_crew.schemas import DimensionScore, Verdict
from brief_crew.service.runner import RunExecution, SyntheticValidatorRunner
from brief_crew.validator_flow import ValidatorFlow


REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_PATH = REPO_ROOT / "frontend" / "tests" / "fixtures" / "backendVerdictFrames.json"

#: Must equal `RUN_ID` in `frontend/tests/helpers.ts` - the client drops frames
#: belonging to any other run, so a fixture built under a different id would be
#: ignored in silence rather than failing loudly.
FIXTURE_RUN_ID = "run-under-test"

#: Frozen so the fixture is byte-stable and a diff means a real shape change.
FIXTURE_TS = datetime(2026, 8, 30, 12, 0, 0, tzinfo=timezone.utc)

EVIDENCE_URL = "https://news.ycombinator.com/item?id=1"

#: Three distinct market sources. `DimensionScore.evidence_thin` is computed as
#: `len(evidence_urls) < 3`, so this is the one way to say "we looked and found
#: three sources" as opposed to "we barely looked" - which is the difference
#: the third fixture entry below turns on.
MARKET_URLS = [
    EVIDENCE_URL,
    "https://example.com/market-note",
    "https://example.com/category-revenue",
]


def _dimension(score: int, urls: list[str] | None = None) -> DimensionScore:
    return DimensionScore(
        score=score,
        anchor_matched=f"A rubric anchor standing in for level {score}.",
        evidence_urls=list(urls) if urls is not None else [EVIDENCE_URL],
    )


def _verdict(
    *,
    demand: int,
    coverage: float,
    market: int = 3,
    competitive: int = 3,
    feasibility: int = 3,
    headroom: int = 3,
    market_urls: list[str] | None = None,
) -> Verdict:
    """A real `Verdict`, so the schema - not the test - decides the answer.

    Every dimension past `demand` has a default equal to what the first two
    fixture entries were built with, so widening this signature could not move
    a byte of the frames that already existed - which matters, because those
    two are what `realVerdictFrameShape.spec.ts` asserts field for field.
    """

    return Verdict(
        demand=_dimension(demand),
        market=_dimension(market, market_urls),
        competitive_room=_dimension(competitive),
        feasibility=_dimension(feasibility),
        headroom_over_free=_dimension(headroom),
        evidence_counts={"sentiment_usable_threads": 1},
        market_coverage=coverage,
        sentiment_coverage=coverage,
        feasibility_coverage=coverage,
        median_market_source_age_months=1,
        branches_ok=3,
        cheapest_next_test="Interview five clinic operations managers.",
    )


#: The two verdicts the fixture carries, chosen to cover both ends of every
#: nullable or optional part of the contract in one file:
#:
#: * `REJECTED` fires `FLOOR_NO_DEMAND`, so `fatal_floors` is non-empty and
#:   `decision_reason` names the floor; at confidence 0.50 a REJECT is also
#:   `provisional`, which is the flag the report has to say out loud.
#: * `RESCORED` is what the revise loop republishes: no floor, so `fatal_floors`
#:   is `[]` and `decision_reason` is `null`, and `provisional` is false.
#:
#: * `THIN_EVIDENCE` is the third case and the one neither of the others can
#:   reach: a floor is LISTED and did not DECIDE. `compute_mechanical_result`
#:   collects `fatal_floors` first and then picks a label through an if/elif
#:   whose FIRST arm is `confidence < 0.35`
#:   (`schemas/validator.py:538-566`), so a run that is both under-evidenced
#:   and floored comes back `NEEDS_WORK / INSUFFICIENT_EVIDENCE` carrying
#:   `["FLOOR_NO_MARKET"]`. A client that reads `fatal_floors[0]` as the
#:   reason - the obvious implementation - tells the operator the market was
#:   rejected when what actually happened is that the run could not see far
#:   enough to say. Nothing in the first two entries distinguishes those, so
#:   until this entry existed the shell could get it wrong and stay green.
#:
#: A client that renders all three renders every case the schema can produce.
REJECTED = _verdict(demand=0, coverage=0.50)
RESCORED = _verdict(demand=3, coverage=0.90)
#: D 2, M 0, C 2, F 3, X 3 -> composite 3.8; coverage 0.34 on all three
#: branches -> confidence 0.34, band LOW, and the override fires. `market`
#: carries THREE sources while scoring 0, so `evidence_thin` is false there and
#: true for D, C, F and X: the M ladder's zero means "three sources and no
#: nameable buyer", which is a finding, where the other four are simply thin.
THIN_EVIDENCE = _verdict(
    demand=2, coverage=0.34, market=0, competitive=2, market_urls=MARKET_URLS
)


def build_verdict_frames() -> tuple[FrameData, ...]:
    """Both verdict frames, straight out of the real serializer.

    The registry is built from the live `ValidatorFlow` structure rather than
    hand-written, so `synthesize` is a node because the flow declares one.
    """

    buffer = FrameBuffer(capacity=16)
    adapter = StreamSinkAdapter(
        run_id=FIXTURE_RUN_ID,
        buffer=buffer,
        registry=NodeRegistry.from_flow_structure(build_flow_structure(ValidatorFlow)),
    )
    for verdict in (REJECTED, RESCORED, THIN_EVIDENCE):
        adapter(None, VerdictComputedEvent(verdict=verdict, timestamp=FIXTURE_TS))
    # An emit that raised would be swallowed into `emit_errors` and leave a
    # short, silently-wrong fixture behind, so refuse to build one.
    stats = buffer.stats()
    if stats.emit_errors or stats.dropped:
        raise AssertionError(f"frame capture lost frames: {stats}")
    return buffer.replay()


def fixture_payload() -> str:
    frames = [frame.to_dict() for frame in build_verdict_frames()]
    return json.dumps(frames, indent=2) + "\n"


class VerdictFrameContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.rejected, self.rescored, self.thin = build_verdict_frames()

    def test_the_frame_carries_exactly_the_agreed_payload(self) -> None:
        """The contract the Studio client is built against, key for key.

        `assertEqual` on the whole mapping rather than a handful of `assertIn`s:
        an *extra* key is as much a contract change as a missing one, because
        this payload is deliberately a hand-picked subset of `Verdict` and the
        thing it must never become is a full model dump.
        """

        self.assertEqual(self.rejected.kind.value, "verdict")
        self.assertEqual(self.rejected.event_type.value, "VERDICT_COMPUTED")
        self.assertEqual(self.rejected.level.value, "INFO")
        self.assertEqual(
            self.rejected.to_dict()["details"],
            {
                "verdict": "REJECT",
                "composite_score": 4.2,
                "confidence": 0.5,
                "confidence_band": "MODERATE",
                "provisional": True,
                "fatal_floors": ["FLOOR_NO_DEMAND"],
                "decision_reason": "FLOOR_NO_DEMAND",
                "dimensions": {
                    "demand": 0,
                    "market": 3,
                    "competitive_room": 3,
                    "feasibility": 3,
                    "headroom_over_free": 3,
                },
                # Added 2026-09-01 with the reasoning-effort drop. How closely
                # each dimension's prose matched its rubric anchor, 0-1, keyed
                # by DimensionCode.
                #
                # `anchor_problems` rejects below 0.85 and reported the overlap
                # only inside that rejection, so a passing run recorded nothing
                # and the threshold was a cliff with no visible approach. That
                # matters now that the Synthesist runs at "low" effort: anchor
                # reproduction is the first thing expected to degrade, and a
                # rejection costs a full escalation-tier retry.
                #
                # D is absent: score 0 has no level-1 exemption but IS matched
                # by overlap, so it appears whenever the ladder has that level.
                # Level 1 is excluded because it is matched VERBATIM - there is
                # no margin to report, only a pass or a rejection.
                "anchor_margins": self.rejected.to_dict()["details"]["anchor_margins"],
            },
        )
        margins = self.rejected.to_dict()["details"]["anchor_margins"]
        self.assertTrue(margins, "the margins must not be empty for this verdict")
        for code, value in margins.items():
            with self.subTest(dimension=code):
                self.assertIn(code, {"D", "M", "C", "F", "X"})
                self.assertIsInstance(value, float)
                self.assertGreaterEqual(value, 0.0)
                self.assertLessEqual(value, 1.0)

    def test_an_empty_floor_list_and_a_null_reason_are_present_not_omitted(self) -> None:
        """A verdict decided by the composite alone still says so.

        Both of these are the common case - most runs trip no floor - and a
        client that has to distinguish "absent" from "empty" gets it wrong on the
        first quiet verdict. So the keys are always there.
        """

        details = self.rescored.to_dict()["details"]
        self.assertEqual(details["fatal_floors"], [])
        self.assertIsNone(details["decision_reason"])
        self.assertFalse(details["provisional"])
        self.assertEqual(details["verdict"], "NEEDS_WORK")

    def test_a_listed_floor_is_not_always_the_reason_the_run_was_decided(self) -> None:
        """The third entry, and the distinction it exists to make visible.

        `fatal_floors` is collected in full and the LABEL is then chosen by an
        if/elif whose first arm is the low-confidence override
        (`schemas/validator.py:538-566`). So this verdict lists
        `FLOOR_NO_MARKET` - market scored 0 with demand at 2, which is exactly
        that floor's trigger - and was decided by `INSUFFICIENT_EVIDENCE`
        instead, because at 0.34 the run cannot support a final answer at all.

        Neither of the other two entries can catch a client that reads
        `fatal_floors[0]` as the reason: in `REJECTED` the floor and the reason
        are the same string, and in `RESCORED` both are empty. Here they differ,
        and a shell that conflates them says "no market" about a run whose real
        finding is "we could not see".
        """

        details = self.thin.to_dict()["details"]
        self.assertEqual(details["verdict"], "NEEDS_WORK")
        self.assertEqual(details["decision_reason"], "INSUFFICIENT_EVIDENCE")
        self.assertEqual(details["fatal_floors"], ["FLOOR_NO_MARKET"])
        self.assertNotEqual(details["decision_reason"], details["fatal_floors"][0])
        self.assertEqual(details["confidence"], 0.34)
        self.assertEqual(details["confidence_band"], "LOW")
        self.assertEqual(details["composite_score"], 3.8)
        self.assertTrue(details["provisional"])
        self.assertEqual(
            details["dimensions"],
            {
                "demand": 2,
                "market": 0,
                "competitive_room": 2,
                "feasibility": 3,
                "headroom_over_free": 3,
            },
        )

    def test_the_thin_entry_is_thin_where_the_report_would_say_so(self) -> None:
        """D, C, F and X are thin; M is not, and the asymmetry is the finding.

        `DimensionScore.evidence_thin` is `len(evidence_urls) < 3`, and
        `ValidationReport.thin_dimensions` is the field a report renders from
        it. The verdict FRAME carries neither - its payload is the hand-picked
        contract in `events/verdict.py`, deliberately not a model dump - so this
        is asserted on the `Verdict` the frame was built from rather than on the
        frame. It is what makes this entry the screen it is meant to be: four
        dimensions nobody could gather evidence for, and one that scored zero
        having been looked at properly.
        """

        thin = {
            code
            for code, dimension in (
                ("D", THIN_EVIDENCE.demand),
                ("M", THIN_EVIDENCE.market),
                ("C", THIN_EVIDENCE.competitive_room),
                ("F", THIN_EVIDENCE.feasibility),
                ("X", THIN_EVIDENCE.headroom_over_free),
            )
            if dimension.evidence_thin
        }
        self.assertEqual(thin, {"D", "C", "F", "X"})
        self.assertEqual(len(THIN_EVIDENCE.market.evidence_urls), 3)

    def test_the_payload_is_the_schema_s_arithmetic_not_the_serializer_s(self) -> None:
        """The frame must be a report of `compute_mechanical_result`, not a copy.

        Every value asserted above is one the schema recomputes and overwrites.
        Reading them back off the model is what makes this frame worth having:
        if the serializer ever computed any of them itself, the two would drift
        and the trace would disagree with the report.
        """

        for frame, verdict in (
            (self.rejected, REJECTED),
            (self.rescored, RESCORED),
            (self.thin, THIN_EVIDENCE),
        ):
            details = frame.to_dict()["details"]
            self.assertEqual(details["verdict"], verdict.verdict)
            self.assertEqual(details["composite_score"], verdict.composite_score)
            self.assertEqual(details["confidence"], verdict.confidence)
            self.assertEqual(details["confidence_band"], verdict.confidence_band)
            self.assertEqual(details["provisional"], verdict.provisional)
            self.assertEqual(details["fatal_floors"], list(verdict.fatal_floors))
            self.assertEqual(details["decision_reason"], verdict.decision_reason)

    def test_nothing_in_the_payload_can_be_clipped(self) -> None:
        """`FieldBoundedSerializer` clips every string at 4096 characters.

        That bound exists for tool output and model prose. Everything in this
        payload is a `Literal` union or an integer, so none of it can reach the
        bound - `decision_reason`, the longest, is 21 characters. Asserted
        rather than assumed, because a future field that *is* free text would
        arrive here truncated and silently wrong.
        """

        details = self.rejected.to_dict()["details"]
        for key, value in details.items():
            if isinstance(value, str):
                self.assertLess(len(value), 64, key)

    def test_the_frame_lands_on_the_synthesist_node(self) -> None:
        """Both publications, including the revised one.

        `revise_verdict` re-runs the same crew through the same
        `_run_synthesis`, so its output is still the Synthesist's. Attributing
        the correction to `revise_verdict` would leave a client that shows "the
        score" reading two nodes, with the stale one never replaced.
        """

        self.assertEqual(self.rejected.node_id, "synthesize")
        self.assertEqual(self.rescored.node_id, "synthesize")
        self.assertEqual(self.thin.node_id, "synthesize")

    def test_a_graph_without_a_synthesist_quarantines_rather_than_invents(self) -> None:
        """Brief Flow declares no `synthesize`, and must not gain a phantom one.

        The quarantine node is visible in the UI and counted in
        `frames.unattributed`, so this failure mode announces itself. Silently
        naming a node the graph does not draw would not.
        """

        buffer = FrameBuffer(capacity=4)
        adapter = StreamSinkAdapter(
            run_id="brief-flow-run",
            buffer=buffer,
            registry=NodeRegistry(flow_method_nodes={"check_cache": "check_cache"}),
        )
        adapter(None, VerdictComputedEvent(verdict=RESCORED, timestamp=FIXTURE_TS))
        self.assertEqual(buffer.replay()[0].node_id, QUARANTINE_NODE_ID)

    def test_the_synthetic_double_emits_the_serializer_shape(self) -> None:
        """A double that lies about the contract is how the last one survived.

        `SyntheticValidatorRunner` backs `SYNTHETIC=1`, the E2E suite and the
        only way to look at this UI without spending money. Its verdict frame
        must carry the same keys the real serializer emits, or the free path
        certifies nothing about the paid one - and unattended mode is exactly
        where this frame is the *only* carrier of the score.
        """

        buffer = FrameBuffer(capacity=64)
        adapter = StreamSinkAdapter(
            run_id="synthetic-run",
            buffer=buffer,
            registry=NodeRegistry.from_flow_structure(
                build_flow_structure(ValidatorFlow)
            ),
        )
        SyntheticValidatorRunner()(
            RunExecution(
                run_id="synthetic-run",
                inputs={"idea": "a synthetic idea", "no_gates": True},
                capture=adapter,
            )
        )
        verdicts = [
            frame for frame in buffer.replay() if frame.kind.value == "verdict"
        ]
        self.assertEqual(len(verdicts), 1)
        self.assertEqual(verdicts[0].node_id, "synthesize")
        self.assertEqual(
            sorted(verdicts[0].details),
            sorted(self.rescored.details),
        )
        self.assertEqual(
            sorted(dict(verdicts[0].details["dimensions"])),
            sorted(dict(self.rescored.details["dimensions"])),
        )

    def test_frontend_fixture_matches_the_serializer(self) -> None:
        """The other half of the pin.

        `frontend/tests/fixtures/backendVerdictFrames.json` is what the Studio
        suite drives its real client with. If the serializer's output moves and
        the fixture does not, the frontend goes on being tested against a shape
        the backend no longer emits.
        """

        self.assertTrue(
            FIXTURE_PATH.is_file(),
            f"missing {FIXTURE_PATH}; regenerate with --write",
        )
        self.assertEqual(
            FIXTURE_PATH.read_text(encoding="utf-8"),
            fixture_payload(),
            "the serializer no longer emits the frames the frontend fixture "
            "holds. Review the change on both sides, then regenerate:\n"
            "    .\\.venv\\Scripts\\python.exe "
            "tests\\events\\test_verdict_frame.py --write",
        )


def _write_fixture() -> None:
    FIXTURE_PATH.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE_PATH.write_text(fixture_payload(), encoding="utf-8")
    print(f"wrote {FIXTURE_PATH}")


if __name__ == "__main__":
    if "--write" in sys.argv:
        _write_fixture()
    else:
        unittest.main()
