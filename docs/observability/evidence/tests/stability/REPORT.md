# Full-suite crash rate: pre-observability baseline vs current tree

**Verifier:** V-STABILITY. Read-only on the repository; the only files written are
under `docs/observability/evidence/tests/stability/`. No `.env` was copied, moved
or read; no credential value appears here.

**Question.** The full Python suite died twice in a row on the current tree with
`Windows fatal exception: access violation`, exit 139. Does the **crash rate on
the full suite differ** between the pre-observability baseline (b65bd65) and the
current tree?

**Answer, in one line: no. The baseline crashes too, and in this sample it
crashed MORE often than the current tree (2/6 vs 1/6). The access violation is
pre-existing and is not evidence against the observability work.**

---

## 1. Arms, and the worktree self-check

| | baseline arm | current arm |
| --- | --- | --- |
| tree | `D:\MultiAgentSystem-wt\stability-base` (worktree) | `D:\MultiAgentSystem` |
| commit | `b65bd654003bcbc92e8ff643d245cf173d92dc0e` (detached), `git status --short` empty | `7417270` + uncommitted observability work |
| interpreter | `D:\MultiAgentSystem\.venv\Scripts\python.exe` (3.13.5), the SAME venv for both arms | same |
| PYTHONPATH | `D:\MultiAgentSystem-wt\stability-base\src` | unset (editable install) |
| suite size | 2544 tests, 13 skipped | 2685 then 2695 tests, 8 skipped |

The trap in CLAUDE.md is that a worktree silently tests the MAIN tree's source
unless PYTHONPATH is set. Proved before any run, not assumed:

```text
$ cd D:\MultiAgentSystem-wt\stability-base
$ PYTHONPATH='D:\MultiAgentSystem-wt\stability-base\src' \
  D:\MultiAgentSystem\.venv\Scripts\python.exe -c \
  "import brief_crew, sys; print('BRIEF_CREW_FILE', brief_crew.__file__); print('PYVER', sys.version)"
BRIEF_CREW_FILE D:\MultiAgentSystem-wt\stability-base\src\brief_crew\__init__.py
PYVER 3.13.5 (main, Jul  1 2025, 18:31:42) [MSC v.1944 64 bit (AMD64)]

$ ... -c "import brief_crew.observability"
ModuleNotFoundError: No module named 'brief_crew.observability'

# control, main tree, no PYTHONPATH:
BRIEF_CREW_FILE D:\MultiAgentSystem\src\brief_crew\__init__.py
OBS             D:\MultiAgentSystem\src\brief_crew\observability\__init__.py
```

Both halves hold: the worktree loads ITS OWN source, and the observability
package genuinely does not exist there. A later crash dump confirms it from the
other direction: every application frame in base-5's faulting stack reads
`D:\MultiAgentSystem-wt\stability-base\src\...`, so that run was the baseline's
code and not the main tree's.

The 13 skips on the baseline against 8 on the current tree are the expected
doc-reading tests. At b65bd65 in a fresh worktree the `docs/` tree is absent and
those tests skip rather than fail, which is that commit's own change.

## 2. The runs

Command, identical on both arms, one run at a time, arms alternating, nothing
else of mine running concurrently:

```text
<venv>\python.exe -X faulthandler -u -m unittest discover -s tests -t .
```

