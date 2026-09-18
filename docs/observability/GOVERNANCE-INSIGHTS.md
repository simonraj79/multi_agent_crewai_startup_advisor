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
It adds no model judge, new telemetry content, schema, review labels or automatic
prompt changes. Future experiments can use the cited runs as examples; this
feature itself does not perform training or claim continual learning.

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

Findings group by workflow and, where present, node/gate. Each run counts once
per finding even if the signal appears repeatedly. At least three sampled
terminal runs in the workflow and two affected runs are required. These are
triage floors, not statistical significance tests. Thresholds live in `config.py`.

The denominator is all scanned completed, failed or cancelled runs for the
workflow. It is not the number of visits to the node: branches can skip nodes,
and a workflow may have changed between runs. Rates cannot establish a causal
effect or compare models or workflow versions. Supporting references include
run IDs and, where applicable, frame sequence or gate IDs.

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
