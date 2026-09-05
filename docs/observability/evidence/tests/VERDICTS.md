# V-REVIEW verdicts — C1, C3, D4, D6, E2, E3, F2, F3

**Final, 2026-09-06, at `58a1c0b`.** By V-REVIEW, who **built none of this code
and edited none of it**, and whose only writes are under
`docs/observability/evidence/tests/`. The first pass is [`REVIEW.md`](REVIEW.md);
it is kept unchanged, including the findings later commits closed, because the
diagnosis is the part worth keeping.

## Provenance — this review measured four commits, not one

The programme was working-tree state when the review began and was committed
under it, in four commits. Every one was re-measured rather than assumed:

| commit | what | what V-REVIEW re-ran |
| --- | --- | --- |
| `b65bd65` | the tree at the start — no observability code | — |
| `e68dac4` | the exporter, the audit, the DoD, the reconciliation tooling | all eight rows (first full pass) |
| `7417270` | the synthetic double's prompt digest, the trace fixture's messages | nothing in the exporter package moved (`git diff` empty), so the figures carried |
| `ad6a696` | the E3 fix, the tally on every terminal, the C1 test able to fail | E3 in full, plus the two MEDIUMs it closed |
| `58a1c0b` | error class on every error observation, deferred billed cost, identity scrubbed by value only, the `fc-` boundary, tests own their OTel state | **all six test rows re-run and re-pasted, both probe scripts re-run unedited, F3 regenerated** |

Each row's `.txt` now carries a dated section per commit it was measured at,
with `git rev-parse HEAD` and the md5 of `src/brief_crew/observability/*.py` at
run time. **The md5s are of the WORKING-TREE files**, and most differ from
`git show <commit>:<path> | md5sum` for one reason: `core.autocrlf` is true
here, so the index holds LF and the working copy CRLF (`git ls-files --eol` →
`i/lf w/crlf`). Compare across that boundary with `git diff`, never with a raw
md5. At `58a1c0b`, `git diff HEAD -- src/ tests/` is empty.

Measured on Windows 11, python 3.13.5, crewai 1.15.18, langfuse 4.15.1.

## The table

| Row | Verdict | Evidence, in one sentence |
| --- | --- | --- |
| **C1** | **PASS** | `test_no_flow_identifiers.py` **10/10** — it gained the three extractors this review found missing (flow method names = node ids, both workflow ids, the builder libraries) and a control that plants a node id and proves the search would find it — and V-REVIEW's own wider grep, re-run unedited, finds **33 hits over 134 identifiers, every one a coincidental English word** and not one distinctive identifier: [`C1.txt`](C1.txt). |
| **C3** | **PASS** | `test_event_coverage.py` **16/16**, and an enumeration that does **not** use the exporter's own walk confirms **165 = 36 mapped + 129 unmapped-with-reason**, no overlap, nothing in neither table, no stale row, nothing outside the enumeration on a text sweep of the whole installed package, and all 36 mapped names real `isinstance` branches by AST: [`C3.txt`](C3.txt). |
| **D4** | **PASS** | `test_retry_legibility.py` **9/9**: a guardrail retry is two generations under one task span with `attempt` `[1, 2]` and the verdict as a score on the task; a transport retry is a failed generation at `level=ERROR` followed by a successful one, both driven as real `FrameData`: [`D4.txt`](D4.txt). |
| **D6** | **PASS** | `test_terminal_states.py` **35/35**: the ceiling abort ends the trace `failed` with the ceiling and the figure named, `service_restart` has its own branch and is not reported as a $0.00 budget breach, the constants are mirrored against the registry's own, and C3's tally now rides all five terminals the registry writes: [`D6.txt`](D6.txt). |
| **E2** | **PASS** | `test_exporter_isolation.py` **16/16 in 22.5 s, process exit code 0, 26 s wall clock including interpreter exit** — the first pass could not report this row at all, because the module wedged forever on the SDK's unbounded `Queue.join()`; the three conditions are three separate tests, each against a control run: [`E2.txt`](E2.txt). |
| **E3** | **PASS** | `test_content_policy.py` **33/33**, and both probe scripts re-run **unedited**: the planted-key probe is **CLEAN on all six conditions**, and the locator reports **zero fields under the default policy** and exactly three under `LANGFUSE_CAPTURE_CONTENT=1` — all of them the user's own sentence, with the planted key and DSN already `***` inside those same strings, which is the capture switch working: [`E3.txt`](E3.txt) §§1–4. |
| **F2** | **PASS** | Six rows say "a committed test"; six modules serve them, one each. The package grew 141 → 151 → 181, and every one of those 40 tests pins something a V-REVIEW pass measured or a builder audit found. Checked **class by class**: every class in the two supporting modules maps to a named row, and no test serves no row: [`INDEX.md`](INDEX.md). |
| **F3** | **PASS** | Regenerated at `58a1c0b`: **FAIL = 0** against the 11 credential variables this process holds, WARN 8,125 of which **65 token-shaped, all examined** — 51 the capture-on proof run's planted marker, 11 test placeholders, 2 the `pk-lf-not-a-real-key` prose quote, 1 the all-zeros `fc-` injection — and the **ten UUID false positives are gone**, 75 → 65, while the tree grew. `--self-test` passes 17/17: [`secret-scan.txt`](secret-scan.txt), [`INDEX.md`](INDEX.md) §6. |

