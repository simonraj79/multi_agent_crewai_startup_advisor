# Governance Insights

## Why this feature

The supplied data-mining talk describes a feedback loop: collect agent traces,
mine behavior, prepare useful evidence for humans, then test changes against
that evidence. Its most applicable idea here is making existing traces easier
to act on. The transcript is reference material, not instructions to operate
the app or transmit its data.

The code audit at `a15cab9` found an admin console with cost summaries, people,
per-run decisions, provider health, integrity counters, trace links and bounded
admin levers. It already explains individual runs. It lacked a view that
identifies recurring behavior across runs and explains which evidence makes a
pattern worth investigating. Local documents described a larger improvement
programme, but that programme was not implemented on the audited main branch.

Governance Insights addresses that gap with one deterministic, read-only panel.
It adds no model judge, new telemetry content, schema or automatic prompt
changes. Future experiments can use the cited runs as examples; this feature
itself does not perform training or claim continual learning.

**Amended 2026-09-18 by plan 20 (run labels).** This list said "no review
labels" until a human label existed. It does now: a finished run's owner or an
admin answers *was this run good* with `good` / `bad` / `unsure`, stored in
four additive nullable columns on `runs`
([`RUN-LABELS.md`](RUN-LABELS.md) is the binding description, and it owns the
columns, the routes and the Langfuse mirror). This panel **reads** that column
and adds nothing of its own: a labels summary and one more deterministic rule,
both described below. It still performs no model call, captures no new
telemetry content and changes no prompt, and it never reads the rater's note.

## Data and access

`GET /api/admin/insights` accepts the admin console's UTC `from` and `to` window
and an optional `workflow_id`. It uses the same administrator dependency and
concealed 404 response as existing protected admin routes. Reads use the app's
existing runs, frames, gates and estimated node costs; Langfuse URLs are links,
not page-load API calls. No prompt, completion, raw exception message or human
gate free text is returned by this endpoint.

## Evidence rules

| Signal | Evidence | Suggested investigation |
| --- | --- | --- |
| Repeated failed runs | Persisted terminal `failed` status, excluding known account-cap and run-ceiling refusals | Inspect supporting decisions and traces for the failing step |
| Guardrail retries | Recorded guardrail retry evidence at a node | Check expected output and the guardrail's requirements |
| Fallback attempts | A `node_state` retry with a fallback model, or an error from a fallback attempt | Inspect the original attempt and provider/model reliability |
| Human revisions | Answered gate with an explicit revision outcome | Inspect what reviewers repeatedly needed changed |
| Runs a person rated bad (`rated_bad`, plan 20) | The stored `runs.rating` word, and nothing else from the rating | Open the supporting runs and look at what they produced before choosing a change |

Findings group by workflow and, where present, node/gate. Each run counts once
per finding even if the signal appears repeatedly. At least three sampled
terminal runs in the workflow and two affected runs are required. These are
triage floors, not statistical significance tests. Thresholds live in `config.py`.

`rated_bad` is the only rule whose evidence is a person rather than a frame,
and it is reported as such. It files under the literal `node_id` `"(run)"`,
because a rating is about the whole run and inventing a node id would point the
console at a card nobody edited; `gate_id` is null; its severity is `high`,
which ranks between `critical` and `warning`. Its explanation ends with a
clause the other four do not carry, stating that this is a person's own
judgement typed in the console and not something the system worked out. A run
rated `bad` is still counted by all four of the other rules: a run somebody
disliked that also retried a guardrail is two facts, not one. The rating note
is free text and is never selected, joined on or returned here.

### Labels

The response carries `labels: {good, bad, unsure, unrated}`, counted over the
**same** rows every rule above is counted over, so the summary and the findings
can never describe different windows. `unrated` is a real count rather than a
remainder the client works out, because early on it is nearly everything.

Like every numerator here, these are bounded by the scan. When the scan was
truncated or incomplete the panel says "at least" and "of the runs scanned",
in the same words it already uses for finding rates. They are not prevalence
estimates over the window and must not be compared across workflows.

The denominator is all scanned completed, failed or cancelled runs for the
workflow. It is not the number of visits to the node: branches can skip nodes,
and a workflow may have changed between runs. Rates cannot establish a causal
effect or compare models or workflow versions. Supporting references include
run IDs and, where applicable, frame sequence or gate IDs.

