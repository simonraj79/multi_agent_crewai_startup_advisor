# V-REVIEW — code, test and policy review of `src/brief_crew/observability/**`

Written 2026-09-05 by V-REVIEW, who built none of this code and edited none of
it. Two halves: a hang diagnosis, and the row review for **C1, C3, D4, D6, E2,
E3** of [`DEFINITION-OF-DONE.md`](../../DEFINITION-OF-DONE.md) against
[`TRACE-CONTRACT.md`](../../TRACE-CONTRACT.md).

**No test output is pasted here.** The suite does not currently finish (Part 1);
a later pass owns `evidence/tests/` output once it is green. Every measurement
quoted below was run by V-REVIEW for this review and says so where it sits.

**Nothing in this file is a credential value.** Every key-shaped string quoted
is a prefix or a placeholder of repeated characters that authenticates against
nothing.

> **`TRACE-CONTRACT.md` was revised by another agent while this review was
> running.** Findings below were formed against the earlier text and then
> re-checked against the revision; where the revision changed the answer, the
> finding says so. §8 (content policy), §7 (scores), §9 (knobs) and §10
> (self-report) are unchanged, so findings 1, 5, 8, 17, 19 and 21 are unaffected.
> §1 changed the trace-`tags` rule and added `run_metrics` to trace metadata —
> see §C1 point 1 and finding 15.

---

## Part 1 — the hang

### Verdict

`tests/observability/test_exporter_isolation.py` wedges **permanently**, not
slowly. Every other module passes in under 0.1 s (`test_content_policy` 13,
`test_event_coverage` 10, `test_no_flow_identifiers` 6, `test_retry_legibility`
9, `test_terminal_states` 13, `test_trace_shape` 29 — all OK, re-run for this
review).