**Eight PASS. No PARTIAL, no FAIL.** E3 was PARTIAL at `e68dac4` and was closed
at `ad6a696`; every other row has been PASS since it could first be measured.

## The first pass's BLOCKER/HIGH findings — all closed

| # | Sev then | Closed at | Where |
| ---: | --- | --- | --- |
| 1 | BLOCKER | `e68dac4` | Every raw error read goes through one choke point, `_safe` → `content.safe_message`, which scrubs **before** it bounds — cutting first can split a key so the shape rule stops matching while most of it is still on the wire. |
| 2 | BLOCKER | `e68dac4` | `close()` runs each closable under `backend._bounded`, a daemon worker with a timeout, so no SDK `Queue.join()` can hold the caller — and the caller is `app.py`'s lifespan shutdown and, through the SDK's `atexit`, interpreter exit. |
| 3 | BLOCKER | `e68dac4` | `_evict_resource_manager` pops the key from the SDK's process-wide cache **and** `atexit.unregister`s the manager's shutdown; `close()` evicts first and bounds second. |
| 4 | HIGH | `e68dac4` | `_terminal_of` compares `reason` against `COST_CEILING_REASON` and `INTERRUPTED_REASON` by name; an interrupted run is no longer reported as a run that breached a **$0.00** ceiling. |
| 5 | HIGH | `e68dac4` | Credential values are selected by **shape** as well as name, so `DATABASE_URL` — invisible to `is_secret_key` — is held whole and by its password segment. |
| 6 | HIGH | `ad6a696` | The serializer's unhandled tally reaches the trace, and rides **all five** `WORKFLOW_END` sites the registry writes, not only the flow's own. |
| 7 | HIGH | `e68dac4` | `_enqueue_shutdown` is a `put_nowait` with a drop-oldest fallback; `_displace` puts a flush marker or the shutdown sentinel **back** instead of discarding it. |

Findings 9, 10, 13, 15 and the C1 extractor gap are closed too, each named in
the list below with its fix.

## Still open, with severity

Closed items are struck through and **kept**, not deleted: a closed finding with
its fix named beside it is the only version of this list that can be checked
later.

