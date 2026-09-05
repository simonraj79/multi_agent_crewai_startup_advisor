# Cold read — answers (RC, pass 2)

I have seen only the PNG files listed in the questions. I have not read any source, any
brief, or any other document in this repository. Everything below is what I can see in
the pictures.

---

## 1. `T1/report-header.png` — what is the verdict, and why that rather than what the score suggests?

The verdict is **REJECT**.

The score sitting next to it is **4.2/10** at "Moderate confidence · 50%", which on its
own reads like a middling, arguable result — not a kill. The panel headed **"WHAT
DECIDED THIS RUN"** explains the gap in one sentence: **"Demand scored 0 of 5. Nobody in
the evidence describes having this problem. A zero on Demand rejects the idea whatever
the other scores say."** So it is a rejection by rule, not by arithmetic — a single
dimension bottoming out overrides the average, and the page says so in plain words
before showing me any numbers.

Worth noting: this is the first screenshot of this kind I have had to read where I did
not have to work out *why* the badge and the number disagree. The red-bordered box tells
me, unprompted, in a sentence a non-specialist can read.

## 2. Same image — which dimension caused it, and what did it score?

**Demand**, and it scored **0 out of 5**.

Three separate things on screen agree on this and I did not have to cross-reference
them: the callout names Demand explicitly; the chip near the top reads "Thin evidence ·
Demand"; and in the SCORES list the Demand row carries a small amber **"thin"** pill, an
empty red-tinted bar, and **0/5** at the right. Its question is printed under the label —
"Is anyone actively trying to solve this today?" — which makes the zero intelligible
rather than abstract.

## 3. `T1/report-header-insufficient.png`

**What is the verdict, and why.** The verdict is **NEEDS WORK**, score **3.8/10**, "Low
confidence · 34%". The "WHAT DECIDED THIS RUN" box (amber here, not red) reads: **"Too
little evidence to judge. Confidence came out at 34%, under the bar this system needs
before it will call anything final. The five scores below stand, but the answer does
not."** So the deciding factor is *insufficient confidence*, not any particular score —
the run is refusing to commit rather than delivering a judgement. The chip "Provisional
· not a final answer" says the same thing a second time.

**Is a dimension named as blocking, and did it decide the verdict?** Yes, one is named,
and no, it did not decide it. Below a divider inside the same box, under a quieter
heading **"ALSO BLOCKING"**, it says: **"Market scored 0 of 5 — no buyer segment was
named and no price was found. On stronger evidence that alone would reject the idea."**

The wording is doing careful work and I think it succeeds. "ALSO BLOCKING" is visually
subordinate — smaller, greyer, under a rule — so I read it as secondary before I read a
word of it. And the sentence itself gives me the counterfactual: this zero *would* have
been a rejection if the evidence had been stronger, but it was not, so it is not the
reason. I could not have got that from a badge and a number; I only know it because the
page wrote it down. Compare with image 1, where the equivalent statement was the
headline and phrased as decided fact ("rejects the idea whatever the other scores say").
The two boxes are the same component saying two genuinely different things, and the
difference is legible.

**Which dimensions have thin evidence?** **Market** — and only Market, as far as the
image shows. The chip at the top reads "Thin evidence · Market" (singular, and it names
the dimension in words rather than an initial), and the Market row carries the amber
"thin" pill next to its label. Demand above it is 2/5 with no pill. The image is cut off
partway through "Competitive room", so I cannot see the remaining rows — but the chip
names only Market, and in the other image the chip and the pills agreed, so I take the
chip as the complete list.

---

## 4. `G4/roles-sheet.png` and `T2/characters-32px.png` — can I tell the 32px characters apart?

**In a row, easily. In isolation, mostly — with one honest reservation.**

Working from the six Idea Validator characters at true 32px, and confirming against the
6× magnified rasters above them (which show me exactly which pixels survive):

- **Scoper** — pale yellow-green, pear/bell body, a stubby fin sticking left off the
  top, narrow rectangular eyes, a small grin.
- **Market Analyst** — periwinkle blue, egg-shaped, a thin straight antenna with a dot
  on the end, a cat-like "w" mouth.
- **Sentiment Analyst** — warm yellow, round pebble body, a curved antenna leaning
  right, rectangular eyes, a wide smile.
