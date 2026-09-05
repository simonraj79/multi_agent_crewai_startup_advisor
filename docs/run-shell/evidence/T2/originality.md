# T2.3 — originality statement and part inventory

W2, `run-shell/cast`, 2026-09-05. The system is documented in full at
[`docs/run-shell/CHARACTERS.md`](../../CHARACTERS.md); this file is the part
inventory and the statement, verbatim, so a verifier grading T2.3 does not have
to read the whole design note.

Evidence beside this file: `characters-32px.png` (thirteen roles rasterised at
exactly 32×32 and magnified 6× with smoothing off, dark, plus six on light) and
`states-32px.png` (all six states for two characters, at 96 px and at a true
32 px raster, dark and light). The `.html` that produced each PNG is kept
beside it; both were written by `frontend/scripts/character-sheet.mjs`, which a
verifier can re-run.

## The part inventory

Every part is a path written by hand in
[`frontend/src/characters/pip.ts`](../../../../frontend/src/characters/pip.ts)
as SVG numbers. There are twenty-three shapes in the whole system.

| Part | Variants | Each one is |
| --- | ---: | --- |
| **Body** | 4 — `pebble`, `drop`, `bean`, `bell` | one closed `<path>`, 4–6 cubic segments, standing on `y = 28` |
| **Eyes** | 4 — `round`, `oval`, `square`, `lens` | a `<circle>`, an `<ellipse>`, a rounded `<rect>`, and an even-odd `<path>` donut |
| **Resting mouth** | 3 — `smile`, `cat-w`, `oh` | a quadratic stroke, a double quadratic stroke, a filled `<ellipse>` |
| **Crown** | 6 — `antenna`, `sprout`, `curl`, `ring`, `fin`, `ears` | a stroke plus a `<circle>`; four filled `<path>`s; one stroked `<ellipse>` |
| **State mouths** | 5 more | a flat line, a filled oval, a downturned arc, a filled half-disc, plus the resting one |
| **Detail tier** | 2 | two cheek `<ellipse>`s at 20% opacity, two sparkle `<circle>`s — both off below 48 px |
| **Colour** | 12 | `var(--character-1 … 12)`, the palette `motion.css` already ships |

4 × 4 × 3 × 6 × 12 = **3,456 distinct characters**, all of them reachable
(measured: 3,456 of 3,456).

## The statement

**No part of this cast is traced from, rotoscoped from, derived from, or
modelled on an existing character.** Every shape is a hand-written list of SVG
coordinates. No asset was downloaded, no sprite sheet exists, no font is
loaded, no image file of any kind is in the system, and no third-party artwork
was opened while it was drawn. A whole figure is 1,574 bytes of generated
markup at 32 px, plus one stylesheet.

**What it is not, structurally rather than by promise.** A Pip has no limbs, no
feet, no shoes, no face-plate, no visor, no separate head, no accessory and no
outline. That rules out:

- **Kirby** — defined by arms, feet and shoes on a sphere. A Pip has none of
  those and cannot grow them: the body is one closed path.
- **Among Us** — defined by a single wide visor and a backpack. A Pip has two
  separate wide-set eyes and nothing on its back.
- **Pusheen** — a striped quadruped cat. A Pip is untextured, has no legs and
  no tail.
- **Tamagotchi** — a low-resolution pixel grid inside a device chrome. A Pip is
  a vector with no device around it.
- **ChatDev's characters** — the reference product's art, which is not in this
  repository. It was removed on purpose in 2026-09-02
  (`CLAUDE.md` remaining-work item 6) and nothing sprite-shaped came back.
  `frontend/tests/builderCardDesign.spec.ts` still asserts no `/sprites/` path
  reaches a card.
- **Any Slack, Notion, Figma or Duolingo mascot** — all of which are
  limbed, outlined, or built around a face-plate.

**What it does resemble, and deliberately:** a river stone, a seed pod, an
acorn. Closed, weighted, sitting on a floor. These are small quiet objects, not
performers, and that is the design: the cast has to sit inside a graph an
operator came to read without competing with it.

## Why it is appealing, in three decisions

1. **The crown grows out of the body instead of sitting on it.** It is cut from
   the same fill and hinged at the body's own crown point, so 3,456 creatures
   share one silhouette logic and none of them looks accessorised. It is also
   the part that wilts when the agent is blocked, which is the one gesture the
   figure makes.
2. **The face is only ever three marks** — eye, eye, mouth — with cheeks and
   sparkles switched off below 48 px in code rather than trusted to scale. That
   is what makes it readable at the size the graph actually renders.
3. **The whole cast is generated**, so the system is at its best exactly where a
   hand-drawn cast is at its worst: the thirteenth agent of a flow nobody has
   seen gets a real character with a crest, a colour and a mouth of its own,
   rather than the grey question mark every competitor shows there. The
   `Copy Desk` row on `characters-32px.png` is four such agents, and the fourth
   section of `../G4/roles-sheet.png` is reserved for a flow that did not exist
   when this was written.

## The one honest limit

Full collisions between unrelated roles happen at about 1 in 3,456. **Partial**
collisions are much commoner: two roles sharing body, eyes and crest and
differing only in mouth and colour occur about 1 in 48, and there is a real
instance on `characters-32px.png` — two agents of the six-role flow come out
`pebble / lens / … / antenna`, separated by their mouth and by `c5` versus
`c12`. Colour is doing real work there and the sheet shows it working. The
alternative, assigning characters by position in the graph, would give the same
agent a different face in two different flows, which is the defect this system
exists to replace.
