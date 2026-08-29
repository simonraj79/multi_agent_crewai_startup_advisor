# 05 · Evaluator — *stretch*

**Pattern 6 — Evaluator–Optimizer.** Slide 62: *"Add an evaluator gate: a fourth
agent that rejects any brief without sources. Pattern 6, in a few lines."*

> 🔨 **Option A is implemented; Option B is not.** `writing_task` carries
> `guardrails=[check_mechanics, ATTRIBUTION_GUARDRAIL]` with
> `guardrail_max_retries: 2`, in `src/brief_crew/guardrails.py`. There is no
> fourth agent, on this file's own recommendation.
>
> The cost split this file argues for is the reason there are two entries in that
> list. Checks 1 and 5 (sources present, length in range) are arithmetic and live
> in the **callable**, which costs nothing; checks 2 and 3 (attribution,
> faithfulness) need judgement and are all that is left in the **string**, which
> costs an LLM call on every evaluation. Ordering matters: the free check runs
> first.
>
> Note `guardrails` (plural) is used, not `guardrail` (singular) — setting both
> would null the singular field outright, as this file warns.
>
> Still open: the `run_scores` table and the four-axis quality scoring below.
> Cost is measured; quality is not.

Derived from slide 25's Human Swarm **Critic** — *CAN: approve or reject with a
written reason. CANNOT: search, calculate, or write.* See `workflow.md` §4.

> **Agent Spec Card** (slide 28) — describing **Option B**, the visible fourth
> agent. Note the file's *recommended* path is **Option A**, a task guardrail
> with no agent at all: it has no Role, no Tools and no persona, because it is a
> validator rather than a crew member. Read "Read this before you build it"
> before filling this card in.

| Field | Value |
|---|---|
| **Role** | Editorial Fact-Checker with sign-off authority over the `{topic}` brief |
| **Tools** | **none** — it checks faithfulness to the research it was given, not truth in the world |
| **Inputs** | `context: [research_task, analysis_task, writing_task]` — it must see the brief *and* everything the brief claims to rest on |
| **Outputs** | `VERDICT: PASS` or `FAIL`, a six-row checklist table with the offending sentence quoted on each failure, and a numbered list of required fixes. Under 250 words. |
| **Guardrail** | Judge only against the checklist — style, tone, structure and persuasiveness are out of scope. Do NOT rewrite, improve, or suggest wording. A brief that is honest about thin evidence is a PASS. |
| **State** | Reads only. Owns nothing. |

---

## Read this before you build it

Pattern 6 is a **loop**: generate → judge → regenerate on failure. The judging
is easy. The loop is the part that needs a decision, because
`Process.sequential` has no mechanism to send a task backwards.

You have three ways to close it. They differ enormously in cost and effort.

| Option | Closes the loop? | Cost | Effort |
|---|---|---|---|
| **A. Task guardrail** on `writing_task` | **Yes** — the task retries automatically | see below | Two lines |
| **B. Evaluator agent + review task** | **No** — produces a verdict, nothing acts on it | 1 extra call, always | An agent and a task |
| **C. Guardrail + evaluator agent** | Yes, with a visible verdict artifact | Both | Both |

**Start with A.** It is what "in a few lines" actually means, it is the only one
of the three that genuinely implements the pattern, and it is the cheapest. Add
B only if you want a separate reviewer persona to show in the trace.

### What a guardrail actually costs

This is worth getting right before you attach one, because the intuition is
wrong. A **string** guardrail is not a cheap check — `LLMGuardrail.__call__`
constructs a throwaway `Agent(role="Guardrail Agent")` and calls `.kickoff()`, so
**every evaluation is its own LLM call, whether it passes or fails.** And a
rejection re-runs the *entire task*, not just the validation.

At the default `guardrail_max_retries=3`, worst case for one brief:

```
4 × writing_task execution  +  4 × guardrail judgement call
```

The Writer runs on `gemini-3.7-flash` at $3.75/Mtok completion — the most
expensive completion rate in the crew — which makes a frequently-firing string
guardrail the costliest thing in it. Two consequences:

- Use `guardrail_max_retries: 2`, not the default 3.
- Put deterministic checks in a **function** guardrail — arithmetic like word
  count and "does a Sources section exist" costs nothing and needs no model.

⚠️ **Exhaustion raises.** When retries run out, `Task._invoke_guardrail_function`
(`task.py:1327` in 1.15.18 — *not* `_process_guardrail`, which does not exist) raises a
plain `Exception("Task failed guardrail validation after N retries...")`. There
is no best-effort passthrough — under `Process.sequential` the run dies. That is
defensible for a sourcing gate, but choose it knowingly.

⚠️ **`guardrails` (plural) overrides `guardrail` (singular).** Setting the list
nulls the single field outright — they do not combine. Pick one.

