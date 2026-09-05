"""V-REVIEW's INDEPENDENT E3 planted-credential probe (second pass, 2026-09-06).

Not a committed test. It is the repeat of the first pass's measured leak, driven
through the REAL exporter with the in-memory `RecordingBackend`, and it is
deliberately WIDER than `tests/observability/test_content_policy.py`:

  * both policies (capture off, the default; and capture on)
  * a fake OpenRouter key  `sk-or-v1-<64 chars>`  and a fake DSN
    `postgresql://user:pass@host/db`, both planted in EVERY carrier the exporter
    can put text into: the run's inputs, a node error, an agent/task error, a
    model-call error, a tool error, a tool's args/query/notes, the LLM
    utterance, a guardrail message, a gate id, an unknown-kind frame's details,
    a METRICS snapshot's free-text `reason` (which rides onto the run span as
    `run_metrics`), and a terminal cancelled frame's `reason`
  * the assertion is over the WHOLE captured payload - every observation with
    its metadata and its parent chain, every score, the trace output - not over
    a chosen field

Nothing in this file is a credential. The key is `sk-or-v1-` followed by 64
zeros and the DSN's password is the literal string `not-a-real-password`;
neither authenticates against anything.

Usage:  ./.venv/Scripts/python.exe docs/observability/evidence/tests/e3_planted_key_probe.py
"""

from __future__ import annotations

import dataclasses
import json
import os
from pathlib import Path
import sys
from unittest import mock


REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))

from brief_crew.events.models import FrameKind, FrameLevel, UIEventType  # noqa: E402
from tests.observability.replay import Recorder, drive, exporter_for  # noqa: E402


KEY = "sk-or-v1-" + "0" * 64
DSN = "postgresql://studio:not-a-real-password@127.0.0.1:5432/validator"
DSN_PASSWORD = "not-a-real-password"
IDEA = "a lopsided orrery for counting rainfall in disused lighthouses"

LEAKY = f"ConnectionError: {DSN} refused, and the provider echoed {KEY}"


def build_frames() -> Recorder:
    recorder = Recorder()
    recorder.run_started({"idea": f"{IDEA} {KEY} {DSN}"})
    recorder.node_started("n1", agent_role="a role", task_name="a task")

    # A tool whose arguments, query and notes all carry both plants, and which
    # then raises with both in the error text.
    recorder.tool_call(
        "n1",
        "a tool",
        args={"query": IDEA, "note": KEY, "dsn": DSN},
        error=LEAKY,
        agent_role="a role",
        task_name="a task",
    )
    # A model call that fails with both in the error text.
    recorder.model_call_failed(
        "n1", "c1", error=LEAKY, agent_role="a role", task_name="a task"
    )
    # A model call that succeeds and says both out loud.
    recorder.model_call(
        "n1",
        "c2",
        text=f"I used {KEY} against {DSN} for {IDEA}",
        agent_role="a role",
        task_name="a task",
    )
    # A guardrail whose message carries both.
    recorder.add(
        FrameKind.GUARDRAIL,
        UIEventType.GUARDRAIL_CHECK,
        "n1",
        {
            "stage": "after",
            "guardrail": f"check citing {KEY}",
            "success": False,
            "retry_count": 1,
            "feedback": f"{IDEA} {DSN}",
            "agent_role": "a role",
            "task_name": "a task",
        },
        level=FrameLevel.WARNING,
        message=LEAKY,
    )
    # A gate whose id carries the key.
    recorder.gate_opened("n1", f"gate-{KEY}")
    # A frame kind this exporter has never seen, with both plants in details
    # and in the frame message.
    unknown = recorder.add(
        FrameKind.NODE_STATE,
        UIEventType.NODE_START,
        "n1",
        {"anything": f"{IDEA} {KEY} {DSN}", "reason": LEAKY},
        message=LEAKY,
    )
    object.__setattr__(unknown, "kind", _UnknownKind("teleport"))
    # The node itself errors with both.
    recorder.add(
        FrameKind.NODE_STATE,
        UIEventType.NODE_END,
        "n1",
        {"stage": "error", "error": LEAKY, "error_class": "ConnectionError",
         "agent_role": "a role", "task_name": "a task"},
        level=FrameLevel.ERROR,
    )
    # A metrics snapshot with a free-text reason: this rides onto the run span
    # as `run_metrics`, and the first pass recorded it as unscrubbed.
    recorder.add(
        FrameKind.METRICS,
        UIEventType.METRICS_UPDATED,
        "workflow",
        {
            "usage": {"call_count": 2},
            "frames": {"emitted": 12},
            "reason": LEAKY,
        },
    )
    return recorder


