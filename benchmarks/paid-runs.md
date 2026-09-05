# Paid template runs — plan 14, criterion 9

**2026-09-05.** One paid run of every gallery pattern template against real
OpenRouter, on a local **paid** backend — no `SYNTHETIC` variable, `/docs`
answering 404, which is the check that proves it. This is the file plan 14
criterion 9 names, and it did not exist until now.

**The evidence is committed beside this file**, one
`benchmarks/live/2026-09-05-<template>.json` per run, each carrying the whole
frame stream, the run's own usage row, the document and run ids, the citation
check and the verbatim result body. Nothing on this page is retyped from memory;
every figure came out of `GET /api/runs/{id}` or out of the OpenRouter credits
endpoint.

```text
backend   PORT=8097  BUILDER_ALLOW_GATELESS_GRAPHS=1  BUILDER_PLATFORM_FIRECRAWL_DEFAULT=1
          RUN_RATE_LIMIT_MAX_RUNS=100  CREWAI_TRACING_ENABLED=false
          PYTHONPATH=D:\MultiAgentSystem-wt\s1-15-api\src   (no SYNTHETIC)
proof     GET /readyz -> ok, storage sqlite;  GET /docs -> 404
models    cheap  openrouter/google/gemini-3.5-flash-lite:nitro
          escal. openrouter/google/gemini-3.8-flash
```

## The five runs

Every row is one run. `static` is what `POST /api/builder/validate` answered for
that exact document at run time — not the fixture's copy, though the two agree.
`cost_usd` is what the service computed from its own `PRICES` table. The
right-hand column is the thing criterion 9 is actually about: **the estimate must
exceed the measured cost.** It does, by between 18x and 730x.

| template | run id | status | elapsed | prompt / completion | calls | `cost_usd` | static | measured / static | gates |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `news-to-social` | `e32a7914` | **completed** | 33.0 s | 2,558 / 4,445 | 3 | $0.017323 | $0.4284 | **4.04 %** | 0 (ungated by design) |
| `sequential-pipeline` | `eac19d14` | **completed** | 42.7 s | 2,849 / 3,639 | 5 | $0.013944 | $0.6597 | **2.11 %** | 1 approve |
| `conditional-router` | `eb837836` | **completed** | 8.7 s | 521 / 515 | 2 | $0.000840 | $0.6116 | **0.14 %** | 1 approve |
| `reflection-loop` | `4ec8bfd5` | **completed** | 11.4 s | 1,746 / 635 | 4 | $0.002111 | $1.5384 | **0.14 %** | 1 approve |
| `hierarchical-delegation` | `877f393f` | **completed** | 60.9 s | 10,956 / 6,207 | 11 | $0.029346 | $0.5235 | **5.61 %** | 1 approve |
| `sequential-pipeline` (first attempt) | `a9887442` | **failed** | 53.4 s | 5,022 / 328 | 9 | $0.002327 | $0.6597 | 0.35 % | 1 approve |
| **six runs, summed** | | | | **24,652 / 15,769** | **34** | **$0.065893** | **$4.4213** | **1.49 %** | |

Document ids, frame totals and per-node usage are in the evidence files; the run
ids above are the first eight characters of the full uuid each file carries.

### Spend, measured twice and agreeing

| | |
| --- | --- |
| balance before | **$27.451601** (`total_usage` 92.548398535) |
| balance after | **$27.385659** (`total_usage` 92.614340525) |
| **real spend** | **$0.065942** |
| sum of the six `cost_usd` rows | **$0.065893** |
| difference | **$0.000049** |

*The "after" row is the SETTLED reading, taken 49 minutes after the last run and
confirmed unchanged twice. An earlier read at $27.385711 was $0.000052 short:
OpenRouter's credits endpoint lags a completion by minutes, which is why the
balance is read at the end and not run by run. Every intermediate reading this
session was low, never high.*

**That is the interesting number on this page.** `cost_usd` is tokens x a local
price table, and CLAUDE.md has said for months that it is therefore an estimate,
because OpenRouter's own per-generation cost "never reaches the process".
Measured against OpenRouter's own accounting across six runs, three models and
40,421 tokens, the arithmetic lands within **$0.000049** — $0.0659 either
way.

