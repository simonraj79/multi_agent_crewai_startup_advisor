# Validator Studio Feature List

Source: [`PRD.md`](../PRD.md), dated 2026-08-29.

Validator Studio is additive to the existing Brief Crew. It combines a six-agent CrewAI startup validator with a live Vue 3 graph interface, durable human approval gates, structured evidence, and deterministic scoring.

## Implementation Status

Last reconciled: 2026-08-29 (second pass), against source and executable tests
rather than against prose. Every row below names the test or the source path it
rests on; a row with neither is not evidence.

Status meanings: **Not started** has no implementation; **In progress** has an active implementation slice; **Partial** has verified behavior but incomplete acceptance criteria; **Complete** has passing executable acceptance evidence; **Blocked** has an external dependency preventing completion.

**Complete means a criterion that a machine checked.** A feature whose acceptance criterion is a *measurement that has never been taken* is **Partial**, however finished the code looks. A feature that ships but has no test is **Partial**, not Complete.

### Measured baseline for this pass

⚠️ **These counts move.** The suite was being extended by other work while this
reconciliation ran: it went 295 → 341 Python tests and 103 → 116 frontend tests
between the first and last run of this pass. Re-run before quoting a number.
Every row below was checked against the later state.

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -t .
# Ran 341 tests ... OK (skipped=1)