class _UnknownKind:
    def __init__(self, value: str) -> None:
        self.value = value


def payload_of(backend) -> str:
    """Everything the backend was asked to send, as one string."""

    def clean(value):
        if dataclasses.is_dataclass(value):
            return {k: clean(v) for k, v in dataclasses.asdict(value).items()}
        if isinstance(value, dict):
            return {str(k): clean(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [clean(v) for v in value]
        return value

    return json.dumps(
        {
            "observations": [clean(o) for o in backend.observations],
            "scores": clean(list(backend.scores)),
            "trace_output": clean(getattr(backend, "trace_output", None)),
        },
        default=str,
    )


def probe(capture: bool, terminal: str) -> tuple[str, list[str]]:
    from brief_crew.observability.content import credential_values_in_environment

    with mock.patch.dict(os.environ, {"DATABASE_URL": DSN}, clear=False):
        secrets = credential_values_in_environment()
        exporter, backend = exporter_for(
            capture_content=capture, secret_values=secrets
        )
        recorder = build_frames()
        if terminal == "cancelled":
            recorder.run_cancelled(reason=LEAKY)
        elif terminal == "failed":
            recorder.run_failed(LEAKY, error_class="ConnectionError")
        else:
            recorder.run_completed({"markdown_body": f"{IDEA} {KEY}"})
        drive(exporter, recorder.frames)
        blob = payload_of(backend)

    leaks: list[str] = []
    if KEY in blob:
        leaks.append("KEY")
    if DSN in blob:
        leaks.append("DSN")
    if DSN_PASSWORD in blob:
        leaks.append("DSN_PASSWORD")
    if not capture and IDEA in blob:
        leaks.append("IDEA (default policy must withhold user text)")
    return blob, leaks


def where(blob: str, needle: str) -> list[str]:
    """Which observation names carry the needle, for a readable failure."""

    found: list[str] = []
    data = json.loads(blob)
    for observation in data["observations"]:
        if needle in json.dumps(observation, default=str):
            found.append(
                f"{observation.get('as_type')} {observation.get('name')!r} "
                f"status_message={str(observation.get('status_message'))[:80]!r}"
            )
    if needle in json.dumps(data.get("trace_output"), default=str):
        found.append("trace_output")
    if needle in json.dumps(data.get("scores"), default=str):
        found.append("scores")
    return found


def main() -> int:
    print("=" * 72)
    print("E3 PLANTED-CREDENTIAL PROBE")
    print("=" * 72)
    print(f"planted key      : sk-or-v1- + 64 zeros  (len {len(KEY)})")
    print(f"planted DSN      : {DSN}")
    print(f"planted idea text: {IDEA!r}")
    print()

    failures = 0
    for capture in (False, True):
        for terminal in ("failed", "cancelled", "completed"):
            blob, leaks = probe(capture, terminal)
            label = f"capture_content={int(capture)} terminal={terminal:<9}"
            if leaks:
                failures += 1
                print(f"LEAK  {label}  {leaks}")
                for needle, name in ((KEY, "KEY"), (DSN, "DSN"), (DSN_PASSWORD, "PW")):
                    if needle in blob:
                        for place in where(blob, needle):
                            print(f"        {name} in {place}")
            else:
                print(f"clean {label}  payload {len(blob)} chars")

    # The control: the probe would notice a leak if there were one.
    print("\ncontrol - the same search over an UNSCRUBBED string:")
    print(f"   KEY in a raw message           : {KEY in LEAKY}")
    print(f"   DSN password in a raw message  : {DSN_PASSWORD in LEAKY}")

    print("\nRESULT:", "CLEAN" if failures == 0 else f"{failures} LEAKING CONDITIONS")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
