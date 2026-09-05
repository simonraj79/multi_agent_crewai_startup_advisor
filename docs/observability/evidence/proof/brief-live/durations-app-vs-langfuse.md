# Durations - run `6586c854-3ca3-44c4-a587-eb6a3ef01962`

DoD B4: Langfuse spans against the app's own frame timestamps.
Generated 2026-09-05T17:17:00Z. Tolerance in the verdict column: 1 s.

Every row is ONE observation against ONE app span, matched on role, label and start order. A child's duration is never added to its parent's: the contract nests node -> task -> agent -> tool over one call, and summing that tree turns a 2.006 s agent into 6.014 s.

Slowest first, which is the ranking B4 asks for.

#### The B4 answer

| the slowest | label | Langfuse s | app s |
| --- | --- | --- | --- |
| agent | Business Brief Writer producing decision-ready one-pagers on predictive maintenance for commercial building lifts | 29.096 | 29.093 |
| task | writing_task | 88.725 | 88.726 |
| tool | firecrawl_web_scrape_tool | 3.166 | 3.166 |

Rows outside the 1 s tolerance: **0**.

### Agents - one row per observation

| rank | label | # | app s | Langfuse s | delta s | verdict | observation id | Diagnosis |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Business Brief Writer producing decision-ready one-pagers on predictive maintenance for commercial building lifts | 1 | 29.093 | 29.096 | 0.003 | within 1 s | 8d9904bdcb1e2057 |  |
| 2 | Strategy Analyst turning raw research on predictive maintenance for commercial building lifts into a defensible point of view | 1 | 23.882 | 23.875 | 0.007 | within 1 s | b2d90846f78230e2 |  |
| 3 | Business Brief Writer producing decision-ready one-pagers on predictive maintenance for commercial building lifts | 2 | 23.665 | 23.666 | 0.001 | within 1 s | dc56bb6f3e0545d1 |  |
| 4 | Guardrail Agent | 1 | n/a | 18.557 | n/a | Langfuse only | 3489692d258d8d2f |  |
| 5 | Senior Research Analyst specialising in predictive maintenance for commercial building lifts | 1 | 17.584 | 17.576 | 0.008 | within 1 s | 6d20dc39728ed85c |  |
| 6 | Guardrail Agent | 2 | n/a | 17.391 | n/a | Langfuse only | 480a491eac1ecdc2 |  |

### Tasks - one row per observation

| rank | label | # | app s | Langfuse s | delta s | verdict | observation id | Diagnosis |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | BriefCrew | 1 | 130.248 | n/a | n/a | app only | - |  |
| 2 | writing_task | 1 | 88.726 | 88.725 | 0.001 | within 1 s | 6c7beb27e6e5d462 |  |
| 3 | AgentExecutor | 3 | 29.088 | n/a | n/a | app only | - |  |
| 4 | analysis_task | 1 | 23.887 | 23.886 | 0.001 | within 1 s | 876ce55f78973586 |  |
| 5 | AgentExecutor | 2 | 23.877 | n/a | n/a | app only | - |  |
| 6 | AgentExecutor | 5 | 23.658 | n/a | n/a | app only | - |  |
| 7 | AgentExecutor | 4 | 18.549 | n/a | n/a | app only | - |  |
| 8 | research_task | 1 | 17.587 | 17.586 | 0.001 | within 1 s | 0d86f86330fc68fa |  |
| 9 | AgentExecutor | 1 | 17.578 | n/a | n/a | app only | - |  |
| 10 | AgentExecutor | 6 | 17.393 | n/a | n/a | app only | - |  |

### Tools - one row per observation

| rank | label | # | app s | Langfuse s | delta s | verdict | observation id | Diagnosis |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | firecrawl_web_scrape_tool | 3 | 3.166 | 3.166 | 0.000 | within 1 s | ce589664114cd63a |  |
| 2 | firecrawl_web_scrape_tool | 2 | 2.745 | 2.744 | 0.001 | within 1 s | b6de65bd9af75c2d |  |
| 3 | firecrawl_web_search_tool | 1 | 1.779 | 1.776 | 0.003 | within 1 s | d779ac5395ca3c67 |  |
| 4 | firecrawl_web_scrape_tool | 1 | 1.744 | 1.744 | 0.000 | within 1 s | 4c34aaa47459f8e0 |  |

