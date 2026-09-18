# Run labels: was this run good, and the trace says so too

Binding description of plan 20 (`.agent/plans/20-run-labels.md`, branch
`admin/run-labels`). **Committed**, like everything else under
`docs/observability/`, and for the reason `.gitignore`'s own exception gives:
a criterion settled by a file nobody else can see is an assertion by the
builder.

Read [`TRACE-CONTRACT.md`](TRACE-CONTRACT.md) first. It owns what the app
writes to Langfuse; this page owns one score on that contract and the routes
that produce it.

## 1. What it is

Before this, the only durable human signal a run carried was a gate reply,
which says what somebody accepted *mid-run*, and every Langfuse score was
automatic (`guardrail_passed`, `task_attempts`, `run_status`, `run_succeeded`),
which says what a machine checked. Neither answers *was this run any good*. Without that answer a run is useful only to itself: it
cannot be found again, compared against another, or used as an example.

So a finished run's owner, or an admin, answers one question with one of three
words and an optional short note, and can take it back:

> **Was this run good?**  Good / Bad / Not sure

The word is stored on the run and mirrored to the run's Langfuse trace as a
score, so the trace list can be filtered to the runs a person thought were
good. That is the whole feature. It performs no model call, adds no
environment knob, reads no trace, changes no prompt and trains nothing.

## 2. The routes

`RunRating` is `{run_id, rating, rating_note, rated_by, rated_at}`; `rating`
is `good` / `bad` / `unsure` or `null`, and every other field is nullable. The
**request** body is `{"rating": …, "note": …}` with `extra="forbid"`: the
request spells it `note` and the response spells it `rating_note`, which is
the column's spelling and the one the client treats as canonical.

