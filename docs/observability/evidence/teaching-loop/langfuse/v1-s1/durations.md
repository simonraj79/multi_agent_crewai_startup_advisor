# Durations from Langfuse spans - run `0813aacd-1550-4eca-b5be-c15ca29d5ffc`

DoD B4. Slowest first. The app-side column is in `app-figures.md`;
`reconcile.py` is what puts the two within-1-s comparison side by side.

Run span: 2026-09-27T07:20:51.247000Z -> 2026-09-27T07:20:58.039000Z (6.792 s)

Every figure below is an observation's OWN duration. A child's duration
is never added to its parent's: the contract nests node -> task -> agent
-> tool over one 2 s tool call, and summing that tree reports 6 s.

## Agents

| agent_role | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| Tutor | 1 | 2.417 | 2.417 |  |
| Assessor | 1 | 1.879 | 1.879 |  |

## Tasks

| task_name | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| tutor | 1 | 2.433 | 2.433 |  |
| assess | 1 | 1.895 | 1.895 |  |

## Tools

| tool | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| - | - | - | - | - |

## Nodes

| node_id | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| tutor | 1 | 2.878 | 2.878 |  |
| assess | 1 | 2.356 | 2.356 |  |
| teacher_check | 3 | 0.817 | 0.805 |  |
| submission | 1 | 0.011 | 0.011 |  |
| verdict | 1 | 0.007 | 0.007 |  |
| final | 1 | 0.007 | 0.007 |  |
| report | 1 | 0.005 | 0.005 |  |

## The B4 answer: the slowest agent, task and tool

| role | label | seconds | observation id |
| --- | --- | --- | --- |
| agent | Tutor | 2.417 | fc8fb6b6fd369e7f |
| task | tutor | 2.433 | 9f0dc3a911a0279a |
| tool | (none observed) | n/a |  |

## Slowest individual observations

| role | type | name | seconds | id |
| --- | --- | --- | --- | --- |
| run | SPAN | run | 6.792 | b6c7a293bff20574 |
| node | SPAN | tutor | 2.878 | ccb6ddbb59c12746 |
| task | SPAN | tutor | 2.433 | 9f0dc3a911a0279a |
| agent | AGENT | Tutor | 2.417 | fc8fb6b6fd369e7f |
| generation | GENERATION | google/gemini-3.5-flash-lite:nitro | 2.408 | 57c00d5297a74451 |
| node | SPAN | assess | 2.356 | e47ec5cba1bb3553 |
| task | SPAN | assess | 1.895 | 11cc1e35afe4363c |
| agent | AGENT | Assessor | 1.879 | b1eb1ef37df7152e |
| generation | GENERATION | google/gemini-3.5-flash-lite:nitro | 1.868 | cea0a7dba44b591a |
| node | SPAN | teacher_check | 0.805 | 7522433784e30339 |
| node | SPAN | submission | 0.011 | d4adb4f695454d5e |
| node | SPAN | teacher_check | 0.007 | 9368d75aecbd527f |
| node | SPAN | verdict | 0.007 | a8cf0377c4e667ee |
| node | SPAN | final | 0.007 | c4dea235c370e47d |
| node | SPAN | teacher_check | 0.005 | 9795fa5ce96edf38 |
| node | SPAN | report | 0.005 | f3daa1e36fea1a2a |
| event | EVENT | NODE_START | n/a | be575ec230ce0b56 |
| event | EVENT | NODE_START | n/a | 9cf2d4f9d721bdd7 |
| event | EVENT | NODE_START | n/a | 9b545957fe11f1a0 |
| event | EVENT | NODE_START | n/a | bcb586e233bc8191 |