The `NITRO_PRICE_FACTOR` worry — that `:nitro` routes on speed and may bill above
the published floor — did **not** materialise on any of these runs. That is a
statement about these six and not a guarantee: the endpoint spread is real
(`docs/tech-stack.md` measured 3.6x across eight endpoints for one model), and a
run that routed to `priority` would move this. What is now established is that
the computation itself is correct, which was the open half.

### Static estimates are ~60x the truth, and that is by construction

The worst case for the five templates is **$3.7615**; they cost **$0.0636**
between them — **1.7 %**. The paid acceptance run measured 2.8 % on the
validator, so this is the second data point for that ratio and it is the same
order.

The estimate prices every node as if every guardrail retried, every tool loop ran
to `max_iter` and every cycle went round three times. `reflection-loop` is the
clearest case: priced at **$1.5384** for four laps of two agents, it went round
**twice** and cost **$0.002111** — 0.14 %. `conditional-router` prices all three
desks although exactly one runs, and exactly one ran.

**None of this argues for lowering the margin.** The bound exists to refuse a
graph that *could* reach the ceiling, and the run that goes to the cap is the one
it is written for. What these runs settle is that the ceiling is nowhere near
binding for a template-shaped graph.

## The verification run — `max_iter` 3 → 6, 2026-09-05

One further paid run, after defects 2 and 3 were repaired. Same backend recipe
as above (`PORT=8097`, no `SYNTHETIC`, `/docs` → **404**), same subject, same
template — a **different document**, because `news-to-social`'s researcher now
carries `max_iter: 6`. It is a verification, not a second sample of the sweep.

| template | run id | status | elapsed | prompt / completion | calls | `cost_usd` | static | measured / static | gates |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `news-to-social` (`max_iter: 6`) | `d69c6986` | **completed** | 31.8 s | 2,835 / 4,579 | 3 | $0.017892 | $0.6103 | **2.93 %** | 0 (ungated by design) |

Per node: `research` on `gemini-3.5-flash-lite:nitro`, **2 calls**, $0.0014868;
`write` on `gemini-3.8-flash`, 1 call, $0.0164055. Evidence:
[`live/2026-09-05-news-to-social-maxiter6.json`](live/2026-09-05-news-to-social-maxiter6.json).

**No `max_iter` exhaustion occurred, and that is a measurement rather than a
grep.** `research` is the only tool-using node in the graph and its cap is now
6; its usage row records **2 calls**, and exhaustion requires
`iterations >= max_iter`. The serve log's *"Maximum iterations reached"* line is
**not** evidence either way here — `handle_max_iterations_exceeded` prints it
only when the agent is verbose, and an authored agent is not.

**So this run does not exercise the nudge**, and saying otherwise would be the
kind of claim this page exists to refuse. What it establishes is the other half:
the raised cap still runs, still completes, and still costs cents — $0.0179
against a $0.6103 worst case, **2.93 %**, the same order as the 1.49 % the six
runs above measured and the 2.8 % the acceptance run did. The nudge itself is
proved red-then-green by `tests/builder/test_max_iter_nudge.py`, against a
scripted LLM double that records the role of the last message at the call, with
four guard tests that fail naming the CrewAI symbol the day it moves.

Defect 3 is not exercised here either: `news-to-social` is the one gallery
template with no gate. It is proved by
`tests/builder/test_gates.py::RouteGateTests` and `DurableGateTests` through the
real engine, and `hierarchical-delegation` — the template that met it for money —
has not been re-run for money since.

**Spend: $0.017892 by the service**, which takes the programme's recorded total
to **$0.125492** of the $5.00 allowance ($0.0417 acceptance + $0.065893 template
sweep + this).

| | |
| --- | --- |
| balance before | **$27.385625** (`total_usage` 92.614374845) |
| balance after | **$27.367552** (`total_usage` 92.632447785) |
| **real spend** | **$0.018073** |
| the service's own `cost_usd` | **$0.017892** |
| difference | **$0.000181** |

