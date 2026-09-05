# Durations from Langfuse spans - run `9becf713-e984-45a9-b9c0-5b229a15cb60`

DoD B4. Slowest first. The app-side column is in `app-figures.md`;
`reconcile.py` is what puts the two within-1-s comparison side by side.

Run span: 2026-09-05T16:33:05.199000Z -> 2026-09-05T16:33:07.870000Z (2.671 s)

Every figure below is an observation's OWN duration. A child's duration
is never added to its parent's: the contract nests node -> task -> agent
-> tool over one 2 s tool call, and summing that tree reports 6 s.

## Agents

| agent_role | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| Tidewater Cartographer | 1 | 2.231 | 2.231 |  |

## Tasks

| task_name | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| Take a sounding for the Tidewater approaches, north channel. You MUST call BOTH of your tools, in this order and once each. FIRS | 1 | 2.251 | 2.251 |  |

## Tools

| tool | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| sounding_line_lookup | 1 | 0.018 | 0.018 |  |
| read_website_content | 1 | 0.000 | 0.000 |  |

## Nodes

| node_id | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| chart_the_shoals | 7 | 2.646 | 2.646 | 6 |
| start_survey | 2 | 0.007 | 0.004 |  |
| the_brief | 1 | 0.005 | 0.005 |  |
| workflow | 4 | 0.000 | 0.000 | 4 |

## The B4 answer: the slowest agent, task and tool

| role | label | seconds | observation id |
| --- | --- | --- | --- |
| agent | Tidewater Cartographer | 2.231 | a6280bb92209fb0a |
| task | Take a sounding for the Tidewater approaches, north channel. You MUST call BOTH of your tools, in this order and once each. FIRS | 2.251 | bfd8a2ef290c826c |
| tool | sounding_line_lookup | 0.018 | ac336998a8cb5c64 |

## Slowest individual observations

| role | type | name | seconds | id |
| --- | --- | --- | --- | --- |
| run | SPAN | run | 2.671 | 6294c8c6a2958199 |
| node | SPAN | chart_the_shoals | 2.646 | 789867469c2df048 |
| task | SPAN | Take a sounding for the Tidewater approaches, north channel. You MUST call BOTH of your tools, in this order and once each. FIRS | 2.251 | bfd8a2ef290c826c |
| agent | AGENT | Tidewater Cartographer | 2.231 | a6280bb92209fb0a |
| generation | GENERATION | google/gemini-3.5-flash-lite | 1.261 | 2dcb3b753af2f79f |
| generation | GENERATION | google/gemini-3.5-flash-lite | 0.940 | f3a76fd7fc3cbf3d |
| tool | TOOL | sounding_line_lookup | 0.018 | ac336998a8cb5c64 |
| node | SPAN | the_brief | 0.005 | 133b429a6d3e3bee |
| node | SPAN | start_survey | 0.004 | 8375f246907f5ca1 |
| node | SPAN | start_survey | 0.003 | 198bbc1dbfe39b0e |
| tool | TOOL | read_website_content | 0.000 | 0eb0d52dff1e8883 |
| node | EVENT | NODE_START | n/a | 51cee9c8f1ee328f |
| node | EVENT | NODE_START | n/a | 63ea8493a4e191ec |
| node | EVENT | NODE_START | n/a | 8e2efd0727d8a1fc |
| node | EVENT | NODE_START | n/a | 97e5302615ad7d99 |
| node | EVENT | AGENT_CALL | n/a | 96af4c3a634b8c20 |
| node | EVENT | AGENT_CALL | n/a | ba7a7923926e7a8f |
| node | EVENT | AGENT_CALL | n/a | 691437a9a4e9e7b1 |
| node | EVENT | AGENT_CALL | n/a | 6d43aab91860208e |
| node | EVENT | AGENT_CALL | n/a | 1957cc266cc639a8 |
