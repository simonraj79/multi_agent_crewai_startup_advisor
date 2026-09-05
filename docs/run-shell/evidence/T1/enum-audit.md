# T1.3 — every internal code that reaches the run shell, and what happened to it

Written 2026-09-05 on branch `run-shell/cast` by W1, merging the two
independent audits written for task 1 (`task1-A.md` §4 and `task1-B.md` §4) and
re-checking every line against the working tree before recording it.

**Scope.** `frontend/src/` outside the flow builder: the run shell's components,
its views, the composables that feed them and the data modules they read. The
builder workspace is out of scope — it is an authoring surface whose users are
the people who wrote the identifiers.

**What counts as a leak.** Text that reaches a `<template>`, an `aria-label` or
a `title`. A comparison, a type, a CSS class binding, a `data-*` attribute and
a comment do not: they are how the client reads the server, and moving them
behind a display table would buy nothing and cost the grep that finds them.
The mechanical form of the rule, which `frontend/tests/noRawCodes.spec.ts`
enforces, is `/\b[A-Z][A-Z0-9]+(_[A-Z0-9]+)+\b/` — a shout joined to another
shout by an underscore, which is the shape an identifier has and prose does
not.

**Line numbers are as of this branch on 2026-09-05 and three other workers are
editing four of these files concurrently.** Where a number has drifted, the
symbol named beside it is the durable reference.

**Dispositions.** `FIXED (W1)` — done in this branch by me. `W3` / `W5` — owned
by another worker in this same branch, named in §0 of
`docs/run-shell/DEFINITION-OF-DONE.md`. `TECHNICAL` — legitimately a code, with
the reason. `OPEN` — a real leak nobody on this branch owns.

---

## 1. The verdict panel — FIXED (W1)

The block this task started from, and the finding that reshaped it: **the
explanatory paragraph was false on the exact screen it was written for.**
`Verdict.compute_mechanical_result` (`src/brief_crew/schemas/validator.py`,
:538-566) computes `fatal_floors` and `decision_reason` *independently* — the
floors are collected unconditionally, then a separate ladder picks the reason
and its **first** branch is `confidence < 0.35 → INSUFFICIENT_EVIDENCE`. So a
run at 34% confidence with `market == 0` carried `FLOOR_NO_MARKET` in the list
while that floor decided nothing, and the panel's loudest block asserted the
opposite ("It, not the arithmetic, is why this run reads NEEDS_WORK") over a
bare, unexplained `INSUFFICIENT_EVIDENCE` line underneath.

| Site | What rendered | Disposition |
| --- | --- | --- |
| `ReportPanel.vue` verdict badge | `NEEDS_WORK` | FIXED — `verdictLabel()`; DOM text is `Needs work`, the shout is `text-transform` in CSS, the enum is `data-code` |
| `ReportPanel.vue` band chip | `LOW` beside `34% confidence` | FIXED — one chip, `Low confidence · 34%` |
| `ReportPanel.vue` provisional chip | literal `PROVISIONAL` | FIXED — `Provisional · not a final answer`. The head word is kept because `validator_guardrails.py` requires the markdown body below to carry "Provisional" in its own title; two names for one thing is worse than one unfamiliar one |
| `ReportPanel.vue` thin chip | `Thin evidence: D, C, F, X` | FIXED — `Thin evidence · Demand, Competitive room, Feasibility and Headroom over free`; all five collapse to `all five dimensions` |
| `ReportPanel.vue` floor list | `Already free` beside `<code>FLOOR_ALREADY_FREE</code>` | FIXED — block deleted; the code moved to `data-code`, so it is still greppable from the DOM and no longer in the reading path |
| `ReportPanel.vue` `.verdict-reason` | a bare `INSUFFICIENT_EVIDENCE` as body prose | FIXED — deleted; it is the block's headline now |
| `ReportPanel.vue` explanatory `<p>` | `…is why this run reads NEEDS_WORK` | FIXED — deleted, and it was false as well as leaky |
| `ReportPanel.vue` no-verdict badge | `COMPLETE` | FIXED — `Finished` |
| `ReportPanel.vue` score labels | `sentenceCase(key.replaceAll('_',' '))` | FIXED — `DIMENSIONS` table; correct by luck before, and each row now carries its ladder's own question from `tasks.yaml` |

The replacement is keyed on `decision_reason` and demotes non-deciding floors
to an `ALSO BLOCKING` sub-line inside the same block, in the conditional tense
("On stronger evidence that alone would reject the idea") — which is the case
the old design could not express at all.

## 2. The verdict gate — FIXED (W1)

`GateCard.vue`, the screen where an operator approves or revises a decision,
and the densest concentration of raw codes in the console.