The "after" row was read ~10 minutes past the run and confirmed unchanged twice;
an intermediate read four minutes in said $0.001656, which is the lag the
section above documents. **The difference is 1.0 % and it is larger than the
sweep's**, which agreed to $0.000049 over six runs — one run, one endpoint, and
the obvious candidate is `:nitro` routing the cheap-tier calls above the
published floor, which `NITRO_PRICE_FACTOR` exists for. One sample is not a
finding; it is a thing to watch on the next paid run.

## The verification run — the gate payload, 2026-09-05

The other half of the previous section's closing paragraph. It said defect 3
*"is not exercised here"* and that `hierarchical-delegation` — the template that
met it for money — *"has not been re-run for money since"*. It has now.

Same backend recipe (`PORT=8097`, no `SYNTHETIC`, `/docs` → **404**), same
template, same saved input, same `approve` at the same gate. Against
`main` = **`847f282`**, where `route_gate` records the decision under
`decision__<gate>` and `out__<gate>` keeps the payload the operator was shown.

| template | run id | status | elapsed | prompt / completion | calls | `cost_usd` | static | measured / static | gates |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `hierarchical-delegation` | `d1fdeea6` | **completed** | 54.5 s | 7,231 / 4,886 | 9 | $0.022287 | $0.5235 | **4.26 %** | 1 approve |

Per node, both on `team` because the members are priced inside the crew:
`gemini-3.5-flash-lite:nitro` 3 calls $0.0022559, `gemini-3.8-flash` 6 calls
$0.020031. Evidence:
[`live/2026-09-05-hierarchical-delegation-decision-ns.json`](live/2026-09-05-hierarchical-delegation-decision-ns.json),
which carries the full flow state, all 149 frames and all three checks.

### The three checks, from the run rather than from the diff

**(a) The two state keys are separate.** `GET /api/runs/d1fdeea6…/state`:

```json
"out__confirm":      "{\"summary\": \"Plan the launch of a keyboard-first task manager for engineering teams.\"}",
"decision__confirm": {"decision": "approve", "honoured": false, "turns_used": 0}
```

The payload is where a downstream node reads it and the decision is beside it,
not on top of it. On 2026-09-05 before the fix, `out__confirm` **was** that
second object.

**(b) The specialists are briefed on the payload.** The three declared tasks, as
CrewAI interpolated them — these are the exact strings that were
`{'decision': 'approve', 'honoured': False, 'turns_used': 0}` last time:

```text
Size the market for {"summary": "Plan the launch of a keyboard-first task manager for engineering teams."} and name the buyer.
Define the v1 scope for {"summary": "Plan the launch of a keyboard-first task manager for engineering teams."} in five bullets.
List the three ways {"summary": "Plan the launch of a keyboard-first task manager for engineering teams."} fails, and the early …
```

Six task names appear in the frame stream; the other three are the hierarchical
manager's own delegation prose and carry no interpolation, so the check that
holds of **all six** is the negative one: **no task name carries the decision
dict.** The manager's delegation context is on topic too — it briefs the Market
Specialist on *"a keyboard-first task manager for engineering teams (similar in
ethos to Linear)"*.

**(c) The body is on topic.** 1,219 characters about command-palette hotkeys,
Markdown-only interfaces rejected by PMs and designers, bi-directional GitHub
webhook races and multi-seat provisioning. The previous run's body, at a dearer
$0.029346, was about counterparty default and AML screening.

### Spend

| | |
| --- | --- |
| balance before | **$27.367552** (`total_usage` 92.632447785) |
| balance after | **$27.345242** (`total_usage` 92.654757565) |
| **real spend** | **$0.022310** |
| the service's own `cost_usd` | **$0.022287** |
| difference | **$0.000023** |

Read three minutes past the run and confirmed unchanged three times. **The
difference is 0.10 %**, back in line with the sweep's $0.000049 over six runs and
an order tighter than the previous section's 1.0 %. That does not resolve the
`:nitro` question either — it is a second single sample, and the honest reading
is that one run's difference is noise in both directions.

Programme total: **$0.148038** of the $5.00 allowance — MISSION.md §7 owns
that figure and its four rows.

### What is still off topic, and it is not the gate

Two residuals, neither of them defect 3 and neither of them new:

- ~~**The payload reaches the prompt as its JSON envelope**, not as prose — the
  task literally reads `Size the market for {"summary": "…"} and name the
  buyer.` Every model handled it and every output is on topic, so this costs
  nothing today; it is a shape nobody chose, and the first author who writes a
  gate whose payload has three keys will find out what it renders as.~~
  **FIXED and verified for money — the next section.** Run `5556ec33` on the
  same template with the same input reads
  `Size the market for Plan the launch of a keyboard-first task manager for
  engineering teams. and name the buyer.`
- **The crew node's result is the LAST task's output**, so the deliverable is
  the Risk specialist's three failure modes and not a synthesis of market,
  product and risk. That is `CrewOutput.raw`'s semantics, it was recorded as a
  separate observation when the sweep ran, and it is unchanged. A template that
  wants a synthesis needs a node that writes one.

## The verification run — the gate payload as PROSE, 2026-09-05

The first residual the section above names, closed. It said the payload reaches
the prompt *"as its JSON envelope, not as prose"*, that every model handled it
anyway, and that *"the first author who writes a gate whose payload has three
keys will find out what it renders as"*. They will not.

`runtime.state_ref_text` renders a JSON OBJECT — a string that parses to one, or
a mapping — as prose at the ONE seam where a state reference becomes text a
model reads: `prompt_inputs`, for both arms of `run_agent` and both arms of
`run_crew`. A single-key object becomes its bare value, a multi-key object
becomes `key: value` lines in the payload's own order, a nested value is compact
JSON, and everything else — a plain string, a number, a list, a string that
merely LOOKS like JSON — is returned as the SAME object.

**`out__<gate>` is unchanged, and that is the design rather than an omission.**
Replay, the State tab, the export and `gate_payload` all read the stored form
and all of them want the object back; `route_branch` compares `state.get(key)`
against a literal and a router that started comparing prose would answer
differently for the same document; and `emit_output` writes a deliverable a
client parses. Three of those four are pinned by a negative test in
`tests/builder/test_prompt_interpolation.py` (23 tests).

Same backend recipe (`PORT=8097`, no `SYNTHETIC`, `/docs` → **404**), same
template, same saved input, same `approve` at the same gate. Against
`wd/payload-prose` = **`6233ad0`**.

| template | run id | status | elapsed | prompt / completion | calls | `cost_usd` | static | measured / static | gates |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `hierarchical-delegation` | `5556ec33` | **completed** | 55.0 s | 6,808 / 4,579 | 9 | $0.020923 | $0.5235 | **4.00 %** | 1 approve |

Per node, both on `team` because the members are priced inside the crew:
`gemini-3.5-flash-lite:nitro` 3 calls $0.0021148; `gemini-3.8-flash` 6 calls
$0.0188078. Evidence:
[`live/2026-09-05-hierarchical-delegation-prose.json`](live/2026-09-05-hierarchical-delegation-prose.json),
which carries all 151 frames, the full flow state and the checks below.

### The three task names, read out of the frames

These are the exact strings CrewAI interpolated, taken from the `task_name` on
this run's own `agent` and `llm` frames. The previous run's are quoted two
sections above; the difference is the whole change.

```text
Size the market for Plan the launch of a keyboard-first task manager for engineering teams. and name the buyer.
Define the v1 scope for Plan the launch of a keyboard-first task manager for engineering teams. in five bullets.
List the three ways Plan the launch of a keyboard-first task manager for engineering teams. fails, and the early signal for each
```

