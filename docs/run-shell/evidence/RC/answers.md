# Cold read (RC)

I was given no brief, no code and no conversation. Everything below comes from
looking at the named PNGs and nothing else. Where I could not tell, I say so.

---

## 1. `T1/report-header.png` — the verdict, and why

**The verdict is NEEDS WORK — 6.0 out of 10, "Moderate confidence · 62%".**

It is NEEDS WORK rather than the pass that a 6/10 would otherwise suggest
because the header says outright that the answer is not finished: the amber chip
reads **"Provisional · not a final answer"** and the chip beside it reads
**"Thin evidence · Demand and Headroom over free"** — so two of the five things
being scored rest on evidence the system itself does not consider solid, and it
declines to turn a middling score into a verdict.

## 2. Which dimension caused it, and what it scored

The image names **two**, not one: **Demand** and **Headroom over free**, each
carrying a small amber **`thin`** tag next to its name. **Both scored 3/5.**

An honest limit here: *every* dimension in this shot scored 3/5 — Demand, Market,
Competitive room, Feasibility and Headroom over free all show 3/5 with visually
identical bars. So nothing in the scores singles those two out; the only thing
that does is the `thin` tag. If a single dimension is wanted, Demand is the one
named first in the header chip, but the image gives me two and I cannot tell
which of them weighed more.

## 3. Which dimensions have thin evidence

**Demand**, and **Headroom over free**. Those are the only two carrying the
`thin` tag, and the header chip names the same two in words.

---

## 4. `G4/roles-sheet.png` and `T2/characters-32px.png` — telling them apart

**Can I tell the 32 px characters apart? Mostly yes — but only side by side.**

At the 6x magnified raster the cast is clearly differentiated: silhouette
(pointed teardrop vs round pebble vs bean), what sits on top of the head (a fin,
a bent antenna, a straight stalk, a sprout, a floating ring), eye style (plain
dots vs goggled "lens" rings) and mouth (grin, dot, jagged) all survive. At the
*true* 32 px thumbnails printed underneath, the reliable signals collapse to
about two: **colour** and **the head-top shape**. Faces are essentially gone.

**The two that look most alike: Scoper and Synthesist** (Idea Validator row).
Both are the same pale yellow-green, both are about the same size, and at true
32 px they read as the same creature. Magnified I can separate them — Scoper is a
taller pointed teardrop with a side fin and a wide toothy mouth; Synthesist is a
rounder pebble with a straight antenna and a small dot mouth — but at 32 px I
would only be confident with the two side by side. In isolation I would not bet
on which one I was looking at. (Runner-up pair: **Sentiment Analyst and
Feasibility Analyst**, both amber with big goggled eyes. Those two I *can* still
separate at 32 px, because Feasibility is visibly darker/browner and has a curl
rather than a straight antenna.)

The Copy Desk and Clinic Rota rows are easier, because they use colours the first
six do not (lilac, peach, pink) — which suggests colour is doing most of the work
at small sizes.

**Do any resemble something I already know?** Family resemblances, though nothing
that reads as a copy:

- The ones with a **floating ring above the head** (Analyst, Localisation Lead,
  Roster Architect) look a lot like a **Chao** from the Sonic games — same round
  body, same detached halo.
- The ones with a **stalk or sprout** growing out of the head read as **Pikmin**.
- The amber, goggle-eyed ones (Feasibility Analyst, Fact Checker) read a little
  like a **Minion** from Despicable Me — round, yellow, big ringed eyes.
- The overall silhouette — a rounded blob with two big dark eyes — is generically
  in **Pac-Man ghost / Boo** territory.

None of them made me think "that is character X" outright; they are their own
thing built from borrowed grammar.

**`T2/states-32px.png` — the six states.** Yes, I can tell all six apart at
32 px, and the sheet is honest about why: the eyes and the mouth are the only
things that change, and they change a lot. idle = neutral small mouth; working =
flat squinting slits and a lowered head; speaking = round open mouth, head tipped
back; blocked = amber outline round the whole figure plus a wilted frown;
blocked-error = the same frown with a red/pink outline; done = closed arc "happy"
eyes and a grin.

**The two closest are `blocked` and `blocked-error`**, and they are closest by
construction: the caption under each says the pose is the same, so the **only**
difference is the outline colour (amber vs red). At 32 px I can see that
difference on both themes, but it is colour and nothing else, so I would expect a
red/green colour-blind viewer to find them identical. `idle` and `working` are
the next closest, and those I can separate by the eyes alone.

---

## 5. `T2/trace-completed.png` — what the crew did, in order

Reading only what is on screen, top to bottom:

1. **Scoper** speaks first (04:15:23) — "I read the idea under test against the
   e…". Something scoped the idea.
2. **A second scoping entry at the same second** — "Revise scope here. I read the
   idea under test agains…". So the scope was done twice; something asked for a
   revision.
