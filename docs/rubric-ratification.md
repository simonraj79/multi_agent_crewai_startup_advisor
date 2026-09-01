# Rubric ratification record

**Decided 2026-09-01.** The owner delegated this decision explicitly. Until now
`RUBRIC_ANCHORS` had been *audited* and *adversarially reviewed*
([`rubric-review.md`](rubric-review.md), 13 findings) but never **ratified** —
and audited is not reviewed: a derivation error is a judgement nobody made, and
it cannot be found by running the suite.

Read this **beside** `rubric-review.md`, not instead of it. That document was
never updated when its own findings were repaired, so it overstates what is
broken. Section 4 below gives each finding's current status.

## Provenance, and why ratification was needed at all

PRD §10.2 writes out **only** the Demand ladder and labels it *"Illustrative"*.
M, C, F and X never existed in any specification: they were derived by an
earlier agent from the PRD's stated rules, weights, floors and dimension
questions. Four of the five ladders in this system, and three of its four fatal
floors, were therefore invented — soundly or not — by a process nobody had
checked end to end.

## The decision

| Ladder | Weight | Decision |
| --- | ---: | --- |
| **D** — Demand | 0.30 | Ratified, with C6 and C7 |
| **M** — Market | 0.20 | Ratified, with C2 |
| **C** — Competitive room | 0.20 | Ratified, with C5 |
| **F** — Feasibility | 0.15 | Ratified, with C4 — **level 0 retired** |
| **X** — Headroom over free | 0.15 | Ratified, with C1 and C3 |

The scoring **machinery** is ratified untouched and is the strongest part of the
system: the level-1 reservation, the `forbidden={2}` lower bound on X, anchor
separation, the recomputed counts, and the ordering of the confidence override.
The review's conclusion that it held under attack is confirmed.

## What was changed, and why

Seven changes were applied. Each was **measured against the shipped code**, not
argued from the text.

### C1 — the free-product REJECT must be attributed *(critical)*

`FLOOR_ALREADY_FREE` is a REJECT. Its **repository** route demanded four
machine-checked conditions on a URL a tool actually returned. Its **product**
route demanded one enum on a `Competitor` — and `Competitor.url` is optional
while `findings_urls` skips a null one, so an unsourced name written by a
cheap-tier agent entered **no closure check at all** and still returned
`REJECT / FLOOR_ALREADY_FREE` at composite 7.7, confidence 0.90 HIGH,
`provisional=False`, zero guardrail complaints.

That is finding F1's own failure shape, one level up.

`zero_ok` and `forbidden` now read `free_whole_attributed`. The **ceiling** still
reads the unattributed count, deliberately: an unverifiable claim may *lower* a
score, but it may not *kill* an idea.

### C2 — the market floor fired on one web page *(critical)*

`zero_ok = sources >= 1 and segments == 0` returned a final, non-provisional
`REJECT / FLOOR_NO_MARKET` on a **single** source. Worse, its justification was
fabricated: `config.py` cited a PRD floor of *"no money, no nameable buyer"* and
**the word "buyer" does not occur in PRD.md at all** (verified, 0 occurrences).
An invented provenance for a REJECT is worse than none, because the next reader
treats it as settled.

What the PRD actually supplies is the dimension *question* — "Is there money,
and can you name whose?" — a conjunction whose level-0 negation is **both**
halves. Firing on the buyer half alone rejects the commonest market-research
result there is, a category-revenue page naming no segment: measured at
confidence 1.0.

`RUBRIC_FLOOR_MIN_MARKET_SOURCES = 3` now gates the floor, M=1's lower bound
widened in the same edit, and both anchors carry the money conjunct. The stated
reason for previously refusing this — that it "would orphan the 1-2 source
states" — was also checkably false: the M ceiling's `else` branch is 3, so those
states never lost a legal score.

### C3 — the top of X was awarded for a question nobody asked *(critical)*

`free_named` counts neither `None` nor `"NONE"`, so *"the branch established
nothing is free"* and *"the branch never asked"* were the **same state** to the
ceiling. Measured: two competitors with coverage unset produced X ceiling 5 and
`VALIDATE` at composite 10.0 — and the all-`"NONE"` state produced a
**byte-identical** `DimensionSupport`.

