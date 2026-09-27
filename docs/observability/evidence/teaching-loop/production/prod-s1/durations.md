# Durations from Langfuse spans - run `e3617cd4-8207-4b78-b750-e894ac44e804`

DoD B4. Slowest first. The app-side column is in `app-figures.md`;
`reconcile.py` is what puts the two within-1-s comparison side by side.

Run span: 2026-09-27T09:25:24.344000Z -> 2026-09-27T09:25:29.884000Z (5.540 s)

Every figure below is an observation's OWN duration. A child's duration
is never added to its parent's: the contract nests node -> task -> agent
-> tool over one 2 s tool call, and summing that tree reports 6 s.

## Agents

| agent_role | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| Assessor | 1 | 1.184 | 1.184 |  |
| Tutor | 1 | 0.833 | 0.833 |  |

## Tasks

| task_name | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| assess | 1 | 1.200 | 1.200 |  |
| tutor | 1 | 0.878 | 0.878 |  |

## Tools

| tool | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| - | - | - | - | - |

## Nodes

| node_id | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| teacher_check | 3 | 2.453 | 2.408 |  |
| assess | 1 | 1.581 | 1.581 |  |
| tutor | 1 | 1.130 | 1.130 |  |
| report | 1 | 0.071 | 0.071 |  |
| submission | 1 | 0.054 | 0.054 |  |
| final | 1 | 0.021 | 0.021 |  |
| verdict | 1 | 0.020 | 0.020 |  |

## The B4 answer: the slowest agent, task and tool

| role | label | seconds | observation id |
| --- | --- | --- | --- |
| agent | Assessor | 1.184 | efd7a431a42339d9 |
| task | assess | 1.200 | 267148754d6723f0 |
| tool | (none observed) | n/a |  |

## Slowest individual observations

| role | type | name | seconds | id |
| --- | --- | --- | --- | --- |
| run | SPAN | run | 5.540 | ae8e498d3a28086e |
| node | SPAN | teacher_check | 2.408 | 82c8b052e66030c7 |
| node | SPAN | assess | 1.581 | 25c94f3acc54ec97 |
| task | SPAN | assess | 1.200 | 267148754d6723f0 |
| agent | AGENT | Assessor | 1.184 | efd7a431a42339d9 |
| generation | GENERATION | google/gemini-3.5-flash-lite:nitro | 1.165 | 407c607008f29429 |
| node | SPAN | tutor | 1.130 | 22e044cf12e397ac |
| task | SPAN | tutor | 0.878 | f7694e39835ee2b6 |
| agent | AGENT | Tutor | 0.833 | 22c86f0801c90343 |
| generation | GENERATION | google/gemini-3.5-flash-lite:nitro | 0.819 | 3de1f0c7488bf10b |
| node | SPAN | report | 0.071 | 3c99f454ba0b92fd |
| node | SPAN | submission | 0.054 | 6c3a62264843465c |
| node | SPAN | teacher_check | 0.025 | a30af469b52f389b |
| node | SPAN | final | 0.021 | c540bdeb53c8c10d |
| node | SPAN | teacher_check | 0.020 | db1ebba24f29a2cf |
| node | SPAN | verdict | 0.020 | f49f195da3dc1e40 |
| event | EVENT | NODE_START | n/a | 8931b7c8a45a9a9c |
| event | EVENT | NODE_START | n/a | 90a04d7f3754f117 |
| event | EVENT | NODE_START | n/a | 414c2d9d5a011447 |
| event | EVENT | NODE_START | n/a | ba6c8a1a8d4c83d6 |
