# Durations from Langfuse spans - run `86371a87-7c50-498a-b32b-4936bd6c0c6a`

DoD B4. Slowest first. The app-side column is in `app-figures.md`;
`reconcile.py` is what puts the two within-1-s comparison side by side.

Run span: 2026-09-27T09:25:15.045000Z -> 2026-09-27T09:25:23.381000Z (8.336 s)

Every figure below is an observation's OWN duration. A child's duration
is never added to its parent's: the contract nests node -> task -> agent
-> tool over one 2 s tool call, and summing that tree reports 6 s.

## Agents

| agent_role | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| Assessor | 1 | 2.590 | 2.590 |  |
| Tutor | 1 | 1.383 | 1.383 |  |

## Tasks

| task_name | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| assess | 1 | 2.624 | 2.624 |  |
| tutor | 1 | 1.398 | 1.398 |  |

## Tools

| tool | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| - | - | - | - | - |

## Nodes

| node_id | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| assess | 1 | 3.036 | 3.036 |  |
| teacher_check | 3 | 2.391 | 2.213 |  |
| tutor | 1 | 1.691 | 1.691 |  |
| final | 1 | 0.132 | 0.132 |  |
| report | 1 | 0.079 | 0.079 |  |
| submission | 1 | 0.011 | 0.011 |  |
| verdict | 1 | 0.008 | 0.008 |  |

## The B4 answer: the slowest agent, task and tool

| role | label | seconds | observation id |
| --- | --- | --- | --- |
| agent | Assessor | 2.590 | 63fe150d711b15f4 |
| task | assess | 2.624 | 5bbfe24f2002ce93 |
| tool | (none observed) | n/a |  |

## Slowest individual observations

| role | type | name | seconds | id |
| --- | --- | --- | --- | --- |
| run | SPAN | run | 8.336 | 88494fa48e853ac3 |
| node | SPAN | assess | 3.036 | 6bc09cb3b48caaf8 |
| task | SPAN | assess | 2.624 | 5bbfe24f2002ce93 |
| agent | AGENT | Assessor | 2.590 | 63fe150d711b15f4 |
| generation | GENERATION | google/gemini-3.5-flash-lite:nitro | 2.560 | 07f9b5d1abbeb0d9 |
| node | SPAN | teacher_check | 2.213 | 6940ee11fb873b45 |
| node | SPAN | tutor | 1.691 | 24a9c96adb147d32 |
| task | SPAN | tutor | 1.398 | 7cb0fe0cd8491b60 |
| agent | AGENT | Tutor | 1.383 | 9fdd01a251a5e430 |
| generation | GENERATION | google/gemini-3.5-flash-lite:nitro | 1.223 | 5d0891c9954b22b1 |
| node | SPAN | final | 0.132 | bd0bfb668de54bc7 |
| node | SPAN | teacher_check | 0.091 | 187a9130adb33155 |
| node | SPAN | teacher_check | 0.087 | e9e3e05808dbc19b |
| node | SPAN | report | 0.079 | d71dfc13f211e3b2 |
| node | SPAN | submission | 0.011 | c2a261b8fa0cdd98 |
| node | SPAN | verdict | 0.008 | c76046ca1d109032 |
| event | EVENT | NODE_START | n/a | e034a036941108bb |
| event | EVENT | NODE_START | n/a | 65544f608cf29646 |
| event | EVENT | NODE_START | n/a | 615d1fc09847215f |
| event | EVENT | NODE_START | n/a | fb43a74e04aabc06 |
