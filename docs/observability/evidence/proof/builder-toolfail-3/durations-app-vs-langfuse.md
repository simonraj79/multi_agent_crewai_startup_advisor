# Durations - run `f0297951-e1ff-49a1-90f6-725d06d9b112`

DoD B4: Langfuse spans against the app's own frame timestamps.
Generated 2026-09-05T18:29:57Z. Tolerance in the verdict column: 1 s.

Every row is ONE observation against ONE app span, matched on role, label and start order. A child's duration is never added to its parent's: the contract nests node -> task -> agent -> tool over one call, and summing that tree turns a 2.006 s agent into 6.014 s.

Slowest first, which is the ranking B4 asks for.

#### The B4 answer

| the slowest | label | Langfuse s | app s |
| --- | --- | --- | --- |
| agent | Tidewater Cartographer | 2.387 | n/a |
| task | Take a sounding for the Tidewater approaches, north channel. You MUST call BOTH of your tools, in this order and once each. FIRS | 2.395 | 2.395 |
| tool | sounding_line_lookup | 0.014 | 0.015 |

Rows outside the 1 s tolerance: **0**.

### Agents - one row per observation

| rank | label | # | app s | Langfuse s | delta s | verdict | observation id | Diagnosis |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Tidewater Cartographer | 1 | n/a | 2.387 | n/a | one side has no duration | 7c527ecb44053432 |  |

### Tasks - one row per observation

| rank | label | # | app s | Langfuse s | delta s | verdict | observation id | Diagnosis |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | crew | 1 | 2.413 | n/a | n/a | app only | - |  |
| 2 | Take a sounding for the Tidewater approaches, north channel. You MUST call BOTH of your tools, in this order and once each. FIRS | 1 | 2.395 | 2.395 | 0.000 | within 1 s | 715aa6415d2efdfe |  |
| 3 | AgentExecutor | 1 | 2.388 | n/a | n/a | app only | - |  |

### Tools - one row per observation

| rank | label | # | app s | Langfuse s | delta s | verdict | observation id | Diagnosis |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | sounding_line_lookup | 1 | 0.015 | 0.014 | 0.001 | within 1 s | dbc7ae8b3f47569f |  |
| 2 | read_website_content | 1 | 0.001 | 0.000 | 0.001 | within 1 s | ab6378130d772e46 |  |

### Nodes - one row per observation

| rank | label | # | app s | Langfuse s | delta s | verdict | observation id | Diagnosis |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | chart_the_shoals | 1 | 2.699 | 2.697 | 0.002 | within 1 s | 644acc07d8d0c2a0 |  |
| 2 | the_brief | 1 | 0.009 | 0.007 | 0.002 | within 1 s | 57dfdb16c7fdb777 |  |
| 3 | start_survey | 1 | 0.006 | 0.005 | 0.001 | within 1 s | 610e995b476c2b1e |  |
| 4 | start_survey | 2 | 0.005 | 0.004 | 0.001 | within 1 s | 808f527e19f4dfeb |  |
