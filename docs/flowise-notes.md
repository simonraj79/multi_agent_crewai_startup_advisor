# Flowise notes — the build-time interaction reference, read from source

Extracted on **2026-09-02** from `D:\Flowise-main` (git root is one level
down: `D:\Flowise-main\Flowise-main\`; every path below is relative to that
root). `flowise-ui` **v3.1.4**, React Flow **11.10.4** (`reactflow`, the
pre-`@xyflow` API — `reactFlowInstance.project()`, not
`screenToFlowPosition`). Vue Flow (`@vue-flow/core`) is a port of that API, so
everything here transfers one-to-one.

Licence: `LICENSE.md` is split — `packages/server/src/enterprise/` is
commercial, **everything else including the whole canvas UI is Apache-2.0**.
We copy interaction patterns and measurements, not files.

## 0. There are two canvases, and they are different products

| | v1 Chatflow / Agentflow | **Agentflow v2** |
| --- | --- | --- |
| Entry | `packages/ui/src/views/canvas/index.jsx` (670 lines) | `packages/ui/src/views/agentflowsv2/Canvas.jsx` (831) |
| Node | `views/canvas/CanvasNode.jsx` — fixed **300px** card, typed ports per input | `views/agentflowsv2/AgentFlowNode.jsx` — `width: max-content`, one in / one out, colour-driven |
| Config | inline widgets on the node face + "Additional Parameters" dialog | **double-click opens `EditNodeDialog`** |
| Edge | `ButtonEdge.jsx` — bezier, always-visible delete button | `AgentFlowEdge.jsx` — **gradient source-colour → target-colour**, hover-only delete |
| Type check | `baseClasses` string match on handle ids | none; cycle check only |
| Tools | edge into a `list: true` `Tools` anchor | an `array` param inside the agent node |

Take the **v2 node model** as the primary reference: it is the one that
scales, and it is the one Flowise itself moved to.

## 1. Canvas mechanics (exact values)

`canvas/index.jsx:586-660`, `agentflowsv2/Canvas.jsx:720-821`:

| Setting | v1 | v2 |
| --- | --- | --- |
| `minZoom` | 0.1 | **0.5** |
| `maxZoom` | default 2 | default 2 |
| `snapGrid` | `[25, 25]` | `[25, 25]` |
| `snapToGrid` | user toggle, **off by default** | same |
| `deleteKeyCode` | `['Delete']`, suppressed while any dialog is open | same |
| `<Background>` | `color='#aaa' gap={16}`, toggleable | same |
| `<MiniMap>` | absent | present, `nodeStrokeWidth={3}` |
| Undo / redo | **none** — zero hits for `undo|redo` in `packages/ui/src` | none |
| Copy / paste | a `window` `paste` listener that sniffs for `{"nodes":[` and **replaces the whole flow** (`index.jsx:533-549`, with its own `//TODO` apology) | same |
| Multi-select | React Flow defaults (Shift box, Ctrl click) | same |
| Unsaved guard | `usePrompt('You have unsaved changes! …', isDirty)` (`index.jsx:559`); `*` before the name (`CanvasHeader.jsx:444`) | dirty flag only |

Snap and background are **toggles injected into `<Controls>`**
(`index.jsx:606-635`, magnet and artboard icons), and the controls bar is
re-laid horizontally and centred at the bottom.

New v2 flows are **seeded with a Start node** at `{x:100, y:100}`
(`Canvas.jsx:656-677`); drop-time guards answer *"Only one start node is
allowed"* as a persistent snackbar (`Canvas.jsx:320-407`).

### Palette — `views/canvas/AddNodes.jsx` (786 lines)

- A `Popper` off a FAB at `{left:20, top:20}`, not a docked rail. List `maxWidth: 370`, scroll `calc(100vh - 300px)`.
- Search: **debounced 500 ms**, hand-rolled fuzzy scorer (`fuzzyScore`, `:120-193`): exact substring 1000, +200 at start, +100 at word boundary, −2×offset, −3×length-delta; else per-char +10, consecutive bonus, 0 if any char unmatched. Scored on `name`, `label`, `category × 0.5`.
- Categories are accordions, auto-expanded while filtering. Badges: `"Name;BADGE"` split on `;`, chip at `0.65rem/700`.
- Drag is plain HTML5 DnD: `dataTransfer.setData('application/reactflow', JSON.stringify(node))`, `effectAllowed='move'`.

**Drop position** (`index.jsx:274-324`, `Canvas.jsx:301-317`):

```js
const position = reactFlowInstance.project({
  x: event.clientX - reactFlowBounds.left - 100,   // half a node
  y: event.clientY - reactFlowBounds.top  - 50
})
```

In Vue Flow this is `screenToFlowCoordinate({x, y})` with no manual bounds
subtraction. Ids: `${name}_${n}` incrementing until free
(`utils/genericHelper.js:4-17`); v2 also uniquifies the **label**.

## 2. Node grammar

### v2 node — `AgentFlowNode.jsx` (711 lines)

- `nodeColor = data.color || '#666666'`. Border = `getStateColor()`: selected → colour, hovered → `alpha(c, .8)`, idle → `alpha(c, .5)`. Fill (light) = `lighten(c, .9)` idle / `lighten(c, .8)` hover; (dark) `darken(c, .8/.7)`. Selection ring `boxShadow: 0 0 0 1px {stateColor}`.
- Icon: a `borderRadius: 15px` squircle filled with `data.color` holding a white 24px Tabler icon.
- Label `0.85rem / 500`. `minHeight = max(60, outputs × 20 + 40)`.
- **Config summary chips inside the node** (`:440-656`): a model pill (`borderRadius: 16px`, height 24, 20px provider icon + `0.7rem` name) and 20px circular icons per attached tool / knowledge store. *The node summarises its own config without opening anything* — the best idea in the repo.
- **Status badge** at `top:-10, right:-10` (`:279-310`): `ERROR` → `error.dark` with tooltip carrying `data.error`; `INPROGRESS` → `warning.dark` + spinning loader; `STOPPED` → stop icon; `FINISHED` → `success.dark` check. Warning badge at `top:-10, left:-10`.
- Toolbar is React Flow's `NodeToolbar`: 20px Duplicate / Delete / Info.

### Ports — exact sizes

| | v1 (`NodeInputHandler.jsx:850-864`, `NodeOutputHandler.jsx:74-206`) | v2 (`AgentFlowNode.jsx:331-357`, `:659-699`) |
| --- | --- | --- |
| Input | **10×10 px** circle; colour by *selection*, not type; type only in a hover tooltip | a **5×20 px bar** of `nodeColor` at `left:-2`; omitted on Start |
| Output | 10×10 circle | **20×20** handle at `right:-10` holding a `IconCircleChevronRightFilled` in `nodeColor`; **`opacity: hovered ? 1 : 0`, `transition: opacity .2s`** |
| Hit target | = visual (10 px) | 20 px |
| Multi-output spacing | `offsetTop + clientHeight/(n+1) × (i+1)` | same |

Connection-drag feedback is CSS (`views/canvas/index.css:41-49`):

```css
.react-flow__handle-connecting { cursor: not-allowed; background: #db4e4e !important; }
.react-flow__handle-valid      { cursor: crosshair;   background: #5dba62 !important; }
```

### Port vs inline param — `utils/genericHelper.js:118-231`

`initNode()` sorts every declared input by **type**: the whitelist
(`string, number, boolean, password, json, code, options, multiOptions,
asyncOptions, array, datagrid, file, folder, date, tabs, …`) renders as an
inline widget (`inputParams`); **every other type is an object type and
becomes a port** (`inputAnchors`). A third form, `acceptVariable: true`,
renders both a text field and a handle. Handle ids encode the contract:
`${nodeId}-input-${name}-${type}` / `${nodeId}-output-${name}-${baseClasses.join('|')}`.

`isValidConnection` (`:426-461`) is string parsing of those ids: compatible if
any target base class appears in the source's `|` list, and the target anchor
is `list: true` or not yet occupied. v2 (`:463-518`) has no types — only
self-connection and a DFS cycle check in `onConnect`, which **fails silently**
(no red handle, the drop just does nothing). Do not replicate that.

### Edges

v2 `AgentFlowEdge.jsx` (193 lines): `getBezierPath` with a `+0.0001` nudge on
equal coordinates; a per-edge `<linearGradient>` from `data.sourceColor` to
`data.targetColor` resolved at connect time from the node categories; two
stacked paths — an invisible **`strokeWidth: 15` hit path** and the visible
one at `selected ? 3 : 2`, `opacity: selected ? 1 : .75`; delete button only
on hover, 12×12, filled with the same gradient; branch labels
(`proceed` / `reject` for human input, `0` / `1` for conditions) at
`0.5rem/700` via `EdgeLabelRenderer`. The dangling `ConnectionLine.jsx`
**previews the branch label and colour while you drag**.

## 3. New-flow creation, save, export

- List page → **"Add New"** → `navigate('/canvas')`. Name starts `"Untitled Agent"`; inline pencil → text field, **Enter saves, Escape cancels** (`CanvasHeader.jsx:484-490`). First save opens a name dialog; later saves are silent.
- Save payload is React Flow's own `toObject()` — `{nodes, edges, viewport}` — with the credential id lifted out of `inputs` first (`index.jsx:211-245`). v1 has a **concurrent-edit guard** (*"has changed since you opened, overwrite?"*, `:456-484`); v2 does not.
- Export (`genericHelper.js:587-636`) rebuilds `node.data` to a whitelist, drops the viewport, **strips `password` / `file` / `folder` inputs and every `FLOWISE_CREDENTIAL_ID` recursively** (`_removeCredentialId`, `:572-585`). Secrets never leave in an export.
- Duplicate = `localStorage['duplicatedFlowData']` + open a new tab; the target canvas consumes and deletes the key on mount (`:504-506`).
- Templates: a read-only canvas at `/v2/marketplace/:id` with one action, **"Use Template"**, which navigates with `state.templateFlowData` and hydrates through the same `handleLoadFlow` as import and paste — one code path, three entry points.

## 4. Tools, credentials, custom tools

**Attachment.** v1: a `Tools` input anchor with `list: true`
(`ToolAgent.ts:46-51`); `onConnect` mirrors the edge into
`inputs.tools` as `{{sourceId.data.instance}}` tokens and disconnect reverses
it (`ReactFlowContext.jsx:138-176`). That dual bookkeeping is where a port
drifts. v2: tools are an `array` param on the agent (`Agent.ts:251-271`) with
`loadConfig: true`, so picking a tool pulls its own param schema into a nested
config.

**Credentials.** A node declares `credential: {credentialNames: [...]}`;
`initNode` unshifts it as the first `inputParam` of type `credential`
(`genericHelper.js:160-167`). `CredentialInputHandler.jsx` renders an async
dropdown with *create new* and an edit pencil; creation goes through
`AddEditCredentialDialog.jsx` which renders the credential component's own
inputs. On the server (`packages/server/src/utils/index.ts`):
`getEncryptionKey()` `:1553-1590` (env `FLOWISE_SECRETKEY_OVERWRITE` → AWS
Secrets Manager → `~/.flowise/encryption.key`),
`encryptCredentialData()` `:1597-1600` = **`crypto-js` `AES.encrypt(json,
passphrase)`** (OpenSSL `EVP_BytesToKey`, CBC, no auth tag — **do not copy
the primitive**; use AES-GCM with a real KDF), entity
`entities/Credential.ts` stores only `encryptedData` beside plaintext
`name` / `credentialName`.

**Custom tool** (`views/tools/ToolDialog.jsx`, 628 lines): Name (required,
`my_tool` snake case), Description (required, multiline, "for the model to
decide when to use it"), Icon URL, **Input Schema as an editable grid** —
columns `property`, `type ∈ {string, number, boolean, date}`, `description`,
`required` — with **"Paste JSON"** and **"Add Item"**, then a CodeMirror JS
function editor with "How to use" and "See Example". Save disabled until name
and description exist. Stored as `{name, description, color, schema: text,
func: text, iconSrc}` (`entities/Tool.ts`); at runtime
`CustomTool.ts` converts the schema through a guarded Zod parser into a
`DynamicStructuredTool`.

## 5. Test panel and execution view

- **`views/chatmessage/ChatPopUp.jsx`** (245 lines) is rendered as a child of `<ReactFlow>` so it floats over the graph: a `Popper` off a FAB at `{right:20, top:20}`, with **clear** (`right:80`) and **expand to modal** (`right:140`) when open. Not resizable, not draggable. In v2 the same slot becomes a schedule or webhook tester when the Start node's trigger type says so (`Canvas.jsx:813-819`). Clearing chat calls `clearAgentflowNodeStatus()`, wiping every node badge.
- **Live node status:** one SSE event `nextAgentFlow` → `onAgentflowNodeStatusUpdate({nodeId, status, error})` → a direct `setNodes` patch (`ReactFlowContext.jsx:23-36`) → the status badge. That is the whole pipeline; copy it verbatim. Server emits from `buildAgentflow.ts:1106, 1442, 1489, 2118, 2184`.
- **Execution view** (`views/agentexecutions/`): `ExecutionDetails.jsx` (989) is a right `Drawer`, **resizable by dragging its left edge** (`MIN 400`, default `innerWidth − 400`); a `RichTreeView` trace with status icons, virtual "Iteration N" parents for loop bodies, all expanded by default, the first stopped node auto-selected. `NodeExecutionDetails.jsx` (1,285) shows **Input / Output / State** per node with a rendered-vs-raw toggle. **No per-node duration** — only LLM nodes that emit `timeMetadata` get a `"N.NN seconds"` chip (`:310-315`). The `Execution` entity has whole-run timestamps only.

## 6. Error handling — what Flowise actually does

1. **Pre-run validation is server-side, manual, and stale.** `ValidationPopUp.jsx` (302 lines) is a FAB at `{right:80, top:20}` opening a 400px "Checklist (N)" popper with a **"Validate Flow"** button that calls the API — so it validates the **last saved** flow, not the canvas. Rules in `packages/server/src/services/validation/index.ts`: unconnected node → *"This node is not connected to anything"* (`:29-44`); a non-optional param that is `undefined | null | ''` → *"`{label}` is required"* (`:74-79`); array rows (`:82-175`); *"Credential is required"* (`:178-183`); nested config (`:186-234`); hanging edges (`:260-310`). Issue cards are amber (`alpha('#FFB938', .5)`) with the node's category icon.
2. **Execution errors** surface three ways: a **persistent** notistack snackbar with a dismiss `IconX` (the `errorFailed()` block is copy-pasted ~40 times, `index.jsx:349-379`); the node's status badge turning red with the error in its tooltip; and the trace entry `{nodeId, status: 'ERROR', data.error}` (`buildAgentflow.ts:2163-2207`). Run state precedence `TERMINATED > ERROR > STOPPED > FINISHED`.
3. **Retry, backoff, error edges, fallback: none.** Grepped `maxRetries|retryCount|onError|fallback` across every Agentflow node — only `Loop.ts`'s `fallbackMessage`. One node throw aborts the whole run (`:2207`).
4. A **version-drift FAB** (`syncNodes`, `index.jsx:326-347`) appears when a node's `data.version` is older than its component and migrates it on click — worth having when our vocabulary changes.

## 7. MCP — `packages/components/nodes/tools/MCP/`

- **`CustomMCP.ts`**: two inputs — `mcpServerConfig` (a `code` field holding stdio `{command, args}` or remote `{url, headers}` JSON, with `{{$vars.x}}` interpolation) and `mcpActions` (`asyncMultiOptions`, `loadMethod: 'listActions'`, `refresh: true`). Transport is a **global env switch** (`CUSTOM_MCP_PROTOCOL`), not per server.
- **`core.ts`**: `createClient()` tries `StreamableHTTPClientTransport` first and **falls back to `SSEClientTransport`** (`:128-165`); `initialize()` = connect → `tools/list` → build tools → close; each invocation opens a fresh client (`:212-246`). `listActions` returns `{label: NAME, name, description}` and, on failure, **a single sentinel option** *"No Available Actions — check your API key and refresh"* rather than a toast. Only the **checked** actions become live tools.
- Security worth copying: `sanitizeMCPToolDescription` (strip C0 / zero-width / bidi, truncate at 1,024, warn on 13 prompt-injection regexes), `sanitizeMCPToolName` (`[^a-zA-Z0-9_-] → _`, max 128), `validateMCPServerConfig` (command allow-list `CUSTOM_MCP_ALLOWED_COMMANDS` empty by default, arg / flag / env allow-lists, shell-metachar refusal).
- **`CustomMcpServerTool.ts`** + `CustomMcpServerDialog.jsx` (1,107 lines): a workspace-level registry — URL, `authType ∈ {NONE, CUSTOM_HEADERS}`, header table, status `PENDING | AUTHORIZED | ERROR`, and a **"Discovered Tools"** section from a live connect. Headers stored encrypted; URLs masked as `${origin}/************` in lists.
- UI: `asyncMultiOptions` with `refresh: true` renders an `IconRefresh` that remounts the dropdown (bumps a `key`) — manual refresh, no polling.

## 8. Reference captures

`images/flowise_agentflow.gif` (14.7 MB, the v2 canvas in motion — primary),
`images/flowise.gif` (4.9 MB, v1), `images/flowise.png`, `assets/Demo.png`,
`packages/ui/src/assets/images/agentflow-generator.gif`, `next-agent.gif`,
`Exporting.gif`, and the empty-state illustrations `validate_empty.svg` /
`executions_empty.svg`. They stay in `D:\Flowise-main`.

## 9. Adopt, beat, avoid

**Adopt** — the v2 node identity (category colour, squircle icon, summary
chips); gradient edges with a 15px hit path and hover-only delete; branch
labels on the dangling connection line; red/green handles during drag; seed
with a Start node and refuse a second; export strips secrets; the one-event
status pipeline; snap/background as toggles at `[25,25]`, off by default;
Enter-saves / Escape-cancels rename; "Use Template" through the same load
path as import.

**Beat** — ship **undo/redo** (Flowise has none); real selection
copy/paste; ports **≥ 12px visual with a ~24px hit ring, coloured by type**;
**live client-side validation against the canvas** rather than a stale
server checklist; **per-node timing** on every trace entry; **per-node retry,
error edges and fallback** (entirely absent); the concurrent-edit guard on
the modern canvas; visible feedback on a rejected cycle.

**Avoid** — the whole-flow paste sniffer; `crypto-js` passphrase AES; a
global transport switch for MCP; mirroring edges into `inputs` by hand.
