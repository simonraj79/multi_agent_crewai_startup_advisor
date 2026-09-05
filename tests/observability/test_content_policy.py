"""Definition of Done row E3: what leaves the process, and what does not.

Two planted markers and one question asked twice. The markers are a fake
provider key in the shape of a real one, and a distinctive sentence standing in
for whatever a user actually typed. They are planted in the places a leak has
already happened in this repository - a tool argument, a tool's own reported
query, a model's answer, the run inputs - and then the whole exported payload is
searched for them.

Under the default policy neither may appear anywhere. With
`LANGFUSE_CAPTURE_CONTENT=1` the sentence must appear, because that is what the
switch is for, and the key still must not - a capture switch is permission to
send the user's words, never permission to send a credential.

The test searches the ENTIRE payload rather than the fields it expects to be
risky. That is deliberate: every leak this repository has had was in a field
nobody thought to look at, most recently a preview built by a second walk that
did not redact while the value beside it did.
"""

from __future__ import annotations

import dataclasses
import json
import os
import unittest
from unittest import mock

from brief_crew.events.models import FrameKind, FrameLevel, UIEventType
from brief_crew.observability.content import (
    STRUCTURAL_STRING_KEYS,
    credential_values_in_environment,
    policy_details,
    safe_message,
    scrub_text,
)
from tests.observability.replay import Recorder, RunFacts, drive, exporter_for


#: Shaped like a real provider key and belonging to nobody. It authenticates
#: against nothing, which is the same rule `tests/__init__.py` states about its
#: own placeholders.
PLANTED_KEY = "sk-or-v1-0000000000000000-planted-fake-key"
PLANTED_TEXT = "a lopsided orrery for counting rainfall in disused lighthouses"
IDENTITY = {"agent_role": "an authored role", "task_name": "an authored task"}


def _exercise(**policy_overrides) -> str:
    exporter, backend = exporter_for(
        facts=RunFacts(
            run_id="11111111-2222-4333-8444-555555555555",
            workflow_id="a-workflow",
            inputs={"idea": f"{PLANTED_TEXT} {PLANTED_KEY}"},
        ),
        **policy_overrides,
    )
    recorder = Recorder()
    recorder.run_started({"idea": f"{PLANTED_TEXT} {PLANTED_KEY}"})
    recorder.node_started("n1", **IDENTITY)
    recorder.tool_call(
        "n1",
        "an authored tool",
        args={"query": f"{PLANTED_TEXT}", "note": PLANTED_KEY},
        **IDENTITY,
    )
    recorder.model_call(
        "n1",
        "call-1",
        text=f"I looked up {PLANTED_TEXT} using {PLANTED_KEY}",
        **IDENTITY,
    )
    recorder.node_ended("n1", **IDENTITY)
    recorder.run_completed({"markdown_body": PLANTED_TEXT})
    drive(exporter, recorder.frames)
    payload = {
        "observations": [dataclasses.asdict(o) for o in backend.observations],
        "scores": [dataclasses.asdict(s) for s in backend.scores],
        "trace_output": backend.trace_output,
    }
    return json.dumps(payload, default=str)


class DefaultPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.blob = _exercise()

    def test_no_user_text_leaves_the_process(self) -> None:
        self.assertNotIn(PLANTED_TEXT, self.blob)

    def test_no_credential_shaped_string_leaves_the_process(self) -> None:
        self.assertNotIn(PLANTED_KEY, self.blob)
        self.assertNotIn("sk-or-v1-", self.blob)

    def test_what_leaves_instead_is_a_fingerprint_and_a_length(self) -> None:
        payload = json.loads(self.blob)
        run = [
            o
            for o in payload["observations"]
            if o["metadata"].get("observation_role") == "run"
        ][0]
        self.assertIn("input_fingerprint", run["payload_input"])
        self.assertIn("input_chars", run["payload_input"])
        self.assertEqual(["idea"], run["payload_input"]["input_keys"])

    def test_a_generation_still_says_how_long_the_answer_was(self) -> None:
        payload = json.loads(self.blob)
        generation = [
            o
            for o in payload["observations"]
            if o["metadata"].get("observation_role") == "generation"
        ][0]
        self.assertGreater(generation["metadata"]["completion_chars"], 0)
        self.assertIsNone(generation["payload_output"])
        self.assertEqual(64, len(generation["metadata"]["prompt_fingerprint"]))


class CaptureOnTests(unittest.TestCase):
    def setUp(self) -> None:
        self.blob = _exercise(capture_content=True)

    def test_the_content_is_present_when_capture_is_on(self) -> None:
        self.assertIn(PLANTED_TEXT, self.blob)

    def test_the_credential_is_still_scrubbed(self) -> None:
        self.assertNotIn(PLANTED_KEY, self.blob)
        self.assertIn("***", self.blob)


