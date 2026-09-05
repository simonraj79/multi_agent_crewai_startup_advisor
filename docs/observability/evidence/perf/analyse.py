"""Turn `main/e4-raw.json` and `blackhole/e4-raw.json` into the tables in `overhead.md`.

Kept beside the data so every figure in `overhead.md` is regenerable rather than
typed. Reads only; writes `raw-stats.txt` and `tables.md`.

    .venv/Scripts/python.exe docs/observability/evidence/perf/analyse.py
"""

from __future__ import annotations

import json
import math
import statistics as st
from pathlib import Path
from typing import Any, Sequence

HERE = Path(__file__).resolve().parent


def table(headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
    out = ["| " + " | ".join(str(h) for h in headers) + " |"]
    out.append("| " + " | ".join("---" for _ in headers) + " |")
    for row in rows:
        out.append("| " + " | ".join("" if c is None else str(c) for c in row) + " |")
    return "\n".join(out)


def arm(runs: list[dict[str, Any]], name: str) -> list[dict[str, Any]]:
    return [r for r in runs if r["arm"] == name]


def stats(values: list[float]) -> dict[str, float]:
    return {
        "n": len(values),
        "mean": st.fmean(values),
        "median": st.median(values),
        "min": min(values),
        "max": max(values),
        "sd": st.stdev(values) if len(values) > 1 else 0.0,
    }


def welch(a: list[float], b: list[float]) -> tuple[float, float, float, float]:
    ma, mb = st.fmean(a), st.fmean(b)
    va, vb = st.variance(a), st.variance(b)
    se = math.sqrt(va / len(a) + vb / len(b))
    t = (ma - mb) / se if se else float("nan")
    df = (va / len(a) + vb / len(b)) ** 2 / (
        (va / len(a)) ** 2 / (len(a) - 1) + (vb / len(b)) ** 2 / (len(b) - 1)
    )
    return ma - mb, se, t, df


def main() -> int:
    main_raw = json.loads((HERE / "main" / "e4-raw.json").read_text(encoding="utf-8"))
    bh_raw = json.loads((HERE / "blackhole" / "e4-raw.json").read_text(encoding="utf-8"))

    on = arm(main_raw["runs"], "on")
    off = arm(main_raw["runs"], "off")
    bh = arm(bh_raw["runs"], "bh")
    bh_off = arm(bh_raw["runs"], "off")

    lines: list[str] = []
    say = lines.append

    say("## Per arm, wall clock launch -> terminal status (client side, ms)")
    say("")
    rows = []
    for label, runs in (
        ("on", on),
        ("off", off),
        ("bh (extra)", bh),
        ("off, bh session control", bh_off),
    ):
        s = stats([r["wall_clock_seconds"] * 1000 for r in runs])
        rows.append(
            [
                label,
                s["n"],
                f"{s['mean']:.1f}",
                f"{s['median']:.1f}",
                f"{s['min']:.1f}",
                f"{s['max']:.1f}",
                f"{s['sd']:.1f}",
            ]
        )
    say(table(["arm", "n", "mean", "median", "min", "max", "stdev"], rows))
    say("")

    wa = [r["wall_clock_seconds"] * 1000 for r in on]
    wb = [r["wall_clock_seconds"] * 1000 for r in off]
    d, se, t, df = welch(wa, wb)
    off_mean = st.fmean(wb)
    med_d = st.median(wa) - st.median(wb)
    say("## The delta")
    say("")
    say(
        table(
            ["quantity", "value"],
            [
                ["mean(on) - mean(off)", f"{d:+.2f} ms ({d / off_mean * 100:+.3f} % of the off mean)"],
                ["median(on) - median(off)", f"{med_d:+.2f} ms ({med_d / st.median(wb) * 100:+.3f} %)"],
                ["standard error of that delta", f"{se:.2f} ms"],
                ["Welch t / df", f"{t:.2f} / {df:.1f}"],
                ["95 % interval on the mean delta", f"{d - 1.96 * se:+.2f} .. {d + 1.96 * se:+.2f} ms"],
                ["stdev of the on arm / the off arm", f"{st.stdev(wa):.1f} ms / {st.stdev(wb):.1f} ms"],
            ],
        )
    )
    say("")

    d2, se2, t2, _ = welch(
        [r["wall_clock_seconds"] * 1000 for r in bh],
        [r["wall_clock_seconds"] * 1000 for r in bh_off],
    )
    say(
        f"Extra arm: mean(bh) - mean(off control) = {d2:+.2f} ms "
        f"(SE {se2:.2f} ms, Welch t = {t2:.2f}).",
    )
    say("")

    say("## The exporter's own counters, per run (from the summary line)")
    say("")
    rows = []
    for label, runs in (("on", on), ("bh (extra)", bh)):
        exported = [r for r in runs if r.get("exporter")]
        p50 = [r["exporter"]["enqueue_p50_us"] for r in exported]
        p95 = [r["exporter"]["enqueue_p95_us"] for r in exported]
        enq = [r["exporter"]["frames_enqueued"] for r in exported]
        sent = [r["exporter"]["observations_sent"] for r in exported]
        rows.append(
            [
                label,
                f"{len(exported)}/{len(runs)}",
                f"{min(enq)}-{max(enq)}",
                sum(r["exporter"]["frames_dropped"] for r in exported),
                f"{min(sent)}-{max(sent)}",
                sum(r["exporter"]["http_errors"] for r in exported),
                f"{st.median(p50):g} ({min(p50)}-{max(p50)})",
                f"{st.median(p95):g} ({min(p95)}-{max(p95)})",
            ]
        )
    say(
        table(
            [
                "arm",
                "summary lines",
                "frames_enqueued",
                "frames_dropped",
                "observations_sent",
                "http_errors",
                "enqueue p50 us, median (range)",
                "enqueue p95 us, median (range)",
            ],
            rows,
        )
    )
    say("")

    say("## What the app did, per arm - the E2 half of this measurement")
    say("")
    rows = []
    for label, runs in (("on", on), ("off", off), ("bh (extra)", bh), ("off control", bh_off)):
        frames = [r["frames"] for r in runs]
        rows.append(
            [
                label,
                len(runs),
                ", ".join(sorted({str(r["status"]) for r in runs})),
                f"{min(frames)}-{max(frames)}",
                sum(int(r["frames_dropped"] or 0) for r in runs),
                ", ".join(sorted({str(r["calls"]) for r in runs})),
                ", ".join(sorted({str(r["total_tokens"]) for r in runs})),
            ]
        )
    say(
        table(
            ["arm", "runs", "status", "app frames", "app frames dropped", "calls", "tokens"],
            rows,
        )
    )
    say("")

    say("## Every run")
    say("")
    rows = []
    for source, runs in (("main", main_raw["runs"]), ("blackhole", bh_raw["runs"])):
        for r in runs:
            exporter = r.get("exporter") or {}
            rows.append(
                [
                    source,
                    r["arm"],
                    r["block"],
                    r["index_in_block"],
                    r["run_id"],
                    r["status"],
                    f"{r['wall_clock_seconds'] * 1000:.1f}",
                    r["frames"],
                    exporter.get("frames_enqueued", "-"),
                    exporter.get("frames_dropped", "-"),
                    exporter.get("observations_sent", "-"),
                    exporter.get("http_errors", "-"),
                    exporter.get("enqueue_p50_us", "not found"),
                    exporter.get("enqueue_p95_us", "not found"),
                ]
            )
    say(
        table(
            [
                "set",
                "arm",
                "block",
                "#",
                "run_id",
                "status",
                "wall ms",
                "app frames",
                "enqueued",
                "dropped",
                "sent",
                "http_err",
                "p50 us",
                "p95 us",
            ],
            rows,
        )
    )
    say("")

    confirm_path = HERE / "confirm" / "e4-raw.json"
    if confirm_path.is_file():
        confirm_raw = json.loads(confirm_path.read_text(encoding="utf-8"))
        c_on = arm(confirm_raw["runs"], "on")
        c_off = arm(confirm_raw["runs"], "off")
        say("## Confirmation pass, re-run against a later working tree")
        say("")
        rows = []
        for label, runs in (("on", c_on), ("off", c_off)):
            s = stats([r["wall_clock_seconds"] * 1000 for r in runs])
            rows.append(
                [
                    label,
                    s["n"],
                    f"{s['mean']:.1f}",
                    f"{s['median']:.1f}",
                    f"{s['min']:.1f}",
                    f"{s['max']:.1f}",
                    f"{s['sd']:.1f}",
                ]
            )
        say(table(["arm", "n", "mean", "median", "min", "max", "stdev"], rows))
        say("")
        ca = [r["wall_clock_seconds"] * 1000 for r in c_on]
        cb = [r["wall_clock_seconds"] * 1000 for r in c_off]
        cd, cse, ct, _ = welch(ca, cb)
        cp50 = [r["exporter"]["enqueue_p50_us"] for r in c_on if r.get("exporter")]
        cp95 = [r["exporter"]["enqueue_p95_us"] for r in c_on if r.get("exporter")]
        say(
            f"mean(on) - mean(off) = {cd:+.2f} ms ({cd / st.fmean(cb) * 100:+.3f} %), "
            f"SE {cse:.2f} ms, Welch t = {ct:.2f}, 95 % interval "
            f"{cd - 1.96 * cse:+.2f} .. {cd + 1.96 * cse:+.2f} ms."
        )
        say("")
        say(
            f"Enqueue latency, on arm: p50 median {st.median(cp50):g} us "
            f"(range {min(cp50)}-{max(cp50)}), p95 median {st.median(cp95):g} us "
            f"(range {min(cp95)}-{max(cp95)}), from {len(cp50)}/{len(c_on)} summary lines. "
            f"Statuses: {', '.join(sorted({str(r['status']) for r in confirm_raw['runs']}))}; "
            f"app frames dropped {sum(int(r['frames_dropped'] or 0) for r in confirm_raw['runs'])}."
        )
        say("")

    say("## Process boot, per block (not per run - a one-off cost)")
    say("")
    rows = []
    boot_reports = list(main_raw["block_reports"]) + list(bh_raw["block_reports"])
    if confirm_path.is_file():
        boot_reports += [dict(r, arm=r["arm"] + " (confirm)") for r in confirm_raw["block_reports"]]
    for report in boot_reports:
        obs = report.get("observability") or {}
        rows.append(
            [
                report["block"],
                report["arm"],
                f"{report['boot_seconds']:.2f}",
                obs.get("exporter"),
                obs.get("reason") or "-",
                obs.get("environment"),
                obs.get("capture_content"),
            ]
        )
    say(
        table(
            ["block", "arm", "boot s", "/readyz exporter", "reason", "environment", "capture_content"],
            rows,
        )
    )
    say("")
    boots_on = [r["boot_seconds"] for r in main_raw["block_reports"] if r["arm"] == "on"]
    boots_off = [r["boot_seconds"] for r in main_raw["block_reports"] if r["arm"] == "off"]
    say(
        f"Boot, on arm mean {st.fmean(boots_on):.2f} s; off arm mean "
        f"{st.fmean(boots_off):.2f} s; difference "
        f"{(st.fmean(boots_on) - st.fmean(boots_off)) * 1000:+.0f} ms, paid once per process."
    )

    text = "\n".join(lines) + "\n"
    (HERE / "tables.md").write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
