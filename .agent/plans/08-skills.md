# 08 — Skills

## Problem

"Skills = knowledge." A skill gives an agent domain knowledge without
bloating its prompt: the name and description load at run start, and the
body loads only when a task matches. That is not a feature to build — it
is a feature to expose. CrewAI 1.15.18 implements it natively:

```python
Agent.skills: list[Path | Skill | str] | None      # and Crew.skills
```

with `SkillFrontmatter` (`crewai/skills/models.py:43-63`: `name` 1–64
chars, lowercase alphanumeric and hyphens; `description` 1–1,024;
`license`, `compatibility`, `metadata`, `allowed_tools`), a `Skill` model
carrying `disclosure_level`, and three levels defined at `models.py:25-35`:
`METADATA = 1` (frontmatter only), `INSTRUCTIONS = 2` (body loaded),
`RESOURCES = 3` (`scripts/` / `references/` / `assets/` catalogued). The
loader does the promotion (`crewai/skills/loader.py:44` `discover_skills`
at METADATA, `:120` `activate_skill` → INSTRUCTIONS, `:281` `load_resources`
→ RESOURCES), and `crewai/skills/tool.py:58` is where an agent activates a
skill on demand during execution — the "body loads only when a task
matches" behaviour, already in the package.

Nothing in this repository uses any of it, and the two things in the tree
that look like skills are not: `.agents/skills/` and `.claude/skills/` are
vendored MIT CrewAI **developer** skills for the coding agent
(`docs/licensing.md`), not user-attachable packs.

Two package facts constrain the design: a `str` that is not a path is a
**registry reference** to CrewAI AMP (`is_registry_ref`,
`resolve_registry_ref` in `crewai/skills/registry.py`), so user input is
always passed as a `Path`; and Render's disk is ephemeral, so a file on
disk is a cache and a database row is the truth.

## Scope

- Per-user skill packs: a `user_skills` table holding the `SKILL.md` body, materialised to disk under `SKILLS_ROOT` when a run needs it.
- Endpoints to list, create from pasted markdown, update, delete, and import from a zip.
- A built-in library of four skills this repository owns, offered to every user.
- The `skill` attachment node `{skill_id}` and its card.
- Run-time attachment as `Path`s on `Agent.skills` (and `Crew.skills` for crew nodes), with the package's own disclosure.
- Skill events mapped to frames.

## Out of scope

- `scripts/` in a skill pack. A script is code, and `AGENTS.md:67` stands; refused at import.
- `references/` and `assets/` in v1. The row holds one file. Multi-file packs are v2 (Status).
- Sharing skills between users, a marketplace, or AMP registry references.
- Skills as knowledge sources (`Agent.knowledge_sources`). Different primitive, different plan.

## Design

### D1 — The row is the truth; the disk is a cache

`user_skills.body` holds the `SKILL.md` text (≤ `MAX_SKILL_BYTES = 64 KiB`,
which is also `persistence.MAX_STRING_LENGTH` — `_sanitize_json` raises
above it, so a larger cap would lose the row at write time, the same trap
CLAUDE.md §9 records for the run result). `builder/skills.py::materialise(skill_id)`
writes `SKILLS_ROOT/users/<user_id>/<name>/SKILL.md` if absent or stale
(compared by `updated_at`) and returns the directory `Path`. Boot does not
pre-materialise; the first run that attaches a skill does. A restart
therefore costs one file write, not a lost skill — the `builder_rehydrate`
lesson applied by construction rather than by a sweep.

### D2 — Parse with the package's parser, refuse with its error

`POST /api/builder/skills` accepts `{body}` and runs
`crewai.skills.parser.parse_frontmatter` (`parser.py:39`) then validates
`SkillFrontmatter`; a `SkillParseError` (`parser.py:35`) or a pydantic
error is a 422 carrying the parser's own sentence. `name` comes from the
frontmatter, is unique per user, and is the directory name — so the
package's name pattern is the only pattern, and there is no second
validator to drift. `version` is `metadata.version` when present, else
`1`, and increments on every `PUT`.

### D3 — Four built-in skills the repository owns