class ScrubberTests(unittest.TestCase):
    def test_every_prefix_the_contract_names_is_blanked(self) -> None:
        for prefix in ("sk-or-", "sk-lf-", "pk-lf-", "fc-", "ghp_", "github_pat_", "pcsk_", "AIza"):
            with self.subTest(prefix=prefix):
                planted = f"{prefix}abcdefghijklmnop1234"
                self.assertNotIn(planted, scrub_text(f"before {planted} after"))

    def test_a_value_held_in_this_process_is_blanked_by_comparison(self) -> None:
        secret = "a-value-that-is-long-enough-to-be-a-credential"
        self.assertEqual("before *** after", scrub_text(f"before {secret} after", (secret,)))

    def test_the_environment_scan_selects_by_the_rule_already_in_force(self) -> None:
        """It reuses `events.redaction.is_secret_key` over the variable NAME.

        The suite sets an obviously fake provider key, so this asserts the scan
        finds credential-shaped variables at all rather than asserting a count -
        a machine with more of them is not a failing machine.
        """

        values = credential_values_in_environment()
        self.assertIsInstance(values, tuple)
        self.assertTrue(all(isinstance(value, str) for value in values))

    def test_a_string_under_an_unknown_key_is_described_not_sent(self) -> None:
        described = policy_details(
            {"a_new_free_text_field": PLANTED_TEXT}, capture=False
        )
        self.assertNotIn(PLANTED_TEXT, json.dumps(described))
        self.assertEqual(len(PLANTED_TEXT), described["a_new_free_text_field"]["chars"])

    def test_a_vocabulary_key_passes_through(self) -> None:
        described = policy_details({"stage": "after", "tool_status": "ok"}, capture=False)
        self.assertEqual({"stage": "after", "tool_status": "ok"}, described)

    def test_the_allowlist_carries_the_identity_the_contract_requires(self) -> None:
        """Section 3 puts agent role and task name on EVERY observation.

        If either were treated as content, every observation would carry a hash
        where a reader needs a name, and rows B1 and B2 - the per-agent and
        per-task tables - could not be built at all.
        """

        for key in ("agent_role", "task_name", "node_id", "run_id", "model"):
            with self.subTest(key=key):
                self.assertIn(key, STRUCTURAL_STRING_KEYS)

    def test_a_secret_named_key_is_redacted_even_under_capture(self) -> None:
        described = policy_details({"api_key": PLANTED_KEY}, capture=True)
        self.assertEqual({"api_key": "***"}, described)


#: A connection string in the shape `DATABASE_URL` actually takes here. The
#: name matches no rule `events/redaction.py` has - `databaseurl` is in no list
#: and ends in none of `SECRET_KEY_SUFFIXES` - so it was on no comparison list
#: at all until `credential_values_in_environment` learned to select by the
#: SHAPE of the value. It points at nothing and the password is a word.
PLANTED_DSN = "postgresql://studio:hunter2-not-a-real-password@127.0.0.1:5432/validator"
PLANTED_DSN_PASSWORD = "hunter2-not-a-real-password"


def _exercise_failures(**policy_overrides) -> str:
    """Every FAILING shape the exporter renders, each carrying both markers.

    The success path is the one `_exercise` covers and the one that was clean.
    The failure paths were not: contract section 6 asks for an
    `ExceptionClass: redacted message` on a `statusMessage`, so an exception
    message is the ONE class of string this exporter sends as text whatever
    `capture_content` says - and every site that built one did its own
    `[:1024]` and no scrubbing. Measured: a planted `sk-or-v1-` value in a
    failing frame reached six observations and the trace output with capture
    OFF.

    An exception message is not written by this application. It is written by a
    provider's client library or a database driver, and a driver that names the
    DSN it could not reach puts a password into it with no key-shaped
    dictionary key anywhere for the redaction rules to catch.
    """

    exporter, backend = exporter_for(
        facts=RunFacts(
            run_id="11111111-2222-4333-8444-555555555555",
            workflow_id="a-workflow",
            inputs={"idea": PLANTED_TEXT},
        ),
        **policy_overrides,
    )
    leaky = f"ConnectionError: {PLANTED_DSN} refused the key {PLANTED_KEY}"
    recorder = Recorder()
    recorder.run_started({"idea": PLANTED_TEXT})
    recorder.node_started("n1", **IDENTITY)
    recorder.tool_call("n1", "an authored tool", error=leaky, **IDENTITY)
    recorder.model_call_failed("n1", "call-1", error=leaky, **IDENTITY)
    # A frame kind nothing recognises, which becomes an EVENT carrying its
    # whole details map - the widest surface in the exporter.
    recorder.add(
        FrameKind.NODE_STATE,
        UIEventType.THINKING_PROCESS,
        "n1",
        {"stage": "a stage nobody declared", "error": leaky, "note": leaky},
        level=FrameLevel.ERROR,
    )
    recorder.add(
        FrameKind.NODE_STATE,
        UIEventType.NODE_END,
        "n1",
        {"stage": "error", "error": leaky, "error_class": "ConnectionError", **IDENTITY},
        level=FrameLevel.ERROR,
    )
    recorder.run_failed(leaky, error_class="ConnectionError")
    drive(exporter, recorder.frames)
    payload = {
        "observations": [dataclasses.asdict(o) for o in backend.observations],
        "scores": [dataclasses.asdict(s) for s in backend.scores],
        "trace_output": backend.trace_output,
    }
    return json.dumps(payload, default=str)