| arm | run | exit | wall (s) | result / crashed at | `Thread 0x` blocks in dump |
| --- | ---: | ---: | ---: | --- | ---: |
| base | 1 | 0 | 139 | Ran 2544 in 133.8s, OK (skipped=13) | 0 |
| current | 1 | 1 | 152 | Ran 2685 in 146.8s, FAILED (errors=2, skipped=8) | 0 |
| base | 2 | 0 | 132 | Ran 2544 in 127.3s, OK (skipped=13) | 0 |
| current | 2 | **139** | 90 | **CRASH**, access violation at ~90 s | 100 (capped) |
| base | 3 | 0 | 131 | Ran 2544 in 126.0s, OK (skipped=13) | 0 |
| current | 3 | 1 | 149 | Ran 2695 in 143.8s, FAILED (errors=2, skipped=8) | 0 |
| base | 4 | 0 | 130 | Ran 2544 in 125.4s, OK (skipped=13) | 0 |
| current | 4 | 1 | 148 | Ran 2695 in 142.5s, FAILED (errors=2, skipped=8) | 0 |
| base | 5 | **139** | 58 | **CRASH**, access violation at ~58 s | 99 |
| current | 5 | 1 | 148 | Ran 2695 in 143.2s, FAILED (errors=2, skipped=8) | 0 |
| base | 6 | **139** | 82 | **CRASH**, access violation at ~82 s | 100 (capped) |
| current | 6 | 1 | 151 | Ran 2695 in 145.5s, FAILED (errors=2, skipped=8) | 0 |

Six per arm, not the four asked for: the fourth pair left the two arms at 0/4 and
1/4, which distinguishes nothing, so two further pairs were run. Runs 5 and 6 are
where the baseline crashed. Raw output for every run is beside this file in
`runs/<arm>-<n>.txt`, each carrying its own `### ARM / ### CWD / ### PYTHONPATH /
### EXIT / ### WALL_SECONDS` header.

**No port errors of any kind** in any of the twelve runs. `address already in
use`, `WinError 10048` and `EADDRINUSE` are all absent, so the suite's ephemeral
ports did not collide with the 8000 / 8093 / 8098 / 8099 servers other workers hold.

### Crash rate

| arm | crashes | runs | rate | 95% CI (Clopper-Pearson) |
| --- | ---: | ---: | ---: | --- |
| **baseline b65bd65** | **2** | 6 | **33.3 %** | 4.3 % to 77.7 % |
| **current tree** | **1** | 6 | **16.7 %** | 0.4 % to 64.1 % |
| pooled | 3 | 12 | 25.0 % | 5.5 % to 57.2 % |

Fisher exact test on `[[2,4],[1,5]]`: **p = 1.00**. The two rates are not
distinguishable, and the point estimate points at the baseline.

### The two persistent errors are not crashes

Every completing run on the current arm exits 1 on the same two, both inside
another worker's live edit and unrelated to stability:

```text
ERROR: tests.observability.test_trace_shape.RootSpanTests.test_detaching_leaves_a_root_that_keeps_the_chosen_trace_id
ERROR: tests.observability.test_trace_shape.RootSpanTests.test_the_sdk_gives_the_run_span_a_parent_that_is_not_there
```

## 3. Where the crash lands, and what "about 100 threads" actually was

base-5 is the only one of the three dumps whose `Current thread` block survived
truncation, and it is the baseline's own source:

```text
Windows fatal exception: access violation

Current thread 0x000066c0 (most recent call first):
  File "...\sqlalchemy\util\_collections.py", line 526 in get
  File "...\sqlalchemy\sql\elements.py", line 711 in _compile_w_cache
  File "...\sqlalchemy\engine\base.py", line 1635 in _execute_clauseelement
  File "...\sqlalchemy\sql\elements.py", line 526 in _execute_on_connection
  File "...\sqlalchemy\engine\base.py", line 1421 in execute
  File "D:\MultiAgentSystem-wt\stability-base\src\brief_crew\service\persistence.py", line 1739 in save_node_metrics
  File "D:\MultiAgentSystem-wt\stability-base\src\brief_crew\service\registry.py", line 3119 in _persist_status
```

The immediate frame differs per crash. SQLAlchemy statement-cache lookup here,
`socket.socketpair` during asyncio loop creation in the two reported earlier. But
the neighbourhood is one: the service layer, a TestClient/httpx or MCP socket
path, inside a process carrying a very large leaked-thread population. What each
crash was next to:

| run | last thing on stdout before the fault |
| --- | --- |
| base-5 | a builder flow completing (`builder_ug_7f3a2b19_v1`), persisting node metrics |
| base-6 | tests/service orphan recovery, `GET http://testserver/api/runs/orphan-http/frames` |
| current-2 | `MCP Connection Started - http://127.0.0.1:52922/mcp, streamable-http` |

