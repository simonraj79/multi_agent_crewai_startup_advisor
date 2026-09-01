#!/usr/bin/env python
"""What the guardrails and the rubric anchors are actually doing, across runs.

This exists because a cost/latency dial was turned without any way to see the
consequence. On 2026-09-01 ``VALIDATOR_SYNTHESIST_REASONING_EFFORT`` moved from
``high`` to ``low`` and ``VALIDATOR_REPORTER_REASONING_EFFORT`` was introduced at
``low``. Both are defensible on latency grounds and neither is observable: the
thing predicted to degrade first is the Synthesist's ability to reproduce rubric
anchor prose, and nothing in this system reported on that until now.

Two numbers, and the distinction between them is the point.

**RETRY RATE** is the one that decides whether a cheaper setting was worth it,
and it is not primarily about latency. ``guardrail_max_retries: 2`` allows three
evaluations of a task, each a full escalation-tier call, so:

* On WALL CLOCK a cheaper setting almost cannot lose. Three calls at ~20s is
  about one call at ~61s, so the break-even first-attempt failure rate is
  roughly 1.0.
* On RELIABILITY it can lose badly. A run DIES when all three attempts fail, at
  roughly ``p³``: 12.5% of runs at p=0.5, and 0.8% at p=0.2.

So the binding constraint is run failure, not seconds, and the number to watch
is ``p`` - the share of tasks whose FIRST guardrail evaluation was rejected.

**ANCHOR MARGIN** is the leading indicator. ``anchor_problems`` rejects below
``ANCHOR_MATCH_THRESHOLD`` (0.85) and, until today, mentioned the overlap only
inside that rejection - so a passing run recorded nothing and the only signal
was a cliff with no visible approach. ``anchor_margins`` now rides on every
verdict frame. A mean drifting 0.95 -> 0.88 -> 0.86 is a warning; a first
rejection is a post-mortem.

Reads only. No model is called and nothing is written, so this is free and safe
to run against production.

    python scripts/dial_stats.py                       # local SQLite
    DATABASE_URL=postgresql://... python scripts/dial_stats.py
    python scripts/dial_stats.py --since 2026-09-01    # after the dial moved
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sqlalchemy import create_engine, select  # noqa: E402

from brief_crew.config import ANCHOR_MATCH_THRESHOLD  # noqa: E402
from brief_crew.service.persistence import run_frames, runs  # noqa: E402

DEFAULT_URL = "sqlite:///output/validator-studio.db"


def _rows(engine, since: datetime | None):
    """Every guardrail and verdict frame, newest run first."""
    statement = select(
        run_frames.c.run_id,
        run_frames.c.ts,
        run_frames.c.kind,
        run_frames.c.node_id,
        run_frames.c.details,
    ).where(run_frames.c.kind.in_(("guardrail", "verdict")))
    if since is not None:
        statement = statement.where(run_frames.c.ts >= since)
    with engine.connect() as connection:
        return list(connection.execute(statement))


def _details(value) -> dict:
    if isinstance(value, dict):
        return value
    try:
        return json.loads(value) if value else {}
    except (TypeError, ValueError):
        return {}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL", DEFAULT_URL))
    parser.add_argument("--since", help="ISO date, e.g. 2026-09-01")
    args = parser.parse_args()

    since = None
    if args.since:
        since = datetime.fromisoformat(args.since).replace(tzinfo=timezone.utc)

    engine = create_engine(args.database_url)
    rows = _rows(engine, since)
    if not rows:
        print("No guardrail or verdict frames found. Has a run completed yet?")
        return 0

    # A guardrail evaluation is FIRST when its retry_count is 0. That is the one
    # that decides `p`: a rejection there costs an entire extra escalation call,
    # and three of them kill the run.
    first_total: Counter[str] = Counter()
    first_failed: Counter[str] = Counter()
    retries_seen: Counter[str] = Counter()
    margins: dict[str, list[float]] = defaultdict(list)
    seen_runs: set[str] = set()

    for row in rows:
        seen_runs.add(row.run_id)
        details = _details(row.details)
        if row.kind == "guardrail":
            if details.get("stage") != "after":
                continue
            node = row.node_id or "unknown"
            attempt = details.get("retry_count")
            if attempt == 0:
                first_total[node] += 1
                if details.get("success") is False:
                    first_failed[node] += 1
            elif isinstance(attempt, int) and attempt > 0:
                retries_seen[node] += 1
        else:
            for code, value in (details.get("anchor_margins") or {}).items():
                if isinstance(value, (int, float)):
                    margins[code].append(float(value))

    print(f"runs inspected: {len(seen_runs)}" + (f"  (since {args.since})" if since else ""))

    print("\nFIRST-ATTEMPT GUARDRAIL FAILURE RATE  (p)")
    print("  run failure is ~p^3, so p<=0.2 keeps it under 1%")
    if not first_total:
        print("  no first-attempt guardrail frames recorded")
    for node, total in first_total.most_common():
        failed = first_failed[node]
        rate = failed / total
        flag = "  <-- ABOVE 0.2" if rate > 0.2 else ""
        print(f"  {node:22} {failed:3}/{total:<3} = {rate:5.1%}   run-fail ~{rate**3:5.1%}{flag}")

    if retries_seen:
        print("\n  retry evaluations observed (each is a whole extra call):")
        for node, count in retries_seen.most_common():
            print(f"    {node:22} {count}")

    print(f"\nANCHOR MARGIN  (rejects below {ANCHOR_MATCH_THRESHOLD:.0%})")
    if not margins:
        print("  none recorded - verdict frames predate `anchor_margins`")
    for code in ("D", "M", "C", "F", "X"):
        values = margins.get(code) or []
        if not values:
            continue
        worst = min(values)
        mean = statistics.fmean(values)
        headroom = mean - ANCHOR_MATCH_THRESHOLD
        flag = "  <-- CLOSE TO THE THRESHOLD" if headroom < 0.05 else ""
        print(
            f"  {code}  n={len(values):<3} mean={mean:.3f}  worst={worst:.3f}"
            f"  headroom={headroom:+.3f}{flag}"
        )

    print(
        "\nRead this next to VALIDATOR_SYNTHESIST_REASONING_EFFORT and\n"
        "VALIDATOR_REPORTER_REASONING_EFFORT in config.py. Both are env-overridable,\n"
        "so a bad reading is reverted without a deploy."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
