# 03 — Node library

Node types, ports, palette, drag-drop, node identity, and the vocabulary the
server publishes. Build-time; compared against Flowise.

## Problem

Seven node kinds are a closed union on both sides (`document.py:58`,
`types/builder.ts:102-103`), with one target port `in` for every kind
(`types/builder.ts:110`) and out-ports fixed per kind (`document.py:388-395`,
mirrored at `nodeKinds.ts:109-114`). An `agent` carries `agent_id` and a
three-name `tools` tuple (`document.py:182-204`, `config.py:2014-2020`); a
`crew` carries `crew_id` (`document.py:207-220`). There is no tool node, no
MCP node, no skill node, and no way to type a role. The palette is seven
server-ordered tiles with hotkeys `1–7`, billable counters, a `/` filter and
the saved-graph list (`NodePalette.vue:106-273`); drag uses
`application/x-builder-kind` (`:13`, `:153`). A card's identity is a kind
eyebrow, a Lucide icon, a kind gradient (`builder.css:47-53`) and one summary
line built by `summariseConfig` (`BuilderNode.vue:60-115`).

Flowise v2 shows what a node should say about itself without opening it: a
model pill and one 20 px avatar per attached tool inside the card
(`docs/flowise-notes.md` §2). Our card cannot, because the document has
nothing to summarise.

## Scope

The ten-kind vocabulary (FD3), the port table (FD4), the document schema
changes that carry authored agents and crews (FD5) and their bounds (FD6),
the v1→v2 upgrade (FD2), palette changes, node identity and config chips,
edge-class rules in `bounds.py`, and **C2 — the vocabulary v2 shape**, which
this plan owns.

## Out of scope

Inspector forms (04). The registry's contents (05), the tool catalogue's
contents (06), MCP discovery (07), skill storage (08). Port pixels and edge
strokes (02). Compilation (09).

## Design

**D1 — Ten kinds, two families, three port classes.** `NodeKind` grows to
`input | agent | crew | gate | router | transform | output | tool | mcp | skill`
in both `document.py:58` and `types/builder.ts:102`. `InspectorRail`'s total
`Record<NodeKind, Component>` (`InspectorRail.vue:67-75`) and the palette's
compile-time counter check (`NodePalette.vue:23`) turn a missing kind into a
build failure, which is the point of keeping the union closed.

| Kind | Family | Target ports | Source ports | Accepts incoming |
| --- | --- | --- | --- | --- |
| `input` | flow | — | `out` | no (unchanged, `nodeKinds.ts:124-133`) |
| `agent` | flow | `in`, `attach` | `out` (+ `error` if `on_error == 'route'`) | yes |
| `crew` | flow | `in`, `attach`, `member` | `out` (+ `error`) | yes |
| `gate` | flow | `in` | `approve`, `revise` | yes |
| `router` | flow | `in` | branch labels (unchanged, `nodeKinds.ts:279-284`) | yes |
| `transform` | flow | `in` | `out` | yes |
| `output` | flow | `in` | none (unchanged, `:331-334`) | yes |
| `tool` | attachment | — | `attach` | no |
| `mcp` | attachment | — | `attach` | no |
| `skill` | attachment | — | `attach` | no |

`TargetPort` becomes `'in' | 'attach' | 'member'` (`types/builder.ts:110`,
`document.py:467-480`). Edge class is a pure function of `target_port`;
`outPortsOf(node)` (`nodeKinds.ts:361`) stays the single source for source
ports and gains the conditional `error`.

**D2 — Edge rules move into `bounds.py`, reported, never raised (R6).**

| Rule | Code | Severity |
| --- | --- | --- |
| `attach` target must be agent or crew; source must be tool/mcp/skill | `attach-target-not-agent` | error |
| `member` target must be crew; source must be agent | `member-target-not-crew` | error — CONTRACT REQUEST |
| a member agent carries any `in`/`out`/`error` edge | `member-agent-has-flow-edges` | error |
| an attachment node has no attach edge | `attachment-unattached` | warning — CONTRACT REQUEST (shared with 02) |
| attachments on one node > `MAX_ATTACHMENTS_PER_NODE` | `attachments-over-max` | error — CONTRACT REQUEST |
| attachment nodes > `MAX_ATTACHMENT_NODES` | `attachment-nodes-over-max` | error — CONTRACT REQUEST |
| crew members outside 1..`MAX_CREW_MEMBERS` | `crew-members-out-of-range` | error — CONTRACT REQUEST |

