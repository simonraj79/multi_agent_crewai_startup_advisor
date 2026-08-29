# Validator Studio Feature List

Source: [`PRD.md`](../PRD.md), dated 2026-08-29.

Validator Studio is additive to the existing Brief Crew. It combines a six-agent CrewAI startup validator with a live Vue 3 graph interface, durable human approval gates, structured evidence, and deterministic scoring.

## Implementation Status

Last synchronized: 2026-08-29, against source and executable tests rather than against prose.

Status meanings: **Not started** has no implementation; **In progress** has an active implementation slice; **Partial** has verified behavior but incomplete acceptance criteria; **Complete** has passing executable acceptance evidence; **Blocked** has an external dependency preventing completion.

**Complete means a criterion that a machine checked.** A feature whose acceptance criterion is a *measurement that has never been taken* is **Partial**, however finished the code looks. A feature that ships but has no test is **Partial**, not Complete.

### ⚠️ Read this before trusting any status below

**1. The documented test command silently skips 6 of the 100 tests on disk.**

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -t .
# Ran 94 tests ... OK (skipped=1)
```

`tests/events/` has **no `__init__.py`**, so `unittest discover` does not descend into it and `tests/events/test_spine.py` never runs. `tests/__init__.py`, `tests/integration/__init__.py`, `tests/service/__init__.py`, `tests/tools/__init__.py` and `tests/validator/__init__.py` all exist; `tests/events/` is the sole omission.

Those six tests **do pass** when named explicitly:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.events.test_spine
# Ran 6 tests ... OK
```

So the event spine *is* covered — the coverage just is not wired into the command everyone runs, and a regression in ordering, immutability, run isolation or ring eviction would not fail the suite. `pyproject.toml` declares `[tool.pytest.ini_options]`, but **pytest is not installed in `.venv`**, so that path is not an available substitute today. Until `tests/events/__init__.py` is added, every M0 status below carries an "undiscovered" caveat.

> The equivalent gap in `tests/service/` was closed during this reconciliation pass — that directory is now discovered, and its 27 tests are counted above.

**2. The frontend has no executable tests at all.** `frontend/package.json` declares no test runner. `vue-tsc -b && vite build` passing is a compile check, not acceptance evidence. **No F32-F39 feature can be Complete under this file's own definition**, regardless of how finished the UI is.

**3. Nothing has been run against paid services.** Every test uses doubles, mocks, or `create_app(synthetic=True)`. No live OpenRouter/Firecrawl/HN/GitHub/Pinecone/Cohere run has happened since the service and UI landed.

### Milestone status

| Milestone | Features | Status | Verified evidence, and what is missing |
|---|---|---|---|
| M-1 Prerequisites | F25 plus event and persistence prerequisites | **Partial** | `BriefFlow.check_cache` returns `Literal["cache_hit", "cache_miss"]` (`src/brief_crew/main.py:105`); both router edges appear in the derived graph — asserted by `tests/integration/test_validator_service.py::test_both_graphs_are_exposed_with_derived_routes` (discovered) and `tests/service/test_graph_registry.py::test_brief_flow_graph_has_both_router_branches`. `PostgresFlowPersistence` exists (`service/persistence.py:343`) and round-trips — but on **SQLite only**. |
| M0 Event spine | F19-F24 | **Partial** | `src/brief_crew/events/` implements the ContextVar stream sink, immutable frames, the 2,000-frame ring and bounded subscriber queues. All six `tests/events/test_spine.py` tests pass — but are **not discovered** (see warning 1). `FrameKind.METRICS` is declared and never emitted; unattributed frames are routed to a visible node but **not counted in run status**. |
| M1 Service | F25-F31 | **Partial** | All 11 documented endpoints exist in `service/app.py`. The discovered `tests/integration/test_validator_service.py` covers both graphs, two gate round trips, HTTP 409, gapless frames, WS replay + ping/pong, NDJSON logs, cancellation and durable recovery. `tests/service/` (now discovered, 27 tests) adds ETag, health/readiness, ZIP export, usage pricing, persistence round trips and the full gate-expiry watch ladder. Missing: WebSocket gate replies (F27), session TTL cleanup (F30), the 250 ms batch cadence (F31 batches by size, not time), and any PostgreSQL exercise. |
| M2 Studio | F32-F39 | **Partial** | A real Vue 3 + Vue Flow application (`frontend/src/`, ~9 components/modules), not a landing page: fixed topology, five node states, animated `edge_taken` edges, gate cards with a live `expires_at` countdown, reconnecting WS client with replay/dedup, refresh recovery, per-node cost, mock fallback. **Zero executable tests**, so nothing here can be Complete. Several PRD behaviours are absent — see F33-F39 rows. |
| M3 Validator | F01-F18, F40, F42 | **Partial** | 59 discovered tests across `tests/validator/` (48) and `tests/tools/` (11) cover the schemas, the deterministic verdict, guardrails, all three tools, the branch cache and the three-way fan-out. F42 has **never been measured**, and roughly half the F0x sub-criteria are unimplemented or untested — see the per-feature rows. |
| M4 Gates | F03, F12, F27, F37 | **In progress** | Both native `@human_feedback` gates pause, persist and resume — `tests/integration/test_validator_service.py::test_native_validator_flow_pauses_and_resumes_twice` and `::test_two_gate_round_trips_duplicate_replay_and_logs` (both discovered), plus durable recovery in a fresh app. Server-side gate expiry landed during this pass and is covered by `tests/service/test_gate_expiry.py` (12 tests). **One slice remains:** WebSocket gate replies (F27/F37) — the inbound socket loop still handles `ping` only. |
| M5 Hardening | F23-F24, F29-F31, F41-F44 | **In progress** | Usage accounting, backpressure, log export and durable persistence are implemented and tested. F42 not measured, F43 has real gaps (no Brief Crew regression test, no acceptance set), F44's artifacts (`render.yaml`, `Dockerfile`, `.github/workflows/`) appeared during this pass and are not yet verified against a deployed host. |