### Nodes - one row per observation

| rank | label | # | app s | Langfuse s | delta s | verdict | observation id | Diagnosis |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | scrape_web | 1 | 131.062 | 131.061 | 0.001 | within 1 s | db30287c748b73f1 |  |
| 2 | index_content | 1 | 3.351 | 3.351 | 0.000 | within 1 s | 181a917f049120a0 |  |
| 3 | retrieve_cached | 1 | 2.843 | 2.842 | 0.001 | within 1 s | 572d55bdc31f4c79 |  |
| 4 | check_cache | 1 | 0.003 | 0.001 | 0.002 | within 1 s | e05cb4f2222620fa |  |
| 5 | persist | 1 | 0.003 | 0.002 | 0.001 | within 1 s | 8ffc1891f4da408e |  |
| 6 | write_brief | 1 | 0.002 | 0.001 | 0.001 | within 1 s | 484a8d2047cc64eb |  |
| 7 | scrape_web | 2 | n/a | n/a | n/a | Langfuse only | ae8a04fd02d2c022 |  |
| 8 | scrape_web | 3 | n/a | n/a | n/a | Langfuse only | 92bf20f739daa6be |  |
| 9 | scrape_web | 4 | n/a | n/a | n/a | Langfuse only | e3e04ef5abc8e7f1 |  |
| 10 | scrape_web | 5 | n/a | n/a | n/a | Langfuse only | abb13f753cdc0300 |  |
| 11 | scrape_web | 6 | n/a | n/a | n/a | Langfuse only | 92fb7ce8b9052aa7 |  |
| 12 | scrape_web | 7 | n/a | n/a | n/a | Langfuse only | 7e66fc3aec0b505a |  |
| 13 | scrape_web | 8 | n/a | n/a | n/a | Langfuse only | 58e88e62d0a5f80c |  |
| 14 | scrape_web | 9 | n/a | n/a | n/a | Langfuse only | dc975f18dcd550bd |  |
| 15 | scrape_web | 10 | n/a | n/a | n/a | Langfuse only | 3b6cfbd9999b62e4 |  |
| 16 | scrape_web | 11 | n/a | n/a | n/a | Langfuse only | d6870750235c7a03 |  |
| 17 | scrape_web | 12 | n/a | n/a | n/a | Langfuse only | ad0009b88af9b190 |  |
| 18 | scrape_web | 13 | n/a | n/a | n/a | Langfuse only | 5af3e778c3c79adc |  |
| 19 | scrape_web | 14 | n/a | n/a | n/a | Langfuse only | 062120f0f567e690 |  |
| 20 | scrape_web | 15 | n/a | n/a | n/a | Langfuse only | eb05594b1e3cb26f |  |
| 21 | scrape_web | 16 | n/a | n/a | n/a | Langfuse only | d8ce5fabc52f56e7 |  |
| 22 | scrape_web | 17 | n/a | n/a | n/a | Langfuse only | efdf650afce866b8 |  |
| 23 | scrape_web | 18 | n/a | n/a | n/a | Langfuse only | a34cc063b46b565f |  |
| 24 | scrape_web | 19 | n/a | n/a | n/a | Langfuse only | cbc5ed384304d186 |  |
| 25 | scrape_web | 20 | n/a | n/a | n/a | Langfuse only | ced3518b2b792d0c |  |
| 26 | scrape_web | 21 | n/a | n/a | n/a | Langfuse only | bb4640d8756cb66d |  |
| 27 | scrape_web | 22 | n/a | n/a | n/a | Langfuse only | 4d99fbc6d426444a |  |
| 28 | scrape_web | 23 | n/a | n/a | n/a | Langfuse only | 9efc001c8ecdf486 |  |
