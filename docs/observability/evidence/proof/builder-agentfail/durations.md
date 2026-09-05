# Durations from Langfuse spans - run `ca13fc73-0ca9-4a31-bc8c-6e53ed1d562d`

DoD B4. Slowest first. The app-side column is in `app-figures.md`;
`reconcile.py` is what puts the two within-1-s comparison side by side.

Run span: 2026-09-05T16:34:16.173000Z -> 2026-09-05T16:34:16.924000Z (0.751 s)

Every figure below is an observation's OWN duration. A child's duration
is never added to its parent's: the contract nests node -> task -> agent
-> tool over one 2 s tool call, and summing that tree reports 6 s.

## Agents

| agent_role | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| Channel Sounder | 1 | 0.401 | 0.401 |  |

## Tasks

| task_name | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| Write one short paragraph about the depth of the north reach of the estuary. Use no tools. | 1 | 0.409 | 0.409 |  |

## Tools

| tool | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| - | - | - | - | - |

## Nodes

| node_id | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| sound_the_channel | 16 | 0.711 | 0.711 | 15 |
| start_sounding | 2 | 0.006 | 0.004 |  |
| the_brief | 1 | 0.004 | 0.004 |  |
| workflow | 4 | 0.000 | 0.000 | 4 |

## The B4 answer: the slowest agent, task and tool

| role | label | seconds | observation id |
| --- | --- | --- | --- |
| agent | Channel Sounder | 0.401 | 4d48441dc522611c |
| task | Write one short paragraph about the depth of the north reach of the estuary. Use no tools. | 0.409 | 1b64cf88d2b52be2 |
| tool | (none observed) | n/a |  |

## Slowest individual observations

| role | type | name | seconds | id |
| --- | --- | --- | --- | --- |
| run | SPAN | run | 0.751 | 7b7b091f59ba3cd2 |
| node | SPAN | sound_the_channel | 0.711 | 56422a601804505e |
| task | SPAN | Write one short paragraph about the depth of the north reach of the estuary. Use no tools. | 0.409 | 1b64cf88d2b52be2 |
| agent | AGENT | Channel Sounder | 0.401 | 4d48441dc522611c |
| generation | GENERATION | google/gemini-3.5-flash-lite | 0.077 | fa782d39b6ef9b77 |
| generation | GENERATION | google/gemini-3.5-flash-lite | 0.061 | 63a291dbd9758626 |
| generation | GENERATION | google/gemini-3.5-flash-lite | 0.052 | 5cc6b566e7874812 |
| generation | GENERATION | google/gemini-3.5-flash-lite | 0.047 | fba97a13179c570b |
| generation | GENERATION | google/gemini-3.5-flash-lite | 0.045 | 173ca4a2d24c9222 |
| generation | GENERATION | google/gemini-3.5-flash-lite | 0.041 | c9ccc2da79d92401 |
| node | SPAN | the_brief | 0.004 | 5358aa9a4c4f4edc |
| node | SPAN | start_sounding | 0.004 | 61b4313c33d7c5a2 |
| node | SPAN | start_sounding | 0.002 | 1e66f7d0cce5989c |
| node | EVENT | NODE_START | n/a | 24040cee44422529 |
| node | EVENT | NODE_START | n/a | ae73c039bd753b12 |
| node | EVENT | NODE_START | n/a | 4a0c4fe7cb576b92 |
| node | EVENT | NODE_START | n/a | 245034eba58960ce |
| node | EVENT | AGENT_CALL | n/a | ef7cd08ce59a59aa |
| node | EVENT | AGENT_CALL | n/a | 2575fd08f9285c3f |
| node | EVENT | AGENT_CALL | n/a | 9ee83008662e34d8 |
