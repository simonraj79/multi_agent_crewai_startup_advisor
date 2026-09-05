# Durations from Langfuse spans - run `6586c854-3ca3-44c4-a587-eb6a3ef01962`

DoD B4. Slowest first. The app-side column is in `app-figures.md`;
`reconcile.py` is what puts the two within-1-s comparison side by side.

Run span: 2026-09-05T16:34:41.590000Z -> 2026-09-05T16:36:58.860000Z (137.270 s)

Every figure below is an observation's OWN duration. A child's duration
is never added to its parent's: the contract nests node -> task -> agent
-> tool over one 2 s tool call, and summing that tree reports 6 s.

## Agents

| agent_role | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| Business Brief Writer producing decision-ready one-pagers on predictive maintenance for commercial building lifts | 2 | 52.762 | 29.096 |  |
| Guardrail Agent | 2 | 35.948 | 18.557 |  |
| Strategy Analyst turning raw research on predictive maintenance for commercial building lifts into a defensible point of view | 1 | 23.875 | 23.875 |  |
| Senior Research Analyst specialising in predictive maintenance for commercial building lifts | 1 | 17.576 | 17.576 |  |

## Tasks

| task_name | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| writing_task | 1 | 88.725 | 88.725 |  |
| analysis_task | 1 | 23.886 | 23.886 |  |
| research_task | 1 | 17.586 | 17.586 |  |

## Tools

| tool | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| firecrawl_web_scrape_tool | 3 | 7.654 | 3.166 |  |
| firecrawl_web_search_tool | 1 | 1.776 | 1.776 |  |

## Nodes

| node_id | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| scrape_web | 23 | 131.061 | 131.061 | 22 |
| index_content | 1 | 3.351 | 3.351 |  |
| retrieve_cached | 1 | 2.842 | 2.842 |  |
| persist | 1 | 0.002 | 0.002 |  |
| check_cache | 1 | 0.001 | 0.001 |  |
| write_brief | 1 | 0.001 | 0.001 |  |

## The B4 answer: the slowest agent, task and tool

| role | label | seconds | observation id |
| --- | --- | --- | --- |
| agent | Business Brief Writer producing decision-ready one-pagers on predictive maintenance for commercial building lifts | 29.096 | 8d9904bdcb1e2057 |
| task | writing_task | 88.725 | 6c7beb27e6e5d462 |
| tool | firecrawl_web_scrape_tool | 3.166 | ce589664114cd63a |

## Slowest individual observations

| role | type | name | seconds | id |
| --- | --- | --- | --- | --- |
| run | SPAN | run | 137.270 | 4727eabef6394bdf |
| node | SPAN | scrape_web | 131.061 | db30287c748b73f1 |
| task | SPAN | writing_task | 88.725 | 6c7beb27e6e5d462 |
| agent | AGENT | Business Brief Writer producing decision-ready one-pagers on predictive maintenance for commercial building lifts | 29.096 | 8d9904bdcb1e2057 |
| generation | GENERATION | google/gemini-3.8-flash | 29.072 | 05a05ec9cb896041 |
| task | SPAN | analysis_task | 23.886 | 876ce55f78973586 |
| agent | AGENT | Strategy Analyst turning raw research on predictive maintenance for commercial building lifts into a defensible point of view | 23.875 | b2d90846f78230e2 |
| generation | GENERATION | google/gemini-3.8-flash | 23.864 | a2d309705ceee299 |
| agent | AGENT | Business Brief Writer producing decision-ready one-pagers on predictive maintenance for commercial building lifts | 23.666 | dc56bb6f3e0545d1 |
| generation | GENERATION | google/gemini-3.8-flash | 23.642 | a86b781fad0f2854 |
| agent | AGENT | Guardrail Agent | 18.557 | 3489692d258d8d2f |
| generation | GENERATION | google/gemini-3.8-flash | 18.539 | 5b798c6e47d1c0d7 |
| task | SPAN | research_task | 17.586 | 0d86f86330fc68fa |
| agent | AGENT | Senior Research Analyst specialising in predictive maintenance for commercial building lifts | 17.576 | 6d20dc39728ed85c |
| agent | AGENT | Guardrail Agent | 17.391 | 480a491eac1ecdc2 |
| generation | GENERATION | google/gemini-3.8-flash | 17.383 | 0ec92bdd608bb084 |
| generation | GENERATION | google/gemini-3.5-flash-lite:nitro | 4.439 | 2f6791a9c5c4503e |
| node | SPAN | index_content | 3.351 | 181a917f049120a0 |
| tool | TOOL | firecrawl_web_scrape_tool | 3.166 | ce589664114cd63a |
| node | SPAN | retrieve_cached | 2.842 | 572d55bdc31f4c79 |

