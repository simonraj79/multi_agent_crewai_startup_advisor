# Product round 1 — the whole-product gauntlet

**Persona: design director.** The prompt opens with the gauntlet's sentence,
verbatim from `benchmarks/README.md`:

> You are a hostile design director who has shipped a competitor to this
> product. You are looking for reasons to reject. Vague praise is a failure
> of your job.

| | |
| --- | --- |
| Round | product 1 (round 1 of the product-level gauntlet) |
| Tree | `D:\MultiAgentSystem-wt\judge`, branch `judge/product-1` off `gauntlet/plans` |
| HEAD | **`5cb7092`**, 2026-09-04 22:28:44 +0800 |
| Backend | `SYNTHETIC=1`, `SYNTHETIC_BRANCH_DELAY_SECONDS=5`, `PORT=8092`, `BUILDER_ALLOW_GATELESS_GRAPHS=1`, `MCP_ALLOW_INSECURE_LOCAL=1`, `RUN_RATE_LIMIT_MAX_RUNS=100`, the five-mode `SYNTHETIC_FAILURE` string |
| UI | `E2E_API_TARGET=http://127.0.0.1:8092`, `E2E_UI_PORT=5280` |
| Viewport | 1440×900, `data-theme="dark"` unless a line says otherwise |
| References | `docs/flowise-notes.md` (build-time, Flowise Agentflow v2), `docs/chatdev-notes.md` (run-time, ChatDev 2.0) |
| Spend | **$0.00.** No paid backend, no `send-message`, no `E2E_BASE_URL`. |

## The coin flip, and why there was not one

**There was no A/B flip this round, and the leg was NOT BLIND.** Two reasons,
both recorded rather than worked around:

1. `benchmarks/README.md`'s own standing limitation applies in full. Every
   agent spawned in this repository auto-loads `D:\MultiAgentSystem\CLAUDE.md`
   and the user's `MEMORY.md` before it reads a word of its brief. Between them
   they name the `$10.00` run ceiling and the 13-billable / 8-escalation bounds
   — figures printed on our own cost meter, in the capture — and the defect ids
   in exactly the `D-15-13` form. A critic cannot be blind to which set is ours.
2. This round is a **verifier plus critic** pass on a named branch, so the
   evaluator knew which tree it was measuring before it opened a capture.

**Every visual score below (dimensions 1–10) is therefore a CRITIQUE, not a
blind comparison.** The reference scores are read from
`docs/flowise-notes.md` and `docs/chatdev-notes.md`, which are measurements
from those products' source, not from captures taken side by side this round.
Where a reference score rests on a note rather than on a pixel, the row says so.

What would close it is unchanged: an evaluator that does not auto-load this
repository's documentation. Nothing in this harness provides one.

## What was executed here

| Suite | Result | Command |
| --- | --- | --- |
| Python | **2420 run · 0 failures · 6 skipped · 152.1 s** | `unittest discover -s tests -t .`, `PYTHONPATH` set |
| Frontend unit | **1682 passed in 84 files · 12.5 s** | `npm test` |
| Type check | **exit 0** | `npx vue-tsc -b --force` |
| Production build | **built in 772 ms**, one >500 kB chunk warning | `npm run build` |
| **E2E** | **121 passed · 7 FAILED · 9.0 min** (128 tests in 23 files) | `npx playwright test`, both projects |
| Captures | 13 passed · 2.7 min | `capture-run`, `capture-templates`, `visual/node-grammar`, `visual/choreography` |

The E2E suite is **red at HEAD**. That is not an environment artefact and the
evidence is in defect **P-02** below.

---

# Part A — the eighteen open ledger rows, re-measured at `5cb7092`

Each row's own located command was re-run. `ABSENT` means the row's defect is
gone with the figure that now answers it; `PRESENT` means it is still there.
The builder's `## Status` prose was not taken as evidence for any row.

> **Note on the commit range.** The brief named `git log --oneline 9b06e40..HEAD`.
> Two rows are closed by commits that **predate** `9b06e40` (`d875762` for
> D-15-28, and its test at `aeaedc9`), so the range under-reports. Fixing
> commits below were found with `git log HEAD --grep=<id>` and each was checked
> to be an ancestor of HEAD.

