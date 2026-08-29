"""Measurement primitives and target verdicts for the F42 performance harness.

This module is deliberately free of CrewAI imports so the verdict logic can be
unit-tested with injected numbers. Nothing in here decides *how* a run happens;
it only decides what a set of numbers means.

Design rule: a target is reported as MISSED whenever the observation fails it.
Numbers are never rounded toward a target, and an absent measurement is
reported as UNMEASURED rather than being quietly dropped.
"""

from __future__ import annotations

import ctypes
import os
import statistics
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

# --------------------------------------------------------------------------
# Targets. These mirror PRD section 13 and feature F42, and are imported from
# config.py rather than restated - the project rule is that constants live
# there, so the harness and any future acceptance gate cannot drift apart.
# The local aliases keep this module's call sites readable.
# --------------------------------------------------------------------------
from brief_crew.config import (
    VALIDATOR_PERF_RUNS_PER_ARM,
    VALIDATOR_PERF_SAMPLE_INTERVAL_S,
    VALIDATOR_PERF_TARGET_DROPPED_FRAMES,
    VALIDATOR_PERF_TARGET_FANOUT_SPEEDUP,
    VALIDATOR_PERF_TARGET_GATE_RESUME_MS,
    VALIDATOR_PERF_TARGET_PEAK_RSS_BYTES,
)

TARGET_FANOUT_SPEEDUP = VALIDATOR_PERF_TARGET_FANOUT_SPEEDUP
TARGET_PEAK_RSS_BYTES = VALIDATOR_PERF_TARGET_PEAK_RSS_BYTES
TARGET_GATE_RESUME_MS = VALIDATOR_PERF_TARGET_GATE_RESUME_MS
TARGET_DROPPED_FRAMES = VALIDATOR_PERF_TARGET_DROPPED_FRAMES
DEFAULT_RUNS_PER_ARM = VALIDATOR_PERF_RUNS_PER_ARM
DEFAULT_SAMPLE_INTERVAL_S = VALIDATOR_PERF_SAMPLE_INTERVAL_S

MET = "MET"
MISSED = "MISSED"
UNMEASURED = "UNMEASURED"
INCOMPLETE = "INCOMPLETE"

MEGABYTE = 1024 * 1024

TELEMETRY_ENV_VARS = (
    "CREWAI_DISABLE_TELEMETRY",
    "CREWAI_DISABLE_TRACKING",
    "OTEL_SDK_DISABLED",
)


def disable_crewai_telemetry() -> dict[str, str]:
    """Opt out of CrewAI's OTel exporter so a synthetic run makes no HTTP call.

    ``setdefault`` so an operator who has deliberately set one of these keeps
    control. CrewAI re-reads these on every telemetry operation, so this works
    whether or not ``crewai`` has already been imported.
    """
    for name in TELEMETRY_ENV_VARS:
        os.environ.setdefault(name, "true")
    return {name: os.environ.get(name, "") for name in TELEMETRY_ENV_VARS}


def telemetry_state() -> dict[str, str]:
    """Report what the process will actually do, without changing it."""
    return {name: os.environ.get(name, "<unset>") for name in TELEMETRY_ENV_VARS}


# --------------------------------------------------------------------------
# Statistics
# --------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class Summary:
    """Median plus the full spread, because five samples hide outliers."""

    count: int
    median: float
    minimum: float
    maximum: float
    mean: float

    @property
    def spread(self) -> float:
        return self.maximum - self.minimum

    def as_dict(self) -> dict[str, float | int]:
        return {
            "count": self.count,
            "median": self.median,
            "min": self.minimum,
            "max": self.maximum,
            "mean": self.mean,
            "spread": self.spread,
        }


def summarize(values: Sequence[float]) -> Summary | None:
    """Return median/min/max/mean, or None when there is nothing to summarize."""
    samples = [float(value) for value in values]
    if not samples:
        return None
    return Summary(
        count=len(samples),
        median=statistics.median(samples),
        minimum=min(samples),
        maximum=max(samples),
        mean=statistics.fmean(samples),
    )


