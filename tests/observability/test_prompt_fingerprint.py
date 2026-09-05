"""Definition of Done row B5: which PROMPT produced a bad output.

The row asks that a generation carry "a stable prompt fingerprint" under the
default content policy, so a bad output can be traced to a specific
task+agent+model+prompt-version without the prompt being stored. What shipped
first fingerprinted the IDENTITY - `node|agent_role|task_name|model` - which is
honest about itself (`prompt_fingerprint_basis` said so) and cannot answer the
question: it is constant across every call an agent makes on a task and across
every revision of the prompt, so two different prompts hash identically.

The fix spans two modules and this file covers the join, because the join is
where it could go wrong quietly:

* `events/serializer.py::prompt_digest` hashes `LLMCallStartedEvent.messages`
  and puts the hash and two counts on the LLM `before` frame. It has to be
  there: CrewAI hands the rendered messages to the provider and keeps nothing,
  so no code downstream of the frame pipeline can hash something no frame
  carries.
* the exporter copies those three fields onto the generation and records
  `prompt_fingerprint_basis: "messages"`, falling back to the identity hash -
  and SAYING so - only when the frame carried none.

The tests below drive the real `FieldBoundedSerializer` over a real
`LLMCallStartedEvent`, not a lookalike, because the field being read is the
event's own and a double would be asserting against this file's idea of it.
"""

from __future__ import annotations

import unittest

from crewai.events import LLMCallStartedEvent

from brief_crew.events.models import FrameKind, UIEventType
from brief_crew.events.serializer import FieldBoundedSerializer, prompt_digest
from brief_crew.events.registry import NodeRegistry
from tests.observability.replay import Recorder, by_role, drive, exporter_for


MESSAGES = [
    {"role": "system", "content": "You check claims against primary sources."},
    {"role": "user", "content": "Check the five claims in the attached brief."},
]


class PromptDigestTests(unittest.TestCase):
    """The hash itself: stable, sensitive, and empty-handed about content."""

    def test_the_same_messages_hash_the_same_and_carry_the_counts(self) -> None:
        first = prompt_digest(MESSAGES)
        second = prompt_digest(
            [dict(message) for message in MESSAGES]  # a fresh structure, same words
        )
        self.assertEqual(first, second)
        self.assertEqual(2, first["message_count"])
        self.assertEqual(
            sum(len(message["content"]) for message in MESSAGES),
            first["prompt_chars"],
        )
        self.assertEqual(64, len(first["prompt_fingerprint"]))

    def test_one_word_of_difference_changes_the_hash(self) -> None:
        """The property the identity fingerprint did not have.

        Same node, same role, same task, same model, one word of prompt
        different: the old basis returned the same 64 characters for both, so
        "which prompt produced this" had one answer for every call an agent
        ever made.
        """

        changed = [dict(MESSAGES[0]), {**MESSAGES[1], "content": "Check four claims."}]
        self.assertNotEqual(
            prompt_digest(MESSAGES)["prompt_fingerprint"],
            prompt_digest(changed)["prompt_fingerprint"],
        )

    def test_reordering_the_same_messages_changes_the_hash(self) -> None:
        """"role + content, IN ORDER" - a conversation is not a set."""

        self.assertNotEqual(
            prompt_digest(MESSAGES)["prompt_fingerprint"],
            prompt_digest(list(reversed(MESSAGES)))["prompt_fingerprint"],
        )

    def test_a_bare_string_prompt_is_hashed_too(self) -> None:
        """`messages` is `str | list[dict] | None` on the event, not just a list."""

        digest = prompt_digest("a single rendered prompt")
        self.assertEqual(1, digest["message_count"])
        self.assertEqual(len("a single rendered prompt"), digest["prompt_chars"])

    def test_a_multimodal_content_list_is_read_one_level_and_no_further(self) -> None:
        """The rule this module's class name states, kept by the fingerprint.

        A content PART that is not a string contributes its type and nothing
        else. `str()` on an unknown object runs on the capture thread inside
        the capture lock, and an object whose `__str__` reaches back into
        CrewAI would put arbitrary framework work on the one path that must do
        none.
        """

        class _Live:
            def __str__(self) -> str:  # pragma: no cover - must never be called
                raise AssertionError("the fingerprint traversed a live object")

        digest = prompt_digest(
            [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "check this"},
                        {"type": "image_url", "image_url": {"url": "data:..."}},
                        _Live(),
                    ],
                }
            ]
        )
        self.assertEqual(1, digest["message_count"])
        self.assertEqual(64, len(digest["prompt_fingerprint"]))

    def test_no_messages_produces_no_keys_at_all(self) -> None:
        """The signal the exporter reads to say "identity" instead of lying."""

        self.assertEqual({}, prompt_digest(None))
        self.assertEqual({}, prompt_digest([]))

    def test_the_content_is_not_in_what_comes_back(self) -> None:
        rendered = repr(prompt_digest(MESSAGES))
        for message in MESSAGES:
            self.assertNotIn(message["content"], rendered)
            self.assertNotIn(message["content"][:20], rendered)


