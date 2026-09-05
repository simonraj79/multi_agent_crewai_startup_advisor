# Test index — DoD row F2

> **F2:** *Are the committed tests only those the rows above require?*
> Verifier: V-REVIEW, who built none of this code and edited none of it.
> Written 2026-09-06 (second pass), against the **uncommitted** working tree at
> `git rev-parse HEAD` = `b65bd654003bcbc92e8ff643d245cf173d92dc0e`. The md5 sums
> that pin the code under test are in each row's `.txt` beside its output.

Measured, not read off the file names: every module below was run alone, and the
whole package together, on 2026-09-06 — **141 tests, 0 failures, 22.9 s**:

```text
$ ./.venv/Scripts/python.exe -m unittest discover -s tests/observability -t .
Ran 141 tests in 22.959s
OK
```

## 1. The rows whose Evidence column names a committed test

Six rows, and exactly six, say the words *"a committed test"* in
`DEFINITION-OF-DONE.md` §4: **C1, C3, D4, D6, E2, E3**. Each has one module and
no module serves two of them.

| Test file | Tests | Row | Serves it how |
| --- | ---: | --- | --- |
| `tests/observability/test_no_flow_identifiers.py` | 6 | **C1** | greps the seven files of `src/brief_crew/observability/` for every agent key, role sentence, task key, tool name, tool class, crew class and built-in skill pack in the repository, asserts zero hits, and has a control asserting the extractors found something to check |
| `tests/observability/test_event_coverage.py` | 16 | **C3** | enumerates the installed CrewAI's `BaseEvent` subclasses and asserts the two tables partition them; feeds the exporter an unknown frame kind and an unknown stage and asserts each becomes an EVENT; asserts the serializer's unhandled tally reaches the trace |
| `tests/observability/test_retry_legibility.py` | 9 | **D4** | replays a guardrail retry and a transport retry as real `FrameData` and asserts two generations under one task with the attempt index, the guardrail score, and the failed-then-successful order |
| `tests/observability/test_terminal_states.py` | 20 | **D6** | drives the cost-ceiling abort and asserts `failed` with the ceiling and the figure named; plus the rest of contract §6 (completed, failed, operator cancel, service restart, gate pause) and the D3 rule that nothing is left without an end time |
| `tests/observability/test_exporter_isolation.py` | 16 | **E2** | one test per condition — black-hole port, slow host, missing keys — each against a control run, asserting the run is unchanged AND the failure is counted; plus the `/readyz` surface and the no-op exporter |
| `tests/observability/test_content_policy.py` | 23 | **E3** | plants a fake key and a distinctive sentence in every carrier, on both policies, and searches the whole captured payload; plus the failure-path and `DATABASE_URL` halves added after the first pass measured a leak on them |

**No row in that set is without a test, and no test in that set serves no row.**

## 2. The rest of the package — supporting, not required

These two modules pin the trace CONTRACT rather than a row whose evidence is a
test. Every row they name (`A1`, `A2`/`D5`, `A3`, `B1`, `B2`, `B5`, `D2`, `D3`)
asks in its own Evidence column for a **proof run**: session JSON, trace JSON, a
screenshot. So they are not "tests the rows require" in F2's literal sense, and
they are not gold-plating either: they are the unit-level pin of the shape the
proof runs are then read against, and three of them exist because a live smoke
run found the contract unmet (§7 revision log, 2026-09-05).

| Test file | Tests | Rows it supports | V-REVIEW's call |
| --- | ---: | --- | --- |
| `tests/observability/test_trace_shape.py` | 38 | A1, A2/D5, A3, B1, B2, B5, D2, and contract §1–§5 | **Keep.** It is the only place the run span's rootness, the deterministic trace id, the §3 metadata on every observation, `null_fields` (Amendment A1), cross-run isolation and re-delivery idempotence are asserted at all. A proof run can show one trace is right; this shows the shape cannot silently change. |
| `tests/observability/test_prompt_fingerprint.py` | 13 | B5 | **Keep, and it is the newest.** B5's fingerprint moved into the frame serializer on 2026-09-05 (§7 revision log), so the join between two modules is new code with no proof run behind it yet. It also asserts the negative — the prompt text never reaches a frame — which is an E3 property nothing else covers. |

