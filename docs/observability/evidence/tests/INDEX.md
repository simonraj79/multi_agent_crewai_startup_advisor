# Test index — DoD row F2

> **F2:** *Are the committed tests only those the rows above require?*
> Verifier: V-REVIEW, who built none of this code and edited none of it.
> Final version, 2026-09-06, at **`58a1c0b`** — the third and last commit this
> review measured (`e68dac4` → `7417270` → `ad6a696` → `58a1c0b`). The code tree
> is clean: `git diff HEAD -- src/ tests/` is empty. See
> [`VERDICTS.md`](VERDICTS.md) for the provenance and the CRLF caveat on the md5
> sums each row's `.txt` carries.

Measured, not read off the file names: every module below was run alone and the
whole package together, on 2026-09-06 at `58a1c0b`:

```text
$ ./.venv/Scripts/python.exe -m unittest discover -s tests/observability -t .
Ran 181 tests in 20.899s
OK
```

**The package has grown 141 → 151 → 181 across the three commits this review
measured, and every one of those 40 tests pins something a V-REVIEW pass
measured or a builder audit found — not new surface.** That is the F2 question
asked the other way round, and it is worth stating plainly because "the suite
grew 28 %" is otherwise the kind of number that reads as gold-plating:

| commit | module | Δ | what the new tests pin |
| --- | --- | ---: | --- |
| `ad6a696` | `test_no_flow_identifiers` | +4 | the three identifier extractors this review found missing, and a control that plants a node id and proves the search would find it |
| `ad6a696` | `test_terminal_states` | +5 | C3's unhandled tally on every terminal the registry writes, not only the flow's own |
| `ad6a696` | `test_content_policy` | +1 | the metrics snapshot this review measured leaking a planted key |
| `58a1c0b` | `test_content_policy` | +9 | identity scrubbed by value only, the `fc-`-only boundary, and that a run id containing `fc-` survives intact |
| `58a1c0b` | `test_terminal_states` | +10 | the exception class reaching every error observation, and the exporter's own tally when no metrics frame arrived |
| `58a1c0b` | `test_trace_shape` | +11 | the deferred billed-cost resolution, and that a generation held for its price is never marked failed by a failed run's sweep |

## 1. The rows whose Evidence column names a committed test

Six rows, and exactly six, say the words *"a committed test"* in
`DEFINITION-OF-DONE.md` §4: **C1, C3, D4, D6, E2, E3**. Each has one module and
no module serves two of them.

| Test file | Tests | Row | Serves it how |
| --- | ---: | --- | --- |
| `test_no_flow_identifiers.py` | **10** | **C1** | greps the seven files of `src/brief_crew/observability/` for every agent key, role sentence, task key, tool name, tool class, crew class and built-in skill pack, and — since `ad6a696` — every flow METHOD name (which are the node ids), both registered workflow ids and the builder agent/crew/action/tool registries, filtered by `_is_distinctive` to identifiers worth searching, with a control that plants a node id and proves the search would find it |
| `test_event_coverage.py` | 16 | **C3** | enumerates the installed CrewAI's `BaseEvent` subclasses and asserts the two tables partition them; feeds the exporter an unknown frame kind and an unknown stage and asserts each becomes an EVENT; asserts the serializer's unhandled tally reaches the trace |
| `test_retry_legibility.py` | 9 | **D4** | replays a guardrail retry and a transport retry as real `FrameData` and asserts two generations under one task with the attempt index, the guardrail score, and the failed-then-successful order |
| `test_terminal_states.py` | **35** | **D6** | drives the cost-ceiling abort and asserts `failed` with the ceiling and the figure named; plus the rest of contract §6 (completed, failed, operator cancel, service restart, gate pause), the D3 rule that nothing is left without an end time, the tally on every terminal the registry writes, the exporter's own fallback tally, and a builder agent failure naming its exception class on all four observations |
| `test_exporter_isolation.py` | 16 | **E2** | one test per condition — black-hole port, slow host, missing keys — each against a control run, asserting the run is unchanged AND the failure is counted; plus the `/readyz` surface and the no-op exporter |
| `test_content_policy.py` | **33** | **E3** | plants a fake key and a distinctive sentence in every carrier, on both policies, and searches the whole captured payload; plus the failure-path, `DATABASE_URL`, metrics-snapshot and identity-field halves, each added after a V-REVIEW pass or a builder audit measured a leak on it |

