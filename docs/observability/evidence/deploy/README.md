# The Langfuse exporter, turned on in production

**2026-09-05 (UTC) / 2026-09-06 local (UTC+8).** The exporter has been in the
tree and off since it was built. This is the change that made the deployed API
export anything, and this directory is the whole record of it.

Everything here is **names, ids, statuses and lengths**. No credential value was
printed, logged, echoed or written at any point — not into a file here, not into
the commit, not into a terminal. Every value was read with `os.environ` inside
Python and handed straight to the Render API. `secret-scan.txt` is the check on
that claim rather than the claim itself.

## What was set

Three variables on the API service, and nothing on the studio service:

| Name | Shape | Why |
|---|---|---|
| `LANGFUSE_PUBLIC_KEY` | secret, `sync: false` | Half of the Basic-auth pair. "Public" names its role in Langfuse's own model, not its sensitivity — Langfuse echoes it on every object its API serves ([gotchas](../../../gotchas-and-insights.md) 60), so it is treated as a credential here |
| `LANGFUSE_SECRET_KEY` | secret, `sync: false` | The other half |
| `LANGFUSE_BASE_URL` | literal, `https://us.cloud.langfuse.com` | Not a secret. A literal for the same reason `CORS_ALLOW_ORIGINS` is one: a value knowable when the manifest is written should not be a manual step that can be missed. The value was compared against `.env` in Python and the comparison printed `True` — the comparison, not the value |

**There is no fourth variable, and that is the design.**
`LANGFUSE_EXPORT_ENABLED` defaults to `bool(public and secret)` (`config.py`),
the derived shape `VALIDATOR_REQUIRE_AUTH` already uses: naming the destination
*is* turning it on, so there is no boolean anyone can forget and no
half-configured state.

**`LANGFUSE_CAPTURE_CONTENT` was deliberately NOT set**, on the API service or
in the manifest. Its default is `0` and `0` is the only value for a public
deployment. `/readyz` now reports `capture_content: false` from the live
service, which is the check that matters — the absence of a row in a dashboard
is not evidence, and this is.

## Identifiers

| | |
|---|---|
| API service | `agentic-crew-ai-api`, `srv-da9qe7p42hec738l26og` (web, python, singapore, `autoDeploy: yes`, branch `main`) |
| Studio service | `agentic-crew-ai-studio`, `srv-dabb1v3tqb8s73fc2iv0` — **recorded and untouched**. No variable was written to it and `render.yaml` adds none |
| Deploy | `dep-dae9dpp7lnhs73em082g`, trigger `new_commit`, commit `bf48eeb` |
| Commit (manifest) | `bf48eeb` — `render.yaml` alone |
| Commit (this evidence) | see `git log` for the commit that adds this directory |

## The order, which is the load-bearing part

Render **snapshots a deploy's environment when the deploy is CREATED**
(deployment trap 3). A variable written after a deploy exists reaches nothing.
So the sequence was, and had to be:

```text
22:24:14Z  /readyz probed  ->  exporter "disabled"                (before)
22:24:37Z  three per-key PUTs to /services/{id}/env-vars/{key}    -> 200, 200, 200
22:24:38Z  env-vars re-listed by NAME  ->  16 became 19, nothing removed
22:25:39Z  git push origin main (bf48eeb)
22:25:43Z  Render created dep-dae9dpp7lnhs73em082g  ->  4 s later, no manual POST needed
22:27:21Z  that deploy went live
22:27:58Z  /readyz probed  ->  exporter "enabled"                 (after)
```

The variables existed **65 seconds before** the deploy that snapshotted them.
Had the push gone first, every probe would have read `disabled` and the obvious
conclusion — "the keys did not take" — would have been wrong.

**Per-key `PUT`, never the bulk `PUT`.** The bulk form replaces the whole set,
so one mistake there drops `OPENROUTER_API_KEY`, `CREDENTIALS_MASTER_KEY` and
the rest. `env-names-before.txt` and `env-names-after.txt` are the proof it did
not: the diff is three additions and zero removals.

## Before and after

Both bodies are saved verbatim, and that is safe by construction rather than by
inspection: `exporter_state` (`src/brief_crew/observability/__init__.py:54`)
deliberately omits the base URL and both keys, because `/readyz` is
unauthenticated and a URL can carry credentials in its userinfo. Its own
docstring says so.

