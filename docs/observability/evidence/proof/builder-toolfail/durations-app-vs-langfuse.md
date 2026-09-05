# Durations - run `9becf713-e984-45a9-b9c0-5b229a15cb60`

DoD B4: Langfuse spans against the app's own frame timestamps.
Generated 2026-09-05T17:17:01Z. Tolerance in the verdict column: 1 s.

Every row is ONE observation against ONE app span, matched on role, label and start order. A child's duration is never added to its parent's: the contract nests node -> task -> agent -> tool over one call, and summing that tree turns a 2.006 s agent into 6.014 s.

Slowest first, which is the ranking B4 asks for.

#### The B4 answer

| the slowest | label | Langfuse s | app s |
| --- | --- | --- | --- |
| agent | Tidewater Cartographer | 2.231 | n/a |
| task | Take a sounding for the Tidewater approaches, north channel. You MUST call BOTH of your tools, in this order and once each. FIRS | 2.251 | 2.252 |
| tool | sounding_line_lookup | 0.018 | 0.018 |

Rows outside the 1 s tolerance: **0**.

### Agents - one row per observation

| rank | label | # | app s | Langfuse s | delta s | verdict | observation id | Diagnosis |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Tidewater Cartographer | 1 | n/a | 2.231 | n/a | one side has no duration | a6280bb92209fb0a |  |

### Tasks - one row per observation

| rank | label | # | app s | Langfuse s | delta s | verdict | observation id | Diagnosis |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | crew | 1 | 2.264 | n/a | n/a | app only | - |  |
| 2 | Take a sounding for the Tidewater approaches, north channel. You MUST call BOTH of your tools, in this order and once each. FIRS | 1 | 2.252 | 2.251 | 0.001 | within 1 s | bfd8a2ef290c826c |  |
| 3 | AgentExecutor | 1 | 2.233 | n/a | n/a | app only | - |  |

### Tools - one row per observation

| rank | label | # | app s | Langfuse s | delta s | verdict | observation id | Diagnosis |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | sounding_line_lookup | 1 | 0.018 | 0.018 | 0.000 | within 1 s | ac336998a8cb5c64 |  |
| 2 | read_website_content | 1 | 0.000 | 0.000 | 0.000 | within 1 s | 0eb0d52dff1e8883 |  |

### Nodes - one row per observation

| rank | label | # | app s | Langfuse s | delta s | verdict | observation id | Diagnosis |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | chart_the_shoals | 1 | 2.646 | 2.646 | 0.000 | within 1 s | 789867469c2df048 |  |
| 2 | the_brief | 1 | 0.006 | 0.005 | 0.001 | within 1 s | 133b429a6d3e3bee |  |
| 3 | start_survey | 1 | 0.005 | 0.004 | 0.001 | within 1 s | 8375f246907f5ca1 |  |
| 4 | start_survey | 2 | 0.004 | 0.003 | 0.001 | within 1 s | 198bbc1dbfe39b0e |  |
| 5 | chart_the_shoals | 2 | n/a | n/a | n/a | Langfuse only | 96af4c3a634b8c20 |  |
| 6 | chart_the_shoals | 3 | n/a | n/a | n/a | Langfuse only | ba7a7923926e7a8f |  |
| 7 | chart_the_shoals | 4 | n/a | n/a | n/a | Langfuse only | 691437a9a4e9e7b1 |  |
| 8 | chart_the_shoals | 5 | n/a | n/a | n/a | Langfuse only | 6d43aab91860208e |  |
| 9 | chart_the_shoals | 6 | n/a | n/a | n/a | Langfuse only | 1957cc266cc639a8 |  |
| 10 | chart_the_shoals | 7 | n/a | n/a | n/a | Langfuse only | 7f3a55b2309906a7 |  |
| 11 | workflow | 1 | n/a | n/a | n/a | Langfuse only | 51cee9c8f1ee328f |  |
| 12 | workflow | 2 | n/a | n/a | n/a | Langfuse only | 63ea8493a4e191ec |  |
| 13 | workflow | 3 | n/a | n/a | n/a | Langfuse only | 8e2efd0727d8a1fc |  |
| 14 | workflow | 4 | n/a | n/a | n/a | Langfuse only | 97e5302615ad7d99 |  |
