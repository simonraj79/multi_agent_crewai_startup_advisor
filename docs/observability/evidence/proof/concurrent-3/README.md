# `concurrent-3` — A2 / D5 on the code that fixed the `fc-` scrub

The pass-1 pair (`../concurrent/`) was measured before identity fields were
scrubbed by value only, so A2 needed a clean pair on `58a1c0b`. This is it:
`../validator-live-3` and `../builder-toolfail-3` themselves, launched together,
so the row still costs no extra run.

The backend carried `RUN_CONCURRENCY=2` (`../readyz-before-pass3.json`:
`executor.workers: 2`), so both executed rather than queueing.

`launch-times.txt`, verbatim:

```text
validator-live-3   POST sent   2026-09-05T18:07:35.207Z
builder-toolfail-3 POST sent   2026-09-05T18:07:35.212Z
builder-toolfail-3 202 back at 2026-09-05T18:07:35.274Z
validator-live-3   202 back at 2026-09-05T18:07:35.274Z
```

**5 ms** between the two POSTs, well inside the 2 s the brief allows. They
overlapped for real: `builder-toolfail-3` ran to its terminal frame at
`18:07:38.938Z` while `validator-live-3` ran on until `18:08:36.630Z`.

Both were left alone until the exporter had printed a summary line for each —
the deferred billed-cost lookups run for up to four minutes past the terminal
frame, and pulling before they settle would read a half-priced trace:

```text
langfuse-exporter run=f0297951-... lookup_ok=2  lookup_failed=0   (18:12:23Z)
langfuse-exporter run=f146e846-... lookup_ok=11 lookup_failed=0
```

`membership-check.txt`, the quotable line:

```text
TOTALS: sessions=2 traces=2 observations=102 mismatches=0 cross-membership=0 no-run_id=0 VERDICT=PASS
```

All **102** observations carry a `metadata.run_id`, every one equals the
`sessionId` of the trace it sits in, and neither run's session contains anything
belonging to the other. Produced by

```powershell
.\.venv\Scripts\python.exe scripts\observability\membership_check.py `
    --from-dir ..\validator-live-3 --from-dir ..\builder-toolfail-3 --out .
```

exit 0.

## Why this pair and not the pass-1 one

Pass 1's pair also read `mismatches=0 cross-membership=0 no-run_id=0` over 97
observations, and that result stands. But between the two, pass 2 found that the
exporter scrubbed a run id containing `fc-` down to `…-b5***` before storing it
(`../validator-live-2/README.md`), which is precisely the field
`membership_check.py` compares. Had that run been half of a concurrent pair, the
check would have reported one mismatch on its `run` span — not a concurrency
bug, but indistinguishable from one in the artifact A2 rests on. `58a1c0b`
scrubs identity fields by exact value only; this pair is the measurement taken
after that, and `validator-live-3`'s `trace.metadata.run_id` reads
`f146e846-7e32-4276-9c9d-d79909a02eec` in full.

Session URLs:
`https://us.cloud.langfuse.com/project/cmto3mj7t06ykad0ipon3ksbw/sessions/f146e846-7e32-4276-9c9d-d79909a02eec`
`https://us.cloud.langfuse.com/project/cmto3mj7t06ykad0ipon3ksbw/sessions/f0297951-e1ff-49a1-90f6-725d06d9b112`