# --------------------------------------------------------------------------
# Target verdicts
# --------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class TargetResult:
    """One PRD target, its observation, and an unambiguous verdict."""

    key: str
    label: str
    target: str
    observed: str
    status: str
    detail: str = ""
    advisory: bool = False
    data: Mapping[str, Any] = field(default_factory=dict)

    @property
    def failed(self) -> bool:
        return not self.advisory and self.status == MISSED

    @property
    def unmeasured(self) -> bool:
        return not self.advisory and self.status == UNMEASURED

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "target": self.target,
            "observed": self.observed,
            "status": self.status,
            "detail": self.detail,
            "advisory": self.advisory,
            "data": dict(self.data),
        }


def evaluate_speedup(
    sequential_seconds: Sequence[float],
    parallel_seconds: Sequence[float],
    *,
    target: float = TARGET_FANOUT_SPEEDUP,
    advisory: bool = False,
    advisory_reason: str = "",
) -> TargetResult:
    """Median sequential wall clock divided by median parallel wall clock.

    ``advisory=True`` is for synthetic mode, where the ratio is a function of the
    sleep durations the operator chose rather than of the system under test, so
    it must not be allowed to pass or fail the PRD target.
    """
    label = "Fan-out speedup (parallel vs sequential)"
    sequential = summarize(sequential_seconds)
    parallel = summarize(parallel_seconds)
    if sequential is None or parallel is None:
        return TargetResult(
            key="fanout_speedup",
            label=label,
            target=f">= {target:.2f}x",
            observed="n/a",
            status=UNMEASURED,
            advisory=advisory,
            detail="one or both arms produced no completed runs",
        )
    if parallel.median <= 0 or parallel.maximum <= 0:
        return TargetResult(
            key="fanout_speedup",
            label=label,
            target=f">= {target:.2f}x",
            observed="n/a",
            status=UNMEASURED,
            advisory=advisory,
            detail="parallel arm wall clock was zero; the timer resolution is too coarse",
        )

    speedup = sequential.median / parallel.median
    worst_case = sequential.minimum / parallel.maximum
    best_case = sequential.maximum / parallel.minimum
    status = MET if speedup >= target else MISSED
    detail = (
        f"median {sequential.median:.3f}s sequential / {parallel.median:.3f}s parallel; "
        f"worst-case bound {worst_case:.3f}x, best-case bound {best_case:.3f}x"
    )
    if advisory and advisory_reason:
        detail = f"{detail}. {advisory_reason}"
    return TargetResult(
        key="fanout_speedup",
        label=label,
        target=f">= {target:.2f}x",
        observed=f"{speedup:.3f}x",
        status=status,
        advisory=advisory,
        detail=detail,
        data={
            "speedup_median": speedup,
            "speedup_worst_case": worst_case,
            "speedup_best_case": best_case,
            "target": target,
            "sequential": sequential.as_dict(),
            "parallel": parallel.as_dict(),
        },
    )


def advisory_overhead(
    sequential_seconds: Sequence[float],
    parallel_seconds: Sequence[float],
    branch_seconds: Sequence[float],
    *,
    target: float = TARGET_FANOUT_SPEEDUP,
    projections: Sequence[float] = (10.0, 30.0),
) -> TargetResult:
    """Isolate the Flow's fixed serial cost and project the live speedup from it.

    This is the one thing synthetic mode can say about the live target. With a
    fixed serial overhead ``O`` and equal per-branch latency ``B``, parallel wall
    clock is ``O + B`` and sequential is ``O + 3B``, so the speedup is
    ``(O + 3B) / (O + B)``. Clearing ``target`` needs
    ``B >= O * (target - 1) / (3 - target)``.
    """
    label = "Fixed serial orchestration overhead"
    sequential = summarize(sequential_seconds)
    parallel = summarize(parallel_seconds)
    branches = [float(value) for value in branch_seconds]
    if sequential is None or parallel is None or len(branches) != 3:
        return TargetResult(
            key="serial_overhead",
            label=label,
            target="n/a",
            observed="unmeasured",
            status=UNMEASURED,
            advisory=True,
            detail="needs both arms and three known synthetic branch durations",
        )

    from_parallel = parallel.median - max(branches)
    from_sequential = sequential.median - sum(branches)
    overhead = (from_parallel + from_sequential) / 2.0
    if overhead <= 0 or target >= 3.0:
        return TargetResult(
            key="serial_overhead",
            label=label,
            target="n/a",
            observed=f"{overhead:.3f}s",
            status=UNMEASURED,
            advisory=True,
            detail="overhead is non-positive; branch sleeps are too short to separate",
        )

    required_branch = overhead * (target - 1.0) / (3.0 - target)
    projected = {
        f"{latency:.0f}s_branches": (overhead + 3 * latency) / (overhead + latency)
        for latency in projections
    }
    projection_text = ", ".join(
        f"{latency:.0f}s branches -> {(overhead + 3 * latency) / (overhead + latency):.2f}x"
        for latency in projections
    )
    return TargetResult(
        key="serial_overhead",
        label=label,
        target="n/a",
        observed=f"{overhead:.3f}s per run",
        status=MET,
        advisory=True,
        detail=(
            f"derived {from_parallel:.3f}s from the parallel arm and {from_sequential:.3f}s "
            f"from the sequential arm. At this overhead each branch must exceed "
            f"{required_branch:.2f}s for the fan-out to reach {target:.2f}x. "
            f"Projection: {projection_text}"
        ),
        data={
            "overhead_seconds": overhead,
            "overhead_from_parallel": from_parallel,
            "overhead_from_sequential": from_sequential,
            "required_branch_seconds_for_target": required_branch,
            "target": target,
            "projected_speedup": projected,
        },
    )


