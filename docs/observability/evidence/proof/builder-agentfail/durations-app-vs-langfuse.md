# Durations - run `ca13fc73-0ca9-4a31-bc8c-6e53ed1d562d`

DoD B4: Langfuse spans against the app's own frame timestamps.
Generated 2026-09-05T17:17:03Z. Tolerance in the verdict column: 1 s.

Every row is ONE observation against ONE app span, matched on role, label and start order. A child's duration is never added to its parent's: the contract nests node -> task -> agent -> tool over one call, and summing that tree turns a 2.006 s agent into 6.014 s.

Slowest first, which is the ranking B4 asks for.

#### The B4 answer

| the slowest | label | Langfuse s | app s |
| --- | --- | --- | --- |
| agent | Channel Sounder | 0.401 | 0.145 |
| task | Write one short paragraph about the depth of the north reach of the estuary. Use no tools. | 0.409 | 0.410 |
| tool | (none observed) | n/a | n/a |

Rows outside the 1 s tolerance: **0**.

### Agents - one row per observation

| rank | label | # | app s | Langfuse s | delta s | verdict | observation id | Diagnosis |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Channel Sounder | 1 | 0.145 | 0.401 | 0.256 | within 1 s | 4d48441dc522611c |  |
| 2 | Channel Sounder | 2 | 0.158 | n/a | n/a | app only | - |  |
| 3 | Channel Sounder | 3 | 0.102 | n/a | n/a | app only | - |  |

### Tasks - one row per observation

| rank | label | # | app s | Langfuse s | delta s | verdict | observation id | Diagnosis |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | crew | 1 | 0.443 | n/a | n/a | app only | - |  |
| 2 | Write one short paragraph about the depth of the north reach of the estuary. Use no tools. | 1 | 0.410 | 0.409 | 0.001 | within 1 s | 1b64cf88d2b52be2 |  |
| 3 | AgentExecutor | 1 | 0.137 | n/a | n/a | app only | - |  |
| 4 | AgentExecutor | 2 | 0.127 | n/a | n/a | app only | - |  |
| 5 | AgentExecutor | 3 | 0.096 | n/a | n/a | app only | - |  |

### Tools - one row per observation

| rank | label | # | app s | Langfuse s | delta s | verdict | observation id | Diagnosis |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| - | - | - | - | - | - | - | - | - |

### Nodes - one row per observation

| rank | label | # | app s | Langfuse s | delta s | verdict | observation id | Diagnosis |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | sound_the_channel | 1 | 0.711 | 0.711 | 0.000 | within 1 s | 56422a601804505e |  |
| 2 | start_sounding | 2 | 0.005 | 0.004 | 0.001 | within 1 s | 61b4313c33d7c5a2 |  |
| 3 | the_brief | 1 | 0.004 | 0.004 | 0.000 | within 1 s | 5358aa9a4c4f4edc |  |
| 4 | start_sounding | 1 | 0.003 | 0.002 | 0.001 | within 1 s | 1e66f7d0cce5989c |  |
| 5 | sound_the_channel | 2 | n/a | n/a | n/a | Langfuse only | ef7cd08ce59a59aa |  |
| 6 | sound_the_channel | 3 | n/a | n/a | n/a | Langfuse only | 2575fd08f9285c3f |  |
| 7 | sound_the_channel | 4 | n/a | n/a | n/a | Langfuse only | 9ee83008662e34d8 |  |
| 8 | sound_the_channel | 5 | n/a | n/a | n/a | Langfuse only | 944173c0ecb601d7 |  |
| 9 | sound_the_channel | 6 | n/a | n/a | n/a | Langfuse only | 28fc248005d299a6 |  |
| 10 | sound_the_channel | 7 | n/a | n/a | n/a | Langfuse only | 4e56d7cf23747371 |  |
| 11 | sound_the_channel | 8 | n/a | n/a | n/a | Langfuse only | 57f62ceb6ba3782f |  |
| 12 | sound_the_channel | 9 | n/a | n/a | n/a | Langfuse only | 93ca5a0cea481efd |  |
| 13 | sound_the_channel | 10 | n/a | n/a | n/a | Langfuse only | 371aec35634825d2 |  |
| 14 | sound_the_channel | 11 | n/a | n/a | n/a | Langfuse only | 7acf15fd19e55c20 |  |
| 15 | sound_the_channel | 12 | n/a | n/a | n/a | Langfuse only | e0efc608b0e69598 |  |
| 16 | sound_the_channel | 13 | n/a | n/a | n/a | Langfuse only | c652982bf7b48d7b |  |
| 17 | sound_the_channel | 14 | n/a | n/a | n/a | Langfuse only | a0c36f46b97e55a0 |  |
| 18 | sound_the_channel | 15 | n/a | n/a | n/a | Langfuse only | 3e73e288cd3e3831 |  |
| 19 | sound_the_channel | 16 | n/a | n/a | n/a | Langfuse only | ca15fc638ed2e8f5 |  |
| 20 | workflow | 1 | n/a | n/a | n/a | Langfuse only | 24040cee44422529 |  |
| 21 | workflow | 2 | n/a | n/a | n/a | Langfuse only | ae73c039bd753b12 |  |
| 22 | workflow | 3 | n/a | n/a | n/a | Langfuse only | 4a0c4fe7cb576b92 |  |
| 23 | workflow | 4 | n/a | n/a | n/a | Langfuse only | 245034eba58960ce |  |
