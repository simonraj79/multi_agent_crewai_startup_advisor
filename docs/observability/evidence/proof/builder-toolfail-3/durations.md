# Durations from Langfuse spans - run `f0297951-e1ff-49a1-90f6-725d06d9b112`

DoD B4. Slowest first. The app-side column is in `app-figures.md`;
`reconcile.py` is what puts the two within-1-s comparison side by side.

Run span: 2026-09-05T18:07:36.203000Z -> 2026-09-05T18:07:38.935000Z (2.732 s)

Every figure below is an observation's OWN duration. A child's duration
is never added to its parent's: the contract nests node -> task -> agent
-> tool over one 2 s tool call, and summing that tree reports 6 s.

## Agents

| agent_role | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| Tidewater Cartographer | 1 | 2.387 | 2.387 |  |

## Tasks

| task_name | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| Take a sounding for the Tidewater approaches, north channel. You MUST call BOTH of your tools, in this order and once each. FIRS | 1 | 2.395 | 2.395 |  |

## Tools

| tool | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| sounding_line_lookup | 1 | 0.014 | 0.014 |  |
| read_website_content | 1 | 0.000 | 0.000 |  |

## Nodes

| node_id | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| chart_the_shoals | 1 | 2.697 | 2.697 |  |
| start_survey | 2 | 0.009 | 0.005 |  |
| the_brief | 1 | 0.007 | 0.007 |  |

## The B4 answer: the slowest agent, task and tool

| role | label | seconds | observation id |
| --- | --- | --- | --- |
| agent | Tidewater Cartographer | 2.387 | 7c527ecb44053432 |
| task | Take a sounding for the Tidewater approaches, north channel. You MUST call BOTH of your tools, in this order and once each. FIRS | 2.395 | 715aa6415d2efdfe |
| tool | sounding_line_lookup | 0.014 | dbc7ae8b3f47569f |

## Slowest individual observations

| role | type | name | seconds | id |
| --- | --- | --- | --- | --- |
| run | SPAN | run | 2.732 | 78fb70a2f343bae9 |
| node | SPAN | chart_the_shoals | 2.697 | 644acc07d8d0c2a0 |
| task | SPAN | Take a sounding for the Tidewater approaches, north channel. You MUST call BOTH of your tools, in this order and once each. FIRS | 2.395 | 715aa6415d2efdfe |
| agent | AGENT | Tidewater Cartographer | 2.387 | 7c527ecb44053432 |
| generation | GENERATION | google/gemini-3.5-flash-lite | 1.386 | d358948519d60019 |
| generation | GENERATION | google/gemini-3.5-flash-lite | 0.974 | c905579aae23efe2 |
| tool | TOOL | sounding_line_lookup | 0.014 | dbc7ae8b3f47569f |
| node | SPAN | the_brief | 0.007 | 57dfdb16c7fdb777 |
| node | SPAN | start_survey | 0.005 | 610e995b476c2b1e |
| node | SPAN | start_survey | 0.004 | 808f527e19f4dfeb |
| tool | TOOL | read_website_content | 0.000 | ab6378130d772e46 |
| event | EVENT | NODE_START | n/a | 962227c9e3d29ad5 |
| event | EVENT | NODE_START | n/a | bac9e507713938f1 |
| event | EVENT | NODE_START | n/a | e4040a9e6dfc8484 |
| event | EVENT | NODE_START | n/a | f3f273f55e9c4ba7 |
| event | EVENT | AGENT_CALL | n/a | b7600d300a8fc70e |
| event | EVENT | AGENT_CALL | n/a | 4c891f1f1dc58f34 |
| event | EVENT | AGENT_CALL | n/a | 0190a73e12060f80 |
| event | EVENT | AGENT_CALL | n/a | a68cdef9931e9e97 |
| event | EVENT | AGENT_CALL | n/a | 86e77e12f23abc10 |