| id | verdict | measured at HEAD | fixing commit(s) |
| --- | --- | --- | --- |
| **D-15-2** | **PRESENT** | 16-node `Idea validator`, 1440×900, **no dock open at all**: opens at scale **0.733** (title 11.00 px, the declared floor) with **7 of 16 nodes wholly off-pane**; pressing the new `7 off-pane · Fit` chip brings all 16 on-pane at scale **0.436** — card 105 px, title **6.53 px**. On the 6-node `Sequential pipeline` with the Versions panel docked: pane 380 px tall, 2 of 6 wholly inside, 2 clipped (75 %, 41 %), 2 wholly outside; Fit → 6 of 6 on-pane at scale **0.376**, card 90 px, title **5.64 px**. The graph is never simultaneously whole and legible at this viewport. | `b981916`, `d1a2096`, `80609d9` — a real fix (the minimap chip is one of the two answers the row itself named) that trades clipped-but-legible for whole-but-unreadable |
| D-15-23 | **ABSENT** | Version rows now read `v2 · head · draft` and `v1 · published`; the published version is badged **on its own row** and carries no `DRAFT`. Header, library row and version rows agree. | `0610084` |
| D-15-24 | **ABSENT** | The v2 row reads `Sequential pipeline · 6 nodes · saved · **−1 node, −1 edge** · just now · 5.4 KB` — a computed node/edge delta per row, not just a byte size. | `f60d0d0`, `8fc03fa` |
| D-15-25 | **ABSENT** | With the version panel open, `⋮` menu box (925–1137, 106–367) against version rows (276–1060, 443–506): **overlap 0 px²**. Menu item reads **`Export head (v2)`**. | `1846302`, `09d970d` |
| D-15-26 | **ABSENT** | Four glyphs, each **32×32** (was 28), each with a native `title` (`Versions` / `Duplicate` / `Export` / `Delete`) and an `aria-label` naming the document. Export right edge 1149, Delete left edge **1172** → **23 px** separation (row asked ≥16). | `8415706`, `80609d9` |
| D-15-27 | **ABSENT** | Template card heights are equal within each grid row (401 / 401 / 401 / 401, then 459 / 459, then 401 / 401); worst ratio across the whole grid **1.14×** (was ~3.4×). `.template-caveat` is `overflow-y: auto`, clientHeight **66** vs scrollHeight **198** — it scrolls inside a clamped box. | `677657f`, `80609d9` |
| D-15-28 | **ABSENT** | Live through the routes on 8092, all ten node kinds in one document: `CREATE 201 → EXPORT 200 → IMPORT **201**`, kinds preserved `['input','agent','crew','gate','router','transform','output','tool','mcp','skill']`, `needs_credentials: ['n_agent','n_tool','n_mcp']`. `McpConfig.server_id` and `SkillConfig.skill_id` are now nullable, `server_hint` is accepted and `skill_name` exists as a real field. | `d875762` (schema), `aeaedc9` (round trip over every kind) |
| D-15-29 | **ABSENT** | The schema refusal now names the node the canvas names. Measured on three malformed creates: `the "Idea" input node: field - Field required (nodes.0.field)` and `the "Writer" agent node: task - Field required (nodes.1.task)`. No bare `nodes.3` anywhere. | `b67f8ab` |
| D-15-30 | **ABSENT** | `tests/builder/test_export.py` now carries `RoundTripEveryKindTests` with `test_the_fixture_covers_every_kind_and_fails_when_one_is_added`, `test_the_fixture_itself_parses_which_raw_document_deliberately_does_not` and `test_the_stripped_document_re_parses_for_every_kind`. `raw_document()` still deliberately does not parse and a test now says so. `skill_name` is a schema field (`document.py:708`). | `aeaedc9` |
| D-15-31 | **ABSENT** | Plan 15 criterion 11 reads `(~~33~~ **37**)`; `npx vitest run tests/builderPersistence.spec.ts` → **`Tests  37 passed`**. Struck through, not silently edited. | `f98ef5e` |
| **D-15-32** | **ABSENT** (measured half) | With `TEST_DATABASE_URL` unset: bare `python -m unittest tests.pg.test_two_writers` → **exit 0** over five skips; `python scripts/run_without_skips.py tests.pg.test_two_writers` → **exit 1**, naming all five skipped tests. `ci.yml` also gained an explicit `[ -z "$TEST_DATABASE_URL" ] → exit 1` step. **Residual, and it is a ruling, not a defect:** `ci.yml:95` is still `if: github.ref == 'refs/heads/main'` (PLANS.md decision 25), so the new guard has never executed in CI on any branch. Logged as **P-10**, not held against the row. | `13ae696` |
| D-15-33 | **ABSENT** | Plan 15 criterion 6 now reads "…upgrades ~~to a clean v2 document~~ **cleanly, and would upgrade cleanly to v2 with `BUILDER_DOCUMENT_SCHEMA` moved**", with a dated amendment stating the shipped path's actual answer. | `9ce52c5` |
| D-15-34 | **ABSENT** | `grep -c -i credential tests/service/test_isolation_matrix.py` → **22** (was 1). The docstring table has a `credentials` row at `:14` (`404 on GET, DELETE and the probe; empty list` / `401`) and `CredentialRoutes` asserts it in the same three-caller shape. Module green: **36 tests**. | `b49c45b` |
| D-01-6 | **ABSENT** | `CREDENTIAL_FIELDS['http_header']` and `['mcp_header']` are now `('name', 'header_value')`, and `is_secret_key('header_value')` → **True**. Swept every kind: **no credential field other than `name` is non-secret**. The row's own suggested fix (`value` on `SECRET_KEYS`) was tried and measured wrong — six tests red across four modules — and the field was renamed instead. | `70a0e55` |
| D-01-7 | **ABSENT** | Measured live, four handshakes against `ws://127.0.0.1:8092/ws` with `CORS_ALLOW_ORIGINS=()`: no `Origin` → **4404 run not found**; `http://evil.example.com` → **4406 origin not allowed**; `http://127.0.0.1:8092` (same-origin) → **4404**; `Origin: null` → **4406**. The origin is asked *before* the run is looked up, so it is not an existence oracle either. | `cd3ce75` |
| D-01-8 | **ABSENT** | Plan 01 criterion 9 reads `authGate.spec.ts (~~5~~ **4**)`, `identityStorage.spec.ts (~~9~~ **8**)`, `builderRunHandoff.spec.ts (3)`. Measured: **4 passed**, **8 passed**, **3 passed**. | `f98ef5e` |
| D-01-9 | **ABSENT** | `grep -rln "tech-stack" tests/` → **`tests/test_env_knob_doc.py`** (was nothing). Ran it: **6 tests, OK**, including `test_the_plan_records_that_this_test_verifies_it` and `test_the_heading_count_is_the_scan_count`. | `e767dbb` |
| D-01-10 | **ABSENT** | Criterion 6 carries an amendment saying the second exclusion **no longer exists** rather than explaining it — `70a0e55` removed it by renaming the field. The better of the two fixes the row named. | `ed002d8` |