### Feature Evidence Ledger

Test paths marked **†** are on disk and passing but **not reached by `unittest discover`** — see the warning above.

#### Core validation workflow

| Feature | Status | Evidence, and what is missing |
|---|---|---|
| F01 Startup Idea Submission | **Partial** | `run_id` is a fresh UUID under a caller-supplied `session_id` (`service/registry.py::create_run`); queueing is a `ThreadPoolExecutor(max_workers=RUN_CONCURRENCY)`; all seven states exist in `service/models.RunStatus`. Tests: `tests/integration/test_validator_service.py::test_two_gate_round_trips_duplicate_replay_and_logs`, `tests/service/test_graph_registry.py::test_default_executor_uses_configured_run_concurrency`. Missing: the CLI accepts an idea but not a `session_id`, and the Studio's "Send" affordance is unreachable (`canLaunch` excludes `running`/`waiting`, which are the only states that render that label). |
| F02 Structured Idea Scoping | **Partial** | Scoper on `ESCALATION_MODEL` with `tools=[]` (`validator_crew.py:136-143`), asserted by `tests/validator/test_crews.py::test_single_agent_crews_use_expected_models_and_tool_surfaces`. `ScopedIdea` carries every required field including `assumptions` (3-5) and `as_of` (`schemas/validator.py:161-184`). Query lists are joined with `"\n".join(...)` before interpolation (`validator_flow.py:255,271`) — **untested**. "Category-based queries rather than generic keyword appending" exists only as prompt prose; `scope_problems()` does not check query quality at all. |
| F03 Scope Confirmation Gate | **Complete** | Native `@human_feedback` pause, editable fields, deterministic `@router` with zero LLM calls, durable pending feedback, and resume across a fresh app instance — verified by `tests/integration/test_validator_service.py::test_two_gate_round_trips_duplicate_replay_and_logs` and `::test_pending_gate_recovers_and_resumes_in_a_new_app`. **Expiry landed during this reconciliation pass:** a background sweeper (`registry.py`, `VALIDATOR_GATE_SWEEP_INTERVAL_SECONDS`) advances an unanswered gate along an `expired` → `alerted` watch ladder that leaves `answered_at` NULL, so the run stays `waiting`, is never auto-answered, and a late reply still resumes it. Twelve tests in `tests/service/test_gate_expiry.py` cover exactly that, including single-emission across many sweeps, the grace period before alerting, expiry detected after downtime, and no re-emission on recovery. |
| F04 Parallel Research Fan-Out | **Partial** | Three sibling `@listen("scope_approved")` methods with an `and_()` join, one single-agent Crew each, all three appearing as distinct graph nodes. `tests/validator/test_flow.py::test_no_gate_flow_fans_out_transitions_and_persists` asserts a measured `ConcurrencyTracker.maximum == 3`; `::test_flow_definition_has_three_siblings_and_one_join` asserts the topology. Missing: **no sequential fallback exists**, so the "withdraw the parallel implementation if measurement fails" escape hatch in F42 has nothing to fall back to. |
| F05 Market Landscape Research | **Partial** | Cheap-tier analyst + Firecrawl search-with-scrape; both `Document.url` and `metadata.source_url` shapes handled (`tools/market_research.py::_source_url`); plan/rate-limit detection is substring- and status-code-based with **no hard-coded quota**. Tests: `tests/tools/test_market_research.py` (both methods). Missing: `MarketFindings` has **no paying-segment field** and no `retrieved_at`; the 402/"plan limit" branch is untested. |
| F06 Community Sentiment Research | **Partial** | HN Algolia story search then comment-tree retrieval; citations always derived from `objectID`, so a null `story_url` cannot break them; 429 detected without reading rate-limit headers. Tests: `tests/tools/test_hn_sentiment.py` (both methods). Missing: **points and comment counts are never captured** (`Thread` has no such fields); there is **no back-off** — the tool raises, discards partials and returns `rate_limited`; only three of five classification labels are ever produced in tests. |
| F07 Technical Feasibility Research | **Partial** | Module-level shared token buckets at exactly 8/24 req-min, `User-Agent` on every request, honest `rate_limited`, relevance/license/activity capture. Tests: `tests/tools/test_github_feasibility.py` (all three methods, including `assert_called_once`-style header checks across every call). Missing: **archived state is never read** and `Repo` has no field for it; "implementation signals" is only a token-overlap heuristic; the raw license identifier is discarded. |
| F08 Structured Tool Results and Evidence Closure | **Partial** | All three tools return the seven-key envelope; URL-less results are dropped with a note; `URL_CLOSURE` rejects findings URLs outside the captured set; failed/empty/rate-limited status forces empty sources plus an explicit gap. Tests: `tests/validator/test_guardrails.py::FindingsTests` (all three). Missing: the recording tool subclasses and `_capture_urls` (`validator_crew.py:41-98`) have **no test at all**; at the report stage the allowed set is re-derived from findings rather than from the recorded raw tool URLs. |
| F09 Evidence Synthesis | **Partial** | Synthesist on escalation tier with `tools=[]`, consuming all three branches only after `and_()`; five anchored `DimensionScore`s; evidence counts recomputed. Divergences worth deciding on: the model's **kill-criteria candidates are discarded** and replaced by the computed floor list (`schemas/validator.py:365`), and there is no separate draft verdict. **No reasoning setting is configured anywhere** — `agents.yaml` sets no `reasoning`/`reasoning_effort` for the synthesist, so it inherits the provider default rather than an explicit choice. |
| F10 Deterministic Rubric and Verdict | **Complete** | `Verdict.compute_mechanical_result` (`schemas/validator.py:286-371`) computes composite, verdict, confidence, band and provisional in a `@model_validator(mode="after")`. `tests/validator/test_schemas.py::VerdictTests` (11 tests) submits a fixture with deliberately wrong model arithmetic (`composite_score=99, verdict="REJECT", confidence=1`) and asserts every field is overwritten; covers the 7.0 and 4.0 thresholds at the boundary, all four floors, floor ordering, and confidence-override-before-floors. Note: reproducibility is a property of a pure validator on a frozen model rather than a dedicated two-run test. |
| F11 Mechanical Confidence Scoring | **Partial** | Weighted coverage, staleness multiplier, the 0.60 branch penalty and all three band boundaries are computed and tested (`test_schemas.py::test_staleness_and_branch_penalty_are_mechanical`, `::test_confidence_band_boundaries`, `::test_moderate_confidence_reject_is_provisional`); provisional labelling is enforced in **both** title and summary (`test_guardrails.py::test_moderate_reject_requires_provisional_title_and_summary`); LOW-confidence wording is rejected. Missing: the three coverage ratios and `median_market_source_age_months` are **accepted from the model and never recomputed** against the branch findings, so confidence is deterministic given its inputs but its inputs are not mechanical. |
| F12 Verdict Review Gate | **Partial** | Second native gate pauses after synthesis, routes deterministically, and preserves a structured operator override (`route_verdict` re-validates an edited `Verdict`). Server-side gate payload carries verdict and confidence — asserted in `tests/integration/test_validator_service.py::test_two_gate_round_trips_duplicate_replay_and_logs`. Missing: the Studio card renders **neither the rubric nor the evidence gaps** — `GateCard.vue` shows only `verdict`, `confidence` and flat string fields, and `PendingGate` has no gaps field. |
| F13 Validation Report Generation | **Partial** | Reporter on escalation tier; `output_pydantic=ValidationReport` with `output_file` absent, asserted by `tests/validator/test_crews.py::test_tasks_have_structured_outputs_and_report_has_no_output_file`; the Markdown body is written by the Flow `persist` step (`validator_flow.py:349-355`), asserted in `test_flow.py::test_no_gate_flow_fans_out_transitions_and_persists`. Missing: the required sections exist only as prompt prose — **"risks" is not requested at all** — and `report_mechanics_problems` checks none of the score table, kill criteria, cheapest next test, gaps or Sources heading. Fail-on-exhausted-retries relies entirely on CrewAI's own raise; nothing in this repo tests it. |

