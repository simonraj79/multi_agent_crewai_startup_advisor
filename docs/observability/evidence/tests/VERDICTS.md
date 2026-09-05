# V-REVIEW verdicts — C1, C3, D4, D6, E2, E3, F2, F3

Second pass, 2026-09-06, by V-REVIEW, who **built none of this code and edited
none of it**. The first pass is [`REVIEW.md`](REVIEW.md); it is kept unchanged,
including the findings this pass closes, because the diagnosis is the part worth
keeping.

**The tree is uncommitted.** `git rev-parse HEAD` =
`b65bd654003bcbc92e8ff643d245cf173d92dc0e`, which does **not** contain any of
this: `src/brief_crew/observability/`, `scripts/observability/`,
`tests/observability/` and `docs/observability/` are untracked, and
`config.py`, `events/serializer.py`, `service/app.py`, `service/registry.py`,
`service/runner.py` and `tests/__init__.py` are modified. Every `.txt` beside
this file carries the **md5 of `src/brief_crew/observability/*.py` at the moment
its commands ran**, which is what pins this evidence to code a later commit can
be compared against. The md5s were identical across every run in this pass.

Everything below was measured on Windows, python 3.13.5, crewai 1.15.18,
langfuse 4.15.1.

## The table

| Row | Verdict | Evidence, in one sentence |
| --- | --- | --- |
| **C1** | **PASS** | `test_no_flow_identifiers.py` 6/6 green, and V-REVIEW's own wider extractor — 134 identifiers including the registered workflow ids, both flow classes, every flow **method** name (which are the node ids), the builder agent/crew libraries, all 11 `BUILDER_ACTION_REFS` and the 11 builder platform tool ids — found **31 hits over 10 sources, every one a coincidental English substring** (`report` in "reporting", `scope` in `_NodeScope`, `turn` in "returns") and not one distinctive identifier: [`C1.txt`](C1.txt). |
| **C3** | **PASS** | `test_event_coverage.py` 16/16 green, and an enumeration that does **not** use the exporter's own walk confirms **165 = 36 mapped + 129 unmapped-with-reason**, no overlap, nothing in neither table, no stale row, no BaseEvent subclass outside the enumeration on a text sweep of the whole installed package, and all 36 mapped names present as real `isinstance` branches by AST: [`C3.txt`](C3.txt). |
| **D4** | **PASS** | `test_retry_legibility.py` 9/9 green: a guardrail retry is two generations under one task span with `attempt` `[1, 2]` and the verdict as a score on the task, and a transport retry is a failed generation at `level=ERROR` followed by a successful one, both driven as real `FrameData`: [`D4.txt`](D4.txt). |
| **D6** | **PASS** | `test_terminal_states.py` 20/20 green: the ceiling abort ends the trace `failed` with the ceiling and the figure named, and the first pass's fabricated-money defect is closed — `service_restart` now has its own branch and its own tests, and `ReasonConstantMirrorTests` pins both constants against the registry's own: [`D6.txt`](D6.txt). |
| **E2** | **PASS** | `test_exporter_isolation.py` **16/16 green in 22.7 s, process exit code 0, 25 s wall clock including interpreter exit** — the first pass could not report this row at all because the module wedged forever; the three conditions are three separate tests, each against a control run: [`E2.txt`](E2.txt). |
| **E3** | **PARTIAL** | `test_content_policy.py` 23/23 green and the planted-key experiment repeated: every `statusMessage` and the trace `output.reason` now read `***`, and the DSN and its password with them — but **one field still leaves verbatim on both policies**, `run span .metadata.run_metrics.reason`, carrying the planted key, the whole DSN and the password: [`E3.txt`](E3.txt). |
| **F2** | **PASS** | Six rows say "a committed test"; six modules serve them, one each, no row without a test and no test in that set without a row. Two further modules (`test_trace_shape.py` 38, `test_prompt_fingerprint.py` 13) pin the trace contract the proof rows are read against and are named for the orchestrator to rule on rather than left to be discovered: [`INDEX.md`](INDEX.md). |
| **F3** | **PASS** | The scan answers **0 actual credential values** against the 11 credential variables this process holds, and V-REVIEW examined **all 75** token-shaped warnings: the two the brief names are placeholders as described, 52 more are the `capture-on` proof run's planted `sk-or-v1-` + zeros marker, 10 are the middle of a UUID (`…-4bfc-…`), and 11 are test placeholders that are English words after the prefix: [`secret-scan.txt`](secret-scan.txt), [`INDEX.md`](INDEX.md) §6. |

