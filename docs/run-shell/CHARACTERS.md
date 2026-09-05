# The cast — Pips

The run console's character system. One agent, one **Pip**: a single-piece
rounded creature with no limbs, no face-plate and no separate head, assembled
from five hash-selected parts and animated by six CSS classes.

Written by W2 on `run-shell/cast`. It covers T2.3 (kawaii, original, legible at
32 px), T2.4 (compositional and deterministic from identity), the determinism
half of G3, and the sheet behind G4. **The interpretation layer and the run
choreography are not here** — this module is given a state and it draws it; what
decides that an agent is `working` rather than `speaking` is W3's and W4's work.

| | |
| --- | --- |
| Generator | [`frontend/src/characters/pip.ts`](../../frontend/src/characters/pip.ts) — pure, no imports, no DOM, no clock |
| Component | [`frontend/src/components/AgentCharacter.vue`](../../frontend/src/components/AgentCharacter.vue) |
| Stylesheet | [`frontend/src/assets/styles/character.css`](../../frontend/src/assets/styles/character.css) |
| Tests | `frontend/tests/characterSystem.spec.ts` (44), `frontend/tests/characterDeterminism.spec.ts` (30) |
| Sheets | `frontend/scripts/character-sheet.mjs` → `evidence/T2/characters-32px.png`, `evidence/T2/states-32px.png`, `evidence/G4/roles-sheet.png` |
| Figures below | `frontend/scripts/character-stats.mjs` — **regenerate, never quote** |

---

## 1. What a Pip is

A rounded body, two oversized eyes, a small mouth, and a flourish growing out of
the crown. The crown flourish is **cut from the body's own fill**, so it fuses
into a single silhouette rather than reading as a hat on a ball — that is the
whole reason the cast stays legible when it shrinks.

**Four marks on screen, never more:** body (crest included), eye, eye, mouth.
Cheeks and eye sparkles are a **detail tier** the generator switches off below
48 px, because at 32 px they are mud rather than charm. That is a rule enforced
in two places — `pipSvg` omits the markup, and `.pip--sm .pip-detail` hides it
if a caller forces it on — not a guideline.

Eyes are 6.4 units across in a 32-unit box: the pair spans roughly 58% of the
body's width. That single number is the kawaii proportion argument, and every
other measurement was fitted around it.

## 2. Part inventory

| Part | Variants | Selected by | Why it is on this axis |
| --- | ---: | --- | --- |
| **Body** | 4 — `pebble`, `drop`, `bean`, `bell` | `mix32(h)` bits **0–7** mod 4 | Silhouette is the only identity cue that survives 32 px, so it carries the widest variation: squat-and-wide, tall-and-tapered, two-lobed-with-a-waist, flared-with-two-feet. All four stand on the same floor (`y = 28`) so a row of Pips lines up, and all four are one closed path so the crest can be cut from the same fill. |
| **Eyes** | 4 — `round`, `oval`, `square`, `lens` | bits **8–15** mod 4 | **Shapes, not expressions.** Expression belongs to the state; an identity that already looked like it was winking could not then be asked to look worried. `lens` is a donut and is the one variant that needs no sparkle. |
| **Resting mouth** | 3 — `smile`, `cat-w`, `oh` | bits **16–23** mod 3 | Only `idle` wears it; the other five states override the mouth. That is exactly why this axis gets three variants and not six — two thirds of its value would be spent on states the agent is not in. |
| **Crown** | 6 — `antenna`, `sprout`, `curl`, `ring`, `fin`, `ears` | bits **24–31** mod 6 | One group, `currentColor`, hinged at the body's own crown point. It is also the part that **wilts** when the agent is blocked, and the part that is drawn **1.3× larger below 48 px** — see §4, where the reason is a cold reader's finding rather than a preference. |
| **Colour** | 12 — `--character-1 … --character-12` | **raw FNV-1a mod 12** (not the mixed word) | Byte for byte the index `useRunChoreography.characterIndex` already assigns, so a Pip is the colour its node's medallion and handoff token already are. |

**4 × 4 × 3 × 6 × 12 = 3,456 distinct characters**, and all 3,456 are reachable
— measured, §6.

Each body carries its own `eyeY`, `eyeDx`, `mouthDy`, `crownX/Y` and
`crestScale`, so a part swap never lands a mouth in a waist or an eye off the
edge. Those five numbers are the interface between the parts, and they exist
because the first draft got two of them wrong.

