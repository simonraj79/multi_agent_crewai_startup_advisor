# Durations - run `f371b3b9-6ca5-4b8b-9f63-9c34249ef440`

DoD B4: Langfuse spans against the app's own frame timestamps.
Generated 2026-09-05T18:29:58Z. Tolerance in the verdict column: 1 s.

Every row is ONE observation against ONE app span, matched on role, label and start order. A child's duration is never added to its parent's: the contract nests node -> task -> agent -> tool over one call, and summing that tree turns a 2.006 s agent into 6.014 s.

Slowest first, which is the ranking B4 asks for.

#### The B4 answer

| the slowest | label | Langfuse s | app s |
| --- | --- | --- | --- |
| agent | Channel Sounder | 0.653 | 0.450 |
| task | Write one short paragraph about the depth of the north reach of the estuary. Use no tools. | 0.664 | 0.664 |
| tool | (none observed) | n/a | n/a |

Rows outside the 1 s tolerance: **0**.

### Agents - one row per observation

| rank | label | # | app s | Langfuse s | delta s | verdict | observation id | Diagnosis |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Channel Sounder | 1 | 0.450 | 0.653 | 0.203 | within 1 s | a9ba1f503291bff6 |  |
| 2 | Channel Sounder | 2 | 0.104 | n/a | n/a | app only | - |  |
| 3 | Channel Sounder | 3 | 0.095 | n/a | n/a | app only | - |  |

### Tasks - one row per observation

| rank | label | # | app s | Langfuse s | delta s | verdict | observation id | Diagnosis |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | crew | 1 | 0.695 | n/a | n/a | app only | - |  |
| 2 | Write one short paragraph about the depth of the north reach of the estuary. Use no tools. | 1 | 0.664 | 0.664 | 0.000 | within 1 s | e7f16220a4378c14 |  |
| 3 | AgentExecutor | 1 | 0.444 | n/a | n/a | app only | - |  |
| 4 | AgentExecutor | 2 | 0.101 | n/a | n/a | app only | - |  |
| 5 | AgentExecutor | 3 | 0.091 | n/a | n/a | app only | - |  |

### Tools - one row per observation

| rank | label | # | app s | Langfuse s | delta s | verdict | observation id | Diagnosis |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| - | - | - | - | - | - | - | - | - |

### Nodes - one row per observation

| rank | label | # | app s | Langfuse s | delta s | verdict | observation id | Diagnosis |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | sound_the_channel | 1 | 0.998 | 0.998 | 0.000 | within 1 s | 58373c3b1d66f048 |  |
| 2 | start_sounding | 1 | 0.004 | 0.004 | 0.000 | within 1 s | 61f952578291593b |  |
| 3 | start_sounding | 2 | 0.003 | 0.002 | 0.001 | within 1 s | a0172f85e75ccd9b |  |
| 4 | the_brief | 1 | 0.003 | 0.003 | 0.000 | within 1 s | b9f36ab7a9c367c7 |  |