class BeforeFrameTests(unittest.TestCase):
    """The real serializer over a real event, ADDITIVELY."""

    def _draft(self, **event_fields: object):
        serializer = FieldBoundedSerializer()
        event = LLMCallStartedEvent(
            model="provider/model", call_id="call-1", **event_fields
        )
        drafts = serializer.drafts(None, event, NodeRegistry())
        return dict(drafts[0].details)

    def test_the_before_frame_carries_the_hash_and_the_two_counts(self) -> None:
        details = self._draft(messages=MESSAGES)
        self.assertEqual("before", details["stage"])
        self.assertEqual(prompt_digest(MESSAGES)["prompt_fingerprint"], details["prompt_fingerprint"])
        self.assertEqual(2, details["message_count"])

    def test_the_prompt_text_never_reaches_the_frame(self) -> None:
        """The whole reason this is a hash. Contract section 8, at the source.

        A frame is served to the browser over the socket, written to the
        database, exported as NDJSON and now sent to a third-party console. The
        prompt passing through `prompt_digest` must appear in none of that, and
        the check is over the WHOLE rendered detail map rather than over the
        three new keys, because a leak that mattered would be somewhere nobody
        was looking.
        """

        rendered = repr(self._draft(messages=MESSAGES))
        for message in MESSAGES:
            self.assertNotIn(message["content"], rendered)

    def test_an_event_with_no_messages_adds_no_keys(self) -> None:
        details = self._draft()
        for key in ("prompt_fingerprint", "message_count", "prompt_chars"):
            self.assertNotIn(key, details)
        self.assertEqual({"stage", "call_id", "model"}, set(details))


class GenerationMetadataTests(unittest.TestCase):
    """What the exporter does with it, and what it does without it."""

    def _generation(self, before_extra: dict[str, object]):
        exporter, backend = exporter_for()
        recorder = Recorder()
        recorder.run_started({})
        recorder.node_started("n1", agent_role="a role", task_name="a task")
        recorder.add(
            FrameKind.LLM,
            UIEventType.MODEL_CALL,
            "n1",
            {
                "stage": "before",
                "call_id": "call-1",
                "model": "provider/model",
                "agent_role": "a role",
                "task_name": "a task",
                **before_extra,
            },
        )
        recorder.add(
            FrameKind.LLM,
            UIEventType.MODEL_CALL,
            "n1",
            {
                "stage": "utterance",
                "call_id": "call-1",
                "text": "a truncated ans",
                "truncated": True,
                "text_chars": 4096,
                "model": "provider/model",
            },
        )
        recorder.add(
            FrameKind.TOKEN,
            UIEventType.MODEL_CALL,
            "n1",
            {
                "call_id": "call-1",
                "model": "provider/model",
                "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
                "cost_usd": 0.0001,
            },
        )
        recorder.node_ended("n1")
        recorder.run_completed({})
        drive(exporter, recorder.frames)
        return by_role(backend.observations, "generation")[0]

    def test_the_fingerprint_from_the_frame_wins_and_says_what_it_is(self) -> None:
        digest = prompt_digest(MESSAGES)
        generation = self._generation(digest)
        self.assertEqual("messages", generation.metadata["prompt_fingerprint_basis"])
        self.assertEqual(
            digest["prompt_fingerprint"], generation.metadata["prompt_fingerprint"]
        )
        self.assertEqual(digest["message_count"], generation.metadata["message_count"])
        self.assertEqual(digest["prompt_chars"], generation.metadata["prompt_chars"])

    def test_without_one_the_basis_says_identity_rather_than_messages(self) -> None:
        """A fallback that cannot be mistaken for the real thing.

        The exporter still produces a fingerprint - the no-cost doubles emit a
        before-frame with no messages, so this is the ordinary synthetic run -
        but `prompt_fingerprint_basis` names the identity, and the two counts
        are present and null rather than absent so that a reader can tell them
        from an exporter that forgot to send them.
        """

        generation = self._generation({})
        self.assertEqual(
            "node|agent_role|task_name|model",
            generation.metadata["prompt_fingerprint_basis"],
        )
        self.assertTrue(generation.metadata["prompt_fingerprint"])
        self.assertIsNone(generation.metadata["message_count"])
        self.assertIsNone(generation.metadata["prompt_chars"])

    def test_the_completion_length_is_the_true_one_not_the_frames(self) -> None:
        """`completion_chars` answers "how long was the answer", not "how long
        is the field the frame was allowed to carry".

        The utterance frame's `text` is cut to `MAX_UTTERANCE_CHARS`, so
        `len(text)` reports that ceiling for every completion that reached it -
        which is precisely the long answers a reader is asking about. The
        serializer's own `text_chars` is the length before its cut.
        """

        generation = self._generation({})
        self.assertEqual(4096, generation.metadata["completion_chars"])