def evaluate_peak_rss(
    peak_bytes: int | None,
    *,
    target_bytes: int = TARGET_PEAK_RSS_BYTES,
    probe_name: str = "unknown",
    reason: str = "",
) -> TargetResult:
    """Peak resident set size against the 400 MB budget on a 512 MB host."""
    if peak_bytes is None:
        return TargetResult(
            key="peak_rss",
            label="Peak RSS during fan-out",
            target=f"< {target_bytes / MEGABYTE:.0f} MB",
            observed="unmeasured",
            status=UNMEASURED,
            detail=reason or f"no working memory probe on this platform ({probe_name})",
            data={"probe": probe_name},
        )
    status = MET if peak_bytes < target_bytes else MISSED
    return TargetResult(
        key="peak_rss",
        label="Peak RSS during fan-out",
        target=f"< {target_bytes / MEGABYTE:.0f} MB",
        observed=f"{peak_bytes / MEGABYTE:.1f} MB",
        status=status,
        detail=f"measured via {probe_name}",
        data={
            "peak_bytes": peak_bytes,
            "peak_mb": peak_bytes / MEGABYTE,
            "target_bytes": target_bytes,
            "probe": probe_name,
        },
    )


def evaluate_gate_latency(
    samples_ms: Sequence[float],
    *,
    target_ms: float = TARGET_GATE_RESUME_MS,
) -> TargetResult:
    """Gate reply to resume, judged on the worst sample rather than the median."""
    summary = summarize(samples_ms)
    if summary is None:
        return TargetResult(
            key="gate_resume",
            label="Gate reply to resume",
            target=f"< {target_ms:.0f} ms",
            observed="unmeasured",
            status=UNMEASURED,
            detail="the gate probe produced no samples",
        )
    status = MET if summary.maximum < target_ms else MISSED
    return TargetResult(
        key="gate_resume",
        label="Gate reply to resume",
        target=f"< {target_ms:.0f} ms",
        observed=f"max {summary.maximum:.1f} ms (median {summary.median:.1f} ms)",
        status=status,
        detail=(
            f"{summary.count} gate round trips; "
            f"min {summary.minimum:.1f} ms, max {summary.maximum:.1f} ms. "
            "Judged on the worst sample."
        ),
        data={"target_ms": target_ms, **summary.as_dict()},
    )


