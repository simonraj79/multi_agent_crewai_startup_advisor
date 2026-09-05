# OpenRouter → Langfuse: stopping this application's broadcast, and only this application's

**Changed 2026-09-05.** One field on one destination. The broadcast destination
`multi-agent-crew-ai` now **excludes** the OpenRouter API key this repository
uses, so this app's generations no longer reach the Langfuse project through
OpenRouter. Nothing else on the destination moved.

Evidence: [`../evidence/audit/openrouter-change/`](../evidence/audit/openrouter-change/).
Every claim below names a file there. Where a claim is an inference rather than
a measurement it says **NOT VERIFIED** and why.

**No key value appears in this document or in any evidence file, and no full key
hash does either.** Key identity was established by comparing a SHA-256 digest
*in code* and printing only a boolean and a six-character prefix; the two
screenshots of the destination editor show the API-key picker collapsed to a
name. `.gitignore:146-150` deliberately un-ignores this tree, so these files are
written to be published: a scan for the four live credentials in `.env`, for
`sk-or-v1-…` / `pk-lf-…` / `sk-lf-…` shapes, and for the app key's full hash
returns **zero hits across all six evidence files**.

---

## 1. Prior state, quoted from the audit

[`openrouter-forwarding.md`](openrouter-forwarding.md) §1 is the baseline this
change is measured against, and it says of itself: *"Nothing was changed. The §1
table is the baseline to diff against."* The rows that matter here, verbatim:

| Setting | Value (audit §1) |
| --- | --- |
| Destination id (API) | `8bfe1a26-2ffb-4bbe-a8cf-11839a239f8b` |
| Destination id (UI route) | `15910` |
| Name | `multi-agent-crew-ai` |
| Type | `langfuse` |
| `enabled` | `true` |
| Langfuse host | `https://us.cloud.langfuse.com` |
| **Privacy Mode** | **☐ OFF** → prompts and completions **are** sent |
| Cost / Identity / Request-context metadata | all three **☐ OFF** |
| Sampling rate | `1` (100%) |
| Included API keys | none selected |
| Excluded API keys | none selected |
| `api_key_hashes` | `null` — the API documents this as "all keys" |
| `filter_rules` | `null` |
| Created / updated | `2026-09-05T08:24:27.107Z` / `2026-09-05T08:24:50.201Z` |

And the finding that motivated the change, also verbatim:

> **Two thirds of the Langfuse project is not this application**, and nothing on
> the OpenRouter side distinguishes them except that one metadata key. This is a
> finding for whoever owns the Langfuse console inventory, and the fix is one
> field on this destination.

with the measurement behind it — 45 traces over the 24 h to `2026-09-05T13:01Z`,
`MultiAgentCrewAI` 15, `LTA_ML_PROBLEM` 14, `WikiSkills` 16.

I re-read the destination from the management API before touching anything;
[`before-destination.json`](../evidence/audit/openrouter-change/before-destination.json)
records that read at **`2026-09-05T13:46:12.964Z`** and it agrees with the audit
table field for field.

### Which key is this application's, established rather than assumed

The audit named `MultiAgentCrewAI` from trace metadata. I confirmed it from the
credential side, by **two independent comparisons made in code**:

1. `sha256(os.environ["OPENROUTER_API_KEY"]).hexdigest()` equals the `hash`
   field of exactly **one** of the 11 rows of `GET /api/v1/keys`, and that row
   is `name: "MultiAgentCrewAI"`. `hash` is therefore the SHA-256 of the key —
   itself a small measured finding, since nothing documents it.
2. `GET /api/v1/key` authenticated with the app key returns a masked `label`
   that is byte-equal to that same row's `label` and to no other row's.

Neither the key nor the full digest was printed, logged or written; the
evidence file carries the boolean, the match count (`1`) and the prefix
`958f03`. The row is `disabled: false`, `expires_at: null`, and its
`workspace_id` is the destination's own workspace — which matters in §3.

### The rule the change relies on, quoted from the saved docs

`../evidence/audit/openrouter/docs/broadcast-overview.md`, *API Key Filtering*:

> You can also select **excluded** API keys for a destination. Requests made
> with an excluded key are never sent to that destination, even if the key is
> also in the included list: exclusions take precedence.

