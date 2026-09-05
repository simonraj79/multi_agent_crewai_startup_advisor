# Durations - run `f146e846-7e32-4276-9c9d-d79909a02eec`

DoD B4: Langfuse spans against the app's own frame timestamps.
Generated 2026-09-05T18:29:55Z. Tolerance in the verdict column: 1 s.

Every row is ONE observation against ONE app span, matched on role, label and start order. A child's duration is never added to its parent's: the contract nests node -> task -> agent -> tool over one call, and summing that tree turns a 2.006 s agent into 6.014 s.

Slowest first, which is the ranking B4 asks for.

#### The B4 answer

| the slowest | label | Langfuse s | app s |
| --- | --- | --- | --- |
| agent | Validation report writer | 27.839 | 14.680 |
| task | reporting_task | 29.568 | 29.568 |
| tool | research_market_landscape | 6.115 | 6.119 |

Rows outside the 1 s tolerance: **1**.

### Agents - one row per observation

| rank | label | # | app s | Langfuse s | delta s | verdict | observation id | Diagnosis |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Validation report writer | 1 | 14.680 | 27.839 | 13.159 | **OVER 1 s** | a01a05e7ab12d735 |  |
| 2 | Validation report writer | 2 | 13.164 | n/a | n/a | app only | - |  |
| 3 | Startup validation scoper | 1 | 10.000 | 9.507 | 0.493 | within 1 s | 826d058fce9205a7 |  |
| 4 | Market evidence analyst | 1 | 9.881 | 9.873 | 0.008 | within 1 s | 6c64f98173c32d9d |  |
| 5 | Technical feasibility analyst | 1 | 7.904 | 7.887 | 0.017 | within 1 s | 429ab69eba843eb9 |  |
| 6 | Startup validation synthesist | 1 | 5.248 | 5.234 | 0.014 | within 1 s | 7102102ba575941d |  |
| 7 | Community demand analyst | 1 | 3.314 | 3.307 | 0.007 | within 1 s | 65aef72efe564984 |  |
| 8 | Guardrail Agent | 1 | n/a | 1.706 | n/a | Langfuse only | b829b8883b6b20dd |  |

### Tasks - one row per observation

| rank | label | # | app s | Langfuse s | delta s | verdict | observation id | Diagnosis |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | ReportCrew | 1 | 29.593 | n/a | n/a | app only | - |  |
| 2 | reporting_task | 1 | 29.568 | 29.568 | 0.000 | within 1 s | 9500e495d58b35f6 |  |
| 3 | AgentExecutor | 6 | 14.674 | n/a | n/a | app only | - |  |
| 4 | AgentExecutor | 7 | 13.159 | n/a | n/a | app only | - |  |
| 5 | ScopeCrew | 1 | 10.062 | n/a | n/a | app only | - |  |
| 6 | scoping_task | 1 | 10.007 | 10.006 | 0.001 | within 1 s | 917e4442d54909d9 |  |
| 7 | MarketCrew | 1 | 9.942 | n/a | n/a | app only | - |  |
| 8 | AgentExecutor | 1 | 9.915 | n/a | n/a | app only | - |  |
| 9 | market_task | 1 | 9.886 | 9.886 | 0.000 | within 1 s | 649cbba8f2053a64 |  |
| 10 | AgentExecutor | 4 | 9.876 | n/a | n/a | app only | - |  |
| 11 | FeasibilityCrew | 1 | 8.218 | n/a | n/a | app only | - |  |
| 12 | feasibility_task | 1 | 7.910 | 7.909 | 0.001 | within 1 s | da130dcdec8f4cc3 |  |
| 13 | AgentExecutor | 3 | 7.892 | n/a | n/a | app only | - |  |
| 14 | SynthesisCrew | 1 | 5.281 | n/a | n/a | app only | - |  |
| 15 | synthesis_task | 1 | 5.253 | 5.253 | 0.000 | within 1 s | 908617faf04d9b88 |  |
| 16 | AgentExecutor | 5 | 5.244 | n/a | n/a | app only | - |  |
| 17 | SentimentCrew | 1 | 3.345 | n/a | n/a | app only | - |  |
| 18 | sentiment_task | 1 | 3.320 | 3.320 | 0.000 | within 1 s | 073eff520abd0df9 |  |
| 19 | AgentExecutor | 2 | 3.309 | n/a | n/a | app only | - |  |
| 20 | AgentExecutor | 8 | 1.708 | n/a | n/a | app only | - |  |

### Tools - one row per observation

| rank | label | # | app s | Langfuse s | delta s | verdict | observation id | Diagnosis |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | research_market_landscape | 1 | 6.119 | 6.115 | 0.004 | within 1 s | f1aaa83740dd35d1 |  |
| 2 | assess_technical_feasibility | 1 | 4.001 | 4.000 | 0.001 | within 1 s | 924fabc7decf5202 |  |
| 3 | analyze_community_sentiment | 1 | 1.864 | 1.862 | 0.002 | within 1 s | 85365d913248a1cc |  |

### Nodes - one row per observation

| rank | label | # | app s | Langfuse s | delta s | verdict | observation id | Diagnosis |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | write_report | 1 | 29.877 | 29.876 | 0.001 | within 1 s | b745e52182baf0b7 |  |
| 2 | research_market | 1 | 15.500 | 15.499 | 0.001 | within 1 s | b1c9d46446eafe00 |  |
| 3 | research_feasibility | 1 | 10.783 | 10.782 | 0.001 | within 1 s | 4de07b3600ad6248 |  |
| 4 | scope_idea | 1 | 10.379 | 10.378 | 0.001 | within 1 s | 33f1d4138dd168e8 |  |
| 5 | synthesize | 1 | 5.563 | 5.562 | 0.001 | within 1 s | d6acee545db21015 |  |
| 6 | research_sentiment | 1 | 3.755 | 3.754 | 0.001 | within 1 s | 5942aba61aee41d1 |  |
| 7 | confirm_scope | 1 | 0.002 | 0.002 | 0.000 | within 1 s | 1fa1457c63d2fdb3 |  |
| 8 | persist | 1 | 0.002 | 0.001 | 0.001 | within 1 s | 652002db26c4a980 |  |
| 9 | review_verdict | 1 | 0.002 | 0.000 | 0.002 | within 1 s | b24e168d2e2e647a |  |
| 10 | route_verdict | 1 | 0.002 | 0.001 | 0.001 | within 1 s | 87b3ba26d5e6a550 |  |
| 11 | route_scope | 1 | 0.001 | 0.001 | 0.000 | within 1 s | 7b70a3699f57160d |  |