## 3. The hash

House style — FNV-1a 32-bit, the loop from `characterIndex` kept verbatim —
plus one documented finaliser.

```ts
const FNV_OFFSET = 0x811c9dc5
const FNV_PRIME  = 0x01000193

export function fnv1a(input: string): number {
  let hash = FNV_OFFSET
  for (let index = 0; index < input.length; index += 1) {
    hash ^= input.charCodeAt(index)
    hash = Math.imul(hash, FNV_PRIME) >>> 0   // the only 32-bit multiply JS has
  }
  return hash >>> 0
}

export function mix32(word: number): number {  // Murmur3-style `lowbias32`
  let x = word >>> 0
  x ^= x >>> 16;  x = Math.imul(x, 0x7feb352d) >>> 0
  x ^= x >>> 15;  x = Math.imul(x, 0x846ca68b) >>> 0
  x ^= x >>> 16
  return x >>> 0
}

export function normaliseIdentity(value: string): string {
  return (value || '')
    .normalize('NFKD')
    .replace(/[\u0300-\u036f]/g, '')   // drop the combining marks NFKD produced
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, ' ')
    .trim()
}

export function characterSeed(key: string): string {
  return normaliseIdentity(key) || 'agent'
}

export function pipParts(key: string): PipParts {
  const raw = fnv1a(characterSeed(key))
  const mixed = mix32(raw)
  return {
    body:   (mixed         & 0xff) % 4,
    eyes:  ((mixed >>>  8) & 0xff) % 4,
    mouth: ((mixed >>> 16) & 0xff) % 3,
    crest: ((mixed >>> 24) & 0xff) % 6,
    colour: (raw % 12) + 1,            // == characterIndex(seed)
  }
}
```

**Why the finaliser is there, and why the colour skips it.** Raw FNV-1a's last
operation is a multiply, so its low bits are a shallow function of the last
bytes fed in — and `% 4` and `% 6` read exactly those bits. Agent roles are
natural language, and natural language has a small set of endings, so a family
of roles that rhyme lands in one hat: two ordinary role words hashing to wholly
different 32-bit numbers were measured agreeing under `% 4`, `% 6` **and** `% 8`
alike, which made them the same creature in all four shape axes. One `mix32`
before the slice costs three multiplies and fixes it. `characterSystem.spec.ts`
pins that with three rhyming roles that must stay apart.

The **colour** deliberately does not go through it. `characterIndex` has no
finaliser, and a Pip whose body was a different colour from its own node
medallion would be a worse defect than the bias: the spec asserts
`pipParts(key).colour === characterIndex(key)` for the same string. Twelve
colours over a sixteen-node graph must collide anyway — `characterIndex`'s own
comment already says so.

`% 4` on a byte is exact; `% 3` and `% 6` carry a bias under 0.4%, which §6's
measured distribution confirms is invisible.

### Normalisation, and the bug it had

`"Tone Coach"`, `"tone-coach"` and `"  TONE   COACH "` are one agent;
`"Senior Editor"` and `"Editor"` are two.

**Dropping the combining marks is a separate step and it has to be.** NFKD
decomposes an accented letter into a base letter *followed by* a combining
mark, and that mark then sits in the middle of a word — so handing it straight
to `[^a-z0-9]+` turns it into a space and splits the word. `Résumé Writer`
became `re sume writer`: three tokens, a different hash, and a different
creature from the same name typed without the accent. That was in the first
draft of this function and a test caught it; the fixture now carries both
spellings and asserts they hash the same.

### The fallback chain

**`role` → `nodeId` → `task` → the literal `'agent'`.**

`nodeId` outranks `task` deliberately. A task name is authored text that a
router can vary between two passes of the same node, so hashing it ahead of the
node id would repaint the cast mid-run — the exact defect `characterIndex`'s
docstring says it exists to avoid. A node id is fixed for the life of the graph
and is on every frame. `task` is kept as the last resort before the literal,
because a frame carrying neither a role nor a node id still carries something a
human wrote, and a character built from it beats every such agent sharing one.