Derived from prompts this repository already owns in
`crews/validator_crew/config/{agents,tasks}.yaml` and the ratified rubric
(`docs/rubric-ratification.md`), shipped under `data/skills/builtin/`:

| `name` | What it teaches | Source it is distilled from |
| --- | --- | --- |
| `market-research-method` | write 2–4 keywords specific-to-broad; read a tool envelope; record source URL, date, and whether the date is retrieval time | `tasks.yaml` `market_task`; CLAUDE.md §6 (query shape) |
| `hn-signal-reading` | classify a thread as PROBLEM / OPINION / OFF_TOPIC with the ratified definitions; count usable threads; never infer demand from points alone | `tasks.yaml` `sentiment_task` (C7 definitions) |
| `evidence-citation` | every claim cites a URL the tools returned; unknown → say so; no invented links | `validator_guardrails.py` URL-closure rules |
| `report-writing` | the Markdown subset the console renders — headings, lists, links, code spans; no tables, no HTML | `tasks.yaml` `reporting_task`; `frontend/src/utils/markdown.ts` |

Built-ins have `user_id = NULL`, are visible to everyone, cannot be edited
or deleted through the API, and are seeded by `init_db` from the files
(idempotent, keyed on name). The gauntlet's "users can write their own or
install one" is satisfied by D2 and the import route; the built-ins make
a fresh account's palette non-empty.

### D4 — Attach as a `Path`, let the package disclose

`runtime:run_agent` receives `skills: [skill_id]` (FD10), loads each row
with the run user's ownership check (built-ins pass for everyone),
materialises, and passes `[Path, …]` to `Agent(skills=…)`; a crew node
passes the same to `Crew(skills=…)`. The package loads each at `METADATA`,
lists name and description in the agent's context
(`format_skill_context`, `loader.py:293`), and promotes to `INSTRUCTIONS`
when the agent activates it (`skills/tool.py:58`). The product adds
nothing to that path — the whole value is that the disclosure is the
package's, so a CrewAI upgrade that improves it improves the product.

### D5 — The card says what a skill is, and the palette keeps the three apart

The palette groups attachments under three headings with one line each —
**Tools** *"hands: search, fetch, query"*, **Skills** *"knowledge: how to
do a job well"*, **MCP** *"extensibility: any server's tools"* — so the
distinction the gauntlet calls the product's clearest idea is on screen
where the choice is made. A `skill` card shows the name, the first
sentence of the description, `v<version>`, and a *"built-in"* or *"mine"*
chip; the inspector shows the full description and a read-only render of
the body through the console's escape-first Markdown renderer
(`frontend/src/utils/markdown.ts`), because a skill body is untrusted text
the same way a report is.

### D6 — Events become frames

`SkillLoadedEvent`, `SkillActivatedEvent`, `SkillUsedEvent` and
`SkillLoadFailedEvent` (`crewai/events/types/skill_events.py:44-65`) map
to AGENT frames with `details.skill = <name>` and
`details.disclosure ∈ {metadata, instructions, resources}`, so the run
console can show *"activated skill hn-signal-reading"* on the agent's
card — the one moment a skill is visibly doing something.
`SkillLoadFailedEvent` also produces a `node_error` frame (C6) with
`error_class = "skill_load"`; it does not fail the step, because a missing
skill degrades an agent rather than breaking it.

## Interfaces

### C11 — skill package layout and API (owned here)

On disk (`SKILLS_ROOT`, default `data/skills`, env-overridable):

```text
data/skills/builtin/<name>/SKILL.md           committed, this repository's
data/skills/users/<user_id>/<name>/SKILL.md   materialised cache, git-ignored
```

`SKILL.md` = YAML frontmatter (`name`, `description`, optional `license`,
`compatibility`, `metadata: {version: "1"}`, `allowed_tools`) + Markdown
body, exactly as `crewai/skills/parser.py:76` reads it.

`user_skills` table (new; safe with `create_all()`):

| Column | Type | Note |
| --- | --- | --- |
| `id` | String(32) PK | `sk_[0-9a-f]{12}` |
| `user_id` | String(128) | NULL for built-ins; index `(user_id, updated_at)` |
| `name` | String(64) NOT NULL | frontmatter name; unique `(user_id, name)` |
| `description` | String(1024) NOT NULL | |
| `version` | Integer NOT NULL | |
| `body` | Text NOT NULL | ≤ 64 KiB |
| `size_bytes` | Integer NOT NULL | |
| `created_at`, `updated_at` | DateTime NOT NULL | |