**No row in that set is without a test, and no test in that set serves no row.**

## 2. The rest of the package — supporting, not required

These two modules pin the trace CONTRACT rather than a row whose evidence is a
test. Every row they name asks in its own Evidence column for a **proof run**:
session JSON, trace JSON, a screenshot. So they are not "tests the rows require"
in F2's literal sense, and they are not gold-plating either: they are the
unit-level pin of the shape the proof runs are then read against, and several
exist because a live smoke run found the contract unmet (§7 revision log).

| Test file | Tests | Class → row |
| --- | ---: | --- |
| `test_trace_shape.py` | **49** | `TraceIdentityTests`, `TraceFieldsTests` → A1, A3, contract §1 · `HierarchyTests` → contract §2/§3 and Amendment A1's `null_fields` · `GenerationTests`, `BilledCostResolutionTests` → B1, B2, B5, E5, contract §4 · `ToolTests` → D2, contract §5 · `ConcurrencyTests` → A2/D5 · `RedeliveryTests` → contract §1's idempotence · `FoldedFrameTests` → the FOLD disposition · `RootSpanTests`, `RootSpanThroughTheBackendTests` → the §7 revision that made the run span a real root · `ErrorClassTests` → B3/D1 |
| `test_prompt_fingerprint.py` | 13 | `PromptDigestTests`, `BeforeFrameTests`, `GenerationMetadataTests` → **B5**, and the negative half (the prompt text never reaches a frame) is an **E3** property nothing else covers |

**Every class in both modules maps to a row.** There is no test in this package
that serves no row — checked class by class at `58a1c0b`, not by reading the
file names.

| Support file | Role |
| --- | --- |
| `__init__.py` | makes `unittest discover` walk the directory at all — [gotchas](../../../gotchas-and-insights.md) 20, the trap that once held this repository's Python count at 65 |
| `replay.py` | the shared frame builder. Named so the default `test*.py` pattern walks past it; builds real `FrameData`, not a lookalike |

## 3. Observability tests OUTSIDE `tests/observability/`

| File | State | Row | Note |
| --- | --- | --- | --- |
| `tests/events/test_trace_fixture.py` | modified | B5 | `messages=[…]` on the fixture's `LLMCallStartedEvent`, so the committed record of what the real ladder produces carries what production carries. A fixture correction, not a new test. |
| `frontend/tests/fixtures/serializerFrames.ndjson` | modified | B5 | the regenerated fixture that change produces. Not a test. |
| `tests/__init__.py` | modified | E2 (safety) | sets `LANGFUSE_EXPORT_ENABLED=0` by **assignment**, not `setdefault`, argued at the site: a developer with a real `.env` has both keys, the knob defaults ON when both are present, and `setdefault` would leave the whole suite posting live traces to a real project. |
| `tests/perf/__init__.py` | modified at `58a1c0b` | E2/E4 (safety) | sets `OTEL_SDK_DISABLED` at import so the perf tests own their OTel state rather than inheriting whatever ran before them. |
| `tests/service/test_observability.py` | unchanged, pre-existing (`e91f4df`) | — | F20/F21/F30/F31, the older event-and-metrics work. Not part of this programme and not counted against F2. |

Nothing else under `tests/` mentions `langfuse` or `observability`, and nothing
under `frontend/` mentions Langfuse at all.

## 4. Rows with NO test, and why that is correct

| Row | Evidence it asks for instead |
| --- | --- |
| A1, A3, B3, B5, B6, C2, D1, D2, D3 | a real proof run: trace/session JSON and a console screenshot (V-PROOF) |
| A2/D5, B1, B2, B4, E1, E4, E5 | counting artifacts: `membership-check.txt`, `per-agent.md`, `per-task.md`, `durations.md`, `RECONCILIATION.md`, `evidence/perf/overhead.md` (V-RECON) |
| F1, F4 | `audit/openrouter-forwarding.md` §1 and `evidence/proof/RUNS.md` (ORCH) |
| F3 | `evidence/tests/secret-scan.txt` — a scanner run, not a test |