| Support file | Role |
| --- | --- |
| `tests/observability/__init__.py` | makes `unittest discover` walk the directory at all — [gotchas](../../../gotchas-and-insights.md) 20, the trap that once held this repository's Python count at 65 |
| `tests/observability/replay.py` | the shared frame builder. Named so the default `test*.py` pattern walks past it; builds real `FrameData`, not a lookalike |

## 3. Observability tests OUTSIDE `tests/observability/`

| File | State | Row | Note |
| --- | --- | --- | --- |
| `tests/events/test_trace_fixture.py` | **modified** (+19/−1) | B5 | the one change is `messages=[…]` on the fixture's `LLMCallStartedEvent`, so the committed record of what the real ladder produces carries what production carries and `prompt_digest` is exercised by it. A fixture correction, not a new test. |
| `frontend/tests/fixtures/serializerFrames.ndjson` | **modified** (1 line) | B5 | the regenerated fixture the change above produces. Not a test. |
| `tests/__init__.py` | **modified** | E2 (safety) | sets `LANGFUSE_EXPORT_ENABLED=0` by **assignment**, not `setdefault` — the only assignment in that file, and it is argued at the site: a developer with a real `.env` has both keys, the knob defaults ON when both are present, and `setdefault` would leave ~2,500 tests posting live traces to a real project over the network. |
| `tests/service/test_observability.py` | **unchanged, pre-existing** (`e91f4df`) | — | F20/F21/F30/F31, the older event-and-metrics work. Not part of this programme and not counted against F2. |

Nothing else under `tests/` mentions `langfuse` or `observability`
(`grep -rln "observability\|langfuse\|LANGFUSE" tests/ --include=*.py`), and
nothing under `frontend/` mentions Langfuse at all.

## 4. Rows with NO test, and why that is correct

| Row | Evidence it asks for instead |
| --- | --- |
| A1, A3, B3, B5, B6, C2, D1, D2, D3 | a real proof run: trace/session JSON and a console screenshot (V-PROOF) |
| A2/D5, B1, B2, B4, E1, E4, E5 | counting artifacts: `membership-check.txt`, `per-agent.md`, `per-task.md`, `durations.md`, `RECONCILIATION.md`, `evidence/perf/overhead.md` (V-RECON) |
| F1, F4 | `audit/openrouter-forwarding.md` §1 and `evidence/proof/RUNS.md` (ORCH) |
| F3 | `evidence/tests/secret-scan.txt` — a scanner run, not a test |

**F2's verdict: PASS.** Six rows require a test; six modules serve them, one
each. Two further modules pin the contract the proof rows are read against, and
both are named above so the orchestrator can rule on them rather than discover
them. There is no test in this package that serves no row.

## 5. Files V-REVIEW added to `evidence/tests/` — evidence, NOT tests

None of these is under `tests/`, none is collected by `unittest discover`, and
none should ever be committed as a test. They are the verifier's own
instruments, kept so a later reader can re-run the measurement rather than
believe the transcript.

| File | What it does |
| --- | --- |
| `c1_identifier_grep.py` | V-REVIEW's own, wider C1 extractor: adds the registered workflow ids, the flow classes, every flow **method** name (which are the node ids), `BUILDER_AGENT_LIBRARY`, `BUILDER_CREW_LIBRARY`, `BUILDER_ACTION_REFS` and the 11 builder platform tool ids — none of which the committed test extracts — and greps the two new serializer functions as well as the package. 134 identifiers, 31 hits, all coincidental English. |
| `c3_partition_check.py` | enumerates CrewAI's events **without** using the exporter's own walk, adds a text sweep of the whole installed package for a third declaring module, and checks the 36 mapped names against `serializer.py`'s `isinstance` ladder through the AST rather than by substring. |
| `e3_planted_key_probe.py` | the first pass's measured leak, repeated and widened: a fake `sk-or-v1-` key and a fake `postgresql://…` DSN planted in every carrier, both policies, three terminals, searched over the whole payload. |
| `e3_leak_locator.py` | names the JSON **path** of every occurrence with the parent chain excluded, so one leaking field is not reported once per descendant. |