**What the fallback looks like is: an ordinary Pip.** No placeholder face, no
question-mark badge, no grey. A system whose strangers look broken punishes the
author of every flow it has never seen — which is the whole case for a
generated cast. `identityFor` returns `named: false` so the **caption** beside
the figure can show the node id instead of a role; that is the only difference,
and it is outside the character.

## 4. The six states

One SVG. Both eye layers and all five mouths are in the markup; CSS shows
exactly one of each, so the mark count on screen stays at four. Nothing
re-renders on a frame — a run event sets a class.

| State | Pose and expression | Motion | Reduced motion | What drives it |
| --- | --- | --- | --- | --- |
| **idle** | Upright. Full open eyes. The hash-selected resting mouth. | **None.** | Identical — already still. | Node has not started, or the run has not launched. |
| **working** | Leans in `rotate(5deg)`. Eyes squint to `scaleY(0.4)` — two bars. Short flat mouth. Detail tier off. | `pip-bob`, **2600 ms** ease-in-out infinite: `translateY(0 → −0.9 → 0)` on the shell only. ≈0.9 px of travel at 32 px. | Keeps the lean and the squint. | Node is running. |
| **speaking** | Tips back `rotate(-3deg)`. Eyes open. Big filled oval mouth. | `pip-speak`, **640 ms** ease-in-out infinite: `scaleY(1 → 0.42 → 1)` on the mouth *only*, inside a ~5 px box. | Mouth stays fully open. | The agent is producing text a rail is revealing. |
| **blocked** | Eyes widen `scaleY(1.14)`. Crown **wilts** `rotate(-22deg)` about its own hinge. Small downward mouth. `--warn-border` outline. | **None**, beyond a one-shot 480 ms `pip-settle` on arrival. | Identical after 480 ms. | A human gate is open on this node. |
| **blocked-error** | Same wilt, same frown, **eyes closed into two crosses** (`×_×`), outline from `--err-border`. | Same one-shot. | Identical. | The node failed. |
| **done** | Eyes close into two arcs `^ ^`. Wide filled grin. Settles `scale(1.04, 0.95)`. | **None.** | Identical. | Node completed. |

The right-hand column is what the state *means*, not something this module
computes. **The mapping from run events to these six words is W4's**
(`useRunChoreography.ts`); `AgentCharacter.vue` takes `state` as a prop and
reads no clock, no store and no frame.

**Idle, blocked, blocked-error and done are static, and that is a decision.**
Sixteen idle nodes breathing is sixteen things moving; stillness is what makes
the one working node legible, and it is what keeps the live-animation count
inside plan 11's bound of twelve on a graph of any size. Blocked in particular
does not pulse: a pulsing ring on the one node waiting for a person competes
with the gate card that is asking them for something, and an amber outline at
32 px is already the loudest signal this system has.

**`blocked` and `blocked-error` are separated by two signals, not one, and the
second one was added after a cold reader found its absence.** Given the sheets
alone, the reader reported that the amber and the red outline were the only
difference between the two states — which means a colour-blind viewer sees one
state where the product means two. The general rule that breaks is that colour
must never be the sole carrier of a distinction, so `blocked-error` now also
closes its eyes into two crosses. The cross is the kawaii idiom for it, it is
four straight strokes so it survives the 32 px raster where a subtler
expression would not, and it is the largest change the eyes can make short of
closing them entirely, which `done` already owns. The wilt, the frown and the
pose stay shared, so the two states still read as one family.

`characterSystem.spec.ts` asserts this structurally rather than by eye: it
parses `character.css`, collects what each state's rules declare, and requires
that whatever `blocked-error` does and `blocked` does not includes at least one
property that is not a colour.

### The small tier is not the big one scaled down

Below 48 px three things change, and each was measured rather than guessed.
The detail tier goes off (cheeks and sparkles are mud at that size). The crown
is drawn **1.3× larger** (`SMALL_CREST_SCALE`). And the whole figure **drops
two units** down the box (`SMALL_LIFT`) so the bigger crown still fits.

The crown grew because the same cold reader could not confidently separate two
same-coloured agents at a true 32 px. That is measurable rather than a matter
of taste: at 32 px the body and the eyes are shared vocabulary across a
sixteen-node graph, so the crown is doing nearly all of the identifying work,
and the crown was five or six units of a 32-unit box — two or three actual
pixels. One of the confused pair wore a `fin`, which at that size was
indistinguishable from the `bell` body's own peak.