| Site | What rendered | Disposition |
| --- | --- | --- |
| `.verdict-row strong` | `NEEDS_WORK` | FIXED — `verdictLabel()`, code kept in `data-code` |
| `<dt>{{ label(item.key) }}</dt>` + CSS `uppercase` | `MEDIAN MARKET SOURCE AGE MONTHS`, `BRANCHES OK`, `KILL CRITERIA` | FIXED — `humaniseCode`, and the `text-transform: uppercase` removed: a humanised key shouted still reads as a constant name |
| `<pre v-if="item.kind === 'json'">` | the whole payload verbatim — `[]`, `null`, `false`, `NEEDS_WORK`, `HIGH`, plus JSON blocks | FIXED — labelled rows: `null → —`, `[] → none`, booleans → `yes`/`no`, enums through the same table the report reads, objects as a one-level key/value list, anything deeper behind a collapsed `<details>` holding the pretty JSON |
| `.gate-field span` + CSS `uppercase` | `feedback`, `target user` | FIXED — `Feedback`, `Target user` |
| `.gate-derived-note` | "Recomputed from the five dimension scores…" | FIXED — generic: "Recomputed by the server from the scores and the evidence behind them" |

**Latent and not fixed here:** `gate.title` falls back to `authored.label or node_id`
(`service/registry.py`), so an unlabelled builder gate titles the card
`n1_confirm`. That is a *server* fallback on a surface the operator authored;
it is recorded under §6 rather than patched from the client.

## 3. The canvas edge chips — FIXED (W1)

`WorkflowEdge.vue` rendered `data.label`, which `service/graph.py` sets to the
raw `router_event`. `scope_approved`, `scope_revise`, `verdict_approved` and
`verdict_revise` were painted on the graph itself. Now through `humaniseCode`
("Scope approved"), with the id kept in `data-code` so every existing
id-keyed assertion still resolves.

## 4. Run status, three renderings of one enum — PART FIXED (W1), rest W5

Three surfaces rendered the status and none of them was a lookup, so the same
run read `failed` in the history list and `error` in the status rail — the
client contradicting itself about one fact, because `studioApi.ts` normalises
the live run's status and not the history rows'.

| Site | What rendered | Disposition |
| --- | --- | --- |
| `RunHistory.vue` `.run-history-status` | the un-normalised `BackendRunStatus`: `failed`, `cancelling` | FIXED — `runStatusDisplay()` |
| `StatusPanel.vue` `statusLabel` | `status.replace('_',' ')` over CSS `capitalize` | **W5** — `data/runStatusDisplay.ts` was written first for this reason |
| `StudioView.vue:367` `{{ status }}` | lower-case `queued` / `error`, no transform at all | **W5** |
| `StatusPanel.vue` `connectionLabel` | raw `connecting` / `reconnecting` / `offline` beside a human `Mock stream` | **W5** |
| `StudioView.vue:152` second `connectionLabel` | a different vocabulary again | **W5** |

`frontend/src/data/runStatusDisplay.ts` covers **both** unions in
`types/studio.ts` — `RunStatus` and `BackendRunStatus` — and maps the two pairs
that are one state under two spellings (`error`/`failed`, `stopping`/`cancelling`)
to one word and one tone. That is the whole fix for the contradiction.

## 5. The activity trace and the dialogue rail — W3

The largest surface by volume, and it is not a wording bug in any component:
`ChatRail.vue:188` renders `entry.message`, which is `frame.message` copied
through, and `events/serializer.py` composes that from Python identifiers —
`scope_idea started`, `persist started`, `ValidatorFlow completed`,
`reporting_task completed`, `route_scope routed to scope_approved`. Every one
appears dozens of times per run.

| Site | What rendered | Disposition |
| --- | --- | --- |
| `ChatRail.vue:188` `entry.message` | the whole trace, as Python log lines | **W3** — the interpretation layer in `src/trace/` |
| `ChatRail.vue:184` `entry.actor` | falls back to `frame.node_id`: `unattributed`, `n1_confirm` | **W3** |
| `ChatRail.vue` call chips | `String(details.tool ?? details.model ?? frame.kind)` — a tool function name, a model id, or the bare kind `llm` | **W3** |
| `DialogueRail.vue:202` `row.entry.role` | derived by regex-stripping `started\|completed\|failed` off the log line, so a task event names the speaker `reporting_task` | **W3** |
| `DialogueRail.vue:203` `row.entry.task` | `details.task` = `_task_name`: `reporting_task`, or the literal `Task` | **W3** |
| `DialogueRail.vue:198` initials | `RE` for `reporting_task` | **W3** |
| `StatusPanel.vue` error banner | `frame.message` verbatim → `write_report failed` | **W5**, with W3's interpreter |
| `GateCard.vue` summary fallback | `frame.message` → `confirm_scope paused` | **W3** (the summary is composed upstream) |