**Seventeen of eighteen absent. One — D-15-2 — is PRESENT for the fourth round
running**, and for the first time it is present on the flagship template with
**nothing docked at all**, which is a wider surface than any of its three
previous sentences.

---

# Part B — the sixteen dimensions

Reference scores for 1–10 come from the two notes files. **Dimensions 1–10 were
not scored blind** (see the disclosure above). Dimensions 11–16 are scored
against test output and the plans' `## Status` evidence; their reference is the
engineering standard, 10.

| # | Dimension | ours | ref | ≥8 met? | open defect? |
| ---: | --- | ---: | ---: | --- | --- |
| 1 | New-flow creation | **9** | 7 | yes | no |
| 2 | Node grammar at 50 % | **9** | 8 | yes | no |
| 3 | Drag precision | **9** | 6 | yes | no |
| 4 | Inspector ergonomics | **8** | 7 | yes | no |
| 5 | Edge legibility | **8** | 8 | yes | no |
| 6 | Graph scale | **7** | 8 | **NO** | **yes** |
| 7 | Launch sequence fidelity | **9** | 7 | yes | no |
| 8 | Easing character | **8** | 8 | yes | no |
| 9 | Message choreography | **9** | 7 | yes | no |
| 10 | Alive vs noisy | **9** | 6 | yes | no |
| 11 | Compiler correctness | **9** | 10 | yes | yes (below ref) |
| 12 | Error handling | **7** | 10 | **NO** | **yes** |
| 13 | Cost discipline | **8** | 10 | yes | yes (below ref) |
| 14 | Isolation | **9** | 10 | yes | yes (below ref) |
| 15 | Templates | **6** | 10 | **NO** | **yes** |
| 16 | RAMP integrity | **4** | 10 | **NO** | **yes** |

**The gate is not met.** Four dimensions are under 8 and every engineering
dimension is under its reference.

---

## 1 · New-flow creation — ours 9, ref 7 (Flowise), *not blind*

**Measured.** `#/build` → click `Blank canvas` → the canvas holds
`idea → result`, one edge, and the problems headline reads **`Ready to publish`**
— a valid, publishable graph in **one click**. First own node: one canvas click
plus one digit (`2`) → `agent_1` placed **and the inspector already open on it**.
Three pointer/key actions from landing to a configured-and-selected first node.

Flowise seeds a Start node at `{x:100,y:100}` (`Canvas.jsx:656-677`); a
Start-only flow is not runnable, and the palette is a FAB `Popper` with a
**500 ms debounced** search you must open before you can drag anything.

Deduction (one point): at 1440×900 the gallery's third template row sits at
**y1208**, 308 px below the fold, so two of the eight shapes are invisible on
arrival and there is no "new blank graph" affordance outside the grid.

## 2 · Node grammar at 50 % — ours 9, ref 8 (Flowise), *not blind*

`benchmarks/ours/03/03-node-grammar-zoom050-1440x900-dark.png`, read. Ten kinds,
each with a per-kind accent, an icon medallion, a **numbered eyebrow that names
the kind in words** (`01 · INPUT`, `03 · CREW`, `08 · MCP`), a title, a
sub-line and a count badge. At 0.5 the titles resolve; the sub-lines do not.
Flowise v2 carries colour + squircle icon + label + config chips and no kind
word at all — ours answers "agent vs task vs tool vs router" from the eyebrow
without relying on the reader having learned the palette.

Deduction: the sub-line (`cheap · scoper`, `2 iter · no tools`) is ~5 px at 0.5
and carries the only statement of tier and tool count.

## 3 · Drag precision — ours 9, ref 6 (Flowise), *not blind*

**Measured** on `.vue-flow__handle`: the element is **24×24 px** (hit) and its
`::after` is **12×12 px**, `border-radius: 50%`, white fill, 1.5 px accent ring
(visual). Every port is visible at rest. Validity is projected onto the target
as `is-port-ready` from the canvas's own predicate
(`BuilderNode.vue:709-729`), and the canvas is `ConnectionMode.Strict` with
per-port `data-handleid` (`in`, `out`, `attach`, `member`, `approve`, `revise`).

Flowise v1 is a **10 px visual = 10 px hit** circle coloured by *selection*, not
type. Flowise v2's output handle is 20 px but `opacity: hovered ? 1 : 0`, and a
rejected cycle **fails silently** — its own notes say "do not replicate that".