**Before** — `readyz-before.json`, `2026-09-05T22:24:14Z`:

```json
{"exporter": "disabled", "reason": "LANGFUSE_EXPORT_ENABLED is off",
 "environment": "live", "capture_content": false, "resolve_billed_cost": false}
```

**After** — `readyz-after.json`, `2026-09-05T22:27:58Z`, HTTP 200:

```json
{"exporter": "enabled", "reason": null,
 "environment": "live", "capture_content": false, "resolve_billed_cost": true}
```

All four required answers hold: `exporter == "enabled"`,
`environment == "live"`, `capture_content == false`,
`resolve_billed_cost == true`. The last one is an *effective* answer rather than
a knob — it is `true` only because `OPENROUTER_API_KEY` is also set on this
service, since the generation lookup answers only for the key that made the
call.

`/healthz` answered 200 with `storage.backend: "postgresql"` and one worker
(`healthz-after.json`); the deploy did not disturb it.

> **A note on the timestamp in the brief that commissioned this.** It gave the
> before state as `2026-09-06T21:56:44Z`. The date is a day ahead of UTC — this
> machine is UTC+8, so a local clock reading 2026-09-06 sits at 2026-09-05Z —
> but the *time* is exact: `dep-dae8vd95efls739pg4kg`, the deploy this one
> replaced, finished at `2026-09-05T21:56:43.452734Z`. That probe was taken one
> second after the previous deploy went live. The observability object it
> reported is byte-identical to the one re-probed here at 22:24:14Z, so the
> before state is confirmed twice, independently, whatever the label said.

## Files

| File | What it is |
|---|---|
| `readyz-before.json` | the live `/readyz`, probed before anything was changed |
| `env-names-before.txt` | the 16 variable NAMES on the API service, before |
| `env-upsert.txt` | the three PUTs: name, HTTP status, value **length** |
| `env-names-after.txt` | the 19 NAMES after — the same 16 plus three |
| `deploys.json` | the newest three deploys, with the live one at the top |
| `readyz-after.json` | the live `/readyz`, after the deploy went live |
| `healthz-after.json` | `/healthz` on the same pass |
| `secret-scan.txt` | `scripts/observability/secret_scan.py` over this directory and `render.yaml` |

## What this does NOT prove, and it is the important half

**No run was launched on production, so no production trace has ever been seen
in Langfuse.** The exporter reports itself enabled from inside the process, and
that is exactly as far as this evidence goes. It is a statement about
configuration, not about delivery.

The gap is not laziness. `POST /api/sessions/{id}/runs` on this deployment
requires a **Google-signed-in user** — `AUTH_BASE_URL` is set, which turns
`VALIDATOR_REQUIRE_AUTH` on — and it is the endpoint that spends real money.
Neither half of that is something an agent should do unattended.

So the following are all still unproven on production:

- that a trace appears in the Langfuse project at all;
- that the trace carries the run id, the node identities and the per-generation
  fingerprints the contract describes;
- that billed-cost resolution actually resolves against OpenRouter from this
  host — `resolve_billed_cost: true` says the preconditions hold, not that a
  lookup has succeeded;
- that egress to `us.cloud.langfuse.com` is reachable from Render's singapore
  region at all. **A wrong or unreachable base URL would look exactly like this
  from `/readyz`**: the exporter reports enabled, the queue fills, the flush
  fails, and only the exporter's own counters and the process log would say so.

**Closing it is one signed-in run.** Launch one idea on
`https://agentic-crew-ai-studio.onrender.com`, then open the Langfuse project
and look for a trace carrying that run id. Until somebody does, "the exporter is
on in production" is the whole claim.

## One follow-up left undone

`docs/deploying.md` row 13a still reads *"Answers **0** on 2026-09-06:
`render.yaml` sets none of the fourteen `LANGFUSE_*` knobs"*. That command now
answers **3**, and the observability block below it still says the feature is
off in production. Both are stale as of this commit. The pass that made this
change was scoped to `render.yaml` and this directory, so the correction is left
for whoever owns that file rather than made half-way.
