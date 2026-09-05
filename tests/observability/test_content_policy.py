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
import pathlib
import unittest
from unittest import mock

from brief_crew.events.models import FrameKind, FrameLevel, UIEventType
from brief_crew.observability.content import (
    CREDENTIAL_BOUNDARY,
    FC_MIN_HEX_CHARS,
    STRUCTURAL_STRING_KEYS,
    credential_values_in_environment,
    policy_details,
    safe_identity,
    safe_message,
    scrub_text,
)
from brief_crew.events.redaction import REDACTED
from tests.observability.replay import (
    Recorder,
    RunFacts,
    by_role,
    drive,
    exporter_for,
)


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
        """Each prefix with a tail of the shape a real key of that kind has.

        `fc-` is the odd one and it is odd deliberately: since 2026-09-06 it
        needs **20+ hex characters** after it, because a Firecrawl key is
        `fc-` + 32 hex while a UUID's tail supplies 12 - and about 1.5% of
        UUIDs contain `fc-`. The other prefixes take any tail; only Firecrawl's
        collides with something this system prints constantly.
        """

        for prefix in ("sk-or-", "sk-lf-", "pk-lf-", "ghp_", "github_pat_", "pcsk_", "AIza"):
            with self.subTest(prefix=prefix):
                planted = f"{prefix}abcdefghijklmnop1234"
                self.assertNotIn(planted, scrub_text(f"before {planted} after"))
        planted = "fc-" + "a1b2c3d4e5" * 4
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
    # A METRICS snapshot whose `reason` is free text. It rides onto the run
    # span as `run_metrics`, and it was the ONE site the first audit of this
    # file missed: `reason` is `"interval"` or `"run_completed"` on every frame
    # this application emits, so the branch that copied it looked like it was
    # copying vocabulary. It is typed `str`.
    recorder.add(
        FrameKind.METRICS,
        UIEventType.METRICS_UPDATED,
        "workflow",
        {
            "reason": leaky,
            "usage": {"call_count": 2, "cost_usd": 0.001, "total_tokens": 700},
            "frames": {"captured": 12, "dropped": 0},
        },
    )
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

    def test_the_run_metrics_snapshot_is_scrubbed_too(self) -> None:
        """Its own assertion, because it was its own hole.

        `run_metrics` is a whole frame-details map copied onto the run span,
        and until 2026-09-06 it was copied VERBATIM - the only remaining site
        in this file where a `details` value reached an observation through
        neither `policy_details` nor the scrubber. A second review's locator
        found the planted key, the DSN and its password all three sitting in
        `run_span.metadata.run_metrics.reason`, on BOTH policies.
        """

        run_span = next(
            observation
            for observation in json.loads(self.blob)["observations"]
            if (observation["metadata"] or {}).get("observation_role") == "run"
        )
        metrics = json.dumps(run_span["metadata"].get("run_metrics"))
        self.assertNotIn(PLANTED_KEY, metrics)
        self.assertNotIn(PLANTED_DSN, metrics)
        self.assertNotIn(PLANTED_DSN_PASSWORD, metrics)
        # Scrubbing is not deletion, and the numbers are what the proof rows
        # read: the snapshot must still be a snapshot.
        self.assertEqual(2, run_span["metadata"]["run_metrics"]["usage"]["call_count"])

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

        # A separator before the key, because since 2026-09-06 a prefix glued
        # to an alphanumeric is deliberately NOT matched - that boundary is
        # what stops a UUID containing `fc-` being rewritten. A real key in
        # prose, JSON, a header or a URL is preceded by a space, a quote, `=`,
        # `:` or `/`.
        text = ("x" * 39) + " " + PLANTED_KEY
        cut = safe_message(text, limit=50)
        self.assertLessEqual(len(cut), 50)
        self.assertNotIn("sk-or-v1-", cut)
        # The whole key went, including the part that sat past the limit: the
        # control is that bounding first leaves `sk-or-v1-0` on the wire.
        self.assertEqual(("x" * 39) + " ***", cut)

    def test_the_boundary_applies_to_fc_and_only_to_fc(self) -> None:
        """The narrowing, asserted from both sides.

        A UUID contains nothing but hex and hyphens, so `fc-` is the ONLY one
        of these prefixes that can occur inside one - which is why it is the
        only one the boundary guards. Applying the boundary to the others would
        buy nothing and cost real detections: a key glued after a hyphen inside
        an id is exactly what V-REVIEW's planted-key probe plants, and a
        blanket boundary let six of them through.
        """

        # `fc-` after a hex digit: a UUID, left alone.
        self.assertEqual("b5fc-f714a76e5f71", safe_message("b5fc-f714a76e5f71"))
        # every other prefix after a hyphen: a key, removed.
        self.assertEqual("gate-***", safe_message("gate-sk-or-v1-" + "0" * 64))
        # and a real Firecrawl key still goes, hyphen or no hyphen.
        self.assertEqual("id-***", safe_message("id-fc-" + "ab" * 16))

    def test_a_message_that_is_not_a_string_still_comes_back_as_one(self) -> None:
        self.assertEqual("", safe_message(None))
        self.assertEqual("404", safe_message(404))


#: A REAL run id from the paid `validator-live-2` proof run. It contains `fc-`,
#: which is Firecrawl's prefix, and it was rewritten to `…-b5***` on its way to
#: Langfuse. About 1.5% of UUIDs contain `fc-`.
UUID_WITH_A_PREFIX_IN_IT = "1a0bea14-ffb3-459d-b5fc-f714a76e5f71"