Exclusion is therefore the surgical instrument: it removes one key and leaves
the destination doing everything else it did. Disabling the destination,
enabling Privacy Mode, or setting an *included* list would each have been wrong
here — the first two stop or strip **everyone's** traces, and the third would
have had to enumerate every other key by hand and would silently omit any key
created later.

---

## 2. The change

| | |
| --- | --- |
| **What** | `MultiAgentCrewAI` added to the destination's **Excluded API Keys**. One field. |
| **Where** | destination `8bfe1a26-2ffb-4bbe-a8cf-11839a239f8b`, UI route `15910`, workspace `d9782653-59a8-51a5-9ff4-b28da297b63f` |
| **When** | server-side `updated_at` moved to **`2026-09-05T13:50:49.171Z`** |
| **How** | the OpenRouter web UI — `https://openrouter.ai/workspaces/default/observability/destinations/15910/edit`, API Key Filter → Excluded API Keys → search `MultiAgentCrewAI` → tick → **Save** |
| **Attempts** | one; no retry was needed |

**Why not the management API.** The task allowed a `PATCH` if the destinations
endpoint exposed an exclusion field. It does not. `GET
/api/v1/observability/destinations` and `GET …/destinations/{id}` both return
exactly fifteen fields —

```text
api_key_hashes, broadcast_generation_cost, broadcast_generation_identity,
broadcast_generation_request_context, config, created_at, enabled, filter_rules,
id, name, privacy_mode, sampling_rate, type, updated_at, workspace_id
```

— and there is **no `excluded_api_key_hashes` and no field of any other name
carrying exclusions**. `api_key_hashes` is the *included* list. So the API could
not express the change, and — see §3 — it cannot read it back either.

Before saving I checked the sections I was not there to touch: Regions still
**Global ✅ · EU ☐ · US ☐**, all three *Additional generation metadata*
categories still ☐, Privacy Mode still ☐, Sampling still `1`, Filter Rules still
"No filter rules configured".

- BEFORE: [`before-ui-api-key-filter.jpg`](../evidence/audit/openrouter-change/before-ui-api-key-filter.jpg)
  — Included "Select API keys", Excluded "Select API keys", both empty.
- AFTER: [`after-ui-api-key-filter.jpg`](../evidence/audit/openrouter-change/after-ui-api-key-filter.jpg)
  — Included still empty; Excluded reads **"1 selected"** with the chip
  `MultiAgentCrewAI`.
- AFTER, the rest of the form:
  [`after-ui-regions-metadata-privacy.jpg`](../evidence/audit/openrouter-change/after-ui-regions-metadata-privacy.jpg).

**The API-key dropdown is deliberately absent from every screenshot.** Opened,
it renders each key as its name over an OpenRouter-masked prefix
(`sk-or-v1-…`). Those masks are not credentials, but the prior audit chose not
to record even partial prefixes and this document keeps that rule, so the only
capture of the picker is the collapsed chip, which is a name.

---

## 3. After state, from the API — and what the API will not tell you

[`after-destination.json`](../evidence/audit/openrouter-change/after-destination.json),
read `2026-09-05T13:53:55.181Z`. Diffed against the before file, **one field of
fifteen changed**:

```text
CHANGED updated_at   '2026-09-05T08:24:50.201Z' -> '2026-09-05T13:50:49.171Z'
fields identical otherwise: 14 of 15
```

`enabled: true`, `privacy_mode: false`, the three `broadcast_generation_*`
booleans all `false`, `sampling_rate: 1`, `api_key_hashes: null`,
`filter_rules: null`, and the `config` block are byte-identical before and
after. That diff is the proof that nothing but the intended field moved.

> **The management API is not a faithful record of this destination, and that is
> a finding.** `updated_at` moved, so the write landed — but the exclusion I
> wrote is invisible in every API response. A reader who diffs these two JSON
> files and concludes "nothing changed except a timestamp" would be wrong, and
> would have no way to know it. **The UI editor is currently the only place the
> excluded list can be read.** Anyone later automating this — a Terraform-ish
> reconciler, a drift check, a restore-from-backup — must know that the API can
> neither set nor see it.

So the after state is asserted from the UI, and it is:

| Setting | After |
| --- | --- |
| Excluded API keys | **`MultiAgentCrewAI`** (1 selected) |
| Included API keys | still none |
| everything else | unchanged, per the 14-of-15 diff |

### One thing worth knowing before you next open that editor