**Not measured this round:** three successful connections at 50 / 100 / 150 %.
The geometry was measured; the gesture was left to `e2e/builder.spec.ts`, which
is green. Zoom steps 1.2× and never lands on exactly 1.0 (0.903 → 1.084).

## 4 · Inspector ergonomics — ours 8, ref 7 (Flowise), *not blind*

Docked rail, never a modal (R15), opening **automatically** on the node just
placed. `jr-inspector-agent.png`: a node-scoped problem banner at the top, NAME,
IDENTIFIER, TIER as a two-way switch with the resolved slug, a live price table
(`INPUT $0.30/M · OUTPUT $2.50/M · CONTEXT 1.0M · SPEED fast`), the honest
sentence *"Routed for speed, so this bills up to $0.54/M on its dearest endpoint
— 1.8× the headline"*, capability chips and the agent picker. Flowise v2
configures through **`EditNodeDialog`, a double-click modal**.

Two deductions, both landed as defects: **P-04** (the library badge calls a
published document a draft) and **P-05** (the canvas stops saying a version is
live once head moves past it).

## 5 · Edge legibility — ours 8, ref 8 (Flowise), *not blind*

**Measured** on `.vue-flow__edge-builder`: a per-edge `<linearGradient
id="edge-gradient-e1">` source→target, a per-edge `marker-end`
(`#edge-arrow-e1`), a `builder-edge-hit` path at **16 px** plus Vue Flow's own
20 px interaction path, and the visible path at **1.5 px / opacity 0.75**.
Branch labels render on the canvas (`scope_approved`, `scope_revise`,
`verdict_revise`). Flowise v2 matches on gradient and hit path (15 px) and has
**no arrowheads** — direction is ours alone.

Deductions: **P-06** (1.5 px renders sub-pixel at the scales the product's own
fit chooses) and **P-07** (the minimap covers 30.2 % of a node).

## 6 · Graph scale — ours 7, ref 8 (Flowise) — **BELOW THE REFERENCE**

The frame budget is met, and the harness is honest about being one machine:
`benchmarks/perf/canvas.json`, `fixture48` at 48 nodes — **mean 16.666 ms, p95
16.700 ms, max 16.800 ms over 371 frames**, against a budget of mean ≤16.7 /
p95 ≤20. `instrumentCheck` blocks the main thread and reports max 300 ms, so the
instrument is known to see a stall. *(File unchanged; not committed.)*

Two reasons it does not reach 8:

- **The harness cannot distinguish 48 nodes from 1.** `fixture48` mean
  16.665881, `idle48` 16.666022, `gesture1` 16.665713 — a spread of
  **0.0003 ms** across 48 nodes, 1 node and doing nothing. Every case is pinned
  to the vsync floor. What is proved is "no frame was dropped"; what is claimed
  in the rubric — *pan/zoom cost at 48 nodes* — is not measurable by this
  instrument. That is worth knowing before the number is quoted again.
- **The usability half fails at scale**, which is D-15-2 and defect **P-03**.
  Flowise pins `minZoom: 0.5` on the v2 canvas, so it cannot render a graph too
  small to read; it clips instead. We render at 0.376 and 0.436. Their floor is
  the design decision that prevents exactly the failure we ship.

## 7 · Launch sequence fidelity — ours 9, ref 7 (ChatDev), *not blind*

`e2e/visual/choreography.spec.ts` "the control glows from the press, and the
cards land staggered", green: `animation-delay` **0s / −0.04s / −0.08s /
−0.12s** by `getComputedStyle`. That is the reference's own negative-delay idea
(`HomeView.vue:11-22`, cubes at `-0…60s`) applied to the graph — and ChatDev
itself has **no entrance stagger on the graph at all** (`LaunchView.vue:1712-1746`
is one `setNodes` plus a `fitView`). One glow vocabulary is shared between the
launch control and the waiting gate, as `docs/chatdev-notes.md` §6 asks.

## 8 · Easing character — ours 8, ref 8 (ChatDev), *not blind*

**Measured live** on a running card: `animation-name: node-glowing, node-pulse`,
`animation-duration: 4s, 2s`, `animation-iteration-count: infinite, infinite`,
`transition: filter .16s, box-shadow .16s`. The two names, both periods and the
dual-period intent match the reference verbatim (`vueflow.css:81-125`).

Deduction, and it is exactly the kind a design director is for: **the timing
functions are `linear, ease-in-out`; the reference is `linear, ease-out`**
(`docs/chatdev-notes.md` §2, quoted from `vueflow.css:81`). One curve was
changed in a plan whose criterion says it quotes the reference's curves. Filed
as **P-09**.

## 9 · Message choreography — ours 9, ref 7 (ChatDev), *not blind*

The handoff token walks the **real edge path** on an `edge_traversal` frame and
is asserted monotone in x *and* y over three samples and removed inside
4,100 ms (`choreography.spec.ts`, green; recording at
`e2e/capture-handoff.spec.ts`). Agent colour is **stable per node** and the same
on the card medallion, in the dialogue rail and on the token — ChatDev re-draws
chat avatars randomly (`LaunchView.vue:960` omits the node id) so they never
match its own graph, and assigns sprites randomly per session. `grep -rn "Edge
condition met" frontend/src` → nothing: we do not parse a log string to find a
handoff, we read a frame.

