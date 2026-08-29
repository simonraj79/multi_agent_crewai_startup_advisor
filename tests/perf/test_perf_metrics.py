"""The verdict logic must be able to say no.

These tests inject fabricated fast/slow numbers and assert the verdict flips.
A harness that cannot report a MISSED target is worthless for a decision the
PRD says may withdraw the parallel implementation (risk R-3).
"""

from __future__ import annotations

import unittest

from scripts.perf_metrics import (
    INCOMPLETE,
    MET,
    MISSED,
    TARGET_FANOUT_SPEEDUP,
    TARGET_GATE_RESUME_MS,
    TARGET_PEAK_RSS_BYTES,
    UNMEASURED,
    MemoryProbe,
    TargetResult,
    advisory_concurrency,
    advisory_overhead,
    evaluate_frame_integrity,
    evaluate_gate_latency,
    evaluate_peak_rss,
    evaluate_speedup,
    overall_status,
    render_table,
    render_verdict_block,
    summarize,
)

MB = 1024 * 1024


class SummaryTests(unittest.TestCase):
    def test_reports_median_and_full_spread_not_just_a_mean(self) -> None:
        # One slow outlier in five samples: the mean lies, the median does not.
        summary = summarize([1.0, 1.0, 1.0, 1.0, 21.0])

        assert summary is not None
        self.assertEqual(summary.count, 5)
        self.assertEqual(summary.median, 1.0)
        self.assertEqual(summary.minimum, 1.0)
        self.assertEqual(summary.maximum, 21.0)
        self.assertEqual(summary.mean, 5.0)
        self.assertEqual(summary.spread, 20.0)

    def test_even_sample_count_and_empty_input(self) -> None:
        summary = summarize([2.0, 4.0])
        assert summary is not None
        self.assertEqual(summary.median, 3.0)
        self.assertIsNone(summarize([]))


class SpeedupVerdictTests(unittest.TestCase):
    def test_fast_parallel_arm_meets_the_target(self) -> None:
        result = evaluate_speedup([6.0] * 5, [3.0] * 5)

        self.assertEqual(result.status, MET)
        self.assertEqual(result.observed, "2.000x")
        self.assertFalse(result.failed)

    def test_slow_parallel_arm_flips_the_verdict_to_missed(self) -> None:
        # Same harness, same call, only the numbers change.
        result = evaluate_speedup([6.0] * 5, [4.0] * 5)

        self.assertEqual(result.status, MISSED)
        self.assertEqual(result.observed, "1.500x")
        self.assertTrue(result.failed)

    def test_just_below_the_target_is_missed_and_never_rounded_up(self) -> None:
        result = evaluate_speedup([1.799] * 5, [1.0] * 5)

        self.assertEqual(result.status, MISSED)
        self.assertEqual(result.observed, "1.799x")

    def test_exactly_the_target_is_met(self) -> None:
        result = evaluate_speedup([TARGET_FANOUT_SPEEDUP] * 5, [1.0] * 5)

        self.assertEqual(result.status, MET)

    def test_worst_and_best_case_bounds_expose_the_spread(self) -> None:
        result = evaluate_speedup([4.0, 5.0, 6.0], [1.0, 2.0, 3.0])

        self.assertAlmostEqual(result.data["speedup_median"], 5.0 / 2.0)
        self.assertAlmostEqual(result.data["speedup_worst_case"], 4.0 / 3.0)
        self.assertAlmostEqual(result.data["speedup_best_case"], 6.0 / 1.0)

    def test_missing_arm_is_unmeasured_not_a_pass(self) -> None:
        self.assertEqual(evaluate_speedup([], [1.0]).status, UNMEASURED)
        self.assertEqual(evaluate_speedup([1.0], []).status, UNMEASURED)

    def test_advisory_speedup_never_decides_the_overall_verdict(self) -> None:
        result = evaluate_speedup([6.0], [4.0], advisory=True, advisory_reason="synthetic")

        self.assertEqual(result.status, MISSED)
        self.assertFalse(result.failed)
        self.assertIn("synthetic", result.detail)
        self.assertEqual(overall_status([result]), MET)


class PeakRssVerdictTests(unittest.TestCase):
    def test_under_budget_meets_the_target(self) -> None:
        result = evaluate_peak_rss(399 * MB, probe_name="probe")

        self.assertEqual(result.status, MET)

    def test_over_budget_flips_to_missed(self) -> None:
        result = evaluate_peak_rss(401 * MB, probe_name="probe")

        self.assertEqual(result.status, MISSED)
        self.assertTrue(result.failed)

    def test_exactly_the_budget_is_missed_because_the_target_is_strict(self) -> None:
        self.assertEqual(evaluate_peak_rss(TARGET_PEAK_RSS_BYTES).status, MISSED)

    def test_no_probe_reports_unmeasured_with_a_reason(self) -> None:
        result = evaluate_peak_rss(None, probe_name="none", reason="no API here")

        self.assertEqual(result.status, UNMEASURED)
        self.assertEqual(result.observed, "unmeasured")
        self.assertIn("no API here", result.detail)