Push-Location frontend; npm test; Pop-Location
# Test Files 11 passed (11) | Tests 116 passed (116)
```

| Directory | Tests |
|---|---|
| `tests/events/` | 6 |
| `tests/integration/` | 19 (`test_validator_service` 9, `test_ws_gate_replies` 10) |
| `tests/perf/` | 58 (`test_perf_arms` 18, `test_perf_metrics` 40) |
| `tests/service/` | 64 (`test_app` 5, `test_gate_expiry` 12, `test_gate_fields` 17, `test_graph_registry` 6, `test_observability` 19, `test_persistence` 5) |
| `tests/tools/` | 43 (`test_indexing` 23, `test_github_feasibility` 8, `test_hn_sentiment` 6, `test_market_research` 4, `test_pinecone_retrieval` 2) |
| `tests/validator/` | 128 (`test_cache` 8, `test_crews` 19, `test_flow` 21, `test_guardrails` 51, `test_schemas` 29) |
| `tests/test_brief_crew_regression.py` | 23 |
| `frontend/tests/` | 116 across 11 spec files |

### ⚠️ Read this before trusting any status below

**1. Both discovery gaps from the previous pass are closed.** `tests/events/`
and `tests/service/` now have `__init__.py`, so `unittest discover` reaches
them; the 341 above is the whole suite, not a subset. The **†** marks used in
the previous revision of this file are gone because nothing is undiscovered any
more. Standing rule: add a test directory's `__init__.py` in the same commit as
the directory, or discovery hides it and reports `OK`.

**2. The frontend now has a test runner.** Vitest + jsdom, 116 tests over 11
spec files. F32-F39 can therefore be judged on evidence rather than capped at
Partial by default — several still fall short on their own criteria, and those
rows say which clause.

**3. Nothing has still been run against paid services.** Every Python test uses
doubles, mocks, `create_app(synthetic=True)` or injected crew factories. No live
OpenRouter / Firecrawl / HN / GitHub / Pinecone / Cohere run has happened, so
**F42 and half of F43 remain unmeasured, not merely untested.**

**4. The rubric ladders are audited, not reviewed.** `RUBRIC_ANCHORS` in
`config.py` binds every verdict at 0.85 token overlap. PRD §10.2 wrote out only
the Demand ladder and labelled it *"Illustrative"*; M/C/F/X are a derivation, and
the PRD's own Demand ladder was itself defective in three ways (now corrected in
PRD §10.2). The ladders pass tests. No human has read them.

### Milestone status

| Milestone | Features | Status | Verified evidence, and what is missing |
|---|---|---|---|
| M-1 Prerequisites | F25 plus event and persistence prerequisites | **Partial** | `BriefFlow.check_cache` returns `Literal["cache_hit", "cache_miss"]`; both router edges appear in the derived graph — `tests/test_brief_crew_regression.py::GraphIntrospectionTests` (2 tests), `tests/service/test_graph_registry.py::test_brief_flow_graph_has_both_router_branches`, `tests/integration/test_validator_service.py::test_both_graphs_are_exposed_with_derived_routes`. `PostgresFlowPersistence` round-trips — but on **SQLite only**. |
| M0 Event spine | F19-F24 | **Partial** | All six `tests/events/test_spine.py` tests are now discovered, and `tests/service/test_observability.py` (19 tests) adds METRICS emission and coalescing, the unattributed count in run status and across recovery, writer cadence, handler latency and run eviction. The one criterion still unmet is **F22's "one loading bubble per active node"** — chips are per call in a flat chronological list. |
| M1 Service | F25-F31 | **Partial** | All 11 endpoints exist and are covered across `tests/integration/` (19) and `tests/service/` (64): both graphs and ETag, two gate round trips over HTTP *and* WebSocket, 409 on duplicates, gapless frames, replay + ping/pong, NDJSON and ZIP, cancellation, gate expiry, run eviction, frame-writer cadence, durable recovery in a fresh app. Missing: any **PostgreSQL** exercise (F31), and F26's queueing under `RUN_CONCURRENCY > 1` is asserted on the executor's configuration rather than on an observed queued-then-started run. |
| M2 Studio | F32-F39 | **Partial** | A real Vue 3 + Vue Flow application with 116 Vitest tests over 11 files, including a spec that asserts `MOCK_GRAPH` matches the live descriptor node-for-node and edge-for-edge. Unmet criteria remain in **F34** (no sprites at all), **F35** (no sprite along the path, no path-length duration, no shared `<defs>`, no self-loop), **F36** (4 entry variants of the 7 named, no `ResizeObserver`), **F37** (evidence gaps still absent from the verdict card, and the node has no `expired` state), **F38** (no workflow selection) and **F39** (guardrail exhaustion is unrepresented). |
| M3 Validator | F01-F18, F40, F42 | **Partial** | 171 discovered tests across `tests/validator/` (128) and `tests/tools/` (43) cover the schemas, the deterministic verdict, all five rubric ladders and their evidence support, the guardrails, all three tools, the branch cache and the three-way fan-out. **F42 has still never been measured** — the harness exists and is tested, the run has not happened. |
| M4 Gates | F03, F12, F27, F37 | **Partial** | Both native `@human_feedback` gates pause, persist and resume across a fresh app instance; server-side expiry runs an `expired` → `alerted` watch ladder that never auto-answers (`tests/service/test_gate_expiry.py`, 12 tests); gate replies now land over **both** HTTP and the WebSocket through one compare-and-set (`tests/integration/test_ws_gate_replies.py`, 10 tests). The WS slice that made this "In progress" is finished, and the verdict gate now sends the whole `Verdict` as read-only `derived` fields, so the rubric *is* on the card (`tests/service/test_gate_fields.py`, 17 tests; `frontend/tests/gateDerived.spec.ts`, 13 tests). What remains is UI content, not transport: the branch **evidence gaps** are still not carried to the gate, because `Verdict` has no gaps field. |
| M5 Hardening | F23-F24, F29-F31, F41-F44 | **Partial** | Usage accounting, backpressure, log export, run eviction and durable persistence are implemented and tested. `render.yaml` (with `maxShutdownDelaySeconds: 300` and `postgresMajorVersion: "18"`), `Dockerfile` and `.github/workflows/ci.yml` exist but have **never been applied to a host**. F42 unmeasured; F43's acceptance set does not exist. |

### Feature Evidence Ledger

Every test path below was run in this pass. Counts are from
`python -m unittest <module>`.

#### Core validation workflow

| Feature | Status | Evidence, and what is missing |
|---|---|---|
| F01 Startup Idea Submission | **Partial** | `run_id` is a fresh UUID under a caller-supplied `session_id` (`service/registry.py::create_run`); queueing is a `ThreadPoolExecutor(max_workers=RUN_CONCURRENCY)`; all seven states exist in `service/models.RunStatus`. Tests: `tests/integration/test_validator_service.py::test_two_gate_round_trips_duplicate_replay_and_logs`, `tests/service/test_graph_registry.py::test_default_executor_uses_configured_run_concurrency`. Missing: the CLI (`validator_flow.py::_build_parser`) accepts `--idea`, `--resume`, `--feedback`, `--namespace`, `--feasibility-cache` and `--no-gates` but **no `--session-id`**; the Studio's primary action is only ever `Launch`/`Relaunch`, so the criterion's "Send" affordance does not exist. |
| F02 Structured Idea Scoping | **Partial** | Scoper on `ESCALATION_MODEL` with `tools=[]`, asserted by `tests/validator/test_crews.py::test_single_agent_crews_use_expected_models_and_tool_surfaces`. `ScopedIdea` carries every required field including 3-5 `assumptions` and `as_of`. Query lists are joined with `"\n".join(...)` before interpolation. Missing, unchanged: **query quality is not validated at all** — `validator_guardrails.scope_problems` checks the assumption count and that at least one scoping gap is named, and nothing else; "category-based queries rather than generic keyword appending" exists only as prompt prose. |
| F03 Scope Confirmation Gate | **Complete** | Native `@human_feedback` pause, editable fields, deterministic `@router` with zero LLM calls, durable pending feedback, resume across a fresh app instance — `tests/integration/test_validator_service.py::test_two_gate_round_trips_duplicate_replay_and_logs`, `::test_pending_gate_recovers_and_resumes_in_a_new_app`. Expiry: a background sweeper advances an unanswered gate along an `expired` → `alerted` ladder that leaves `answered_at` NULL, so the run stays `waiting`, is never auto-answered, and a late reply still resumes it — `tests/service/test_gate_expiry.py` (12 tests) plus `tests/integration/test_ws_gate_replies.py::WebSocketLateGateReplyTests`. |
| F04 Parallel Research Fan-Out | **Partial** | Three sibling `@listen("scope_approved")` methods with an `and_()` join, one single-agent Crew each, all three distinct graph nodes. `tests/validator/test_flow.py::test_no_gate_flow_fans_out_transitions_and_persists` asserts a measured `ConcurrencyTracker.maximum == 3`; `::test_flow_definition_has_three_siblings_and_one_join` asserts the topology. **The sequential fallback now exists** — `VALIDATOR_SEQUENTIAL_BRANCHES` plus a per-branch turnstile with `VALIDATOR_BRANCH_TURN_TIMEOUT_SECONDS`, so R-3's withdrawal is a deploy-time flip. Held at Partial because the criterion the fallback exists to serve (F42) has never been measured, so nobody knows whether it is needed. |
| F05 Market Landscape Research | **Partial** | Cheap-tier analyst + Firecrawl search-with-scrape; both `Document.url` and `metadata.source_url` shapes handled; plan/rate-limit detection is substring- and status-code-based with no hard-coded quota. `MarketFindings.paying_segments` now exists with its own validator, and `Evidence.dated_is_retrieval_time` is set on every row that fell back to the retrieval timestamp. Tests: `tests/tools/test_market_research.py` (4). Missing: `MarketFindings` still carries **no `retrieved_at`** (the retrieval time lives on the tool envelope only), and the 402 / "plan limit" branch is still untested. |
| F06 Community Sentiment Research | **Partial** | HN Algolia story search then comment-tree retrieval; citations always derived from `objectID`, so a null `story_url` cannot break them; 429 detected without reading rate-limit headers. **`Thread.points` and `num_comments` are now populated** — `tools/hn_sentiment.py::_story_metric` reads them from the Algolia story record and the envelope notes stories that reported none. Tests: `tests/tools/test_hn_sentiment.py` (6). Missing: there is still **no back-off** — on 429 the tool raises, discards partials and returns `rate_limited`. |
| F07 Technical Feasibility Research | **Partial** | Module-level shared token buckets at exactly 8/24 req-min, `User-Agent` on every request, honest `rate_limited`, relevance/license/activity capture. **`Repo.archived` is now populated** — `tools/github_feasibility.py::_archived` reads it from the search item or the detail payload, stays tri-state, and the envelope notes how many results reported none. Tests: `tests/tools/test_github_feasibility.py` (8). Missing: "implementation signals" is still only a token-overlap heuristic, and the raw SPDX identifier is reduced to a boolean rather than carried. |
| F08 Structured Tool Results and Evidence Closure | **Partial** | All three tools return the seven-key envelope; URL-less results are dropped with a note; `URL_CLOSURE` rejects findings URLs outside the captured set; failed/empty/rate-limited status forces empty sources plus an explicit gap, and for market also forces `paying_segments` empty. Tests: `tests/validator/test_guardrails.py` findings cases. Missing, unchanged: the recording tool subclasses and `_capture_urls` in `validator_crew.py` have **no direct test**; at the report stage the allowed set is re-derived from findings rather than from the recorded raw tool URLs. |
| F09 Evidence Synthesis | **Partial** | Synthesist on escalation tier with `tools=[]`, consuming all three branches only after `and_()`; five anchored `DimensionScore`s; evidence counts recomputed and enforced by exact equality. **Reasoning effort is now explicit** — `VALIDATOR_SYNTHESIST_REASONING_EFFORT = "high"`, delivered through `openrouter_reasoning_params()` into `LLM(additional_params=...)` because `reasoning_effort=` is silently dropped for OpenRouter in CrewAI 1.15.18. Remaining divergence, deliberate: the model's kill-criteria candidates are discarded and replaced by the computed floor list, and there is no separate draft verdict. |
| F10 Deterministic Rubric and Verdict | **Complete** | `Verdict.compute_mechanical_result` computes composite, verdict, confidence, band and provisional in a `@model_validator(mode="after")`. `tests/validator/test_schemas.py` (29 tests) submits a fixture with deliberately wrong model arithmetic and asserts every field is overwritten; covers the 7.0 and 4.0 thresholds at the boundary, all four floors, floor ordering, and confidence-override-before-floors. Reproducibility is a property of a pure validator on a frozen model rather than a dedicated two-run test. |
| F11 Mechanical Confidence Scoring | **Complete** | Weighted coverage, staleness multiplier, the 0.60 branch penalty and all three band boundaries are computed and tested; provisional labelling is enforced in **both** title and summary; LOW-confidence wording is rejected. The previous gap is closed: `validator_guardrails.compute_confidence_inputs` now **recomputes** the three coverage ratios and the median market-source age from the branch findings and rejects the model's assertions against them, and `_market_source_age_months` returns `None` for a row dated by the retrieval clock so an undated page cannot read as fresh. `VALIDATOR_COVERAGE_TARGET_SOURCES` and `VALIDATOR_DAYS_PER_MONTH` carry the constants. |
| F12 Verdict Review Gate | **Partial** | Second native gate pauses after synthesis, routes deterministically, and preserves a structured operator override. The rubric gap is closed: the gate payload now splits into `fields` (editable) and `derived` (read-only), and for `review_verdict` **every** `Verdict` key is derived — the five `DimensionScore` objects with their `anchor_matched` and `evidence_urls`, `evidence_counts`, the three coverages, `kill_criteria`, `cheapest_next_test`, and the seven recomputed arithmetic fields. `fields` is *pruned* rather than annotated, so a stale client cannot keep offering an edit the server would discard. Tests: `tests/service/test_gate_fields.py` (17), `frontend/tests/gateDerived.spec.ts` (13), `tests/integration/test_validator_service.py::test_two_gate_round_trips_duplicate_replay_and_logs`. Missing: the criterion also asks for **evidence gaps**, and `Verdict` carries none — the branch `gaps` lists stop at synthesis and never reach the gate. |
| F13 Validation Report Generation | **Partial** | Reporter on escalation tier; `output_pydantic=ValidationReport` with `output_file` absent, asserted by `tests/validator/test_crews.py::test_tasks_have_structured_outputs_and_report_has_no_output_file`; the Markdown body is written by the Flow `persist` step, asserted in `test_flow.py`. **Risks are now requested** in `reporting_task`, with an instruction to cite each risk that rests on a source and not to restate the kill criteria. Missing: `report_mechanics_problems` still checks only URL closure both ways, the `# ` title line, the provisional flag/title/summary, `thin_dimensions` and LOW-confidence wording — **not** the score table, kill criteria, cheapest next test, risks section or Sources heading. Fail-on-exhausted-retries still relies on CrewAI's own raise and nothing here tests it. |