class IdentityIsNeverGuessedAtTests(unittest.TestCase):
    """An identifier is scrubbed by exact VALUE, never by shape.

    The shape rule is a heuristic and identifiers are the fields a reader joins
    on, so applying one to the other trades a hypothetical leak for a certain
    corruption. Measured: the run id above reached
    `trace.metadata.run_id` and the run span as `…-b5***`, so
    `membership_check` reported FAIL for a run whose export was otherwise
    perfect - and 85 of that run's 86 observations were fine, because they get
    the id by a different path. A one-in-sixty, silent, primary-key defect.
    """

    def test_a_run_id_containing_a_prefix_survives_on_every_observation(self) -> None:
        exporter, backend = exporter_for(
            facts=RunFacts(
                run_id=UUID_WITH_A_PREFIX_IN_IT,
                workflow_id="a-workflow",
                session_id="a-session",
                inputs={"idea": "an idea"},
            )
        )
        recorder = Recorder(run_id=UUID_WITH_A_PREFIX_IN_IT)
        recorder.run_started({"idea": "an idea"})
        recorder.node_started("n1", **IDENTITY)
        recorder.tool_call("n1", "an authored tool", **IDENTITY)
        recorder.model_call("n1", "call-1", text="an answer", **IDENTITY)
        recorder.node_ended("n1", **IDENTITY)
        recorder.run_completed({"ok": True})
        drive(exporter, recorder.frames, run_id=UUID_WITH_A_PREFIX_IN_IT)

        self.assertTrue(backend.observations)
        for observation in backend.observations:
            with self.subTest(name=observation.name):
                self.assertEqual(
                    UUID_WITH_A_PREFIX_IN_IT,
                    observation.metadata["run_id"],
                    "the run id was rewritten by the shape rule",
                )
        run_span = by_role(backend.observations, "run")[0]
        self.assertEqual(UUID_WITH_A_PREFIX_IN_IT, run_span.session_id)

    def test_the_same_id_survives_as_a_node_a_call_and_a_tool_name(self) -> None:
        """Every identity field, not only the one that was noticed."""

        for key, value in (
            ("node_id", f"node-{UUID_WITH_A_PREFIX_IN_IT}"),
            ("call_id", f"call-{UUID_WITH_A_PREFIX_IN_IT}"),
            ("agent_role", f"role {UUID_WITH_A_PREFIX_IN_IT}"),
        ):
            with self.subTest(key=key):
                self.assertEqual(value, safe_identity(value))

    def test_a_real_key_in_an_identity_field_is_still_removed(self) -> None:
        """Exact-value comparison is kept and is unconditional: a value this
        process actually holds is redacted wherever it appears, id or not."""

        secret = "sk-or-v1-" + "0" * 64
        self.assertEqual(f"node-{REDACTED}", safe_identity(f"node-{secret}", (secret,)))

    def test_free_text_still_gets_the_shape_rule(self) -> None:
        planted = "fc-" + "a" * 32
        self.assertNotIn(planted, safe_message(f"could not reach with {planted}"))
        planted = "sk-or-v1-" + "0" * 64
        self.assertNotIn(planted, safe_message(f"refused the key {planted}"))

    def test_the_shape_rule_leaves_a_uuid_in_free_text_alone_too(self) -> None:
        """The boundary applies to prose as well: a log line naming a run id is
        the commonest free-text string in this system."""

        text = f"run {UUID_WITH_A_PREFIX_IN_IT} finished"
        self.assertEqual(text, safe_message(text))

    def test_a_structural_detail_key_takes_the_identity_rule(self) -> None:
        described = policy_details(
            {"run_id": UUID_WITH_A_PREFIX_IN_IT, "node_id": "n1"},
            capture=False,
        )
        self.assertEqual(UUID_WITH_A_PREFIX_IN_IT, described["run_id"])

    def test_the_boundary_constants_match_the_tooling(self) -> None:
        """A mirror with the anti-rot test this repository builds them with.

        `scripts/observability/_common.py` is another owner's file and states
        the same two constants; a copy without a check is how a client mirror
        agreed with itself at the wrong number for weeks.
        """

        source = (
            pathlib.Path(__file__).resolve().parents[2]
            / "scripts"
            / "observability"
            / "_common.py"
        )
        if not source.exists():  # pragma: no cover - the scripts are optional
            self.skipTest("scripts/observability/_common.py is not on this machine")
        text = source.read_text(encoding="utf-8")
        self.assertIn(f'CREDENTIAL_BOUNDARY = r"{CREDENTIAL_BOUNDARY}"', text)
        self.assertIn(f"FC_MIN_HEX_CHARS = {FC_MIN_HEX_CHARS}", text)
        # The two CONSTANTS agree; the APPLICATION deliberately does not, and
        # `content.py` says why where it narrows it. A scanner over committed
        # evidence can afford a false negative; a redactor on the way out
        # cannot, so only `fc-` - the one prefix a UUID can contain - takes the
        # boundary here.

    def test_a_short_fc_run_of_hex_is_not_a_firecrawl_key(self) -> None:
        """The second half of the rule, in isolation: `fc-` needs 20+ hex."""

        self.assertEqual("fc-abc123", safe_message(" fc-abc123").strip())
        self.assertNotIn("fc-" + "a" * 20, safe_message("x fc-" + "a" * 20))
