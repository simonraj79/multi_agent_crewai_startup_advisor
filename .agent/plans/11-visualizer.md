
### Critic round product-1 fixes — 2026-09-04

**P-08 — a completed run reported `ELAPSED 00:00 · CALLS 0 · TOKENS 0 ·
$0.0000` while the rail beside it showed `640 in · 78 out`.** Measured on run
`7e2bb81d`, status `completed`, whose server record held `created_at` and
`completed_at` **15.019 s** apart. Two independent halves, and only one of them
was synthetic:

*The tokens.* `SyntheticValidatorRunner._utterance` emitted an `llm` frame
carrying `prompt_tokens` — which is what the dialogue rail reads — and **no
TOKEN frame at all**. `useValidatorRun.applyTokenUsage` fires on
`kind === 'token'` and on nothing else, so the two surfaces disagreed by
construction. It now emits the serializer's own three-frame sequence, in the
serializer's own order (`after`, `utterance`, `token` —
`events/serializer.py:525-527`), bracketed by a `before` frame because
`RunRecord._track_llm_timing` keys its per-call clock off exactly those two
stages. Emitting TOKEN gets `CALLS` and the METRICS frames back through the
**production** path rather than a second one written for the double:
`_on_frames` routes it into `_record_usage`, which marks the usage dirty and is
what `metrics_frame` snapshots. The cost comes from `compute_cost_usd` rather
than a literal, so a synthetic run prices the way a paid one does and a `PRICES`
change moves both; it is nested inside `usage` as well as beside it, which is
CLAUDE.md section 8's second `cost_usd` bug met from the double's side.

**Fifth recording of one defect: a double that cannot produce the thing under
test certifies nothing** (closed items 20 and 33, and `_tool_call`'s and
`_utterance`'s own docstrings). The console's entire spend surface — the one an
operator watches while a graph somebody else drew bills against
`MAX_RUN_COST_USD` — was unexercisable on the only path a test or a local
session can use.

*The elapsed, which is not a synthetic artefact.* Nothing about elapsed depends
on model usage, and the server holds both timestamps. `usage.elapsedMs` was
summed from per-call timings that only exist once a METRICS frame has been
emitted, so a run that called no priced model reported that it took no time at
all. Frames carry `ts`, so `noteFrameClock` takes the span between the first
and the last — the run's own clock, replayed identically after a reload.
`Math.max` in both directions: a real METRICS elapsed (which includes queue
time the frames cannot see) still wins, and a snapshot carrying
`elapsed_ms: 0` can no longer erase what the frames already said. That last
clause is a real ordering hazard — `restoreRun` assigns the snapshot *after*
replaying frames.

Proved by breaking it. Against the reverted runner and composable the journey
test fails on `ELAPSED on a completed run / Expected: not "00:00"`, which is the
critic's first measurement verbatim, and two of the three new client tests fail
with `expected +0 to be 3000`.

Tests: `tests/service/test_synthetic_choreography.py::TokenAndCostTests` (**6**),
`frontend/tests/frameHandling.spec.ts` (**3**), and four assertions added to the
existing `@launch` journey in `e2e/studio.spec.ts` — added there rather than in
a test of their own because that run has already completed at that point and a
second `@launch` test would spend money against a paid origin to learn the same
thing.
