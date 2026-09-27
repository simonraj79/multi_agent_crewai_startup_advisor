# Durations from Langfuse spans - run `3120758e-d7b6-45a7-8f05-28e138a203d9`

DoD B4. Slowest first. The app-side column is in `app-figures.md`;
`reconcile.py` is what puts the two within-1-s comparison side by side.

Run span: 2026-09-27T07:23:20.085000Z -> 2026-09-27T07:23:24.409000Z (4.324 s)

Every figure below is an observation's OWN duration. A child's duration
is never added to its parent's: the contract nests node -> task -> agent
-> tool over one 2 s tool call, and summing that tree reports 6 s.

## Agents

| agent_role | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| Tutor | 1 | 0.949 | 0.949 |  |
| Assessor | 1 | 0.921 | 0.921 |  |

## Tasks

| task_name | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| tutor | 1 | 0.962 | 0.962 |  |
| assess | 1 | 0.934 | 0.934 |  |

## Tools

| tool | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| - | - | - | - | - |

## Nodes

| node_id | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| teacher_check | 3 | 1.513 | 1.501 |  |
| tutor | 1 | 1.411 | 1.411 |  |
| assess | 1 | 1.352 | 1.352 |  |
| submission | 1 | 0.008 | 0.008 |  |
| verdict | 1 | 0.007 | 0.007 |  |
| final | 1 | 0.007 | 0.007 |  |
| report | 1 | 0.006 | 0.006 |  |

## The B4 answer: the slowest agent, task and tool

| role | label | seconds | observation id |
| --- | --- | --- | --- |
| agent | Tutor | 0.949 | c69c5a279e7caaea |
| task | tutor | 0.962 | 2fdb7a43d3a99fa8 |
| tool | (none observed) | n/a |  |

## Slowest individual observations

| role | type | name | seconds | id |
| --- | --- | --- | --- | --- |
| run | SPAN | run | 4.324 | 327ad1df22a8289d |
| node | SPAN | teacher_check | 1.501 | dc0067e5bb88ce50 |
| node | SPAN | tutor | 1.411 | 028fc52ecd40b996 |
| node | SPAN | assess | 1.352 | 9321f7a969f2e5db |
| task | SPAN | tutor | 0.962 | 2fdb7a43d3a99fa8 |
| agent | AGENT | Tutor | 0.949 | c69c5a279e7caaea |
| generation | GENERATION | google/gemini-3.5-flash-lite:nitro | 0.940 | f818271cc4ce2a50 |
| task | SPAN | assess | 0.934 | 8f2aac2541694130 |
| agent | AGENT | Assessor | 0.921 | 3134c01a73805dca |
| generation | GENERATION | google/gemini-3.5-flash-lite:nitro | 0.913 | 7de1a3c6655c80fb |
| node | SPAN | submission | 0.008 | 1c4690b6d83ef14f |
| node | SPAN | teacher_check | 0.007 | 08726ed799ee0987 |
| node | SPAN | verdict | 0.007 | d6037c396f4f482f |
| node | SPAN | final | 0.007 | 90aa830d3f5a7d06 |
| node | SPAN | report | 0.006 | d63f445f75e9f996 |
| node | SPAN | teacher_check | 0.005 | 1aa98d36e7c30e46 |
| event | EVENT | NODE_START | n/a | c79aa7eb6dc2bb21 |
| event | EVENT | NODE_START | n/a | db85053f5a7b2599 |
| event | EVENT | NODE_START | n/a | e418d5085bb99471 |
| event | EVENT | NODE_START | n/a | 46989b319edfb2d3 |