The cause is **not** the slow host, **not** the `LANGFUSE_HTTP_TIMEOUT_SECONDS`
default (5.0, which satisfies contract §9's "≤ 5"), and **not** a missing
timeout in the exporter's own thread handling — those were all observed
behaving correctly. The cause is that the **langfuse SDK caches its
`LangfuseResourceManager` by public key and does not evict it on `shutdown()`**.
The second exporter built with the same public key in one process inherits a
manager whose score-ingestion consumer thread is already dead, so nothing ever
calls `task_done()` and every later `flush()`/`shutdown()` blocks forever on an
unbounded `queue.Queue.join()`.

### The stuck stacks

`faulthandler.dump_traceback_later(75)` over
`tests.observability.test_exporter_isolation.UnreachableBackendTests`. The first
test passed; the second never returned. Two threads parked on the same
unbounded `Queue.join()`, and a third parked on the second:

```text
Thread 0x00000734  (the exporter's own "langfuse-exporter" thread)
  langfuse_exporter.py:532  in _loop
  langfuse_exporter.py:663  in _settle
  langfuse_exporter.py:956  in _close_out
  backend.py:634            in flush              -> self._client.flush()
  langfuse/_client/client.py:2335           in flush
  langfuse/_client/resource_manager.py:631  in flush
  queue.py:108                              in join     <-- no timeout

Thread 0x00004bcc  (the app's lifespan thread, under TestClient)
  service/app.py:788        in lifespan
  langfuse_exporter.py:512  in close
  backend.py:639            in close               -> self._client.shutdown()
  langfuse/_client/client.py:2360           in shutdown
  langfuse/_client/resource_manager.py:643  in shutdown
  langfuse/_client/resource_manager.py:631  in flush
  queue.py:108                              in join     <-- no timeout

Thread 0x000060f0  (the main/test thread)
  test_exporter_isolation.py:242 -> :93 in _run_once
  starlette/testclient.py:709 in __exit__ -> :702 wait_shutdown
  concurrent/futures/_base.py:451 in result            <-- no timeout
```

`resource_manager.py:631` is `self._score_ingestion_queue.join()`.
`queue.Queue.join()` takes no timeout: it returns only when `unfinished_tasks`
reaches zero, and only a live consumer's `task_done()` can take it there.

### Why the queue never drains — measured, not reasoned

`LangfuseResourceManager.__new__` returns an instance cached by public key
(`resource_manager.py:137-138`). `shutdown()` (`:639-644`) pauses and joins the
score-ingestion consumer threads but **leaves the instance in `_instances`** —
only the separate `reset()` (`:487-491`) clears that cache.

All three tests in `UnreachableBackendTests` build a real `LangfuseBackend` with
the **same** `public_key="pk-lf-not-a-real-key"`
(`test_exporter_isolation.py:200-214`). The alphabetically first
(`test_a_black_hole_host…`) passes and calls `close()`, killing that key's
consumer. `test_a_slow_host…` then gets the same dead manager back.

Reproduced standalone with a **dead port on both arms**, which is what proves
the slow host is irrelevant to the hang:

```text
A rm id 1988699349280 consumers alive: [True]
A close 0.00s
B rm id 1988699349280 SAME OBJECT: True consumers alive: [False] running flags: [False]
B score queue unfinished: 1
Timeout (0:00:40)!            <-- B flush() never returned
```

The exporter reaches that queue at all because it writes Langfuse **scores**
(contract §7 — `guardrail_passed`, `task_attempts`, `run_succeeded`,
`run_status`), and scores are the one thing the SDK sends through
`_score_ingestion_queue` rather than the OTel span pipeline. A run with no
scores never touches it, which is why single-client probes are fast.

Confirming by removing only the cached instance, again on dead ports:

```text
consumers alive after evict: [True]
B flush 5.62s
B close 0.00s
done
```

### What the exporter got right, and the one place it did not

The exporter's own bounded waits **worked, and are visible in the run log**:
`flush()`'s `marker.done.wait(timeout)` timed out and logged *"the langfuse
exporter did not flush within 5.0s"* twice, and `close()`'s
`thread.join(timeout=10.0)` timed out and logged *"the langfuse export thread
did not stop within 10s"*. Both correct.

What then wedged the process is `close()`'s final loop, which is **not** bounded
despite the docstring on the same method saying *"Idempotent, bounded"*:

```python
# src/brief_crew/observability/langfuse_exporter.py:511-516
for closable in (self._cost_lookup, self._backend):
    try:
        closable.close()          # -> client.shutdown() -> Queue.join(), forever
    except Exception:
        pass
```

### Proposed minimal fix (NOT applied)

`LangfuseBackend.close()` (`backend.py:637-641`) must evict its own key from the
SDK's instance cache after `shutdown()` —
`LangfuseResourceManager._instances.pop(public_key, None)` under that class's
`_lock` — so a later exporter with the same key builds live consumer threads;
**and** `LangfuseExporter.close()` (`langfuse_exporter.py:511-516`) must run
each `closable.close()` under a bounded wait (a watchdog thread with a timeout,
the same shape as the `thread.join(timeout=10.0)` above it) so that no SDK
`Queue.join()` can ever hold the caller.

### Two consequences that are not test-only

* **`atexit`.** The SDK registers `atexit.register(self.shutdown)`
  (`resource_manager.py:279`). A process that exits without a successful
  `LangfuseBackend.close()` runs that unbounded `Queue.join()` at interpreter
  shutdown — so with an unreachable or slow Langfuse and any score queued,
  `serve.exe` cannot exit.
* **A second unbounded wait, independent of the SDK.**
  `self._queue.put(_SHUTDOWN)` at `langfuse_exporter.py:504` is a plain blocking
  `put`, and blocks if the queue is full while the drain thread is wedged.

---

## Part 2 — findings

Ranked by severity. Every row cites `file:line` at the reviewed tree.

| # | Sev | Finding | Where |
| --- | --- | --- | --- |
| 1 | **BLOCKER** | **A credential-shaped string inside an exception message leaves the process under the DEFAULT content policy.** Every `statusMessage` path forwards `details["error"]` raw — calling neither `scrub_text` nor `content_or_description` — and the same text is copied into `trace.output.reason`. Populating `policy.secret_values` changes nothing on these paths. Measured below. This is E3's own question ("even when a tool argument or prompt contains a planted fake key") answered **no**. | `langfuse_exporter.py:847-848`, `:908`, `:921`, `:1211-1214`, `:1258-1259`, `:1300-1302`, `:1594`, `:1597`, `:1656-1659` |
| 2 | **BLOCKER** | `close()` is documented "Idempotent, bounded" and is neither: `closable.close()` → `LangfuseBackend.close()` → SDK `shutdown()` → unbounded `Queue.join()`. The measured hang, and it wedges the app's own lifespan thread, not just a test. | `langfuse_exporter.py:495` (docstring), `:511-516`; `backend.py:637-641` |
| 3 | **BLOCKER** | A second exporter built with the same public key in one process inherits the SDK's shut-down, cached resource manager, so every flush blocks forever. Nothing in `LangfuseBackend.__init__` guards it. | `backend.py:451-491`; SDK `resource_manager.py:137-138`, `:639-644` |
| 4 | **HIGH** | **An interrupted run is reported as a cost-ceiling abort, with a fabricated money figure.** `_terminal_of` treats *any* cancelled frame carrying a non-empty `reason` as the budget stop, but `RunRegistry._fail_interrupted` emits `{"status": "cancelled", "reason": "service_restart"}` for a run orphaned by a process restart. Measured below. | `langfuse_exporter.py:849-863`; `service/registry.py:~2394`, `:84` |
| 5 | **HIGH** | `DATABASE_URL` — a PostgreSQL URI with an embedded password in production — is **not** selected by `credential_values_in_environment`: `is_secret_key("DATABASE_URL")` is False (it normalises to `databaseurl`, matching no suffix). Finding 1 is exactly the path that would carry it, since a `psycopg`/`sqlalchemy` error quotes the DSN. | `content.py:57-80`, `:74`; `events/redaction.py:159-162` |
| 6 | **HIGH** | An unmapped CrewAI event is **dropped before the exporter can see it**, so C3's "never dropped silently" guarantee does not hold end to end. `serializer.py:651` calls `record_unhandled(event)` and returns `()`; `adapter.py:271-273` short-circuits on an empty tuple. `record_unhandled` tallies into a dict that **nothing reads** — no frame, no log line, no metric. Verified below. | `events/serializer.py:645-651`, `:739-750`; `events/adapter.py:271-273` |
| 7 | **HIGH** | `close()`'s `self._queue.put(_SHUTDOWN)` is an unbounded blocking `put`, and blocks before the bounded join below it is ever reached. | `langfuse_exporter.py:504` |
| 8 | **MEDIUM** | The E3 test plants markers only in carriers that are already gated. It emits **no failing frame at all** — `replay.py` has `run_failed`, `model_call_failed` and `tool_call(error=…)` and the test calls none — so finding 1's entire leak surface is unexercised, along with the EVENT-from-unknown-frame path, `METRICS.reason`, and tool `output_preview`/`query`/`notes`. | `test_content_policy.py:44-70`; `replay.py:78`, `:173`, `:233` |
| 9 | **MEDIUM** | `test_event_coverage.py:44-53` ("every declared event is mapped or has a reason") **cannot fail**: `unmapped_reason` returns a truthy fallback for any module absent from `_MODULE_REASONS`, so the `unreasoned` list is empty by construction. A CrewAI upgrade adding a whole new event module is "reasoned about" by a sentence nobody wrote. | `mapping.py:290-293`; `test_event_coverage.py:44-53` |
| 10 | **MEDIUM** | Two real CrewAI 1.15.18 event classes are outside the enumeration entirely — neither mapped nor reasoned. `SkillDownloadStartedEvent` and `SkillDownloadCompletedEvent` are declared in `crewai/skills/events.py`, and `crewai_event_classes()` walks only `crewai.events.types.__path__`. Verified below: 163 of 165. | `mapping.py:254-282`, `:272`, `:256` (docstring) |
| 11 | **MEDIUM** | `http_errors` — the number E2 calls "the one most easily made a lie" — sums exceptions raised out of `_call` and a delta on `transport_failures()`. Against the **real** SDK the first almost never fires (it batches asynchronously and does not raise at the call site), so the count rests entirely on the second, which counts WARNING+ **log records** on two hardcoded logger names. An SDK upgrade that renames a logger silently returns it to zero while the summary still claims a clean export. | `backend.py:391`, `:394-434`; `langfuse_exporter.py:609-627`, `:1667-1677` |
| 12 | **MEDIUM** | `TransportFailureCounter.attach()` adds a handler to **process-global** loggers, so two backends in one process each count the other's failures. | `backend.py:408-412` |
| 13 | **MEDIUM** | The drop-oldest path in `on_frames` evicts a `_FlushMarker` or the `_SHUTDOWN` sentinel, discarding whatever `get_nowait()` returns without inspecting its type. **Measured:** a planted marker was evicted and `marker.done` never set, so a `flush()` caller waits its full timeout and returns False; an evicted sentinel means the drain thread never stops. | `langfuse_exporter.py:447-455` |
| 14 | **MEDIUM** | `_close_out` calls `self._backend.flush()` **on the export thread** (`:956`), as does `_loop`'s flush-marker branch (`:534`). Both are unbounded SDK calls on the one thread every bounded wait in this class depends on. Measured at 5.62 s even on a healthy path — already over `flush()`'s own 5.0 s default. | `langfuse_exporter.py:534`, `:956`; `backend.py:633-635` |
| 15 | **MEDIUM** | `run_metrics["reason"]` is folded onto the run span's metadata unscrubbed and ungated by `capture_content`. The contract's revision now names `run_metrics` in trace metadata (§1), so the **carrier** is sanctioned; what is not is that the free-text `reason` inside it passes neither `scrub_text` nor `policy_details`. | `langfuse_exporter.py:826`, `:907` |
| 16 | **MEDIUM** | `reason` and `decision_reason` sit on `STRUCTURAL_STRING_KEYS`, so free text under those keys passes through verbatim (≤ 256 chars) by default. Shape-scrubbed, so key-safe, but text-leaking. | `content.py:247`, `:266` |
| 17 | LOW | Key-shape matching is **case-sensitive** and needs a ≥ 6-char body, so `GHP_…`, `SK-OR-…` and `AIZA…` survive. All eight contract prefixes are otherwise present, unanchored (an embedded key mid-sentence or inside JSON is caught), plus three extra GitHub variants. | `content.py:42-45` |
| 18 | LOW | Contract §4 says generation `input` is "present, redacted, when `LANGFUSE_CAPTURE_CONTENT=1`". It is never emitted under either policy, because the frame pipeline never records a prompt. Honestly documented at the code; the contract table is the stale half. | `langfuse_exporter.py:1356-1364` |
| 19 | LOW | `secret_values` is snapshotted once at policy construction, so a credential set later in the process is never compared. `_MIN_SECRET_VALUE_CHARS = 12` and `_MAX_SECRET_VALUES = 64` further bound the comparison set. | `policy.py:141`; `content.py:49`, `:54` |
| 20 | LOW | `stats()` iterates `self._finished` (a `deque` the drain thread appends to) and reads `state.latencies` mid-append. Benign under the GIL today; the docstring's "possibly a batch stale" understates it. | `langfuse_exporter.py:462-477`, `:1701` |
| 21 | LOW | `LANGFUSE_FLUSH_INTERVAL_SECONDS` defaults to `0.25`; contract §9 says "≈ 1.0". Deliberate per the DoD revision log (B4, "≤ 0.25 s drain"), so the **contract** is the stale half — worth reconciling so a reader is not left choosing. | `config.py:3567-3568`; `TRACE-CONTRACT.md` §9 |

### Finding 1, measured

Run by V-REVIEW against the real exporter and `RecordingBackend`. Default
policy, `capture_content=False`, with `secret_values` populated, and a
key-shaped placeholder of repeated characters:

```text
capture_content   : False
secret_values set : True
KEY in payload    : True         <-- sk-or-v1-<64 chars>
IDEA in payload   : False        <-- the user's idea IS correctly withheld
  leak in status_message of: run            -> RuntimeError: ... holding sk-or-v1-aaaa...
  leak in status_message of: n1             -> RuntimeError: ... holding sk-or-v1-aaaa...
  leak in status_message of: a task         -> RuntimeError: ... holding sk-or-v1-aaaa...
  leak in status_message of: a role         -> RuntimeError: ... holding sk-or-v1-aaaa...
  leak in status_message of: provider/model -> AuthError: 401 ... sk-or-v1-aaaa...
  leak in status_message of: a tool         -> ToolError: upstream said sk-or-v1-aaaa...
  leak in trace_output.reason
```

Six observations plus the trace output. One node error becomes four because
`_close_scope` (`:1156-1169`) propagates the message to the task and agent
spans.

The upstream half is real content, not a sanitised code: `events/serializer.py`
sets `{"error": self.clip(str(event.error))}` at eight sites — the raw
exception text, clipped only. A provider 401 quotes the key; a database error
quotes the DSN (finding 5).

**One `scrub_text(message, self.policy.secret_values)` at each site in finding 1
closes it.** Three existing tests assert the current verbatim behaviour and must
move in the same commit: `test_terminal_states.py:144`, `test_trace_shape.py:278`,
`test_retry_legibility.py:101`.

### Finding 4, measured

Driving the exporter with exactly the frame `_fail_interrupted` emits:

```text
INTERRUPTED_REASON = 'service_restart'
run span level      : ERROR
run statusMessage   : stopped by the run cost ceiling (service_restart): estimated $0.0000 against a $0.00 ceiling
trace output        : {'status': 'failed', 'reason': 'stopped by the run cost ceiling (service_restart): ...'}
run_status score    : [('run_succeeded', 0), ('run_status', 'failed')]
```

Both Render services carry `autoDeploy: yes`, so every push to `main` restarts
the API and can orphan an in-flight run. Each would appear in Langfuse as a run
that breached a **$0.00** cost ceiling. The discriminator should be
`reason == COST_CEILING_REASON` (`registry.py:97`), not `reason` being truthy —
`cost_ceiling` is a generic registry constant, not a flow identifier, so
comparing against it does not put C1 at risk.

### Finding 6, verified

```python
# src/brief_crew/events/serializer.py:645-651
        # Nothing matched. The sink receives *every* CrewAI event, so this is a
        # real and previously silent discard: ~150 event classes exist and this
        # ladder handles about 30. ...
        self.record_unhandled(event)
        return ()
```

`_event_drafts` returns `()`, and `adapter.py:271-273` returns early on an empty
tuple, so `on_frames` is never called. `grep -rn "unhandled" src/brief_crew/`
returns only the serializer's own three lines plus a docstring reference in
`mapping.py:13` — the tally is written and never read.

So `mapping.py:134`'s EVENT default protects against a new **`FrameKind`** or a
new LLM **stage**, which is strictly narrower than the row's question, and is
currently unreachable in production because `FrameKind` is this repo's own
16-member enum and `test_event_coverage.py:141-146` already asserts every member
has an explicit disposition. `mapping.py:11-15` is admirably honest that *"an
exporter downstream of it cannot see them however it is written"* — the gap is
that nothing pins the layer where the drop actually happens.

### What the concurrency review found clean

Checked specifically, and **correct**:

* **`on_frames` is enqueue-only.** It is called on the capture thread inside
  `with self._capture_lock` (`events/adapter.py:262-264`; the contract is
  restated at `service/registry.py:1472-1475`). The body is `Event.is_set()`,
  two `perf_counter_ns()`, a dataclass build, `Queue.put_nowait`/`get_nowait`,
  and a `deque.append` — no I/O, no SDK call, and no lock the drain thread holds
  for longer than a queue operation (`langfuse_exporter.py:433-461`).
* **No re-entrancy.** The package imports only `brief_crew.events.models` and
  its own modules (`langfuse_exporter.py:80-106`); there is no path from the
  drain thread back into the adapter or its capture lock. `_facts_lock` is taken
  by `begin_run` and `_state_for`, never by `on_frames`.
* **Nothing raises into the caller.** `on_frames`, `begin_run`, `_call`,
  `_absorb` and `_loop` are each total, and `registry._enqueue_frames`
  (`registry.py:3116-3124`) wraps the call in a second try/except.
* **The SDK client is built with a bounded HTTP timeout**, and with `base_url=`
  rather than `host=` — the comment at `backend.py:465-478` records that `host=`
  is silently outranked by `LANGFUSE_BASE_URL` in the environment, which would
  have sent these tests' spans to the real project. A genuine trap, correctly
  avoided.
* **D6's discriminator matches the app.** `RunRegistry._execute`'s `HookAborted`
  branch (`registry.py:2737-2755`) sets `reason`/`cost_usd`/`ceiling_usd` only
  for a budget stop and nothing for an operator cancel — exactly what
  `_terminal_of` reads. Finding 4 is that a *third* producer of `reason` exists.
* **C1's property is TRUE at HEAD**, verified over a superset of identifiers
  (see §C1).

---

## Part 3 — DoD row → test mapping

| Row | Pinned by | Verdict |
| --- | --- | --- |
| C1 | `tests/observability/test_no_flow_identifiers.py` (6) | **PARTIALLY PINNED** |
| C3 | `tests/observability/test_event_coverage.py` (10) | **PARTIALLY PINNED** |
| D4 | `tests/observability/test_retry_legibility.py` (9) | **PINNED** |
| D6 | `tests/observability/test_terminal_states.py` (13) | **PINNED** for the budget stop; finding 4's false positive **NOT PINNED** |
| E2 | `tests/observability/test_exporter_isolation.py` (3 conditions) | **NOT PINNED — the module does not complete** |
| E3 | `tests/observability/test_content_policy.py` (13) | **PARTIALLY PINNED** — and finding 1 is a measured failure of the row |

### §C1 — PARTIALLY PINNED

**The property holds at HEAD.** Verified independently over a superset of the
test's own extractors: 9 agent keys and 9 role sentences
(`crews/*/config/agents.yaml`), 12 task keys, 4 tool names and 11 tool classes,
7 crew classes, the 4 built-in skill packs, **plus** 2 workflow ids, 2 flow
class names, 18 flow method names, `BUILDER_AGENT_LIBRARY` (6),
`BUILDER_CREW_LIBRARY` (6), `BUILDER_ACTION_REFS` (11) and 15 builder platform
tool names — case-insensitively over all 7 files in the package. **Zero real
leaks.** Every hit is a coincidental English substring: `persist` inside
"frame-persistence" (`langfuse_exporter.py:19`), `scope` inside `_NodeScope`,
`report` inside "self-report", `exa` inside "exactly". The credential prefixes
at `content.py:43` are contract §8's, not tool names; `crew_events`
(`mapping.py:204`) is a CrewAI module name.

The positive mechanism is real code, not a comment: `langfuse_exporter.py:978-979`
reads `details.get("agent_role")` / `details.get("task_name")`, and `:799` takes
tags from `facts.workflow_id`, copied off the run record rather than mapped.

**Where the test falls short of the row's words:**

1. **"flow name" is in the row and in no extractor.** Nothing reads
   `service/graph.py:26` (`BRIEF_WORKFLOW_ID = "brief-flow"`) or `:28`
   (`VALIDATOR_WORKFLOW_ID = "idea-validator"`), nor `ValidatorFlow`/`BriefFlow`,
   nor the flow method names that **are** the node ids. `if frame.node_id ==
   "confirm_scope"` would pass all six tests. This was not hypothetical:
   contract §1 **used to** define trace tags as `[flow_kind, …]` with
   `flow_kind ∈ {validator, brief, builder}` — a written invitation to hardcode
   that table. The exporter declined it, and the contract's revision during this
   review now reads `[workflow_id, "gates:" + gates_mode, "mode:" + run mode]`,
   which removes the invitation. **The gap in the test is unchanged**: nothing
   pins the declining, and the row's words "flow name" still have no extractor
   behind them.
2. **Builder library identities are unchecked** —
   `BUILDER_AGENT_LIBRARY` (`builder/runtime.py:266`),
   `BUILDER_CREW_LIBRARY` (`:278`) and the 15 platform tool names in
   `builder/tools.py`.
3. **The skill-pack half can silently skip.** `@unittest.skipUnless(SKILLS.exists(), …)`
   (`:126`), and the control test (`:130-141`) sets floors for yaml, tools and
   crews but **no floor for skills** — the one extractor that can vanish is the
   one the control does not cover.
4. **The positive half is a text search** (`:143-160`): five expressions must
   appear anywhere in `langfuse_exporter.py`; a comment would satisfy it.
5. `_package_sources` globs `PACKAGE.glob("*.py")`, so it *does* cover all seven
   files. It does not cover `scripts/observability/`, where
   `measure_overhead.py:101` defaults `--workflow-id` to `idea-validator` —
   defensible (offline tooling, and the DoD's evidence clause scopes the grep to
   `src/brief_crew/observability/**`), but a reader of "the instrumentation
   path" should be told.

### §C3 — PARTIALLY PINNED, and the second half is answered at the wrong layer

The mapping structures are real and complete for what they cover:
`FRAME_DISPOSITIONS` (`mapping.py:73-110`) has exactly the 16 `FrameKind`
members with no gaps; `FRAME_PIPELINE_EVENTS` (`:146-183`) names 36 CrewAI
classes, all of which are real `isinstance` branches in
`events/serializer.py:424-641`; `_MODULE_REASONS` (`:190-251`) carries 19
per-module reasons; `crewai_event_classes()` (`:254-282`) walks the package
live. Measured at CrewAI 1.15.18: 163 `BaseEvent` subclasses under
`crewai.events.types`, 36 mapped + 127 reasoned = 163.

Departures, in order of weight:

1. **The "not dropped" half is proven one layer above the layer that drops** —
   finding 6. `UnknownFrameTests` (`:93-139`) builds hand-made `FrameData` and
   forces an `_UnknownKind` on via `object.__setattr__` (`:112`); no CrewAI
   event, no serializer and no adapter are in the path. The row's wording ("an
   event type *the exporter* has never seen") makes that defensible on the
   letter, but the operator's version of the question — *CrewAI ships a new
   event type; do I see it in Langfuse?* — is answered **no**.
2. **`test_every_declared_event_is_mapped_or_has_a_reason` cannot fail**
   (finding 9).
3. **Two classes are outside the enumeration** (finding 10) — verified:
   `crewai/skills/events.py` declares `SkillEvent`,
   `SkillDownloadStartedEvent`, `SkillDownloadCompletedEvent`.
4. **Reasons are per-module**, so a new class in an existing module inherits an
   unrelated sentence (`mapping.py:217-221`).
5. `test_the_two_tables_partition_the_declared_classes` (`:55-66`) is
   near-tautological: `unmapped_with_reason()` is *defined* as
   `classes − FRAME_PIPELINE_EVENTS` (`:309-313`).
6. `test_every_handled_name_is_named_by_the_frame_pipeline` (`:73-85`) is a
   substring search over `serializer.py`'s text, not its `isinstance` ladder — a
   name in an import list satisfies it. Sound today by luck.
7. **Four of the 19 "deliberate" reasons say in their own words that they are
   gaps, not decisions**: `hook_events` *"recorded as a gap rather than a
   decision"* (`:213-216`), `knowledge_events` *"The largest single gap on this
   list"* (`:217-221`), `mcp_events` *"A real gap"* (`:227-232`),
   `reasoning_events` *"not framed today"* (`:240-243`). Honest, and worth the
   verifier's eye against the row's word "deliberately".

### §D4 — PINNED

`test_retry_legibility.py` covers both mechanisms the row names.
`GuardrailRetryTests` asserts two generations under one task span with `attempt`
`[1, 2]` (`:51-64`), the guardrail verdict as a **score on the task** with
values `[0, 1]` (`:66-71`), `task_attempts == 2` (`:73-76`), and that no
observation is left open (`:78-79`). `TransportRetryTests` asserts the failed
call is a generation at `level=ERROR` carrying the exception class, followed by
a successful one, ordered, with usage on the second only and `attempt` `[1, 2]`
(`:97-118`). Both drive the real `FrameData` the pipeline produces, via
`replay.py`, rather than a lookalike.

Worth naming, not a failure: the retry index is derived from the frame order the
recorder builds, so it pins the exporter's arithmetic, not that CrewAI actually
emits that order.

### §D6 — PINNED, with one hole beside it

`BudgetStopTests` asserts the trace ends `failed` and not `cancelled` (`:64-67`),
the reason names the ceiling and the figure (`:68-74`), the run span is `ERROR`
(`:75-77`), the `run_status` score says `failed` (`:78-82`), and nothing is left
without an end time (`:83-104`). `OperatorCancelTests` pins the other side — a
cancel with no reason stays `cancelled` (`:116-129`). `BUDGET_STOP` (`:31-37`)
uses `"reason": "cost_ceiling"`, matching `registry.py:97`.

**Not pinned:** no test feeds a cancelled frame carrying a reason that is *not*
the ceiling, which is why finding 4 survived a green module. One test asserting
`reason="service_restart"` stays `cancelled` closes it.

### §E2 — NOT PINNED

The three conditions are all written and the intent is right: the module
compares status, frame count and result against a control run (`_RunOutcome`,
`:64-82`) and asserts the failure is **counted** rather than merely survived.
The keyless condition (`MissingKeysTests`) passes.

The harness is sound, which is worth recording because it is the thing most
likely to be certifying nothing: `create_app` imports `build_exporter` from the
package **inside** the function (`service/app.py:772`), so `_run_once`'s
`patch("brief_crew.observability.build_exporter", …)` really does put the test's
exporter in the service's path — proved by the black-hole test's
`frames_enqueued > 20` assertion passing rather than reading zero.

It does not currently pin the row, for the reason in Part 1: the two transport
conditions cannot both run in one process, so the module never reports. Until
that is fixed the row is **NOT RUN**, not PASS.

Two notes for whoever fixes it:

* `test_the_summary_line_carries_the_failure_count` is the sharpest test in the
  package — it asserts the summary is written *after* the final flush by reading
  the line, and asserts `http_errors=0 ` is absent. It also inherits finding 11:
  it proves the ordering, not that the count came from a transport result.
* `ExporterSurfaceTests` (`:287-333`) runs without the SDK and pins real things:
  the no-op surface, double `close()`, a backend that raises on every call never
  reaching the caller, and drop-oldest at capacity 2.

### §E3 — PARTIALLY PINNED, and finding 1 is a measured failure of the row

**What is correct.** `content.py` implements §8's described-value half properly.
All eight contract prefixes are present (`content.py:42-45`), unanchored, so an
embedded key inside a sentence or a JSON blob is caught; three extra GitHub
variants are added, which "at least" permits. `scrub_text` bounds at
`MAX_MESSAGE_LENGTH = 4096`, matching `SerializerLimits.max_string`
(`events/serializer.py:246`) as §8 requires. `credential_values_in_environment`
selects by `events.redaction.is_secret_key` rather than carrying its own name
list, which is the right call. `policy_details` (`content.py:242-352`) **fails
closed** — an allowlist, so a string under an unrecognised key becomes
`{chars, sha256}` rather than passing through.

Under the default policy the following were all confirmed **absent** from the
payload: trace input (the user's idea), node/agent/task span outputs, the LLM
`utterance` text, tool `args`, `input_preview`, `output_preview`, `query`,
`notes`, the verdict fold, and free text inside an EVENT's details.

**What fails.** Finding 1: every `statusMessage` carrier and
`trace.output.reason` forward raw error text, ungated and unscrubbed, and
finding 5: `DATABASE_URL` is not in the comparison set. Plus findings 15, 16,
17, 18 and 19.

**What the test misses.** The payload *search* is genuinely deep — `_exercise`
(`:71-76`) walks `dataclasses.asdict` over every observation including the whole
parent chain, plus scores and trace output. The gap is the **planting**: the
test emits six frame shapes and **not one of them fails**, so the largest leak
surface is never touched (finding 8). Two weaker assertions:
`test_every_prefix_the_contract_names_is_blanked` (`:126-130`) tests only
lowercase, mid-sentence, 20-char bodies, so it would not catch finding 17; and
`test_the_environment_scan_selects_by_the_rule_already_in_force` (`:136-146`)
asserts only that a tuple of strings comes back, so finding 5 is invisible to
it. The end-to-end path never exercises `secret_values` at all, because
`replay.py:281-288` leaves it `()`.

---

## Part 4 — scope note

The brief for this pass named C1, C3, D4, D6, E2, E3. The DoD also assigns
**F2** (the committed tests are only those the rows require) and **F3** (no
committed artifact contains a credential value) to V-REVIEW. Neither was
reviewed here. `evidence/tests/` currently holds `secret-scan.txt` (F3's
artifact) and this file; **F2's `evidence/tests/INDEX.md` does not exist yet.**
