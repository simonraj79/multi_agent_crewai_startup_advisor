# 02 · Analyst

**Stage 2 of 3** · **Pattern 1, stage 2** · no tools · the judgement step.

> 🔨 **Implemented** in `brief_crew.py::analyst`. `tools=[]` is passed
> explicitly rather than omitted, so the empty tool surface reads as a decision
> in the code and not as an oversight.
>
> The `context` warning below is confirmed against 1.15.18: `Task.context`
> defaults to a `_NotSpecified` sentinel, not `None` — which is exactly how
> CrewAI distinguishes *unset* (inherit all prior) from *explicit empty list*
> (no context at all). The consequence is load-bearing one file over, on the
> Writer.
>
> The two-agents-vs-three comparison this file argues for is runnable without
> editing anything: `BriefCrew(from_notes=True)` is already a two-agent crew.

The **Analyst** in this repository's role decomposition: it may calculate and
compare; it may not search, write, or critique. The empty tool surface below is
that "may not search", enforced in code as `tools=[]`. See `workflow.md` §4.

> **Agent contract** — **Role · Tools · Inputs · Outputs · Guardrail**
> (`workflow.md` §4). Filled in below; the rest of this file is the reasoning
> behind it. Note **Guardrail** here is a *prompt-level* "what it must NOT do",
> which appears in the task YAML as `Constraints:` — it is **not** CrewAI's
> `guardrail:` field, which is a post-hoc output validator (see `00` §8).

| Field | Value |
|---|---|
| **Role** | Strategy Analyst turning raw research on `{topic}` into a defensible point of view |
| **Tools** | **none — deliberate.** Not an omission; see "Why no tools" below. |
| **Inputs** | `context: [research_task]` — the Researcher's notes, and nothing else |
| **Outputs** | 300–500 words: *Bottom line* (one sentence) · *What matters* (3–4 findings, each with its "so what") · *Confidence: High/Medium/Low* with justification · *What would change this* |
| **Guardrail** | Use ONLY the research notes — introducing an outside fact is a failure, not initiative. Do not promote an "Unverified" item by restating it confidently. Do not flatten recorded disagreement. Do NOT write the brief. |
| **State** | Reads only. Owns nothing. |

Receives the Researcher's notes. Decides what actually matters and what the
reader should conclude. Hands the Writer an argument, not a pile of facts.

---

## Identity

```yaml
analyst:
  role: >
    Strategy Analyst turning raw research on {topic} into a defensible point of view
  goal: >
    Reduce the research notes to the three or four things that genuinely matter,
    state the single most important implication for the reader, and be explicit
    about how much confidence the evidence actually supports. Cut everything
    that is merely interesting.
  backstory: >
    You have spent years writing the one-page note that lands on a decision
    maker's desk, and you learned early that the hardest part is deciding what
    to leave out. You are ruthless about the difference between a fact and an
    insight: a number is not a finding until you can say what follows from it.
    You are equally ruthless about your own certainty - you would rather write
    "the evidence is thin here" than imply a confidence the sources do not
    support. You never introduce a fact the research did not contain.
```

---

## Configuration

| Setting | Value |
|---|---|
| `llm` | `openrouter/google/gemini-3.8-flash` |
| `tools` | *(none - deliberate)* |
| `max_iter` | `10` |
| `max_execution_time` | `300` |
| `allow_delegation` | `False` |
| `verbose` | `True` |

No `max_rpm` and no `inject_date`: this agent makes a single call and reasons
only over text it was handed, so neither buys anything. Both are set on the
Researcher, which needs them.

**This is the one agent for which the escalation tier is non-negotiable.** The
Writer and the retired Manager also run on `gemini-3.8-flash`, but the Writer is
the crew's designated A/B candidate for dropping to the cheap tier
(`03-writer.md`) and the Manager is not built. Only the Researcher and the
Evaluator are unambiguously on `gemini-3.5-flash-lite:nitro`. Selection and
framing is where the brief's quality is actually decided, so this is the one place the cheap
default is a false economy — and the one agent that should *not* be A/B'd
down. Note there is no tier above this one in the current stack —
"trade up if the brief reads thin" has no destination.

> **Both tiers were corrected on 2026-09-04, prices measured live.** Escalation
> moved `gemini-3.7-flash` → `gemini-3.8-flash` (`f19a2c6`) at the same
> $0.75 / $3.75. The cheap tier had been recorded as `z-ai/glm-5.3-flash` at
> $0.075 / $0.250 and is really `gemini-3.5-flash-lite:nitro` at
> **$0.30 / $2.50**.
>
> 🛑 **This page's central claim rests on a gap four times smaller than it was
> written against, and it has NOT been re-argued.** "The one agent for which
> the escalation tier is non-negotiable" and "the cheap default is a false
> economy" were written when escalation cost 10× the input and 15× the output.
> The real figures are **2.5×** and **1.5×**, and the two context windows are
> now equal. A 1.5× completion premium is a materially weaker reason to keep
> this agent off the cheap tier than a 15× one. Somebody should decide this
> deliberately; nobody has.

