# Open comparison defects

One row per defect the critic landed and nobody has closed. A row leaves
this table only when a later round scores the dimension at or above the
reference and the fix is named. Format is fixed; the method is in
`README.md`.

| id | plan | round | date | dim | ours | ref | delta | located defect | status | closed by |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |

**No round has run as of 2026-09-02.** The table is empty because nothing
has been built against a plan yet, not because nothing is wrong. The first
entry will come from `rounds/02-canvas-1.md`.

## Conventions

- `id` is `D-<plan>-<n>`, monotonically increasing per plan; never reused.
- `ours` / `ref` are the critic's scores for that dimension, 1–10; `delta` is `ref − ours`.
- `located defect` is the critic's sentence verbatim, with viewport, zoom and component; a sentence without a location is not a defect and does not get a row.
- `status` is `open` or `closed`; a closed row stays in the table with its closing commit so a regression is a reopen, not a new id.
- A feature cannot pass its gate while any row for its plan is `open`, even at a score of 8 or above.