3. **Market Analyst** (04:15:28) — "I read A claim auditor that chec…".
4. **Sentiment Analyst** (04:15:33) — same phrasing.
5. **Feasibility Analyst** (04:15:38) — same phrasing. Three researchers, one
   after another, five seconds apart each.
6. **Synthesist** (04:15:38) — the one message shown in full: it says it read the
   idea "against the evidence I could actually retrieve", is "reporting what the
   sources support rather than what would make a tidier answer", and that **no
   model was called for this sentence — it is a synthetic stand-in with the shape
   of a real one.** So this is a rehearsal, not a real run.
7. **Review verdict** (04:15:39) — **"You approved"**. A human signed off.
8. **Validation report writer** started on Reporting, "thought for 1ms", then
   finished Reporting (all 04:15:39).
9. **Run** — **"Run finished"**.

So: scope → scope revised → three research passes (market, community sentiment,
technical feasibility) → synthesis → a human approves → the report is written →
done. I could follow that without any explanation, which is the main thing I
would want from a panel like this.

**Lines I cannot make sense of:**

- `"Startup validation sc…"` and `"Startup validation s…"` — the names are cut
  off, and three different rows share the same truncated prefix, so the list's
  most prominent text is its least informative part. I only know which agent each
  row is because the grey line underneath starts "Scoper here" / "Revise scope
  here" / "Synthesist here".
- `scoping_t_`, `market_ta_`, `sentiment__`, `feasibility_`, `synthesis_` — a
  monospace fragment between the name and the time. I assume it is an internal
  identifier; every one of them is truncated too, so it tells me nothing while
  costing the row a third of its width.
- `"Validation report writer thought for 1ms"` — I understand the words, but
  "thought for 1ms" is odd enough that I would suspect a placeholder rather than
  a measurement, especially on a run that says no model was called.
- `"Review verdict / You approved"` appears with no visible line before it saying
  I was *asked* anything. The approval is recorded; the question is not, at least
  not in this crop.
- The seam just above "Review verdict": a half-cut `▸ Details` line is clipped
  under the Synthesist bubble, so two regions appear to overlap by a few pixels.

---

## 6. `T3/before-1440.png` vs `T3/after-1440.png` (and the light pair)

**The "after" reads as the more finished product**, clearly, in both themes.

The three differences I noticed first:

1. **The report header stopped talking in codes.** Before: `NEEDS_WORK`,
   `62% confidence`, `MODERATE`, `PROVISIONAL`, `Thin evidence: D, X`. After:
   `NEEDS WORK`, `Moderate confidence · 62%`, `Provisional · not a final answer`,
   `Thin evidence · Demand and Headroom over free`. "D, X" meant nothing to me on
   the before shot — I could not have told you what X was.
2. **The score list explains itself.** Before it was headed `RUBRIC DIMENSIONS`
   with five bare labels. After it is headed `SCORES`, and each dimension carries
   a plain question underneath — "Is anyone actively trying to solve this today?",
   "Is there money, and can you name whose?" — plus the amber `thin` tags on the
   two weak ones. I understood what was being measured only in the after.
3. **The left-hand trace rail became populated by characters and human names.**
   Before: grey circles with two-letter stubs (`SY`, `RE`, `VA`, `WO`) over lines
   like `write_report to persist` and `workflow / Synthetic validator completed`.
   After: small coloured characters over `Validation report writer started on
   Reporting`, `Confirm scope / Waiting for you`, `Review verdict / You approved`,
   `Run finished`. The before rail reads like a log; the after reads like a story.

Smaller things I also noticed: the status word changed from `Completed` to
`Finished`; the gates helper text changed from "Pauses for you at the scope and
verdict gates" to "Pauses for you at every human gate"; and the after shows
9 calls / $0.0034 against the before's 6 / $0.0022, so they are not the same run.

**The light pair is the bigger win.** In `before-1440-light.png` a whole class of
small labels is washed out to near-invisible pale cyan on white — `LIVE ACTIVITY`,
`FIXED VALIDATOR GRAPH`, `VALIDATION REPORT`, `RUBRIC DIMENSIONS`, `Connected`,
`MODERATE`, and the inline `SyntheticValidatorRunner` chip, which I had to hunt
for. In `after-1440-light.png` all of those are dark enough to read at a glance.
That alone would decide it for me.

**Is anything in the after harder to read than in the before? Yes, two things:**

- **The trace rail's top block truncates the names.** The before rail showed
  `Synthesist` and `Reporter` in full; the after shows `Startup validation sc…`
  twice, `Community deman…`, `Technical feasibilit…`, plus those cut-off
  monospace fragments. More rows fit, but the row headings got worse.
- **The score bars lost contrast.** Before, a bright bar sat on a dark track and
  the filled proportion was obvious. After, the fill is a pale mint-to-blue
  gradient on a light track — and in the light theme especially, the pale mint end
  of the bar is hard to separate from the track it sits in. The `3/5` numeral is
  doing more work than the bar now.