- **Feasibility Analyst** — deeper amber/gold, bean body, a little curl on top, and the
  distinguishing feature: **big round goggle eyes** rather than slots, plus a small
  round "oh" mouth.
- **Synthesist** — pale green, pebble body, a long thin antenna leaning right, slot
  eyes, an "oh" mouth.
- **Reporter** — cyan, bell body, a sprout/leaf shape on top, an "oh" mouth.

Covering the others, colour alone gets me four of the six immediately (blue, cyan,
amber, gold). The **two that look most alike are Scoper and Synthesist** — both are a
pale yellow-green, both are a rounded body with slot eyes, and at 32px the hue
difference is a couple of steps at most. **I could still tell them apart at 32px**, but
by *silhouette*, not colour: Scoper's topknot is a stubby fin canted left, Synthesist's
is a long thin antenna canted right, and that difference survives the raster clearly.
Their mouths differ too (grin vs a round "oh"), though at true 32px the mouth is two or
three pixels and I would not want to rely on it. The second-closest pair is Sentiment
Analyst vs Feasibility Analyst — both yellow-ish — but Feasibility's big round goggle
eyes separate them instantly, and that is the most legible single feature on the whole
sheet.

The `G4` sheet extends this to nineteen characters across four flows, and the same rule
holds: within any one flow they are all distinct, and the parts that carry the
distinction at small size are, in order, **colour, then top-knot shape, then eye shape**.
Mouths are decoration at 32px. Two things I noticed that seem deliberate: the sheet says
"no pair-flow art. Every character is a pure function of its role string, so a flow the
cast's builder never saw gets real characters rather than a row of grey question marks"
— and the fourth block is labelled "AUTHORED AFTER FREEZE 6833089", i.e. a flow the art
was not drawn for, and those five are as distinct as the shipped six. That is a real
claim and the picture supports it.

**Do any resemble something I already know?** Yes, and I do not think it is accidental:

- The overall silhouette — rounded dome, flat-ish base, rectangular pixel eyes — reads
  as a **Pac-Man ghost**, particularly the Reporter and Scoper.
- The ones with a **floating ring/halo above the head** (Analyst in Brief Crew,
  Localisation Lead in Copy Desk, Roster Architect in Clinic Rota Planner) read very
  strongly as a **Chao from Sonic Adventure**. That is the closest match on the sheet and
  the one I recognised before reading any label.
- The bulb-with-a-sprout body is a bit **onion/garlic**, which gives the whole cast a
  faintly vegetable feel — Animal Crossing gyroids or Plants vs Zombies territory, though
  much less specific than the Chao resemblance.

None of them is a copy of anything I can name. The Chao similarity is the one I would
flag if a designer asked.

**`T2/states-32px.png` — can I tell the six states apart at 32px?**

Yes, all six, comfortably. Left to right: **idle** (neutral, small resting mouth),
**working** (eyes narrowed to slits, flat mouth, body leaning), **speaking** (wide round
eyes, round open mouth, tipped back), **blocked** (an outline glow around the whole
figure, wide staring eyes, the topknot **wilted/drooping**, a frown), **blocked-error**
(outline glow, **X X for eyes**, wilted topknot, frown), **done** (eyes closed into
happy arcs, a broad grin). The states differ in pose and face, not only in colour, which
is what makes them survive the raster.

