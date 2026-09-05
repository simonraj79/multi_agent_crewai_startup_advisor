# Durations from Langfuse spans - run `f4c8c779-52f2-40e1-9351-2668ea276ae4`

DoD B4. Slowest first. The app-side column is in `app-figures.md`;
`reconcile.py` is what puts the two within-1-s comparison side by side.

Run span: 2026-09-05T16:33:04.230000Z -> 2026-09-05T16:33:54.536000Z (50.306 s)

Every figure below is an observation's OWN duration. A child's duration
is never added to its parent's: the contract nests node -> task -> agent
-> tool over one 2 s tool call, and summing that tree reports 6 s.

## Agents

| agent_role | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| Validation report writer | 1 | 16.626 | 16.626 |  |
| Startup validation scoper | 1 | 13.901 | 13.901 |  |
| Market evidence analyst | 1 | 6.680 | 6.680 |  |
| Technical feasibility analyst | 1 | 6.170 | 6.170 |  |
| Startup validation synthesist | 1 | 3.899 | 3.899 |  |
| Guardrail Agent | 1 | 2.296 | 2.296 |  |
| Community demand analyst | 1 | 2.186 | 2.186 |  |

## Tasks

| task_name | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| reporting_task | 1 | 18.945 | 18.945 |  |
| scoping_task | 1 | 14.034 | 14.034 |  |
| market_task | 1 | 6.696 | 6.696 |  |
| feasibility_task | 1 | 6.183 | 6.183 |  |
| synthesis_task | 1 | 3.918 | 3.918 |  |
| sentiment_task | 1 | 2.202 | 2.202 |  |

## Tools

| tool | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| research_market_landscape | 1 | 3.789 | 3.789 |  |
| assess_technical_feasibility | 1 | 3.536 | 3.536 |  |
| analyze_community_sentiment | 1 | 0.605 | 0.605 |  |

## Nodes

| node_id | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| write_report | 9 | 19.264 | 19.264 | 8 |
| scope_idea | 7 | 14.410 | 14.410 | 6 |
| research_market | 7 | 12.296 | 12.296 | 6 |
| research_feasibility | 7 | 9.389 | 9.389 | 6 |
| synthesize | 7 | 4.300 | 4.300 | 6 |
| research_sentiment | 7 | 2.657 | 2.657 | 6 |
| confirm_scope | 1 | 0.003 | 0.003 |  |
| route_scope | 1 | 0.002 | 0.002 |  |
| review_verdict | 1 | 0.002 | 0.002 |  |
| route_verdict | 1 | 0.002 | 0.002 |  |
| persist | 1 | 0.001 | 0.001 |  |

## The B4 answer: the slowest agent, task and tool

| role | label | seconds | observation id |
| --- | --- | --- | --- |
| agent | Validation report writer | 16.626 | 4601d7501c7fc493 |
| task | reporting_task | 18.945 | 7f838c91a5684b2a |
| tool | research_market_landscape | 3.789 | a6c68222501bc21d |

## Slowest individual observations

| role | type | name | seconds | id |
| --- | --- | --- | --- | --- |
| run | SPAN | run | 50.306 | 5525de0c3601355d |
| node | SPAN | write_report | 19.264 | c0fa62409a92b0b0 |
| task | SPAN | reporting_task | 18.945 | 7f838c91a5684b2a |
| agent | AGENT | Validation report writer | 16.626 | 4601d7501c7fc493 |
| generation | GENERATION | google/gemini-3.8-flash | 16.600 | c5a7eed92550304e |
| node | SPAN | scope_idea | 14.410 | cd65f669d2eb6555 |
| task | SPAN | scoping_task | 14.034 | 6dfb83723296e78d |
| agent | AGENT | Startup validation scoper | 13.901 | d8f044a1aadf1806 |
| generation | GENERATION | google/gemini-3.8-flash | 13.888 | 06da27df751f0ebf |
| node | SPAN | research_market | 12.296 | 2df46cce0a7305da |
| node | SPAN | research_feasibility | 9.389 | 780033877dd975ad |
| task | SPAN | market_task | 6.696 | 24a7e1d59a77be61 |
| agent | AGENT | Market evidence analyst | 6.680 | 5110f385afb7793c |
| task | SPAN | feasibility_task | 6.183 | 17b86b77e236cbc3 |
| agent | AGENT | Technical feasibility analyst | 6.170 | a656aaa1076b568b |
| node | SPAN | synthesize | 4.300 | 0ebe23e34c2295b8 |
| task | SPAN | synthesis_task | 3.918 | efc9e2d1d24515b3 |
| agent | AGENT | Startup validation synthesist | 3.899 | f08d4270ed7ed45c |
| generation | GENERATION | google/gemini-3.8-flash | 3.885 | a07839dc6a12d3a3 |
| tool | TOOL | research_market_landscape | 3.789 | a6c68222501bc21d |

---

## V-RECON — B4: the app's frames beside these spans, and every delta explained

