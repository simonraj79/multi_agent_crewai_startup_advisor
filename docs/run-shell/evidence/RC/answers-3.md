# Cold read — answers-3

Reader: RC (cold). Inputs: the listed PNGs only. No source, no brief, no other
notes read. Where I could not tell, I say so.

---

## 1. `T1/report-header.png`

**Verdict: REJECT.** Score 4.2/10, "Moderate confidence · 50%".

It is a REJECT *despite* a middling 4.2 because one dimension bottomed out. The
red panel headed **WHAT DECIDED THIS RUN** says it in plain words:
**"Demand scored 0 of 5."** and underneath, "Nobody in the evidence describes
having this problem. A zero on Demand rejects the idea whatever the other scores
say."

**Dimension that caused it: Demand. It scored 0 of 5** (the scores list confirms
`Demand 0/5`, with a small amber **thin** badge beside it; Market, Competitive
room and Feasibility are all 3/5, which is what pulls the composite up to 4.2).

The header also carries two chips: "Provisional · not a final answer" and
"Thin evidence · Demand".

I understood this in one pass without knowing anything about the product. The
override block is doing the whole job — the number alone would have misled me.

---

## 2. `T1/report-header-insufficient.png`

**Verdict: NEEDS WORK.** Score 3.8/10, "Low confidence · 34%".

**Why:** the amber panel says **"Too little evidence to judge."** — "Confidence
came out at 34%, under the bar this system needs before it will call anything
final. The five scores below stand, but the answer does not."

**Is a dimension named as blocking?** Yes. There is a separate sub-row inside the
same panel, ruled off and labelled **ALSO BLOCKING**: "Market scored 0 of 5 — no
buyer segment was named and no price was found. On stronger evidence that alone
would reject the idea."

**Did it decide the verdict?** **No** — and the wording makes that unusually
clear. The word "ALSO", the position below the main reason, and especially the
conditional "**On stronger evidence** that alone **would** reject the idea" all
say this is a second finding that did *not* get to decide, because the
low-confidence rule got there first. I read that correctly on the first pass and
did not have to guess. It is the one thing I would have expected a screen like
this to muddle, and it doesn't.

**Which dimensions have thin evidence?** Just one: **Market**. The chip at the
top reads "Thin evidence · Market" (spelled out, not abbreviated), and in the
scores list **Market** carries the amber **thin** badge and reads 0/5. Demand
reads 2/5 with no badge. Competitive room, Feasibility and Headroom over free
are below the crop of this screenshot, so I cannot see whether they carry badges
— but the header chip names only Market, so I would take that as the full list.

---

## 3. `T1/report-header-plain.png`

**No, there is no override block here.** Nothing between the chip row and the
`SCORES` panel — the layout goes straight from "Provisional · not a final
answer" / "Thin evidence · Demand and Headroom over free" into the five score
rows. Its absence is clean; there is no empty container or stray rule where the
red/amber box sat in the other two, so I would not have known a block *could*
appear if I had only seen this one.

**Does the header still tell me why the verdict is what it is?** Partly, and I
want to be precise about the gap.

- It tells me the **verdict** (NEEDS WORK), the **score** (6.0/10), the
  **confidence** ("Moderate confidence · 62%"), that the answer is
  **provisional**, and **which two dimensions are thin** (Demand, Headroom over
  free) — both of which carry a `thin` badge in the list, and all five score
  3/5.
- What it does **not** tell me is the *rule*. Nothing states the threshold — why
  6.0 lands on NEEDS WORK rather than on the neighbouring verdicts, or where the
  boundaries are. In the other two screens a sentence did that work for me. Here
  I have to assume "the verdict is just the score band", which is a reasonable
  inference but is nowhere written down.

So: it tells me **what**, and it tells me **what was weak**, but not **why that
number means that word**. For an ordinary run that is probably the right amount
of chrome — the interesting cases are the two above, and those are the ones that
explain themselves. But if a reader ever asks "why NEEDS WORK and not the next
band up", this screen has no answer for them.

---

## 4. Characters at 32 px — `G4/roles-sheet.png`, `T2/characters-32px.png`, `T2/states-32px.png`

### Telling them apart

Yes, mostly — but the work is being done by **colour first, silhouette second,
and face last**.