**The drop rather than a shrink is the point.** Making headroom by scaling the
figure down would have taken the eyes with it, and the eyes are the other thing
that has to survive 32 px. The box has four unused units under the floor and
this spends two of them. `characterSystem.spec.ts` re-measures all twenty-four
(body × crest) pairs at **both** tiers, because growing the crown is exactly
the change most likely to put one back outside the box.

Both numbers are applied by the generator and not by CSS, and that is forced:
`.pip-crest-hinge` already owns `transform` for the blocked wilt and
`.pip-figure` owns it for the pose, and `transform` is one property — a CSS
boost on either would be silently dropped the moment a state applied. The spec
asserts that neither selector grows a `transform` rule.

**Every loop starts at its reduced-motion pose.** `pip-bob` is written
`0% → translateY(0)` and `pip-speak` `0% → scaleY(1)` specifically so that a
still of a Pip at `t = 0` and a Pip with motion disabled are the same picture. A
screenshot therefore cannot flatter this design, which is what makes the
evidence sheets trustworthy. `pip-settle` is the one exception and it is a
one-shot that *ends* at rest, so any capture more than 480 ms after the class
arrives is the static picture.

Under `@media (prefers-reduced-motion: reduce)` every character animation is
`animation: none` — the third of the reduced-motion blocks `docs/design.md` §5
names. `characterSystem.spec.ts` asserts that by **parsing `character.css`**:
every selector that declares an animation outside the block must appear inside
it. A list in a comment goes stale the first time somebody adds a keyframe; a
parse does not.

### Offscreen

`AgentCharacter.vue` runs an `IntersectionObserver` and adds `pip--paused` when
the figure is not intersecting, which sets `animation-play-state: paused` on the
two animated elements. Paused rather than cleared: `animation: none` would snap
the pose back to `t = 0` and a Pip scrolled halfway off a rail would visibly
jump. The observer is disconnected on unmount, and its absence is guarded —
jsdom has none, and there the character simply animates, which is what it did
before the pause existed.

## 5. Tokens

`docs/design.md`: a value is a token or it does not exist. **`character.css`
contains no hex triple and no colour function at all**, and both
`characterSystem.spec.ts` and W5's `designTokens.spec.ts` assert it.

| Token | Where it lands | Why it works in both themes |
| --- | --- | --- |
| `--character-1 … --character-12` (`motion.css`) | Body and crest, via `style="color:var(--character-N)"` + `fill: currentColor` | The theme swaps the value; the SVG never learns which theme it is in. |
| `--bg-node` (`tokens.css`) | Eyes, mouth, cheeks (at `opacity: .2`) | It **inverts**: `#2a2a2a` dark, `#ffffff` light. So the ink is always the opposite of the card the Pip sits on — dark eyes on a pastel body in dark theme, white eyes on a deep body in light theme, with no second rule. |
| `--text-title` | Eye sparkle | Inverts the same way. In dark theme it reads as a shine; in light theme, as a pupil in a white eye. Both are correct kawaii and neither needed a special case. |
| `--warn-border` | The blocked outline | Already the product's "a human is holding this up" colour — it is what the gate textarea pulses to. |
| `--err-border` | The blocked-error outline | The product's existing error border. |
| `--motion-medium`, `--ease-out` | The pose transition between states, and the one-shot settle | The existing transition-scale tokens, used for a transition. |

**The two loop durations (2600 / 640 ms) are literals, and that is the house
rule rather than an exception to it.** `motion.css` already writes every loop it
owns as a literal — `gradientShift 6s`, `glowPulse 3s`, `borderPulse 4s`,
`run-node-land 480ms`. The two duration tokens are transition-scale (160/260 ms)
and would be wrong for a loop.

**Contrast.** No new colour means no new contrast risk: the twelve values were
chosen against `--bg-node` in both themes and a Pip is a flat fill of one of
them. The only derived value is the cheek, `--bg-node` at 20% over the body
colour — a darkening in dark theme and a lightening in light theme, and in both
cases a fraction of a difference that already passes.

## 6. Measured, not asserted

Regenerated on 2026-09-05, after the cold reader's two changes, by
`cd frontend && node scripts/character-stats.mjs`,
against `src/characters/pip.ts` at head. **Re-run it rather than quoting this
block** — the command is the contract and the number never is.