On the **first** reload after saving, the chip rendered as
**`Deleted/Disabled Key`** rather than the key's name. It is a render race, not
a fact about the key, and it self-corrected: a second load of the same URL
showed `MultiAgentCrewAI`, which is the state captured in
`after-ui-api-key-filter.jpg`. The key itself is demonstrably fine —
`GET /api/v1/keys` reports it `disabled: false`, `expires_at: null`, same
`workspace_id` as the destination.

It is recorded because the failure mode it invites is expensive: somebody
opening this editor, reading "Deleted/Disabled Key", concluding the exclusion is
broken, and clearing it — which would silently restore the forwarding this
change exists to stop. **Reload before believing that label.**

---

## 4. The proof

One chat completion, `max_tokens: 8`, on `CHEAP_MODEL` from
`src/brief_crew/config.py` (`openrouter/google/gemini-3.5-flash-lite:nitro`,
`openrouter/` stripped), sent with `OPENROUTER_API_KEY` — the excluded key —
carrying a unique marker and `X-Title: exclusion-check`.
[`probe-request-and-response.json`](../evidence/audit/openrouter-change/probe-request-and-response.json).

```text
marker         exclusion-check-1788616463        (also sent as trace.trace_id,
                                                  trace.probe and trace.metadata.probe)
sent           2026-09-05T13:54:23.251Z          HTTP 200 in 1.03 s
generation id  gen-1788616463-5l46OLAf97BzcaL6k9hT
tokens         15 prompt / 4 completion          cost $0.0000261
```

(The completion response reports 15/4 and `GET /api/v1/generation` reports 7/7
for the same call — native versus OpenRouter's normalised counts. Both are
quoted below where they were read; the cost, $0.0000261, is identical in both.)

`trace_id` was set to the marker deliberately: the audit measured the Langfuse
trace id to be `sha256(trace.trace_id)[:32]`, so the trace's id is computable
off-line and its absence can be asserted by a direct fetch rather than only by
scanning a list.

**Read back at T+2.95 min** (the 120 s the task asked for, and a margin) and
again at **T+13.62 min** — both reads returning the same five answers. (The
second file is named `…T15min…` for the delay it was scheduled with; 13.62 is
what it measured.)
[`probe-langfuse-query-result.json`](../evidence/audit/openrouter-change/probe-langfuse-query-result.json),
[`probe-langfuse-recheck-T15min.json`](../evidence/audit/openrouter-change/probe-langfuse-recheck-T15min.json):

| Assertion | Result |
| --- | --- |
| no trace in the window carries the marker | **true** |
| no trace in the window carries the generation id | **true** |
| `GET /api/public/traces/sha256(marker)[:32]` | **404** |
| `GET /api/public/observations/sha256(gen-id)[:16]` | **404** |
| traces returned in the ±5 min window, from any key | **0** |

### The half that makes the negative mean something

A trace that never arrives is equally consistent with "the exclusion worked" and
with "the request never happened". The audit settled that distinction with its
probe b, and the same control is run here:
`GET /api/v1/generation?id=gen-1788616463-…` answers **200**, with
`total_cost: 2.61e-05` and 7/7 tokens. **OpenRouter saw the request, served it
and billed it, and did not forward it.**

### And the half that does not

[`probe-langfuse-window-survey.json`](../evidence/audit/openrouter-change/probe-langfuse-window-survey.json)
— every trace in the Langfuse project over the eight hours to
`2026-09-05T13:56Z`:

```text
47 traces, ALL of them before the change at 13:50:49Z, none after:
  WikiSkills 16 · MultiAgentCrewAI 15 · LTA_ML_PROBLEM 14 · (no key name) 2
newest broadcast trace of any kind:  12:54:45Z   (the prior audit's own probes)
```

So **no other key produced any traffic after the change** — nor for the 56
minutes before it. Their silence is therefore evidence of nothing, and the
positive control stays open. See §6.

The two rows with no `openrouter.api_key_name`, at `13:39:41Z` and `13:40:59Z`
and both named `idea-validator`, are **not** broadcast traces: they are
app-side, written directly by the parallel instrumentation work. They are worth
naming because they carry one useful fact — **Langfuse's ingest was accepting
writes eleven minutes before the change**, so "Langfuse was down" is not an
available explanation for the probe's absence. What they do not establish is
that the OpenRouter→Langfuse *broadcast* path was up at probe time.

