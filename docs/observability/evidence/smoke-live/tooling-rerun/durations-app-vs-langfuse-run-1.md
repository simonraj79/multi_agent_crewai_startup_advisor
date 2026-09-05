# Durations - run `4548c884-6e5c-404c-a28a-bbf5a8ce8cf7`

DoD B4: Langfuse spans against the app's own frame timestamps.
Generated 2026-09-05T15:19:11Z. Tolerance in the verdict column: 1 s.

Every row is ONE observation against ONE app span, matched on role, label and start order. A child's duration is never added to its parent's: the contract nests node -> task -> agent -> tool over one call, and summing that tree turns a 2.006 s agent into 6.014 s.

Slowest first, which is the ranking B4 asks for.

#### The B4 answer

| the slowest | label | Langfuse s | app s |
| --- | --- | --- | --- |
| agent | Technical feasibility analyst | 2.005 | 2.006 |
| task | feasibility_task | 2.005 | n/a |
| tool | assess_technical_feasibility | 2.004 | 2.005 |

Rows outside the 1 s tolerance: **0**.

### Agents - one row per observation

| rank | label | # | app s | Langfuse s | delta s | verdict | observation id | Diagnosis |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Technical feasibility analyst | 1 | 2.006 | 2.005 | 0.001 | within 1 s | c268471fc550fc0f |  |
| 2 | Community demand analyst | 1 | 2.001 | 1.999 | 0.002 | within 1 s | d390cec95bfae0e5 |  |
| 3 | Market evidence analyst | 1 | 2.001 | 1.999 | 0.002 | within 1 s | 44142966c5aa55d9 |  |
| 4 | Validation report writer | 1 | 0.007 | 0.000 | 0.007 | within 1 s | 990a42ee25ecbc81 |  |
| 5 | Startup validation scoper | 1 | 0.002 | 0.000 | 0.002 | within 1 s | 4026066f4d647fcf |  |
| 6 | Startup validation synthesist | 1 | 0.002 | 0.000 | 0.002 | within 1 s | c76538f8cdebadce |  |

### Tasks - one row per observation

| rank | label | # | app s | Langfuse s | delta s | verdict | observation id | Diagnosis |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | feasibility_task | 1 | n/a | 2.005 | n/a | Langfuse only | 557d7f2c71b2da8f |  |
| 2 | market_task | 1 | n/a | 1.999 | n/a | Langfuse only | 3096aa6e7a841032 |  |
| 3 | sentiment_task | 1 | n/a | 1.999 | n/a | Langfuse only | bed4a1b2aad8ef14 |  |
| 4 | reporting_task | 1 | n/a | 0.000 | n/a | Langfuse only | 89c74b1397b7ed7f |  |
| 5 | scoping_task | 1 | n/a | 0.000 | n/a | Langfuse only | c89c2a8db0d02938 |  |
| 6 | synthesis_task | 1 | n/a | 0.000 | n/a | Langfuse only | 30a1eea0e65c0f2b |  |

### Tools - one row per observation

| rank | label | # | app s | Langfuse s | delta s | verdict | observation id | Diagnosis |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | assess_technical_feasibility | 1 | 2.005 | 2.004 | 0.001 | within 1 s | 8aacb501648f9c00 |  |
| 2 | research_market_landscape | 1 | 2.001 | 1.999 | 0.002 | within 1 s | c75b32d29976070c |  |
| 3 | analyze_community_sentiment | 1 | 2.000 | 1.998 | 0.002 | within 1 s | f9415efb15acd3b6 |  |

### Nodes - one row per observation

| rank | label | # | app s | Langfuse s | delta s | verdict | observation id | Diagnosis |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | research_feasibility | 1 | 2.006 | 2.005 | 0.001 | within 1 s | a5029a841ef9e8a1 |  |
| 2 | research_market | 1 | 2.001 | 1.999 | 0.002 | within 1 s | b0459be489c380bf |  |
| 3 | research_sentiment | 1 | 2.001 | 1.999 | 0.002 | within 1 s | c167d33de4847229 |  |
| 4 | write_report | 1 | 0.007 | 0.000 | 0.007 | within 1 s | 58b6792ef119dbef |  |
| 5 | scope_idea | 1 | 0.002 | 0.000 | 0.002 | within 1 s | ba2bd058a7221478 |  |
| 6 | synthesize | 1 | 0.002 | 0.000 | 0.002 | within 1 s | 07faea52db47fc23 |  |
| 7 | confirm_scope | 1 | 0.000 | 0.000 | 0.000 | within 1 s | eafcef350557ccc0 |  |
| 8 | persist | 1 | 0.000 | 0.000 | 0.000 | within 1 s | f32c37c6c8f700c4 |  |
| 9 | review_verdict | 1 | 0.000 | 0.000 | 0.000 | within 1 s | 73d4c861a6ecf62f |  |
| 10 | route_scope | 1 | 0.000 | 0.000 | 0.000 | within 1 s | b6f8ce01dab8e0b9 |  |
| 11 | route_verdict | 1 | 0.000 | 0.000 | 0.000 | within 1 s | ed749fbc45f00d90 |  |