At the 6× magnification I can see five varying parts per figure (the monospace
caption under each spells them out, e.g. `bell/lens/cat-w/fin/c12`,
`pebble/oval/cat-w/antenna/c8` — body / eyes / mouth / topper / colour). At the
**true 32 px** row underneath, which is the size that actually ships on a node
badge:

- **Colour** survives completely. Every figure in a flow has a distinct hue.
- **The topper survives** — antenna, sprout, curl, bun, ears, fin all read as
  different shapes even that small, because they break the outline.
- **The mouth does not survive.** `smile`, `cat-w` and `oh` are two or three
  pixels; at true size they are a smudge. I could not tell you which mouth a
  32 px figure has without the magnified version beside it.
- **The eyes half-survive** — `lens` (big pale eyes with a dark ring) versus
  plain dark eyes is visible as "light eyes / dark eyes", but no finer.

**In isolation** (one badge, nothing to compare against): I could tell you the
colour and roughly the topper, and that is it. I do not think I could name a
character from a single 32 px badge cold; I could match one to a legend.

### The two that look most alike

Within the shipped six (`Idea Validator`): **Scoper** (`bell/lens/cat-w/fin/c12`)
and **Synthesist** (`pebble/lens/oh/antenna/c12`). They share a colour token
(`c12`) and both render as the same pale sage green, and both have the pale
ringed eyes. **At 32 px I could still tell them apart, but only by the topper**:
the Synthesist has a long thin antenna leaning right, the Scoper has a small
stubby fin and a wider, more pear-shaped body. Take the topper away and I would
be guessing. The mouths (a small "w" versus a small "o") are no help at that
size.

Second-closest pair, and arguably the harder one across the whole sheet:
**Sentiment Analyst** (`pebble/lens/smile/antenna/c5`) and **Feasibility
Analyst** (`bean/lens/oh/curl/c5`) — same yellow/amber family, both with a
topper that leans right. Here the body shape rescues it: the Feasibility Analyst
is visibly chunkier with much heavier-ringed eyes. At true 32 px I would call
this one about 80/20 rather than certain.

Across the four flows there is repetition of colour (mint green appears as
Analyst, Localisation Lead and Roster Architect; teal as Writer, Rest Rules
Auditor and Reporter) — but those never share a screen, so I do not think it
matters.

### Do any resemble a character I already know?

Yes, several, and I would flag two of them as more than vague.

- **The ball-on-a-stalk antenna over a round, limbless body** — most obviously
  the **Market Analyst** and **Fact Checker** — reads to me as a **Chao** from
  *Sonic Adventure*. The specific tell is the floating bobble held above the
  head on a thin stem; that is a Chao's most recognisable feature, and the
  proportions here (fat rounded body, no neck, oversized eyes filling the upper
  half) are the same.
- **The leaf/stem topper** — the `sprout` figures, e.g. **Reporter**, **Writer**,
  **Tone Coach** — reads as **Pikmin**. A small round creature with a stalk
  growing out of the crown of its head is Pikmin's whole visual identity, and
  the part is literally called `sprout` in the caption.
- **The teardrop/pointed-top bodies** (**Fact Checker**, and the `drop` bodies
  generally) read as a **Dragon Quest slime** — the rounded blob that pulls up
  to a point at the top, with a plain face and no limbs.
- More loosely: the whole cast reads as **onion/garlic bulbs with faces**, which
  is close to Pikmin's *Onion*; and the pink **Handover Briefer**, a limbless
  pink dome with dark eyes and an "o" mouth, reads a little **Kirby**-ish,
  though the eyes are the wrong shape for that to be a strong match.

None of these is a copy — the parts are simpler and the eyes are square rather
than oval — but the **Chao antenna** and the **Pikmin sprout** are close enough
that I noticed them unprompted, which is what you asked. If the intent was "not
recognisably anybody else's", those two toppers are the ones I would look at
again.

### `T2/states-32px.png` — the six states

Six states shown on two characters (Market Analyst, Tone Coach), each at 96 px
and at a true 32 px raster: **idle** (still, resting mouth), **working** (lean +
squint, 2.6s bob), **speaking** (tip back + open, 0.64s mouth), **blocked**
(wide eyes + wilt + warn outline, still), **blocked-error** (x_x eyes + wilt +
error outline, still), **done** (arc eyes + grin, still).