## 6. F3 — every token-shaped WARN hit, examined

The scan
(`./.venv/Scripts/python.exe scripts/observability/secret_scan.py --paths docs/observability scripts/observability src/brief_crew/observability tests/observability --diff --out …`)
answers **PASS: 0 actual credential values**, comparing against the 11
credential variables this process holds (names printed, values never).

It was run **twice**, and the second run is the one in `secret-scan.txt`,
because a proof run (`evidence/proof/capture-on/`) and this pass's own evidence
files landed between them:

| run | text files | prefix warnings | token-shaped | actual values |
| --- | ---: | ---: | ---: | ---: |
| 16:37:10Z | 298 | 1,059 | 23 | **0** |
| 16:45:07Z | 385 | 3,179 | 75 | **0** |
| 16:45:55Z (recorded) | 386 | 7,422 | 75 | **0** |

The **prefix** column is not a measure of anything and the third run shows why:
`secret-scan.txt` is written INTO a scanned path, so each run scans the previous
run's own list of prefixes and the bare-prefix count compounds. The two columns
that mean something — token-shaped, and actual values — did not move.

V-REVIEW examined **all 75** token-shaped hits. Every one is a placeholder or a
false positive, in four families:

* **The two the brief names, confirmed.**
  `evidence/proof/builder-toolfail/inject.md:249` is `fc-` followed by **32
  zeros** — the deliberately-wrong key that proof run injects. `REVIEW.md:90`
  (and now `INDEX.md` itself) quotes `pk-lf-not-a-real-key`, the public key
  three tests share and the reason the SDK's resource-manager cache wedged them.
* **52 in `evidence/proof/capture-on/`** (`app-frames.ndjson`, `frames.ndjson`,
  `app-run.json`, `request.json`) — `sk-or-<67 chars>`, plus one at 16 and one
  at 13. Every one is `sk-or-v1-` followed by **zeros**, inside the marker
  sentence that proof run plants: *"…our staging key is sk-or-v1-000…"*. They
  are in the APP's own frame log, which is the point of that run — a pasted key
  does reach a frame, and the exporter's shape scrubber is what stops it
  reaching Langfuse.
* **Ten that are not credentials at all** —
  `evidence/proof/backend-8000.log:7527,7554` and
  `evidence/proof/validator-live/{app-frames,frames}.ndjson:141–144`, reported
  as `fc-<17 chars>`. Every one is the **middle of a UUID**:
  `"agent_id":"338eb374-d34e-4bfc-…"` — the scanner's `fc-` pattern matches
  inside `4bfc-`.
* **Eleven test-file placeholders**, all English words after the prefix:
  `pk-lf-`/`sk-lf-` in `test_exporter_isolation.py` (6) and
  `test_trace_shape.py` (2), and `test_content_policy.py:43`'s `sk-or-v1-` plus
  64 zeros.

`E3.txt` carries none, deliberately: this pass's own probe builds its planted
key by concatenation and the transcript masks the literal, so the scanner has
nothing to warn about in it.

One scanner note, LOW and worth a line in `FOLLOW-UPS`: because `fc-` is only
two characters before the `{6,}` body, **every UUID containing `fc-` is a
token-shaped hit**. A real Firecrawl key would still be caught by the value
comparison, but the shape channel's precision degrades as the evidence tree
grows — it went from 23 hits to 75 in eight minutes — and the next reader has to
re-clear them all. Anchoring `fc-` on a word boundary would fix it.