---

## Option A — task guardrail (recommended)

A guardrail runs against the task's output. If it fails, the agent gets the
failure message back and retries the same task. That is the evaluator–optimizer
loop, complete, with no fourth agent.

Attach to `writing_task` in `03-writer.md`:

```yaml
writing_task:
  # ... existing description and expected_output ...
  guardrail: >
    Reject the brief unless ALL of the following hold:
      1. It contains a Sources section with at least three distinct URLs.
      2. Every numeric claim and every named-entity claim in the body is
         attributable to a source in that list.
      3. It contains no fact absent from the research notes and analysis above.
      4. It is between 500 and 700 words.
    On rejection, state exactly which check failed and which specific claim or
    section caused it. Do not rewrite the brief yourself.
  guardrail_max_retries: 2
```

**Why `guardrail_max_retries: 2`** rather than the default 3. Each retry is a
full re-run of the writing task *plus* another judgement call. If two focused
attempts do not fix it, the defect is upstream — the Researcher did not return
sources, and no amount of rewriting at stage 3 conjures them. Failing fast
surfaces the real cause. Do not raise this to paper over a stage-1 problem.

**Mixing check types.** Checks 1 and 4 are mechanical — a deterministic function
guardrail does them for free, with no LLM call at all. Checks 2 and 3 require
judgement and need the model. Since `guardrails` accepts an ordered list mixing
callables and strings, the cheapest arrangement puts the function guardrail
first (count and length) and lets the string guardrail handle only attribution.
Given the cost figures above, this is worth doing rather than a nicety.

**Do not reach for the Agent-level guardrail.** `Agent` also has a `guardrail`
field, which looks like it would work here. It does not: it fires only on
standalone `agent.kickoff()`, never when that agent executes a task inside a
`Crew`. For this crew, Task-level is the only option.

---

## Option B — evaluator agent

Adds a visible fourth reviewer to the crew. Produces a verdict as a task output.
Understand clearly: **in sequential this does not gate anything.** It writes a
review that lands after the brief and changes nothing about the brief. It is a
demonstration of the reviewer role, not a functioning gate.

It becomes a genuine gate only under `Process.hierarchical` (`04-manager.md`),
where the manager can read the verdict and send the Writer back.

### Identity

```yaml
evaluator:
  role: >
    Editorial Fact-Checker with sign-off authority over the {topic} brief
  goal: >
    Pass or fail the brief against a fixed checklist, and when you fail it, say
    exactly which claim broke which rule. You are checking sourcing and
    faithfulness to the research, not style, tone, or whether you find the
    argument persuasive.
  backstory: >
    You have spent your career finding the one unsourced number in an otherwise
    clean document, and you have learned that the claim that slips through is
    almost always the most confident-sounding sentence on the page. You apply
    the checklist and nothing but the checklist - you have watched reviewers
    with opinions about wording let real errors past while arguing over a
    subheading. You quote the offending sentence verbatim so nobody has to guess
    what you meant. A pass from you means something because your fails are
    specific.
```

### Configuration

| Setting | Value |
|---|---|
| `llm` | `openrouter/z-ai/glm-5.3-flash` with the effort set to **`"minimal"`** — via `additional_params={"extra_body": {"reasoning": {"effort": "minimal"}}}`. The `LLM(reasoning_effort=...)` field is accepted and then silently dropped for non-o1 models in 1.15.18; see `00-shared-config.md` §3. |
| `tools` | *(none — it checks internal consistency, it does not re-research)* |
| `max_iter` | `5` |
| `max_execution_time` | `300` |
| `allow_delegation` | `False` |
| `verbose` | `True` |

**Why `reasoning_effort: "minimal"`.** `glm-5.3-flash` reasons by default and
reasoning bills at the completion rate — measured, 68 of 71 completion tokens on
a trivial prompt. This agent applies a fixed checklist; it has nothing to
deliberate about. Setting minimal effort measured **8.8× cheaper** on short
calls. This is the single largest cost lever in the crew, and it belongs here
more than anywhere else.

**Why the cheap tier.** This is a mechanical comparison against a fixed list, not
a judgement call. A gate that costs as much as the work it gates is not a gate.
At $0.075/$0.250 per Mtok, `glm-5.3-flash` is 10× cheaper on input than the
`gemini-3.7-flash` Writer it polices. If it produces sloppy verdicts, escalate to
`gemini-3.7-flash` — but measure first, because a gate that costs as much as the
Writer inverts the economics of having one.

**Why no tools.** Same logic as the Analyst. Its job is *faithfulness to the
research it was given*, not truth in the world. A URL that resolves is not the
test; a claim traceable to the notes is. Giving it search would let it validate
against sources the crew never saw, which is a different and much more expensive
job.

### Task — `evaluation_task`