**Cost of this task: $0.0000261**, one generation, against a $0.01
authorisation — 0.26% used.

---

## 5. How to revert

Remove the exclusion. Nothing else was touched, so nothing else needs restoring.

1. Open `https://openrouter.ai/workspaces/default/observability/destinations/15910/edit`.
2. Scroll to **API Key Filter**. Under **Excluded API Keys (optional)**, click
   the `×` on the `MultiAgentCrewAI` chip — or reopen the picker and untick it.
   (If the chip reads `Deleted/Disabled Key`, reload first: §3.)
3. The control must read **"Select API keys"** again, with no chip beneath it.
4. **Save.**
5. Verify: `GET /api/v1/observability/destinations` should show `updated_at`
   moved again, with all fourteen other fields still matching
   `before-destination.json`. That is the whole check the API can perform — the
   exclusion's absence itself is only readable in the UI.
6. To confirm end to end, repeat §4's probe; the trace should appear in Langfuse
   at `sha256(<marker>)[:32]` within a few minutes.

There is no API route for either direction. **Do not revert by re-enabling the
destination or by clearing Privacy Mode** — neither was changed, and touching
either would be a second, different change.

---

## 6. What was NOT verified

- **NOT VERIFIED: that the destination still delivers other keys' traffic.**
  This is the intended positive control and it could not be run. It needs a
  request made with a key that is *not* excluded; the only key available to this
  task is the excluded one, and using another was out of bounds. The
  opportunistic substitute failed too: `WikiSkills` and `LTA_ML_PROBLEM`
  produced **no** traffic at all in the eight hours surveyed, so their absence
  after the change carries no information. **The owner's other apps' traffic
  will settle this over the next day** — if `WikiSkills` and `LTA_ML_PROBLEM`
  traces continue to appear in the Langfuse project while `MultiAgentCrewAI`
  ones stop, the exclusion is confirmed surgical. Until then, "only this key was
  removed" rests on the UI state (Included empty, Excluded = one named key) and
  on the documented precedence rule, not on a measurement.

  The destination row's own menu carries a **`Send Trace`** action — a manual
  emitter that does not use any API key. It is the cheapest way to obtain this
  control and it was **deliberately not pressed**: it writes a trace into the
  owner's project, which is a second change to their data, and this task was
  scoped to one.

- **NOT VERIFIED: that the exclusion holds for a request shaped unlike the
  probe.** One call was sent: non-streaming, single message, eight completion
  tokens, on the cheap model. A streaming call, a tool call, a different model
  and a request carrying `session_id` were not tried. The filter is documented
  as keyed on the API key alone, so shape ought to be irrelevant — but that is a
  reading of a sentence, not a measurement.

- **NOT VERIFIED: that no trace arrives later than the recheck.** The audit saw
  its probes land within roughly three minutes; the docs promise only that
  traces are sent "asynchronously after requests complete", with **no stated
  delivery-time bound** and a retry queue implied for global traffic. Absence at
  T+13.62 min is strong, not conclusive.

- **NOT VERIFIED: what the UI actually stored.** The save is confirmed by
  `updated_at` and by the reloaded editor rendering the right name, but the
  stored identifier itself was never read: the management API does not return
  it, and the editor loads it through a server-rendered payload rather than an
  inspectable XHR. That the exclusion matches *this* key rests on the picker
  offering exactly one search hit for `MultiAgentCrewAI`, on the chip resolving
  back to that name, and on the probe not arriving.

- **NOT VERIFIED: anything about OpenRouter's own logs.** The generation is
  still in OpenRouter's ledger — the exclusion governs the broadcast
  destination, not `https://openrouter.ai/logs`, and the separate **Input &
  Output Logging** feature remains **ON**. Prompts and completions from this app
  continue to be stored by OpenRouter. If that is also unwanted, it is a
  different switch and a different change.

- **Unrelated observation, recorded because it will confuse someone.** The audit
  counted **13** API keys from the settings page on 2026-09-05; `GET
  /api/v1/keys` now returns **11** (confirmed not a paging artefact —
  `offset=10` returns one row, `offset=20` none). Two names in the audit's list,
  a duplicate `MCP: OpenRouter MCP: Claude Code (openrouter)` and `OpenCoder`,
  are absent. Nothing in this task deleted a key. Whether they were removed
  elsewhere, or the UI and the API count different things, was **not
  investigated**.