**Seven PASS, one PARTIAL, no FAIL.**

## The first pass's BLOCKER/HIGH findings, re-verified against current code

| # | Sev then | Now | Where it was closed |
| ---: | --- | --- | --- |
| 1 | BLOCKER | **CLOSED** | Every raw error read goes through one choke point: `langfuse_exporter.py:1205-1216` `_safe` → `content.py:130-161` `safe_message`, called at `:1010`, `:1514`, `:1559`, `:1601`, `:1964`, `:2027`. It scrubs **before** it bounds, which is the opposite order from `scrub_text` and the right one here — cutting first can split a key so the shape rule stops matching while most of it is still on the wire. Measured: six observations and the trace output that carried the planted key now read `***`. |
| 2 | BLOCKER | **CLOSED** | `close()` runs each closable under `backend.py:477-515` `_bounded`, a daemon worker with a timeout, so no SDK `Queue.join()` can hold the caller — and the caller here is `service/app.py`'s lifespan shutdown and, through the SDK's own `atexit`, interpreter exit. |
| 3 | BLOCKER | **CLOSED** | `backend.py:517-557` `_evict_resource_manager` pops the key from `LangfuseResourceManager._instances` under that class's own lock **and** `atexit.unregister`s the manager's shutdown; `LangfuseBackend.close()` evicts first and bounds second (`:786-800`), so a wedged shutdown cannot leave a stale cache entry for the next exporter. |
| 4 | HIGH | **CLOSED** | `langfuse_exporter.py:1001-1055` compares `reason` against `COST_CEILING_REASON` and `INTERRUPTED_REASON` by name instead of reading it as a boolean; a `service_restart` orphan is now `failed` with *"interrupted by a service restart before the run finished"* and **no money figure**, and any third reason stays `cancelled` and is reported. |
| 5 | HIGH | **CLOSED** | `content.py:47-54, 101-109` selects credential values by **shape** as well as by name: a URL carrying userinfo is held whole and its password segment separately, so `DATABASE_URL` — whose name `is_secret_key` will never match — is covered, and so are `REDIS_URL` and whatever the next one is called. |
| 6 | HIGH | **MOSTLY CLOSED** | The serializer's unhandled tally now travels: `serializer.py:866-888` `_unhandled_report` puts per-class counts on the run's terminal frame and `langfuse_exporter.py:974-999, 1167-1175` writes them onto the trace as `unhandled_event_counts`. **Residual:** it is spliced in at `serializer.py:546` and `:554` only — the FlowFinished and FlowFailed drafts — so a run whose terminal frame comes from the **registry** (operator cancel, cost-ceiling abort, the orphan sweep's `service_restart`) carries no tally at all. |
| 7 | HIGH | **CLOSED** | `_enqueue_shutdown` (`:614-620`) is a `put_nowait` with a drop-oldest fallback, and `_displace` (`:500-538`) now puts a `_FlushMarker` or the `_SHUTDOWN` sentinel **back** instead of discarding whatever `get_nowait` returned — finding 13 closed in the same edit. |

Findings 9 and 10 (the C3 test that could not fail; the two `crewai/skills/events.py`
classes outside every count) are closed too: `UNMAPPED_WITH_REASON` is written
out rather than derived, `unmapped_reason` returns `""` for a class nobody wrote
a reason for, and the enumeration walks `crewai.skills.events` — 163 became 165.

## Still open, with severity

| # | Sev | Open item |
| ---: | --- | --- |
| 15 | **MEDIUM** | **The one E3 hole.** `run span .metadata.run_metrics.reason` is copied verbatim from the METRICS frame (`langfuse_exporter.py:957-963` selects `usage`/`frames`/`reason`, `:1166` folds it onto the run span) and passes **neither** `policy_details` nor `safe_message`. It is the only field in the payload that bypasses both; its sibling `computed_result` on the same span **is** filtered (`:1817-1821`), which makes this an omission rather than a design. What saves it today is an accident: the only producer is `RunRecord.emit_metrics(reason)` (`service/registry.py:1133`) and all ten call sites pass one of five literals, so no credential can reach it through the app as it stands. One call fixes it. |
| 6r | **MEDIUM** | The unhandled-event tally rides only the flow's own terminal frame, so cancelled, budget-stopped and service-restart runs — exactly the runs a reader investigates — reach Langfuse with no `unhandled_event_counts`. |
| 11 | **MEDIUM** | `http_errors` — the number row E2 calls the one most easily made a lie — rests on `TransportFailureCounter`, a `logging.Handler` attached to **two hardcoded logger names** (`backend.py:395-421`). Against the real SDK the raise-at-the-call-site half almost never fires, so an SDK upgrade that renames a logger silently returns the count to zero while the summary still reports a clean export, and no test can see it because the tests' doubles raise. |
| 12 | **MEDIUM** | `TransportFailureCounter.attach()` adds the handler to **process-global** loggers, so two backends in one process each count the other's failures. |
| 16 | **MEDIUM** | `reason` and `decision_reason` are on `STRUCTURAL_STRING_KEYS` (`content.py:313-351`), so free text under those keys passes through verbatim to 256 characters on the default policy. Shape-scrubbed, so key-safe; still text-leaking if a flow ever writes a sentence there. |
| C3r | LOW–MED | Four of the 21 unmapped reasons say in their own words that they are **gaps, not decisions** — `knowledge_events` (7 classes, *"the largest single gap on this list"*), `mcp_events` (7, *"a real gap"*), `reasoning_events` (4), `hook_events` (1). Honest and informative, so V-REVIEW does not read them as placeholders; named because "deliberately unmapped" and "a gap we wrote down" are different claims, and because knowledge + memory (17 classes) means **embedding and retrieval spend appears in no figure this programme produces**. |
| C1r | LOW | The committed C1 test still has **no extractor for the row's words "flow name"** — not the workflow ids, not the flow classes, not the flow method names that are the node ids — so `if frame.node_id == "confirm_scope"` would pass all six of its tests, and no extractor for the builder library registries. The property holds at this tree (measured), but the test is narrower than the row. Its skill-pack half can also silently skip, and the control test sets floors for yaml/tools/crews and **not** for skills. |
| 17 | LOW | The key-shape regex is **case-sensitive** and needs a ≥ 6-character body (`content.py:42-45`), so `GHP_…`, `SK-OR-…` and `AIZA…` survive it. |
| 18 | LOW | Contract §4 says a generation's `input` is *"present, redacted, when `LANGFUSE_CAPTURE_CONTENT=1`"*. It is never emitted under either policy, because no frame carries a prompt — the DoD's own B5 revision says no content enters a frame. The code is right; the contract table is the stale half. |
| 21 | LOW | `LANGFUSE_FLUSH_INTERVAL_SECONDS` defaults to `0.25`; contract §9 says *"≈ 1.0"*. Deliberate per the B4 revision (*"≤ 0.25 s drain"*), so again the contract is the stale half — worth reconciling so a reader is not left choosing. |
| F3r | LOW | `scripts/observability/secret_scan.py`'s `fc-` pattern matches **inside a UUID** (`…-4bfc-…`); 10 of the 75 token-shaped warnings are that, and the count grows with the evidence tree. Anchoring `fc-` on a word boundary fixes it. Separately, `secret-scan.txt` is written into a scanned path, so each run scans the previous run's prefix list and the bare-prefix count compounds — 1,059 → 3,179 → 7,422 in eight minutes, over an unchanged 0 actual values and an unchanged 75 token-shaped. |

## What would make E3 a PASS

One change, and it is smaller than the finding: filter `run_metrics` where it is
folded onto the run span, the way `computed_result` already is —

```python
run_span.metadata["run_metrics"] = policy_details(
    state.metrics,
    capture=self.policy.capture_content,
    secret_values=self.policy.secret_values,
)
```

— or `safe_message` over `reason` where the three keys are selected at `:957-963`.
A test asserting a planted key in a METRICS `reason` does not reach the payload
would then pin it; `test_content_policy.py` has the harness for it already and
plants in every carrier **except** that one.
