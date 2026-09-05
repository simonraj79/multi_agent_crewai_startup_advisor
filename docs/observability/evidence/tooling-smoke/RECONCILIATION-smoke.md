# Reconciliation - run `54a93dc8-13e3-4edf-b180-af206f1eb168`

Generated 2026-09-05T13:37:22Z by `scripts/observability/reconcile.py`.
DoD rows **E1** and **E5**. Every **Diagnosis** cell is empty on purpose:
the script measures, a verifier names the cause.

| source | what it is | file |
| --- | --- | --- |
| app | the run's own frames and snapshot | `http://127.0.0.1:8098` |
| Langfuse | session `not found`, 0 observations | public API |
| OpenRouter | 0 of 0 generation records | `GET /api/v1/generation?id=` |

## 1. Totals

| metric | app | Langfuse | OpenRouter | verdict | Diagnosis |
| --- | --- | --- | --- | --- | --- |
| calls | 6 | n/a | n/a | agree | - |
| input tokens | 3840 | n/a | n/a | agree | - |
| output tokens | 449 | n/a | n/a | agree | - |
| total tokens | 4289 | n/a | n/a | agree | - |
| cost (USD) | $0.002275 | n/a | n/a | agree | - |

## 2. Duplicates (E1)

**NOT CHECKED** - no Langfuse observations were pulled for this run, so nothing was examined for a second copy. This is not a pass.

## 3. Per-call join on `response_id`

- **no generation ids to join.** Not a pass: the join is the only check that can find a call present in two sources and absent from the third, and it did not run.

- app calls carrying no generation id: 6 (expected to be every call on a SYNTHETIC run - the double writes `response_id: None`)
- Langfuse generations carrying no `metadata.response_id`: n/a

| generation id | model | agent_role | app in/out | LF in/out | OR in/out | app cost | LF cost | OR cost | Diagnosis |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| - | - | - | - | - | - | - | - | - | - |

## 4. Durations, app frames versus Langfuse spans (B4)

Not computed: both an app and a Langfuse directory are needed.

## 5. Diagnosis notes

_Verifier: one line per differing cell above. E5 accepts no cell left blank._
