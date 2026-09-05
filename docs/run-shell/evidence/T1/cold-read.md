# T1 cold read — the three report headers

Reader: RC (cold). Inputs: the three PNGs only — no source, no brief, no other
notes. Answers to questions 1–3, copied from
`docs/run-shell/evidence/RC/answers-3.md`.

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