**Correction to the premise.** "about 100 threads alive, 78 of them registry" is
NOT a thread-population measurement. It is faulthandler's `MAX_NTHREADS` cap of
100 blocks per dump. base-6 and current-2 hit exactly 100 and lost their
`Current thread` block to that truncation; base-5 printed 99 and kept it.

## 4. The thread leak is identical on both arms

tests/service alone, run once per arm under a driver that reports
`threading.active_count()` after the suite finishes (`runs/threads_driver.py`,
`runs/threads-base.txt`, `runs/threads-current.txt`):

| | baseline b65bd65 | current tree |
| --- | ---: | ---: |
| tests run | 1136, 0 errors, 0 failures | 1136, 0 errors, 0 failures |
| wall | 73.1 s | 74.3 s |
| **threads alive at end** | **1164** | **1164** |
| validator* | 1050 | 1050 |
| brief* | 96 | 96 |
| CrewAISyncHandler_0..9 | 10 | 10 |
| OtelBatchSpanRecordProcessor | 1 | 1 |
| LanceDBBackgroundEventLoop, CrewAIEventsLoop, mcp, Thread x3, MainThread | 6 | 6 |

The same census, the same count, and the same `OtelBatchSpanRecordProcessor`
thread on BOTH arms. That one is CrewAI's own, not the new exporter's. The
observability wiring adds ZERO threads and no measurable time to tests/service
(+1.2 s, inside run-to-run noise). The 1,164 leaked registry worker and
`_sweep_loop` threads that dominate the crash dumps are entirely pre-existing at
b65bd65.

## 5. Confounder, stated because it is real

The **current arm was being edited by other agents while it was measured**; the
baseline arm is frozen at a commit and cannot be.
`src/brief_crew/observability/mapping.py` was written at 00:56:41, inside
current-2's window, and the current arm's test count moved from 2685 (run 1) to
2695 (runs 3-6). So the current arm is six runs of a MOVING tree, and its 1/6 is
the rate of whatever it happened to be at each moment. This cuts against the
current tree if anything: a tree being edited mid-run is the more hostile arm,
and it still crashed less.

## 6. Conclusion

Across twelve full-suite runs, six per arm, alternating, on one machine and one
interpreter, the baseline b65bd65 crashed **2 times in 6** with
`Windows fatal exception: access violation` and the current tree crashed **1 time
in 6**. Fisher exact p = 1.00, and with n = 6 per arm the 95% intervals
(4.3-77.7 % and 0.4-64.1 %) overlap almost completely: these numbers CANNOT
distinguish the two rates, and in particular they cannot rule out a modest change
in either direction, since anything up to roughly a 3x swing is inside this
sample. What they can rule out is the hypothesis the question was really asking
about. **A crash of this exact signature occurs on a tree that contains no
observability code at all**, one of its faulting stacks reads entirely from the
baseline worktree's own source, and the thread leak that supplies the conditions
for it is identical on both arms to the last thread (1164 = 1164 after
tests/service). The access violation is a pre-existing property of this suite on
Windows, a very large population of never-joined registry threads outliving the
tests that made them, and the observability work is not its cause. Attributing it
to the exporter is not supported; the reported "1-in-10 on tests/service with the
wiring removed" is consistent with the pooled 25 % rate measured here and with
nothing else.

---

*Method note: `runs/run_one.sh` is the harness; every raw log, the thread driver
and its two outputs sit beside it. The worktree
`D:\MultiAgentSystem-wt\stability-base` was removed after the final run.*

*Addendum, measured at teardown: the main tree's HEAD moved from `7417270` at the
start of this pass to `ad6a696` at the end, and `git status` showed further
uncommitted edits under `src/brief_crew/observability/`, `src/brief_crew/config.py`,
`src/brief_crew/events/serializer.py` and `scripts/observability/` belonging to
other workers. That is the section 5 confounder quantified: the current arm is not
one tree measured six times.*