class GateLatencyVerdictTests(unittest.TestCase):
    def test_fast_round_trips_meet_the_target(self) -> None:
        self.assertEqual(evaluate_gate_latency([40.0, 55.0, 61.0]).status, MET)

    def test_a_single_slow_round_trip_flips_the_verdict(self) -> None:
        # Judged on the worst sample: a median that hides one 900 ms gate is a lie.
        result = evaluate_gate_latency([40.0, 42.0, 900.0])

        self.assertEqual(result.status, MISSED)
        self.assertIn("900.0 ms", result.observed)

    def test_exactly_the_target_is_missed(self) -> None:
        self.assertEqual(evaluate_gate_latency([TARGET_GATE_RESUME_MS]).status, MISSED)

    def test_no_samples_is_unmeasured(self) -> None:
        self.assertEqual(evaluate_gate_latency([]).status, UNMEASURED)


class FrameIntegrityVerdictTests(unittest.TestCase):
    @staticmethod
    def clean(**overrides: object) -> dict[str, object]:
        stats = {
            "captured": 26,
            "dropped": 0,
            "gaps": 0,
            "emit_errors": 0,
            "seq_contiguous": True,
            "unpaired_nodes": 0,
        }
        stats.update(overrides)
        return stats

    def test_clean_runs_meet_the_target(self) -> None:
        result = evaluate_frame_integrity([self.clean(), self.clean()])

        self.assertEqual(result.status, MET)
        self.assertIn("0 dropped", result.observed)

    def test_one_dropped_frame_flips_the_verdict(self) -> None:
        result = evaluate_frame_integrity([self.clean(), self.clean(dropped=1)])

        self.assertEqual(result.status, MISSED)
        self.assertIn("1 dropped frames", result.observed)

    def test_a_seq_gap_flips_the_verdict(self) -> None:
        self.assertEqual(
            evaluate_frame_integrity([self.clean(gaps=2)]).status, MISSED
        )

    def test_a_non_contiguous_sequence_flips_the_verdict(self) -> None:
        self.assertEqual(
            evaluate_frame_integrity([self.clean(seq_contiguous=False)]).status, MISSED
        )

    def test_an_unpaired_node_start_flips_the_verdict(self) -> None:
        self.assertEqual(
            evaluate_frame_integrity([self.clean(unpaired_nodes=1)]).status, MISSED
        )

    def test_an_emit_error_flips_the_verdict(self) -> None:
        self.assertEqual(
            evaluate_frame_integrity([self.clean(emit_errors=1)]).status, MISSED
        )

    def test_no_runs_is_unmeasured(self) -> None:
        self.assertEqual(evaluate_frame_integrity([]).status, UNMEASURED)


class AdvisoryTests(unittest.TestCase):
    def test_concurrency_advisory_warns_when_the_fanout_never_fanned_out(self) -> None:
        result = advisory_concurrency([1, 1, 1])

        self.assertEqual(result.status, MISSED)
        self.assertTrue(result.advisory)
        self.assertFalse(result.failed)
        self.assertIn("NOT a fan-out measurement", result.detail)

    def test_concurrency_advisory_passes_at_three(self) -> None:
        self.assertEqual(advisory_concurrency([3, 3, 3]).status, MET)

    def test_overhead_is_recovered_from_both_arms(self) -> None:
        # Construct arms from a known overhead of 2.0s and 0.5s branches.
        overhead, branch = 2.0, 0.5
        result = advisory_overhead(
            [overhead + 3 * branch] * 5, [overhead + branch] * 5, (branch, branch, branch)
        )

        self.assertEqual(result.status, MET)
        self.assertTrue(result.advisory)
        self.assertAlmostEqual(result.data["overhead_seconds"], overhead, places=6)
        # B >= O(t-1)/(3-t) = 2.0 * 0.8 / 1.2
        self.assertAlmostEqual(
            result.data["required_branch_seconds_for_target"], 2.0 * 0.8 / 1.2, places=6
        )
        self.assertGreater(result.data["projected_speedup"]["30s_branches"], 2.5)

    def test_overhead_needs_three_branch_durations(self) -> None:
        self.assertEqual(advisory_overhead([3.0], [1.0], (0.5,)).status, UNMEASURED)