#### Schemas and guardrails

| Feature | Status | Evidence, and what is missing |
|---|---|---|
| F14 Pydantic Validation Models | **Complete** | All five leaf models and all six stage models present. URLs validated with an actionable message and stored as `str` — no `HttpUrl` anywhere; `source_urls` mirror validators on all three findings models. `tests/validator/test_schemas.py` (29 tests) covers actionable messages, exact source mirroring, duplicate rejection, the computed `evidence_thin` flag and strict non-coercion of score strings. |
| F15 Zero-Cost Mechanical Guardrails | **Partial** | 51 tests in `tests/validator/test_guardrails.py`. Status honesty, URL closure, count consistency, required gaps, evidence-count recomputation, report structure, confidence language and provisional labels all implemented and tested; `parse_raw_model` returns successful raw text **byte-identical**, asserted by exact equality. The previous headline gap is closed: **`RUBRIC_ANCHORS` now carries all five ladders**, so M/C/F/X are bound at 0.85 overlap rather than accepting any prose, and `score_support_problems` / `rubric_support` additionally bound each score against the counted evidence. Held at Partial for one unchanged clause: **query quality is still not validated at all**. |
| F16 Citation Judgement Guardrail | **Complete** | Exactly one string guardrail, on the reporting task only, ordered after the mechanical callable, with the prompt text pinned in YAML and hard-checked against a constant so it cannot drift. This is now executable rather than read: `tests/validator/test_crews.py::test_guardrail_sets_are_exactly_as_specified` asserts the count, type and position of every guardrail on every task and that the single-guardrail `guardrail=` field stays unused, and `::test_exactly_one_llm_guardrail_and_it_is_last_on_the_report` asserts there is exactly one string guardrail and where it sits. |

#### Cache and retrieval

| Feature | Status | Evidence, and what is missing |
|---|---|---|
| F17 Branch-Level Warm Cache | **Complete** | Lookup happens inside `@listen("scope_approved")` steps, so never before confirmation. Market always, sentiment **never**, feasibility opt-in; branch-specific score and age thresholds; cached evidence labelled with source and retrieval dates and explicitly marked supplemental. Tests: `tests/validator/test_cache.py` (8 tests) plus `tests/validator/test_flow.py::test_market_cache_supplements_but_never_skips_live_research` (asserts the order lookup → live → index) and `::test_sentiment_branch_never_looks_up_cache`. |
| F18 Safe Evidence Indexing | **Complete** | One document per source URL with `branch`, `category`, `idea_hash`, publisher and timestamps; branch+category metadata filters reach `index.query(filter=...)`; per-user namespace is an opaque SHA-256 digest that provably does not leak the identity; `ScopedIdea`/`Verdict`/`ValidationReport` are rejected **before any embedding spend**. Tests: `tests/validator/test_cache.py`, `tests/tools/test_indexing.py` (23), `tests/tools/test_pinecone_retrieval.py` (2). |

#### Live event and observability spine

| Feature | Status | Evidence, and what is missing |
|---|---|---|
| F19 Ordered CrewAI Event Capture | **Complete** | ContextVar-scoped stream sink (`events/context.py`) with an opt-in `async def` listener fallback and **no plain sync handler anywhere**; run context is re-established around resume as well as initial kickoff; an ordinary CLI run installs no sink so its events are ignored. Tests: `tests/events/test_spine.py::test_capture_is_scoped_ordered_and_immutable`, `::test_concurrent_contexts_do_not_leak_frames` (both now discovered), and `tests/service/test_observability.py::test_capture_never_blocks_on_or_performs_database_writes` proves the no-I/O clause rather than asserting it. |
| F20 Versioned Frame Protocol | **Complete** | `{type:"frame", data:{...}}` with `v`, gapless `seq`, run id, timestamp, kind, event type, level, node id, message, bounded details and duration; field-by-field mapping with **no `to_json()` and no whole-object traversal**; a structured `edge_taken` frame emitted from the router's return value. The last gap is closed: **`FrameKind.METRICS` is emitted** — `registry.py` snapshots run and per-node usage as a `METRICS_UPDATED` frame capped at `MAX_METRICS_NODES`. Tests: `test_spine.py::test_router_finish_emits_node_end_then_edge`, `::test_serializer_clips_fields_without_serializing_live_objects`, and `test_observability.py::MetricsFrameTests` (5 tests: terminal snapshot, coalescing against ring flooding, no frame when no model was called, the interval snapshot, and a snapshot before a gate pause). |
| F21 Stable Node Attribution | **Complete** | Declared node ids in the graph descriptor; the exact task-name → agent-role-prefix → current Flow method → quarantine chain; each fan-out branch is its own Flow method; the `unattributed` node is present and visible in both descriptors. The last gap is closed: **unattributed frames are counted and exposed in run status** — `test_observability.py::UnattributedFrameTests` (3 tests) covers the buffer counting only quarantined frames, run status reporting the count, and the count surviving recovery from storage. The Studio renders the node and its count (`frontend/tests/quarantineNode.spec.ts`, 8 tests). |
| F22 Token Streaming and Call Timing | **Partial** | `LLMStreamChunkEvent` becomes a non-blocking `llm`/chunk frame; before/after pairs drive live timer chips in the rail with a 100 ms ticker, frozen on completion. Missing, unchanged and the only F19-F24 criterion still unmet: **no per-node loading bubble** — chips are per call inside a flat chronological list, so during the three-way fan-out there is no per-node "this node is thinking" affordance. |
| F23 Per-Run and Per-Node Usage Accounting | **Complete** | Accumulation keyed on `(node_id, model)` with prompt/completion tokens, calls, elapsed ms and cost priced through `compute_cost_usd()`; a `Flow.usage_metrics` discrepancy is **logged rather than silently resolved**. Tests: `tests/service/test_graph_registry.py::test_llm_usage_is_priced_persisted_and_exposed_by_node_and_model`, `::test_flow_usage_mismatch_is_logged_without_failing_the_run`. The UI half is now covered too — `frontend/tests/frameHandling.spec.ts::accumulates run and per-node token usage`. |
| F24 Bounded Backpressure | **Complete** | 2,000-frame ring counting evictions as both drop and gap; 512-frame subscriber queues counting drops; a separate `_PersistenceWriter` thread doing every DB write; counters exposed in run status. Tests: `tests/service/test_graph_registry.py::test_status_and_replay_are_bounded`, `tests/events/test_spine.py::test_ring_reports_eviction_as_drop_and_gap` (now discovered), and `test_observability.py::FrameWriterCadenceTests` (4 tests) for the writer's size/interval/flush/stop behaviour. |

