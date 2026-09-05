# Durations - run `036ace4e-8b58-4a9b-9d46-0b78448684f9`

DoD B4: Langfuse spans against the app's own frame timestamps.
Generated 2026-09-05T15:19:13Z. Tolerance in the verdict column: 1 s.

Every row is ONE observation against ONE app span, matched on role, label and start order. A child's duration is never added to its parent's: the contract nests node -> task -> agent -> tool over one call, and summing that tree turns a 2.006 s agent into 6.014 s.

Slowest first, which is the ranking B4 asks for.

#### The B4 answer

| the slowest | label | Langfuse s | app s |
| --- | --- | --- | --- |
| agent | Market evidence analyst | 2.011 | 2.013 |
| task | market_task | 2.011 | n/a |
| tool | research_market_landscape | 2.011 | 2.013 |

Rows outside the 1 s tolerance: **0**.

### Agents - one row per observation

| rank | label | # | app s | Langfuse s | delta s | verdict | observation id | Diagnosis |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Market evidence analyst | 1 | 2.013 | 2.011 | 0.002 | within 1 s | fa8307eab5f43776 |  |
| 2 | Technical feasibility analyst | 1 | 2.006 | 2.005 | 0.001 | within 1 s | 6d0136a3a9c131c3 |  |
| 3 | Community demand analyst | 1 | 2.001 | 2.000 | 0.001 | within 1 s | 814cd0218ca37a64 |  |
| 4 | Startup validation synthesist | 1 | 0.001 | 0.000 | 0.001 | within 1 s | c4e2c0474ef5e08d |  |
| 5 | Startup validation scoper | 1 | 0.000 | 0.000 | 0.000 | within 1 s | 87e3fce05d0359d6 |  |
| 6 | Validation report writer | 1 | 0.000 | 0.000 | 0.000 | within 1 s | 5090c06335b85b1d |  |

### Tasks - one row per observation

| rank | label | # | app s | Langfuse s | delta s | verdict | observation id | Diagnosis |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | market_task | 1 | n/a | 2.011 | n/a | Langfuse only | 05fb47aa3062afb4 |  |
| 2 | feasibility_task | 1 | n/a | 2.005 | n/a | Langfuse only | fce1eb051067613f |  |
| 3 | sentiment_task | 1 | n/a | 2.000 | n/a | Langfuse only | 71fbefd07a0a08b9 |  |
| 4 | reporting_task | 1 | n/a | 0.000 | n/a | Langfuse only | 68ea18f5103c97c8 |  |
| 5 | scoping_task | 1 | n/a | 0.000 | n/a | Langfuse only | 890c543fa8213174 |  |
| 6 | synthesis_task | 1 | n/a | 0.000 | n/a | Langfuse only | 346a921778a3b781 |  |

### Tools - one row per observation

| rank | label | # | app s | Langfuse s | delta s | verdict | observation id | Diagnosis |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | research_market_landscape | 1 | 2.013 | 2.011 | 0.002 | within 1 s | 0b66f5b27f495bb2 |  |
| 2 | assess_technical_feasibility | 1 | 2.006 | 2.005 | 0.001 | within 1 s | 602189eb01af2ed9 |  |
| 3 | analyze_community_sentiment | 1 | 2.001 | 1.999 | 0.002 | within 1 s | 341a61ba45549b9b |  |

### Nodes - one row per observation

| rank | label | # | app s | Langfuse s | delta s | verdict | observation id | Diagnosis |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | research_market | 1 | 2.013 | 2.011 | 0.002 | within 1 s | 91c00e33fc27a757 |  |
| 2 | research_feasibility | 1 | 2.006 | 2.005 | 0.001 | within 1 s | a51fa655cb8e8f80 |  |
| 3 | research_sentiment | 1 | 2.001 | 2.000 | 0.001 | within 1 s | f240db83aa528c12 |  |
| 4 | synthesize | 1 | 0.001 | 0.000 | 0.001 | within 1 s | 5755b128b5b1bab6 |  |
| 5 | confirm_scope | 1 | 0.000 | 0.000 | 0.000 | within 1 s | e26fffadb17d76aa |  |
| 6 | persist | 1 | 0.000 | 0.000 | 0.000 | within 1 s | dcedd578c154a1ee |  |
| 7 | review_verdict | 1 | 0.000 | 0.000 | 0.000 | within 1 s | 074196e46f2a7751 |  |
| 8 | route_scope | 1 | 0.000 | 0.000 | 0.000 | within 1 s | 69296a2d952da2a4 |  |
| 9 | route_verdict | 1 | 0.000 | 0.000 | 0.000 | within 1 s | 17b48bc4cf59b8e5 |  |
| 10 | scope_idea | 1 | 0.000 | 0.000 | 0.000 | within 1 s | 7ecc75955c106a2a |  |
| 11 | write_report | 1 | 0.000 | 0.000 | 0.000 | within 1 s | ea4420874452c74f |  |