---

## V-RECON — B4 on the second flow

Added 2026-09-06 by **V-RECON**, the named verifier for B4. Everything above is
the Langfuse side alone and was regenerated from the live API on 2026-09-06
**byte-identical** to the committed copy. The side-by-side is
`durations-app-vs-langfuse.md` beside this file.

### The B4 answer — the slowest of each kind

| the slowest | label | Langfuse s | app s | delta s |
| --- | --- | ---: | ---: | ---: |
| **agent** | Business Brief Writer producing decision-ready one-pagers … (`8d9904bdcb1e2057`) | 29.096 | 29.093 | 0.003 |
| **task** | writing_task (`6c7beb27e6e5d462`) | 88.725 | 88.726 | 0.001 |
| **tool** | firecrawl_web_scrape_tool #3 (`ce589664114cd63a`) | 3.166 | 3.166 | 0.000 |

Behind them: agents — Strategy Analyst 23.875 s, Brief Writer (2nd pass)
23.666 s, Guardrail 18.557 s and 17.391 s, Senior Research Analyst 17.576 s;
tools — scrape #2 2.744 s, `firecrawl_web_search_tool` 1.776 s, scrape #1
1.744 s. `writing_task` at 88.7 s of a 137.3 s run is the answer to "why was this
run slow", and its four generations (two writer passes, two guardrail passes)
are the reason.

### Rows outside the 1 s tolerance: **0** of 17 paired rows

| | |
| --- | --- |
| paired rows | 17 |
| **outside 1 s** | **0** |
| largest delta | **0.008 s** — AGENT `Senior Research Analyst …` (`6d20dc39728ed85c`) |
| median delta | 0.001 s |
| sum of all deltas | 0.032 s |

### The §7 timing model, measured on this run

`startTime − metadata.frame_ts` over all 52 observations that carry a
`frame_ts`: max **+0.004 s**, median **+0.001 s**, none above 10 ms. The
≤ 0.25 s drain allowance is essentially unused, and on this run the
frame-choice effect that costs `validator-live` 0.119 s costs at most 0.008 s,
because every agent here makes its first model call within milliseconds of
starting.

### The unpaired rows

- **2 "Langfuse only" agent rows** — both `Guardrail Agent`
  (`3489692d258d8d2f` 18.557 s, `480a491eac1ecdc2` 17.391 s). Same cause as on
  `validator-live`: CrewAI emits only an `AgentExecutor` frame pair for a
  guardrail agent, so the app-side span carries that label (rows
  `AgentExecutor` #4 18.549 s and #6 17.393 s, within 10 ms of the Langfuse
  figures) while the exporter names the observation from the LLM frame's
  `agent_role`. One interval, two labels, two unmatched rows.
- **7 "app only" task rows** — `BriefCrew` 130.248 s plus six `AgentExecutor`
  boundaries; the exporter gives a crew boundary no observation of its own.
- **22 "Langfuse only" node rows** — **exactly** the 22 EVENT observations
  (verified by id), which have no `endTime` by construction and are classified
  as `node` by the HEAD version of `pull_langfuse_run.py`. Tooling artifact,
  already fixed in the working tree.

**B4 verdict on this run: PASS**, 17 of 17 paired rows within 1 s, worst
0.008 s.
