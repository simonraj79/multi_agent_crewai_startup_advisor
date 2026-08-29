# Validator Studio frontend

Vue 3 + TypeScript + Vite + Vue Flow console for the `idea-validator` workflow.
It renders the fixed validator topology and drives it from the FastAPI service's
frame stream (`/api/…` and `/ws`), falling back to a scripted mock when no
backend answers.

## Commands

```powershell
npm install
npm run dev     # dev server on http://localhost:5173, proxying /api and /ws to 127.0.0.1:8000
npm run build   # vue-tsc -b (app, node and test projects) then vite build
npm test        # vitest run - single pass, exits; npm run test:watch for the watcher
```

## Tests

Vitest with the jsdom environment. Specs live in [`tests/`](tests) and never
touch a socket, a server or a paid API: `tests/helpers.ts` provides a
deterministic `StudioApiLike` double that `useValidatorRun` accepts by injection,
and `tests/studioApi.spec.ts` drives the real transport against a fake
`WebSocket` and a stubbed `fetch`.

Coverage focuses on behaviour that has broken before:

| Spec | Protects |
| --- | --- |
| `edgeAnimation.spec.ts` | The three-way research fan-out animates all its edges at once, each with its own lifetime, ending when its branch settles and leaking no timers. |
| `quarantineNode.spec.ts` | The `unattributed` quarantine node is rendered, counted, quiet when empty and loud when it holds frames. |
| `runRecovery.spec.ts` | Saved run context: kept for an in-flight run, cleared at a terminal state, and safe when site data is blocked. |
| `gateCard.spec.ts` | PRD F03 / Scenario C: an expired gate stays answerable and reads as a notice, never a lockout. |
| `frameHandling.spec.ts` | Gate, node-state, usage, dedup and gap-replay frame handling, including unknown frame kinds. |
| `studioApi.spec.ts` | Stream cursor, reconnect, ping, gate acks, frame pagination and snapshot normalisation. |