#### Schemas and guardrails

| Feature | Status | Evidence, and what is missing |
|---|---|---|
| F14 Pydantic Validation Models | **Complete** | All five leaf models and all six stage models present (`schemas/validator.py`). URLs validated with an actionable message and **stored as `str`** — no `HttpUrl` anywhere; `source_urls` mirror validators on all three findings models. Tests: `tests/validator/test_schemas.py::UrlAndFindingTests` (5 tests) covering actionable messages, exact source mirroring, duplicate rejection, the computed `evidence_thin` flag and strict non-coercion of score strings. |
| F15 Zero-Cost Mechanical Guardrails | **Partial** | Status honesty, URL closure, count consistency, required gaps, evidence-count recomputation, report structure, confidence language and provisional labels all implemented and tested (13 tests in `tests/validator/test_guardrails.py`). Crucially `parse_raw_model` returns successful raw text **byte-identical**, asserted twice by exact equality. Missing: **query quality is not validated at all**, and `RUBRIC_ANCHORS` contains anchors for **Demand only** — for M/C/F/X any anchor text passes at every score except the verbatim level-1 reservation. |
| F16 Citation Judgement Guardrail | **Partial** | Exactly one string guardrail, on the reporting task only, ordered after the mechanical callable (`validator_crew.py:336-352`), with the prompt text pinned in YAML and hard-checked against a constant so it cannot drift. The three research tasks carry one callable each and no strings. **No test asserts guardrail count, type or order on any task** — the claim is verified by reading, not by execution. |