#### Backend service

| Feature | Status | Evidence, and what is missing |
|---|---|---|
| F25 Workflow and Graph APIs | **Complete** | Both endpoints live; topology derived from `build_flow_structure()`; the overlay is validated key-for-key against the derived node set and **startup raises if any router lacks statically inferable events**; ETag set from a content hash. Tests: `tests/integration/test_validator_service.py::test_both_graphs_are_exposed_with_derived_routes` asserts both cache routes, both gate kinds, the quarantine node, fixed layout metadata and the three-way `scope_approved` fan-out; `tests/service/test_app.py::test_graph_run_status_and_frames_contract` adds the ETag header. |
| F26 Run Lifecycle APIs | **Partial** | `POST /api/sessions/{sid}/runs` returns 202 with run id, status and graph version; `GET /api/runs/{rid}` returns status, pending gate, frame counters, error and usage; `GET .../frames` supports `after`, `limit` capped at `MAX_REPLAY_LIMIT=500` and comma-separated kind filtering; `run_id` is distinct from `session_id`. Run records are now evicted after `VALIDATOR_RUN_RETENTION_SECONDS` and rehydrated from storage on the next read (`test_observability.py::RunEvictionTests`, 5 tests). Held at Partial for one unchanged reason: queueing under `RUN_CONCURRENCY > 1` is asserted on the executor's **configuration**, never on an observed queued-then-started run. |
| F27 Human Gate APIs | **Complete** | HTTP replies, structured approve/revise, HTTP 409 on a duplicate through a real SQL compare-and-set (`UPDATE ... WHERE answered_at IS NULL` + `rowcount == 1`), and pending-gate recovery through run status. **Gate replies over WebSocket landed and are tested** — `service/app.py::handle_gate_reply` shares the same compare-and-set, bounded by `WS_MAX_MESSAGE_BYTES` / `WS_MAX_GATE_FIELDS` / `WS_MAX_GATE_FIELD_CHARS`. Tests: `tests/integration/test_ws_gate_replies.py` (10 tests — socket reply resumes the run, WS and HTTP produce identical frames, duplicate refused while the socket stays usable, malformed messages refused without killing socket or run, ping/replay/`after` survive a reply, the stream keeps flowing during a reply, and a late reply after expiry still resumes), plus `tests/service/test_app.py::test_websocket_refuses_control_messages_on_a_gateless_run` and three `frontend/tests/studioApi.spec.ts` cases. |
| F28 Cooperative Cancellation | **Complete** | `POST .../cancel` marks the run cancelling; a per-run scoped `PRE_STEP` hook raises `HookAborted` at the next boundary; the response returns an explicit `effect` and `eta_hint`, and the UI holds "Stopping…" until a server `run_state` frame confirms. Test: `tests/integration/test_validator_service.py::CancellationIntegrationTests::test_cancel_stops_at_next_runner_boundary`. |
| F29 Log Export | **Complete** | NDJSON and ZIP both served; the ZIP contains `frames.ndjson`, `run.json` and `node-metrics.json`; Download Logs is wired in the Studio controls with a spinner and error state. Tests: the integration test asserts NDJSON ordering and completeness; `tests/service/test_app.py::test_health_readiness_and_log_exports` covers ZIP; `frontend/tests/downloadLogs.spec.ts` (10 tests) covers the browser half — object-URL minting and revocation, the ZIP filename, percent-encoded run ids, anchor cleanup, and both failure paths. |
| F30 Reconnecting WebSocket | **Complete** | `/ws?session_id=&run_id=&after=` with ping/pong, sequence replay, an explicit `replay_gap` when the cursor is behind the ring, `replay_truncated` when more remains, client-side dedup and exponential backoff; a slow subscriber drops from its own bounded queue rather than blocking the run. The last gap is closed: **run records are pruned** after `VALIDATOR_RUN_RETENTION_SECONDS`, with a connected subscriber pinning a terminal run and a `waiting` run never evicted (`test_observability.py::RunEvictionTests`). Client side: `frontend/tests/studioApi.spec.ts` (cursor, reconnect-and-resume, malformed message, idle ping, unsubscribe). |
| F31 Durable Run Persistence | **Partial** | Runs, node metrics, ordered frames, gates, session/workflow/flow ids and graph versions all persisted; `PostgresFlowPersistence` implements CrewAI `FlowPersistence` for state and pending feedback; `RUN_CONCURRENCY=1` default with queueing; resumability proven across a **new app instance**, with SQLite round trips, frame ordering and idempotency in `tests/service/test_persistence.py` (5 tests). Frame batching is no longer size-only: `VALIDATOR_FRAME_FLUSH_INTERVAL_SECONDS = 0.25` bounds the wait for a partial batch, tested in `test_observability.py::FrameWriterCadenceTests`. Missing, and the reason this stays Partial: everything automated runs on **SQLite**. No PostgreSQL exercise, no multi-process compare-and-set test. |

#### Studio UI

The frontend now has executable tests (103 across 10 files), so these rows are
judged on their own criteria rather than capped by a missing runner.

