# 15 — Persistence (save, autosave, versioning, import/export)

Written 2026-09-02 against `25634c0`. Owner: S1. Owns C10 (tables and
additive columns). Consumes C1 (03), C4 (01), C11 (08), C12 (07), C7 (10).

## Problem

Saving already works well, and the rest of the lifecycle does not exist.

What works: `useBuilderPersistence.ts` saves by compare-and-set
(`save()` `:431`, `expected_version` on the wire), autosaves after 2,500 ms
idle (`AUTOSAVE_IDLE_MS` `:47`, armed `:520-523`, suppressed with no id,
while saving, or under a conflict `:194-212`), turns a 409 into
`ConflictDialog` whose both resolutions go through `commit` so the loser is
one Ctrl+Z away (`:478-516`), keeps a `localStorage` draft under
`builder-draft:<id>` offered back only when `baseVersion === head_version`
(`:49`, `:293-326`), and guards `beforeunload` (`:532-537`). Server side,
`store.save` ignores the client's version and recomputes `expected + 1`
(`store.py:383-392`), decides on `UPDATE … WHERE version = expected` and
`rowcount` (`:408-428`), flips status to `draft` on every save (`:421`),
`mark_published` uses the same CAS (`:459-471`), rows are re-validated on
the way out (`:613-632`), `list` is SQL-scoped to the caller (`:293-297`), and
`published()` ignores ownership for the boot sweep (`:515-522`).

What does not exist:

- **Export / import.** Nothing writes a file and nothing reads one; the only foreign-document ingress is the system clipboard (`useBuilderClipboard.paste`).
- **Duplicate.** `⌘D` duplicates nodes, not documents; no route.
- **Version history.** `GET /workflows/{id}?version=` is accepted (`builder_api.py:462-475`) and `persistence.open(id, atVersion)` forwards it (`:380-384`), but no UI ever passes one, and there is no endpoint listing versions although `store.versions` exists (`:267`).
- **Delete from the UI.** `builderApi.remove` (`:243`) has no caller.
- **Every table this plan set needs.** No credentials, skills, MCP servers, custom tools or test inputs; `runs` has no `mode`.
- **Retention.** Terminal runs, their frames and metrics accumulate forever (CLAUDE.md closed item 32).
- **Concurrency proof.** Five compare-and-set paths — `pending_feedback`, the gate reply, `reopen_gate`, the orphan sweep, the document version — have never met two writers on PostgreSQL (CLAUDE.md remaining-work item 3).

## Scope

Export, import, duplicate, version history, delete, the `builder.flow/v1 →
v2` upgrade on read, the new tables and additive columns (C10), retention,
and the two-writer PostgreSQL test. The persistence half of rubric 14.

## Out of scope

- Real-time collaboration, presence, locking (cut-list 11).
- A migration tool. `_add_missing_columns` (`persistence.py:551-592`) stays additive-and-nullable only; the first backfill or `NOT NULL` is the point a real tool becomes cheaper (`:542-546`), and nothing here needs one.
- Encryption primitives and credential routes — 01 owns C4; this file owns only the table.
- Skill file storage on disk — 08 owns C11; this file owns the index row.

## Design

### D1 — Export strips secrets and identity, and is a document, not a backup

`GET /api/builder/workflows/{id}/export?version=` answers
`application/json` with `Content-Disposition: attachment; filename="<name>.builder.json"`:

```json
{ "export": "builder.flow/v2", "exported_at": "<iso>", "name": "<name>",
  "source_version": 7, "needs_credentials": ["search", "docs_mcp"],
  "document": { … } }
```