#### Cache and retrieval

| Feature | Status | Evidence, and what is missing |
|---|---|---|
| F17 Branch-Level Warm Cache | **Complete** | Lookup happens inside `@listen("scope_approved")` steps, so never before confirmation. Market always, sentiment **never**, feasibility opt-in; branch-specific score and age thresholds; cached evidence labelled with source and retrieval dates and explicitly marked supplemental. Tests: `tests/validator/test_cache.py` (5 relevant methods) plus `tests/validator/test_flow.py::test_market_cache_supplements_but_never_skips_live_research` (asserts the order `lookup → live → index`) and `::test_sentiment_branch_never_looks_up_cache`. |
| F18 Safe Evidence Indexing | **Complete** | One document per source URL with `branch`, `category`, `idea_hash`, publisher and timestamps; branch+category metadata filters reach `index.query(filter=...)`; per-user namespace is an opaque SHA-256 digest that provably does not leak the identity; `ScopedIdea`/`Verdict`/`ValidationReport` are rejected **before any embedding spend**. Tests: `tests/validator/test_cache.py::test_tool_results_become_one_document_per_source_url`, `::test_indexing_uses_only_captured_source_envelopes`, `::test_namespace_is_stable_and_opaque`, `tests/tools/test_indexing.py` (both), `tests/tools/test_pinecone_retrieval.py` (both). |

#### Live event and observability spine