| # | Sev | Item |
| ---: | --- | --- |
| 15 | ~~MEDIUM~~ **closed `ad6a696`** | ~~`run_metrics.reason` copied verbatim onto the run span.~~ Now through `policy_details` where its keys are selected. The audit it prompted found **five more** copy sites and fixed them in the same commit; `58a1c0b` then extended the rule to every identity field. |
| 6r | ~~MEDIUM~~ **closed `ad6a696`** | ~~The tally rode only the flow's own terminal frame.~~ Five `WORKFLOW_END` sites, pinned by a test that greps the registry for them. |
| C1r | ~~LOW~~ **closed `ad6a696`** | ~~No extractor for "flow name" or the builder libraries.~~ Three extractors, an `_is_distinctive` filter, and a can-fail control. `if frame.node_id == "confirm_scope"` would now fail that module. |
| 11 | **MEDIUM** | `http_errors` — the number row E2 calls the one most easily made a lie — rests on `TransportFailureCounter`, a `logging.Handler` attached to **two hardcoded logger names** (`backend.py:395-421`). Against the real SDK the raise-at-the-call-site half almost never fires, so an SDK upgrade that renames a logger silently returns the count to zero while the summary still reports a clean export, and no test can see it because the tests' doubles raise. |
| 12 | **MEDIUM** | `TransportFailureCounter.attach()` adds the handler to **process-global** loggers, so two backends in one process each count the other's failures. |
| 16 | **MEDIUM** | `reason` and `decision_reason` are on `STRUCTURAL_STRING_KEYS`, so free text under those keys passes verbatim to 256 characters on the default policy. Shape-scrubbed, so key-safe; still text-leaking if a flow ever writes a sentence there. Nearest relative of the bug `ad6a696` fixed. |
| C3r | LOW–MED | Four of the 21 unmapped reasons say in their own words that they are **gaps, not decisions** — `knowledge_events` (7 classes, *"the largest single gap on this list"*), `mcp_events` (7, *"a real gap"*), `reasoning_events` (4), `hook_events` (1). Honest and informative, so not placeholders; named because "deliberately unmapped" and "a gap we wrote down" are different claims, and because knowledge + memory (17 classes) means **embedding and retrieval spend appears in no figure this programme produces**. The one thing on C3 an orchestrator should rule on rather than inherit. |
| 17 | LOW | The key-shape regex is **case-sensitive** and needs a ≥ 6-character body, so `GHP_…`, `SK-OR-…` and `AIZA…` survive it. |
| 18 | LOW | Contract §4 says a generation's `input` is *"present, redacted, when `LANGFUSE_CAPTURE_CONTENT=1`"*. It is never emitted under either policy, because no frame carries a prompt — the DoD's own B5 revision says no content enters a frame. The code is right; the contract table is the stale half. |
| 21 | LOW | `LANGFUSE_FLUSH_INTERVAL_SECONDS` defaults to `0.25`; contract §9 says *"≈ 1.0"*. Deliberate per the B4 revision, so again the contract is the stale half. |
| F3r | LOW | `scripts/observability/_common.py` applies the credential boundary to **every** prefix, and it is a redactor as well as a scanner: `gate-sk-or-v1-…` and `user-ghp_…` are blanked by `content.py` and **not** by `_common.py`'s redaction pattern, which is what writes pulled Langfuse exports into `evidence/`. Bounded by the unconditional exact-value rule ahead of it and by the exporter scrubbing that shape on the way out. [`INDEX.md`](INDEX.md) §6. |
| F3s | LOW | Both copies require `fc-` + 20 **hex**, so an `fc-` key with a non-hex tail is invisible to both. A bet on the vendor's format, not a defect; the exact-value rule covers it meanwhile. |

## Closing — what these eight rows do and do not certify

**They certify the instrumentation path, not the run.** Every figure above comes
from unit-level tests and from V-REVIEW's own probes against an in-memory
backend. Rows A*, B*, C2, D1–D3, E1, E4, E5, F1 and F4 belong to V-PROOF,
V-RECON and ORCH and are answered by real runs, not by anything here.

**The full Python suite does not complete on this machine, and that is
pre-existing.** [`stability/REPORT.md`](stability/REPORT.md) — V-STABILITY,
twelve alternating full-suite runs, six per arm, one machine, one interpreter —
measured `Windows fatal exception: access violation`, exit 139, on **the
pre-observability baseline `b65bd65` 2 times in 6** and on the observability
tree **1 time in 6**; Fisher exact p = 1.00, and one baseline crash's faulting
stack reads entirely from the baseline worktree's own source. The signature is a
property of this suite on Windows — a large population of never-joined registry
threads outliving the tests that made them, identical on both arms to the last
thread — and is not caused by the observability work.

**V-REVIEW's own attempts at `58a1c0b`: four runs, four crashes**, exit 139 each,
at three different points (a different builder flow each time), 74–111 s in.
Two things follow and neither is a contradiction of the report:

* This machine had been running suites back to back all session, and the
  report's arms were **alternated** precisely to control for that, where these
  four were not. 4/4 here is not comparable with 1/6 there, and V-REVIEW is
  **not** claiming a regression.
* But it does mean the builder's recorded **"2707 tests OK on the one run that
  survived"** is a figure this review **relays and could not reproduce**. It is
  a single observation. The observability package itself is stable — 181/181,
  run more than a dozen times this session with no crash and no flake — as are
  `tests/events` (105) and the service modules exercised here.

So the honest statement of what is green: **every module these eight rows depend
on passes, repeatedly and alone; the full-suite figure is one run nobody has
repeated, on a suite that crashed before this programme existed.** Whoever owns
the merge should decide whether a suite with a 1-in-4-to-1-in-6 access violation
is a merge blocker in its own right. It is not this programme's defect, and it
is not this programme's call.