**Can I tell six apart at 32 px? Four cleanly, two with effort.**

- **blocked** and **blocked-error** are unmistakable — they gain a coloured ring
  around the whole figure, which is a huge signal at that size.
- **done** is clear: the eyes become closed arcs and the mouth a wide grin, a
  big light/dark change in the eye row.
- **working** is clear: the eyes flatten to two dashes and the whole figure
  tilts, so even the silhouette changes.
- **idle** and **speaking** are the pair I would struggle with. Both are upright
  with round dark eyes; the difference is a slightly wider mouth and a small
  backward tip. At true 32 px I would probably read "speaking" as "idle" if I saw
  it alone. In motion this presumably does not matter (one is animated, one is
  not) — but in a still, or with motion reduced, it does.

**Red/amber colour blindness — blocked vs blocked-error:** **Yes, still
distinguishable, and comfortably.** The two do not differ only by ring colour.
**blocked** has wide open round eyes and a flat/frowning mouth; **blocked-error**
has **x_x** — both eyes replaced by crosses — which is a completely different
shape and is legible at 32 px in both the dark and light captures. Someone who
saw both rings as the same colour would still read "worried" versus "dead". That
is the right way round: the colour is the reinforcement, the eye shape is the
message.

---

## 5. `T2/trace-completed.png` — what the crew did

A side panel titled **Agent trace** (under a "LIVE ACTIVITY" kicker) with a count
of **44**, and inside it a collapsible section **WHAT THE CREW SAID** holding
**8**. Reading it top to bottom:

1. **07:04:15** — *Startup validation scoper*, stage **Scoping**. Begins "Scoper
   here. I read the idea under test against the e…"
2. **07:04:16** — *Startup validation scoper* again, stage **Scoping**. This one
   begins "Revise scope here. I read the idea under test agains…" — so the scope
   appears to have been done once and then redone a second later.
3. **07:04:21** — *Market evidence analyst*, stage **Market**.
4. **07:04:26** — *Community demand analyst*, stage **Sentiment**.
5. **07:04:31** — *Technical feasibility analyst*, stage **Feasibility**.
6. **07:04:31** — *Startup validation synthesist*, stage **Synthesis**. This one
   is expanded to several lines rather than a single preview.
7. Below the section, in the plain trace: **07:04:32** *Validation report writer*
   **started on Reporting**; then **thought briefly**; then **finished
   Reporting**.
8. **07:04:32** — **Run** → **Run finished**.

So, in my own words: the scoper framed the idea and then immediately revised its
framing; three specialists then went off in turn to look at market, community
sentiment and technical feasibility, roughly five seconds apart each; a
synthesist pulled the three together; a report writer wrote it up; the run
ended. Each entry has a role name, a **stage label** under the name, a
timestamp, and a portrait — I could follow the whole shape of the run without
knowing anything about the system, which is the main thing.

### Lines I cannot make sense of

- **"Market Analyst here. I read A claim auditor that chec…"** — and the same
  construction in three more entries: *"Sentiment Analyst here. I read A claim
  auditor that c…"*, *"Feasibility Analyst here. I read A claim auditor that
  c…"*, and in full on the synthesist: **"Synthesist here. I read A claim
  auditor that checks numbers in newsroom drafts against the evidence I could
  actually retrieve, and I am"**. Read cold, this says the analyst read *a
  person* — "a claim auditor" — and the capital A mid-sentence makes it worse.
  I take it that the idea being validated is "A claim auditor that checks
  numbers in newsroom drafts" and it has been spliced into the sentence without
  quotation marks or any other bracketing. It needs quotes, or a colon, or the
  idea moved out of the sentence entirely.
- The **same sentence appears four times** with only the speaker's name changed.
  With four consecutive entries reading identically apart from the first two
  words, the section stops being informative — my eye slid straight off it.
- **The name on entry 2 contradicts its text.** The speaker is labelled
  *"Startup validation scoper"* but the body starts *"Revise scope here."* One
  of the two is wrong, or at least they are not the same voice.