| Feature | Status | Evidence, and what is missing |
|---|---|---|
| F19 Ordered CrewAI Event Capture | **Partial** | ContextVar-scoped stream sink (`events/context.py`) with an opt-in `async def` listener fallback and **no plain sync handler anywhere**; capture does no socket or DB I/O; run context is re-established around resume as well as initial kickoff (`registry.py::_execute` wraps both in `capture_events`); an ordinary CLI run installs no sink so its events are ignored. Tests: `tests/events/test_spine.py::test_capture_is_scoped_ordered_and_immutable`†, `::test_concurrent_contexts_do_not_leak_frames`†. Status held at Partial because the evidence is undiscovered. |
| F20 Versioned Frame Protocol | **Partial** | `{type:"frame", data:{...}}` with `v`, gapless `seq`, run id, timestamp, kind, event type, level, node id, message, bounded details and duration (`events/models.py`); field-by-field mapping with **no `to_json()` and no whole-object traversal**; a structured `edge_taken` frame emitted from the router's return value rather than parsed from a log line. Tests: `test_spine.py::test_router_finish_emits_node_end_then_edge`†, `::test_serializer_clips_fields_without_serializing_live_objects`†. Missing: **`FrameKind.METRICS` is declared in the enum and never emitted by anything.** |
| F21 Stable Node Attribution | **Partial** | Declared node ids in the graph descriptor; the exact task-name → agent-role-prefix → current Flow method → quarantine chain (`events/registry.py::resolve`); each fan-out branch is its own Flow method so branches stay independently attributable; the `unattributed` node is present and visible in the descriptor (asserted by the discovered `test_both_graphs_are_exposed_with_derived_routes`). Missing: **unattributed frames are not counted and the count is not exposed in run status** — `status_payload` reports count/captured/dropped/gaps/emit_errors/subscriber_dropped and nothing else. |
| F22 Token Streaming and Call Timing | **Partial** | `LLMStreamChunkEvent` becomes a non-blocking `llm`/chunk frame; before/after pairs drive live timer chips in the rail with a 100 ms ticker, frozen on completion (`ChatRail.vue`, `useValidatorRun.ts::completeCallEntry`). Missing: **no per-node loading bubble** — chips are per call inside a flat chronological list, so during the three-way fan-out there is no per-node "this node is thinking" affordance. No test (frontend). |
| F23 Per-Run and Per-Node Usage Accounting | **Partial** | Accumulation keyed on `(node_id, model)` with prompt/completion tokens, calls, elapsed ms and cost priced through `compute_cost_usd()` (`registry.py::_record_usage`); UI shows run and per-node totals; a `Flow.usage_metrics` discrepancy is **logged rather than silently resolved**. Tests: `tests/service/test_graph_registry.py::test_llm_usage_is_priced_persisted_and_exposed_by_node_and_model`, `::test_flow_usage_mismatch_is_logged_without_failing_the_run` (both now discovered). Held at Partial because the UI half — per-node and total usage on screen — has no test. |
| F24 Bounded Backpressure | **Partial** | 2,000-frame ring counting evictions as both drop and gap; 512-frame subscriber queues counting drops; a separate `_PersistenceWriter` thread doing every DB write; counters exposed in run status. Tests: `tests/service/test_graph_registry.py::test_status_and_replay_are_bounded` (discovered) and `tests/events/test_spine.py::test_ring_reports_eviction_as_drop_and_gap`† (undiscovered — the ring-eviction counter is the half still invisible to the suite). |

#### Backend service