def evaluate_frame_integrity(
    stats: Sequence[Mapping[str, Any]],
    *,
    target_dropped: int = TARGET_DROPPED_FRAMES,
) -> TargetResult:
    """Zero dropped frames and a gapless per-run seq across every measured run."""
    if not stats:
        return TargetResult(
            key="frame_loss",
            label="Dropped UI frames / gapless seq",
            target=f"{target_dropped} dropped, 0 gaps",
            observed="unmeasured",
            status=UNMEASURED,
            detail="no run captured frames",
        )

    dropped = sum(int(entry.get("dropped", 0)) for entry in stats)
    gaps = sum(int(entry.get("gaps", 0)) for entry in stats)
    emit_errors = sum(int(entry.get("emit_errors", 0)) for entry in stats)
    captured = sum(int(entry.get("captured", 0)) for entry in stats)
    non_contiguous = [
        entry for entry in stats if not bool(entry.get("seq_contiguous", True))
    ]
    unpaired = sum(int(entry.get("unpaired_nodes", 0)) for entry in stats)

    problems: list[str] = []
    if dropped > target_dropped:
        problems.append(f"{dropped} dropped frames")
    if gaps:
        problems.append(f"{gaps} seq gaps")
    if emit_errors:
        problems.append(f"{emit_errors} emit errors")
    if non_contiguous:
        problems.append(f"{len(non_contiguous)} runs with a non-contiguous seq")
    if unpaired:
        problems.append(f"{unpaired} NODE_START frames without a NODE_END")

    status = MISSED if problems else MET
    return TargetResult(
        key="frame_loss",
        label="Dropped UI frames / gapless seq",
        target=f"{target_dropped} dropped, 0 gaps",
        observed=(
            "; ".join(problems)
            if problems
            else f"0 dropped, 0 gaps over {captured} frames"
        ),
        status=status,
        detail=f"{len(stats)} instrumented runs, {captured} frames captured",
        data={
            "runs": len(stats),
            "captured": captured,
            "dropped": dropped,
            "gaps": gaps,
            "emit_errors": emit_errors,
            "unpaired_node_starts": unpaired,
            "runs_with_non_contiguous_seq": len(non_contiguous),
        },
    )


def advisory_concurrency(observed: Sequence[int], *, expected: int = 3) -> TargetResult:
    """Diagnostic: did the parallel arm actually run branches concurrently?

    This is advisory rather than a PRD target, but a speedup number measured
    while the parallel arm never reached ``expected`` concurrent branches is not
    a measurement of fan-out at all, so it must be visible next to the ratio.
    """
    values = [int(value) for value in observed]
    if not values:
        return TargetResult(
            key="branch_concurrency",
            label="Observed concurrent research branches (parallel arm)",
            target=f"{expected}",
            observed="unmeasured",
            status=UNMEASURED,
            advisory=True,
            detail="no parallel run was instrumented",
        )
    peak = max(values)
    status = MET if peak >= expected else MISSED
    return TargetResult(
        key="branch_concurrency",
        label="Observed concurrent research branches (parallel arm)",
        target=f"{expected}",
        observed=str(peak),
        status=status,
        advisory=True,
        detail=(
            "per-run maxima: " + ", ".join(str(value) for value in values)
            + ("" if status == MET else "; the speedup ratio above is NOT a fan-out measurement")
        ),
        data={"per_run_max": values, "expected": expected},
    )


def overall_status(results: Iterable[TargetResult]) -> str:
    """MISSED beats INCOMPLETE beats MET. Advisory rows never decide the verdict."""
    collected = list(results)
    if any(result.failed for result in collected):
        return MISSED
    if any(result.unmeasured for result in collected):
        return INCOMPLETE
    return MET


# --------------------------------------------------------------------------
# Human-readable rendering
# --------------------------------------------------------------------------
_STATUS_MARK = {MET: "PASS", MISSED: "*** MISSED ***", UNMEASURED: "unmeasured"}

#: The four numbers PRD section 13 / feature F42 commit to.
PRD_TARGET_KEYS = frozenset({"fanout_speedup", "peak_rss", "gate_resume", "frame_loss"})


def render_table(results: Sequence[TargetResult]) -> str:
    """Render the target table, shouting about any missed target."""
    rows = [("Metric", "Target", "Observed", "Verdict")]
    for result in results:
        label = result.label + (" (advisory)" if result.advisory else "")
        rows.append(
            (label, result.target, result.observed, _STATUS_MARK.get(result.status, result.status))
        )
    widths = [max(len(row[index]) for row in rows) for index in range(4)]
    lines = []
    for position, row in enumerate(rows):
        lines.append(
            "  ".join(value.ljust(widths[index]) for index, value in enumerate(row)).rstrip()
        )
        if position == 0:
            lines.append("  ".join("-" * width for width in widths))
    for result in results:
        if result.detail:
            lines.append(f"    - {result.key}: {result.detail}")
    return "\n".join(lines)


