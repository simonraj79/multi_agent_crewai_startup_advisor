# Rubric review — `RUBRIC_ANCHORS`, independent adversarial pass

**Reviewer:** independent agent. I did not write these ladders and had no part in
the derivation or the audit that repaired them.
**Date:** 2026-08-29
**Scope:** `RUBRIC_ANCHORS` in `src/brief_crew/config.py`, the support check in
`src/brief_crew/validator_guardrails.py`, and the verdict arithmetic in
`src/brief_crew/schemas/validator.py`.
**Method:** hand-built evidence scenarios executed against the repository's own
`Verdict` model and `rubric_problems()` at head. No network, no paid calls, no
files changed except this one. Every number quoted below is output from the
shipped code, not arithmetic I did on paper.

---

## Verdict

**No. Do not spend money on a live acceptance run against this rubric as it
stands.** Three of the five ladders will produce confidently wrong verdicts on
ordinary ideas, and I can trigger each one with an evidence state the schemas
represent and the guardrails accept in silence.

That said, this is not a rubric that needs rewriting. The *machinery* around it
is unusually good — the level-1 reservation, the ceiling bounds, the anchor
separation, the recomputed counts and the ordering of the confidence override
all held under deliberate attack, and I say so with worked examples in
[What did not break](#what-did-not-break). The failures are concentrated in
**four anchors and one tool coupling**. Fix those five things and my answer
becomes yes.

The three things that most determine the answer:

1. **The headroom floor cannot see the thing it exists to catch.**
   `FLOOR_ALREADY_FREE` is counted only over GitHub repositories marked
   `SOLVES_ENTIRELY`. A free *product* — Google Calendar, Notion, a free tier —
   that already does the whole job cannot reach X=0. The ladder's own words put
   it at X=3, and X=3 clears the `min(scores) >= 3` gate. **Measured: composite
   9.4, confidence 0.90 HIGH, `VALIDATE`, zero guardrail complaints, for an idea
   where a free product already covers most of the core job.** PRD §10.2 calls
   this floor "the most valuable output this system produces."

2. **The demand floor rejects on one usable thread.** `zero_ok = usable >= 1 and
   problems == 0`. One on-topic Hacker News comment in which nobody happens to
   state a problem fires `FLOOR_NO_DEMAND`. **Measured: a final, non-provisional
   `REJECT — no demand` at confidence 0.60, built on five web pages, four repos
   and one HN opinion.** The confidence override cannot save this case, and the
   reason is structural — see F2.

3. **Three of the four floors, and the entire VALIDATE gate, turn on labels the
   tools pre-compute by substring matching.** `github_feasibility._relevance()`
   assigns `SOLVES_ENTIRELY` on ≥75% query-word overlap with a repo's
   name/description/topics; `hn_sentiment._classify()` assigns `PAYS` to any
   comment containing the substring `pay`. Both fields ship in the tool envelope
   under the *same names the schema uses*, so copying them is the cheapest valid
   output a cheap-tier branch agent can produce. Nothing measures whether the
   agents override them.

---

## Findings, by severity

| # | Sev | Dim | Defect | Evidence scenario | Wrong outcome |
|---|---|---|---|---|---|
| **F1** | **Critical** | X | `FLOOR_ALREADY_FREE` counts only repositories. A free *product* covering the whole core job maxes out at the X=3 anchor, which passes `min>=3`. | 5 market sources, 2 competitors, 1 paying segment, 5 problem threads (2 acted), 3 PARTIAL repos, and a market source naming a free product that covers most of the job. Scored D5 M5 C5 F5 **X3**. | `VALIDATE`, composite **9.4**, confidence **0.90 HIGH**, no guardrail problems. The one kill the PRD says justifies the system is unreachable for non-GitHub substitutes. |
| **F2** | **Critical** | D | `zero_ok = usable >= 1`. One usable thread with no problem thread fires the REJECT floor, and `sentiment_coverage` counts *problem* threads, so it is 0 exactly when D=0 fires — the confidence override is structurally unable to intervene. | 5 market sources, 4 PARTIAL repos, sentiment branch returns **one** `OPINION` thread. Scored D0 M5 C3 F4 X5. | `REJECT / FLOOR_NO_DEMAND`, confidence **0.60**, **`provisional=False`** — a final "nobody wants this" on one off-hand comment. No guardrail problems. |
| **F3** | **High** | M | `zero_ok = sources >= 1`. Any market branch that worked at all permits M=0, which with D≤2 is a REJECT floor. It is the only floor of the four with no mechanical guard, and `score_support_problems`' own docstring concedes this. | 5 dated market sources, 2 competitors, a named paying segment, 2 problem threads. Synthesist scores **M0**, D2. | `REJECT / FLOOR_NO_MARKET`, composite 5.4, confidence **0.69**, non-provisional, **zero guardrail problems** over five healthy sources. |
| **F4** | **High** | F, X | The two dimensions that gate VALIDATE are decided by tool-side keyword heuristics that arrive pre-filled in schema-shaped fields. | `_relevance("clinic scheduling", repo "acme/clinic-scheduling", desc "A demo clinic scheduling app, abandoned")` → **`SOLVES_ENTIRELY`**. Add one word to the query and the same repo becomes `PARTIAL`. `_classify("Payload CMS handles this already.")` → **`PAYS`**. | `FLOOR_ALREADY_FREE` (a REJECT) can fire on a dead student demo whose *name* matches the query; and D=4/D=5's "acted" clause reduces to the substring `pay`. The hardest verdict the system issues becomes sensitive to how many words the Scoper put in a query. |
| **F5** | **High** | X | **Dead band.** A named free product that covers only *part* of the core job, with PARTIAL repos present, satisfies no anchor: 0 and 2 need a repository substitute, 1 needs "no free product is named", 3 needs "covers most", 4 and 5 need "no free product". | Repos: 1 PARTIAL. Market source names a free tool covering ~40% of the job. | No anchor is true. The Synthesist must still quote one at ≥85% overlap, so it quotes a false one — most likely X=3 or X=5. Same class of defect as the PRD's original D2/D3 dead band. |
| **F6** | **Medium-High** | X | X=4 and X=5 both open "No free substitute **and no free product**", and nothing in the system ever searches for free alternatives. `ScopedIdea` carries one `market_query`, community queries and tech queries — none about free or open substitutes. "No free product named" is the default state. | 5 market sources, 4 problem threads, 2 PARTIAL repos, no free product mentioned because nobody looked. Scored X5. | `VALIDATE`, composite **8.3**, confidence 0.78 HIGH. The top of the headroom ladder is earned by the absence of a search. |
| **F7** | **Medium** | D, M | `market_paying_segments` is a list of free-text strings with no URL closure and no source binding; only its **length** is checked. Length ≥1 is the final clause of **both** D=5 and M=5 — 0.50 of the total weight. | Identical evidence, `paying_segments=[]` vs `["clinic administrators"]`. | Composite **9.0 → 10.0**. One unverifiable string is worth a full point out of ten, and it is the one place D and M genuinely double-count. |
| **F8** | **Medium** | C | A genuinely uncontested market is unrepresentable. `competitors == 0` forces the level-1 ceiling, and any dimension at 1 fails `min>=3`. There is no C anchor for "no incumbent exists". | 5 market sources, 5 problem threads, 3 PARTIAL repos, **no competitor named**. Best legal scores D5 M5 **C1** F5 X5. | `NEEDS_WORK` at composite **8.4**, confidence **0.90 HIGH**. The strongest competitive position the rubric can encounter scores lowest on the competitive dimension. |
| **F9** | **Medium** | F | F=0 is **mandatory**, not merely permitted, whenever the branch returned repos and none is relevant — which is the normal result for a v1 built from general-purpose tools. F=1 fails `SCORE_LEVEL_ONE_F`, F=2 fails `SCORE_SUPPORT_F`; 0 is the only legal score. And F≥3 requires a *reusable domain repository*, so the ladder answers "did GitHub return a domain library?" rather than its stated question "can 2-3 engineers ship a v1?". | 5 market sources, 5 problem threads, 3 repos all `IRRELEVANT`. Scored F0 (and X is then forced to 1). | `NEEDS_WORK / FLOOR_NOT_BUILDABLE` at composite 6.5, confidence **0.75 HIGH**, for an idea that is trivially buildable. An honest Synthesist has no escape from the floor. |
| **F10** | **Low-Medium** | all | Level 1 means "we did not reach the question" but scores **1 out of 5** in the weighted mean, so a missing branch is penalised twice — once in score, once in confidence. PRD §10.2 says score and confidence must measure different things. | Feasibility branch rate-limited (a live risk per R-7). F=1, X=1 contribute 0.30 of composite as if they were near-bottom findings. | Mostly caught: the override fired at confidence 0.32 in my test. But at 0.35–0.60 a *provisional* REJECT built partly on absent evidence is reachable, which is within PRD spec but worth knowing. |
| **F11** | **Low** | all | `DimensionScore.evidence_thin` is computed, surfaced in the report, and **inert in the verdict**. | All five dimensions scored 5, each citing the **same single** HN URL. | `VALIDATE`, composite **10.0**, confidence 0.90, all five dimensions flagged `evidence_thin=True`, zero guardrail problems. |
| **F12** | **Low** | X | `is_live_free_substitute` requires `license_permits_commercial` and a push within 12 months — F's questions, not X's. A user does not need a licence to use a free tool, and a finished stable tool is still a substitute. `_license_permits_commercial` also returns `False` whenever GitHub reports no licence, which is common for small repos. | A `SOLVES_ENTIRELY` repo with no detected licence. | X=0 silently under-fires; the run scores X=2 and merely blocks VALIDATE instead of rejecting. |
| **F13** | **Low** | C | `vendor_owned` does the opposite of what `config.py` claims. Because `market_task` requires *an attributed source showing* ownership, the honest default is `False`, so C=0 (which needs **every** competitor vendor-owned) is close to unreachable. The flag's only practical effect is capping C at 4. | 2 independent competitors, no beatability axis stated. | C=2 rather than C=0 — a 0.8-composite difference that the config comment describes as the flag's main job, and it almost never happens. |

---

## Per-ladder notes

Every scenario below was executed. `problems=NONE` means `rubric_problems()`
with findings attached returned an empty list — the system accepted the verdict.

### D — Demand (weight 0.30)

**The ladder itself is the best-constructed of the five.** It is a total,
disjoint partition of the evidence space, every clause is countable, and the
support ceiling reproduces the anchors exactly. The three PRD defects (D=4
unsatisfiable, D=0 on a non-existent classification, the 24/36-month dead band)
are genuinely fixed; I tried to reopen all three and could not.

| Scenario | Hand score | System | Comment |
|---|---|---|---|
| 5 problem threads within 24mo, 2 `PAYS`, market names a segment | D=5 | ceiling 5, accepted | Correct. |
| 3 problem threads, 1 recent, none acted | D=3 | ceiling 3 | Correct. |
| 5 problem threads, all `date_is_retrieval_time=true` | D=2 | ceiling **2** | Correct and good — undated evidence cannot carry recency. |
| 3 problem threads at 25 months | D=2 | ceiling 2 | Correct; at 24.6 months ceiling is 3 (the documented grace). |
| Sentiment branch failed, 0 threads | D=1 | `one_ok` true | Correct, and confidence dropped to 0.33 → `INSUFFICIENT_EVIDENCE`. |
| **1 `OPINION` thread, nothing else** | I would score **1** or refuse to score | **D=0 accepted** → non-provisional REJECT | **F2. The awkward middle that breaks it.** |
| 10 threads: 9 `OFF_TOPIC`, 1 `OPINION` | D=1 at most | D=0 accepted | Same defect, more obviously wrong. |

**On attack #4 — was dropping the PRD's "<3 usable threads" right?** The
*principle* was right: pushing thinness into the score double-counts what
confidence measures. The *application* was wrong, and F2 is the proof. The
argument assumed confidence would catch thin sentiment evidence. It cannot here:
`compute_confidence_inputs` sets `sentiment_coverage = problem_threads / 5`, and
D=0 requires `problem_threads == 0` **by definition** — so the coverage term is
always 0 exactly when this floor fires, and the remaining 0.40 market + 0.25
feasibility can still reach 0.65. The dropped clause was not redundant with
confidence for this one branch of the ladder. It was the only guard on it.

The minimal repair keeps the principle and closes the hole. It is not a
thinness test on the score; it is a **precondition on a fatal floor**:

```python
# config.py, DEMAND_ANCHORS[0]
0: (
    "At least 3 usable threads, and none is a problem thread: nobody in the "
    "evidence describes having this problem."
),
# validator_guardrails.py, rubric_support()["D"]
zero_ok = usable >= 3 and problems == 0,
```

D=1 stays exactly as written. Nothing else in the ladder counts usable threads,
so `composite` and `confidence` keep measuring different things.

**On attack #5 — did the 24-month boundary shift the ladder's meaning?** Yes,
slightly, and correctly. Three problem threads whose newest is 25–36 months old
now score 2 where the PRD's text scored nothing at all. Resolving the dead band
*downward* is the right direction, because D=3's "≥1 within 24 months" is the
clause carrying the ladder's freshness claim — widening D=3 to 36 months would
have weakened it. It also unifies the recency window at 24 months across D, M
and C, which is worth something on its own. I would make the same change.

**On the 0.30 weight.** Defensible on the ladder's own merits — D is the most
mechanised of the five and the PRD's argument for it is sound. But the weight is
applied to evidence from **one developer-centric forum**: `hn_sentiment.py` is
the sentiment branch's only tool. For any idea outside Hacker News's
demographic — the repo's own worked example, "a scheduling assistant for
clinics", is one — the branch returns nothing usable, D=1 fires, and `min>=3`
makes VALIDATE unreachable no matter how strong the market and feasibility
evidence is. The weight is not the bug; the coupling of the heaviest weight to
the narrowest evidence base is. Either accept that this product scores
developer-facing ideas only, or add a second community source.

### M — Market (weight 0.20)

Total and disjoint, and the ceiling matches the countable half of each anchor.
Judgement clauses ("names a buyer segment", "states a price or a budget") are
dropped from the bound, which is the safe direction and is fine — **except at
level 0**, which is a REJECT floor.

| Scenario | Hand score | System | Comment |
|---|---|---|---|
| 5 recent sources, segment recorded in `paying_segments` | M=5 | ceiling 5 | Correct. |
| 1 source naming hospitals, no price | M=2 | ceiling 3 | Ceiling generous by design; fine. |
| 5 sources, all `dated_is_retrieval_time` | M=3 at most | ceiling 3 | Correct — and staleness drops to 0.70. |
| Market branch 429s | M=1 | `one_ok` true, confidence collapses to ≤0.25 | Correct. Best-behaved failure in the system. |
| **5 healthy sources, Synthesist asserts M=0** | should be rejected | **accepted** → REJECT | **F3.** `zero_ok = sources >= 1` is vacuous. |
| Sources show category revenue but name no segment | M=0 (per the anchor) | accepted | See below. |

**On attack #6 — was dropping the PRD's "no money" conjunct right?** On the
wording, yes: the dimension asks "can you name whose?", and money nobody can
attribute to a buyer is not an answer to it. I could not construct a realistic
evidence state where money is demonstrated and no segment is nameable — a report
saying "$4B spent by hospitals" names hospitals. So the reading is defensible.

The problem is elsewhere and the auditor did not reach it: **M=0 is the only one
of the four floors with no mechanical guard.** D=0, F=0 and X=0 all have a
countable `zero_ok`; M=0's is "the branch returned at least one source", true of
every successful run. A Synthesist can score M=0 over any evidence and the
guardrail agrees. Proposed repair, using a counter that already exists:

```python
# validator_guardrails.py, rubric_support()["M"]
zero_ok = sources >= 3 and segments == 0,
```

This keeps M=0 a judgement about the sources' *content* while requiring the
branch to have actually looked (≥3 sources) and requiring the Market Analyst's
own structured answer to agree (no paying segment recorded). It bounds the floor
without enforcing the prose clause.

### C — Competitive room (weight 0.20)

Total and disjoint. No floor, so errors here cost at most 0.8 composite —
except through `min(scores) >= 3`, which is where F8 bites.

| Scenario | Hand score | System | Comment |
|---|---|---|---|
| 3 competitors, 2 recent sources describing the same unserved need, none vendor-owned | C=5 | ceiling 5 | Correct. |
| 2 competitors, one owned by a platform vendor, unserved need described | C=4 | ceiling 4 | Correct — the flag caps at 4. |
| 3 independent competitors, no beatability axis stated | C=2 | ceiling 3, C=2 legal | Correct. |
| 3 competitors all vendor-owned, no axis | C=0 | `zero_ok` true | Correct, but see below. |
| A source states a beatability axis against *unnamed* incumbents | C=1 | forced to 1 | Level-1 text says "evidence does not reach this question" — it did. Minor. |
| **No competitor named at all** | this is the *best* case | **C=1**, blocks VALIDATE | **F8.** |

**On attack #2 — is the `vendor_owned` definition sound and consistently
applicable?** The definition in `market_task` ("owned by, or bundled into, a
larger platform vendor rather than sold as an independent product") is clear
enough to apply — Microsoft Bookings yes, Calendly no. What it is not is
*load-bearing where the config comment claims*. The prompt requires **an
attributed source showing** the ownership, and market pages rarely state it, so
the honest default is `False`. C=0 needs **every** named competitor to be
vendor-owned, which under that default is close to unreachable. In practice the
flag does no work at the 0/2 split and all its work at the 5-cap. I would either
accept that (and correct the comment) or drop `vendor_owned` from C=0 entirely
and make C=0 "at least 1 competitor is named and no source states an axis on
which any of them is beatable" — which is the honest bottom of this ladder
anyway, and is fully mechanical against `competitors >= 1`.

Note also that `vendor_owned` is an LLM judgement made in the **market branch**,
by a cheap-tier model, feeding a *mechanical* check in the synthesis step. The
PRD's reproducibility claim — "the LLM contributes five anchored integers and
nothing else — that is what makes two runs over the same evidence agree" — is
weaker than it reads: run-to-run variance also enters through this boolean, and
through `Thread.classification` and `Repo.relevance` (F4).

### F — Feasibility (weight 0.15)

Total and disjoint. The ceiling is exact. The problem is not the ladder's
internal structure but what it measures.

| Scenario | Hand score | System | Comment |
|---|---|---|---|
| 3 MIT repos, PARTIAL, pushed this month | F=5 (if separable) / F=4 | ceiling 5 | The 4/5 hinge is judgement worth 0.3 composite. Acceptable. |
| 1 GPL-3.0 PARTIAL repo pushed 2 months ago | F=3 | ceiling 3 | Correct — GPL-3.0 is in the commercial-licence set. |
| 1 PARTIAL repo, `months_since_push=None` | F=2 | ceiling 2 | Correct: unknown activity is not recent activity. |
| GitHub rate-limited, 0 repos | F=1 | `one_ok` true | Correct. |
| **3 repos returned, all IRRELEVANT** | F is unknown, arguably 1 | **F=0 is the only legal score** → `FLOOR_NOT_BUILDABLE` | **F9.** F=1 → `SCORE_LEVEL_ONE_F`, F=2 → `SCORE_SUPPORT_F`. The floor is compulsory. |

**On attack #1 — was over-firing the right trade for F=0?** I agree with the
*reasoning* (an unreachable floor is worse than a cautious one) and disagree with
the *conclusion*, because the premise that F=0 is worth having does not survive
inspection. Note first that "over-firing" understates it: in the
repos-returned-none-relevant state, F=0 is not a choice the Synthesist makes
cautiously — it is the **only score the guardrail permits**. Now look at what
F=0 actually buys over F=1:

- Both block VALIDATE, because `min(scores) >= 3`.
- Both are non-fatal — F=0 caps at NEEDS_WORK, F=1 has no floor.
- The difference is 0.3 of composite and the `FLOOR_NOT_BUILDABLE` label.

So the entire value of F=0 is a **label** that says "two or three engineers
cannot ship this" — and it fires on ideas whose only crime is being built from
general-purpose parts. The kind of idea it wrongly kills is the ordinary one: a
scheduling assistant for clinics, a billing reconciliation tool, an internal
approvals workflow. None has a domain-specific GitHub library; all are buildable
in a fortnight. Meanwhile the ideas that score F=4 and F=5 are the ones with
*prior art*, which is not the same as buildability and is, if anything,
correlated with the X floor firing.

Given the label is the only prize and the false-positive class is that large, I
would make F=0 require the branch to have looked hard: `zero_ok = repos >= 3 and
relevant == 0`, with the anchor amended to "The feasibility branch returned at
least 3 repositories, and none of them is marked SOLVES_ENTIRELY or PARTIAL." A
one-repo miss then scores 2, not a floor. This is the same shape of fix as D=0
and M=0: keep the floor mechanical, require the branch to have actually reached
the question before it can fire.

**On attack #8 — F=5's "together cover the separable parts of the scoped v1".**
Low severity, leave it. It sits on top of a countable clause (≥3 reusable repos)
and the judgement is worth 0.3 composite. It can only flip a verdict sitting
exactly on the 7.0 boundary.

### X — Headroom over free (weight 0.15)

**This ladder is not fit for purpose in its current form.** It is the only one of
the five with a dead band (F5), its floor is blind to the most common form of the
thing it hunts (F1), its severity ordering between levels 2 and 3 is inverted
(below), and its top two levels are earned by an absence nobody searched for
(F6). It is also the dimension the PRD singles out as the system's reason to
exist.

| Scenario | Hand score | System | Comment |
|---|---|---|---|
| 1 MIT `SOLVES_ENTIRELY` repo, pushed last month, not archived | X=0 | ceiling 2 **and 2 forbidden** → only 0 is legal | **Correct and airtight.** See below. |
| 2 `SOLVES_ENTIRELY` repos, one live one dead | X=0 | only 0 legal | Correct. |
| 1 `SOLVES_ENTIRELY` repo, archived | X=2 | ceiling 2 | Correct — blocks VALIDATE at composite 8.5, confidence 0.85. |
| 1 `SOLVES_ENTIRELY` repo, no licence detected | X=2 | ceiling 2 | **F12** — should arguably be 0; `_license_permits_commercial` returns `False` on a missing licence. |
| **A free product covers most of the core job, 3 PARTIAL repos** | I would score **0 or 2** | **X=3** → VALIDATE at 9.4 | **F1.** |
| **A free product covers ~40% of the job, 1 PARTIAL repo** | no anchor is true | Synthesist must quote a false one | **F5.** |
| No free product because nobody looked, 2 PARTIAL repos | X=5 accepted | ceiling 5 | **F6.** |
| No relevant repos at all, no free product | X=1 | `one_ok` true, but **ceiling is 3** | X=3 would pass both checks with a demonstrably false anchor. Blocked here only because F=0/F=1 fires in the same state — an accident, not a guard. |

**The severity inversion, stated plainly.** Compare two runs on identical
demand/market evidence:

| Evidence | Score | Composite | Confidence | Verdict |
|---|---|---|---|---|
| An **archived**, abandoned repo that does the whole job | X=2 | 8.5 | 0.85 HIGH | `NEEDS_WORK` |
| A **live, free, named product** that covers most of the job | X=3 | 9.4 | 0.90 HIGH | **`VALIDATE`** |

The dead repository blocks the idea. The living free competitor does not. That is
backwards, and it follows directly from X=0 and X=2 being written over
repositories while X=3 is written over products.

**On attack #7 — is the `forbidden={2}` rule sound?** Yes, and it is the single
best piece of engineering in the whole rubric. With `live >= 1`: the ceiling is 2,
2 is forbidden, `one_ok` is false because `relevant >= 1`, and `zero_ok` is true —
so **0 is the only legal score**. I tried to evade it from the Synthesist's side
and could not. The residual exposure is entirely upstream: the floor rests on the
Feasibility Analyst's `relevance` label (F4), on a licence flag that answers the
wrong question (F12), and on the branch having been given a query that would
surface the substitute at all (F6).

**On attack #3 — can two analysts disagree on X=3/4/5 over the same repo set?**
Yes, and the cost is 0.6 composite (X=3 vs X=5), enough to flip a verdict sitting
near 7.0. But this is the *smallest* of X's problems, and I would not spend a
change on it while levels 0–3 are broken. The hinge only matters once the run has
honestly established "no free substitute and no free product", and F6 says that
precondition is usually unearned.

**Proposed minimal repair** (structure only — the exact wording is the owner's):

- **X=0** gains a disjunct for a free product: *"…or a market or sentiment source
  names a free product that covers the whole core job."* This makes the floor
  reachable for non-GitHub substitutes. It also makes `zero_ok` partly a
  judgement, which is the trade in decision D1 below.
- **X=2** absorbs today's X=3: *"…or a market or sentiment source names a free
  product that covers most of the core job."* A live free competitor should block
  VALIDATE, not clear it.
- **X=3** becomes the level that closes the dead band: *"No free substitute, and
  every named free product covers only a separable part of the core job."*
- **X=4 and X=5** keep their PARTIAL-repository clauses, with "no free product"
  narrowed to "no free product covering most of the core job" so they stop being
  the default.
- Add a free-alternatives query to `ScopedIdea` (a `free_alternative_query`
  alongside `market_query`) so X=4/X=5 are earned rather than assumed. This is a
  schema change and therefore a bigger decision than the others.

---

## Gaming it: the cheapest VALIDATE

Playing a Synthesist that wants a `VALIDATE`, here is the least evidence that
produces one. All numbers are measured.

**Nine documents.** Five market pages (dated, within 24 months), three Hacker
News comments (one containing the substring "pay"), one MIT-licensed GitHub repo
pushed this month and marked PARTIAL, two named competitors, and one string in
`paying_segments`.

```
D=4 M=5 C=5 F=3 X=5   composite 8.8   confidence 0.66   VALIDATE   problems: NONE
```

Two structural facts make this cheap:

1. **The support check bounds the arithmetic, not the argument.** Every
   *countable* clause is enforced; every *qualitative* clause — "names a buyer
   segment", "states a price or a budget", "states an axis of beatability",
   "describe the same unserved need", "covers most of the core job", "cover the
   separable parts" — is deliberately dropped from the ceiling. At the ceiling,
   the effective rubric is a source count. A Synthesist that asserts every
   judgement clause is satisfied scores at the ceiling on all five dimensions and
   the system agrees.

2. **Coverage saturates at five sources per branch.** `VALIDATOR_COVERAGE_TARGET_SOURCES = 5`,
   so five market pages is "fully covered" and confidence 0.66 clears the 0.60
   VALIDATE gate on nine documents total.

And the cheapest *maximal* VALIDATE: score all five dimensions 5 while citing
**the same single URL** in all five `evidence_urls` lists. Composite 10.0,
confidence 0.90, all five dimensions flagged `evidence_thin=True`, zero guardrail
problems (F11).

**The single most valuable lever is one string.** `paying_segments` is
unvalidated free text whose *length* is the last clause of both D=5 and M=5:

```
paying_segments=[]                          max scores (4,4,5,5,5)  composite  9.0
paying_segments=["clinic administrators"]   max scores (5,5,5,5,5)  composite 10.0
```

That is the D/M double-count made concrete: 0.50 of the total weight terminates
in the same unbound field. `Competitor` at least carries an optional URL and
`Evidence` requires one; `paying_segments` requires nothing. A one-line repair
would be to require each paying segment to be attributable — e.g. a
`list[Evidence]` or a parallel `paying_segment_urls` closed against the tool
results, the same treatment `source_urls` already gets.

### The hidden gate nobody has stated

Working backwards from the verdict function, `VALIDATE` is only reachable when
the **feasibility branch** returns at least one repository marked `PARTIAL` that
is commercially licensed and pushed within 12 months, **and zero** repositories
marked `SOLVES_ENTIRELY`. Everything else is necessary but this is the narrow
part. Measured, holding demand and market evidence at maximum:

| Feasibility branch returned | Best legal scores | Composite | Verdict |
|---|---|---|---|
| 1 PARTIAL, MIT, recent | D5 M5 C5 F3 X5 | 9.4 | **VALIDATE** |
| 1 SOLVES_ENTIRELY, live | D5 M5 C5 F3 **X0** | 7.9 | REJECT / FLOOR_ALREADY_FREE |
| 1 SOLVES_ENTIRELY, archived + unlicensed | D5 M5 C5 F2 X2 | 8.2 | NEEDS_WORK |
| 1 SOLVES_ENTIRELY + 3 PARTIAL | D5 M5 C5 F5 X2 | 9.1 | NEEDS_WORK |
| 3 IRRELEVANT | D5 M5 C5 **F0** X1 (F0 compulsory) | 7.3 | NEEDS_WORK / FLOOR_NOT_BUILDABLE |
| none (rate-limited) | D5 M5 C5 F1 X1 (F1 compulsory) | 7.6 | NEEDS_WORK |

A run can have perfect demand and market evidence and still be capped by one
archived repository, or by GitHub returning nothing (R-7 says the 10 req/min
per-IP limit makes this likely). Combined with F4 — that `relevance` arrives
pre-computed from query-word overlap — **the top-line verdict of this product is
largely decided by string matching against the Scoper's tech query.** The owner
should know this before the first live run, whatever else is changed.

---

## What did not break

I attacked these and they held. This is the coverage of the review.

- **Anchor separation under the 0.85 overlap threshold.** Maximum *within-ladder*
  off-diagonal token overlap: D 0.69 (2 vs 3), F 0.67, X 0.65, C 0.62, M 0.59 —
  all far below 0.85. No neighbouring level's text can be accepted for another
  level. Cross-ladder level-1 anchors reach 0.83 (M=1 vs F=1), but level 1 is
  matched **verbatim** rather than by overlap, so that is not exploitable. The
  "keep anchors short so they stay far apart" design works.
- **The level-1 reservation.** Every ladder now names its own firing condition;
  `one_ok` bounds level 1 from below mechanically; the text match is exact. I
  could not score 1 on a branch that had answered, and I could not score above 1
  on a branch that had not. This is the strongest part of the design and it fixes
  a real hole the PRD describes.
- **The D ladder's partition.** Total and disjoint over every combination of
  usable/problem/recent/acted/segment counts I could construct. No state matches
  two D anchors; no state matches none. The three PRD defects are genuinely
  closed.
- **M, C and F partitions.** Also total and disjoint. Only X has a gap (F5).
- **Ceiling correctness.** For all five ladders, `rubric_support`'s ceiling
  reproduces the countable half of each anchor. I could not find an evidence
  state where an *honest* score exceeded its ceiling — no false guardrail
  failures. Under-scoring is permitted everywhere except 0 and 1, as documented.
- **The X floor's `forbidden={2}` rule.** With a live free substitute counted, 0
  is the only legal score. Not evadable from the Synthesist's side.
- **Undated evidence.** Five problem threads all flagged `date_is_retrieval_time`
  cap D at 2. Market sources flagged `dated_is_retrieval_time` are excluded from
  every recency clause and from the median age. `months_since_push=None` is never
  "recent"; `archived=None` never kills an idea. All confirmed.
- **The recency grace band.** 24.6 calendar months still counts as within 24
  months, 25 does not — exactly as `RUBRIC_RECENCY_GRACE_MONTHS` documents, and
  in the safe direction.
- **Recomputed counts.** `evidence_counts`, the three coverage ratios,
  `branches_ok` and the median-age staleness band are all recomputed and enforced
  by equality. I could not get a fabricated count or a kinder staleness band past
  `rubric_problems()`.
- **URL closure on `evidence_urls`.** Fabricated URLs are caught. (URLs are
  closed against the union of all three branches rather than the scoring
  dimension's own branch, so D can cite a GitHub URL — cosmetic, not a defect.)
- **Ordering of the confidence override.** It runs ahead of every floor, as the
  PRD requires. A dead market branch always lands below 0.35 (measured 0.25 and
  0.32 in two constructions) and produces `NEEDS_WORK / INSUFFICIENT_EVIDENCE`
  rather than a REJECT. The one gap is F2, where the override is structurally
  unable to help because the coverage numerator is zero by construction.
- **Under-scoring cannot manufacture a bad verdict.** A Synthesist that scores 3
  everywhere on evidence supporting 5 gets `NEEDS_WORK` at composite 6.0 with no
  guardrail objection. Deliberate, and harmless.

---

## Decisions only a human can make

Four. I have laid out the trade-off on each; I should not pick.

**D1 — Should the X floor cover free products, at the cost of ceasing to be
mechanical?** Today `FLOOR_ALREADY_FREE` is fully determined by counters, which
is why it is trustworthy. Extending it to "a source names a free product that
covers the whole core job" makes the system's most valuable kill *reachable*
(F1) but puts a REJECT floor behind a prose judgement — the same weakness F3
identifies in M=0. The alternatives are: extend the floor and accept the
judgement; or keep the floor mechanical and settle for capping X at 2 when a free
product is named, which blocks VALIDATE without ever rejecting. **My view, for
what it is worth: the second option gets most of the value at none of the cost,
but it means this system will never REJECT "Notion already does this", and the
PRD says that kill is the point.** That tension is yours to resolve.

**D2 — Is "no competitor found" evidence of a clear field, or evidence of a bad
search?** F8 forces C=1, which blocks VALIDATE for the best possible competitive
position. Adding a C anchor for "no incumbent exists" would fix it, but it would
also reward a Firecrawl run that simply missed the incumbents — and competitor
recall is the branch you have least reason to trust. This turns on how much you
trust `research_market_landscape`, which nobody has measured yet.

**D3 — Should `FLOOR_NOT_BUILDABLE` exist at all?** F9 shows F=0 fires on
ordinary ideas, and the analysis shows its only benefit over F=1 is the label,
since both block VALIDATE. Three options: tighten `zero_ok` to `repos >= 3 and
relevant == 0` (my suggestion, keeps the label, narrows the false positives);
retire F=0 and the floor entirely and let F=1/F=2 do the work; or keep it as-is
and accept a stream of "not buildable" verdicts on buildable ideas. This is a
product-voice decision as much as a scoring one.

**D4 — Does 0.30 on Demand survive the sentiment branch being Hacker News
only?** The weight is justified by the PRD's argument and by D being the
best-built ladder. But paired with a single developer forum and the `min>=3`
gate, it means non-developer verticals cannot VALIDATE. Reweight, add a second
community source, or scope the product to ideas HN discusses — all three are
defensible and only you can say which product you are building.

---

## Recommended order of work

Ordered by how much wrong verdict each removes per line changed. Items 1–3 are
small, mechanical, and in my view must land before any paid run.

1. **F2 — D=0 precondition.** Two edits: `DEMAND_ANCHORS[0]` gains "At least 3
   usable threads", `rubric_support`'s `zero_ok` becomes `usable >= 3 and
   problems == 0`. Removes the silent non-provisional false REJECT. Also update
   the D=0 line in `tasks.yaml`, which quotes the anchor verbatim.
2. **F4 — rename the tool label fields.** `github_feasibility` emits `relevance`
   and `hn_sentiment` emits `classification` under the exact schema field names.
   Rename them in the envelopes (`query_term_overlap`, `signal_terms_matched`) so
   copying is no longer a valid schema value, and note in each branch prompt that
   the tool's hint is a keyword match, not a judgement. Three of four floors stop
   being decidable by substring.
3. **F3 — M=0 precondition.** One line: `zero_ok = sources >= 3 and segments == 0`.
4. **F1 + F5 + F6 — the X ladder.** The largest change and the one most worth
   doing carefully, after decision D1. Renumber levels 0–3 as sketched above,
   close the dead band, and narrow the "no free product" precondition on 4 and 5.
5. **F7 — bind `paying_segments` to a source.** One unverified string should not
   be worth a full composite point across two dimensions.
6. **F9 — F=0 precondition**, after decision D3.
7. **F8, F11, F12, F13** — lower value; take them with whichever of the above
   touches the same file.

Whatever is changed, re-run `tests/validator/` — `test_crews.py` and
`test_guardrails.py` assert anchor text, anchor separation and support bounds
directly, so an anchor edit will surface there rather than silently.

---

## Method and limits of this review

- Every scenario was constructed as real `MarketFindings` / `SentimentFindings` /
  `FeasibilityFindings` / `Verdict` objects and run through the shipped
  `rubric_problems(verdict, findings=…)` — the same guardrail
  `make_rubric_guardrail` attaches to `synthesis_task` in
  `crews/validator_crew/validator_crew.py:317`. Scenarios the schemas cannot
  represent were discarded rather than reported.
- Composite, confidence, band, floors, verdict and provisional status all come
  from `Verdict.compute_mechanical_result`, not from my arithmetic.
- Tool behaviour (F4) was demonstrated by calling `_relevance` and `_classify`
  directly with literal payloads. No network calls were made.
- **What this review does not cover:** whether the *branch agents* in practice
  produce honest labels (only a live run with traces can answer that, and F4 is
  the reason to look); whether Firecrawl's competitor and pricing recall is good
  enough for the C and M ladders; and the qualitative quality of the anchor prose
  as an instruction to a language model, as opposed to its logical structure,
  which is what I tested.