I would also note the same clipped `▸ Details` seam in the after rail that I
mentioned in question 5; it is not in the before.

---

## 7. The six state captures

| Image | What state I read | Anything broken |
| --- | --- | --- |
| `S/empty.png` | Nothing has run yet: the pipeline is drawn, the trace rail says "Run activity will appear here", status **Ready**, 00:00 / 0 calls / $0.0000, Launch armed and Download logs greyed out. | Nothing broken. Two nits: node body text is tiny at this fit, and the small "Unattributed" card floating top-right is so dim I nearly missed it. Also this shot has gates set to **Unattended** where every other shot shows **Review** — I do not know whether that is deliberate. |
| `S/first-run.png` | A run in flight and **paused at the first human gate**: "Confirm — waiting for you", step 2 of 7, the Confirm scope node ringed amber, and a gate card on the right with the scoped fields, a Feedback box, Approve / Revise and "29:59 remaining". | Nothing broken or overlapping. The gate card pushes "Idea to validate" and the rest of the rail below the fold, which is reasonable but does mean the run controls are off-screen while you answer. |
| `S/long-run.png` | A **finished** run with the full report open and the trace scrolled to the end — 44 events, status Finished, 9 calls, $0.0034, "Run finished" at the bottom. | Readable throughout. One flaw: at the boundary between the pinned "what the crew said" block and the scrolling list there is a **clipped half-line** (`▸ Details` cut in two) — the two regions overlap by a few pixels. |
| `S/failure.png` | A **failed run of a user-built graph** ("cast failure state"): red Error chip, a red "Run failed" banner, step 3 of 4 marked red, the node showing `SyntheticRefusal: SYNTHETIC_FAILURE… attempt 1` with a "Re-run from here" button, status **Failed**. | Nothing broken. It is repetitive — the same truncated failure sentence appears four times in a row (twice from the specialist, twice from System) — and each one is cut off at "attempt 1…", so I never see the end of the error. |
| `S/narrow.png` | A very **narrow viewport** (phone width), where the right-hand rail has become a **drawer sitting over** the console, with chevron handles on both edges to pull the panels back. Status Finished. | It works, and the drawer's own contents are legible and unclipped. The console *behind* it shows as a sliver of half-cut words down the left edge (`NE`, `Mod 62%`, `Pro`, `Th`, `De`) — expected for an overlay, but untidy, and there is no dimming to say "this layer is not the one you are using". |
| `T2/reduced-motion.png` | A run **mid-flight in the research stage with motion switched off**: step 3 of 7 "Research — Market still pulling", a static boat-and-rowers mark, the Market Analyst node ringed and marked RUNNING with a tool-call chip under it, Launch replaced by a "Running…" button and Cancel armed. | Nothing broken. The caption under the mark (`MARKET SIGNAL BUILD`) is very small but legible, and the still reads fine as a still — I would not have known animation was missing if the filename had not said so. |

---

## 8. `G1/graph.png` and `G1/trace.png` — can I tell what this is?

**Yes, without being told.** The graph is titled **Clinic Rota Planner**, and the
step strip plus the node titles spell out the job: **Clinic brief → Forecast
demand → Confirm the demand** (a human gate — "Waiting for you: Confirm the
demand", then "You approved") **→ Draft the rota → Audit the rest rules → Breach
count / Redraft notes → Rota legal? → Plan the cover → Write the notice → Staff
notice.** The brief on the right fills in the rest: opening hours, "one GP is on
leave Thursday and Friday", "eleven hours between shifts, no more than three late
finishes per person per week".

So: it takes a clinic's staffing brief, forecasts how much cover is needed, has a
human confirm that forecast, drafts a staff rota, audits it against working-time
rules, counts breaches and loops back to redraft if the rota is not legal, plans
locum cover for the gaps, and finally writes a notice for the staff. There is a
`×4` badge under "Draft the rota", which I read as it having gone round that loop
four times.

**The agents, from the trace rail, are named plainly:** Shift Demand Forecaster,
Roster Architect, Rest Rules Auditor, Locum Cover Planner, Handover Briefer. I
did not need the graph to work out who they are; the names say it.

**Do the small characters on the graph nodes match the ones in the side panel?**
**By colour, yes; by shape, I cannot tell.** In the panel the Forecaster is
lilac/purple, the Roster Architect and Rest Rules Auditor are green, the Locum
Cover Planner is teal-blue and the Handover Briefer is pink. On the canvas the
"Forecast demand" badge is the same lilac, "Draft the rota" and "Audit the rest
rules" the same green, "Plan the cover" the same teal — and the larger figure in
the step strip above "DRAFT THE ROTA" is the green one, which is the right agent
for that step. That is a consistent story. But the on-node badges are roughly ten
pixels across in this capture, so I am matching **hue and rough silhouette only**;
I genuinely cannot verify at this size that each is the same character rather
than a same-coloured sibling.