```text
distribution over 200,000 synthetic keys, % per bucket
  body   24.99 24.91 25.04 25.07
  eyes   24.98 24.92 25.01 25.09
  mouth  33.57 33.31 33.12
  crest  16.71 16.95 16.84 16.75 16.39 16.36
  colour 8.25 8.29 8.26 8.44 8.29 8.41 8.13 8.45 8.16 8.44 8.34 8.54

distribution over a 450-role natural-language corpus, count per bucket
  body   pebble=109 drop=113 bean=112 bell=116
  eyes   round=130 oval=116 square=97 lens=107
  mouth  smile=146 cat-w=145 oh=159
  crest  antenna=80 sprout=65 curl=69 ring=77 fin=87 ears=72
  colour c1=36 c2=45 c3=27 c4=36 c5=53 c6=35 c7=34 c8=38 c9=50 c10=41 c11=23 c12=32

distinct characters reachable            3456 of 3456
keys needed to hit all of them            26,322

unrelated-pair full collision, 400,000 pairs  0.00038   (1/3456 = 0.00029)
natural corpus: 450 roles -> 423 distinct characters
natural corpus colours used              12 of 12

axes that differ, one word apart
  Analyst / Senior Analyst               5 of 5  (body, eyes, mouth, crest, colour)
  Writer / Technical Writer              5 of 5  (body, eyes, mouth, crest, colour)
  Researcher / Senior Researcher         4 of 5  (body, mouth, crest, colour)
  Editor / Copy Editor                   4 of 5  (body, eyes, crest, colour)
  Coach / Tone Coach                     3 of 5  (mouth, crest, colour)
  Checker / Fact Checker                 3 of 5  (body, eyes, colour)
  Reporter / Reporters                   2 of 5  (body, colour)

last-character edit -> same colour        0.05143 over 100,000
last-character edit -> same character     0.00009

five spellings of one name -> 1 character
empty role -> node id                     {"key":"n7 second pass","named":false}

markup size at 32px (no detail tier)      1822 bytes
markup size at 96px (detail tier on)      1998 bytes
```

**The 450-role corpus is the sample that matters**, and it is included because
synthetic keys do not rhyme and the hash's only real weakness would be on roles
that do. 450 natural-language roles built from 24 heads × 18 tails give **423
distinct characters** — 27 collisions against a birthday expectation of about
29 — and use all twelve colours.

**The honest limit.** Full collisions between *unrelated* roles happen at about
1 in 3,456, and **partial** collisions are much commoner: two roles sharing
body, eyes and crest and differing only in mouth and colour occur about 1 in 48.
The evidence sheet shows a real instance — on the six-role flow, two agents come
out `pebble/lens/…/antenna` and are separated by mouth and by `c5` versus `c12`.
Colour is doing real work there and the sheet shows it working. The alternative
— assigning characters by graph position — would give the same agent a different
face in two flows, which is the defect this replaces.

## 7. The 32 px raster, and what it found

`scripts/character-sheet.mjs` rasterises every figure at exactly 32×32 through a
canvas and magnifies it 6× with `imageSmoothingEnabled = false`. A vector drawn
at 96 px and a vector drawn at 32 px are the same picture on a design sheet and
two different pictures on a screen, and this is the difference. It is the only
test of the "reads at 32 px" claim that is not an assertion — the same lesson
`docs/gotchas-and-insights.md` already carries about jsdom mounts and the two
builder layout defects: **a structural assertion never asks how wide anything
ended up.**

It has found four real defects so far. Three were found while the system was
being designed:

- **The `bean` body's eyes touched both edges.** The first draft was a narrow
  leaning peanut ~15 units wide; the eye pair needs 12.8 of that plus margin, so
  at 32 px it read as a damaged blob with its eyes cut into the outline. The
  bean is now two lobes in one outline, 17 units across the eye line.
- **The bean's mouth was in its waist.** `mouthDy` became a per-body number.
- **The `oh` mouth vanished.** `rx/ry` went 1.6/1.3 → 1.8/1.5.

The fourth was found by the first sheet rendered in this repository:

- **Four of the twenty-four (body × crest) pairs poked out of the top of the
  viewBox** and were cut flat by the raster — `bean` + `ring` worst at −0.72
  units. Because `.pip-svg` sets `overflow: visible` they were not clipped in
  the live DOM; they spilled outside the figure's own box instead, which on a
  32 px node slot is the same defect in a different coat. The antenna and the
  ring were shortened and the bean's `crestScale` cut from 0.94 to 0.86.

