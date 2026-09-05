# `capture-on` — B5's capture half: content present, planted key redacted (SYNTHETIC)

Run 2026-09-05 by V-PROOF on the free synthetic backend, `127.0.0.1:8099`,
restarted with `LANGFUSE_CAPTURE_CONTENT=1`. `readyz-8099-capture.json`
confirms `capture_content: true` before the launch. No money was spent.

| | |
| --- | --- |
| app run id | `c5d1dde9-c22d-4621-a171-9a7e85803105` |
| Langfuse trace id | `c5d1dde9c22d4621a1719a7e85803105` |
| terminal status | `completed` |
| observations | 33 — SPAN 18, AGENT 6, GENERATION 6, TOOL 3 |

The idea (`request.json`) carries two plants:

* the marker phrase `MARKER-QUILTED-SEXTANT`
* a fake OpenRouter key, `sk-or-v1-` followed by 64 zeros

## What the trace shows — counted over the raw exported JSON

| file | `MARKER-QUILTED-SEXTANT` | the fake key | any `sk-or-` |
| --- | ---: | ---: | ---: |
| `langfuse-traces.json` | **1** | **0** | **0** |
| `langfuse-observations.json` | **18** | **0** | **0** |
| `langfuse-session.json` | **1** | **0** | **0** |

`trace.input` under capture:

```json
{"idea": "MARKER-QUILTED-SEXTANT is the marker phrase for this capture test. A tide-table app for harbour pilots; our staging key is *** and must never appear in a trace.", "no_gates": true}
```

The user's text is present — capture is genuinely on — and the key shape is
`***`. A TOOL observation's `input` shows the same: `{"query": "MARKER-QUILTED-SEXTANT … our staging key is *** …"}`.
All six GENERATIONs carry a non-null `output`.

Compare `../validator-live` under the DEFAULT policy, where the same fields
are `{"input_keys", "input_chars", "input_fingerprint"}` and every generation's
`input`/`output` is null.

## The one part of §4 capture cannot satisfy, and why

**Generation `input` is null on all six even with capture on.** It is not a
policy failure: the LLM `before` frame carries **no messages at all**. Measured
on the PAID `validator-live` run, the `MODEL_CALL` before-frame's detail keys
are exactly

```text
agent_id, agent_role, call_id, message_count, model,
prompt_chars, prompt_fingerprint, stage, task_id, task_name
```

— no `messages`. That is DoD §7's own revision ("no content enters a frame":
the serializer fingerprints and counts, and the exporter copies). So the
exporter has nothing to put in a generation's `input` under any policy, on a
paid run or a synthetic one. `TRACE-CONTRACT.md` §4's row
"`input`/`output` … present, redacted, when `LANGFUSE_CAPTURE_CONTENT=1`" is
therefore satisfiable for `output` only, and the contract and the frame
pipeline disagree with each other rather than the exporter being wrong.

The completion side, the trace input, and every tool argument and result **are**
captured and redacted, so "which prompt produced a bad output" is answerable
via the fingerprint plus the captured completion.
