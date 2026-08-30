# Licensing — a decision that has not been made

**There is no `LICENSE` file in this repository, and `pyproject.toml` has no
`license` field.**

That is not a neutral state. Under the Berne Convention, copyright attaches
automatically to everything here the moment it is written. No licence means **all
rights reserved**: a reader may look at the code, and legally may not copy it,
modify it, redistribute it, or use it in their own project. Forking on GitHub is
permitted by the GitHub Terms of Service — nothing beyond that is.

For a teaching or portfolio project this is almost always the opposite of what
the author intends. Publishing it says *"look at this and learn from it"*;
publishing it without a licence says *"look, but you may not use it."* GitHub's
own guidance is blunt about this, and so is
[choosealicense.com/no-permission](https://choosealicense.com/no-permission/).

Nobody but the copyright holder can make this call, so this file prepares it
rather than settling it.

---

## What you already inherit

Before choosing, check what the repository is obliged to be compatible with.

| Vendored material | Where | Licence | Constrains your choice? |
|---|---|---|---|
| CrewAI agent skills (4) | `.agents/skills/`, `.claude/skills/` | **MIT** — from [`crewAIInc/skills`](https://github.com/crewAIInc/skills) | **No.** MIT is permissive and compatible with every option below, including GPL. |
| CrewAI itself | dependency, not vendored | MIT | No — a dependency, not distributed here. |

**Result: nothing constrains the choice.** MIT-licensed vendored files impose one
obligation only — the copyright notice and permission text must travel with them.
See *Attribution* at the end.

Everything else in `src/`, `tests/`, `frontend/src/` and `agents/` is original
work, with one exception noted under *Open questions*.

---

## The realistic options

### MIT — recommended

The default for a teaching project, and the recommendation here.

- **Permits:** use, copy, modify, merge, publish, distribute, sublicense, sell.
- **Requires:** the copyright notice and licence text travel with the code.
- **Provides:** an explicit "as is" warranty disclaimer.

**Why it fits this repository specifically.** The project's value to a reader is
the *approach* — a rubric bound to counted evidence, a router that decides
without a model, gates that survive a restart. You want those ideas lifted into
other people's code; that is the whole point of publishing. MIT removes every
obstacle to that, is four paragraphs long, and is the licence a reader already
understands without reading it. It also matches the CrewAI ecosystem this sits
in, so nobody has to think about compatibility.

**The trade you are making:** someone can take this, improve it, and never share
the improvement back. If that outcome would genuinely bother you, MIT is the
wrong choice and you want the third option.

### Apache-2.0

MIT's permissions, plus two things MIT lacks.

- An **express patent grant** from contributors, and automatic termination of
  that grant for anyone who sues over patents.
- A requirement to **state what you changed** in modified files.

**Choose this instead if** you expect corporate users (some companies' legal
review prefers or requires it), or you want patent protection made explicit
rather than implied. The cost is length: ~200 lines against MIT's ~20, plus a
`NOTICE` file convention.

For a project of this kind the patent grant is close to theoretical. Reasonable
choice, slightly heavier than the situation needs.

### GPL-3.0 / AGPL-3.0

Copyleft: derivative works must also be released under the same licence. AGPL
extends this to **network use** — anyone running a modified version as a hosted
service must publish their source.

**Choose this only if** the reciprocity is the point — if you would rather the
code not be used at all than be used in a closed product. Given this repository
ships a deployable web service, AGPL is the version that would actually bite.

**The cost is real.** Copyleft materially reduces the audience: many companies
prohibit GPL dependencies outright, and a student or hobbyist wanting to borrow
one guardrail now has a licensing question. For a project whose stated purpose is
to be read and learned from, this works against you.

### CC BY 4.0 for the prose, separately

A genuine option worth considering, because this repository is unusually
documentation-heavy: `agents/`, `PRD.md` and `AGENTS.md` together substantially
outweigh the code, and they are prose, not software. Creative Commons licences
are designed for prose; software licences are not.

**A dual arrangement** — code under MIT, documentation under CC BY 4.0 — is
common and defensible. It is also more explaining than most readers want. If you
would rather keep it simple, MIT over the whole repository is perfectly ordinary
and nobody will be confused by it.

---

## Recommendation

**MIT over the whole repository**, unless one of these is true:

- You expect corporate adoption and want an explicit patent grant → **Apache-2.0**.
- You would rather the code go unused than be used in a closed product → **AGPL-3.0**.
- You care enough about the prose being treated as prose to explain a dual
  licence → **MIT + CC BY 4.0 for `agents/`, `PRD.md`, `AGENTS.md`**.

---

## How to apply it, once decided

Three steps.

**1. Add the `LICENSE` file.** Easiest path, and it avoids transcription errors:
on GitHub, **Add file → Create new file**, type `LICENSE` as the filename, and a
**"Choose a license template"** button appears. Pick one and it inserts the exact
text with your name and the year filled in. Or copy it from
[choosealicense.com](https://choosealicense.com/).

**2. Declare it in `pyproject.toml`.** There is a placeholder comment in the
`[project]` table marking where it goes. Modern PEP 639 syntax:

```toml
license = "MIT"
license-files = ["LICENSE"]
```

Some older tooling still expects `license = { file = "LICENSE" }`. Either works
with the hatchling backend this project uses; the string form is current.

**3. Mention it in the README.** The *Licence* section currently says "None yet"
and points here. Replace it with one line naming the licence.

---

## Open questions the licence choice does not resolve

Two things need a decision that no `LICENSE` file settles, because they concern
material that may not be yours to license.

**The lecture deck.** `agents/README.md` and `agents/workflow.md` both name their
source as a specific person's slide deck, and `agents/workflow.md` §3–§4 and
`agents/patterns.md` §12 reproduce that deck's taxonomy, tables and quoted lines
at length. Applying a licence to this repository does not grant rights over
someone else's material, and a permissive licence would be *asserting* rights you
may not hold. Worth resolving — by permission, by attribution, or by reducing the
reproduction to citation — before publishing, independently of the licence.

**`PRD.md` §8.** That section reverse-engineers a third-party frontend with
file-and-line citations and a component-by-component *Lift / Adapt / Drop* plan.
Whether any of that may be lifted depends entirely on that project's own licence,
which is not recorded anywhere here. Check it before acting on the plan, and
before publishing a document that describes acting on it.

Neither is a reason to delay choosing a licence for your own code. Both are
reasons not to let a licence imply coverage it does not have.

---

## Attribution for the vendored MIT skills

Whatever you choose, `.agents/skills/` and `.claude/skills/` remain MIT and carry
CrewAI's copyright, not yours. MIT requires the notice to travel with the files.

They currently ship with no `LICENSE` file of their own. The tidy fix is a short
`.agents/skills/LICENSE` (and the same in `.claude/skills/`) containing upstream's
MIT text and copyright line, or a `NOTICE` at the repo root recording their
origin and licence. `skills-lock.json` already records the source repository and
a content hash, which is good provenance but is not the notice MIT asks for.

If you re-run `npx skills add crewaiinc/skills`, check whether upstream has since
added a `LICENSE` and let it come along.