```yaml
evaluation_task:
  description: >
    Audit the brief produced in the previous step against the research notes
    and analysis. Apply this checklist and nothing else:

      1. SOURCING - Does the brief carry a Sources section with at least three
         distinct URLs?
      2. ATTRIBUTION - Is every numeric claim and every named-entity claim in
         the body traceable to a listed source?
      3. FAITHFULNESS - Does the brief contain any fact, number, or example
         absent from the research notes and analysis?
      4. CONFIDENCE - If the analysis rated confidence Low or Medium, does the
         brief tell the reader that?
      5. LENGTH - Is it between 500 and 700 words?
      6. PROVENANCE - If any fact came from the cached corpus rather than a
         page scraped this run, does the brief say so rather than presenting
         it as freshly verified?

    For each check: PASS or FAIL. For every FAIL, quote the offending sentence
    verbatim and name the rule it broke.

    Constraints:
      - Judge only against the checklist. Style, tone, structure and how
        persuasive you find the argument are out of scope.
      - Do NOT rewrite, improve, or suggest wording. You return a verdict.
      - A brief that is honest about thin evidence is a PASS. Thin research is
        not the brief's failure.
  expected_output: >
    A verdict in markdown:

      ## VERDICT: PASS | FAIL

      ## Checklist
      | # | Check | Result | Evidence |
      Six rows. For failures, the quoted sentence.

      ## Required fixes
      Numbered, specific, actionable. Empty if PASS.

    Under 250 words. A verdict, not an essay.
  agent: evaluator
  context:
    - research_task
    - analysis_task
    - writing_task
```

---

## What to look for in the trace

- **A real rejection.** Slide 22 notes the lecture's own Pattern 6 demo *"fails
  round 1, passes by 2-3"*. A gate that passes first time on every run is not
  demonstrating anything — check the rules are actually binding.
- **The retry, under Option A.** The Writer running twice, second time carrying
  the failure message. That is the pattern, visible in one place.
- **Cost.** Add the retries to your call count. A gate that fires often is
  expensive; a gate that never fires is dead weight. Both are findings.

---

## Scoring the brief, not just gating it

Slide 66's sixth production problem is **evaluation** — *"score per-agent AND the
whole system."* Everything above this line is a **gate**: pass/fail on one brief
against a fixed checklist. That is not a score, and the difference matters
because this repository proposes four comparisons and **none of them is
resolvable as currently specified**:

| Comparison | Where | Measured by cost? | Measured by quality? |
|---|---|---|---|
| Writer on cheap tier vs escalation tier | `03-writer.md` | yes | **no** |
| Two agents vs three (merge Analyst + Writer) | `02-analyst.md` | yes | **no** |
| Code `@router` vs LLM Manager | `04-manager.md` | yes | **no** |
| `Process.sequential` vs `Process.hierarchical` | slide 62 | yes | **no** |

`08-observability.md` measures tokens, calls and dollars per agent. Nothing
measures whether the brief got better. So every one of those A/Bs currently
resolves to "the cheap one won", which is true by construction and answers
nothing. Slide 53 asks *whether you'd keep it* — a cost number alone cannot
answer that.

**The smallest thing that fixes it:**

1. **Fix three to five golden topics.** They must be re-runnable, so the cache
   state is comparable between arms. Record them in the repo, not in someone's
   shell history.
2. **Score each brief 1–5 on four axes**, using this agent's checklist discipline
   — quote the evidence, judge nothing else:
   - **Sourced** — every claim attributable, no orphan numbers.
   - **Decisive** — does the title state a *finding*? (`03-writer.md` already
     argues this is the cheapest test of whether the pipeline produced anything.)
   - **Faithful** — nothing present that the research did not contain.
   - **Calibrated** — does the stated confidence match the actual evidence?
3. **Same judge, same prompt, both arms, blind to which arm produced which.**
   Otherwise you are measuring the judge's expectations.
4. **Store the scores next to the cost.** `run_metrics` already carries tokens
   and dollars (`07-deployment.md`); a `run_scores` table alongside it makes
   quality a query rather than a memory.

This is one more table and one more prompt. Without it the project can say what
its crew *costs* and not what it is *worth* — and the honest answer to slide 53
needs both numbers, not one.

> Judge on the cheap tier with `reasoning_effort: "minimal"`, exactly as this
> agent does. A scorer that costs more than the thing it scores will not get run
> twice.

---

## The cheapest version of all

Two of the six checks — a Sources section exists, word count in range — are
deterministic string operations. They need no model, cost nothing, and catch the
most common failure.

Before adding a fourth agent, consider whether a plain function guardrail
already gets you most of the value. Then you can answer slide 53's *"whether
you'd keep it"* with something better than a working feature: a measured judgement
about whether it needed to be an agent at all.
