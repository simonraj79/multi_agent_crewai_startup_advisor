# `secret-scan.txt`, triaged — every WARN accounted for

Run by V-PROOF at the end of the Task 3 proof session, 2026-09-06, over
`docs/observability/evidence/proof` (162 text files, 12 binary), with the values
of eleven credential variables loaded from `.env` and the environment and
compared, never printed.

```text
FAIL - actual credential values found: 0
WARN - credential-shaped prefixes:     74 (of which token-shaped: 62)
VERDICT: PASS
```

`secret-scan.txt` on disk is the **final** run, made with the scanner as revised
at `58a1c0b`, over all three passes — 309 text files and 17 binaries:

```text
FAIL - actual credential values found: 0
WARN - credential-shaped prefixes:     68 (of which token-shaped: 52)
VERDICT: PASS
```

`actual credential values found: 0` has been the answer in every run of this
scan, which is the line F3 is about.

**Two things about that number changed at `58a1c0b`, and both were defects this
file previously had to explain away:**

1. **The report can no longer re-match itself.** Running the identical command
   twice in a row now gives `68` both times. Before, each run counted the
   previous report's own rendered warnings, so the total climbed — 74, then 156,
   then 461 — over a directory whose credential count never moved off zero.
2. **`fc-` no longer matches inside a UUID.** `validator-live-2`'s run id
   contains `fc-`, so it produced **358** warnings on its own — 179 in
   `app-frames.ndjson` and 179 in the `frames.ndjson` copy, one per frame. They
   are gone.

What remains, counted rather than guessed:

| file | WARNs | what |
| ---: | ---: | --- |
| `capture-on/app-frames.ndjson` + its `frames.ndjson` copy | **27 + 27** | the planted fake `sk-or-v1-0…0`, which is the point of that run |
| `capture-on/{app-run.json, request.json, README.md}` | 5 | the same plant, at its source and in the prose describing it |
| this file, `VERDICTS.md`, `PLAN.md`, the two `inject.md`s | 9 | the literal prefixes written out in sentences |

Every one is a shape in a document that exists to talk about shapes. The table
below enumerates the pass-1 sources, and is kept because the `fc-`-inside-a-UUID
entry is the first record of a defect that took two more passes to close.

**F3's own question — "does any committed artifact contain a credential value" —
answers no.** The 74 WARNs are shapes. All of them are one of four things:

| what | where | why it is not a credential |
| --- | --- | --- |
| `sk-or-v1-` + 64 zeros | `capture-on/{request.json,frames.ndjson,app-frames.ndjson}` and `capture-on/README.md` | the **planted fake key** B5's capture half exists to redact. It is sixty-four `0` characters and authenticates against nothing. Its presence in the app's own frames and absence from every `langfuse-*.json` in that directory is exactly the evidence the row wants |
| `sk-or-<3 or 4 chars>` in prose | `PLAN.md`, `capture-on/README.md`, `VERDICTS.md` | the literal prefix written out in a sentence describing the plant |
| `fc-<17 chars>` | `validator-live/{app-frames,frames}.ndjson` lines 141-144 | **a false positive inside a UUID.** The match is the middle of `agent_id: "338eb374-d34e-4bfc-9ec2-11d22c2a6355"` — the scanner sees `fc-9ec2-11d22c2a6355` where the text reads `…4bfc-9ec2…`. Nothing Firecrawl-shaped is in any frame |
| `sk-lf-` / `pk-lf-` | none in this tree | the write-time redactor in `scripts/observability/_common.py` replaced `metadata.scope.attributes.public_key` before `json.dump`, so smoke-live's blocker D1 did not recur: every `pull_langfuse_run.py` and `membership_check.py` invocation printed a redaction count and every `langfuse-*.json` here carries `<redacted>` in that field |

## Two further checks this scanner does not make

1. **The bearer JWT.** `secret_scan.py` does not know about the identity token, so
   it was grepped for by hand: `grep -rl "eyJ"` over
   `docs/observability/evidence/proof/` returns exactly two paths, and neither is
   a token — `identity/transcript.txt:27` is the *sentence* "grep -c eyJ over
   this directory answers 0 for every file" (that file's own prose defeats its
   own claim, harmlessly), and `validator-live/B6-scores-project-surface.png` is
   a three-byte coincidence inside PNG deflate data. No JWT was written to any
   file: the token lived in a scratch file outside the repository for the length
   of the session and was deleted with it.
2. **The Ed25519 private key.** It never was inside the repository —
   `mint_identity.py` refuses any path in it — and
   `%TEMP%\brief-crew-proof-identity\` was removed at the end of the session, so
   every token minted for these runs is now unverifiable as well as expired.