The tri-state distinction that `Competitor`'s docstring, `market_task` and
`config.py` each defend at length was erased at the one place it decides a
score, in the direction that manufactures a VALIDATE. An unsettled competitor
now caps X at 3.

> The test written to defend this had a docstring stating the correct semantics
> and assertions that contradicted it — it looped over `None` **and** `"NONE"`
> asserting an identical ceiling. It has been split. This is why 796 green tests
> could not see the defect.

### C4 — F level 0 and `FLOOR_NOT_BUILDABLE` are **retired** *(critical)*

Three measured facts, each confirmed against shipped code:

1. **The floor was compulsory.** At `relevant == 0` the ceiling was 1, `zero_ok`
   true and `one_ok` false — so scores 1–5 were all rejected and an honest
   Synthesist could not decline it.
2. **Its trigger is the modal outcome** for an ordinary v1. `limit` is `le=5`,
   the search is stars-ranked, and five generic top-starred matches are
   correctly marked IRRELEVANT.
3. **The branch was non-monotone.** At D2 M2 C2 X2: F=1 → `REJECT` at composite
   3.7; F=0 → `NEEDS_WORK` at 3.4. *Strictly worse evidence, strictly better
   label*, because `elif feasibility == 0` sat above `elif composite < 4.0`.
   `config.py`'s claim that F=0 "caps the run at NEEDS_WORK, never REJECT" was
   false as written: it did not cap, it raised.

"No open-source prior art" is evidence about GitHub's top five by stars. It is
not evidence that two or three engineers cannot ship, and it must not reject an
idea. That state is now an honest **F=2**. `FLOOR_NOT_BUILDABLE` remains in
`FloorCode` so rows already written still parse.

**Honest limit:** the ordinary-stack idea now scores F=2, but X is still forced
low in the same state and `min(scores) >= 3` still blocks VALIDATE. This removes
a false verdict *reason* and a non-monotonicity; it does not rescue that class
of idea.

### C5 — `vendor_owned` becomes tri-state *(high)*

It was the **only** two-state flag on `Competitor` carrying a three-state
question, while `free_core_coverage`, `Repo.archived`, `Thread.points` and
`Evidence.dated_is_retrieval_time` are all tri-state. Measured: three
competitors whose ownership no source established became three `False`s,
`vendor_owned == 0`, and the ceiling was **5** — the top of the ladder, for
evidence nobody gathered.

This settles review finding F13, which was right that the flag does no work and
wrong about why: it does no reliable work at **either** end.

Two further repairs ride with it. **C=1 now means "the branch returned no
source"**, mirroring M=1 — it previously meant "named no competitor", a *false
sentence about a branch that worked* which forced a compulsory 1 on an
uncontested market, precisely the idea worth looking at. And **one definition of
vendor-owned** replaces three: the old wording split on ownership *or* bundling
and gave opposite answers for an acquired-but-standalone product (Slack under
Salesforce), leaving 0.4 of the composite to which half of a sentence a
cheap-tier model weighted. Bundling is readable off a pricing page, which is what
Firecrawl retrieves; ownership lives in footers and press releases, which it
does not.

### C6 — confidence must measure retrieval, not the answer's direction *(high)*

`sentiment_coverage` counted **problem** threads, and D=0 requires *no* problem
thread — so the term was `0.0` **by construction exactly when the demand floor
fired**. The confidence attached to "nobody wants this" was computed entirely
from the market and feasibility branches, the two with nothing to say about
demand. Measured: 3 OPINION threads and **40** OPINION threads both returned
`REJECT / FLOOR_NO_DEMAND` at confidence 0.65.

It now counts **usable** (non-`OFF_TOPIC`) threads. PRD §10.3 requires
`composite_score` and `confidence` to measure different things; this is the error
F4 removed from the tools, one layer up.

> The checker and the Synthesist prompt are bound by **exact equality**, so both
> had to change in the same commit or every synthesis would fail its guardrail.

### C7 — define the labels where they are assigned, and give the floor a margin *(high)*