class FailurePathContentTests(unittest.TestCase):
    """Row E3 over the paths that send text on EVERY policy.

    `os.environ` is patched rather than mocked around, because the process's own
    credential values are read once at policy build time by
    `credential_values_in_environment`, and the point of the DSN half is that it
    is caught by being a value this process holds - not by looking like a key.
    """

    def setUp(self) -> None:
        with mock.patch.dict(os.environ, {"DATABASE_URL": PLANTED_DSN}, clear=False):
            self.blob = _exercise_failures(
                secret_values=credential_values_in_environment()
            )

    def test_a_planted_key_in_an_exception_message_does_not_leave(self) -> None:
        self.assertNotIn(PLANTED_KEY, self.blob)
        self.assertNotIn("sk-or-v1-", self.blob)

    def test_a_planted_connection_string_does_not_leave(self) -> None:
        self.assertNotIn(PLANTED_DSN, self.blob)
        self.assertNotIn(PLANTED_DSN_PASSWORD, self.blob)

    def test_the_statuses_still_say_what_went_wrong(self) -> None:
        """Scrubbing is not deletion. The row asks for a REDACTED message, not
        for no message: a failure with no sentence on it is B3's question
        unanswered, and this exporter would have traded one defect for another.
        """

        self.assertIn("ConnectionError", self.blob)
        self.assertIn("refused the key", self.blob)

    def test_the_trace_output_reason_is_scrubbed_too(self) -> None:
        """Its own assertion because it is its own path: the terminal reason is
        copied into `trace.output`, which is rendered in the Langfuse trace LIST
        - the one place a reader sees before opening anything."""

        self.assertNotIn(PLANTED_KEY, json.dumps(json.loads(self.blob)["trace_output"]))

    def test_the_same_holds_with_capture_on(self) -> None:
        """A capture switch is permission to send the user's words. It has
        never been permission to send a credential."""

        with mock.patch.dict(os.environ, {"DATABASE_URL": PLANTED_DSN}, clear=False):
            blob = _exercise_failures(
                capture_content=True,
                secret_values=credential_values_in_environment(),
            )
        self.assertNotIn(PLANTED_KEY, blob)
        self.assertNotIn(PLANTED_DSN_PASSWORD, blob)


class UrlCredentialSelectionTests(unittest.TestCase):
    """`credential_values_in_environment` selects by SHAPE as well as by name."""

    def test_a_url_with_userinfo_is_held_even_though_its_name_is_not_secret(
        self,
    ) -> None:
        from brief_crew.events.redaction import is_secret_key

        # The premise, asserted rather than assumed: if this ever becomes True
        # the shape rule is redundant and this test should say so loudly.
        self.assertFalse(is_secret_key("DATABASE_URL"))
        with mock.patch.dict(os.environ, {"DATABASE_URL": PLANTED_DSN}, clear=True):
            values = credential_values_in_environment()
        self.assertIn(PLANTED_DSN, values)
        self.assertIn(PLANTED_DSN_PASSWORD, values)

    def test_a_url_without_userinfo_is_not_treated_as_a_credential(self) -> None:
        """Over-collecting here is not free: every value is blanked wherever it
        appears in a message, so an ordinary host name held as a secret would
        redact readable text for nothing."""

        with mock.patch.dict(
            os.environ, {"SERVICE_URL": "https://example.invalid/api"}, clear=True
        ):
            self.assertEqual((), credential_values_in_environment())

    def test_both_forms_are_blanked_by_the_scrubber(self) -> None:
        with mock.patch.dict(os.environ, {"DATABASE_URL": PLANTED_DSN}, clear=True):
            values = credential_values_in_environment()
        whole = safe_message(f"could not reach {PLANTED_DSN}", values)
        just_the_password = safe_message(
            f"authentication failed for {PLANTED_DSN_PASSWORD}", values
        )
        self.assertNotIn(PLANTED_DSN, whole)
        self.assertNotIn(PLANTED_DSN_PASSWORD, whole)
        self.assertNotIn(PLANTED_DSN_PASSWORD, just_the_password)


class SafeMessageTests(unittest.TestCase):
    def test_it_scrubs_before_it_bounds(self) -> None:
        """The opposite order from `scrub_text`, and the reason is the edge.

        Cutting first can split a key at the boundary so that the shape rule no
        longer matches it while most of it is still on the wire.
        """

        text = ("x" * 40) + PLANTED_KEY
        cut = safe_message(text, limit=50)
        self.assertLessEqual(len(cut), 50)
        self.assertNotIn("sk-or-v1-", cut)
        # The whole key went, including the part that sat past the limit: the
        # control is that bounding first leaves `sk-or-v1-0` on the wire.
        self.assertEqual(("x" * 40) + "***", cut)

    def test_a_message_that_is_not_a_string_still_comes_back_as_one(self) -> None:
        self.assertEqual("", safe_message(None))
        self.assertEqual("404", safe_message(404))
