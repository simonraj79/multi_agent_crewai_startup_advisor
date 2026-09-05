# Durations - run `f4c8c779-52f2-40e1-9351-2668ea276ae4`

DoD B4: Langfuse spans against the app's own frame timestamps.
Generated 2026-09-05T17:16:58Z. Tolerance in the verdict column: 1 s.

Every row is ONE observation against ONE app span, matched on role, label and start order. A child's duration is never added to its parent's: the contract nests node -> task -> agent -> tool over one call, and summing that tree turns a 2.006 s agent into 6.014 s.

Slowest first, which is the ranking B4 asks for.

#### The B4 answer

| the slowest | label | Langfuse s | app s |
| --- | --- | --- | --- |
| agent | Validation report writer | 16.626 | 16.633 |
| task | reporting_task | 18.945 | 18.946 |
| tool | research_market_landscape | 3.789 | 3.792 |

Rows outside the 1 s tolerance: **0**.

### Agents - one row per observation

| rank | label | # | app s | Langfuse s | delta s | verdict | observation id | Diagnosis |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Validation report writer | 1 | 16.633 | 16.626 | 0.007 | within 1 s | 4601d7501c7fc493 |  |
| 2 | Startup validation scoper | 1 | 14.020 | 13.901 | 0.119 | within 1 s | d8f044a1aadf1806 |  |
| 3 | Market evidence analyst | 1 | 6.690 | 6.680 | 0.010 | within 1 s | 5110f385afb7793c |  |
| 4 | Technical feasibility analyst | 1 | 6.171 | 6.170 | 0.001 | within 1 s | a656aaa1076b568b |  |
| 5 | Startup validation synthesist | 1 | 3.913 | 3.899 | 0.014 | within 1 s | f08d4270ed7ed45c |  |
| 6 | Guardrail Agent | 1 | n/a | 2.296 | n/a | Langfuse only | 129d55b7d611c970 |  |
| 7 | Community demand analyst | 1 | 2.193 | 2.186 | 0.007 | within 1 s | 4a8a088877ff90b5 |  |

### Tasks - one row per observation

| rank | label | # | app s | Langfuse s | delta s | verdict | observation id | Diagnosis |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | ReportCrew | 1 | 18.973 | n/a | n/a | app only | - |  |
| 2 | reporting_task | 1 | 18.946 | 18.945 | 0.001 | within 1 s | 7f838c91a5684b2a |  |
| 3 | AgentExecutor | 6 | 16.628 | n/a | n/a | app only | - |  |
| 4 | ScopeCrew | 1 | 14.087 | n/a | n/a | app only | - |  |
| 5 | scoping_task | 1 | 14.034 | 14.034 | 0.000 | within 1 s | 6dfb83723296e78d |  |
| 6 | AgentExecutor | 1 | 14.002 | n/a | n/a | app only | - |  |
| 7 | MarketCrew | 1 | 6.722 | n/a | n/a | app only | - |  |
| 8 | market_task | 1 | 6.696 | 6.696 | 0.000 | within 1 s | 24a7e1d59a77be61 |  |
| 9 | AgentExecutor | 4 | 6.685 | n/a | n/a | app only | - |  |
| 10 | FeasibilityCrew | 1 | 6.464 | n/a | n/a | app only | - |  |
| 11 | feasibility_task | 1 | 6.184 | 6.183 | 0.001 | within 1 s | 17b86b77e236cbc3 |  |
| 12 | AgentExecutor | 3 | 6.163 | n/a | n/a | app only | - |  |
| 13 | SynthesisCrew | 1 | 3.935 | n/a | n/a | app only | - |  |
| 14 | synthesis_task | 1 | 3.918 | 3.918 | 0.000 | within 1 s | efc9e2d1d24515b3 |  |
| 15 | AgentExecutor | 5 | 3.908 | n/a | n/a | app only | - |  |
| 16 | AgentExecutor | 7 | 2.298 | n/a | n/a | app only | - |  |
| 17 | SentimentCrew | 1 | 2.239 | n/a | n/a | app only | - |  |
| 18 | sentiment_task | 1 | 2.202 | 2.202 | 0.000 | within 1 s | 3481a7d1eda262bf |  |
| 19 | AgentExecutor | 2 | 2.189 | n/a | n/a | app only | - |  |

### Tools - one row per observation

| rank | label | # | app s | Langfuse s | delta s | verdict | observation id | Diagnosis |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | research_market_landscape | 1 | 3.792 | 3.789 | 0.003 | within 1 s | a6c68222501bc21d |  |
| 2 | assess_technical_feasibility | 1 | 3.537 | 3.536 | 0.001 | within 1 s | 3b7e95c99f4a3f8f |  |
| 3 | analyze_community_sentiment | 1 | 0.606 | 0.605 | 0.001 | within 1 s | 0b49e819b4e02f9c |  |

### Nodes - one row per observation