def render_verdict_block(results: Sequence[TargetResult]) -> str:
    """A loud, unmissable summary of failures and gaps."""
    status = overall_status(results)
    failed = [result for result in results if result.failed]
    unmeasured = [result for result in results if result.unmeasured]
    advisory_failures = [
        result
        for result in results
        if result.advisory and result.status == MISSED and result.key not in PRD_TARGET_KEYS
    ]

    not_evaluated = [
        result for result in results if result.advisory and result.key in PRD_TARGET_KEYS
    ]

    lines = ["=" * 72]
    if status == MET and not_evaluated:
        lines.append("OVERALL: EVALUATED TARGETS MET (see NOT EVALUATED below)")
    elif status == MET:
        lines.append("OVERALL: ALL TARGETS MET")
    elif status == MISSED:
        lines.append("OVERALL: TARGET(S) MISSED")
    else:
        lines.append("OVERALL: INCOMPLETE - a target could not be measured")
    lines.append("=" * 72)

    for result in not_evaluated:
        lines.append(
            f"  NOT EVALUATED {result.label}: reported {result.observed} as advisory only, "
            f"so it neither passed nor failed the {result.target} target."
        )
    for result in failed:
        lines.append(f"  MISSED     {result.label}: {result.observed} (target {result.target})")
    for result in unmeasured:
        lines.append(f"  UNMEASURED {result.label}: {result.detail}")
    for result in advisory_failures:
        lines.append(f"  WARNING    {result.label}: {result.observed} (expected {result.target})")
    if status == MISSED:
        lines.append("")
        lines.append(
            "  PRD risk R-3: if the fan-out speedup target is not delivered, the parallel"
        )
        lines.append(
            "  implementation is withdrawn in favour of sequential execution. Do not"
        )
        lines.append("  re-run until the target is met and call that the result.")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Memory probes
# --------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class MemoryReading:
    """One sample. ``peak_bytes`` is an OS-maintained high-water mark if any."""

    current_bytes: int | None
    peak_bytes: int | None


class MemoryProbe:
    """A best-effort resident-memory reader for the current process."""

    name = "unavailable"
    available = False
    reason = "no supported memory API on this platform"
    supports_sampling = False

    def read(self) -> MemoryReading:  # pragma: no cover - overridden
        return MemoryReading(None, None)


class PsutilMemoryProbe(MemoryProbe):
    """Preferred path when psutil is installed."""

    name = "psutil"
    supports_sampling = True

    def __init__(self) -> None:
        import psutil  # noqa: PLC0415 - optional dependency, probed at runtime

        self._process = psutil.Process(os.getpid())
        version = getattr(psutil, "__version__", "?")
        self.name = f"psutil {version}"
        self.available = True
        self.reason = ""

    def read(self) -> MemoryReading:
        info = self._process.memory_info()
        current = int(getattr(info, "rss", 0)) or None
        peak = getattr(info, "peak_wset", None)
        return MemoryReading(current, int(peak) if peak else None)