| Feature | Status | Evidence, and what is missing |
|---|---|---|
| F32 Three-Pane Validator Studio | **Partial** | Vue 3 + Vite + Vue Flow; a real three-column grid filling `100dvh`; **both** side rails collapsible; tablet breakpoints at 1180 px and 860 px plus `prefers-reduced-motion`. Unchanged divergence from the criterion: the segmented control is **Graph / Activity, not Chat / Graph**, and it is not a view mode — above 860 px "Activity" only un-collapses the chat rail. `min-width: 720px` on `html, body`. |
| F33 Fixed Live Agent Graph | **Partial** | Fourteen fixed nodes at literal positions, non-draggable/non-selectable/non-connectable, matching the live descriptor exactly — `frontend/tests/mockGraph.spec.ts` (18 tests) asserts the node list and edge list against `build_graph_descriptor(ValidatorFlow, ...)` in order, plus the fan-out, the AND join, both revise loops and the router classification. The **Unattributed node is now rendered and counted** (`quarantineNode.spec.ts`, 8 tests). Missing: **no lock control** — `:show-interactive="false"` explicitly disables it; **no start-state node**; and node height is still not stable, because the meta and usage blocks are `v-if` so nodes grow when usage arrives. |
| F34 Node and Sprite Identity | **Partial — deliberate divergence, still undecided** | **The PRD's 144 downscaled 64×80 character PNGs were never imported, and this is a deliberate substitution rather than an oversight.** Re-verified in this pass: nothing under `frontend/src` mentions a sprite. What ships instead: kind-based Lucide glyphs, a static per-node eyebrow string, and two-letter initials on chat avatars. Consequences to accept or reject explicitly: **no per-agent palette**, **no hash-based assignment**, **no two-frame walk cycle**. Decide whether the vector identity is the accepted answer and amend the criterion, or whether the sprite work is still owed. |
| F35 Edge and Handoff Visualization | **Partial** | Bezier paths, marching-dash animation on active edges, condition labels through `EdgeLabelRenderer`, driven by structured `edge_taken` frame details. The fan-out defect is fixed: `activeEdgeIds` is a `Set`, so **all three branches animate at once** — `frontend/tests/edgeAnimation.spec.ts` (8 tests) covers simultaneous animation, independent lifetimes, stopping on branch completion and on error, re-taken edges, clearing on a terminal state, no carry-over across relaunch and no timer leak on unmount. Missing: **no self-loop case**, **no sprite animated along the path**, **no duration derived from path length** (both timings hard-coded), **no shared SVG `<defs>`** — the glow is a per-edge CSS `drop-shadow`. |
| F36 Live Chat Rail | **Partial** | Timestamped entries in a `role="log" aria-live="polite"` container, auto-scroll, an accessible Show More/Show Less with `aria-expanded`, and timed tool/model chips that tick live and freeze on completion. Missing, unchanged: **four variants, not seven** — `agent`, `system`, `warning`, `error`, so a `gate_open` renders as a generic warning bubble with no `tool`, `model` or `human-interaction` variant; **no `ResizeObserver`** — collapsing is a raw `message.length > 180` heuristic; per-node attribution is an actor name in a flat interleaved list. |
| F37 Gate Interaction Cards | **Partial** | Editable structured fields seeded from the gate payload; a live `expires_at` countdown; the card survives refresh via `localStorage` + `GET /api/runs/{id}` and survives a socket drop (`frontend/tests/runRecovery.spec.ts`, 7 tests). Two things were **corrected** during this pass and are tested. Expiry is *informational*, never a lockout — every option stays enabled, a late reply still submits with its edited fields, and the wording reads as a notice (`frontend/tests/gateCard.spec.ts`, 8 tests), matching the server behaviour under F03. And the verdict card now renders the whole rubric as a read-only `derived` section rather than as text inputs the server would discard (`frontend/tests/gateDerived.spec.ts`, 13 tests). Missing: **evidence gaps are still not on the card** (nothing carries them to the gate), and **expiry is card-only — `NodeRunState` has no `expired` member**, so the node stays visually `waiting`. |
| F38 Run Controls | **Partial** | Read-only status badge, Launch/Relaunch/Cancel/Download Logs with a format picker, Lucide icons throughout; Relaunch immediately starts a new run with the current idea; cancellation waits for a server `run_state` frame before showing `cancelled`. Missing, unchanged: **no workflow selection** — `StatusPanel.vue` prints the literal string "Idea Validator" in a read-only well and `workflowId` cannot be changed from the UI; the criterion's "Send" label does not exist; and the three primary actions carry no `title` tooltips (only the log-format buttons and the run id do). |
| F39 Error and Recovery UX | **Partial** | Frame drops counted and shown in red; four connection states with backoff; server failures surfaced in a dismissable `role="alert"` banner; **run status and connection status are genuinely independent refs**, so a failed run and a disconnected browser are cleanly distinguished. The `localStorage` defect is fixed and tested: a saved run is cleared when an error frame ends it, dropped when it already finished, dropped when the server can no longer serve it, and the page still renders when site data is blocked (`runRecovery.spec.ts`). Missing: **guardrail exhaustion has no representation anywhere in the frontend** — nothing in `frontend/src` mentions it; tool failures get only the generic error treatment; unattributed events are labelled "System" in the rail even though the graph node counts them; evidence-thin `NEEDS_WORK` ends green only incidentally, not by any implemented rule. |

#### Delivery, quality, and operations

| Feature | Status | Evidence, and what is missing |
|---|---|---|
| F40 Headless Validator CLI | **Complete** | `validate` entry point in `pyproject.toml` with `--idea`, `--no-gates`, `--resume`, `--feedback`, `--namespace` and `--feasibility-cache`; dependency-injected crew factories keep it testable with no spend (`tests/validator/test_flow.py::test_validate_headless_entry_point_uses_injected_factories`). The last gap is closed: **concurrent branch output is prefixed with node names** — a ContextVar-scoped stdout wrapper writes `[node_id]` ahead of whole lines only, buffering partial writes per prefix, and any writer outside a branch (the service, another thread) sees an empty prefix and is untouched. |
| F41 Service Entry Point and Environment | **Partial** | `serve` entry point; the `service` extra is installed in `.venv`; `.env` loads from the package path with `override=True`; startup asserts every model constant and every YAML `llm`/`function_calling_llm` uses the `openrouter/` prefix **before FastAPI is imported**. Tests: `tests/service/test_app.py::test_startup_rejects_non_openrouter_model_constants`, `tests/validator/test_crews.py::test_owned_implementation_has_no_openai_model_string`. Divergence, unchanged: `PYTHONIOENCODING=utf-8` is **not set** anywhere in `render.yaml`, the `Dockerfile` or CI; the equivalent is achieved by reconfiguring `sys.stdout`/`sys.stderr` at package import, which is stronger for the CLI but does not cover a subprocess. |
| F42 Performance Validation | **Partial** | Upgraded from Not started because the harness now exists and is itself tested: `scripts/bench_fanout.py` (parallel and sequential arms, gate reply-to-resume probe, RSS sampling at `VALIDATOR_PERF_SAMPLE_INTERVAL_S`, JSON + text output, non-zero exit on a missed target), `scripts/perf_arms.py`, `scripts/perf_metrics.py`, and **58 tests in `tests/perf/`**. Targets are constants, not prose: `VALIDATOR_PERF_TARGET_FANOUT_SPEEDUP = 1.8`, `VALIDATOR_PERF_TARGET_PEAK_RSS_BYTES = 400 MB`, `VALIDATOR_PERF_TARGET_GATE_RESUME_MS = 500`, `VALIDATOR_PERF_RUNS_PER_ARM = 5`. **Not Complete, and this is the clearest case in the file: the measurement has never been taken.** No live five-parallel/five-sequential comparison, no speedup figure, no peak-RSS number, no gate-latency number. Synthetic mode measures orchestration overhead only and reports its speedup as advisory, because there the ratio is a property of `--branch-seconds`. `tests/validator/test_flow.py`'s `ConcurrencyTracker.maximum == 3` is a structural fact, not a speedup. |
| F43 Correctness and Regression Tests | **Partial** | Verified: repeatable verdict bands from identical evidence (by construction, `test_schemas.py`), gapless frame sequences, no event leakage across concurrent runs (`test_spine.py::test_concurrent_contexts_do_not_leak_frames`, now discovered), reconnect, duplicate reply over both transports, restart recovery, post-gate attribution, gate timeout (`test_gate_expiry.py`, 12 tests) and that every router exposes statically inferable labels. **Brief Crew regression is now covered** — `tests/test_brief_crew_regression.py` (23 tests) pins the cache router's contract including that it makes no LLM call, the `Literal` annotation and both statically visible branches, the age helper's refusal to treat unparseable stamps as fresh, the usage-record shape, `persist`'s markdown and run record, Track A owning the retrieval tool while Track B does not, the scrape tool's name and `result_schema`, and `run_crew()`/`kickoff()`. **Still not verified: zero fabricated citations across an acceptance set** — no acceptance set exists and no live run has been made. |
| F44 Deployment Readiness | **Partial** | Health and readiness endpoints report per-dependency status and return 503 when storage is unhealthy; `DATABASE_URL` is honoured with `postgres://`/`postgresql://` normalised to `postgresql+psycopg://`; the frame writer flushes on close via the FastAPI lifespan; credentials stay within the provisioned set with an optional `GITHUB_TOKEN`. `render.yaml` now sets **`maxShutdownDelaySeconds: 300`** and `postgresMajorVersion: "18"`, and `Dockerfile` and `.github/workflows/ci.yml` exist. Not Complete because **none of it has been applied to a host**: no deploy, no live Postgres, no observed graceful shutdown, no observed persistence flush on the target. |

