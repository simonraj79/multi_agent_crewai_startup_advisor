# 04 · Manager — *superseded, kept as a comparison*

**Pattern 4 — Supervisor / Orchestrator-Workers** (`patterns.md` §5). The obvious
next step once a sequential crew runs: put a manager over the workers and let it
decide who works next.

> ⚠️ **Naming trap: `Process.hierarchical` is Pattern 4, NOT Pattern 5.**
> CrewAI spells the supervisor pattern `Process.hierarchical` — sequential is the
> pipeline, hierarchical is the supervisor. **Pattern 5** in this repository's
> vocabulary is *also* called *Hierarchical* but means something different —
> nested teams, supervisors of supervisors, a CEO → CTO/CMO → workers tree.
> Building this file gives you **Pattern 4**. Saying "we used Pattern 5,
> hierarchical" is wrong, and the word collision is why people say it.
> `patterns.md` §6 is the full argument.

The **Orchestrator** in this repository's role decomposition: it may read the
task, delegate, and synthesise the final answer; it may not search, calculate,
write, or critique. Structurally it is also the bottleneck — every hand-off
passes through it, so it is both the coordination cost and the single point of
failure. See `workflow.md` §4.

> **Agent contract** — **Role · Tools · Inputs · Outputs · Guardrail**
> (`workflow.md` §4). **Guardrail** here is a prompt-level "must NOT do", not
> CrewAI's `guardrail:` field.

| Field | Value |
|---|---|
| **Role** | Editorial Manager accountable for the quality of the `{topic}` brief |
| **Tools** | **none — and this is enforced.** `_create_manager_agent()` raises if the manager has tools. See gotcha 4. |
| **Inputs** | `{topic}`, plus each worker's output as it is returned. It does **not** receive a `context:` list — under `Process.hierarchical` the manager assembles context itself by delegating. |
| **Outputs** | Delegation decisions (which worker, what instruction), rejections with a concrete reason, and the final synthesised brief returned as the crew's output. |
| **Guardrail** | Never send work back with "improve this" — always a specific reason. Do not do the work itself. Must NOT appear in `agents=[...]`; it goes in `manager_agent=`. |
| **State** | Owns the run's control flow. Owns no data. |

> ## ⚠️ Superseded under Track B
>
> This crew now has exactly one genuinely dynamic decision — cache hit versus
> miss — and a Flow `@router` makes it deterministically for **zero LLM calls**
> (`07-deployment.md`). A Manager agent would make the identical binary decision
> and charge one LLM call per run to do it.
>
> That turns this file from a stretch goal into something more useful: a
> concrete, measurable comparison between LLM-decided routing and code-decided
> routing, on the same decision. Build it only to answer *keep it or drop it*
> with two traces and a call count — which is a stronger result than a working
> manager.

Read on for what it would take, and what it would cost.

---

## What actually changes

| | Sequential (baseline) | Hierarchical (this) |
|---|---|---|
| Order of work | Fixed: Researcher → Analyst → Writer, every time | Manager decides who works next, per run |
| Task assignment | `agent:` on each task | Manager assigns; `agent:` optional |
| Rejection | None — output flows on regardless | Manager can send work back |
| Trace shape | A straight line | Delegation and review, branching |
| Cost | Baseline | Noticeably higher — manager reasoning on top of every step |

> A sequential crew runs the same steps in the same order every time, whatever
> the topic. That is the limitation this fixes, and the only reason to pay for
> it.

---

## Identity

```yaml
manager:
  role: >
    Editorial Manager accountable for the quality of the {topic} brief
  goal: >
    Get a sourced, decision-ready one-page brief out of the team by assigning
    work to the right specialist and sending back anything that is not good
    enough. Reject weak work rather than passing it along and hoping the next
    person compensates.
  backstory: >
    You run a small research desk and you are the last line before anything goes
    out with your name on it. You know your three specialists well: the
    researcher gathers but will not commit to a view, the analyst has judgement
    but no way to check a fact, the writer makes anything read well including
    things that should not have been written. Your job is to sequence them and
    to catch the specific failure each is prone to. You send work back with a
    concrete reason - never "improve this". You would rather run one extra
    round than sign off on an unsourced claim.
```

---

## Configuration