class _WindowsProcessMemoryCounters(ctypes.Structure):
    _fields_ = [
        ("cb", ctypes.c_ulong),
        ("PageFaultCount", ctypes.c_ulong),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


class WindowsMemoryProbe(MemoryProbe):
    """ctypes GetProcessMemoryInfo. PeakWorkingSetSize is an exact OS high-water mark."""

    name = "ctypes GetProcessMemoryInfo (psapi)"
    supports_sampling = True

    def __init__(self) -> None:
        if sys.platform != "win32":
            raise OSError("not Windows")
        from ctypes import wintypes  # noqa: PLC0415 - Windows only

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        kernel32.GetCurrentProcess.argtypes = []
        self._handle = kernel32.GetCurrentProcess()

        function = None
        for library, symbol in (("kernel32", "K32GetProcessMemoryInfo"), ("psapi", "GetProcessMemoryInfo")):
            try:
                candidate = getattr(ctypes.WinDLL(library, use_last_error=True), symbol)
            except (OSError, AttributeError):
                continue
            candidate.restype = wintypes.BOOL
            candidate.argtypes = [
                wintypes.HANDLE,
                ctypes.POINTER(_WindowsProcessMemoryCounters),
                wintypes.DWORD,
            ]
            function = candidate
            self.name = f"ctypes {symbol} ({library})"
            break
        if function is None:
            raise OSError("GetProcessMemoryInfo is unavailable")
        self._function = function
        if self.read().current_bytes is None:
            raise OSError("GetProcessMemoryInfo returned no data")
        self.available = True
        self.reason = ""

    def read(self) -> MemoryReading:
        counters = _WindowsProcessMemoryCounters()
        counters.cb = ctypes.sizeof(_WindowsProcessMemoryCounters)
        if not self._function(self._handle, ctypes.byref(counters), counters.cb):
            return MemoryReading(None, None)
        return MemoryReading(int(counters.WorkingSetSize), int(counters.PeakWorkingSetSize))


class LinuxProcMemoryProbe(MemoryProbe):
    """/proc/self/status. VmHWM is the kernel's own peak, so no sample can miss it."""

    name = "/proc/self/status (VmRSS/VmHWM)"
    supports_sampling = True

    def __init__(self) -> None:
        self._path = "/proc/self/status"
        if self.read().current_bytes is None:
            raise OSError("/proc/self/status is unreadable")
        self.available = True
        self.reason = ""

    def read(self) -> MemoryReading:
        current: int | None = None
        peak: int | None = None
        try:
            with open(self._path, "r", encoding="utf-8") as handle:
                for line in handle:
                    if line.startswith("VmRSS:"):
                        current = int(line.split()[1]) * 1024
                    elif line.startswith("VmHWM:"):
                        peak = int(line.split()[1]) * 1024
                    if current is not None and peak is not None:
                        break
        except OSError:
            return MemoryReading(None, None)
        return MemoryReading(current, peak)


class ResourceMemoryProbe(MemoryProbe):
    """POSIX getrusage fallback. Peak only; there is no current-RSS reading."""

    name = "resource.getrusage(ru_maxrss)"
    supports_sampling = False

    def __init__(self) -> None:
        import resource  # noqa: PLC0415 - POSIX only

        self._resource = resource
        self._scale = 1 if sys.platform == "darwin" else 1024
        self.available = True
        self.reason = "getrusage reports only a peak; per-arm sampling is unavailable"

    def read(self) -> MemoryReading:
        usage = self._resource.getrusage(self._resource.RUSAGE_SELF)
        return MemoryReading(None, int(usage.ru_maxrss) * self._scale)


def select_memory_probe() -> MemoryProbe:
    """Pick the best available probe and report honestly when there is none."""
    for factory in (PsutilMemoryProbe, WindowsMemoryProbe, LinuxProcMemoryProbe, ResourceMemoryProbe):
        try:
            return factory()
        except Exception:  # noqa: BLE001 - a probe that cannot init is simply not usable
            continue
    return MemoryProbe()


class PeakMemorySampler:
    """Sample resident memory on a background thread to catch a transient peak.

    The OS high-water mark (``peak_bytes``) is exact and cannot miss a spike;
    the sampled series exists so a peak can be attributed to a particular arm,
    since the OS counter is monotonic for the life of the process.
    """

    def __init__(
        self,
        probe: MemoryProbe,
        *,
        interval_s: float = DEFAULT_SAMPLE_INTERVAL_S,
    ) -> None:
        if interval_s <= 0:
            raise ValueError("interval_s must be positive")
        self.probe = probe
        self.interval_s = interval_s
        self.sampled_peak_bytes: int | None = None
        self.os_peak_bytes: int | None = None
        self.sample_count = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _observe(self) -> None:
        reading = self.probe.read()
        self.sample_count += 1
        if reading.current_bytes is not None:
            self.sampled_peak_bytes = max(self.sampled_peak_bytes or 0, reading.current_bytes)
        if reading.peak_bytes is not None:
            self.os_peak_bytes = max(self.os_peak_bytes or 0, reading.peak_bytes)

    def _loop(self) -> None:
        while not self._stop.is_set():
            self._observe()
            self._stop.wait(self.interval_s)

    def __enter__(self) -> "PeakMemorySampler":
        self._observe()
        if self.probe.available and self.probe.supports_sampling:
            self._thread = threading.Thread(
                target=self._loop, name="perf-rss-sampler", daemon=True
            )
            self._thread.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self.interval_s * 20 + 1.0)
            self._thread = None
        self._observe()

    @property
    def peak_bytes(self) -> int | None:
        """The most trustworthy peak available: the OS mark, else the samples."""
        if self.os_peak_bytes is not None:
            return self.os_peak_bytes
        return self.sampled_peak_bytes

    def as_dict(self) -> dict[str, Any]:
        return {
            "probe": self.probe.name,
            "probe_available": self.probe.available,
            "sample_interval_s": self.interval_s,
            "samples": self.sample_count,
            "sampled_peak_bytes": self.sampled_peak_bytes,
            "os_peak_working_set_bytes": self.os_peak_bytes,
            "peak_bytes": self.peak_bytes,
        }


def wall_clock() -> float:
    """A single named source of truth for every duration in this harness."""
    return time.perf_counter()