| Feature | Status | Evidence, and what is missing |
|---|---|---|
| F25 Workflow and Graph APIs | **Complete** | Both endpoints live; topology derived from `build_flow_structure()`; the overlay is validated key-for-key against the derived node set and **startup raises if any router lacks statically inferable events** (`service/graph.py:70-86`); ETag set from a content hash; the Brief Flow router annotation is fixed. Tests: the discovered `tests/integration/test_validator_service.py::test_both_graphs_are_exposed_with_derived_routes` asserts both cache routes, both gate kinds, the quarantine node, fixed layout metadata and the three-way `scope_approved` fan-out; `tests/service/test_app.py::test_graph_run_status_and_frames_contract` adds the ETag header. |
| F26 Run Lifecycle APIs | **Partial** | `POST /api/sessions/{sid}/runs` returns 202 with run id, status and graph version; `GET /api/runs/{rid}` returns status, pending gate, frame counters, error and usage; `GET .../frames` supports `after`, `limit` capped at `MAX_REPLAY_LIMIT=500` and comma-separated kind filtering; `run_id` is distinct from `session_id`. Tests: the integration test exercises the whole path and `tests/service/test_app.py::test_graph_run_status_and_frames_contract` covers kind filtering and the 500 cap. Held at Partial only because the queueing behaviour under `RUN_CONCURRENCY > 1` is asserted on the executor's configuration rather than on an observed queued-then-started run. |
| F27 Human Gate APIs | **In progress** | HTTP replies, structured approve/revise, HTTP 409 on a duplicate and pending-gate recovery through run status are all implemented and covered by the discovered integration test (409 asserted twice, on both gates). The conflict is a real SQL compare-and-set (`UPDATE ... WHERE answered_at IS NULL` + `rowcount == 1`). **Gate replies over WebSocket are still not implemented** — re-checked at the end of this pass, `app.py::incoming` handles `ping` and nothing else. Being implemented now. |
| F28 Cooperative Cancellation | **Complete** | `POST .../cancel` marks the run cancelling; a per-run scoped `PRE_STEP` hook raises `HookAborted` at the next boundary (`registry.py::_cancel_guard`, registered inside `scoped_hooks()`); the response returns an explicit `effect` and `eta_hint` ("stops at the next step boundary" / "up to one agent turn"), and the UI holds "Stopping…" until a server `run_state` frame confirms. Test: `tests/integration/test_validator_service.py::CancellationIntegrationTests::test_cancel_stops_at_next_runner_boundary` (discovered). |
| F29 Log Export | **Complete** | NDJSON and ZIP both served; the ZIP contains `frames.ndjson`, `run.json` and `node-metrics.json`; Download Logs is wired in the Studio controls with a spinner and error state. Tests: the integration test asserts NDJSON ordering and completeness; `tests/service/test_app.py::test_health_readiness_and_log_exports` covers ZIP. Note on shape: gate interactions, tool status and terminal errors travel as ordinary `gate_open`/`gate_closed`/`tool`/`error` frames rather than as separate sections; node timings, usage and cost get their own `node-metrics.json` and `run.json` members in the ZIP. |
| F30 Reconnecting WebSocket | **Partial** | `/ws?session_id=&run_id=&after=` with ping/pong, sequence replay, an explicit `replay_gap` message when the cursor is behind the ring, `replay_truncated` when more remains, client-side dedup and exponential backoff; a slow subscriber drops frames from its own bounded queue rather than blocking the run. Test: discovered integration test reconnects mid-run and asserts exact replayed sequence plus a ping/pong round trip. Missing: **no session TTL cleanup** — `RunRegistry._records` is never pruned and grows for the process lifetime. |
| F31 Durable Run Persistence | **Partial** | Runs, node metrics, ordered frames, gates, session/workflow/flow ids and graph versions all persisted; `PostgresFlowPersistence` implements CrewAI `FlowPersistence` for state and pending feedback; `RUN_CONCURRENCY=1` default with queueing; resumability proven across a **new app instance** (`::test_pending_gate_recovers_and_resumes_in_a_new_app`), with SQLite round trips, frame ordering and idempotency in `tests/service/test_persistence.py` (5 tests). Missing: everything automated runs on **SQLite** — no PostgreSQL exercise, no multi-process compare-and-set test; and frames are batched **by size** (`VALIDATOR_FRAME_BATCH_SIZE=100`, drain-until-empty), not on the ~250 ms cadence the criterion names. |

#### Studio UI

**None of F32-F39 can exceed Partial while `frontend/` has no test runner.** The statuses below record implementation completeness against the criteria; the missing acceptance evidence is common to all of them.