- The synthesist's expanded text **ends mid-sentence**: *"…against the evidence I
  could actually retrieve, **and I am**"* — no ellipsis, no fade, just a stop. It
  reads as a rendering truncation rather than a deliberate summary, because the
  four collapsed entries above it *do* use a proper "…".

### Clipped / cut off

- **One whole trace row is clipped to nothing but its toggle.** Immediately below
  the "WHAT THE CREW SAID" section, before the first *Validation report writer*
  entry, there is a row showing **only "▸ Details"** — its title line, name and
  timestamp are hidden above the boundary. I cannot tell whose row it is. That
  is the one thing in this panel that looks broken rather than merely wordy.
- All four collapsed crew lines are **truncated with "…"** at the panel width
  (e.g. "…against the e…", "…that chec…"). That reads as intentional, but it
  means none of the four previews reaches any content specific to that analyst —
  every one of them is cut off inside the shared boilerplate.

---

## 6. `T3` before vs after

**The "after" reads as the more finished product, clearly, in both themes** —
and in the light theme it is not close.

### Three differences I noticed first

1. **The verdict line stopped talking in shorthand.** Before:
   `NEEDS_WORK` (underscore, code-looking), `6.0/10`, `62% confidence`, a
   separate `MODERATE` chip, `PROVISIONAL`, and — the worst of it —
   **"Thin evidence: D, X"**. I had no idea what D and X were. After:
   **NEEDS WORK**, `6.0/10`, one chip **"Moderate confidence · 62%"**,
   **"Provisional · not a final answer"**, and **"Thin evidence · Demand and
   Headroom over free"**. The chips went from four to three and every one of
   them now says something a stranger can read.
2. **The score block explains its own rows.** Before it was headed **RUBRIC
   DIMENSIONS** and each row was a bare noun plus a bar — "Competitive room"
   meant nothing to me. After it is headed **SCORES**, and under each name sits
   the question it answers: *"Is anyone actively trying to solve this today?"*,
   *"Is there money, and can you name whose?"*, *"Is the incumbent set beatable
   on a stated axis?"*, *"Can two or three engineers ship a v1?"*, *"Is the core
   already free and good?"*. The two weak rows also gained a small **thin**
   badge in place of the "D, X" abbreviation. This is the single biggest
   improvement in the set.
3. **The activity rail became populated by people rather than initials.** Before:
   grey circles reading **SY**, **RE**, **VA**, **WO**, each followed by the same
   long boilerplate paragraph repeated verbatim. After: a **WHAT THE CREW SAID**
   group at the top with a character portrait, a role name (*Market evidence
   analyst*), a **stage** under it (*Market*), a timestamp and a one-line
   preview. I can see the shape of the run at a glance now, where before I had to
   read four identical paragraphs to find out nothing.

Also worth naming, since it changes the impression more than any single item:
in the **light theme** the *before* is close to unusable. "FIXED VALIDATOR
GRAPH", "WHAT THE CREW SAID", "RUBRIC DIMENSIONS", the `MODERATE` chip, the
`SyntheticValidatorRunner` code chip and the "connected · seq 85" line are all
so pale on white that I had to hunt for them; the score bars are pale mint on
white and I cannot judge their lengths; and there are **grey rectangles bleeding
through** the report panel from the graph behind it (two bands, around the
"Score breakdown" heading and near the bottom). The *after* fixes all of that —
dark green-to-blue bars with real contrast, headings legible, no show-through.

### Is anything in the "after" harder to read?

Yes, three things, and one is a regression rather than a trade.

- **The "Score breakdown" table is gone.** In the before I could read all five
  rows (dimension, score, weight, note). In the after only the **header row**
  (`DIMENSION SCORE WEIGHT NOTE`) is visible before the pinned **"2 CITED
  SOURCES"** bar cuts it off — zero data rows. The taller new scores panel has
  pushed the table under the footer. Net, I now have less detail on screen than
  before, not more. Same at 1180.
- **The bars are shorter and start further right.** The new label column (name +
  question) is wide, so each bar has less run; five identical 3/5 bars are
  harder to compare than they were. Minor.
- **Two words for one state.** In the after, the graph header still says
  **"Completed"** while the right rail's STATUS says **"Finished"**. In the
  before both said "Completed". If those are meant to be the same state, one of
  them should change.