### Measurement and verification debt

Carried explicitly so it is not mistaken for completed work.

| Debt | Blocks | Note |
|---|---|---|
| Fan-out speedup, peak RSS, gate reply-to-resume latency | F42 | **Never measured.** The harness and its 58 tests exist; the live run does not. This is the single clearest Partial-not-Complete in the file. |
| Live paid acceptance run + citation-closure set | F43, F05-F08 | Never run. Everything uses doubles or `synthetic=True`. Also leaves the market tool's 402/plan-limit branch untested. |
| Live PostgreSQL exercise | F31, F44 | SQLite only; multi-process compare-and-set on `pending_feedback` and the gate reply is untestable under SQLite's single writer. Target is PG 18. |
| Human review of `RUBRIC_ANCHORS` | F09, F10, F15 | All five ladders are binding and tested; none has been read by a human. M/C/F/X are a derivation, and PRD §10.2's own Demand ladder was defective in three ways before this pass. See CLAUDE.md remaining-work item 5 for the eight anchors the audit itself was unsure of. |
| Firecrawl plan economics | F05 | Real rate limits and per-credit search+scrape cost unmeasured (PRD Q3). |
| Reporter/Scoper cheap-tier A/B | F13, F02 | Not run (PRD Q4); listed under Deferred Enhancements below. |
| F34 sprite decision | F34 | The vector/icon identity is a deliberate substitution. **Undecided** whether the criterion is amended or the sprite work is still owed. |
| `RUN_CONCURRENCY > 1` observed queueing | F26 | Asserted on the executor's configuration, never on a run that was seen queued and then started. |
| Query-quality validation | F02, F15 | `scope_problems` checks the assumption count and one scoping gap; nothing checks that the generated queries are category-based rather than the pitch plus keywords. |
| Guardrail exhaustion in the UI | F39, F13 | The backend's terminal failure mode has no representation in `frontend/src`, and nothing tests the raise. |

## Platform Requirements

- **CrewAI-native orchestration:** Use CrewAI `Flow`, `Process.sequential`, sibling `@listen` fan-out, deterministic `@router` methods, task guardrails, and native human feedback. Do not introduce LangGraph or a custom orchestration engine.
- **OpenRouter-only model access:** Route every agent, guardrail, and human-feedback model call through the model IDs defined for OpenRouter in `config.py`.
- **No direct OpenAI dependency:** The validator must not require `OPENAI_API_KEY`, must not fall back to CrewAI's default OpenAI models, and must explicitly pass the OpenRouter-backed `CHEAP_MODEL` wherever CrewAI would otherwise choose a default model.
- **OpenRouter embeddings:** Continue calling `brief_crew.embeddings` directly. Do not route embeddings through CrewAI's embedder, and keep `DOC_PREFIX` and `QUERY_PREFIX` paired.
- **Centralized model configuration:** Keep model names, pricing, thresholds, and embedding constants in `config.py`; do not inline them in agents, tasks, tools, or service code.
- **Existing Brief Crew compatibility:** Preserve `run_crew()`, `kickoff()`, `output/brief.md`, `output/last_run.json`, existing prompts, and existing behavior.

## Core Validation Workflow

### F01. Startup Idea Submission

- Accept a one-line startup idea from the Studio or the headless CLI.
- Create a distinct `run_id` under a reusable `session_id`.
- Queue runs when the configured concurrency limit is reached.
- Display queued, running, waiting, cancelling, completed, cancelled, and failed states accurately.

### F02. Structured Idea Scoping

- Run a `scoper` agent on the OpenRouter escalation-tier model with no tools.
- Convert the raw idea into a validated `ScopedIdea` containing the market category, target user, technology claim, branch-specific queries, three to five assumptions, scoping gaps, and an `as_of` date.
- Generate category-based research queries instead of appending generic keywords to the original pitch.
- Pass query lists to CrewAI prompts as joined text blocks rather than Python list representations.

### F03. Scope Confirmation Gate

- Pause after scoping and show all parsed fields in an editable form.
- Let the operator approve the scope or submit revisions.
- Route approve/revise decisions deterministically without an LLM call.
- Persist pending feedback so the run remains resumable after disconnects, timeouts, process restarts, and deployments.
- Mark an unanswered timed-out gate as expired without failing or auto-answering the run.

### F04. Parallel Research Fan-Out

- Launch Market Analyst, Sentiment Analyst, and Feasibility Analyst concurrently as three sibling Flow listeners.
- Keep branch methods synchronous so CrewAI runs them through `asyncio.to_thread` with copied context.
- Use one single-agent Crew per branch so all three nodes appear independently in the live graph.
- Join the branches only after all three have completed.
- Retain a sequential fallback if measurement fails the speed or memory targets.

### F05. Market Landscape Research

- Use an OpenRouter cheap-tier Market Analyst and a Firecrawl search-and-scrape tool.
- Return competitors, pricing, paying segments, market evidence, gaps, source URLs, retrieval time, and tool status in a structured envelope.
- Handle both Firecrawl `Document.url` and `SearchResultWeb.metadata.source_url` response shapes.
- Detect plan limits and rate-limit responses rather than hard-coding an unverified Firecrawl quota.

### F06. Community Sentiment Research

- Use an OpenRouter cheap-tier Sentiment Analyst and the Hacker News Algolia API.
- Search relevant stories, then fetch comment trees for the strongest threads.
- Classify evidence as `HAS_PROBLEM`, `PAYS`, `BUILT_WORKAROUND`, `OPINION`, or `OFF_TOPIC`.
- Capture attributable quotes, recency, points, comment counts, gaps, and tool status.
- Cite the Hacker News discussion URL derived from `objectID`, including Ask HN items with a null `story_url`.
- Detect HTTP 429 responses and back off without assuming rate-limit headers exist.

### F07. Technical Feasibility Research

- Use an OpenRouter cheap-tier Feasibility Analyst and GitHub repository search.
- Capture relevance, license, commercial-use suitability, archived state, recent activity, implementation signals, and evidence URLs.
- Send a valid `User-Agent` on every GitHub request.
- Enforce a shared module-level token bucket: 8 requests/minute without `GITHUB_TOKEN`, 24 requests/minute with it.
- Return `rate_limited` honestly so confidence drops instead of producing a verdict from incomplete evidence.
- Support escalating this agent alone if cheap-model results repeatedly exhibit the star-count fallacy.

### F08. Structured Tool Results and Evidence Closure

- Make every research tool return a JSON envelope with `status`, `tool`, `query`, `retrieved_at`, `result_count`, `results`, and `notes`.
- Require every result to contain a non-empty URL.
- Record the exact URL set returned by tools for the run.
- Reject any finding or report URL not present in that captured set.
- Require failed, empty, or rate-limited tools to produce empty sources and explicit evidence gaps.

### F09. Evidence Synthesis

- Run the `synthesist` on the OpenRouter escalation-tier model with no tools.
- Consume the three branch outputs only after fan-in.
- Assign five anchored integer scores: Demand, Market, Competitive room, Feasibility, and Headroom over free.
- Produce evidence counts, kill criteria, the cheapest next test, and a draft verdict.
- Keep reasoning enabled at an appropriate level; do not copy the evaluator's minimal-reasoning setting into this judgement step.

### F10. Deterministic Rubric and Verdict

- Calculate the composite score mechanically on a 0.0–10.0 scale:

  $$\operatorname{score}=2(0.30D+0.20M+0.20C+0.15F+0.15X)$$