| Route | Who | Answers |
| --- | --- | --- |
| `GET /api/runs/{run_id}/rating` | `require_own_run` | 200 with the rating, or four nulls if nobody has rated it. 404 for a stranger's run, an unknown run, or a run id over 128 characters |
| `PUT /api/runs/{run_id}/rating` | `require_own_run` | 200 with the stored rating. 422 for a fourth word, for `""`, or for a note over `MAX_RATING_NOTE_CHARS` (500) after control characters are stripped. 409 if the run has not finished. 403 for a signed-in caller writing a run nobody owns. 404 as above. 503 if the service has no durable store |
| `PUT /api/admin/runs/{run_id}/rating` | `require_admin`, so **404 and never 403** to everybody else | The same answers, except that an admin may rate an unowned run and any other account's run. Every write logs one `WARNING` naming the actor, the run id and the word, and never the note |
| `GET /api/runs` (the owner's history) | the caller's own runs | Each row gains `rating`, `rating_note` and `rated_at`, read in one statement for the whole page rather than one per row. `rated_by` is deliberately absent: the list is the caller's own runs |
| `GET /api/admin/runs` | admin | Each row gains `rating`, `rated_by` and `rated_at`, and a new query parameter `rating=good\|bad\|unsure\|unrated`. Any other word is a **422** naming the four. It is a `WHERE` clause like the other filters, so keyset paging is unaffected |
| `GET /api/admin/runs/{run_id}/decisions` | admin | Gains a `rating` object beside the mid-run gate replies. The object is always present; an unrated run answers four nulls inside it, so the drawer renders one control rather than branching on whether the key exists |
| `GET /api/admin/insights` | admin | Gains `labels` and one new finding rule, `rated_bad`. Section 5 |

That makes seventeen routes under `/api/admin`, sixteen of them behind
`require_admin` (`GET /whoami` is the documented exception). Count them off
`app.openapi()["paths"]`, never off a sentence.

**Only a terminal run can be rated.** `guard_rateable` imports
`registry.TERMINAL_STATUSES` rather than restating it, and refuses anything
else with 409 and one sentence both doors share. A *clear* is refused for the
same reason: there cannot be a rating on a run nobody could have rated.

**A run with no owner is written by an admin or by nobody.** An unowned run is
readable by everyone (that carve-out keeps pre-auth rows usable), so a
signed-in caller who tries to write one gets **403 naming the remedy** rather
than a 404, because the row is already visible to them and a 404 would
contradict the page they are looking at. The anonymous caller on an auth-off
deployment keeps the write, being that deployment's only author.

## 3. Storage

Four additive nullable columns on `runs`, in the table definition and in
`PostgresFlowPersistence._ADDITIVE_COLUMNS`, which is the same startup
migration that added `user_id` and the three run-ceiling columns:

| Column | Type | Holds |
| --- | --- | --- |
| `rating` | `VARCHAR(16)` | `good`, `bad`, `unsure`, or NULL for unrated |
| `rating_note` | `VARCHAR(512)` | The optional sentence, or NULL |
| `rated_by` | `VARCHAR(128)` | The actor, which is not always the owner |
| `rated_at` | `TIMESTAMP WITH TIME ZONE` | When |

Nothing is backfilled and nothing could be: every row written before this
shipped means "nobody has said". `rating = null` clears the note, the actor
and the timestamp with it.

**Last writer wins.** There is no compare-and-set, unlike the five other
`UPDATE … WHERE …; rowcount` paths in `persistence.py`. A 409 on a double
press would refuse with nothing to protect: an opinion has no lost-update
problem, because the second press *is* the newer opinion.

No new table, no history table, and the note is bounded twice on purpose: by
the request model, which answers 422 above it, and again by the column, which
is what a driver would truncate silently.

## 4. What reaches Langfuse, and what never does

### 4.1 The score

| Field | Value |
| --- | --- |
| `name` | `human_rating` |
| `score_id` | `f"{trace_id}-human_rating"`, where `trace_id` is `trace_id_for(run_id)` imported from `observability/backend.py` and never re-derived |
| Level | The **trace**. The observation is `None`, because a rating is about the whole run |
| `dataType` | Always `CATEGORICAL`, on every write, forever |
| `value` | The word itself: `good`, `bad` or `unsure` |
| `comment` | The note, and **only** when `LANGFUSE_CAPTURE_CONTENT=1`. It is off by default |
| `environment` | The exporter's own, so a synthetic run's rating cannot pollute a live view |

A clear writes no score. It **deletes** that one id, twice: once immediately,
and once again `config.RATING_SCORE_CLEAR_SWEEP_SECONDS` (45 s) later on a
daemon timer that asks the database first, so a person who re-rates inside the
window keeps their rating.

### 4.2 Why the id rule exists, which is the part worth reading

Three things were measured against Langfuse cloud on SDK 4.15.1, and each one
ruled out a design that had already been written:

1. **`create_score` with no id appends.** Rating a run `good` and then `bad`
   left **two** `human_rating` scores on the trace, and a clear left both while
   the app's own Postgres row read unrated. Every unit test was green through
   all of it, because a test asserts what the exporter was asked to send, and
   it was asked correctly each time. This was found by reading the real trace
   through the API.
2. **A fixed id upserts, and the type may only move one way.** Under one
   `score_id`, NUMERIC to CATEGORICAL is accepted; CATEGORICAL to NUMERIC is
   **silently ignored**, returning success and changing nothing.
   `client.api.legacy.score_v1.delete(id)` works and is the only delete
   available: the v2 score API has none.
3. **A delete and a create are not on the same clock.** `create_score` goes
   into the SDK's asynchronous batch queue; `delete_score` is a synchronous
   HTTP call. The first design wrote good/bad under a NUMERIC id and `unsure`
   under a CATEGORICAL one and deleted the loser on every write; four rating
   changes inside eight seconds left a stale score on the trace permanently,
   because the delete answered 404 against a create that was still queued and
   the create then landed behind it. A proof that spaced its writes 12 to 20 s
   apart could not see it. Ingestion lag on the upsert path was measured above
   12 s and under roughly 20 s, which is where the 45 s sweep comes from.

Hence: **one id, always CATEGORICAL, every write an upsert, and no delete
except a clear.** Four ratings a second apart then converge on the last one
however the queue reorders them, with no ordering assumption at all. Langfuse
counts a categorical score by value, which is the aggregate a three-word
vocabulary actually wants; a numeric mean would have had to invent a midpoint
for "not sure".

### 4.3 The second score, `gate_outcome`

On a gate-closed frame the exporter now also writes a CATEGORICAL score named
`gate_outcome` whose value is the outcome the frame carried (`approve` /
`revise`), attached to the node's task span if there is one and otherwise
outwards to the agent span, the node span or the trace. The gate-closed event
observation is unchanged; this is additive to it. It is what a person decided
*during* a run, and until now it was metadata on an event, which cannot be
charted or filtered the way a score can. It carries no `score_id`, because one
gate closing is one fact and there is nothing to overwrite.

Both names are facts about a run. Neither names an agent, a task, a tool, a
crew, a flow or a workflow of this repository, so
`tests/observability/test_no_flow_identifiers.py` passes over
`observability/scores.py` unmodified, and a planted identifier still fails it.

### 4.4 What never leaves

The note is free text a person typed. It is content, and it follows the
content policy exactly: absent by default, sent only under
`LANGFUSE_CAPTURE_CONTENT`, and decided in `observability/scores.py` rather
than at the transport. `service/governance_insights.py` never selects it, never
joins on it and never renders it. The admin lever's `WARNING` line names the
actor, the run and the word, and not the note.

**Telemetry never fails the button.** `record_run_rating` returns a bool the
routes ignore. An exporter that is off, unconfigured or unreachable returns
`False` and raises nothing, and the `PUT` still answers 200: a rating is a
person pressing a button, and Langfuse being down is not a reason that button
reports an error. The work happens on a bounded daemon worker joined for at
most 2.0 s, and both `PUT` doors hand the whole write to the threadpool,
because doing it on the event loop was measured to make a concurrent
`GET /healthz` take 2.012 s against 0.112 s.

## 5. What the admin console does with it

* **Runs**: a rating chip on every row, and a filter with a fourth option,
  `unrated`, which is a real question and the interesting one early on.
* **Drawer**: the rating is shown beside the gate replies and can be set there
  through the admin route.
* **Insights**: a `labels` block, `{good, bad, unsure, unrated}`, counted over
  the **same** scanned rows every other rule is counted over, so the strip and
  the findings can never describe different windows. When the scan was
  truncated or incomplete the panel says "at least", because these are lower
  bounds over unevenly covered evidence, exactly as the existing finding rates
  are.
* **One new deterministic rule, `rated_bad`**: per workflow, the runs a person
  marked `bad`. `node_id` is the literal `"(run)"`, because a rating is about
  the whole run and inventing a node id would point the console at a card
  nobody edited; `gate_id` is null; severity `high`, which ranks between
  `critical` and `warning`. It obeys the same floors as the other four rules
  (`GOVERNANCE_INSIGHTS_MIN_RUNS`, `GOVERNANCE_INSIGHTS_MIN_AFFECTED`) and
  carries the same sample shape. Its explanation ends with a clause the other
  four do not have, saying that this one is a person's own judgement rather
  than something the system worked out. A run rated `bad` is still counted by
  all four of the other rules: a run somebody disliked that also retried a
  guardrail is two facts, not one.

Nothing in Insights reads the note.

## 6. How to verify

Run the modules, do not read this page:

```powershell
$env:DATABASE_URL = "sqlite+pysqlite:///:memory:"   # see the note below
.\.venv\Scripts\python.exe -m unittest tests.service.test_run_rating -v
.\.venv\Scripts\python.exe -m unittest tests.observability.test_run_score_hook -v
.\.venv\Scripts\python.exe -m unittest tests.service.test_additive_migration -v
.\.venv\Scripts\python.exe -m unittest tests.service.test_governance_insights -v
.\.venv\Scripts\python.exe -m unittest tests.service.test_admin_fixture_shapes -v
```

`DATABASE_URL` has to be set explicitly on a machine whose `.env` points at a
local PostgreSQL container: `brief_crew/__init__.py` loads `.env` with
`override=True`, so without it the suite writes into the development database.
See [gotchas](../gotchas-and-insights.md) 87, which records that as open.

The PostgreSQL half needs the `pg18-test` container running and is not
skipped when it is:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.pg.test_rating_columns -v
```

Frontend: `frontend/tests/runRating.spec.ts`,
`frontend/tests/adminPanels.spec.ts`,
`frontend/tests/governanceInsights.spec.ts`.

### The free local proof, end to end

No money, no paid model, one real Langfuse project. Start a synthetic backend
with the exporter on:

```powershell
$env:SYNTHETIC = "1"
$env:SYNTHETIC_BRANCH_DELAY_SECONDS = "5"
$env:PORT = "8099"
$env:LANGFUSE_EXPORT_ENABLED = "1"
$env:LANGFUSE_PUBLIC_KEY = "<pk>"
$env:LANGFUSE_SECRET_KEY = "<sk>"
$env:LANGFUSE_ENVIRONMENT = "synthetic"
$env:CREDENTIALS_MASTER_KEY = "Y2ktcGxhY2Vob2xkZXItbm90LWEtbWFzdGVyLWtleSE="
.\.venv\Scripts\serve.exe
```

`LANGFUSE_ENVIRONMENT=synthetic` is not optional: a synthetic run's token
counts are fabricated and must not reach a live cost view.

Run a workflow to completion in the console, rate it Good, then read the score
back from Langfuse rather than from the app:

```text
GET {LANGFUSE_BASE_URL}/api/public/v2/scores?traceId=<trace hex>&name=human_rating
```

The trace hex is `UUID(run_id).hex`. Expect exactly **one** score, `CATEGORICAL`,
value `good`, id `<trace hex>-human_rating`. Re-rate it Bad and read again:
still one score, value `bad`, the same id. Clear it and read again: none.
Each read is free.

## 7. What is not built

Named here so nobody goes looking, and because the larger programme this was
ported from exists and is unmerged.

This is plan 18's LABEL step (criteria A9 to A13) hand-ported from branch
`admin/mining`. **Nothing else of plan 18 came with it**: no `improve_api.py`,
no Mine, no Compare, no Export, no Digest, no `document_version`, no
`improve_digests` table, no gate `proposed` / `corrections` fields. That
programme remains built, green and unmerged on its own branch.

Also not built, deliberately:

* **No ratings history.** Last writer wins and the previous value is gone.
  There is no `rating_events` table and no audit trail beyond the admin
  lever's log line.
* **No model reads a trace, a rating or a note.** There is no judge, no
  digest, no summary, no suggestion generated from anything a person typed.
* **No comparison and no export.** A rated cohort cannot be diffed against
  another or emitted as an eval set from here.
* **No rating from Langfuse back into the app.** The app is the source of
  truth and the trace is the mirror; a score edited in the Langfuse console is
  overwritten by the next write from here and is not read back.

## 8. Honest limits

* **A rating made while the exporter is off is never back-filled.** The mirror
  is written at the moment the button is pressed. Turn Langfuse on afterwards
  and every rating made before that moment is on the run row and not on any
  trace. Nothing re-sends them, and nothing reports how many there are. This
  is the one gap most likely to surprise somebody reading a filtered trace
  list. `CLAUDE.md` remaining-work item 67.
* **A CLI run has no trace, so it can have no score.** `validate --idea` and
  `run_crew` never enter the service's capture scope, so they have no run id
  and no session. That was a named cost of the exporter's layer decision, not
  a new one here.
* **The deferred clear sweep is in-process.** It is a daemon timer, bounded at
  256 pending sweeps with the oldest dropped. A restart inside the window loses
  it, and so does reaching the bound. What is lost is the *second* delete of a
  score whose first delete very probably worked; the app's own row is correct
  either way, and the recovery is to clear the rating again.
* **The rating is a person's opinion and is labelled as one.** `rated_bad`
  says so in its own explanation. It is not a measurement of output quality,
  it establishes no cause, and one account's taste is the only thing behind it
  on a single-rater deployment.
* **`unsure` is an answer, not a missing one.** Nothing turns it into a number
  between good and bad, on the wire, in the score or in the counts.
* **Ratings are counted over scanned rows.** Insights bounds every scan, so
  under a truncated window the label counts are lower bounds and the panel
  says so. They are not prevalence estimates and must not be compared across
  workflows.