- One more I cannot call: in the **light** theme the *after* has a **dark left
  rail** against a white centre and white right rail, where the *before* had a
  light rail throughout. It may well be deliberate (a console-ish trace panel),
  and it is certainly more legible than the washed-out light version — but it is
  the one element that looks like it belongs to the other theme.

### `T3/after-1180.png`

**Yes — the report panel is fully visible beside the right-hand rail, and it has
its own header row.** The header row carries the **"VALIDATION REPORT"** kicker
on the left and, on the right, a **"Copy Markdown"** button and an **×** close
button, both fully drawn and not overlapping anything. The panel's right edge
clears the rail's left edge with a visible gutter; nothing is under anything
else. The verdict row has reflowed sensibly — "NEEDS WORK 6.0/10" on one line
and "Moderate confidence · 62%" wrapped onto the next — and all five score rows
with their questions are intact.

Two caveats at this size, neither about the rail: the report **body** is cut off
mid-sentence by the "2 CITED SOURCES" footer ("…No model was called" and then
nothing), and in the right rail the **Cancel** and **Download logs** controls
have fallen below the bottom edge — only **Relaunch** is reachable without
scrolling.

---

## 7. States — one line each

| Capture | State | Anything broken? |
| --- | --- | --- |
| `S/empty.png` | Never run. Graph drawn with all nodes idle, activity rail shows the placeholder **"Run activity will appear here."**, counters all zero, **Launch** enabled, Cancel and Download logs greyed. | Nothing broken. Layout is clean and the empty rail is a proper empty state, not a blank box. One nit: the header chip says **"Ready"** while the status block below says **"offline"** — two words about the same connection, and "offline" next to an enabled Launch button made me hesitate. |
| `S/first-run.png` | A run paused at the **first human gate** — stage strip reads "Confirm - waiting for you", 1/7, and the right rail has been replaced by an **OPERATOR GATE / Confirm scope** card with editable fields, a feedback box, **Approve / Revise**, and **"29:59 remaining"**. | Nothing broken. The **MARKET QUERY** field's value is truncated to "A claim auditor for newsroom drafts mar…" in a single-line input — expected, but it is the one value I cannot read in full. |
| `S/long-run.png` | A completed run with the report open over the graph; rail shows the full crew list plus the reporting steps and "Run finished". | Two things. The **"Score breakdown" table shows only its header row** before the "2 CITED SOURCES" footer covers it — no data rows at all. And in the rail, the same **row clipped to a bare "▸ Details"** appears under the crew section (see Q5), directly below a synthesist entry that stops mid-sentence at "and I am". |
| `S/failure.png` | A **failed** run of a published graph called "cast failure state" — red **"Run failed"** banner over the right rail, status **Failed**, stage 3 of 4 (`FM_CAST_REFUSAL`) ringed in red, and the failing node showing the error text plus a **"Re-run from here"** button. The rail carries two red-edged error entries and a System line "Run failed: fm_cast_refusal attempt 1 (SyntheticRefusal)". | Nothing overlapping or unreadable — the failure is communicated well, and the red left-borders on the two error rows are the right amount of emphasis. Two oddities: the canvas shows **only one node** for a graph whose strip claims four stages, so the workspace looks nearly empty; and the error sentence in the rail is truncated ("…SyntheticRefusal: Synthetic failure: fm_cast_refusal…") so the interesting part is cut. Also **ELAPSED 00:00** while CALLS is 1 and TOKENS 550 — the timer reads as not having run. |
| `S/narrow.png` | Narrow/phone width, run finished, with the right-hand rail opened as a **full-height drawer** over the content; the report is behind it. | Not broken, but there is **no scrim**. The report underneath shows through in a roughly 50 px strip down the left edge as a column of cut-off word-fragments ("NE", "Mod… 62%", "Pro", "Th", "D… is", "M… is") which reads as visual noise rather than as "there is a page behind this". A dim or blur behind the drawer would settle it. **Download logs** is below the fold. |
| `S/narrow-rail-open.png` | Same narrow width, but paused at the **Confirm scope** gate, with the gate card at the top of the drawer and Approve/Revise reachable. | Works. Same missing scrim — the activity rail shows through on the left as a strip of portraits and half-words. Two fields truncate to the same string ("A scheduling assistant for small veterinary cli…"), and the **WORKFLOW** row at the bottom is cut through the middle of "Idea Validator" by the viewport edge — scrollable, presumably, but the cut lands mid-control rather than between sections. |
| `T2/reduced-motion.png` | A run **in flight** with motion reduced: stage 2/7, "Research - Market still pulling", the Market Analyst node ringed and marked RUNNING while the other two branches sit idle; the rowers/boat mark drawn as a static still. | Nothing broken — this is the cleanest capture in the set. Everything that would animate is drawn in a settled pose and nothing is mid-transition or half-faded. Same **ELAPSED 00:00** oddity as `failure.png` while CALLS 1 / TOKENS 708 / COST $0.0004 are all non-zero. |

