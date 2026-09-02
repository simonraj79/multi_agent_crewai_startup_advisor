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