| Feature | Status | Evidence, and what is missing |
|---|---|---|
| F32 Three-Pane Validator Studio | **Partial** | Vue 3 + Vite + Vue Flow; a real three-column grid filling `100dvh`; **both** side rails collapsible; tablet breakpoints at 1180 px and 860 px plus `prefers-reduced-motion`. Divergences: the segmented control is **Graph / Activity, not Chat / Graph**, and it is not a view mode — above 860 px "Activity" only un-collapses the chat rail and "Graph" does nothing. `min-width: 720px` on `html, body`. |
| F33 Fixed Live Agent Graph | **Partial** | Nine fixed nodes (Scoper, three analysts, Synthesist, Reporter, both gates, final) at literal positions, non-draggable/non-selectable/non-connectable; pan, zoom and fit via `<Controls>`; five distinct states in CSS and `stateLabel`. Missing: **no Unattributed node in the UI** (the server publishes one; the Studio's `MOCK_GRAPH` omits it), **no lock control** — `:show-interactive="false"` explicitly disables it — and no start-state node. Node height is not stable: the meta and usage blocks are `v-if`, so nodes grow when usage arrives. |
| F34 Node and Sprite Identity | **Partial — deliberate divergence, still undecided** | **The PRD's 144 downscaled 64×80 character PNGs were never imported, and this is a deliberate substitution rather than an oversight.** What ships instead: kind-based Lucide glyphs (`ShieldCheck`/`FileText`/`Bot`), a static per-node eyebrow string, and two-letter initials on chat avatars. Consequences to accept or reject explicitly: there is **no per-agent palette** (all six agents render identically), **no hash-based assignment**, and **no two-frame walk cycle** — the animation inventory is six CSS keyframes, none of them a sprite cycle. Decide whether the vector identity is the accepted answer and amend the criterion, or whether the sprite work is still owed. |
| F35 Edge and Handoff Visualization | **Partial** | Bezier paths, marching-dash animation on the active edge, condition labels rendered through `EdgeLabelRenderer`, driven by structured `edge_taken` frame details. Missing: **no self-loop case**, **no sprite animated along the path**, **no duration derived from path length** (both timings are hard-coded: a `3200 ms` timer and a `0.75s` CSS animation), **no shared SVG `<defs>`** — the glow is a per-edge CSS `drop-shadow`. Also `activeEdgeId` is a single ref, so the three-way fan-out and the three-way join each animate **one** edge, not three. |
| F36 Live Chat Rail | **Partial** | Timestamped entries in a `role="log" aria-live="polite"` container, auto-scroll, an accessible Show More/Show Less with `aria-expanded`, and timed tool/model chips that tick live and freeze on completion. Missing: **four variants, not seven** — no `tool`, `model` or `human-interaction` variant, so a `gate_open` renders as a generic warning bubble; **no `ResizeObserver`** — collapsing is a raw `message.length > 180` heuristic; per-node attribution is an actor name in a flat interleaved list. |
| F37 Gate Interaction Cards | **In progress** | Editable structured fields seeded from the gate payload; a live `expires_at` countdown with an `MM:SS remaining` display; expired state disables every input and option and is re-checked before POSTing; the card survives refresh via `localStorage` + `GET /api/runs/{id}` and survives a socket drop. Missing: **no rubric and no evidence gaps on the verdict card**; **expiry is card-only — the node stays visually `waiting` forever** (`NodeRunState` has no `expired` member). Gate replies go over HTTP (`studioApi.ts` POSTs to `/api/runs/{id}/gates/{id}`); the WS path is being added. The countdown now has a server-side counterpart — see F03. |
| F38 Run Controls | **Partial** | Read-only status badge, Launch/Relaunch/Cancel/Download Logs, Lucide icons throughout; Relaunch does immediately start a new run with the current idea; cancellation waits for a server `run_state` frame before showing `cancelled`. Missing: **no workflow selection** — the panel prints the literal strings "Idea Validator" and "M2" in a read-only well, and `workflowId` cannot be changed from the UI; the "Send" label is unreachable as an enabled button; the three primary actions carry no tooltips. |
| F39 Error and Recovery UX | **Partial** | Frame drops counted and shown in red; four connection states with backoff; server failures surfaced in a dismissable `role="alert"` banner; **run status and connection status are genuinely independent refs**, so a failed run and a disconnected browser are cleanly distinguished; last confirmed state is preserved across reconnect by never clearing it. Missing: **guardrail exhaustion has no representation anywhere in the frontend**; tool failures get only the generic error treatment; unattributed events are labelled "System" rather than surfaced as unattributed; evidence-thin `NEEDS_WORK` ends green only incidentally, not by any implemented rule. Defect found: `localStorage` is never cleared, so a terminal run is re-restored on every page load. |

#### Delivery, quality, and operations

| Feature | Status | Evidence, and what is missing |
|---|---|---|
| F40 Headless Validator CLI | **Partial** | `validate` entry point in `pyproject.toml` with `--idea`, `--no-gates`, `--resume`, `--feedback`, `--namespace` and `--feasibility-cache`; dependency-injected crew factories keep it testable with no spend. Test: `tests/validator/test_flow.py::test_validate_headless_entry_point_uses_injected_factories`. Missing: **concurrent branch output is not prefixed with node names** — there is no per-branch print prefixing in `validator_flow.py`, so a live three-way trace interleaves unlabelled. |
| F41 Service Entry Point and Environment | **Partial** | `serve` entry point; the `service` extra is installed in `.venv` (FastAPI 0.141.1, SQLAlchemy 2.0.52); `.env` loads from the package path with `override=True`; startup asserts every model constant and every YAML `llm`/`function_calling_llm` uses the `openrouter/` prefix, **before FastAPI is even imported** (`app.py:114`). Tests: `tests/service/test_app.py::test_startup_rejects_non_openrouter_model_constants` and `tests/validator/test_crews.py::test_owned_implementation_has_no_openai_model_string` (both discovered). Divergence: `PYTHONIOENCODING=utf-8` is **not set**; the equivalent is achieved by reconfiguring `sys.stdout`/`sys.stderr` at package import (`src/brief_crew/__init__.py`), which is stronger for the CLI but does not cover a subprocess. |
| F42 Performance Validation | **Not started** | **Nothing here has ever been measured.** No five-parallel/five-sequential comparison, no ≥1.8× speedup figure, no peak-RSS number against the 400 MB target, no gate reply-to-resume latency against the 500 ms target. `tests/validator/test_flow.py` proves three branches run *concurrently* (`ConcurrencyTracker.maximum == 3`) — that is a structural fact, not a speedup measurement. No live run of any kind has happened. |
| F43 Correctness and Regression Tests | **Partial** | Verified: repeatable verdict bands from identical evidence (by construction, `test_schemas.py::VerdictTests`), gapless frame sequences (discovered integration test asserts `seq == 1..n`), no event leakage across concurrent runs (`test_spine.py::test_concurrent_contexts_do_not_leak_frames`† — undiscovered), reconnect, duplicate reply, restart recovery and post-gate attribution (discovered integration tests), and that every router exposes statically inferable labels (`service/graph.py` raises at import; asserted in `tests/service/test_graph_registry.py`). **Not verified: zero fabricated citations across an acceptance set** — no acceptance set exists and no live run has been made. Gate timeout is now verified — `tests/service/test_gate_expiry.py` (12 tests), added during this pass. **Not verified: Brief Crew behaviour and output unchanged** — there is **no Brief Crew regression test anywhere in `tests/`**; nothing touches `run_crew()`, `kickoff()`, `output/brief.md` or `output/last_run.json`. |
| F44 Deployment Readiness | **In progress** | Health and readiness endpoints report per-dependency status and return 503 when storage is unhealthy; `DATABASE_URL` is honoured with `postgres://`/`postgresql://` normalised to `postgresql+psycopg://`; the frame writer flushes on close via the FastAPI lifespan; credentials stay within the provisioned set with an optional `GITHUB_TOKEN`. `render.yaml`, `Dockerfile` and `.github/workflows/` appeared during this reconciliation pass and are **not yet verified against a deployed host**. Still missing: a configured shutdown delay, so the lifespan flush is not guaranteed enough time to drain the frame writer on the target host. |

### Measurement and verification debt

Carried explicitly so it is not mistaken for completed work:

| Debt | Blocks | Note |
|---|---|---|
| Missing `tests/events/__init__.py` | Honest status for F19-F24 | Six passing tests invisible to the documented command. `tests/service/` was fixed during this pass. |
| No frontend test runner | F32-F39 reaching Complete | `frontend/package.json` declares none. |
| Fan-out speedup, peak RSS, gate latency | F42 | Never measured. |
| Live paid acceptance run + citation-closure set | F43 | Never run. Everything uses doubles or `synthetic=True`. |
| Live PostgreSQL exercise | F31, F44 | SQLite only; multi-process compare-and-set untested against PG 18. |
| Brief Crew regression test | F43 | No test covers the Track A/B behaviour the platform rules forbid regressing. |
| Firecrawl plan economics | F05 | Real rate limits and per-credit search+scrape cost unmeasured (PRD Q3). |
| Reporter/Scoper cheap-tier A/B | F13, F02 | Not run (PRD Q4); listed under Deferred Enhancements below. |
| F34 sprite decision | F34 | The vector/icon identity is a deliberate substitution. **Undecided** whether the criterion is amended or the sprite work is still owed. |

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