Endpoints (authenticated; built-ins readable anonymously in `SYNTHETIC` /
local mode like unowned documents; 404-not-403):

| Method | Path | Body → result |
| --- | --- | --- |
| `GET` | `/api/builder/skills` | `{skills: [{id, name, description, version, owner ∈ builtin\|me, size_bytes, updated_at}]}` — no body |
| `GET` | `/api/builder/skills/{id}` | the row with `body` |
| `POST` | `/api/builder/skills` | `{body}` → 201; 422 with the parser's sentence on a bad frontmatter |
| `PUT` | `/api/builder/skills/{id}` | `{body}` → 200, `version + 1`; 404 for a built-in |
| `DELETE` | `/api/builder/skills/{id}` | 204; documents referencing it validate with `skill-unknown` thereafter |
| `POST` | `/api/builder/skills/import` | multipart zip ≤ 256 KiB containing one `SKILL.md`; any `scripts/` entry → 422 `skill-contains-scripts` |

### `skill` node config (C1, owned by 03 — required shape)

`{ "skill_id": "sk_…" }`. At most `MAX_ATTACHMENTS_PER_NODE = 8` attachments
of any kind per agent, of which skills count.

### `config.py` constants (Integrator-owned; specified here)

`SKILLS_ROOT` (env, default `data/skills`), `MAX_SKILL_BYTES = 65536`,
`MAX_SKILLS_PER_USER = 32`, `MAX_SKILL_IMPORT_BYTES = 262144`,
`BUILTIN_SKILL_NAMES` (the four). One new environment knob.

### Consumed

- **C4** (01): none — skills carry no credential.
- **C5** (09): `with: {skills: [skill_id]}`.
- **C6** (10): AGENT frames with `details.skill`; `node_error` with `error_class = skill_load`.
- **C8** (12): `skill-unknown`; requested: `skill-contains-scripts`.
- **C10** (15): the `user_skills` table.

## Acceptance criteria

1. `init_db` seeds the four built-ins; `GET /api/builder/skills` lists them for an anonymous caller in `SYNTHETIC` mode and for a signed-in user. Test: `tests/service/test_skills_endpoint.py`.
2. Posting a `SKILL.md` with `name: "Bad Name"` answers 422 with the package parser's sentence; posting a valid one answers 201 and the row's `name`, `description`, `version` match the frontmatter. Test: same file.
3. A zip containing `scripts/run.py` is refused with `skill-contains-scripts`; one containing only `SKILL.md` imports. Test: `tests/service/test_skills_import.py`.
4. `materialise(skill_id)` writes the file once, returns the same `Path` on the second call, and rewrites it after a `PUT` (compared by `updated_at`). Test: `tests/builder/test_skills_materialise.py`.
5. `runtime:run_agent` with a `skill` attachment constructs `Agent(skills=[Path])` — a `Path`, never a `str` — and `crewai.skills.loader.load_skill` on that path returns a `Skill` at `METADATA` whose `activate_skill` yields `INSTRUCTIONS` with the body. Test: `tests/builder/test_skills_runtime.py`.
6. Another user's `skill_id` in a document validates with `skill-unknown`; a built-in validates clean for everyone. Test: `tests/service/test_skills_isolation.py`. Rubric 14.
7. A synthetic run with a built-in attached emits an AGENT frame with `details.skill = "hn-signal-reading"` and `disclosure = "instructions"` after activation (the synthetic runner emits the frame; the real path is asserted through a recorded event fixture). Test: `tests/events/test_skill_frames.py`.
8. Deleting a skill makes a document that references it validate with `skill-unknown` and the problems dock anchors it to the skill node. Test: `tests/service/test_skills_endpoint.py::test_delete_orphans_document`.
9. Playwright: paste a `SKILL.md` in the builder's Skills panel, see it listed under *mine*, drag it onto an agent, see the card's `v1` and *mine* chip and the inspector's rendered body; the palette shows the three attachment headings with their one-line descriptions. Spec: `frontend/e2e/builder-skills.spec.ts`. Rubric 4.
10. The four built-in `SKILL.md` files parse under `crewai.skills.parser.parse_skill_md` in the suite, so a CrewAI upgrade that tightens the frontmatter fails a test rather than a run. Test: `tests/builder/test_builtin_skills.py`.