## 10 · Alive vs noisy — ours 9, ref 6 (ChatDev), *not blind*

**Measured live** over a 20-step synthetic run, sampled eight times at 1.8 s:
running animations inside `.vue-flow` peak at **10** (budget 12), page-wide 15;
and at the terminal frame **0** page-wide, held over two further samples. Idle
recede is real — node opacities resolve to **{0.55, 0.6, 1.0}** mid-run, so the
speaker reads at a glance. ChatDev has **no idle recede anywhere**: emphasis is
purely additive at `scale(1.02)`.

Two small deductions: the page-wide count (15) exceeds the rubric's 12 if the
budget is read over the page rather than the canvas, and the plan names *one*
idle level (0.55) where three are rendered.

## 11 · Compiler correctness — ours 9, ref 10

`tests/builder/test_rubric11.py`, **10 tests, OK in 12.4 s**, including
`test_every_fixture_matches_its_golden_in_a_fresh_process` and
`test_the_fresh_process_really_produced_every_fixture`. **20 fixtures**
(`test_there_are_twenty_fixtures` asserts the count) plus 2 replay goldens = 22
files under `tests/builder/fixtures/rubric11/`, every node kind covered by
`test_the_fixtures_cover_every_kind_and_fails_when_one_is_added`. Subprocess
comparison, so it is determinism across interpreter starts and not within one.
20/20. Deduction: **P-10**, the residual under D-15-32.

## 12 · Error handling — ours 7, ref 10 — **BELOW 8**

`tests/builder/test_failure_modes.py` **25 tests, OK**;
`e2e/failure-modes.spec.ts` **7 passed** inside the full run;
`e2e/stream-failure.spec.ts` 2 passed. Five modes raise real classed exceptions
(`auth`, `schema`, `rate_limit`, `refusal`, `tool_timeout`) and the sixth,
`cyclic_graph`, is deliberately absent from `SYNTHETIC_FAILURE_REASONS` because
`bounds.py` refuses it at validate and again at publish — a documented decision,
not a gap.