**F2's verdict: PASS.** Six rows require a test; six modules serve them, one
each. Two further modules pin the contract the proof rows are read against, and
every class in them maps to a named row. No test serves no row; no row that
requires a test is without one.

## 5. Files V-REVIEW added to `evidence/tests/` — evidence, NOT tests

None is under `tests/`, none is collected by `unittest discover`, and none
should ever be committed as a test. All four have run **unedited** across all
three commits — `ad6a696` deliberately kept `_unhandled_report` as an alias of
the now-public `unhandled_report()` so that `c1_identifier_grep.py` would keep
working, and said so at the site, which is the right instinct about a verifier's
artifact.

| File | What it does |
| --- | --- |
| `c1_identifier_grep.py` | V-REVIEW's own, wider C1 extractor: 134 identifiers including the registered workflow ids, both flow classes, every flow **method** name, the builder libraries and action refs, and the 11 platform tool ids, grepped over the package **and** the new serializer functions. 33 hits at `58a1c0b`, every one a coincidental English word. |
| `c3_partition_check.py` | enumerates CrewAI's events **without** the exporter's own walk, sweeps the whole installed package's text for a third declaring module, and checks the 36 mapped names against `serializer.py`'s `isinstance` ladder by AST. |
| `e3_planted_key_probe.py` | a fake `sk-or-v1-` key and a fake DSN planted in every carrier — including `gate-<key>`, an id an author controls — both policies, three terminals, searched over the whole payload. |
| `e3_leak_locator.py` | names the JSON **path** of every occurrence with the parent chain excluded, so one leaking field is not reported once per descendant. |

## 6. F3 — the regenerated scan, and what the remaining WARNs are

Regenerated at `58a1c0b` with the command the DoD names:

```text
$ ./.venv/Scripts/python.exe scripts/observability/secret_scan.py \
    --paths docs/observability scripts/observability src/brief_crew/observability tests/observability \
    --diff --out docs/observability/evidence/tests/secret-scan.txt

FAIL - actual credential values found: 0
WARN - credential-shaped prefixes:     8125 (of which token-shaped: 65)
VERDICT: PASS
```

**FAIL = 0** is the number the row turns on, measured against the 11 credential
variables this process holds (names printed, values never).

**The 8,125 WARNs in one line:** 8,006 are *bare prefixes* — a prefix with
nothing after it, i.e. the scan patterns written out as prose in
`DEFINITION-OF-DONE.md`, `TRACE-CONTRACT.md`, this file and the scanner's own
source — 54 are short tails, and 65 are token-shaped; **7,013 of the 8,125 come
from the `--diff` channel**, which at scan time is dominated by the uncommitted
rewrite of this very report, and a further ~929 from *older* `secret-scan*.txt`
outputs committed under `evidence/smoke-live/` and `evidence/proof/` that predate
the inert rendering. Measured, not reasoned: the same scan **without** `--diff`
answers **1,112 WARN / 65 token-shaped / FAIL 0**.

The self-inflation the orchestrator names is fixed and I confirmed the fix
holds: prefixes are now rendered with the last character bracketed
(`pk-lf[-]`, `ghp[_]`), so a report cannot match itself, and **three consecutive
scans returned the identical 8,125 / 65** where the previous format went
1,059 → 3,179 → 7,422 in eight minutes. What remains is the *older* reports and
the diff of this one, neither of which the rendering change can reach
retroactively.

**All 65 token-shaped hits, examined:**

| where | n | what it is |
| --- | ---: | --- |
| `evidence/proof/capture-on/{frames,app-frames}.ndjson`, `app-run.json`, `request.json` | 51 | the capture-on proof run's planted marker sentence, *"…our staging key is `sk-or-v1-` + zeros"* |
| `tests/observability/test_exporter_isolation.py` | 8 | `pk-lf-`/`sk-lf-` placeholders that are English words after the prefix |
| `tests/observability/test_trace_shape.py` | 2 | the same |
| `tests/observability/test_content_policy.py` | 1 | `PLANTED_KEY` — `sk-or-v1-` plus 64 zeros |
| `evidence/tests/REVIEW.md`, `INDEX.md` | 2 | `pk-lf-not-a-real-key` quoted in prose — the two the brief names, confirmed |
| `evidence/proof/builder-toolfail/inject.md` | 1 | `fc-` plus 32 zeros, the deliberately-wrong key that run injects |