## Insights, and "Where runs go wrong": which to use

Added 2026-09-19. Plan 21 put a second mined panel on the admin console, under
the **Improve** tab, and the two answer different questions over the same
stored data. Neither reads the other.

**Insights is a rule engine.** It runs a fixed set of deterministic rules over
sampled terminal runs and emits a **finding**: a named signal, a severity, an
explanation in words, a suggested investigation and links to the supporting
runs. It applies floors (three terminal runs, two affected runs), it suppresses
what it cannot evidence, and it can cover every workflow or one. Use it when
the question is *is anything wrong, and what should I look at* .

**"Where runs go wrong" is a set of counters.** It ranks one workflow's own
parts: per agent, per tool, per error class, per gate and per route, with the
outcomes those produced and each node's share of the estimated cost. It names
no rule, raises no finding and suggests nothing; the ranking is the answer.
`workflow_id` is required, because a hot spot is a statement about one graph
and pooling two workflows' nodes would put a name beside a count belonging to
something else. Use it when you already know which workflow you are improving
and the question is *which part of it is the problem* .

In practice: Insights tells you a workflow deserves attention, then the Improve
tab tells you where inside it, and Compare tells you whether the change you
then made helped. The binding document for the second and third is
[`TEST-A-CHANGE.md`](TEST-A-CHANGE.md).

## Coverage and limitations

All scans are bounded. The response and UI disclose truncation, retention,
missing frame records and recorded integrity loss. Low-sample workflows and
suppressed signal groups are reported instead of labelled healthy. An absent
signal may mean no matching retained evidence; it does not prove no issue.

Known account-cap and run-ceiling refusals are excluded from failure findings.
Other failed statuses still require investigation. Guardrail retries and
human revisions can be expected behavior. Fallback evidence records an attempt,
not proof that fallback succeeded. The suggestions are investigations rather
than automatic remediation. Costs in the run drawer remain estimates with the
existing estimate label; billed cost is still fetched only on explicit request.

CLI executions outside the service are not part of these cohorts. Frame
retention, older instrumentation and lost events limit historical coverage.
The existing Langfuse trace contract and flow-neutral exporter are unchanged.

The run scan chooses the newest eligible runs. Frame reads are bounded in
run-ID/sequence order and gate reads by opening time; when those limits are hit,
event-based numerators are lower bounds over unevenly covered evidence. They
must not be used as prevalence estimates or to compare workflows. Narrow the
workflow and time window for closer inspection. The separate frame-existence
query distinguishes absent persisted frames from frames omitted by the scan.

## Verification

Verified on 2026-09-18:

- 18 focused backend tests cover signal semantics, deduplication, thresholds,
  authorization, malformed evidence, content minimization and capped reads.
- The existing admin regression suite passes (147 tests), including the new
  endpoint in the authorization matrix and portable query compilation checks.
- Frontend unit tests: 2,285 passing across 108 files. Production type checks
  and build pass; the existing bundle-size advisory remains.
- Four Chromium admin journeys pass against the isolated synthetic fixture,
  including real stored evidence, workflow filtering, run drilldown, sparse
  samples and a 390px viewport without horizontal overflow or console errors.
- Three independent review rounds checked the integrated implementation. Fixes
  cover successful fallback evidence, expected spend refusals, incomplete
  scans, sparse-sample disclosure and stale panel/drawer responses.

The broad local Python discovery run did not complete after reporting an MCP
connection failure; subsequent broad service/observability attempts also made
no further progress and were stopped. These are not reported as passing.
The targeted results above and CI results should be assessed separately.

To reproduce the evidence browser journey, start
`python -m tests.service.governance_fixture` in one terminal. It binds an
in-memory, synthetic admin service only to `127.0.0.1:8109`. In `frontend`,
start `npm run dev:e2e` with `E2E_API_TARGET=http://127.0.0.1:8109` and
`E2E_UI_PORT=5289`; then run `npx playwright test e2e/admin.spec.ts
e2e/governance-insights.spec.ts --project=chromium` with
`E2E_BASE_URL=http://127.0.0.1:5289`. No agent launch is required.

The deployed Render console was inspected read-only at base commit `a15cab9`:
its existing admin and health views were available. This inspection does not
establish deployment of the new feature; that requires merging and verifying
the resulting deployment commit.