| Setting | Value |
|---|---|
| `llm` | `openrouter/google/gemini-3.8-flash` |
| `tools` | *(none — the manager delegates, it does not do the work)* |
| `allow_delegation` | **`True`** *(set anyway — see below)* |
| `max_iter` | `20` |
| `max_execution_time` | `600` *(deliberate deviation from the crew's 300s)* |
| `verbose` | `True` |

> **Escalation tier: `gemini-3.8-flash` since 2026-09-04** (`f19a2c6`) — same
> $0.75 / $3.75 as the `gemini-3.7-flash` it replaced. This agent is retired
> and unbuilt, so the row above is the spec's assignment, not a running
> configuration.

`allow_delegation=True` is **redundant but worth writing**: `_create_manager_agent()`
forces `self.manager_agent.allow_delegation = True` regardless of what you set.
Stating it keeps the spec self-documenting; just don't expect setting it `False`
to have any effect.

`max_execution_time` is doubled to 600s because delegation adds round-trips —
the manager reasons, a worker runs, the manager reviews. The crew-wide 300s in
`00-shared-config.md` is sized for a single worker turn.

### Crew wiring

```
agents        = [researcher, analyst, writer]   # manager NOT in this list
tasks         = [research_task, analysis_task, writing_task]
process       = Process.hierarchical
manager_agent = manager
verbose       = True
```

### Four gotchas, in the order people hit them

1. **`Process.hierarchical` requires either `manager_agent` or `manager_llm`.**
   Set neither and `Crew.check_manager_llm` raises
   `"Attribute 'manager_llm' or 'manager_agent' is required when using
   hierarchical process."` Forget the manager and it breaks at construction.
2. **The manager goes in `manager_agent=`, not in `agents=[...]`.** This is
   enforced, not merely advised — putting it in both raises a
   `manager_agent_in_agents` validation error. It is not a crew member, it is
   the layer above them.
3. **Every specialist keeps `allow_delegation=False`.** If workers can also
   delegate, they delegate to each other and the run loops until it burns
   `max_iter`. Exactly one agent in the crew delegates.
4. **The manager may not have tools — enforced, not advisory.**
   `_create_manager_agent()` (`crew.py:1522-1532`) logs a warning, clears
   `manager.tools`, then raises `Exception("Manager agent should not have
   tools")`. The `tools: (none)` row above is a hard constraint, not taste.

**Simpler alternative:** if you only want dynamic assignment and do not need a
manager *persona*, skip this file and set `manager_llm` on the crew instead.
CrewAI synthesises a default manager. You lose the tailored backstory - which is
most of the value here, since it is what makes the manager catch the specific
failure each worker is prone to.

---

## Tasks under hierarchical

The three task specs in `01`–`03` carry over unchanged, with two adjustments:

> ⚠️ **This conflicts with `05-evaluator.md`.** Drop `agent:` *and* keep `05`'s
> Option A **string** guardrail on `writing_task`, and the crew fails at
> construction: `task.py:421-424` raises `ValueError("Agent is required to use
> non-programmatic guardrails")` when a string guardrail is present and
> `task.agent is None`. Pick one — keep `agent:` on `writing_task`, or make that
> guardrail a **callable**. A function guardrail carries no such requirement,
> which is one more reason to prefer it.

- **`agent:` becomes optional.** The manager assigns work. Leaving the
  assignments in constrains it toward the sequential order — useful for a first
  run, worth removing once to see what it does with a free hand. Removing them
  is the point of the exercise.
- **`context:` becomes load-bearing.** Sequential passed prior outputs
  implicitly. Hierarchical does not guarantee ordering, so the explicit
  `context` lines you kept in `02` and `03` are now the actual data flow. This
  is why those files told you to keep them.

---

## What to look for in the trace

This is the deliverable. Re-run, read the new trace, and it shows delegation and
review rather than a fixed line.

- **Delegation calls.** The manager choosing a worker, with its stated reason.
  Not present anywhere in the sequential trace.
- **A rejection.** The single most informative thing this pattern produces, and
  the one capability `Process.sequential` cannot express at all.
- **Re-runs.** A worker doing the same task twice with different instructions.
- **The call count.** Compare against your sequential run. The gap is the
  coordination tax, measured on your own topic rather than taken on faith.

---

## Honest assessment

For a three-stage pipeline whose stages genuinely are fixed — you always
research before analysing, always analyse before writing — the manager is
**overhead without a job**. There is no routing decision to make. The supervisor
pattern earns its cost when the supervisor dynamically picks the next worker;
here there is nothing to pick.

Build it anyway, because:

- **The rejection capability is real.** Sequential has no mechanism to send work
  back. That is a genuine capability gain, not a reshuffle.
- **The cost delta is the lesson.** You will pay noticeably more for
  approximately the same brief. Nothing in this repository quantifies the
  hierarchical premium: `patterns.md` §11 reasons about it structurally — the
  manager reasons before and after every step — but puts no number on it, and
  the measured figures in `agents/README.md` are Track A versus Track B, not
  sequential versus hierarchical. The actual delta is what you measure.

Then answer *would you keep it* with evidence. For this crew the defensible
answer is almost certainly no, and being able to say so with two traces and a
call count is a stronger result than a working manager.