The fifth and sixth came from a **cold reader who saw only these sheets** and
neither the code nor the brief, which is the one instrument this system cannot
supply for itself:

- **`blocked` and `blocked-error` differed only in the hue of the outline** —
  amber against red — so a colour-blind viewer saw one state where the product
  means two. `blocked-error` now closes its eyes into two crosses as well. §4
  carries the reasoning and the structural check that keeps colour from ever
  being the sole difference again.
- **Two same-coloured agents were separable when magnified but not "in
  isolation" at a true 32 px.** The crown was carrying nearly all of the
  identifying work at five or six units of a 32-unit box. It is now drawn 1.3×
  below 48 px with the figure dropped two units to fit it — see §4. The same
  finding put the eyes under suspicion, so the four variants were rasterised on
  one body at 32 px in both themes: `lens` turned out to be the *most*
  distinctive of the four, not the least — its open centre survives clearly,
  where `round` and `oval` are the closest pair. No widening was needed, and
  the spec now measures that the four differ in construction and in width so a
  later edit cannot quietly collapse them.

Every (body × crest) pair clears the top edge by at least **0.45 units at the
large tier and 0.52 at the small one**, and `characterSystem.spec.ts` measures
all twenty-four at both tiers rather than trusting these paragraphs.

## 8. Regenerating everything

```powershell
Push-Location frontend

# the three evidence sheets (HTML kept beside each PNG). ALWAYS pass --roles:
# the committed sheets include the flow RV authored after the freeze, and a
# bare run would silently drop it back to the three the system shipped with.
node scripts/character-sheet.mjs --roles ../docs/run-shell/evidence/G4/g1-roles.json

# the cross-process determinism fixture
node scripts/character-snapshots.mjs

# the figures in section 6
node scripts/character-stats.mjs

npx vitest run tests/characterSystem.spec.ts tests/characterDeterminism.spec.ts
Pop-Location
```

`--roles` takes a JSON file shaped
`{ "flows": [{ "name": "...", "note": "...", "roles": ["..."] }] }`, resolved
against the working directory. `docs/run-shell/evidence/G4/g1-roles.json` is
the committed one, and its fourth entry is the `Clinic Rota Planner` flow RV
authored after the freeze — five roles the cast's builder never saw, which is
what makes G4's claim about an unfamiliar flow checkable rather than asserted.
A flow with an empty `roles` array renders as a labelled empty section rather
than disappearing, which is how that slot was held open before RV filled it.

## 9. Originality

Reproduced verbatim in `evidence/T2/originality.md`.

A Pip has **no limbs, no feet, no face-plate, no separate head and no outline**
— which rules out, structurally rather than by promise, every silhouette a
reviewer is likely to have in mind. It is not Kirby (defined by arms, feet and
shoes on a sphere), not Among Us (defined by a single visor and a backpack,
where a Pip has two separate wide-set eyes and nothing on its back), not Pusheen
(a striped quadruped cat), not Tamagotchi (a pixel grid inside a device
chrome), not a Slack or Notion mascot, and not ChatDev's art — none of which is
in this tree and none of which was opened while this was drawn.

Every part is a path written by hand in `pip.ts` as SVG numbers. **No part is
traced from, rotoscoped from, or modelled on an existing character**, no asset
was downloaded, no sprite sheet exists, and there is no image file of any kind
in the system: the whole cast is 1,822 bytes of generated markup per figure
and a stylesheet.

What a Pip actually resembles is a **river stone, a seed pod, an acorn** —
closed, weighted, sitting on a floor — and that is the point: these are small
quiet objects, not performers. The appeal comes from three decisions that are
cheap to state and hard to fake. **The crown grows out of the body instead of
sitting on it**, so 3,456 creatures share one silhouette logic and none of them
looks accessorised. **The face is only ever three marks**, so it is readable at
the size the graph actually renders and it never competes with the text an
operator came to read. And **the whole cast is generated**, so the system is at
its best exactly where a hand-drawn cast is at its worst — the thirteenth agent
of a flow nobody has seen, which gets a real character with a crest, a colour
and a mouth of its own rather than the grey question mark every competitor
shows there.