⚠️ **A retrieval tool now exists in this codebase. Do not give it to this agent.**
The temptation to "let it re-check one fact" is live in a way it was not before,
and it destroys the property the next section depends on.

### Why no tools

Two reasons, and the second is the real one.

1. **Separation of concerns.** Gathering already happened. An Analyst with a
   search tool re-researches instead of analysing, and you pay twice.
2. **It creates a hard, visible boundary.** With no tools, every claim in the
   Analyst's output *must* trace back to the Researcher's notes. Anything new
   that appears is unambiguously invented - and it sits right there in the
   trace, one hand-off after its source. This is the cleanest place in the crew
   to observe an error cascade — failure mode #1 in `workflow.md` §9, and the
   one every other failure in that table eventually feeds.

Giving this agent tools would be a reasonable engineering decision and a poor
teaching one.

---

## Task - `analysis_task`

```yaml
analysis_task:
  description: >
    Read the research notes produced in the previous step and turn them into a
    point of view on {topic}.

    Do this:
      1. Identify the 3-4 findings that actually matter to someone who has to
         make a decision. Discard the rest, however interesting.
      2. For each one, state what follows from it - the "so what", not a
         restatement of the fact.
      3. Name the single most important implication overall. One sentence.
      4. Assess confidence as high, medium, or low, with a reason grounded in
         what the sources did and did not establish.
      5. Note what would change your view, and what the brief cannot answer.

    Constraints:
      - Use ONLY the research notes. You have no tools and no way to verify
        anything new. Introducing an outside fact is a failure, not initiative.
      - If the notes flagged something as unverified, it stays unverified. Do
        not promote it by restating it confidently.
      - Where the notes recorded disagreement, do not flatten it. Take a
        position and say what the other side has going for it.
      - Do NOT write the brief. No headline, no polished prose, no formatting
        for a reader. The Writer does that.
  expected_output: >
    An analytical summary in markdown:

      ## Bottom line
      One sentence. The single most important implication.

      ## What matters
      3-4 findings. For each: the finding in bold, then two or three sentences
      of "so what", then the supporting source from the research notes.

      ## Confidence: High | Medium | Low
      Two or three sentences justifying the rating from the state of the
      evidence - not from how plausible the conclusion feels.

      ## What would change this
      2-3 bullets: what evidence would move the assessment, and what the
      research could not establish.

    Target 300-500 words. Working analysis, not a finished document.
  agent: analyst
  context:
    - research_task
```

---

## Design notes

**The `context` line is redundant and should stay.** In `Process.sequential`
every task already receives all prior outputs. Write it out explicitly
anyway - it documents the pipeline, and it becomes
load-bearing the moment you switch to `Process.hierarchical`, where nothing is
implicit.

⚠️ **But "redundant" only holds while the list is complete.** `Crew._get_context`
(`crew.py:1866-1874`) treats an explicit list as a **replacement** for the
implicit all-prior aggregation, not an addition to it: unset → every prior
output; an explicit list → exactly those tasks; an empty list → **no context at
all**. This file names every prior task, and `03-writer.md` names both, which is
why it is currently harmless. Trim either list and you silently narrow what the
agent sees, with no error.

**Confidence rating as a free evaluator.** Forcing an explicit High/Medium/Low
grounded in evidence quality gives you a signal at the hand-off without paying
for the Pattern 6 evaluator agent. If the Researcher fabricated, a good Analyst
frequently rates Low and says the sourcing is thin - the cascade gets caught one
stage early, for nothing. Watch for this in the trace; it makes a genuinely
interesting thing to show in a demo.

---

## ⚠️ The strongest argument against this agent

**Which of the six patterns this build uses, and whether each is worth keeping**,
is the question `workflow.md` §7 answers. For this agent the honest answer is
contested, and the argument lives here.

Analyst and Writer share a model, share an empty tool surface, and arguably
share a persona - "someone who reads research and produces the document".
CrewAI's own `design-agent` skill (published in the `crewai-skills` plugin, not
on docs.crewai.com) is direct about this shape:

> If two "agents" share the same persona, the same tool surface, and the same
> LLM, they are one agent with a longer task description.

By that test, a two-agent crew - Researcher (tools) plus Brief Writer (judgement
and prose in one task) - would produce a comparable brief for roughly a third
fewer LLM calls.

**The case for keeping three:** the personas do differ in a way that shows up in
output. An analyst cuts; a writer builds. Merged into one agent the model
reliably under-cuts, because "decide what to discard" and "make it read well"
pull against each other inside a single prompt. Splitting them makes the discard
step explicit and auditable in the trace.

**The case against:** that is a real but modest quality gain, and you are paying
for an entire extra agent to get it on a one-page brief.

Both readings are defensible. Pick one and be able to say why - and if you have
time, run it both ways and count the calls in each trace. That comparison is
worth more than either brief.
