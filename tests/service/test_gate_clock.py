"""A gate's clock is UTC even when CrewAI's is not.

CrewAI 1.15.18 stamps `PendingFeedbackContext.requested_at` with a NAIVE
`datetime.now()` - the host's local time - and the registry used to label it
UTC. Found by the teaching evaluation loop on a UTC+8 machine: every gate's
`opened_at` and `expires_at` was stored eight hours in the future and hotspots
reported a median wait of -28,798 s
(`docs/observability/TEACHING-EVAL-LOOP.md` section 5).

A CI runner's clock IS UTC, where the old mislabelling and the correct
conversion agree, so these tests pin the zone explicitly: they stamp a context
the way a UTC+8 (and a UTC-5) host would, and patch the helper to know it.
Reverting any call site to the raw value makes them fail on any runner.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from functools import partial
from unittest.mock import patch

from crewai.flow.async_feedback.types import PendingFeedbackContext

from brief_crew.service import registry
from brief_crew.service.registry import (
    RunRegistry,
    _crewai_clock_utc,
    _gate_deadline,
)

SINGAPORE = timezone(timedelta(hours=8))
NEW_YORK = timezone(timedelta(hours=-5))


def _stamped_on(zone: timezone) -> tuple[datetime, datetime]:
    """(the naive value CrewAI would write on a host in `zone`, the true UTC now)."""

    true_now = datetime.now(timezone.utc).replace(microsecond=0)
    return true_now.astimezone(zone).replace(tzinfo=None), true_now


class CrewaiClockTests(unittest.TestCase):
    def test_a_naive_local_stamp_east_of_utc_becomes_the_true_instant(self) -> None:
        naive, true_now = _stamped_on(SINGAPORE)
        self.assertEqual(true_now, _crewai_clock_utc(naive, local_tz=SINGAPORE))

    def test_a_naive_local_stamp_west_of_utc_becomes_the_true_instant(self) -> None:
        naive, true_now = _stamped_on(NEW_YORK)
        self.assertEqual(true_now, _crewai_clock_utc(naive, local_tz=NEW_YORK))

    def test_an_aware_value_is_converted_not_relabelled(self) -> None:
        aware = datetime(2026, 9, 27, 15, 0, tzinfo=SINGAPORE)
        self.assertEqual(
            datetime(2026, 9, 27, 7, 0, tzinfo=timezone.utc),
            _crewai_clock_utc(aware),
        )

    def test_the_default_reads_a_naive_value_as_this_hosts_local_time(self) -> None:
        # What `datetime.now()` wrote on THIS host must come back as now, in
        # UTC, whatever zone the host is in.
        converted = _crewai_clock_utc(datetime.now())
        self.assertLess(
            abs((converted - datetime.now(timezone.utc)).total_seconds()), 5
        )


class GatePromptExpiryTests(unittest.TestCase):
    """The deadline a gate is served with, from a context stamped off-UTC."""

    def _prompt_deadline(self, zone: timezone) -> tuple[datetime, datetime]:
        naive, true_now = _stamped_on(zone)
        context = PendingFeedbackContext(
            flow_id="flow-1",
            flow_class="Flow",
            method_name="confirm_scope",
            method_output={"idea": "x"},
            message="Confirm",
            requested_at=naive,
        )
        with patch.object(
            registry, "_crewai_clock_utc", partial(_crewai_clock_utc, local_tz=zone)
        ):
            prompt = RunRegistry._gate_prompt("run-1", context)
        return _gate_deadline(prompt), true_now

    def test_the_deadline_is_the_timeout_after_the_true_opening_east(self) -> None:
        deadline, true_now = self._prompt_deadline(SINGAPORE)
        wait = (deadline - true_now).total_seconds()
        self.assertEqual(registry.VALIDATOR_GATE_TIMEOUT_SECONDS, wait)

    def test_the_deadline_is_not_in_the_past_west_of_utc(self) -> None:
        # The dangerous direction: labelled UTC, a New York stamp is five hours
        # early, and a thirty-minute gate would be born expired.
        deadline, true_now = self._prompt_deadline(NEW_YORK)
        self.assertGreater(deadline, true_now)
        self.assertEqual(
            registry.VALIDATOR_GATE_TIMEOUT_SECONDS,
            (deadline - true_now).total_seconds(),
        )

    def test_the_gate_id_still_hashes_the_raw_stamp(self) -> None:
        # A restart replays the pending context and must mint the same id.
        naive, _ = _stamped_on(SINGAPORE)
        context = PendingFeedbackContext(
            flow_id="flow-1",
            flow_class="Flow",
            method_name="confirm_scope",
            method_output={},
            message="Confirm",
            requested_at=naive,
        )
        first = RunRegistry._gate_prompt("run-1", context)["gate_id"]
        with patch.object(
            registry,
            "_crewai_clock_utc",
            partial(_crewai_clock_utc, local_tz=SINGAPORE),
        ):
            second = RunRegistry._gate_prompt("run-1", context)["gate_id"]
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