## References

- `.venv/Lib/site-packages/crewai/skills/models.py:25-35` (disclosure levels), `:43-63` (`SkillFrontmatter`), `:117` (`disclosure_level`), `:151` (`with_disclosure_level`); `crewai/skills/loader.py:44, 120, 154, 210, 245, 281, 293`; `crewai/skills/parser.py:35, 39, 76, 95, 129, 159`; `crewai/skills/tool.py:58` (activation during execution); `crewai/skills/registry.py:140-161` (registry refs); `crewai/events/types/skill_events.py:28-65`.
- `docs/crewai-notes.md` §7, §11 item 6.
- `src/brief_crew/service/persistence.py` (`MAX_STRING_LENGTH`, `_sanitize_json`), `builder/runtime.py:406-439`, `crews/validator_crew/config/{agents,tasks}.yaml`, `frontend/src/utils/markdown.ts`, `docs/rubric-ratification.md` (C7 thread definitions), `docs/licensing.md` (the vendored `.agents/skills/` are MIT developer skills, not these).
- Gauntlet: Stage 2 "Skills = knowledge … progressively disclosed", "keep the three distinct".

## Status

**Planned · 2026-09-02.**

Contract requests for 00:

- **C8 (12):** `skill-contains-scripts` (error, import-time).
- **C10 (15):** the `user_skills` table above.
- **v2, C11:** multi-file packs (`references/`, `assets/`) as a `user_skill_files` table; not required for any template.

Open decisions for the owner:

- The four built-in skills are distilled from the validator's prompts. Confirm the licence header they ship under (the repo has no `LICENSE` — remaining-work item 17), because a user will download them.
- Whether a user may attach a skill to a **library** agent node (the repo's own YAML agents) or only to authored ones. Recommendation: authored only in v1 — a library agent's prompt is tuned and pinned by tests, and a skill changes what it reads.

### Owner decisions answered — 2026-09-04

**Decision 10 — authored only.** The library agents are ours, not the author's,
and attaching to them makes the boundary between the two disappear.

**Decision 11 — not answerable; it depends on the repository having no
`LICENSE`.** A public repo with no licence file means all rights reserved
(CLAUDE.md remaining-work item 17). Build the four skills with no licence header
and record the dependency; do not invent a header.

### Built · 2026-09-04

Parser, store, materialisation, four built-in packs, routes, panel and form.
Python **2019** run / 0 failures / 6 skipped; frontend **1400** in 72 files;
`vue-tsc` exit 0.

| # | Criterion | | Shown by |
| ---: | --- | --- | --- |
| 1 | the four built-ins list for anonymous and signed-in | **met, `init_db` clause corrected** | `tests/service/test_skills_endpoint.py` |
| 2 | a bad frontmatter is 422 with the parser's sentence | **met** | same file |
| 3 | a zip carrying `scripts/` is refused | **met** | `tests/service/test_skills_import.py` |
| 4 | `materialise` writes once and rewrites after an edit | **met** | `tests/builder/test_skills_materialise.py` |
| 5 | `run_agent` attaches a pack the package can load | **met, shape corrected** | `tests/builder/test_skills_runtime.py` |
| 6 | another user's pack is `skill-unknown` | **met** | `tests/service/test_skills_isolation.py` |
| 7 | an AGENT frame carries `skill` and `disclosure` | **partial** | `test_skills_runtime.py::SkillFrameTests` |
| 8 | deleting a pack orphans a document that names it | **met** | `test_skills_endpoint.py::test_delete_orphans_document` |
| 9 | Playwright: paste, list, drag, see `v1` and the body | **partial** | `frontend/tests/attachmentPanels.spec.ts` |
| 10 | the four packs parse under the package's parser | **met** | `tests/builder/test_builtin_skills.py` |

**Criterion 1 - two clauses corrected, both asserted.**

*`init_db` does not seed them, and does not need to.* The four are committed
FILES, `load_builtins` parses them at read time, and their ids are DERIVED from
their names (`sk_` + the first 12 hex of a sha256) rather than minted - so they
are the same ids on every deployment with no row to go stale. A seeding pass
would be a migration whose only job is to copy four files into a table nothing
reads, and it would introduce the one failure mode this arrangement does not
have: a row that disagrees with the file.

*"Anonymous in `SYNTHETIC` mode" is true; anonymous on a service that requires
auth is a **401**.* `Depends(current_user)` refuses before the handler runs and
this route gets no exception to the service's own rule. `AnonymousSkillTests`
builds the app the criterion describes - synthetic, no auth server - and asserts
the four list there; `SkillRouteTests` asserts the signed-in half.

**Criterion 5 - met, and the shape is corrected against a measurement.** The
criterion asks for `Agent(skills=[Path])` and `load_skill` on that path
returning a `Skill` at METADATA. Measured: `load_skill` treats a `Path` as a
**search** path and `discover_skills` iterates its CHILDREN, so a pack's own
directory answers `[]` and its parent answers every sibling pack - four
built-ins when the author attached one. `loaded_skill` therefore passes a
`Skill` object, which `Agent.skills` also accepts, which is still not a `str`,
and which names exactly one pack. Both halves are asserted, including the empty
answer that motivated the change; `search_path` exists so a test can still prove
the on-disk layout is a legal CrewAI search path, and one does.

**Criterion 7 - partial, and the boundary is a contract.**
`skill_frame_details` is the mapping D6 specifies and it is tested against REAL
CrewAI event objects rather than dictionaries, because the whole risk is that
the package's field names are not what this plan guessed. Registering it on the
event bus is `events/serializer.py`, which is **C6 and plan 10's**, so no frame
is emitted yet and the criterion's synthetic-run clause is not satisfied. A
mapping with no caller is a smaller debt than a mapping written twice.

**Criterion 9 - partial. The panel is built, docked and unit-proved.** Pasting a
`SKILL.md`, seeing it under *mine*, the `v1` and *built-in*/*mine* chips, the
rendered body and the three attachment headings are all asserted in
`attachmentPanels.spec.ts`. `frontend/e2e/builder-skills.spec.ts` was not
written: a jsdom mount cannot say how wide anything ended up, and the drag
gesture in particular proves a handler is bound and nothing about whether a tile
lands on a card.

#### Departures from the plan, each with its reason

1. **The disk is the store and the row is the index.** Plan D1 specifies
   `user_skills` with `body`, `version` and `size_bytes` and says the row is the
   truth. The table plan 15 shipped (C10) carries `path` and `bytes`, and its own
   comment calls itself "the index row for a SKILL.md pack **on disk**". The
   shipped schema wins, and `version` lives in `metadata.version` where D2
   already put it - so a `PUT` bumps the frontmatter and the card reads it back.

   > **The consequence, recorded rather than papered over: on Render's ephemeral
   > disk a USER's own pack does not survive a restart.** Built-ins are
   > unaffected - they are committed files. Closing it is a C10 change (a `body`
   > column, `TEXT`, bounded at `MAX_SKILL_BYTES`) and C10 belongs to the
   > Integrator. `SkillStore._pack` already degrades to an empty body rather than
   > dropping the row, so the failure is visible rather than silent.

2. **`skill-contains-scripts` is declared in `service/builder_api.py`, not in
   the builder package.** Three separate greps sweep every kebab-case
   module-level constant under `brief_crew/builder/` into the canvas
   problem-code union, and an import-time refusal never lands on a node - the
   problems dock would have nothing to anchor it to. It is still a machine
   readable `code` beside its sentence, which is what the C8 request asked for.

3. **The store lives in `service/attachments.py`.** The builder package must
   stay importable without SQLAlchemy.

4. **`_first_sentence` returns pydantic's actual message**, not the header and
   the field name, and it CUTS the `[type=..., input_value=...]` tail. That tail
   echoes the offending value back into an HTTP response body, and a route that
   echoes its input is the shape `service/credentials_api.py` parses by hand
   specifically to avoid.

#### Decisions

**Decision 10 - authored only.** Nothing here can attach a pack to a LIBRARY
agent, and it is a property rather than a check: an `attach` edge reaches a node,
`bounds.py` refuses any target that is not an agent or a crew, and a library
agent node's prompt comes from YAML that no skill can reach. The rule is 03's
and this plan adds nothing to it.

**Decision 11 - not answerable, and the dependency is pinned.** The four packs
ship with **no `license` field**. This repository has no `LICENSE`, which for a
public repo means all rights reserved (CLAUDE.md remaining-work item 17), and
inventing a header would be inventing provenance - which this repository has
been bitten by before. `test_no_pack_claims_a_licence_because_decision_11_is_not_answerable`
asserts the absence AND asserts that no `LICENSE` exists, so the day one appears
the test fails and names the decision that has become answerable.

#### Contract requests, unchanged and one added

- **C10 (15):** `user_skills.body` (`TEXT`, `<= MAX_SKILL_BYTES`), so a user's
  pack survives a restart on an ephemeral disk. NEW, and it is the one thing in
  this plan that is a real gap rather than a boundary.
- **C6 (10):** call `skill_frame_details` from the serializer's event ladder.
  Written and tested here; nothing emits it.
- **v2, C11:** multi-file packs (`references/`, `assets/`). Unchanged.

### Wave A/B closers — 2026-09-04

**Criterion 9 closes.** `frontend/e2e/builder-skills.spec.ts` pastes a
`SKILL.md`, sees it stored and listed under *mine*, opens its body through the
escape-first renderer, attaches it, and reads the version, the owner and the
body back off the form. Three tests, all green at `369a8c4` against a local
`SYNTHETIC=1` backend with zero console errors tolerated; capture in
`benchmarks/ours/08/`.

| # | Criterion | State | Shown by |
| ---: | --- | --- | --- |
| 9 | paste, list, drag, see `v1` and the body; the palette's three headings | **met, with the "card" read as the inspector's** | `frontend/e2e/builder-skills.spec.ts`, **3 tests** |

**Where the `v1` and *mine* chips live, and why it is not the canvas pill.**
`SkillConfig` carries `skill_id` and `skill_name` and nothing else, and the
export drops the id deliberately — so a version and an owner on the pill would
be facts about the AUTHOR's library rather than about the document, and an
imported graph could not draw them. The card that does carry all three is the
inspector's summary (`[data-testid="skill-summary"]`), which is what the test
asserts. Stated rather than glossed, because it is a departure from the
criterion's wording.

**Two product defects, both found by running it rather than by reading it.**

1. **`commitSkillId` never wrote `skill_name`, and `export.py` drops
   `skill_id`** on the stated grounds that *"the skill is re-resolved by
   `skill_name`, which passes through as an ordinary key"*. Nothing kept that
   promise: an exported graph's skill node carried neither an id nor a name, so
   **every export silently lost its skills** and `BuilderNode` rendered
   `no reference` for a pack the author had definitely chosen. The same absence
   is why an attached pack's pill read `sk_9f2c0a1b3d4e` on the canvas rather
   than what it is. The name is now written beside the id, and null when the
   roster does not know it.
2. **`loadBody` fetched the placeholder id a fresh skill node is born with**, so
   every skill node an author created logged a 404 in a console this suite
   tolerates none of. The `catch` swallowed the exception; the browser logged the
   request regardless. The list has already said what exists, so a request whose
   answer is known is no longer made — and a pack that is genuinely gone still
   says so through `skill-unknown` on the node.

`adopt` now refreshes the list BEFORE committing. Committing first showed an
author a card with no version, no owner and no body for the pack they had
written a second earlier.

**The palette clause is asserted separately**, because it is about the three
families staying distinct: one blurb each from `nodeKinds.ts` (`catalogue
tool` / `MCP server` / `knowledge an agent carries`), and all three carrying
`is-family-attachment`, which is the palette's half of D5's silhouette channel.

**And the refusal path.** A `SKILL.md` whose frontmatter the package's parser
rejects shows the parser's own sentence and stores NOTHING — the second half is
what a message alone does not prove. The 422 that provokes it is forgiven in a
console allowance declared beside the line that causes it, never at file level.