`attach` and `member` edges are excluded from fan-out counting
(`bounds.py:494-510`), from cycle detection (`:597`), from `billable_depths`
(`:258-294`) and from `MAX_GRAPH_NODES` (`:366`); attachment nodes count
against `MAX_ATTACHMENT_NODES` only. A member agent is billable inside its
crew, not as a node: `MAX_BILLABLE_NODES` (`:381`) counts crews and
non-member agents, and the crew's price (09) multiplies by its members.

**D3 — The document (C1, spelled out in FD5).** `AgentConfig` becomes a
union discriminated by presence: `LibraryAgentConfig` (today's fields,
`document.py:182-204`) or `AuthoredAgentConfig` (`role, goal, backstory,
task, llm, tier, max_iter, max_rpm, max_execution_time, allow_delegation,
memory, cache, respect_context_window, reasoning, max_reasoning_attempts,
multimodal, system_template, prompt_template, response_template,
function_calling_llm, tool_failure_policy, retry, on_error,
guardrail_max_retries, prompt_inputs`). Both or neither of `agent_id` /
`role` is refused at parse with a sentence naming the two fields. Same shape
for `CrewConfig` on `crew_id` / `process`. `ToolConfig`, `McpConfig`,
`SkillConfig` per FD5. Every string field keeps `_checked_with_value`'s
`${state.x}` discipline (`document.py:105-123`). `BuilderDocument` gains
`state: FlowStateSchema | None` and `joins` accepts `'any'`
(`document.py:533-559` today refuses it; the compiler consequence is 09's).

**D4 — v1 → v2 upgrade is pure and total.** `upgrade_document(dict) -> dict`
in `document.py`: `schema` `builder.flow/v1` → `v2`; every agent gains
nothing (a v1 agent already has `agent_id`, so it parses as a library agent);
`joins`, `budget`, positions untouched. `store.py:613-632` calls it before
re-validation so every stored row reads as v2. `tests/builder/test_upgrade.py`
runs the four committed template fixtures through it and asserts byte-equal
output after a second pass.

**D5 — Node identity: shape, colour, icon — three channels for rubric 2.**

| Kind | Silhouette | Icon (Lucide) | Accent (`nodeKinds.ts`) |
| --- | --- | --- | --- |
| input | card, no top port | `text-cursor-input` | `#aaffcd` |
| agent | card, 240 px | `user-round` (authored) / `book-user` (library) | `#99eaf9` |
| crew | card, 240 px, **double left border** | `users-round` | `#a0c4ff` |
| gate | card, two labelled bottom ports, amber | `hand` | `#ffe082` |
| router | card with a notched right edge, labelled ports | `git-fork` | `#7dc6ff` |
| transform | slim card | `wand-2` | `#b3b3b3` |
| output | card, no bottom port | `flag` | `#7bdff2` |
| tool | **pill**, 160 px | `wrench` | `#c3a6ff` |
| mcp | pill, 160 px, plug glyph | `plug-zap` | `#d5b8ff` |
| skill | pill, 160 px | `book-open` | `#e0ccff` |

Flow nodes are cards; attachments are pills; a pill can never be mistaken
for a step at 50 % zoom where the 11 px eyebrow is 5.5 px. The three
attachment accents share a hue and differ by lightness, so "this is an
attachment" reads before "which one". Icons render in a 28 px colour-filled
squircle (Flowise v2's `borderRadius: 15px` block), replacing the bare icon.

**D6 — Config chips replace the summary line.** `summariseConfig`
(`BuilderNode.vue:60`) returns structured chips, rendered in the card body:

| Node | Chips |
| --- | --- |
| authored agent | model pill (registry `name`, provider glyph, `cost_in` on hover); attachment avatars (one 20 px per attached tool/mcp/skill, `+N` beyond four); `retry ×N` when `max_retries > 0`; `⚠ routes errors` when `on_error == 'route'` |
| library agent | `agent_id`, tier, tool count (today's line) |
| authored crew | `seq` / `hier` chip; member count; manager model pill when hierarchical |
| tool / mcp / skill | the catalogue label; a key glyph when `credential_id` is set; for mcp the selected tool count |

Attachments therefore appear **twice** — as pills on the canvas and as
avatars on the agent — which is deliberate: the pill is where you configure,
the avatar is where you see the agent's hands.

**D7 — Palette.** Ten tiles in `vocabulary.node_kinds` order (server order,
`NodePalette.vue:106`), hotkeys `1–7` for flow kinds and `T`, `M`, `K` for
tool, mcp, skill (declared in `useBuilderHotkeys`). Attachment tiles carry
their own counter against `max_attachment_nodes`. Drag keeps
`BUILDER_KIND_MIME` and adds the catalogue id for tool tiles, so a **specific
tool** can be dragged from a catalogue sub-list under the tool tile (search
over `vocabulary.tools[].label`, 250 ms debounce — Flowise uses 500 ms with a
fuzzy scorer, `docs/flowise-notes.md` §1; 250 ms because the list is ≤ 30
entries). Drop onto an agent attaches (02 D8). The billable/escalation
counters and disable-at-ceiling rule (`NodePalette.vue:123-130, 236-246`) are
unchanged.

**D8 — Vocabulary v2 is served, never duplicated, still unauthenticated.**
`GET /api/builder/vocabulary` (`builder_api.py:415-420`) carries everything
the palette, the inspector and validation need that is not per-user.
Per-user lists — credentials (C4), skills (C11), MCP servers (C12) — come
from their own authenticated endpoints. Cut-list 17 stands: no client
fallback.

## Interfaces

**Owned — C2, `GET /api/builder/vocabulary` v2 response:**

```jsonc
{
  "schema_id": "builder.flow/v2",
  "node_kinds": ["input","agent","crew","gate","router","transform","output","tool","mcp","skill"],
  "attachment_kinds": ["tool","mcp","skill"],
  "target_ports": { "agent": ["in","attach"], "crew": ["in","attach","member"], "gate": ["in"],
                    "router": ["in"], "transform": ["in"], "output": ["in"], "input": [],
                    "tool": [], "mcp": [], "skill": [] },
  "tiers": ["cheap","escalation"],
  "tier_models": { "cheap": "google/gemini-3.5-flash-lite", "escalation": "google/gemini-3.8-flash" },
  "models": [ /* C3 entries verbatim, ≤ 10: id, name, provider, context_window,
                 supports_tools, supports_vision, supports_json_mode, supports_reasoning,
                 cost_in, cost_out, cost_in_max_endpoint, speed_tier, recommended_for */ ],
  "agent_ids": ["scoper", "..."],            // library agents, unchanged
  "crew_ids": ["scope", "..."],              // BUILDABLE_BUILDER_CREW_IDS, unchanged
  "research_tools": ["research_market_landscape", "..."],   // library-agent tools only
  "tools": [ { "tool_id": "firecrawl_scrape", "label": "Firecrawl scrape", "category": "web",
               "description": "...", "credential_kind": "firecrawl",     // or null
               "attaches_to": ["agent","crew"],
               "params": [ { "name": "limit", "type": "number", "required": false,
                             "default": 3, "min": 1, "max": 10, "description": "..." } ] } ],
  "transform_ops": [...], "router_comparisons": [...], "router_otherwise": "otherwise",
  "result_body_keys": ["markdown_body"],
  "problem_codes": [...], "warning_codes": [...],      // C8, for the runtime mirror check
  "bounds": { /* today's 16 (types/builder.ts:504-521) plus */
    "max_attachment_nodes": 24, "max_attachments_per_node": 8, "max_crew_members": 6,
    "max_prompt_chars": 4000, "max_retries": 3,
    "ceiling_usd_per_m_input": 1.0, "max_run_cost_usd": 10.0 }
}
```

`tools[].params[].type ∈ string | number | boolean | json`; `enum` optional.
`models` is C3 verbatim; `tools` is 06's catalogue verbatim; `problem_codes`
is C8 verbatim. The client `normalise()` (`builderVocabulary.ts:30-91`)
refuses an unknown kind, an empty `models`, or a `tier_models` value absent
from `models`.

**Owned — C1 edge and port additions:** `BuilderEdge.target_port:
Literal['in','attach','member']`; `_OUT_PORTS_BY_KIND` gains `tool/mcp/skill
→ ('attach',)` and the conditional `error`; `upgrade_document`.

**Consumed:** C3 (05), C4 (01), C8 (12), C11 (08), C12 (07).

## Acceptance criteria

1. `python -c "import typing; from brief_crew.builder.document import NodeKind; print(len(typing.get_args(NodeKind)))"` prints `10`; `types/builder.ts` `NodeKind` has the same ten; `tests/builder/test_client_fixtures.py` byte-compares the kind list.
2. `tests/builder/test_document.py`: an agent with both `agent_id` and `role` fails to parse; with neither fails; each alone parses. Same for crew `crew_id` / `process`.
3. `tests/builder/test_bounds.py`: each D2 code fires on a minimal document and nowhere else; attach/member edges do not count toward fan-out, cycles or `MAX_GRAPH_NODES`.
4. `tests/builder/test_upgrade.py`: every committed template fixture round-trips through `upgrade_document` twice, byte-identical after the second pass; a v1 row loaded through `store.load` parses as v2.
5. `GET /api/builder/vocabulary` matches the C2 shape (`tests/service/test_builder_vocabulary.py`), is unauthenticated, and `models`, `tools`, `problem_codes` equal their owning sources byte-for-byte.
6. `frontend/tests/nodeKinds.spec.ts`: `outPortsOf` returns the D1 table for every kind, including `error` only when `on_error == 'route'`; `acceptsIncoming` is false for input, tool, mcp, skill.
7. **Rubric 2:** `e2e/visual/node-grammar.spec.ts` renders one node of each kind at `zoom 0.5`, captures at 1440×900, and asserts per kind: silhouette class (`is-card` / `is-pill`), squircle fill equals the accent, and the eyebrow text. A critic's side-by-side against Flowise v2 at the same zoom is filed in `benchmarks/`.
8. `frontend/tests/builderNode.spec.ts`: an authored agent with three attachments renders a model pill and three avatars; five attachments render four plus `+1`; a hierarchical crew renders `hier` and the manager pill.
9. Palette: ten tiles in server order; `T`, `M`, `K` insert attachment kinds; the tool sub-list filters within 250 ms (`frontend/tests/nodePalette.spec.ts`); dragging a specific tool sets both MIME entries.
10. `e2e/builder.spec.ts` "attach a tool by dropping it on an agent": one undo step, the agent card shows one avatar, the pill shows the tool label; dropping on empty canvas yields `attachment-unattached` in the problems dock.
11. `npx vue-tsc -b --force` fails if a kind is added to `NodeKind` without an inspector or a palette tile (existing totality checks, `InspectorRail.vue:67-75`, `NodePalette.vue:23`).

## References

- Flowise: `views/agentflowsv2/AgentFlowNode.jsx:279-310, 440-656` (chips, status badge), `views/canvas/AddNodes.jsx:120-217, 347-350` (fuzzy search, drag), `utils/genericHelper.js:118-231` (port vs param) — `docs/flowise-notes.md` §1, §2.
- CrewAI: `crewai/agent/core.py` fields (`docs/crewai-notes.md` §1), `crewai/mcp/config.py` (§6), `crewai/skills/models.py:43-63` (§7).
- Repo: `src/brief_crew/builder/document.py:58, 63, 82-123, 141-362, 388-406, 409-480, 498-559`; `bounds.py:62-86, 258-294, 366-398, 466-510, 597-631`; `store.py:613-632`; `service/builder_api.py:287-290, 415-420`; `config.py:1768-1863, 2014-2036`; `frontend/src/data/nodeKinds.ts:99-147, 109-116, 124-133, 271-284, 331-336, 361`; `types/builder.ts:57-73, 102-111, 301-308, 374-412, 504-545`; `data/builderVocabulary.ts:7-91, 137`; `components/builder/NodePalette.vue:13, 23, 106, 123-130, 141-153, 184-198, 236-273`; `BuilderNode.vue:60-127, 191-216`; `assets/styles/builder.css:47-61, 249-272`.
- `docs/flow-builder-spec.md` §3, §5.3, R6, R7, cut-list 17.
- Gauntlet: Stage 2 "Node parameters", "Tools, skills and MCP — keep the three distinct", rubric 2.

## Status

Planned · 2026-09-02.

CONTRACT REQUESTS for 12 / 00 C8: `member-target-not-crew`,
`attachment-unattached` (warning), `attachments-over-max`,
`attachment-nodes-over-max`, `crew-members-out-of-range`. Proceeding as if
granted.

Open decision for the owner: whether attachment tiles get letter hotkeys
(`T`/`M`/`K`) or `8`/`9`/`0`; the plan assumes letters because `0` reads as
"none".

### Owner decisions answered — 2026-09-04

**Decision 18 — letters `T`, `M`, `K`.** Digits 1–7 already select node kinds,
and a second digit row on the same surface is a collision an author discovers
by pressing one.