- Compute `composite_score`, `verdict`, `confidence`, `confidence_band`, and `provisional` in a Pydantic model validator rather than trusting model arithmetic.
- Apply the confidence override before hard floors and score thresholds.
- Return `NEEDS_WORK / INSUFFICIENT_EVIDENCE` whenever confidence is below 0.35.
- Apply fatal-dimension floors for no demand, no market, an already-good free solution, and an unbuildable v1.
- Return `VALIDATE` only when the composite is at least 7.0, every dimension is at least 3, and confidence is at least 0.60.
- Return `REJECT` for a composite below 4.0 when no confidence override applies.
- Make two runs over identical evidence produce the same verdict band.

### F11. Mechanical Confidence Scoring

- Compute confidence from market, sentiment, and feasibility coverage, market-source staleness, and branch completion.
- Use confidence bands: HIGH at 0.70 or above, MODERATE from 0.35 to 0.69, and LOW below 0.35.
- Apply a 0.60 branch penalty whenever fewer than three research branches succeed.
- Label REJECT outcomes between 0.35 and 0.60 confidence as provisional in both the title and summary.
- Prevent LOW-confidence reports from using unjustifiably certain wording.

### F12. Verdict Review Gate

- Pause after synthesis and show the rubric, draft verdict, confidence value, confidence band, evidence gaps, and cheapest next test.
- Let the operator approve or revise the verdict inputs.
- Route button decisions deterministically with zero LLM calls.
- Preserve structured operator overrides for the reporter and audit log.

### F13. Validation Report Generation

- Run the `reporter` on the OpenRouter escalation-tier model initially, with a later cheap-tier A/B option.
- Produce a sourced Markdown report with verdict, confidence, score table, evidence, risks, kill criteria, cheapest next test, gaps, and sources.
- Write the final body to `output/validation.md` from the Flow persistence step.
- Keep `output_pydantic` on the task but omit `output_file` so CrewAI does not write JSON into the Markdown file.
- Fail the run rather than publish a report that exhausts its citation guardrail retries.

## Schemas and Guardrails

### F14. Pydantic Validation Models

- Add flat leaf models for `Evidence`, `Competitor`, `Thread`, `Repo`, and `DimensionScore`.
- Add stage models for `ScopedIdea`, `MarketFindings`, `SentimentFindings`, `FeasibilityFindings`, `Verdict`, and `ValidationReport`.
- Keep nesting to one level where practical to avoid repeated structured-output retries.
- Validate URLs with actionable field-validator messages while storing them as strings.
- Include countable `source_urls` fields and verify that they match nested source objects.

### F15. Zero-Cost Mechanical Guardrails

- Validate scope completeness and query quality.
- Validate branch status honesty, URL closure, source/list count consistency, and required gaps.
- Validate exact rubric anchor selection and reserve score 1 for insufficient evidence.
- Recompute every count used by the confidence calculation.
- Validate report structure, confidence language, and provisional labels.
- Parse the first guarded task attempt from `TaskOutput.raw`, return successful raw text unchanged, and allow Pydantic conversion afterward.

### F16. Citation Judgement Guardrail

- Run one OpenRouter-backed LLM citation guardrail on the reporting task after mechanical checks pass.
- Do not attach paid string guardrails to the three parallel research tasks.
- Surface the final guardrail error as a terminal UI state rather than as a socket disconnect.

## Cache and Retrieval

### F17. Branch-Level Warm Cache

- Look up cached evidence only after the operator confirms the scoped category.
- Use the cache for market evidence, never for sentiment, and optionally for feasibility as a GitHub rate-limit shock absorber.
- Use branch-specific relevance and freshness thresholds.
- Run every research branch even when cached evidence exists; cached passages supplement live evidence and never skip validation work.
- Label cached evidence with retrieval and source dates.

### F18. Safe Evidence Indexing

- Index one document per source URL with `branch`, `category`, `idea_hash`, publisher, and timestamps.
- Add metadata filtering by branch and category to retrieval.
- Use a per-user Pinecone namespace.
- Permit only source evidence at the indexing boundary.
- Reject `ScopedIdea`, `Verdict`, and `ValidationReport` objects to prevent conclusions from becoming evidence.

## Live Event and Observability Spine

### F19. Ordered CrewAI Event Capture

- Capture events through a per-run ContextVar-scoped stream sink, with async event listeners as a fallback.
- Never register plain synchronous bus handlers for UI sequencing.
- Keep capture handlers constant-time, non-blocking, exception-safe, and free of network or database I/O.
- Re-establish run context and the stream sink before every human-feedback resume.
- Ignore events from ordinary Brief Crew CLI runs when no UI or Flow run context is active.

### F20. Versioned Frame Protocol

- Emit `{type: "frame", data: {...}}` messages with protocol version, gapless per-run sequence, run ID, timestamp, kind, event type, level, node ID, message, bounded details, and duration.
- Support `run_state`, `node_state`, `edge_taken`, `agent`, `tool`, `llm`, `token`, `gate_open`, `gate_closed`, `metrics`, and `error` frame kinds.
- Map CrewAI method, task, agent, tool, model, token, and human-feedback events field by field.
- Never serialize entire CrewAI objects or call `event.to_json()`.
- Emit a structured `edge_taken` frame rather than parsing human-readable log strings.

### F21. Stable Node Attribution

- Declare stable node IDs in the graph descriptor.
- Resolve events by task name, agent-role template prefix, current Flow method, then a visible `Unattributed` quarantine node.
- Keep each fan-out branch independently attributable.
- Count unattributed frames and expose the count in run status.

### F22. Token Streaming and Call Timing

- Stream model chunks without blocking the model thread.
- Show one loading bubble per active node.
- Add live timer chips for model and tool calls using before/after event pairs.
- Freeze elapsed durations when a node finishes.

### F23. Per-Run and Per-Node Usage Accounting

- Accumulate prompt tokens, completion tokens, calls, latency, and cost by `(run_id, node_id, OpenRouter model)`.
- Price model calls through `compute_cost_usd()` and the centralized OpenRouter price table.
- Show per-node and total usage in the UI.
- Compare event-derived totals with `Flow.usage_metrics` and log discrepancies rather than silently selecting one.

### F24. Bounded Backpressure

- Keep a 2,000-frame per-run ring buffer and count dropped oldest frames.
- Give each WebSocket subscriber a bounded queue of 512 frames and count drops.
- Perform database writes in a separate batched writer, never in an event handler.
- Expose frame count, dropped count, and emit errors through run status.

## Backend Service

### F25. Workflow and Graph APIs

- `GET /api/workflows` returns registered workflows.
- `GET /api/workflows/{id}/graph` returns a versioned `GraphDescriptor` with an ETag.
- Derive topology from CrewAI's `build_flow_structure()` and enrich it with fixed layout metadata.
- Validate overlay keys and require every router to expose statically inferable events at service startup.
- Correct the existing Brief Flow router return annotation so cache-hit and cache-miss edges appear in the graph.

### F26. Run Lifecycle APIs

- `POST /api/sessions/{sid}/runs` starts or queues a run and returns HTTP 202 with `run_id`, status, and graph version.
- `GET /api/runs/{rid}` returns status, pending gate, frame counters, errors, and usage.
- `GET /api/runs/{rid}/frames` supports `after`, a maximum `limit` of 500, and kind filtering.
- Keep `run_id` distinct from `session_id` so one session can contain multiple runs.

### F27. Human Gate APIs

- `POST /api/runs/{rid}/gates/{gid}` accepts structured approve/revise replies over HTTP.
- Accept gate replies over WebSocket as well.
- Return HTTP 409 when a gate has already been answered.
- Return pending gate state through run status so reconnecting clients can recover it independently of the socket replay.

