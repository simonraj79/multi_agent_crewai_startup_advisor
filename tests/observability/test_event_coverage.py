"""Definition of Done row C3: every CrewAI event is mapped or reasoned about.

Two halves, and the second is the one that matters when something new appears.

The first half enumerates every `BaseEvent` subclass the INSTALLED CrewAI
declares - not a list typed into a file, which is a list that is wrong after the
next upgrade - and asserts each is either converted by the frame pipeline into
something this exporter renders, or carries a written reason for not being.

The second half feeds the exporter a frame whose kind it has never seen and a
frame whose stage it has never seen, and asserts each becomes an EVENT
observation carrying its details. That is the property that makes the first
half survive: a new event type reaching the frame pipeline reaches Langfuse as
something a person can read, rather than vanishing.
"""

from __future__ import annotations

from pathlib import Path
import unittest

from crewai.events import FlowFinishedEvent

from brief_crew.events.models import FrameData, FrameKind, FrameLevel, UIEventType
from brief_crew.events.registry import NodeRegistry
from brief_crew.events.serializer import FieldBoundedSerializer
from brief_crew.observability import mapping
from tests.observability.replay import RUN_ID, Recorder, by_role, drive, exporter_for


SERIALIZER = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "brief_crew"
    / "events"
    / "serializer.py"
)
MAPPING = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "brief_crew"
    / "observability"
    / "mapping.py"
)


class _UnknownKind:
    """A frame kind from a future version of the frame contract."""

    def __init__(self, value: str) -> None:
        self.value = value


class CrewAIEventCoverageTests(unittest.TestCase):
    def test_every_declared_event_is_mapped_or_has_a_reason(self) -> None:
        classes = mapping.crewai_event_classes()
        self.assertGreater(len(classes), 100, "the enumeration found almost nothing")
        unreasoned = [
            name
            for name, module in sorted(classes.items())
            if name not in mapping.FRAME_PIPELINE_EVENTS
            and not mapping.unmapped_reason(name, module)
        ]
        self.assertEqual([], unreasoned)

    def test_the_two_tables_partition_the_declared_classes(self) -> None:
        """The assertion row C3 rests on, and it can now actually fail.

        `UNMAPPED_WITH_REASON` used to be COMPUTED from this same enumeration -
        every class not in the handled set was put into it with a reason looked
        up by declaring module - so a class CrewAI added tomorrow would appear
        on both sides of this equality at once and be reported as reasoned
        about by a table that had never heard of it. A test that cannot fail is
        not evidence, and this is the row whose whole subject is "is anything
        being silently dropped".

        Written out, a new class is in neither half and is named here.
        """

        classes = mapping.crewai_event_classes()
        unmapped = mapping.UNMAPPED_WITH_REASON
        self.assertEqual(
            [],
            sorted(set(classes) - set(mapping.FRAME_PIPELINE_EVENTS) - set(unmapped)),
            "CrewAI declares an event class that is neither handled nor "
            "deliberately unmapped; add it to one of the two tables in "
            "mapping.py with a reason",
        )
        self.assertEqual(
            [],
            sorted(
                (set(mapping.FRAME_PIPELINE_EVENTS) | set(unmapped)) - set(classes)
            ),
            "a table names a class the installed CrewAI does not declare",
        )
        self.assertEqual(
            set(),
            set(mapping.FRAME_PIPELINE_EVENTS) & set(unmapped),
            "a class cannot be both handled and deliberately unmapped",
        )

    def test_the_table_is_written_out_rather_than_derived(self) -> None:
        """The control for the test above, and the only one that can catch a
        reversion to the derived table: a computed one is exactly the size of
        the difference, always, so equality proves nothing about it."""

        source = MAPPING.read_text(encoding="utf-8")
        for name in sorted(mapping.UNMAPPED_WITH_REASON)[:8]:
            with self.subTest(name=name):
                self.assertIn(f'"{name}"', source)

    def test_every_unmapped_class_carries_a_non_empty_reason(self) -> None:
        blank = [n for n, why in mapping.UNMAPPED_WITH_REASON.items() if not why.strip()]
        self.assertEqual([], blank)

    def test_the_enumeration_looks_outside_crewai_events_types(self) -> None:
        """Two classes lived outside every count until it did.

        `crewai/skills/events.py` declares `SkillDownloadStartedEvent` and
        `SkillDownloadCompletedEvent` beside the code that raises them rather
        than under `crewai.events.types`, so a walk of the types package alone
        answered 163 where the installed package declares 165 - and the two
        were absent from the handled set, absent from the unmapped set, and
        absent from the partition assertion whose job is to notice that.
        """

        classes = mapping.crewai_event_classes()
        from crewai.events.base_events import BaseEvent
        import crewai.skills.events as skills_events

        declared = {
            name
            for name, obj in vars(skills_events).items()
            if isinstance(obj, type)
            and issubclass(obj, BaseEvent)
            and obj is not BaseEvent
            and obj.__module__ == skills_events.__name__
        }
        self.assertTrue(declared, "the skills module declares no events any more")
        for name in sorted(declared):
            with self.subTest(name=name):
                self.assertIn(name, classes)

    def test_every_handled_name_is_a_real_class(self) -> None:
        classes = mapping.crewai_event_classes()
        missing = [n for n in mapping.FRAME_PIPELINE_EVENTS if n not in classes]
        self.assertEqual([], missing)

    def test_every_handled_name_is_named_by_the_frame_pipeline(self) -> None:
        """The anti-rot half: the table cannot claim a branch that is not there.

        This exporter's mapping is a statement about ANOTHER module's isinstance
        ladder, which is exactly the kind of mirror this repository has watched
        drift before - a client-side copy of the server's problem codes agreed
        with itself at the wrong number for weeks. Reading the source is what
        stops the same thing happening here.
        """

        source = SERIALIZER.read_text(encoding="utf-8")
        missing = [n for n in mapping.FRAME_PIPELINE_EVENTS if n not in source]
        self.assertEqual([], missing)

    def test_every_disposition_names_a_reason(self) -> None:
        for kind, disposition in mapping.FRAME_DISPOSITIONS.items():
            with self.subTest(kind=kind):
                self.assertTrue(disposition.reason.strip())