class OverallStatusTests(unittest.TestCase):
    @staticmethod
    def result(status: str, *, advisory: bool = False) -> TargetResult:
        return TargetResult(
            key="k", label="l", target="t", observed="o", status=status, advisory=advisory
        )

    def test_all_met_is_met(self) -> None:
        self.assertEqual(
            overall_status([self.result(MET), self.result(MET)]), MET
        )

    def test_any_missed_beats_everything(self) -> None:
        self.assertEqual(
            overall_status([self.result(MET), self.result(MISSED), self.result(UNMEASURED)]),
            MISSED,
        )

    def test_unmeasured_is_incomplete_not_a_pass(self) -> None:
        self.assertEqual(
            overall_status([self.result(MET), self.result(UNMEASURED)]), INCOMPLETE
        )

    def test_advisory_rows_are_ignored(self) -> None:
        self.assertEqual(
            overall_status([self.result(MET), self.result(MISSED, advisory=True)]), MET
        )


class RenderingTests(unittest.TestCase):
    def test_a_missed_target_is_shouted_in_both_the_table_and_the_block(self) -> None:
        results = [
            evaluate_speedup([6.0] * 5, [4.0] * 5),
            evaluate_peak_rss(100 * MB, probe_name="probe"),
        ]

        table = render_table(results)
        block = render_verdict_block(results)

        self.assertIn("*** MISSED ***", table)
        self.assertIn("OVERALL: TARGET(S) MISSED", block)
        self.assertIn("1.500x", block)
        self.assertIn("R-3", block)

    def test_a_clean_sweep_says_so_without_the_withdrawal_warning(self) -> None:
        block = render_verdict_block(
            [evaluate_speedup([6.0] * 5, [3.0] * 5), evaluate_peak_rss(1 * MB)]
        )

        self.assertIn("OVERALL: ALL TARGETS MET", block)
        self.assertNotIn("R-3", block)

    def test_an_advisory_prd_target_is_flagged_as_not_evaluated(self) -> None:
        # A synthetic pass must never read as "the 1.8x target was met".
        block = render_verdict_block(
            [
                evaluate_speedup([6.0] * 5, [4.0] * 5, advisory=True),
                evaluate_peak_rss(1 * MB),
            ]
        )

        self.assertIn("EVALUATED TARGETS MET", block)
        self.assertNotIn("OVERALL: ALL TARGETS MET", block)
        self.assertIn("NOT EVALUATED", block)

    def test_an_unmeasured_target_is_reported_as_incomplete(self) -> None:
        block = render_verdict_block([evaluate_peak_rss(None, reason="no probe")])

        self.assertIn("OVERALL: INCOMPLETE", block)
        self.assertIn("no probe", block)


class MemoryProbeTests(unittest.TestCase):
    def test_the_selected_probe_reads_a_plausible_rss_or_says_why_not(self) -> None:
        from scripts.perf_metrics import select_memory_probe

        probe = select_memory_probe()
        reading = probe.read()

        if not probe.available:
            self.assertTrue(probe.reason, "an unavailable probe must explain itself")
            return
        peak = reading.peak_bytes or reading.current_bytes
        assert peak is not None
        self.assertGreater(peak, 1 * MB)

    def test_sampler_degrades_to_unmeasured_without_a_probe(self) -> None:
        from scripts.perf_metrics import PeakMemorySampler

        with PeakMemorySampler(MemoryProbe(), interval_s=0.01) as sampler:
            pass

        self.assertIsNone(sampler.peak_bytes)
        self.assertEqual(evaluate_peak_rss(sampler.peak_bytes).status, UNMEASURED)

    def test_sampler_catches_a_peak_from_a_scripted_probe(self) -> None:
        from scripts.perf_metrics import MemoryReading, PeakMemorySampler

        class ScriptedProbe(MemoryProbe):
            name = "scripted"
            available = True
            supports_sampling = True
            reason = ""

            def __init__(self) -> None:
                self.readings = iter([10, 500, 20])

            def read(self) -> MemoryReading:
                return MemoryReading(next(self.readings, 20), None)

        sampler = PeakMemorySampler(ScriptedProbe(), interval_s=0.01)
        sampler._observe()
        sampler._observe()
        sampler._observe()

        self.assertEqual(sampler.sampled_peak_bytes, 500)
        self.assertEqual(sampler.peak_bytes, 500)

    def test_sampler_rejects_a_non_positive_interval(self) -> None:
        from scripts.perf_metrics import PeakMemorySampler

        with self.assertRaises(ValueError):
            PeakMemorySampler(MemoryProbe(), interval_s=0)


if __name__ == "__main__":
    unittest.main()
