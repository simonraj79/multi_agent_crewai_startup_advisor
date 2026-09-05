# `concurrent` — A2 / D5: two runs launched 5 ms apart on one backend

Per `PLAN.md`'s preferred form, the concurrent pair is `validator-live` and
`builder-toolfail` themselves, so A2/D5 cost no extra run. The backend carried
`RUN_CONCURRENCY=2` (`../readyz-before.json`: `executor.workers: 2`), so both
executed rather than queueing.

`launch-times.txt`, verbatim:

```text
validator-live  POST sent   2026-09-05T16:33:04.161Z
builder-toolfail POST sent  2026-09-05T16:33:04.166Z
builder-toolfail 202 back at 2026-09-05T16:33:04.218Z
validator-live  202 back at 2026-09-05T16:33:04.229Z
```

**5 ms** between the two POSTs, well inside the 2 s the brief allows. They
overlapped for real: `builder-toolfail` ran 16:33:05.199 → 16:33:07.873 while
`validator-live` ran 16:33:04.230 → 16:33:54.540.

`membership-check.txt`, the quotable line:

```text
TOTALS: sessions=2 traces=2 observations=97 mismatches=0 cross-membership=0 no-run_id=0 VERDICT=PASS
```

Every one of the 97 observations carries a `metadata.run_id`, and every one of
them equals the `sessionId` of the trace it sits in. Produced by
`scripts/observability/membership_check.py --from-dir ../validator-live
--from-dir ../builder-toolfail`, exit 0.

Session URLs:
https://us.cloud.langfuse.com/project/cmto3mj7t06ykad0ipon3ksbw/sessions/f4c8c779-52f2-40e1-9351-2668ea276ae4
https://us.cloud.langfuse.com/project/cmto3mj7t06ykad0ipon3ksbw/sessions/9becf713-e984-45a9-b9c0-5b229a15cb60