---

## 8. `G1/graph.png` and `G1/trace.png`

### Can I tell what this is, cold?

**Yes, and with more confidence than I expected.** This is a **staff rota
planner for a clinic** — building a work schedule for a GP surgery from a
written brief, and checking it against working-time rules.

I can say that from the visible text alone, without being told:

- The workflow is named **"Clinic Rota Planner"** and is a **PUBLISHED GRAPH**.
- The input box is labelled **"BRIEF TO RUN"** and contains a real brief:
  "…surgery 10:00-18:00 every weekday; a late list to 20:00 on Tuesday; baby
  clinic Wednesday morning. One GP is on leave Thursday and Friday. Rest rules:
  eleven hours between shifts, no more than three late finishes per person per
  week."
- The stage strip lays out the whole plan in order: **CLINIC BRIEF → FORECAST
  DEMAND → CONFIRM THE DEMAND → DRAFT THE ROTA → AUDIT THE REST RULES → BREACH
  COUNT → ROTA LEGAL? → PLAN THE COVER → WRITE THE NOTICE → STAFF NOTICE**, with
  the first three ticked, the fourth running, and a **×4** badge under it (a
  fourth pass, I assume).
- The node cards say what each step *does* in a sentence, including the gate:
  *"This is the demand the rota will be built against, and everything below it
  costs money. Approve the forecast, or send it back with what it got wrong."*
  That one sentence told me more about the system's design than the rest of the
  screen.

### Who are the agents?

Named on the node cards ("Run the authored agent 'X' on the cheap tier") and
again in the trace panel:

- **Shift Demand Forecaster** — forecasts the demand
- **Roster Architect** — drafts the rota
- **Rest Rules Auditor** — audits it against the rest rules
- **Locum Cover Planner** — plans the cover
- **Handover Briefer** — writes the notice

The non-agent steps are visibly different in kind — "Breach count" and "Redraft
notes" both say *"Apply the pick transform"*, and "Rota legal?" is a router —
so I could tell which boxes are people and which are plumbing.

### Do the graph characters match the panel ones?

**Yes — by colour, unambiguously; by shape, as far as the size allows.**

| Role | Graph node badge | Trace panel portrait |
| --- | --- | --- |
| Shift Demand Forecaster | *Forecast demand* — lilac/violet | lilac/violet |
| Roster Architect | *Draft the rota* — mint green | mint green |
| Rest Rules Auditor | *Audit the rest rules* — teal | teal |
| Locum Cover Planner | *Plan the cover* — pale blue | pale blue |
| Handover Briefer | (its node is below the visible fold) | pink |

All five also match the "Clinic Rota Planner" row of `G4/roles-sheet.png` on
colour. On **shape**, the node badges are far smaller than the panel portraits —
I can make out the rounded body and that a topper is present, and nothing
contradicts the panel, but I could not swear to "same mouth, same eyes" at that
size. Colour is carrying the identification, which given Q4's finding (colour
survives 32 px, faces do not) seems to be the honest state of affairs.

**One thing that does not line up**, and I mention it because it confused me for
a moment: the trace panel lists **all five** crew as having "returned a
structured result" at 06:22:24, including the **Handover Briefer**, while the
graph says the run is only at **stage 3 of 10** with most nodes still IDLE and
the Roster Architect only just started. The rail also shows **"Run started"
twice** (06:22:05 and 06:22:24), so I suspect the crew section is pooling two
runs. Either way, read cold, the panel says the last agent has finished and the
graph says it has not begun.