*(The third is cut at the frame's own preview bound, exactly as the earlier
run's third was.)* Six distinct task names appear across the stream — those
three and the hierarchical manager's own delegation prose — and **none of the
six carries a JSON envelope**, which is the check the evidence file computes
rather than a reading of the list.

**And the store did not move.** From `GET /api/runs/5556ec33…/state`:

```json
"out__confirm":      "{\"summary\": \"Plan the launch of a keyboard-first task manager for engineering teams.\"}",
"decision__confirm": {"decision": "approve", "honoured": false, "turns_used": 0}
```

Byte-identical to run `d1fdeea6`'s. The rendering is the reader's and the
stored payload is still the object a form can be built from.

**The body is on topic**: 1,311 characters on command-palette adoption among
non-power users, GitHub webhook latency corrupting cycle-time metrics, and
multi-seat provisioning — the same subject as `d1fdeea6`'s, which is what says
this changed the prompt's shape and not its subject.

**One limitation, stated because it is not obvious.** CrewAI renders a whole
`with:` block, so a reference EMBEDDED in a longer string —
`task.description: "work from ${state.out__draft}"` — is already spliced into
that sentence before any entrypoint is called, and there is no seam left at
which the reference can be told from the prose around it. The shape that works,
and the one every gallery template uses, is a `prompt_inputs` value that is
exactly one reference, read by a `{name}` placeholder in the prompt.

### Spend

| | |
| --- | --- |
| balance before | **$27.254979** (`total_usage` 92.745020765) |
| the service's own `cost_usd` | **$0.020923** |

The settled balance is read after the `max_iter` verification run that followed
this one back to back: only the PAIR was bracketed, so the delta for both is
recorded with that run rather than split between them on a guess.

## What each run's OUTPUT actually did

The table above says the runs completed. This says whether they did the job,
which is a different question and the one worth the money.

| template | verdict on the output |
| --- | --- |
| `news-to-social` | **Did its job.** Four real Hacker News stories, four correct item URLs, both variants written to the prompt's shape. One liberty and one miss, below. |
| `sequential-pipeline` | **Did its job, minus its sources.** A 5,265-character brief with a headline and three sections, on topic and genuinely readable. But its sources list reads *"the source analysis did not carry external URLs"* — the URLs the researcher found do not survive `research -> analyse -> write`. |
| `conditional-router` | **Routed correctly.** "charged me twice … refund" classified `billing`; the billing desk answered and the other two never ran — 2 calls for the whole graph. The reply then invents an account history ($29.00 on 1 November 2023, a gateway timeout, a refund it says it has processed), which is what a support-desk prompt with no tools and no account data will do. |
| `reflection-loop` | **Looped.** `generate` ran twice and `critique` twice: the first draft scored under 8, the second passed, and the router took `done`. A decent 1,247-character PM explainer. The card's claim is accurate. |
| `hierarchical-delegation` | **Completed, and answered the wrong question.** Defect 3. The three specialists were briefed on a Python dict and wrote about credit default swaps. **Re-run for money at `847f282` and on topic** — the gate-payload section above. |

### The news post, verbatim

`news-to-social`, run `e32a7914-b88e-4171-8505-d9319cf65da6`, subject
*"AI agents and agentic workflows"*, 33 seconds, $0.017323, no gate.

```markdown
# Short

Agent frameworks tackling real production limits:
• Durable Swarm: https://news.ycombinator.com/item?id=41984257
• Agno: https://news.ycombinator.com/item?id=45714551
• Chatwoot: https://news.ycombinator.com/item?id=44433537
• Oqlous: https://news.ycombinator.com/item?id=43603324

# Long

Agent frameworks are shifting focus to solve gritty production bottlenecks like
server restarts, token bloat, and monolith integration. Developers can now lean
on Durable Swarm (https://news.ycombinator.com/item?id=41984257) for
interruption-proof execution, Agno (https://news.ycombinator.com/item?id=45714551)
for private, FastAPI-style step runtimes, and Chatwoot's thread-safe SDK
(https://news.ycombinator.com/item?id=44433537) for native execution inside Rails
monoliths. Meanwhile, Oqlous AI (https://news.ycombinator.com/item?id=43603324)
tackles Model Context Protocol constraints directly by cutting token
inefficiency and adding native UI support. #RubyOnRails
```

*(The bullet is U+2022 and the file is UTF-8. A terminal that renders it as a
replacement character is the terminal, not the body — checked by codepoint.)*

**Zero fabricated citations.** All four item ids were checked against the live
Hacker News item API, which is free and — for the reason two paragraphs down —
the only check available:

| id | HN title |
| --- | --- |
| 41984257 | Show HN: Durable Swarm — A Framework for Building Reliable AI Agents |
| 45714551 | Show HN: Agno — multi-agent framework, runtime and control plane |
| 44433537 | Show HN: AI Agents — Ruby SDK for building multi-agent AI workflows |
| 43603324 | Alternative of MCP with AI RAG Agentic Framework |

The tool reported `result_count: 4` and the post cites four. Three of the four
names are the story's own. **"Oqlous" is the writer's**: the story is titled
"Alternative of MCP with AI RAG Agentic Framework" and names no product, so that
one is a name asserted where the source gave none. And the researcher's prompt
asks for *"the last 7 days"*, which HN Algolia's relevance search does not
honour — item 41984257 is from 2024. Neither is a defect in the builder; both
are what this template's prompts currently produce, and both are the kind of
thing only a paid run shows.

**Citation closure is not answerable from the frame stream, and that is
structural.** A tool frame carries a bounded `output_preview` — `notes`,
`result_count`, `tool_status`, `output_chars` — and never the result rows, so
"every URL in the body appears in a tool result frame" cannot be evaluated
against this evidence for any template. Recorded because the alternative is a
citation check that reports "4 unbacked" and means "the frames do not carry
URLs". Each evidence file states this next to its own citation block.

## Four defects, every one of them found by spending money

None is visible to the 2,441-test Python suite, the 1,705 frontend tests or the
131 E2E tests, and the reason is the same in every case: the synthetic runner
never builds a `Crew`, never interpolates a prompt and never calls a provider.

### 1 — Every authored builder graph completed instantly, called no model, and returned an object's `repr`. FIXED.

The first paid run, `c5df456d-27e0-4e91-9309-e232aceaa5d2`, reported
**`completed` in 1.5 seconds** with `cost_usd 0.0`, zero tokens, zero
`successful_requests`, seventeen frames, a terminal `WORKFLOW_END`, and this as
the deliverable:

```json
"result": {"markdown_body": "<crewai.types.streaming.CrewStreamingOutput object at 0x0000026581AAC050>", "node_id": "post"}
```

Every node's `NODE_END` carried the same string, and each was handed to the next
node as its prompt input. A green run, a terminal status and a non-empty body —
which is exactly what `e2e/templates.spec.ts` asserts for criterion 7.

**Cause.** Every authored crew carries `Crew(stream=True)` (plan 10 D7,
`builder/runtime.py:677` and `:763`). CrewAI answers that with a **lazy**
`CrewStreamingOutput`: a generator over a worker thread that has not been started
(`crewai/crew.py::kickoff`, verified at 1.15.18). Nothing executes until somebody
iterates it, and `_as_text` fell through to `str(value)`.

**Fix.** `builder/runtime.py::_kickoff` — one helper, used at all four kickoff
sites — drains the iterator and returns `.result`. The drain is both halves: it
is what runs the crew, and it is what raises the per-token `LLMStreamChunkEvent`s
the dialogue rail exists to render. A library crew sets no `stream`, so its plain
`CrewOutput` is returned untouched.

Everything else on this page was measured **after** that fix.

### 2 — A tool-using agent that exhausts `max_iter` fails on Google, and the message shape is CrewAI's. FIXED.

> **Fixed 2026-09-05 in `98ba8e0`**, two layers. `builder/max_iter.py`
> registers one global `before_llm_call` hook that rewrites a trailing model
> turn as a user turn immediately before the request is sent — the seam
> CrewAI exposes, and the only one that works: `LLM.__new__` is a factory
> returning a native provider instance, so subclassing `LLM` is never
> instantiated. And the two tool-using researchers go `max_iter` 3 → 6, so
> the cap is reached less often. The paragraph below, *"Not fixed here"*,
> was true when it was written.


`sequential-pipeline`'s first attempt, run `a9887442-ff35-4da5-8974-52fa03e81a0f`:
**failed** after 9 calls and $0.002327, three times over, with

```text
Error code: 400 - Provider returned error
  Google / Google AI Studio:
  "Requests ending with a model turn are not supported."   INVALID_ARGUMENT
```

**Cause, read out of CrewAI rather than guessed.**
`crewai/utilities/agent_utils.py::handle_max_iterations_exceeded` appends an
**assistant** message and calls the LLM once more to force a final answer:

```python
messages.append(format_message_for_llm(assistant_message, role="assistant"))
answer = llm.call(messages, callbacks=callbacks)
```

Google's chat API refuses a request whose last message is a model turn. Both
tiers in this product are Google-served, so **any authored agent with tools that
runs its tool loop to the cap fails** — after the tool calls have already billed.

**It is intermittent, and that was measured rather than assumed.** The one
permitted retry, run `eac19d14`, **completed** on an identical document with an
identical input: the HN tool returned usable rows earlier that time, the agent
finished inside `max_iter`, and the extra call never happened. The trigger is
exhausting `max_iter`, not the template.

Not fixed here. It is a CrewAI/provider interaction, and choosing between "raise
`max_iter`", "move a tier off Google" and "post-process the message list" is a
decision rather than a repair.

### 3 — A node downstream of a gate reads the gate's REPLY METADATA, not the payload. `hierarchical-delegation` ships wired that way. FIXED.

> **Fixed 2026-09-05 in `8af20c2`**, by the second of the two repairs this
> entry names — the contract change, not the rewiring. The gate's paired
> router records under a reserved namespace of its own,
> `decision__<gate>`, and never writes `out__<gate>`; the one thing it may
> still put there is the operator's own edited payload. So
> `hierarchical-delegation` is left wired to `${state.out__confirm}` and
> that reference now means what its author meant. `10-runtime.md`'s Status
> carries the whole contract and its file list.

Run `877f393f`, input *"Plan the launch of a keyboard-first task manager for
engineering teams."* The task CrewAI actually ran was:

```text
Size the market for {'decision': 'approve', 'honoured': False, 'turns_used': 0} and name the buyer.
```

and the deliverable is three paragraphs about counterparty default, credit
default swap spreads and AML/sanctions screening. It cost **$0.029346** — the
dearest run on this page — and it `completed`, with a 1,129-character body that
satisfies every assertion criterion 7 makes.

**Cause.** A canvas gate compiles to two flow methods sharing one node id. Method
1 pauses and records the payload; method 2, `route_gate`
(`builder/runtime.py:2191`), records the decision and **runs second**:

```python
_record(flow, node_id, {"decision": decision, "honoured": honoured,
                        "turns_used": state.get(turns_key, used), **reply})
```

So `${state.out__<gate>}` is the reply metadata by the time anything downstream
reads it. The gate's own `NODE_END` frame shows the payload was there and was
then overwritten:

```text
seq 16  confirm NODE_END  HumanFeedbackResult(output='{"summary": "Plan the launch of a
        keyboard-first task manager for engineering teams."}', feedback='{"decision": "approve"}', …)
```

`hierarchical-delegation` is the only template that reads a gate:
`team.prompt_inputs = {"brief": "${state.out__confirm}"}`. Its own three members
read `${state.brief}`, and every other template reads `${state.<field>}` — which
is why this is the only one affected and why nothing caught it.

Two candidate repairs, and they are not equivalent: rewire the template to
`${state.brief}`, or stop the router clobbering the pause's output. The second is
a contract change. **Neither was made here**, because a paid-run session is not
where a contract moves.

> **FIXED on `main` = `847f282`, and verified for money on 2026-09-05.** The
> second repair was taken: the decision has its own `decision__<gate>` key and
> `out__<gate>` keeps the payload, so no template needed rewiring. Re-run
> `d1fdeea6` on the same template with the same input passes all three checks —
> the gate-payload section above.

### 4 — `sequential-pipeline` loses its sources between the analyst and the writer.

Not a crash, and visible only in the output. The brief's sources section says
*"the source analysis did not carry external URLs"*, and the body contains zero
links after a research step that fetched three HN threads. The analyst's prompt
asks for tensions and evidence; nothing in the chain requires it to carry a URL
forward. The writer then says so honestly, which is the good half.

## What this does not establish

- **Nothing here ran against the deployed origin.** All six runs are local,
  against `127.0.0.1:8097`.
- **`MAX_RUN_COST_USD` has still never fired on a paid run.** The dearest run
  here is $0.029 against a $10.00 ceiling, so the mid-flight `HookAborted` path
  remains proved by tests only.
- **The two library-agent templates and `idea-validator` were not run here.**
  `idea-validator`'s paid evidence is the 2026-09-04 acceptance run.
- **One run per template is one sample.** `sequential-pipeline` needed two
  attempts to produce one success, which is the sharpest available argument that
  a single green run is not a measurement of reliability.