**Would someone who cannot distinguish red from amber still tell "blocked" from
"blocked-error"?** **Yes, easily.** The outline colour is the *only* thing those two
states share as a signal, and it is not carrying the distinction: **blocked has wide
open circular eyes, blocked-error has X-crossed eyes.** At 32px the X eyes are the most
conspicuous thing in the cell — I picked them out before I noticed the outline colour at
all. Both also carry the wilted topknot, so "something is wrong" is communicated by
posture independently of any colour, and "wrong how" by the eyes. The caption under each
spells it out too ("wide eyes + wilt + warn outline" vs "x_x eyes + wilt + error
outline"). This is the right way round: colour is the redundant channel here, not the
load-bearing one.

---

## 5. `T2/trace-completed.png` — what did the crew do, in order?

Reading only the visible lines, top to bottom:

1. **Startup validation scoper** (labelled *Scoping*), 05:37:45 PM — says it read the
   idea under test against the evidence it could actually retrieve.
2. **Startup validation scoper** again, one second later at 05:37:46 PM, this time
   saying **"Revise scope here…"** — so the scope was redone.
3. **Market evidence analyst** (*Market*), 05:37:51 PM.
4. **Community demand analyst** (*Sentiment*), 05:37:56 PM.
5. **Technical feasibility analyst** (*Feasibility*), 05:38:01 PM.
6. **Startup validation synthesist** (*Synthesis*), 05:38:01 PM — its message is expanded
   in full: "Synthesist here. I read A claim auditor that checks numbers in newsroom
   drafts against the evidence I could actually retrieve, and I am".
7. **Review verdict**, 05:38:02 PM — **"You approved"**. So a human was asked and said
   yes.
8. **Validation report writer** started on Reporting, 05:38:02 PM.
9. **Validation report writer** "thought briefly".
10. **Validation report writer** finished Reporting.
11. **Run** — **"Run finished"**, 05:38:02 PM.

In plain words: a scoper framed the idea, then re-framed it; three specialists went off
in parallel and looked at market, community sentiment and technical feasibility; a
synthesist pulled their findings together; a human approved the verdict; a writer
produced the report; the run ended. I could reconstruct that without being told
anything, which is the point of the panel. The three middle analysts landing five
seconds apart with distinct names and distinct faces is what makes the parallel step
readable as parallel.

**Lines I cannot make sense of:**

- **"Startup validation scoper — Revise scope here. I read the idea under test agains…"**
  at 05:37:46, one second after the first scoper line and *before* any human is shown
  approving or rejecting a scope. I cannot tell from this panel what triggered a
  revision, or whether it is a second pass or a different step wearing the same name.
- **"Validation report writer thought briefly"** — I can guess it means an internal step
  with no output worth showing, but "thought briefly" is not something I can verify or
  act on.

**Names or labels that are cut off:**

- Every preview line in the pinned **"WHAT THE CREW SAID"** block ends in an ellipsis:
  "…against the e…", "…under test agains…", "…I read A claim auditor that chec…", and
  "…that c…" twice.
- The **Synthesist's expanded message ends mid-sentence** — "…and I am" — with no
  ellipsis and no visible continuation.
- The **"Review verdict" row is clipped at its top edge** where it passes under the
  pinned block above it; its avatar is missing and the heading text is sliced. It is
  readable but it looks like a rendering seam, not a deliberate boundary.
- Two numeric badges, **44** (top right) and **8** (on the crew block), are unlabelled —
  I can guess "events" and "messages" but the picture does not say.

---

## 6. `T3/before-*.png` vs `T3/after-*.png`

**The "after" reads as the more finished product**, in both themes, and it is not close.
The "before" reads like an internal tool showing me its own field names; the "after"
reads like something written for a person.

**The three differences I noticed first:**

1. **The trace rail gets faces and real names.** "Before" shows flat circles with
   two-letter monograms — **SY**, **RE**, **VA**, **WO** — next to terse labels
   ("Synthesist", "Reporter", "Validation brief", "workflow"). "After" shows a distinct
   little character per speaker and spells the role out: "Startup validation scoper",
   "Market evidence analyst", "Community demand analyst", "Technical feasibility
   analyst", "Startup validation synthesist", "Validation report writer". I can tell who
   is who at a glance in the "after" and I genuinely could not in the "before" — **VA**
   and **WO** meant nothing to me.
2. **The score block explains itself.** "Before" is headed "RUBRIC DIMENSIONS" and lists
   five bare labels. "After" is headed "SCORES" and prints the question each one answers
   underneath — "Is anyone actively trying to solve this today?", "Is there money, and
   can you name whose?", "Is the incumbent set beatable on a stated axis?", "Can two or
   three engineers ship a v1?", "Is the core already free and good?" — and tags weak rows
   inline with a small **"thin"** pill.
3. **The jargon is gone from the header.** "NEEDS_WORK 6.0/10 62% confidence" plus a
   separate "MODERATE" badge and a chip reading **"Thin evidence: D, X"** becomes "NEEDS
   WORK 6.0/10", one chip reading "Moderate confidence · 62%", and **"Thin evidence ·
   Demand and Headroom over free"**. "D, X" was a code I could not decode from the
   screen; the "after" just says which dimensions.

A fourth, smaller one: "PROVISIONAL" becomes "Provisional · not a final answer", which
tells me what the word means rather than assuming I know.

**Is anything in the "after" harder to read?** Yes — one thing, and in the dark theme it
is serious.

**In `after-1440.png` the report card is translucent and the graph behind it shows
straight through the text.** The heading "Validation report - NEEDS_WORK" has node cards
("Sentiment Analyst", "Feasibility Analyst") sitting inside its letters; the line "This
report is produced by SyntheticValidatorRunner… exercisable at zero cost" has the
Synthesist node overlapping it; and worst of all the two chips at the top collide with
the stage strip behind them, so "Provisional · not a final answer" and "Thin evidence ·
Demand and Headroom over free" are overprinted with "CONFIRM", "RESEARCH", "SCORE",
"REVIEW", "REPORT", "BRIEF" and a "Brief - done 7/7" header. The "before" card is opaque
and has none of this. `S/long-run.png` shows the same bleed-through, so it is not a
one-off capture artefact.

**On the score bars specifically:** in the dark theme they are about equally readable in
both — same mint-to-blue fill, same 3/5 readout — except that in the "after" the empty
part of each track has graph nodes visible behind it, which adds noise the "before" does
not have. **In the light theme the "after" is clearly better:** `before-1440-light.png`
renders the filled bars in a pale mint/cyan on white with no visible track, which is very
low contrast and hard to read at a glance; `after-1440-light.png` uses a strong
dark-green-to-blue fill against a visible grey track. That is a real improvement, and it
is the one place where the light theme is the better evidence of the two.

So: the "after" wins on everything I would call product quality, and loses one point on a
panel that should be opaque and is not.

---

## 7. State by state

- **`S/empty.png`** — Idle, nothing has run: status "Ready", elapsed 00:00, calls 0,
  tokens 0, cost $0.0000, the trace rail says "Run activity will appear here.", the graph
  is drawn but every node is grey/idle, and a green **Launch** is armed. **Nothing
  broken.** Two small observations: the gate toggle is sitting on **Unattended**, which
  the panel itself warns "Runs the whole pipeline without stopping. Costs more" — a
  slightly surprising default for a first-time screen; and the node body text is far too
  small to read at this zoom, though that is the canvas fit, not a defect.
- **`S/first-run.png`** — A run is in flight and has **stopped at the first human gate**:
  the strip says "Confirm - waiting for you", step 2 of 7, the graph's "Confirm scope"
  node is outlined amber and marked WAITING, and the right rail has opened an "OPERATOR
  GATE / Confirm scope" card with editable fields, a Feedback box, **Approve** and
  **Revise**, and a "29:59 remaining" countdown against a 06:06 PM deadline. **Nothing
  broken.** The MARKET QUERY field's text is clipped by the input width ("…newsroom
  drafts marke") — ordinary input overflow, not a layout fault.
- **`S/long-run.png`** — A finished run with the report open: status "Finished", 00:16, 9
  calls, 6.4K tokens, $0.0034, the full report scrolled into view. **Two problems.** (a)
  The report card is translucent, so the graph shows through it — faint node boxes sit
  behind "Validation report - NEEDS_WORK", the "Score breakdown" table and the score bars,
  and the stage-strip labels bleed through the chips at the top. (b) In the trace rail,
  the "Review verdict / You approved" row is **clipped at the seam** under the pinned
  "WHAT THE CREW SAID" block. Neither makes the page unusable; both look unfinished.
- **`S/failure.png`** — A **failed** run of a different, published graph ("cast failure
  state"): the strip reads "fm_cast_refusal - failed", 2 of 4, step 3 is a red circle,
  status is "Failed", and the trace ends "Run failed: fm_cast_refusal attempt 1
  (SyntheticRefusal)". The failing agent's character has **X eyes**, which reads as broken
  at a glance without needing the colour. **Not broken, but two things look awkward:** the
  canvas shows only **one** node for a run the stepper says has four steps, which is
  disorienting; and **two dismissible banners stack** at the top of the right rail
  ("Running your published graph cast failure state. It asks for idea." above "Run
  failed"), the first of which is now stale and still has its own close button.
- **`S/narrow.png`** — Narrow viewport, finished run, with the right rail opened as a
  **full-height overlay drawer** covering most of the width; the report behind it is
  dimmed. Reasonable behaviour for the width. **Minor:** the drawer's content runs past
  the bottom of the viewport — the **Cancel** button is cut in half by the screen edge —
  and the header collapses to just the logo, "Connected" and a sign-out button, so the
  workflow name is gone.
- **`S/narrow-rail-open.png`** — Same narrow viewport, but paused at the Confirm scope
  gate with the gate card in the drawer. **This one does look broken.** The panel is
  translucent and the trace behind it prints straight through the card: I can read "…on
  scoper", "05:36:34 PM", "…could actually retrieve, and I am reporting", "…model was
  called for this", "…s a synthetic stand-in with the shape of" and "…idation scoper
  started on Scoping" *inside* the gate's own fields and between its labels. On the one
  screen where the operator is being asked to make a decision, the decision card is the
  least readable thing in the picture. Also the STARTUP IDEA and MARKET QUERY values are
  clipped by the field width ("…small veterinary clinic"), and "Idea Validator" at the
  foot is cut by the viewport.
- **`T2/reduced-motion.png`** — A run mid-flight with motion switched off: stage 3 of 7,
  "Research - Market still pulling", the Market Analyst node outlined cyan and marked
  RUNNING with a live search string under it, status "Running", the Launch button
  replaced by a disabled "Running…". **Nothing broken.** The little rowing-crew graphic
  above the stepper is a static still with the three branch labels (MARKET SIGNAL BUILD)
  under it and reads perfectly well frozen — which is the thing a reduced-motion capture
  needs to prove. Nothing overlaps, nothing is clipped.

---

## 8. `G1/graph.png` and `G1/trace.png` — can I say what this is without being told?

**Yes, and in some detail.** This is a **staff rota planner for a clinic**. The title
says "Clinic Rota Planner", and the input box shows a real brief — "…list to 20:00 on
Tuesday; baby clinic Wednesday morning. One GP is on leave Thursday and Friday. Rest
rules: eleven hours between shifts, no more than three late finishes per person per
week." The ten-step strip lays out the whole job in order: **CLINIC BRIEF → FORECAST
DEMAND → CONFIRM THE DEMAND → DRAFT THE ROTA → AUDIT THE REST RULES → BREACH COUNT →
ROTA LEGAL? → PLAN THE COVER → WRITE THE NOTICE → STAFF NOTICE**, and the canvas repeats
those as nodes with one-line descriptions. It is currently at step 3 of 10, "Draft the
rota", running, having already been through a human gate ("Confirm the demand — You
approved").

**Who the agents are** comes straight off the trace rail, no decoding needed: **Shift
Demand Forecaster**, **Roster Architect**, **Rest Rules Auditor**, **Locum Cover
Planner**, **Handover Briefer**. Those five names plus the ten step titles are enough for
me to describe the whole workflow to someone else, which is not something I could have
done from the "before" screenshot in question 6.

**Do the characters on the graph nodes match the ones in the side panel?**

**By colour, yes — clearly, and I checked each one.** In the rail: Shift Demand
Forecaster is **lilac/purple**, Roster Architect is **mint green with a floating halo
ring**, Rest Rules Auditor is **teal**, Locum Cover Planner is **light blue**, Handover
Briefer is **pink**. On the canvas and in the stepper the same colours appear on the
matching nodes — a purple figure on "Forecast demand", a **mint-green-with-halo** figure
on the running "Draft the rota" node *and* in the step-4 marker of the strip above, teal
on "Audit the rest rules", light blue on "Plan the cover". The halo is the easiest
cross-check and it lands in both places. This also matches the five characters shown in
the "Clinic Rota Planner" block of `G4/roles-sheet.png`.

**By shape, only as far as silhouette.** The node avatars are rendered very small — a
dozen pixels or so — so I can confirm body outline and top-knot (the halo, the antenna)
but I cannot resolve eyes or mouths on the graph nodes to compare them with the rail.
Everything I *can* resolve agrees; I just want to be clear that "match by shape" is a
claim I can only make at the silhouette level from these two images.

One incidental note: the trace's top block shows all five agents having "returned a
structured result", four of them at the same second (03:57:36 PM), while the graph still
shows the run at step 3 of 10 and "Running". I cannot reconcile those two from the
pictures alone.