Added 2026-09-06 by **V-RECON**, the named verifier for B4. Everything above
this line is the **Langfuse side alone**, one row per observation, and it was
regenerated from the live API on 2026-09-06 **byte-identical** to the committed
copy. The side-by-side is `durations-app-vs-langfuse.md` beside this file
(`reconcile.py --durations-out`, per-observation pairing on role + label in
start order, 1 s tolerance); this section is its verdict.

### The B4 answer — the slowest of each kind, ranked

| the slowest | label | Langfuse s | app s | delta s |
| --- | --- | ---: | ---: | ---: |
| **agent** | Validation report writer (`4601d7501c7fc493`) | 16.626 | 16.633 | 0.007 |
| **task** | reporting_task (`7f838c91a5684b2a`) | 18.945 | 18.946 | 0.001 |
| **tool** | research_market_landscape (`a6c68222501bc21d`) | 3.789 | 3.792 | 0.003 |
| *(node, for context)* | write_report (`c0fa62409a92b0b0`) | 19.264 | 19.265 | 0.001 |

Ranking below them: agents — scoper 14.020 s, market 6.690 s, feasibility
6.171 s, synthesist 3.913 s, sentiment 2.193 s; tools —
`assess_technical_feasibility` 3.537 s, `analyze_community_sentiment` 0.606 s.
The run is 50.33 s and the report writer is a third of it.

### Rows outside the 1 s tolerance: **0** of 26 paired rows

| | |
| --- | --- |
| paired rows | 26 |
| **outside 1 s** | **0** |
| largest delta | **0.119 s** — AGENT `Startup validation scoper` `d8f044a1aadf1806` |
| next largest | 0.014 s — AGENT `Startup validation synthesist` |
| median delta | 0.001 s |
| sum of all deltas | 0.172 s |

### Does the §7 timing model explain the deltas? Partly — measured, not assumed

DoD §7 says the span **start** is the exporter's clock behind a ≤ 0.25 s drain,
the **end** is the frame timestamp, and `metadata.frame_ts` is the true start.
Both halves were checked over all 76 observations of this run:

- **The drain is real and far inside budget.** `startTime − metadata.frame_ts`
  is at most **+0.016 s**, median **+0.001 s**, and only 2 of 76 observations
  exceed 10 ms. The ≤ 0.25 s allowance is not being used.
- **It is therefore NOT the dominant term.** 0.016 s cannot produce a 0.119 s
  delta. The real cause is **which frame opens the span**, and it is visible in
  the metadata:

  `Startup validation scoper` opens on **`frame_seq: 7`**, which is the LLM
  `before` frame at `16:33:04.728Z` — not on the app's own agent-execution
  frame at `16:33:04.622Z` (seq 5, "Startup validation scoper started").
  The app's agent span is seq 5 → seq 13 = 14.020 s; the Langfuse AGENT is
  04.728 + 15 ms → 18.644 = 13.901 s. 0.106 s of frame-choice + 0.015 s of
  drain − 0.002 s at the end = **0.119 s**, to the millisecond.

  **The cause is upstream of the exporter:** every one of this run's 50 `agent`
  frames carries `agent_role: None`. The exporter can only name an agent when a
  frame supplies the role, and the first frame that does is the agent's first
  model call — so an AGENT observation begins at the agent's first LLM call
  rather than at its execution start. An app-side frame-content gap, visible in
  the contract's own `frame_seq`, and worth **0.1 s** on a 14 s span.

### The two unpaired kinds, and why neither is a missing measurement

- **1 "Langfuse only" agent row.** AGENT `Guardrail Agent` `129d55b7d611c970`,
  2.296 s, `16:33:52.217Z → 16:33:54.513Z`. The app measured the same interval —
  it is the `AgentExecutor` #7 row, 2.298 s, `16:33:52.212Z → 16:33:54.510Z`,
  3 ms apart at each end — but under a different **label**, because CrewAI
  emitted no role-named agent frame for the guardrail agent, only an
  `AgentExecutor` pair. The matcher pairs on label, so one interval reads twice
  as two unmatched rows. A labelling mismatch, not a timing one.
- **13 "app only" task rows and 38 "Langfuse only" node rows.**
  The 13 are 6 `*Crew` boundaries and 7 `AgentExecutor` boundaries — app-side
  frame spans the exporter deliberately does not give an observation of their
  own (the contract's tree is node → task → agent, and a crew boundary is the
  same interval as its task under another name). The 38 are **exactly the 38
  EVENT observations** (verified by id: the set difference is empty): a Langfuse
  EVENT is a point in time with no `endTime`, and the HEAD version of
  `pull_langfuse_run.py::observation_role` has no `EVENT` branch, so each falls
  through to the `node` role and is listed as an unpaired node row with `n/a`
  durations. A tooling artifact of the same family as `open-spans.txt`
  (`RUNS.md` defect 5), and the working tree already carries the fix.

**B4 verdict: PASS.** The slowest agent, task and tool are rankable from the
spans; 26 of 26 paired rows agree within 1 s, the worst by 0.119 s; and the
three classes of unpaired row are each explained by a named cause rather than
by a tolerance.