`usable thread` was defined **once**, inside the *Synthesist's* prompt. The
Sentiment Analyst — the agent that actually assigns the label — had no
definition of `OPINION` versus `OFF_TOPIC` anywhere it could read, and
`agents.yaml`'s "distinguish a real problem from an adjacent topic" reads as an
instruction to reach for OPINION, the label that **arms the REJECT**.

Measured on one fixed retrieval of five threads: 3 OPINION + 2 OFF_TOPIC →
`REJECT / FLOOR_NO_DEMAND` at 0.65 non-provisional. Flip **one** label →
`NEEDS_WORK`. Same evidence, opposite verdict, one undefined label, zero margin.

Both labels are now defined in `sentiment_task`, and
`RUBRIC_FLOOR_MIN_USABLE_THREADS` moved **3 → 5**: set with margin against
`VALIDATOR_SENTIMENT_STORY_LIMIT` rather than at the ladder's own smallest count,
so the floor requires a full page of on-topic discussion with no problem in any
of it.

## Accepted with eyes open

Ratified as judgement calls. Each line names what would falsify it.

| Call | What would falsify it |
| --- | --- |
| **X=3/4/5's "most of the core job" vs "a separable part"** is a bounded judgement `rubric_support` deliberately does not enforce, now sitting beside the `free_core_coverage` field. Two sources of truth for one hinge. | A live run where the enum and the prose disagree and the prose wins. |
| **F=5's "together cover the separable parts of the scoped v1"** — inherited from the derivation, still judgement, still unenforced. | An F=5 nobody can justify from the repository list. |
| **D=2's 24-month boundary** replaces the PRD's 36 to close a dead band. | Ideas whose genuine discussion is 24–36 months old scoring as stale. |
| **D=5 requires the *market* branch to name a paying segment** — a cross-branch requirement at the top of the demand ladder. | A demonstrably strong-demand idea capped because the market branch was thin. |
| **`min(scores) >= 3` for VALIDATE** stays. | Every good idea failing on one weak dimension. |

## Deferred, deliberately

Not applied. Each is real but wants live calibration, and **a rubric edit made on
speculation is worse than a known-imperfect rubric**.

- **C8** — bind M's buyer segment to the *scoped* user, and M=3's money to that
  segment. Needs a real run to see whether the looser form actually misfires.
- **C9** — make X=2 the exact complement of X=0.
- **C10** — have every fatal floor cite the evidence it rests on.
- **Whether an uncontested market should reach C≥3** (review F8). This is the
  part that would unblock VALIDATE, and it should not be decided without
  measuring competitor recall first.

## Status of `rubric-review.md`'s findings

| Finding | Status |
| --- | --- |
| **F1** (Critical, X) | Fixed previously; **extended by C1** — its own failure shape survived one level up. |
| **F2** (Critical, D) | Fixed previously; **extended by C7** — the repair left zero margin. |
| **F4** (High) | **Fixed.** `_relevance` → `_query_term_overlap`, `_classify` → `_signal_terms_matched`; both deleted, matching word-anchored, `extra="forbid"` rejects a pasted envelope row. ⚠️ CLAUDE.md's remaining-work item 1 still claims this is open — **it is stale**. |
| **F3** | Addressed by C2. |
| **F13** | Settled by C5 — right that the flag does no work, wrong about why. |
| **F6, F8, F9** | Partly addressed (C3, C4); the recall question is deferred. |
| **F5, F7, F10–F12** | Untouched, and none blocks a scoring run. |

The review's standing verdict — *"do not spend money on a live acceptance run
against this rubric as it stands"* — is **lifted**.

## The one thing most likely to be wrong

**C7's move of `RUBRIC_FLOOR_MIN_USABLE_THREADS` from 3 to 5.** It is set at the
retrieval ceiling (`VALIDATOR_SENTIMENT_STORY_LIMIT` is also 5), so the demand
floor now fires only when *every* retrieved thread is on-topic and none shows a
problem. If HN Algolia routinely returns a mix, `FLOOR_NO_DEMAND` may have become
close to unreachable — trading a floor that over-fired for one that never fires.

**How it would show in a first live run:** a genuinely dead idea scoring
`NEEDS_WORK` at low confidence instead of `REJECT / FLOOR_NO_DEMAND`. If that
happens, 4 is the compromise: still a margin, still above the ladder's own
smallest count.
