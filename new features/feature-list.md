# Validator Studio Feature List

Source: [`PRD.md`](../PRD.md), dated 2026-08-29.

Validator Studio is additive to the existing Brief Crew. It combines a six-agent CrewAI startup validator with a live Vue 3 graph interface, durable human approval gates, structured evidence, and deterministic scoring.

## Implementation Status

Last synchronized: 2026-08-29

Status meanings: **Not started** has no implementation; **In progress** has an active implementation slice; **Partial** has verified behavior but incomplete acceptance criteria; **Complete** has passing executable acceptance evidence; **Blocked** has an external dependency preventing completion.

| Milestone | Features | Status | Verified evidence |
|---|---|---|---|
| M-1 Prerequisites | F25 plus event and persistence prerequisites | **In progress** | `BriefFlow.check_cache` now returns `Literal["cache_hit", "cache_miss"]`; `build_flow_structure(BriefFlow)` verifies 6 nodes and 6 edges, including both labelled router edges. |
| M0 Event spine | F19-F24 | **In progress** | Parallel implementation workstream started. |
| M1 Service | F25-F31 | **Not started** | Depends on the M0 frame contract. |
| M2 Studio | F32-F39 | **Not started** | Frontend workstream is being prepared against mock frames and the API contract. |
| M3 Validator | F01-F18, F40, F42 | **Not started** | Schema, tool, guardrail, and orchestration workstreams are being prepared. |
| M4 Gates | F03, F12, F27, F37 | **Not started** | Depends on validator state, service APIs, and durable persistence. |
| M5 Hardening | F23-F24, F29-F31, F41-F44 | **Not started** | Final integration and measured acceptance milestone. |

### Feature Evidence Ledger

| Feature | Status | Evidence |
|---|---|---|
| F25 Workflow and Graph APIs | **Partial** | Static topology defect repaired and verified; HTTP endpoint and ETag remain outstanding. |
| F01-F24, F26-F44 | **Not started** | No feature may move to Complete until its executable acceptance check passes. |

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
