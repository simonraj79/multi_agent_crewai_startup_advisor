# Durations from Langfuse spans - run `45cc3736-ed0b-466a-9dc6-e7f69ff0eea0`

DoD B4. Slowest first. The app-side column is in `app-figures.md`;
`reconcile.py` is what puts the two within-1-s comparison side by side.

Run span: 2026-09-05T17:25:32.734000Z -> 2026-09-05T17:25:33.989000Z (1.255 s)

Every figure below is an observation's OWN duration. A child's duration
is never added to its parent's: the contract nests node -> task -> agent
-> tool over one 2 s tool call, and summing that tree reports 6 s.

## Agents

| agent_role | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| Channel Sounder | 1 | 0.925 | 0.925 |  |

## Tasks

| task_name | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| Write one short paragraph about the depth of the north reach of the estuary. Use no tools. | 1 | 0.934 | 0.934 |  |

## Tools

| tool | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| - | - | - | - | - |

## Nodes

| node_id | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| sound_the_channel | 1 | 1.227 | 1.227 |  |
| start_sounding | 2 | 0.006 | 0.004 |  |
| the_brief | 1 | 0.005 | 0.005 |  |

## The B4 answer: the slowest agent, task and tool

| role | label | seconds | observation id |
| --- | --- | --- | --- |
| agent | Channel Sounder | 0.925 | 31c5efabeebacd88 |
| task | Write one short paragraph about the depth of the north reach of the estuary. Use no tools. | 0.934 | 15b7f9b00eb6da1b |
| tool | (none observed) | n/a |  |

## Slowest individual observations

| role | type | name | seconds | id |
| --- | --- | --- | --- | --- |
| run | SPAN | run | 1.255 | 067a1fdeec67af39 |
| node | SPAN | sound_the_channel | 1.227 | 584080214b55ad3b |
| task | SPAN | Write one short paragraph about the depth of the north reach of the estuary. Use no tools. | 0.934 | 15b7f9b00eb6da1b |
| agent | AGENT | Channel Sounder | 0.925 | 31c5efabeebacd88 |
| generation | GENERATION | google/gemini-3.5-flash-lite | 0.590 | 6ee7cc0ebb6bab27 |
| generation | GENERATION | google/gemini-3.5-flash-lite | 0.061 | a9879f6211f82629 |
| generation | GENERATION | google/gemini-3.5-flash-lite | 0.051 | 7d9849e6d46f05d5 |
| generation | GENERATION | google/gemini-3.5-flash-lite | 0.043 | ea84bccaa7443a29 |
| generation | GENERATION | google/gemini-3.5-flash-lite | 0.043 | 8c90c30a9e5cf184 |
| generation | GENERATION | google/gemini-3.5-flash-lite | 0.035 | 3304d6a147d1ca7b |
| node | SPAN | the_brief | 0.005 | a7a47ae947dd9326 |
| node | SPAN | start_sounding | 0.004 | b5051c5280551ef7 |
| node | SPAN | start_sounding | 0.002 | dc8af2b5cb3359ac |
| event | EVENT | NODE_START | n/a | f53dbf83a20b9b39 |
| event | EVENT | NODE_START | n/a | 589a86048135c717 |
| event | EVENT | NODE_START | n/a | 08fe7eedb7349951 |
| event | EVENT | NODE_START | n/a | 02c2026acec9f36a |
| event | EVENT | AGENT_CALL | n/a | ecd3270748f9038e |
| event | EVENT | AGENT_CALL | n/a | aedfd5f480452348 |
| event | EVENT | AGENT_CALL | n/a | 937d07c1eda130fb |