Before serialisation the document is passed through `strip_for_export()`
(`builder/export.py`, pure): every `credential_id` becomes `null` and the
node id is appended to `needs_credentials`; every `mcp` node keeps its
`server_id` as `null` plus a `server_hint` (label, transport, masked URL
`<origin>/************` — Flowise's masking); every `skill` node keeps
`skill_name` only. `id`, `version`, `budget` and `user_id` are dropped —
the importer mints its own. No header, no key, no token can be in the file
by construction, which is the property Flowise's `_removeCredentialId`
provides by recursion and we provide by schema (`docs/flowise-notes.md` §3).
`tests/builder/test_export.py` round-trips a document with every secret-bearing
field populated and asserts the JSON contains none of the values.

The client button lives in `DocumentBar`'s overflow menu and downloads
through the same blob-URL path `downloadLogs` already tests
(`frontend/tests/downloadLogs.spec.ts`).

### D2 — Import goes through the one load path

A file picker in the gallery (`TemplateGallery.vue`) and in `DocumentBar`
reads a `.builder.json`, validates the envelope client-side (`export ===
'builder.flow/v2'`, `document` present), and hands `document` to the same
`loadDocument` path a template and a clipboard paste use — one code path,
three entry points, exactly as Flowise does (`docs/flowise-notes.md` §3).
Import **always creates** a new draft owned by the importer; it never
overwrites. `needs_credentials` is rendered as a problem group ("3 nodes
need a credential you own") pointing at each node, so the document opens
honest rather than green. A v1 export imports through D5.

### D3 — Duplicate, versions, delete: three routes the UI was missing

| Route | Behaviour |
| --- | --- |
| `POST /api/builder/workflows/{id}/duplicate?version=` | 201, `Location`, a new `ug_` id, version 1, status `draft`, name `"<name> copy"`, owner = caller. Visibility is `_visible_to` (`store.py:602-610`): another user's document answers 404. |
| `GET /api/builder/workflows/{id}/versions` | `[{version, status, created_at, bytes}]`, newest first, from `store.versions` (`:267`), same visibility. |
| `DELETE /api/builder/workflows/{id}` | exists (`builder_api.py:518-536`); gains a UI caller with a confirm inside the docked rail (R15 — no modal), and refuses (409) while the head is `published` and registered, because a registered workflow with no document cannot be rehydrated (`builder_rehydrate.py:208-242`). Unpublish first. |

The version browser is a section of `DocumentBar`: pick a version, the
canvas opens it read-only (the `viewing head` precondition in
`PublishDialog.vue:94-131` already refuses to publish a non-head), **Restore**
commits it as the next head through the normal CAS save — one undo, one
version, never a rewrite of history.

### D4 — Autosave and drafts: unchanged, with one addition

The 2,500 ms idle autosave, the by-reference snapshot rule (`:416-429`,
`:444`), the draft envelope and the conflict flow stay exactly as they are;
`frontend/tests/builderPersistence.spec.ts` (33 tests) is the contract. One
addition: `onSaved` (added in the uncommitted working tree,
`:99-116`, `:449-452`) is kept and is what refreshes the version browser.

### D5 — `builder.flow/v1 → v2` upgrade on read

`builder/upgrade.py::upgrade_document(raw: dict) -> dict` is pure and
idempotent. It runs inside the store's re-validation path
(`store.py:613-632`) before `BuilderDocument.model_validate`, so every
stored v1 row parses as v2 without a rewrite; the next save writes v2. The
mapping is small because v1 is a subset: `schema` string; `tier` kept and
`llm: {model: <tier preset>}` added; `target_port` defaulted to `in`;
`joins` unchanged; `budget` dropped (re-priced). `tests/builder/test_upgrade.py`
upgrades every committed v1 fixture (`builderValidatorTemplate.json`, the
three template documents) and asserts `validate_document` is clean and
`upgrade(upgrade(x)) == upgrade(x)`.

### D6 — The tables (C10)

New tables are safe with `create_all()` — it creates any table that is
absent (`persistence.py:533-546`). Every table carries `user_id` and is
listed SQL-scoped, per FD9. Types are SQLAlchemy's; `JSON` is the existing
`JSON` column type used by `runs.inputs`.

**`user_credentials`** (01 owns the routes and crypto)

| column | type | notes |
| --- | --- | --- |
| `id` | String(128) PK | `cred_` + 16 hex |
| `user_id` | String(128) NOT NULL | no FK, as `runs.user_id` (`persistence.py:235-239`) |
| `kind` | String(32) NOT NULL | `openrouter, firecrawl, serper, tavily, exa, brave, github, e2b, http_header, mcp_header, postgres` |
| `label` | String(80) NOT NULL | |
| `ciphertext` | LargeBinary NOT NULL | AES-GCM |
| `nonce` | LargeBinary NOT NULL | 12 bytes, unique per row |
| `key_version` | Integer NOT NULL default 1 | rotation |
| `created_at`, `updated_at` | DateTime NOT NULL | |
| `last_used_at` | DateTime | |

Indexes: `ix_user_credentials_user_kind (user_id, kind)`; unique
`(user_id, label)`.

**`user_skills`** (08 owns the files)

| column | type | notes |
| --- | --- | --- |
| `id` | String(128) PK | `skill_` + hex |
| `user_id` | String(128) NOT NULL | |
| `name` | String(64) NOT NULL | CrewAI's `SKILL_NAME_PATTERN` |
| `description` | String(1024) NOT NULL | from frontmatter |
| `path` | String(255) NOT NULL | relative to the skills root |
| `bytes` | Integer NOT NULL | |
| `created_at`, `updated_at` | DateTime NOT NULL | |

Indexes: unique `(user_id, name)`; `ix_user_skills_user_updated (user_id, updated_at)`.

**`mcp_servers`** (07 owns discovery)

| column | type | notes |
| --- | --- | --- |
| `id` | String(128) PK | `mcp_` + hex |
| `user_id` | String(128) NOT NULL | |
| `label` | String(80) NOT NULL | |
| `transport` | String(8) NOT NULL | `stdio` / `sse` / `http` |
| `url` | String(2048) | remote transports |
| `command` | String(255) | stdio only |
| `args` | JSON | list of strings |
| `header_credential_id` | String(128) | → `user_credentials.id`, no FK |
| `env_credential_id` | String(128) | stdio env |
| `status` | String(16) NOT NULL | `pending` / `authorized` / `error` |
| `discovered_tools` | JSON | `[{name, description, input_schema}]` |
| `discovered_at` | DateTime | |
| `last_error` | Text | |
| `created_at`, `updated_at` | DateTime NOT NULL | |

Index: `ix_mcp_servers_user_updated (user_id, updated_at)`.

**`user_tools`** (06 owns the declarative custom tool)

| column | type | notes |
| --- | --- | --- |
| `id` | String(128) PK | `tool_` + hex |
| `user_id` | String(128) NOT NULL | |
| `name` | String(64) NOT NULL | snake case |
| `description` | String(1024) NOT NULL | |
| `input_schema` | JSON NOT NULL | properties, types, required |
| `request` | JSON NOT NULL | `{url, method, headers_template, body_template}` |
| `credential_id` | String(128) | header credential |
| `created_at`, `updated_at` | DateTime NOT NULL | |

Indexes: unique `(user_id, name)`.

**`builder_test_inputs`** (13 owns the panel)

| column | type | notes |
| --- | --- | --- |
| `id` | String(128) PK | `ti_` + hex |
| `user_id` | String(128) NOT NULL | |
| `document_id` | String(128) NOT NULL, FK `builder_documents.id` ON DELETE CASCADE | |
| `label` | String(80) NOT NULL | |
| `inputs` | JSON NOT NULL | the run `inputs` body |
| `node_mocks` | JSON | `{node_id: out value}` for single-node tests |
| `created_at`, `updated_at` | DateTime NOT NULL | |

Index: `ix_builder_test_inputs_document_updated (document_id, updated_at)`.

**Additive column** — `("runs", "mode", "VARCHAR(16)")` appended to
`_ADDITIVE_COLUMNS` (`persistence.py:547-549`), nullable, read as `run` when
`NULL`; values `run / test / node_test` (C7). `tests/service/test_additive_migration.py`
gains the case: a `runs` table created without `mode` gets it on `init_db`,
the pre-existing row reads as `run`, a second `init_db` is a no-op.

Known gap carried, not fixed: `_add_missing_columns` re-ensures indexes on
`runs` only (`persistence.py:584-592`); a new index on a shipped table would
need its own entry there. None of the tables above is shipped, so
`create_all` creates them with their indexes.

> **Amended 2026-09-03 (round 2, D-15-3) — a second additive column, C10.**
> `("builder_document_versions", "source", "VARCHAR(64)")` is appended to
> `_ADDITIVE_COLUMNS`, nullable, read as `stored` when `NULL`. It carries how
> a version came to be — `created`, `saved`, `autosaved`, `restored from v3`,
> `imported`, `duplicated` — for the version browser, whose rows round 1 found
> indistinguishable at minute resolution. `builder_document_versions` shipped
> on 2026-09-02 (`b4ef654`), so `create_all` never adds this column to a
> deployed database; the additive path is the only way it arrives, and
> `tests/service/test_additive_migration.py::VersionSourceColumnTests` builds
> the table as it shipped and asserts the upgrade. Nothing is backfilled. The
> client declares one of `BUILDER_VERSION_SAVE_SOURCES` on a save and the
> server composes the stored string; the label beside it (`name`,
> `node_count`) is read leniently off the stored row and needs no column.
> Recorded against C10 in `00-architecture.md`.

### D7 — Retention

`VALIDATOR_RUN_RETENTION_DAYS` (int, default `0` = keep forever, read in
`config.py`, added to the §6 knob scan — it will be the fortieth) drives a
purge in the same periodic sweep the orphan recovery uses
(`VALIDATOR_ORPHAN_RUN_GRACE_SECONDS`): terminal runs older than the window
are deleted, and `run_frames`, `run_node_metrics`, `run_gates` follow by the
existing `ON DELETE CASCADE`. Documents, versions, credentials, skills and
tools are never purged. The purge logs a count and never runs while a run is
`waiting` on a gate it would delete.

### D8 — Two writers on PostgreSQL

`tests/pg/test_two_writers.py` is skipped unless `TEST_DATABASE_URL` is set.
Each of the five paths spawns two processes (`multiprocessing`, not threads
— SQLAlchemy pools are per process) that race the same row from a barrier and
asserts **exactly one** `rowcount == 1` and the other side's typed refusal:

| Path | Winner | Loser sees |
| --- | --- | --- |
| `pending_feedback` write | one insert | integrity error → handled as already-pending |
| gate reply (`answer_gate`) | one CAS | 409 |
| `reopen_gate` rollback | one CAS | no-op, gate already open |
| orphan sweep adopt/fail | one CAS | row already terminal |
| document `save` | one CAS | `DocumentVersionConflict` → 409 |

Local recipe, documented in the test's docstring:

```powershell
docker run --name pg18-test -e POSTGRES_PASSWORD=test -p 5433:5432 -d postgres:18
$env:TEST_DATABASE_URL = "postgresql+psycopg://postgres:test@127.0.0.1:5433/postgres"
.\.venv\Scripts\python.exe -m unittest tests.pg.test_two_writers
```

`builder/store.py` was written to match the four older paths so that one
test covers all five (CLAUDE.md remaining-work item 3); this is that test.

### D9 — Isolation, the persistence half of rubric 14

A matrix test, `tests/service/test_isolation_matrix.py`, runs every route
in this file as user A, user B and anonymous against a document, a version,
a duplicate, an export, an import and a test input owned by A, with auth on:

| Route | A | B | anonymous |
| --- | --- | --- | --- |
| list | sees it | does not see it | 401 |
| get / versions / export | 200 | **404** | 401 |
| save / delete / duplicate | 200 / 204 / 201 | **404** | 401 |
| import | 201, owner A | 201, owner B, no reference to A's id | 401 |
| test inputs | 200 | **404** | 401 |

B's import of A's exported file must produce a document that contains no
`ug_` id, credential id, server id or skill id from A — the file cannot
carry them (D1). The unowned-row carve-out (`store.py:602-610`) is asserted
too: a row with `user_id IS NULL` is readable by both and by anonymous when
auth is off, because refusing it would destroy pre-auth history.

> **Amended 2026-09-03 (round 2, D-15-7 and D-15-12).** Two things the table
> above did not say, recorded beside it rather than edited into it, so the
> earlier wording stays visible.
>
> 1. **The unowned row has a row per verb.** Round 1 found that "readable by
>    everyone" had silently become "controllable by everyone": `_visible_to`
>    was the sole gate on save, publish and delete. The rule is now that an
>    unowned document is readable and launchable by everyone and writable by
>    nobody who has an identity; `store._writable_by` is the second gate,
>    and the refusal is a **403** naming Duplicate — safe here, and only
>    here, because an unowned row is visible to everyone already. On a
>    backend with an auth server configured no caller can create an unowned
>    row (401 on create, import and duplicate for nobody-at-all); under
>    `SYNTHETIC` and a bare local checkout creation stays open, and the
>    anonymous caller keeps write there because they are the only author
>    that deployment has. Foreign owned documents keep their 404, which is a
>    different rule with its own reason.
>
>    | Route, unowned row | A | B | anonymous, auth on | anonymous, auth off |
>    | --- | --- | --- | --- | --- |
>    | list | not listed | not listed | 401 | listed |
>    | get / versions / export | 200 | 200 | 401 | 200 |
>    | duplicate | 201, owner A | 201, owner B | 401 | 201, unowned |
>    | save / publish / delete | **403**, names Duplicate | **403**, names Duplicate | 401 | 200 / 200 / 204 |
>    | launch (published) | 202 | 202 | 401 | 202, or plan 01's gateless-graph 403 |
>    | create an unowned row | impossible | impossible | 401 | 201 |
>
> 2. **The test-inputs row is asserted at the table level, and the table now
>    says so.** Stage 1 has no test-inputs route — plan 13 owns the panel —
>    so `tests/service/test_isolation_matrix.py::TestInputsTable` asserts what
>    the table can be asserted at: `builder_test_inputs.user_id` is NOT NULL,
>    the only read is a query scoped to its owner, and the rows go with their
>    document on delete. Criterion 10's "exactly" is measured against this
>    note; the route asserts the same three things the day it exists. Round 1
>    (D-15-12) was right that a narrowing declared only in the Status table
>    is a narrowing the contract does not carry.

## Interfaces

**Owned — C10:** the six tables and one additive column in D6, verbatim.
Any plan needing a column not listed here requests it through 00.

**Owned — routes:** `GET …/export`, `POST …/duplicate`, `GET …/versions`,
the import client path; `builder/export.py::strip_for_export`,
`builder/upgrade.py::upgrade_document`; the export envelope in D1.

**Consumed:** C1 (which fields are secret-bearing — `credential_id`,
`server_id`, `skill_id` — comes from 03's schema), C4 (credential ids are
opaque strings here), C7 (`runs.mode` values), C11 / C12 (row shapes agreed
with 08 / 07).

## Acceptance criteria

1. `tests/builder/test_export.py`: an exported document with every secret-bearing field set contains none of their values, and `needs_credentials` names every stripped node. Rubric 14, forbidden-list "credentials in exports".
2. Import of that file as user B creates a draft owned by B with a fresh `ug_` id and a problem group naming each `needs_credentials` node — `tests/service/test_builder_import.py`. Rubric 14.
3. `POST …/duplicate` on another user's document answers 404; on one's own answers 201 with version 1 and `draft` — `tests/service/test_builder_duplicate.py`. Rubric 14.
4. The version browser opens a prior version read-only and Restore creates head + 1 through the CAS — `frontend/tests/versionBrowser.spec.ts` plus an `e2e/builder.spec.ts` step. Rubric 4.
5. Delete from the UI removes the row and its versions (`ON DELETE CASCADE`, `persistence.py:263-275`) and refuses 409 while published-and-registered. Rubric 12.
6. `tests/builder/test_upgrade.py`: every committed v1 fixture upgrades to a clean v2 document; upgrade is idempotent. Rubric 11.
7. `tests/service/test_additive_migration.py` covers `runs.mode`; `create_all` on a database that already has `runs` yields all six new tables with their indexes — asserted with the inspector. Rubric 16.
   *Amended 2026-09-03 (D-15-11):* **five** new tables plus `runs.mode`,
   not six. D6 declares five — `user_credentials`, `user_skills`,
   `mcp_servers`, `user_tools`, `builder_test_inputs` — and `GAUNTLET_TABLES`
   (`service/persistence.py`) and
   `test_all_five_tables_arrive_with_their_indexes_and_constraints` both say
   five; "six" counted the additive column as a table. The Status table
   recorded the correction on 2026-09-03 and left this sentence unamended,
   which round 1 was right to refuse: a criterion ticked "done" over a false
   sentence is a contract nobody can hold anyone to. The earlier wording
   stands above so the correction is visible. (D-15-3 has since added a
   second additive column, `builder_document_versions.source`; the count of
   tables is unchanged.)
8. The knob scan in CLAUDE.md answers forty after `VALIDATOR_RUN_RETENTION_DAYS` lands, and `docs/tech-stack.md` §6 is regenerated in the same commit. Rubric 16.
   *Amended 2026-09-03 (D-15-12):* the scan answers **41**, and
   `docs/tech-stack.md` §6 says forty-one (`52bdc2e`). "Forty" assumed one
   new knob over thirty-nine; Stage 1 landed the six config knobs of S1
   ruling 3 before the count was regenerated, and the criterion was ticked
   against the prose rather than the scan. Re-run on 2026-09-03 while
   building round 2, with no knob added or removed by it: **41**. The
   command is the contract; the earlier wording stands above.
9. `tests/pg/test_two_writers.py` passes against PostgreSQL 18 for all five paths, and CI gains a `services: postgres:18` job that sets `TEST_DATABASE_URL`. Rubric 11, 14.
10. `tests/service/test_isolation_matrix.py` passes with the table in D9 exactly. Rubric 14.
    *Amended 2026-09-03 (D-15-12):* "the table in D9" means the table **and
    its dated amendment** — the unowned row per verb, and the test-inputs row
    asserted at the table level until plan 13's route exists. The test's own
    docstring carries the same two tables.
11. `frontend/tests/builderPersistence.spec.ts` (33) passes unchanged. Rubric 16.

## References

- `frontend/src/composables/useBuilderPersistence.ts:37-49, 99-116, 194-212, 293-326, 380-384, 416-466, 478-537`.
- `src/brief_crew/builder/store.py:79-85, 267, 293-297, 337-345, 374-444, 459-471, 515-522, 561-591, 602-632`.
- `src/brief_crew/service/builder_api.py:415-629, 689-743`; `builder_rehydrate.py:208-242`.
- `src/brief_crew/service/persistence.py:71-86, 122-166, 235-275, 528-592`.
- `frontend/src/components/builder/{PublishDialog.vue:94-131, ConflictDialog.vue:13-25, TemplateGallery.vue, DocumentBar.vue}`.
- `docs/flowise-notes.md` §3 (export whitelist, `_removeCredentialId`, one load path), §4 (URL masking).
- `docs/gotchas-and-insights.md` 14 (`create_all` never alters a shipped table), 22.
- CLAUDE.md closed item 32 (no retention), remaining-work item 3 (five CAS paths, no two-writer test), §10.
- Gauntlet Stage 2 "Error handling" (graceful stream failure: completed step history survives — the frame table already does this), rubric 14.

## Status

**Planned · 2026-09-02.**

Contract requests for 00: none. C10 as written here is the contract; 01,
06, 07, 08 and 13 consume their rows from D6 and must not add columns
without an entry here.

Open decisions for the owner: (1) `VALIDATOR_RUN_RETENTION_DAYS` default —
`0` keeps everything, which is the deployed behaviour today; (2) whether
delete of a published document should unpublish automatically instead of
refusing; (3) whether CI should run the PostgreSQL job on every push or only
on `main`.

**Criteria complete · 2026-09-03.** Built on `s1/15-api` (`9f6e63b`) and
`s1/15-ui` (`831ae6b`), integrated on `gauntlet/plans` at `18a7944`. **No
judge round has run**; PLANS.md carries the status. Every row below was
measured on the integrated tree.

| # | State | Where |
| ---: | --- | --- |
| 1 | done | `tests/builder/test_export.py` (38) — plus `tests/service/test_builder_export_route.py` (13) for the route and the two `Content-Disposition` forms |
| 2 | done | server `tests/service/test_builder_import.py` (21); client `frontend/tests/builderImport.spec.ts` (9). `needs_credentials` is **re-derived**; the envelope's list is accepted and ignored |
| 3 | done | `tests/service/test_builder_duplicate.py` (16) |
| 4 | done, run | `frontend/tests/versionBrowser.spec.ts` (23) and the `e2e/builder.spec.ts` step, green in the 33-test run of 2026-09-03 |
| 5 | done | server `tests/service/test_builder_delete.py` (11); client `frontend/tests/documentLifecycle.spec.ts` (10). Delete cascades `builder_test_inputs` explicitly, because SQLite honours no FK pragma |
| 6 | done | `tests/builder/test_upgrade.py` (12) — the Stage 1 hook, per S1 ruling 5 |
| 7 | done, one correction | `tests/service/test_additive_migration.py` (19). The criterion says **six** new tables; the DDL and S1 ruling 2 have **five** plus `runs.mode`. The test is right |
| 8 | done | `docs/tech-stack.md` §6 regenerated at 41 (`52bdc2e`) |
| 9 | done, **run against PostgreSQL 18.6, 5/5** | `tests/pg/test_two_writers.py`, one throwaway database per test; skips cleanly without `TEST_DATABASE_URL`; CI job `postgres` on `main` only (decision 25) |
| 10 | done, one scope note | `tests/service/test_isolation_matrix.py` (16). The **test-inputs row is covered at the table level** — `user_id NOT NULL`, owner-scoped SELECT, cascade on delete — because Stage 1 has no route; plan 13 owns it |
| 11 | done | `frontend/tests/builderPersistence.spec.ts` unchanged, 33/33 |
| D7 | done | `tests/service/test_run_retention.py` (24) — same tick as orphan recovery, after it; never a `waiting` run, never a terminal run with an unanswered gate, never a document |

What the build found that the plan did not know:

- **The orphan sweep was not a compare-and-set.** D8's table and CLAUDE.md
  remaining-work item 3 both list it as one; `_fail_interrupted` went through
  `update_run_status`, which guards on `id` alone, so two instances — a deploy
  overlapping its predecessor — would both reconcile one run. Now
  `claim_run_status`; the loser drops its stale copy and counts nothing
  (`tests/service/test_orphan_sweep_claim.py`, 12). The adopt path is
  deliberately unclaimed: idempotent, and the reply is guarded by
  `answer_gate`.
- **A losing `save` reported the pre-CAS version** — "is at version 1, not 1;
  reload it" — reachable only with two real writers. `store.save` and
  `mark_published` now re-read the head inside the transaction.
- **Two defects only the merged tree could show**, both fixed at integration:
  `strip_for_export` noted a node on the credential KEY alone, and since S1
  ruling 8 every agent node serialises `credential_id: null`, so a clean export
  reported `needs_credentials: ['scoper']` (merge commit `348af34`; one test
  pins the null default). And the post-save draft was written from the local
  copy, which no longer fingerprints equal to the server's defaulted one, so
  the restore bar offered the version on screen after a reload; the draft is
  now written from the response when nothing changed during the round trip
  (`frontend/tests/builderDraftCanonical.spec.ts`, 3; `e62235a`).
- D2 is built as a **server route** with a client-side notice, per S1 ruling
  7; D3's delete confirm is a strip docked under the document bar, in the
  layout, never an overlay. An export of an unsaved draft is refused with a
  sentence rather than written from nothing.
- `BuilderView.vue` and `ProblemsPanel.vue` carried literal NUL bytes in
  their dedup keys and were **binary to git** — every merge of the file every
  branch touches conflicted as a whole. Spelled as escapes now (`5ebe001`).
- `GET …/versions` can show the published head and an older still-registered
  version both as `published`; the client never sorts, the server answers
  newest first.
- Decisions 23–25 are built on their recommendation and stay open.

**In judge · round 1 scored 2026-09-03** (`benchmarks/rounds/15-1.md`): dim 4 =
**7** against Flowise 3.1.4 at 3 (blind); the engineering critic's scores for
dims 11, 12, 14 and 16 are in the round file; gate 8 not met; 12 located
defects open in `benchmarks/DEFECTS.md` as D-15-1 … D-15-12 (visual first,
then engineering), which is the round-2 build list.

**In build (round 2) · 2026-09-03.** Every row has a fixing commit on
`gauntlet/plans` and every row stays **open**: closing one is the critic's,
after it re-runs each command itself. One commit per id, in build order:
D-15-7 `95dfd70` (the store's write gate; D9 amended, criterion 10 note),
D-15-8 `a324aa0`, D-15-9 `c44deaf`, D-15-10 `9e85e9f` (decision 24 built:
unpublish route, delete guard on the registration), D-15-1 `e27a1f4`,
D-15-2 `569198f`, `fa6829f`, then `b249d89` (the re-fit follows the dock
row the author opens, not any shrink - the first cut re-fitted under the
problems panel and moved the canvas under a drag, 2 of 6 E2E runs - and the
dock is observed when its template ref arrives, which the round-2 capture
showed the second cut did not), D-15-3 `57246b8` then `d9672a0` (a second
additive column, C10; then the relative time reads a real clock and a naive
SQLite stamp as UTC, both found by the capture), D-15-4 `6b25a5b` then
`7cf3326` (the palette name takes the row's width; the browser measurement
said two lines beside the meta were not enough), D-15-5 `9555fb6`, D-15-6
`4a1f328`, D-15-11 `c6d4038`, D-15-12 `3e988b4`. Where an id has more than
one commit the LAST is the one a "closed by" should name; the earlier ones
are kept because their messages record the measurement that corrected them.
Captures for the six visual rows are under `docs/comparison/ours/round2/`
(ignored by the `*.png` rule), taken by the untracked
`frontend/e2e/_round2_capture.spec.ts` at 1440x900 dark. The visual rows each carry a jsdom assertion where one
holds; the wrap and the reachable last row of D-15-4 are measured in
`e2e/builder-layout.spec.ts`, and every visual row is for the critic to
re-capture at 1440x900 dark.

**In judge · round 2 scored 2026-09-03** (`benchmarks/rounds/15-2.md`, persona
staff frontend engineer): dim 4 = **7** against Flowise 3.1.4 at 4 (blind),
dim 11 = **10**, dim 12 = **6**, dim 14 = **10**, dim 16 = **7**; gate 8 not
met. A row verifier re-ran all twelve round-1 rows and found every defect
absent as written (two partly). Five rows closed (D-15-1, -3, -5, -6, -7),
two stay open landed again with a new sentence (D-15-2, -4), five stay open
held by a dimension under its reference (D-15-8 … -12), and ten new rows
opened (D-15-13 … D-15-22): **17 open**, the round-3 build list, read top
to bottom. Round 3's critic is the CrewAI power user.