| rank | label | # | app s | Langfuse s | delta s | verdict | observation id | Diagnosis |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | write_report | 1 | 19.265 | 19.264 | 0.001 | within 1 s | c0fa62409a92b0b0 |  |
| 2 | scope_idea | 1 | 14.411 | 14.410 | 0.001 | within 1 s | cd65f669d2eb6555 |  |
| 3 | research_market | 1 | 12.296 | 12.296 | 0.000 | within 1 s | 2df46cce0a7305da |  |
| 4 | research_feasibility | 1 | 9.389 | 9.389 | 0.000 | within 1 s | 780033877dd975ad |  |
| 5 | synthesize | 1 | 4.302 | 4.300 | 0.002 | within 1 s | 0ebe23e34c2295b8 |  |
| 6 | research_sentiment | 1 | 2.658 | 2.657 | 0.001 | within 1 s | 5f8e87e9c45a63b5 |  |
| 7 | confirm_scope | 1 | 0.003 | 0.003 | 0.000 | within 1 s | dde17dca2b4ef4c7 |  |
| 8 | review_verdict | 1 | 0.003 | 0.002 | 0.001 | within 1 s | bec724a0d5cc8677 |  |
| 9 | persist | 1 | 0.002 | 0.001 | 0.001 | within 1 s | d05ea65d8055f075 |  |
| 10 | route_scope | 1 | 0.002 | 0.002 | 0.000 | within 1 s | 9bbb35a9b9d0cf3a |  |
| 11 | route_verdict | 1 | 0.002 | 0.002 | 0.000 | within 1 s | 3af6d2631e8e0416 |  |
| 12 | research_feasibility | 2 | n/a | n/a | n/a | Langfuse only | 9d938ea44672cced |  |
| 13 | research_feasibility | 3 | n/a | n/a | n/a | Langfuse only | ec8dc7dee75564f3 |  |
| 14 | research_feasibility | 4 | n/a | n/a | n/a | Langfuse only | a3cb70f513af3b47 |  |
| 15 | research_feasibility | 5 | n/a | n/a | n/a | Langfuse only | 06f14a6a6c1a0bbc |  |
| 16 | research_feasibility | 6 | n/a | n/a | n/a | Langfuse only | 748527c6cc680329 |  |
| 17 | research_feasibility | 7 | n/a | n/a | n/a | Langfuse only | 9771024f2cb3b3f0 |  |
| 18 | research_market | 2 | n/a | n/a | n/a | Langfuse only | 0381f6e75b422c7f |  |
| 19 | research_market | 3 | n/a | n/a | n/a | Langfuse only | af47999df0876df8 |  |
| 20 | research_market | 4 | n/a | n/a | n/a | Langfuse only | f4d9fcbd26eeb5d7 |  |
| 21 | research_market | 5 | n/a | n/a | n/a | Langfuse only | 9b8804961f21ffba |  |
| 22 | research_market | 6 | n/a | n/a | n/a | Langfuse only | 6ee8bd93052aecf4 |  |
| 23 | research_market | 7 | n/a | n/a | n/a | Langfuse only | f6bced2daf82ac7d |  |
| 24 | research_sentiment | 2 | n/a | n/a | n/a | Langfuse only | dc5213a8c6c35bbc |  |
| 25 | research_sentiment | 3 | n/a | n/a | n/a | Langfuse only | decebb1e6ca44d27 |  |
| 26 | research_sentiment | 4 | n/a | n/a | n/a | Langfuse only | ccd8096f68b3513e |  |
| 27 | research_sentiment | 5 | n/a | n/a | n/a | Langfuse only | 26e334c1aa15f275 |  |
| 28 | research_sentiment | 6 | n/a | n/a | n/a | Langfuse only | d39f7e5799612116 |  |
| 29 | research_sentiment | 7 | n/a | n/a | n/a | Langfuse only | 82b8097146dcdb03 |  |
| 30 | scope_idea | 2 | n/a | n/a | n/a | Langfuse only | 6716e100bb164e1b |  |
| 31 | scope_idea | 3 | n/a | n/a | n/a | Langfuse only | 50b45257773e5913 |  |
| 32 | scope_idea | 4 | n/a | n/a | n/a | Langfuse only | 00790ba52ccd3886 |  |
| 33 | scope_idea | 5 | n/a | n/a | n/a | Langfuse only | ad8c9c1a3a7d4ae5 |  |
| 34 | scope_idea | 6 | n/a | n/a | n/a | Langfuse only | 139692f706a8a127 |  |
| 35 | scope_idea | 7 | n/a | n/a | n/a | Langfuse only | a032fb3c3cf73b8d |  |
| 36 | synthesize | 2 | n/a | n/a | n/a | Langfuse only | a0012ae6373e0aec |  |
| 37 | synthesize | 3 | n/a | n/a | n/a | Langfuse only | 4f77ddc8704e520f |  |
| 38 | synthesize | 4 | n/a | n/a | n/a | Langfuse only | bb96faa46b6e8a5e |  |
| 39 | synthesize | 5 | n/a | n/a | n/a | Langfuse only | ca890fdccd4cc9cd |  |
| 40 | synthesize | 6 | n/a | n/a | n/a | Langfuse only | d7c02ba860f0bfe5 |  |
| 41 | synthesize | 7 | n/a | n/a | n/a | Langfuse only | 6cddb5a2409803bb |  |
| 42 | write_report | 2 | n/a | n/a | n/a | Langfuse only | d7917b7f49b6acc6 |  |
| 43 | write_report | 3 | n/a | n/a | n/a | Langfuse only | 7dafd574420beb6c |  |
| 44 | write_report | 4 | n/a | n/a | n/a | Langfuse only | db4cdaa7a61241bc |  |
| 45 | write_report | 5 | n/a | n/a | n/a | Langfuse only | 72b43894f04fdda0 |  |
| 46 | write_report | 6 | n/a | n/a | n/a | Langfuse only | 5d64d9e04212633c |  |
| 47 | write_report | 7 | n/a | n/a | n/a | Langfuse only | 037a2d259824b885 |  |
| 48 | write_report | 8 | n/a | n/a | n/a | Langfuse only | f5255001f233f3ff |  |
| 49 | write_report | 9 | n/a | n/a | n/a | Langfuse only | 39f81d9b682e5764 |  |
