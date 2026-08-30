# 03 · Writer

**Stage 3 of 3** · **Pattern 1, stage 3** · no tools · owns the artifact.

> 🔨 **Implemented** in `brief_crew.py::writer` / `writing_task`, with
> `markdown: true` and `output_file: output/brief.md` set in YAML.
>
> **The A/B this file nominates is a parameter, not an edit:**
> `BriefCrew(writer_model=CHEAP_MODEL)` runs the Writer on `glm-5.3-flash`.
> Everything else is held constant, so the comparison is clean.
>
> The optional word-count guardrail is **built and active** —
> `guardrails.check_mechanics` enforces 500–700 words and a `## Sources` section
> with ≥3 distinct URLs, as a callable, for zero LLM calls. It runs *before* the
> string guardrail so the free check rejects first.

The **Writer** in this repository's role decomposition: it may compose the
summary from facts it is handed; it may not search, calculate, or critique. See
`workflow.md` §4.

> **Agent contract** — **Role · Tools · Inputs · Outputs · Guardrail**
> (`workflow.md` §4). Filled in below; the rest of this file is the reasoning
> behind it. Note **Guardrail** here is a *prompt-level* "what it must NOT do",
> which appears in the task YAML as `Constraints:` — it is **not** CrewAI's
> `guardrail:` field, which is a post-hoc output validator (see `00` §8).

| Field | Value |
|---|---|
| **Role** | Business Brief Writer producing decision-ready one-pagers on `{topic}` |
| **Tools** | none |
| **Inputs** | `context: [research_task, analysis_task]` — the Analyst's argument **and** the Researcher's source URLs, which the Analyst compresses away |
| **Outputs** | `output/brief.md` — conclusion-stating title · 2–3 sentence summary · 3–4 sections · *What this means* · *Sources*. **500–700 words, a hard ceiling.** |
| **Guardrail** | Introduce no new facts, examples or numbers. Carry the Analyst's confidence rating through in plain language. **Provenance:** never present cached material as freshly verified. No orphan numbers. If the analysis was thin, write a short honest brief — do not pad to length. |
| **State** | Writes `output/brief.md` and, via the Flow's `persist` step, the `runs.brief_markdown` column. The only agent that produces a durable artifact. |

Turns the Analyst's argument into the one-page brief. This is the only agent
whose output anyone outside the crew reads, and the only one that writes a file.

---

## Identity

```yaml
writer:
  role: >
    Business Brief Writer producing decision-ready one-pagers on {topic}
  goal: >
    Produce a single page that a busy reader can absorb in three minutes and act
    on: the conclusion first, the evidence beneath it, every claim attributed,
    and nothing padded. It must fit on one page.
  backstory: >
    You write the briefs that executives actually read, which means you learned
    to put the answer in the first sentence rather than building to it. You have
    a working allergy to hedging language, throat-clearing introductions, and
    the phrase "in today's rapidly evolving landscape". You treat the length
    limit as a hard constraint rather than a target, because a brief that runs
    to two pages is a brief nobody finishes. You carry every source through from
    the analysis - an unattributed claim is not something you are willing to
    publish.
```

---

## Configuration

| Setting | Value |
|---|---|
| `llm` | `openrouter/google/gemini-3.7-flash` |
| `tools` | *(none)* |
| `max_iter` | `10` |
| `max_execution_time` | `300` |
| `allow_delegation` | `False` |
| `verbose` | `True` |

This agent is the **best A/B candidate for the cheap tier**. Its task is more
heavily templated than any other in the crew — fixed structure, hard word
ceiling, explicit constraints — so most of the difficulty is already solved by
task design rather than model capability. Try `openrouter/z-ai/glm-5.3-flash`
here and compare before assuming the escalation tier is needed. That is a **fifteen-fold**
difference on completion tokens ($3.75 vs $0.250/Mtok) — ten-fold on input —
applied to the crew's most output-heavy agent.

Set on the **task**, not the agent:

| Setting | Value |
|---|---|
| `markdown` | `True` |
| `output_file` | `output/brief.md` |
| `create_directory` | `True` *(default)* |

`output_file` on the task gives you an artifact on disk rather than a string
buried in the console. Having both the artifact and the trace that produced it on
hand is worth the one line.

---

## Task - `writing_task`