class UnknownFrameTests(unittest.TestCase):
    def _run_with(self, extra) -> list:
        exporter, backend = exporter_for()
        recorder = Recorder()
        recorder.run_started({"idea": "x"})
        recorder.node_started("n1")
        extra(recorder)
        recorder.node_ended("n1")
        recorder.run_completed({"ok": True})
        drive(exporter, recorder.frames)
        return backend.observations

    def test_a_frame_kind_this_exporter_has_never_seen_becomes_an_event(self) -> None:
        def add(recorder: Recorder) -> None:
            frame = recorder.add(
                FrameKind.NODE_STATE, UIEventType.NODE_START, "n1", {"anything": 1}
            )
            # A kind from a future frame contract. `FrameData` is frozen, so the
            # substitution is made the way a frozen dataclass is edited at all.
            object.__setattr__(frame, "kind", _UnknownKind("teleport"))

        observations = self._run_with(add)
        events = [o for o in observations if o.as_type == "event"]
        self.assertEqual(1, len(events))
        self.assertEqual("NODE_START", events[0].name)
        self.assertEqual("teleport", events[0].metadata["frame_kind"])
        self.assertEqual({"anything": 1}, events[0].metadata["details"])

    def test_a_stage_this_exporter_has_never_seen_becomes_an_event(self) -> None:
        def add(recorder: Recorder) -> None:
            recorder.add(
                FrameKind.LLM,
                UIEventType.MODEL_CALL,
                "n1",
                {"stage": "daydreaming", "call_id": "c1", "model": "m"},
            )

        observations = self._run_with(add)
        events = [o for o in observations if o.as_type == "event"]
        self.assertEqual(1, len(events))
        self.assertEqual("MODEL_CALL", events[0].name)
        self.assertEqual("daydreaming", events[0].metadata["details"]["stage"])

    def test_the_disposition_for_an_unknown_kind_is_event_and_says_so(self) -> None:
        disposition = mapping.disposition_for(_UnknownKind("teleport"))
        self.assertEqual(mapping.EVENT, disposition.kind)
        self.assertIn("never seen", disposition.reason)

    def test_nothing_is_dropped_without_a_disposition(self) -> None:
        """Every kind the frame contract declares has an entry, not a default."""

        for kind in FrameKind:
            with self.subTest(kind=kind):
                self.assertIn(kind, mapping.FRAME_DISPOSITIONS)


class FrameKindShapeTests(unittest.TestCase):
    def test_the_helper_builds_the_real_frame_type(self) -> None:
        recorder = Recorder()
        recorder.run_started({"idea": "x"})
        self.assertIsInstance(recorder.frames[0], FrameData)
        self.assertEqual(RUN_ID, recorder.frames[0].run_id)
        self.assertIs(FrameLevel.INFO, recorder.frames[0].level)


class UnhandledTallyTests(unittest.TestCase):
    """C3's other half: what the frame pipeline could NOT convert, in Langfuse.

    An event class the serializer's ladder does not match becomes no frame at
    all (`serializer.py::record_unhandled` counts it and returns `()`), so no
    exporter downstream can turn it into an observation however it is written -
    and until the count travelled, the gap existed only inside a process that
    had already exited. The orchestrator's call was NOT to emit a frame per
    unhandled event: memory and knowledge events alone would flood a
    2,000-frame ring with instrumentation about instrumentation. The tally
    rides the run's own terminal frame instead, and the exporter writes it onto
    the trace.
    """

    def test_the_serializer_reports_its_tally_on_the_terminal_frame(self) -> None:
        serializer = FieldBoundedSerializer()
        registry = NodeRegistry()

        class _Unconverted:
            """An event class no branch of the ladder matches."""

            type = "knowledge_query_started"

        for _ in range(3):
            self.assertEqual((), serializer.drafts(None, _Unconverted(), registry))
        drafts = serializer.drafts(
            None,
            FlowFinishedEvent(flow_name="a flow", result="done", state={}),
            registry,
        )
        details = dict(drafts[0].details)
        self.assertEqual({"knowledge_query_started": 3}, details["unhandled_events"])

    def test_a_run_that_converted_everything_adds_no_key(self) -> None:
        serializer = FieldBoundedSerializer()
        drafts = serializer.drafts(
            None,
            FlowFinishedEvent(flow_name="a flow", result="done", state={}),
            NodeRegistry(),
        )
        self.assertNotIn("unhandled_events", dict(drafts[0].details))

    def test_the_exporter_puts_the_tally_on_the_trace(self) -> None:
        exporter, backend = exporter_for()
        recorder = Recorder()
        recorder.run_started({})
        recorder.node_started("n1")
        recorder.node_ended("n1")
        recorder.add(
            FrameKind.RUN_STATE,
            UIEventType.WORKFLOW_END,
            "workflow",
            {
                "status": "completed",
                "result": {"ok": True},
                "unhandled_events": {"KnowledgeQueryStartedEvent": 14},
            },
        )
        drive(exporter, recorder.frames)
        run_span = by_role(backend.observations, "run")[0]
        self.assertEqual(
            {"KnowledgeQueryStartedEvent": 14},
            run_span.metadata["unhandled_event_counts"],
        )