### F28. Cooperative Cancellation

- `POST /api/runs/{rid}/cancel` marks the run as cancelling.
- Use per-run scoped `PRE_STEP` hooks that raise `HookAborted` at the next Flow-method or task boundary.
- Report cancellation granularity explicitly: an active model or tool call may finish before stopping.
- Keep the UI in “stopping after the current step” until the server confirms cancellation.

### F29. Log Export

- `GET /api/runs/{rid}/logs` exports NDJSON or ZIP.
- Include ordered frames, gate interactions, node timings, usage, cost, tool status, and terminal errors.
- Make log download available from the Studio controls.

### F30. Reconnecting WebSocket

- Serve `/ws?session_id=&run_id=&after=`.
- Support ping/pong, retry with backoff, sequence-based replay, deduplication, and session TTL cleanup.
- Replay durable frames after reconnect and expose any sequence gaps.
- Ensure a slow or disconnected client cannot delay a CrewAI run.

### F31. Durable Run Persistence

- Store runs, run metrics, node metrics, frames, gates, session IDs, workflow IDs, flow IDs, and graph versions in Postgres.
- Implement `PostgresFlowPersistence` for CrewAI state and pending feedback.
- Batch frame persistence approximately every 250 ms from one writer task.
- Preserve resumability across Render restarts and deployments.
- Limit active runs to `RUN_CONCURRENCY=1` on the target 512 MB Render instance and queue additional runs.

## Studio UI

### F32. Three-Pane Validator Studio

- Build the Studio with Vue 3, Vite, and Vue Flow.
- Fill the viewport with a live graph canvas, collapsible chat rail, and controls/status panel.
- Support Chat and Graph view modes.
- Adapt the layout for tablet widths; mobile layout is out of scope.

### F33. Fixed Live Agent Graph

- Render Scoper, three research analysts, Synthesist, Reporter, gates, start/final states, and a visible Unattributed node.
- Use stable positions and a fixed topology rather than a graph editor.
- Provide pan, zoom, fit, and lock controls.
- Represent idle, running, waiting, completed, and error states distinctly.
- Keep dimensions stable so status labels and animations do not shift the layout.

### F34. Node and Sprite Identity

- Use deterministic agent-to-palette assignments from the fixed roster.
- Use deterministic hash-based sprite assignment so each agent keeps the same avatar across graph, chat, and reloads.
- Downscale source sprites to 64×80 assets.
- Animate the active agent with the two-frame walk cycle and stop animation for waiting, completed, and error states.

### F35. Edge and Handoff Visualization

- Animate active handoffs from structured `edge_taken` frames.
- Pulse edges during execution and show clear condition labels.
- Use Vue Flow Bezier paths plus one explicit self-loop case.
- Animate a sprite along the traversed path with duration based on path length.
- Keep shared SVG definitions global rather than duplicating them per edge.

### F36. Live Chat Rail

- Stream agent, tool, model, system, warning, error, and human-interaction entries with timestamps and stable avatars.
- Use collapsible long messages with an accessible Show More/Show Less control and `ResizeObserver` support.
- Display structured tool and model activity as timed chips.
- Preserve readable per-node attribution while the three branch crews run concurrently.

### F37. Gate Interaction Cards

- Render scope confirmation as editable structured fields.
- Render verdict review with the rubric, confidence, evidence gaps, and proposed outcome.
- Show waiting and expired states on both the node and the card.
- Restore the active card after reconnect, refresh, timeout, or deployment.

### F38. Run Controls

- Provide workflow selection, read-only status, Chat/Graph segmented control, Launch/Send/Relaunch primary action, Cancel, and Download Logs.
- Make Relaunch immediately start a new run with the current idea.
- Await server confirmation before showing a run as cancelled.
- Use icons for familiar graph, collapse, zoom, fit, lock, download, settings, and cancellation actions, with tooltips where needed.

### F39. Error and Recovery UX

- Render tool failures, guardrail exhaustion, frame drops, unattributed events, disconnects, and server failures explicitly.
- Preserve the last server-confirmed state during reconnect.
- Distinguish a failed run from a disconnected browser.
- Show evidence-thin results as valid `NEEDS_WORK` outcomes rather than degraded failures.

## Delivery, Quality, and Operations

### F40. Headless Validator CLI

- Add a `validate` entry point that runs the validator without the frontend.
- Keep the validator testable before the service and UI are complete.
- Prefix concurrent branch output with node names so terminal traces remain readable.

### F41. Service Entry Point and Environment

- Add a `serve` entry point for FastAPI and WebSocket hosting.
- Install the existing `service` optional dependency group in the isolated `.venv`.
- Set `PYTHONIOENCODING=utf-8` in the service environment.
- Preserve `.env` loading from the package path with `override=True`.
- Add startup validation that all resolved LLMs use configured OpenRouter models and no CrewAI object falls back to an OpenAI model.

### F42. Performance Validation

- Compare five parallel and five sequential research runs.
- Require at least 1.8× fan-out speedup or withdraw the parallel implementation.
- Keep peak resident memory below 400 MB on a 512 MB target.
- Keep gate reply-to-resume latency below 500 ms.

### F43. Correctness and Regression Tests

- Verify zero fabricated citations across the acceptance set.
- Verify repeatable verdict bands from identical evidence.
- Verify gapless frame sequences and matching node-start/node-end pairs.
- Verify no event leakage across concurrent runs.
- Verify gate timeout, reconnect, duplicate reply, restart recovery, and post-gate event attribution.
- Verify Brief Crew behavior and output remain unchanged.
- Verify every router has statically inferable output labels.

### F44. Deployment Readiness

- Run the service with Postgres-backed state and frame history.
- Set a shutdown delay sufficient for active steps and persistence flushing.
- Expose health and run-status information needed by the hosting platform.
- Keep paid credentials limited to the already provisioned OpenRouter, Firecrawl, Pinecone, and Cohere keys; support an optional GitHub token.

## Delivery Order

1. **M-1: Prerequisites** — repair the Brief Flow graph annotation, prove ordered event capture, and implement Postgres Flow persistence.
2. **M0: Event spine** — emit ordered, attributable frames from the existing Brief Flow.
3. **M1: Service** — expose graph, run, frame, gate, cancellation, log, and WebSocket APIs.
4. **M2: Read-only Studio** — visualize an existing Brief Crew run with live nodes, edges, and chat.
5. **M3: Validator crew** — add all six agents, tools, schemas, rubric, guardrails, CLI, and measured fan-out.
6. **M4: Human gates** — complete scope and verdict pause/resume, timeout, reconnect, and recovery.
7. **M5: Hardening** — finish per-node cost, durable logs, cancellation, acceptance tests, and spec reconciliation.

## Explicit Non-Features

- No graph editor or user-authored workflow YAML.
- No LangGraph dependency.
- No manager or hierarchical orchestration agent.
- No multi-tenant accounts or authentication in the initial release.
- No cross-run agent memory or RAG chat.
- No mobile-first graph layout.
- No synchronous long-running HTTP execution route.
- No batch idea validation until the single-run Flow is stable.
- No indexing of generated scopes, verdicts, or reports as evidence.
- No direct OpenAI model or embedding calls.

## Deferred Enhancements

- Postgres-backed run-history browser.
- Comparison against a hierarchical-manager variant when a real non-deterministic routing need appears.
- Multi-idea batch validation.
- A/B testing the reporter on the OpenRouter cheap tier.
- A/B testing the scoper using operator revision rate as the quality measure.