```yaml
writing_task:
  description: >
    Write the final one-page brief on {topic}, using the analysis from the
    previous step.

    Structure:
      1. A title that states the conclusion, not the subject. "Cashless
         adoption has plateaued among over-60s" beats "Cashless payments in
         Singapore".
      2. A two-to-three sentence executive summary carrying the bottom line.
      3. Three or four short sections, one per finding from the analysis, each
         with a bolded lead sentence and the supporting evidence.
      4. A "What this means" close: two or three bullets on the implication,
         and what remains uncertain.
      5. A "Sources" list carrying every URL through from the research.

    Constraints:
      - 500-700 words. This is a hard ceiling, not a target. One page.
      - Use ONLY the analysis and the research notes above. Introduce no new
        facts, examples, or numbers.
      - Carry the Analyst's confidence rating into the brief in plain language.
        If confidence was Low or Medium, the reader must be able to tell.
      - PROVENANCE: if any material fact came from the cached corpus rather
        than a page scraped during this run, say so where it matters. A cached
        fact carries the date it was indexed, not today's date. Never present
        retrieved material as freshly verified.
      - Every factual claim carries its source. No orphan numbers.
      - No introductory throat-clearing. No "in conclusion". The first sentence
        after the title states the finding.
      - If the analysis was thin, write a short honest brief. Do not pad it to
        length with generalities.
  expected_output: >
    A publication-ready markdown brief, 500-700 words:

      # <conclusion-stating title>

      **Summary** - 2-3 sentences carrying the bottom line.

      ## <finding 1>
      Bolded lead sentence, then 2-3 sentences of evidence with sources.

      ## <finding 2>
      ...

      ## <finding 3>
      ...

      ## What this means
      2-3 bullets: implication, and what stays uncertain. State the confidence
      level in plain language.

      ## Sources
      Numbered list, publisher and URL.

    Nothing after the sources list. No meta-commentary about the process.
  agent: writer
  context:
    - research_task
    - analysis_task
  markdown: true
  output_file: output/brief.md
```

---

## Design notes

**Why `context` names both prior tasks.** The Writer needs the Analyst's
argument for structure *and* the Researcher's notes for the source URLs, which
the Analyst compresses away. In `Process.sequential` it would receive both
anyway - stating it makes the dependency explicit and survives the move to
hierarchical.

**Why the title must state the conclusion.** It is the cheapest possible test of
whether the pipeline actually produced a finding. If the Writer can only manage
a title that names the subject, the Analyst did not deliver a point of view, and
you have found a real defect one stage upstream. A topic-shaped title is a
signal, not a style problem.

**Why the word ceiling is stated twice.** Models treat length guidance in
`description` as aspirational and length guidance in `expected_output` as
structural. Stating it in both, and calling it a ceiling rather than a target,
is what actually holds the line. If it still overruns, add a word-count
guardrail rather than arguing with the prompt.

**Why "write a short honest brief" is in the constraints.** Without it, a thin
analysis produces a padded brief - the model fills to length with generalities
and the upstream failure becomes invisible. This constraint keeps the failure
visible where you can point at it.

---

## Known failure modes

| Symptom | Cause | Fix |
|---|---|---|
| Brief is 1,200 words | Ceiling read as a target | Add a word-count guardrail (see below). |
| Contains facts absent from the research | Fabrication at the final stage - the worst place for it, since nothing downstream checks | Strengthen the "only the analysis" constraint. This is a strong Pattern 6 evaluator candidate. |
| Confident tone over a Low-confidence analysis | Confidence rating dropped in the hand-off | Make the confidence carry-through explicit; check it survived stage 2. |
| Title names the topic, not a finding | Analyst produced summary, not a point of view | Fix `02-analyst.md`, not this file. |
| Sources missing or renumbered | Writer only got the analysis | Ensure `context` includes `research_task`. |
| Ends with "I hope this brief is helpful" | Assistant register leaking through | Add the no-meta-commentary line to `expected_output`, as above. |

### Optional word-count guardrail

If the ceiling keeps slipping, a deterministic guardrail on this task is cheaper
than another prompt revision - it returns a failure message and the agent
retries:

- **Rule:** word count between **500 and 700** — the same range the task states.
  A guardrail that permits more than the task's stated ceiling enforces nothing.
- **On failure:** return the actual count and instruct it to cut, not rewrite.
- **Retries:** `guardrail_max_retries: 2`. The default is 3.

This is the smallest possible demonstration of the evaluator idea, one step below
the full Pattern 6 agent in `05-evaluator.md`. The contrast is the point: a
**function** guardrail is deterministic and costs nothing, while a **string**
guardrail is evaluated by a throwaway LLM agent and costs a call every time it
runs — pass or fail. Word counting is arithmetic. Use a function.

⚠️ If a guardrail exhausts its retries it does **not** pass the output through
with a warning — `Task._invoke_guardrail_function` (`task.py:1327`, delegating
per attempt to `crewai.utilities.guardrail.process_guardrail`) raises a plain
`Exception`, which in
`Process.sequential` fails the whole run. That is usually what you want here, but
decide it deliberately rather than discovering it at demo time.
