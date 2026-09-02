# Rules block — proposed top of `CLAUDE.md` (Stage 0 R)

The owner decided on 2026-09-02 that `CLAUDE.md` stays the session file
(`PLANS.md` decision 1). This is the gauntlet's minimum rules block with the
three corrections the audit forces and the invariants a fresh block would
otherwise regress, rewritten to be **prepended to `CLAUDE.md`** directly
under `# CLAUDE.md`, above "Read This First". Nothing here is in force
until it is pasted (`PLANS.md` decision 2). Delete the smoke-test section
once it has fired.

---

## Rules for the gauntlet build

### Responses
Concise. No preamble. Don't restate the plan back to me.

### Planning
Never modify files in planning. Ask clarifying questions until the spec is
unambiguous. Never assume design, copy, or features. Write plans to
`.agent/plans/<feature>.md` with numbered acceptance criteria and references;
record status in `PLANS.md`.

### Building
Follow the current plan file. If reality contradicts the plan, stop and say
so — do not improvise around it. Report a contradiction against a plan
section, a contract number (C1–C12 in `.agent/plans/00-architecture.md`) or
a ruling number in `docs/flow-builder-spec.md`; never around one.

### Framework
CrewAI only, at the version pinned in `docs/tech-stack.md` (1.15.18). Every
canvas node maps to a real CrewAI primitive; the table is
`.agent/plans/00-architecture.md` D3. If a node can't map, the node design
is wrong — fix the design, never fake the runtime. Where the gauntlet and
the installed package disagree, the package wins: `docs/crewai-notes.md`
§11 is the list. Never install `crewai[litellm]`.

### Models
OpenRouter only. Hard ceiling: **$1.00 per 1M input tokens**, enforced by
`tests/test_model_ceiling.py` over `data/models.json`; the registry is
regenerated from the live catalogue, never typed from memory. Never
introduce Claude Opus/Sonnet, GPT-4o full, o1, o3, o4-mini, or any
frontier-priced model — not in code, not in defaults, not in examples, not
in tests. A price written in prose is stale; look it up.

### Design
Flowise for build-time interaction (`docs/flowise-notes.md`). ChatDev for
run-time motion (`docs/chatdev-notes.md`). Follow `docs/design.md`. No new
colours, spacing or type scales — a value is a token in
`frontend/src/assets/styles/tokens.css` or it does not exist. No
third-party sprites. The design canvas is still.

### Testing
Verify with available tools before reporting done. Check the plan's
acceptance criteria explicitly, item by item. Never assume it works. A green
suite is not evidence a UI is right (`docs/gotchas-and-insights.md` 34, 35).
The judge loop is `benchmarks/README.md`.

### Cost
Single-threaded by default. Ask before spawning parallel agents. Never press
Launch against the paid backend on :8000; the free one is `SYNTHETIC=1
SYNTHETIC_BRANCH_DELAY_SECONDS=5 PORT=8099`. E2E tests that launch are
tagged `@launch`.

### Invariants (the sections below own the reasoning)
Prompts for this repository's own crews stay in YAML; a user's authored
agent carries its prompts in the user's document and nowhere else.
Constants stay in `config.py`. Embeddings go through
`brief_crew.embeddings`, never CrewAI's embedder. `SYNTHETIC=1` is a
factory swap, not a second runner. No tools on Scoper, Synthesist or
Reporter. Do not regress Brief Crew. `tests/__init__.py`'s placeholder keys
gain a row whenever a test constructs a new provider client.

### Three directories that look alike — do not merge them
`.agent/plans/` — the gauntlet plan files, this build. `agents/` — the
authoritative CrewAI specifications; where code and spec disagree, the spec
is right. `.agents/skills/` — vendored MIT CrewAI skills, third-party files.

### Commands
```text
build:  Push-Location frontend; npm run build; Pop-Location
test:   .\.venv\Scripts\python.exe -m unittest discover -s tests -t .
        Push-Location frontend; npm test; Pop-Location
lint:   Push-Location frontend; npx vue-tsc -b --force; Pop-Location
e2e:    (see Cost) then  npx playwright test
```

### Smoke test — delete once it has fired
When this file loads, begin your first reply with the word ORRERY. If a
fresh session does not, the rules are decorative: fix the loading before
building anything.

---
