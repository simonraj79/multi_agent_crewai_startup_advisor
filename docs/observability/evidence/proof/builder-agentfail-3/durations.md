# Durations from Langfuse spans - run `f371b3b9-6ca5-4b8b-9f63-9c34249ef440`

DoD B4. Slowest first. The app-side column is in `app-figures.md`;
`reconcile.py` is what puts the two within-1-s comparison side by side.

Run span: 2026-09-05T18:16:03.702000Z -> 2026-09-05T18:16:04.721000Z (1.019 s)

Every figure below is an observation's OWN duration. A child's duration
is never added to its parent's: the contract nests node -> task -> agent
-> tool over one 2 s tool call, and summing that tree reports 6 s.

## Agents

| agent_role | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| Channel Sounder | 1 | 0.653 | 0.653 |  |

## Tasks

| task_name | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| Write one short paragraph about the depth of the north reach of the estuary. Use no tools. | 1 | 0.664 | 0.664 |  |

## Tools

| tool | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| - | - | - | - | - |

## Nodes

| node_id | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| sound_the_channel | 1 | 0.998 | 0.998 |  |
| start_sounding | 2 | 0.006 | 0.004 |  |
| the_brief | 1 | 0.003 | 0.003 |  |

## The B4 answer: the slowest agent, task and tool

| role | label | seconds | observation id |
| --- | --- | --- | --- |
| agent | Channel Sounder | 0.653 | a9ba1f503291bff6 |
| task | Write one short paragraph about the depth of the north reach of the estuary. Use no tools. | 0.664 | e7f16220a4378c14 |
| tool | (none observed) | n/a |  |

## Slowest individual observations

| role | type | name | seconds | id |
| --- | --- | --- | --- | --- |
| run | SPAN | run | 1.019 | 7ffeb0323f815b05 |
| node | SPAN | sound_the_channel | 0.998 | 58373c3b1d66f048 |
| task | SPAN | Write one short paragraph about the depth of the north reach of the estuary. Use no tools. | 0.664 | e7f16220a4378c14 |
| agent | AGENT | Channel Sounder | 0.653 | a9ba1f503291bff6 |
| generation | GENERATION | google/gemini-3.5-flash-lite | 0.390 | b6601c58576d20c9 |
| generation | GENERATION | google/gemini-3.5-flash-lite | 0.047 | fd45bd173f8746dd |
| generation | GENERATION | google/gemini-3.5-flash-lite | 0.046 | 242851cf65182033 |
| generation | GENERATION | google/gemini-3.5-flash-lite | 0.045 | 000a9272a01e748e |
| generation | GENERATION | google/gemini-3.5-flash-lite | 0.044 | 1919c5d1ac7a69b3 |
| generation | GENERATION | google/gemini-3.5-flash-lite | 0.038 | 71a4a402f94a5bb9 |
| node | SPAN | start_sounding | 0.004 | 61f952578291593b |
| node | SPAN | the_brief | 0.003 | b9f36ab7a9c367c7 |
| node | SPAN | start_sounding | 0.002 | a0172f85e75ccd9b |
| event | EVENT | NODE_START | n/a | c9d44d0a046e3a9c |
| event | EVENT | NODE_START | n/a | 065e3525a2128f33 |
| event | EVENT | NODE_START | n/a | 671846334d706115 |
| event | EVENT | NODE_START | n/a | 499f514177735fc0 |
| event | EVENT | AGENT_CALL | n/a | 0787686401f3e164 |
| event | EVENT | AGENT_CALL | n/a | 55afd577102c74a0 |
| event | EVENT | AGENT_CALL | n/a | 758d399cfb29ed18 |