It does not reach 8 for two measured reasons, **P-08** and plan 12's own
admission (`### Built — 2026-09-04`: "Eight of ten met, one partial, one not
reached", criterion 10 `partial`). The rubric asks for six modes *legible and
recoverable*; legibility on a 16-node graph at 1440×900 is not established.

## 13 · Cost discipline — ours 8, ref 10

`tests/test_model_ceiling.py` **11 tests, OK**. The ceiling is measured against
the **max endpoint** price and enforced at the API through
`provider.max_price`, not merely asserted in a table. The canvas carries a
worst-case meter (`$1.22 at published prices / $1.51 enforced · 1.8× nitro
margin / $10.00 ceiling`) with billable / escalation / cycles / nodes bars, the
publish dialog gates on `Inside the run cost ceiling`, and the inspector prints
the per-model rate and the nitro spread in words. This is the strongest
engineering surface in the product.

Deduction: **P-01**'s sibling, **P-08** — the run console's `COST` reads
`$0.0000` and `TOKENS 0` on a completed run, so the one surface an operator
watches for spend cannot be exercised on the only free path there is. That is
closed item 33's lesson arriving again.

## 14 · Isolation — ours 9, ref 10

`tests/service/test_isolation_matrix.py` **36 tests, OK**, now with the
credentials row rubric 14 names by itself. `e2e/isolation.spec.ts` green inside
the full run. Two live controls taken this round: the `/ws` origin gate refuses
a cross-origin handshake with **4406 before the run is looked up** (four
handshakes, table in Part A), and an anonymous `curl` to
`/api/builder/workflows` returned a **different library** from the same route
called inside the signed-in page — two documents versus one, neither visible to
the other.

Residual, unchanged and acknowledged in source: an **unowned** run is still
streamable by anyone who can name its `run_id` and `session_id` *from an allowed
origin*. The origin gate closes the cross-origin half only.

## 15 · Templates — ours 6, ref 10 — **BELOW 8**

Eight shapes ship, all open pre-wired, and `capture-templates.spec.ts` writes
the gallery and every template at 1440×900 and 390×844 in both themes (28 PNGs,
verified on disk). `e2e/templates.spec.ts` green inside the full run.

But the rubric says *"all four run from a cold sign-in with **zero
configuration**"*, and the honest answer is that **the paid half has never been
done** (MISSION §12 item 2, decision 22). What is proved is that four templates
launch against `SYNTHETIC=1`, which replaces the crew factories and nothing
else. Two further deductions are measured here: **P-01** means a template that
attaches a user skill would attach an empty pack, and the flagship template
opens with 7 of its 16 nodes off-pane (**P-03**).

## 16 · RAMP integrity — ours 4, ref 10 — **WORST DIMENSION**

The rubric asks that *every shipped feature has a committed plan file whose
criteria are all checked*, and that `PLANS.md`'s totals hold. Counted, not
copied:

- Criteria per plan sum to **179**, matching `PLANS.md` exactly. That half holds.
- **`PLANS.md` has not been touched for 85 commits** (`git log -1 --format=%H --
  PLANS.md` → `5562bd6`; `git log --oneline 5562bd6..HEAD | wc -l` → **85**),
  while its own preamble says "Update this table when a plan's `Status` line
  changes, and nowhere else". **Twelve plan files have had committed changes in
  that window** — 01, 03, 04, 05, 06, 07, 08, 10, 11, 12, 13 and 15
  (`git log --format= --name-only 5562bd6..HEAD -- .agent/plans/ | sort -u`).
- Consequently **plans 11, 12 and 13 are listed as `Planned` with `0` ticked**
  while their own files say *"Fourteen of the fifteen criteria met"*,
  *"Eight of ten met"* and *"**Eleven of eleven criteria met**"*. The published
  total **123 / 179** understates by **at least 33**; the real figure is
  **≥ 156 / 179**.
- **The tick has no machine-checkable form**, which is why the drift is
  possible. Sampling the second column of every plan's Status table gives at
  least five shapes: `done` (01, 15), `**met**` (11, 12, 13),
  `**not reached**` (05), `**met, with three guarded assertions**` (12), and in
  02, 03, 09, 10 and 14 the cell is *the evidence itself* with no state token at
  all. No expression can regenerate the `Ticked` column.
- **The E2E suite is red at HEAD** — 7 of 128 — and six of those are stale
  committed baselines (**P-02**).
- One stale count survives inside plan 15: line **107** still reads
  "`frontend/tests/builderPersistence.spec.ts` (33 tests) is the contract" while
  criterion 11 twelve pages later reads `(~~33~~ **37**)` and the file answers
  37. D-15-31 fixed the criterion and not the prose that states the contract.

---

# Ranked defects

Every one is specific, located and actionable, with the dimension, both scores,
the delta, the file, the viewport and the measurement.

### P-01 — a user's SKILL.md body is silently discarded, and every skill test is blind to it
**dim 12 · ours 7 · ref 10 · Δ3** *(also dims 13, 15)*

`SkillStore.create` (`src/brief_crew/service/attachments.py:617-624`) stores
`path=str(pack_directory(pack) / SKILL_FILENAME)`, which on the shipped default
`SKILLS_ROOT = "data/skills"` (`config.py:3428`) is **relative and already
contains the root**. `SkillStore._pack` (`attachments.py:528-538`) then
re-prefixes any non-absolute stored path with `skills_root()`:

```text
skills_root()          data\skills
stored by create       data\skills\users\e2e-user\e2e-probe-style\SKILL.md   (exists: True)
read back by _pack     data\skills\data\skills\users\e2e-user\...\SKILL.md   (exists: False)
```

The `except OSError: body = ""` two lines below — written for "the disk is a
cache that a restart can empty" — turns a path bug into silent data loss.
Measured live against 8092, through the routes, as the signed-in synthetic user:

```text
POST /api/builder/skills            201, size_bytes 0, body ""
GET  /api/builder/skills/{id}       body length 0
file on disk                        107 bytes
GET  /api/builder/skills/{builtin}  body length 2548     <- built-ins are fine
```

Built-ins are unaffected because `load_builtins()` never goes through `_pack`.

**Why 2,420 green Python tests cannot see it:** every skill test patches
`SKILLS_ROOT` to a `tempfile` directory, which is **absolute**, so the
re-prefix branch never executes —
`tests/builder/test_skills_materialise.py:60`,
`tests/service/test_skills_endpoint.py:95`, `test_skills_import.py:73`,
`test_skills_isolation.py:80`. The defect is reachable **only on the shipped
default**, which is what production and a fresh checkout use. This is the
repository's own "tests that pass for the wrong reason" pattern, in the one
place it costs an author their content.

The E2E notices and is the only thing that does:
`e2e/builder-skills.spec.ts:214`, `skill-body-render` resolves to
`<div class="markdown-body skill-body"></div>` and the assertion fails
`hidden`. Reproduced in isolation (`--project=chromium`, 1 failed / 2 passed).

**Fix:** store an absolute path, or make `_pack` not re-prefix a path that is
already root-relative — and make the `OSError` fall-through report rather than
blank, since it is now proven to hide a bug rather than a missing file.

### P-02 — the E2E suite is red at HEAD, and six of the seven are stale committed baselines
**dim 16 · ours 4 · ref 10 · Δ6**

`npx playwright test` at `5cb7092`: **121 passed, 7 failed, 9.0 min**, 128 tests
in 23 files, against `SYNTHETIC=1` on 8092 with `E2E_MCP_URL` set.

```text
[chromium] e2e\builder-skills.spec.ts:170                       (= P-01)
[chromium] visual\builder-canvas.spec.ts:164  sixteen-node template — dark
[chromium] visual\builder-canvas.spec.ts:164  sixteen-node template — light
[mobile]   visual\builder-canvas.spec.ts:164  sixteen-node template — dark
[mobile]   visual\builder-canvas.spec.ts:164  sixteen-node template — light
[mobile]   visual\builder-canvas.spec.ts:178  problem state — dark
[mobile]   visual\builder-canvas.spec.ts:178  problem state — light
```

Those are **exactly the six snapshots `d1a2096` regenerated** for the off-pane
strip. Since `d1a2096`, **21 further commits** (34 file changes) landed under
`frontend/src/components/builder/` and `studio.css` (`09d970d`, `0814523`,
`2902a1f`, `f2b0252`, `dae22f2`, `d73fa96` and the `5cb7092` merge), and the
baselines were not regenerated again. The diff
(`test-results/…-dark-chromium/template-16-dark-diff.png`, read) shows the whole
graph translated and the minimap chip changed — product state, not environment.
`problem-state-light` on mobile is 12,723 differing pixels, ratio 0.04.

Not my contamination: the diff's own left rail reads `LIBRARY / Saved graphs /
No saved graphs yet`, so the spec ran against an empty library.

**Fix:** regenerate the six with `--update-snapshots` in the same commit as
whichever change moved them, and fix P-01 rather than re-baselining around it.

### P-03 — the flagship template is never both whole and legible at 1440×900
**dim 6 · ours 7 · ref 8 · Δ1** *(= ledger row D-15-2, fourth round)*

`Idea validator`, 1440×900, dark, **no panel docked**:

| state | transform scale | card width | title | nodes wholly off-pane |
| --- | ---: | ---: | ---: | ---: |
| on open (auto-fit) | 0.733 | 176 px | **11.00 px** | **7 of 16** |
| after pressing `Fit` | 0.436 | 105 px | **6.53 px** | 0 of 16 |

`Sequential pipeline` (6 nodes) with the Versions panel docked, pane 380 px:
2 wholly inside, 2 clipped (75 %, 41 %), 2 wholly outside; after `Fit`, 6 of 6
inside at scale 0.376, card 90 px, title **5.64 px**.

The fix that closed the round-3 sentence — the `N off-pane · Fit` chip
(`b981916`) — is one of the two answers the row itself named, and it works: the
count is honest and the button does what it says. But it hands the author a
second unusable state rather than a usable one, because nothing bounds the fit
from below. Flowise pins `minZoom: 0.5` on the v2 canvas
(`agentflowsv2/Canvas.jsx:720-821`) precisely so this cannot happen.

**Fix:** clamp the fit at the declared 11 px floor and let the chip stay lit
(the graph does not fit, and saying so is honest), or give the minimap a
draggable viewport rectangle so the off-pane part is navigable without zooming
out of legibility.

### P-04 — the library calls a published document a draft
**dim 4 · ours 8 · ref 7 · Δ0 (a regression risk, not a reference gap)**

Measured end to end on `ug_5e8f562b` (v1 published, head v2 saved):

```text
GET /api/workflows                     lists ug_5e8f562b   (launchable)
GET /api/workflows/ug_5e8f562b/graph   200
GET /api/builder/workflows/{id}/versions   v2 draft · v1 PUBLISHED
GET /api/builder/workflows             status: "draft"          <-- server
gallery row (1440×900, y147–214)       "Sequential pipeline draft v2 2 min ago"
```

The summary `status` is derived from **head**, so a document whose live version
is behind head is indistinguishable in the gallery from one that was never
published — while it is answering runs. This is D-15-23's family one layer up:
D-15-23 made the *version rows* honest and left the *document summary* wrong.
The gallery is the only place an author sees all their graphs.

**Fix:** carry a second badge (`v1 live`) on the summary, or make `status` a
pair.

### P-05 — the canvas stops saying a version is live once head moves past it
**dim 4 · ours 8 · ref 7**

Same document, document bar text extracted at 1440×900:

```text
head == published (v1)   "Sequential pipeline · saved · v1 · v1 is live · Republish"
head == v2, v1 live      "Sequential pipeline · saved · v2 · Publish"
```

The `v1 is live` chip disappears exactly when it starts mattering. The only
remaining evidence on the canvas is that the `⋮` menu offers `Unpublish`. An
author editing v2 has nothing telling them a different version is serving
traffic.

### P-06 — edge strokes go sub-pixel at the zoom the product itself chooses
**dim 5 · ours 8 · ref 8 · Δ0**

`builder-edge-path` computed `stroke-width: 1.5px`, `opacity: 0.75`. Rendered
width is `1.5 × scale`:

| state | scale | rendered stroke |
| --- | ---: | ---: |
| validator template on open | 0.733 | **1.10 px** |
| after `Fit` | 0.436 | **0.65 px** |
| sequential + Versions, after `Fit` | 0.376 | **0.56 px** |

At 0.75 opacity a 0.56 px stroke is a grey suggestion. Flowise v2 draws 2 px
unselected at `opacity .75` and refuses to go below 0.5 zoom, so its worst case
is 1.0 px. Visible in `jr-validator-fit.png`: the 22 edges of the flagship
template are barely present.

**Fix:** `vector-effect: non-scaling-stroke` on the visible path, or a
scale-compensated width.

### P-07 — the minimap covers the node you just placed
**dim 5 · ours 8 · ref 8**

Measured on a three-node blank canvas at 1440×900: the minimap is
`position: absolute`, `z-index: 30`, 186×158 px at **x902–1088, y558–716**, and
covers **30.2 %** of `agent_1` — including its model pill and its `2 iter · no
tools` line. It is open by default, does not dodge, and has only a close button.
On the validator template it lands on `Validation report`.

**Fix:** dodge on overlap, or fade to ~20 % opacity until hovered.

### P-08 — a completed run reports 00:00 elapsed, 0 calls, 0 tokens, $0.0000
**dim 12 · ours 7 · ref 10 · Δ3** *(also dim 13)*

Measured live, run `7e2bb81d-edf2-4e6d-8eee-ae8106f9b0aa`, status `completed`,
1440×900 dark:

```text
console STATUS panel      ELAPSED 00:00   CALLS 0   TOKENS 0   COST $0.0000
dialogue rail, same view  Synthesist 640 in · 78 out   Reporter 640 in · 68 out
seq cursor                seq 65, 0 dropped
GET /api/runs?limit=1     created_at   2026-09-04T15:01:42.599
                          completed_at 2026-09-04T15:01:57.618      = 15.019 s
```

**The elapsed half is not a synthetic artefact.** The server holds both
timestamps and the panel renders `00:00` anyway; nothing about elapsed depends
on model usage. The token and cost half cannot be separated from `SYNTHETIC=1`
here, and that is the second half of the defect: the only free path anybody can
exercise leaves the console's entire spend surface untestable, which is exactly
the divergent-double failure closed items 15 and 33 were written about.

The same panel is what an operator watches while a graph somebody else drew
spends against `MAX_RUN_COST_USD`.

**Fix:** compute elapsed from the run record, and have the synthetic runner emit
usage frames with plausible non-zero counts so the panel is exercisable at zero
cost.

### P-09 — one easing curve departs from the reference the criterion says it quotes
**dim 8 · ours 8 · ref 8 · Δ0**

Measured live on `.workflow-node.is-running.is-agent`:

```text
ours       animation: node-glowing 4s linear infinite, node-pulse 2s ease-in-out infinite
reference  animation: node-glowing 4s linear infinite, node-pulse 2s ease-out    infinite
           (vueflow.css:81-125, quoted in docs/chatdev-notes.md §2)
```

Names, periods and the dual-period intent match; the second timing function does
not. Rubric 8 is *"the reference's curves and periods, quoted in
`docs/chatdev-notes.md` §2"*. Either change it back or amend the criterion to
say the departure is deliberate and why.

Beside it: node opacity mid-run resolves to **{0.55, 0.6, 1.0}** where plan 11
criterion 3's evidence names two levels (`idle 0.55, waiting 1.0`).

### P-10 — the CI guard that proves the two-writer job has never run in CI
**dim 11 · ours 9 · ref 10 · Δ1**

D-15-32's fix is real and was re-measured (bare `unittest` exit 0 over five
skips; `scripts/run_without_skips.py` exit 1). But `.github/workflows/ci.yml:95`
remains `if: github.ref == 'refs/heads/main'` by PLANS.md decision 25, so
neither the guard step nor the shim has executed in CI on any branch — both are
proved on one Windows machine only. Not held against the row, because the
`main`-only trigger is a ruling; recorded because "the guard exists" and "the
guard has run" are different sentences and this repository keeps discovering the
difference.

### P-11 — `PLANS.md` is 85 commits stale and understates progress by ≥33 criteria
**dim 16 · ours 4 · ref 10 · Δ6**

Full measurement in dimension 16 above. Headline: `PLANS.md` last changed at
`5562bd6`, 85 commits ago; plans 11, 12 and 13 read `Planned · 0 ticked` while
their own files claim 14/15, 8/10 and 11/11; the published **123 / 179** should
be **≥ 156 / 179**; and the tick cell has at least five incompatible shapes
across the sixteen plans, so no command can regenerate the column.

**Fix:** one token per criterion row (`met` / `partial` / `not reached`) and a
test that regenerates `PLANS.md`'s three numeric columns from the plan files and
fails on drift — the technique plan 01 criterion 6 already uses on itself.

---

## What could not be measured, and why

- **Three successful connect gestures at 50 / 100 / 150 %** (dimension 3). Port
  geometry and the validity projection were measured; the gesture was left to
  `e2e/builder.spec.ts`. A hand-driven drag at three zooms is the one thing that
  would settle it.
- **The paid half of dimension 15** — four template runs against real models
  (decision 22) — and any paid run of a user-authored graph. Out of scope by
  MISSION §12 and §7.
- **A blind comparison.** Structural, disclosed above; nothing in this harness
  provides an evaluator that does not auto-load this repository's own docs.
- **Reference captures.** `D:\Flowise-main` and `D:\ChatDev-main` were not run;
  every reference figure comes from `docs/flowise-notes.md` and
  `docs/chatdev-notes.md`, which are readings of those products' source.
- **PostgreSQL two-writer concurrency** was not re-run this round; MISSION §8
  records 5/5 on PG 18.6 on 2026-09-04 and P-10 is about the CI half of it.
- **Whether the token/cost half of P-08 is a console defect or a synthetic-mode
  property.** The elapsed half is settled; separating the other two needs a paid
  run.

## Spend

**$0.00.** Backend on 8092 in `SYNTHETIC=1` throughout; no `E2E_BASE_URL`; no
`mcp__openrouter__send-message`; no paid model called by anything in this round.