**The ten UUID false positives this review reported at `7417270` are gone.**
They were `fc-` matching inside `…-4bfc-…` in an `agent_id`; the boundary added
at `58a1c0b` removes them, which is why the token-shaped count fell 75 → 65
while the evidence tree grew.

### The scanner's self-test

New at `58a1c0b`, and it is the right kind of test — fabricated strings only, no
`.env` read, and it checks the rendering can't re-match itself:

```text
$ ./.venv/Scripts/python.exe scripts/observability/secret_scan.py --self-test
secret_scan self-test - fabricated strings only, no .env read
============================================================
  [ok ] the run id that was damaged      shape=0 expected=no  value=0
  [ok ] the same id as a trace id        shape=0 expected=no  value=0
  [ok ] a fabricated Firecrawl key       shape=1 expected=yes value=0
  [ok ] a fabricated OpenRouter key      shape=1 expected=yes value=0
  [ok ] a key inside JSON                shape=1 expected=yes value=0
  [ok ] a bare prefix in prose           shape=0 expected=no  value=0
  [ok ] a UUID beside a real key         shape=1 expected=yes value=0
  [ok ] a held value glued mid-word      shape=0 expected=no  value=1
  [ok ] a rendered WARN line for sk-or[-]         scans to 0 match(es)
  [ok ] a rendered WARN line for sk-lf[-]         scans to 0 match(es)
  [ok ] a rendered WARN line for pk-lf[-]         scans to 0 match(es)
  [ok ] a rendered WARN line for fc[-]            scans to 0 match(es)
  [ok ] a rendered WARN line for ghp[_]           scans to 0 match(es)
  [ok ] a rendered WARN line for github_pat[_]    scans to 0 match(es)
  [ok ] a rendered WARN line for pcsk[_]          scans to 0 match(es)
  [ok ] a rendered WARN line for AIz[a]           scans to 0 match(es)
  [ok ] the run id survives redaction byte for byte

17 checks, 0 failure(s)
```

Row 8 is the one worth noticing: *a held value glued mid-word* reports
`shape=0 value=1` — the shape rule declines it and the exact-value rule catches
it anyway. That is the layering the whole design rests on, asserted rather than
described.

### One note on the scanner's blanket boundary — a false-negative class

`content.py` applies the token boundary to **`fc-` only**;
`scripts/observability/_common.py` applies it to **every** prefix. The
divergence is deliberate and documented at `content.py:63-84`, and V-REVIEW
agrees with it — the argument and the measurement are in
[`E3.txt`](E3.txt) §4. What belongs here is the consequence for the tooling,
because `_common.py` wears two hats in one module:

* as a **scanner** (the WARN channel), a false negative costs a warning nobody
  needed — which is exactly what the boundary was for;
* as a **redactor** — `CREDENTIAL_REDACTION_PATTERN`, reached through
  `redact_string` and `redact_for_disk`, which is what `pull_langfuse_run.py`
  uses to write pulled Langfuse exports **into** `docs/observability/evidence/`
  — a false negative writes a credential into a committed file.

Measured: `gate-sk-or-v1-…` and `user-ghp_…` are blanked by `content.py` and
**not** by `_common.py`'s redaction pattern. It is **LOW**, for two reasons that
both hold today: `redact_string` runs the exact-VALUE rule first and
unconditionally, so any credential this process holds is blanked wherever it
sits; and the app-side exporter now scrubs that shape on the way out, so such a
string should never reach Langfuse to be pulled back. The tooling redactor is
the second line here, not the first — worth one line so the next person to touch
`_common.py` knows which of its two hats the boundary was chosen for.

A false negative **both** copies share and neither documents: `fc-` now requires
20+ **hex** characters, so a Firecrawl key whose tail is not hex — or a future
key format that is base62 — is invisible to both. A real `fc-` key is 32 hex
today, so this is a bet on the vendor's format rather than a defect; the
exact-value rule is what covers it meanwhile.