**Not a leak, and checked deliberately so nobody re-checks it:** `event_type`
(`NODE_START`, `GATE_OPEN`, `VERDICT_COMPUTED`) is read only in comparisons in
`useValidatorRun.ts`; no run-shell template binds it. Likewise `tool_status`
(`ok`/`empty`/`rate_limited`/`failed`), `CACHE_HIT`/`CACHE_MISS` and
`from_cache` are on the wire and no client file reads those keys — a
missing-information gap, not a leak.

## 6. Latent leaks on the published-builder-graph path — OPEN

These render correctly for the hand-written validator graph and leak the moment
a node is not in the descriptor: a quarantined frame, or any user-authored
graph, which is a first-class run in this console.

| Site | Renders | Note |
| --- | --- | --- |
| `WorkflowNode.vue:298/299` `data.label` / `data.description` | the server's fallback is `node_id.replace("_"," ").title()` → `Route Scope`, `Check Cache` | title-cased, so it evades the regex; still an identifier |
| `WorkflowNode.vue:94-95` | `3 unattributed frames`, node label `Unattributed` | `QUARANTINE_NODE_ID` used as the user-facing word |
| `WorkflowNode.vue:307/308` `data.model` / `data.tool` | human in the mock, a raw id on a builder graph | |
| `CrewProgress.vue` stage label | `n1_confirm` for an unlabelled authored node; `Stage 3` when the plan frame carries no label | |
| `CrewProgress.vue` branch tooltip | `` `${branch.label}: ${branch.state}` `` → `research_market: running` | |
| `GateCard.vue` `gate.title` | `n1_confirm` for an unlabelled authored gate | §2 |
| `StudioView.vue:515` | `` `${inputField.replaceAll('_',' ').toUpperCase()} TO RUN` `` → `CUSTOMER URL TO RUN` | shouts an author's field name |
| `RunHistory.vue:145` | `run.label \|\| run.run_id.slice(0, 8)` — an 8-char hex fragment as a row title | wording, not an enum; left alone because a run has no better name and inventing one ("Run from 14:02") loses the id the operator pastes into a bug report |

None of these matches the regex today, because they are title-cased, spaced or
hex. They are recorded because the *class* is the same and the next flow will
surface them.

## 7. Legitimately technical — left alone, deliberately

| Site | Token | Why it stays |
| --- | --- | --- |
| `StatusPanel.vue` download options | `NDJSON`, `ZIP` | file formats; the operator is choosing one. Allowlisted in `noRawCodes.spec.ts` |
| `StatusPanel.vue` run id | the id in a `<code>` with the full value as `title` | the identifier the operator quotes in a bug report |
| `StudioView.vue:368` `descriptor.version` | a graph fingerprint in a `<code>` | worth a `title` explaining what it is; not worth humanising |
| `StudioView.vue:474` `handoff.inputField` | in a `<code>` | the API contract the graph's own author chose |
| `StatusPanel.vue` transport problem | names `VITE_API_URL` | a human sentence whose whole job is to name a misconfigured build variable (gotcha 2) |
| `ReportPanel.vue` / `GateCard.vue` `data-code` | every code this branch removed from the reading path | still in the DOM, still greppable, no longer read |
| the markdown report body | whatever the Reporter wrote | the report's own content, not a constant the client leaked |

Borderline, and better behind a diagnostics toggle than humanised:
`StatusPanel.vue`'s `seq 143` and `2 dropped`. They are real stream
diagnostics sitting in an operator's panel.

## 8. Where the two source audits disagreed

Both proposals swept independently; three differences are worth recording
because each was resolved by reading the code rather than by preferring an
author.

1. **The band enum.** A named it `MODERATE` (correct, `validator.py:38`); the
   brief supposed `MEDIUM`. `CONFIDENCE_BANDS` maps both, so a flow spelling it
   the other way reads correctly instead of falling through to the humaniser.
2. **Whether the raw floor token should stay on screen.** A argued the existing
   `<code>` served a developer at an operator's expense and should move to
   `data-code`; B agreed independently. Both are implemented — the token is on
   the element, not in the text.
3. **The block's key.** A and B reached the same conclusion from opposite
   directions: the block must key on `decision_reason`, not `fatal_floors`.
   That agreement is the strongest single result of the two-proposal exercise,
   because it is the one that made the old copy *false* rather than merely
   jargonish.
