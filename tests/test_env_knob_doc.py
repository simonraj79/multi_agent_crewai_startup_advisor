"""`docs/tech-stack.md` §6 must agree with the scan that generates it - D-01-9.

Plan 01's criterion 12 says "§6's scan reports the new knob
(`CREDENTIALS_MASTER_KEY`) and the count in that file is regenerated, not
edited", and until 2026-09-04 nothing checked it: `grep -rln "tech-stack"
tests/` answered nothing. Criterion 13 labels itself a review checklist item;
criterion 12 made an equally manual claim without the label, so it read as
verified. The project already owned the technique - criterion 6's pin opens the
plan file, regex-extracts the criterion and asserts a note is present - and this
is that technique applied to the claim beside it.

**It is also the check `docs/tech-stack.md` asks for by name.** Its own box
says: "The fix is a check that runs: the scan wired into CI against a committed
expected list, so a knob added without a doc edit fails a job instead of aging
quietly into the next audit. It does not exist." The count in that section has
been published wrong six times, never twice for the same reason, and every one
of them was a knob landing in a commit that did not touch the docs. This is the
job that fails.

**So this test WILL go red when somebody adds a knob**, and that is the entire
point. The failure names the knob, names the file, and names the command to
re-run; it is a two-minute fix and it is the only thing standing between a
seventh wrong figure and the next audit.

The scan is the canonical one from §1 - `re.S` multiline, over `config.py` and
`service/app.py`. Never line-anchored: a wrapped `os.getenv(` call hid four
knobs once and that is [gotchas](../docs/gotchas-and-insights.md) 6. §9 records
separately that five knobs are read outside those two files and are therefore
outside this scan's definition; widening it is a decision for whoever closes
that item, and this test deliberately checks the scan the document declares
rather than a better one it does not.
"""

from __future__ import annotations

import pathlib
import re
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
TECH_STACK = REPO_ROOT / "docs" / "tech-stack.md"
PLAN_01 = REPO_ROOT / ".agent" / "plans" / "01-auth-and-workspaces.md"

#: **Both files are local-only from 2026-09-05.** Every `*.md` in this
#: repository except `README.md` and `data/skills/**/SKILL.md` is gitignored and
#: untracked, because the repository is public and these documents are not. So a
#: clean checkout - CI's, and a contributor's first clone - has neither file, and
#: a test that reads one would fail there for a reason that is not a defect.
#:
#: The guard is `skipUnless`, never a silent pass: on THIS machine, where the
#: documents exist, the check still runs and still goes red when a knob is added
#: without a doc edit, which is the entire reason the module exists. A skip that
#: says why is the honest answer to "the evidence is not on this machine"; a
#: green assertion over a missing file is the failure mode
#: [gotchas](../docs/gotchas-and-insights.md) 20 is about.
DOCS_ARE_LOCAL = (
    "docs are local-only (every *.md but README.md is gitignored since "
    "2026-09-05); {} is absent, so there is nothing to check against"
)

#: The canonical scan, verbatim from `docs/tech-stack.md` §1. Restated here as
#: source rather than imported, because the document is what it has to agree
#: with and a shared helper would let both sides move together.
SCAN = re.compile(
    r'(?:os\.getenv|os\.environ\.get|_env_[a-z_]+)\(\s*"([A-Z_][A-Z0-9_]*)"',
    re.S,
)
SCANNED_FILES = (
    "src/brief_crew/config.py",
    "src/brief_crew/service/app.py",
)

REGENERATE = (
    "regenerate docs/tech-stack.md section 6 with the multiline scan in its "
    "section 1 and paste the output; never edit the list or the count by hand"
)

_UNITS = (
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight",
    "nine", "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen",
    "sixteen", "seventeen", "eighteen", "nineteen",
)
_TENS = (
    "", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy",
    "eighty", "ninety",
)


def spell(number: int) -> str:
    """`49` -> `forty-nine`. The heading is prose, so the count is a word."""

    if number < 20:
        return _UNITS[number]
    tens, unit = divmod(number, 10)
    return _TENS[tens] if unit == 0 else f"{_TENS[tens]}-{_UNITS[unit]}"


def scanned_knobs() -> set[str]:
    found: set[str] = set()
    for name in SCANNED_FILES:
        found |= set(SCAN.findall((REPO_ROOT / name).read_text(encoding="utf-8")))
    return found


def documented_knobs() -> set[str]:
    """The names in §6's pasted scan-output block.

    Located by the sentence that introduces it - "The block below is pasted
    scan output" - rather than by counting fences, so an added paragraph does
    not silently point this at a different block.
    """

    text = TECH_STACK.read_text(encoding="utf-8")
    marker = "The block below is pasted scan output"
    if marker not in text:
        raise AssertionError(
            f"{TECH_STACK.name} no longer carries {marker!r}; this test finds "
            "the knob block by that sentence"
        )
    block = text.split(marker, 1)[1].split("```text", 1)[1].split("```", 1)[0]
    return set(re.findall(r"[A-Z][A-Z0-9_]{2,}", block))


@unittest.skipUnless(TECH_STACK.is_file(), DOCS_ARE_LOCAL.format("docs/tech-stack.md"))
class ScanAgreesWithTheDocument(unittest.TestCase):
    def test_every_knob_the_scan_finds_is_documented(self) -> None:
        undocumented = sorted(scanned_knobs() - documented_knobs())
        self.assertEqual(
            [],
            undocumented,
            f"these environment knobs are read in {' and '.join(SCANNED_FILES)} "
            f"and are missing from docs/tech-stack.md section 6: {undocumented}. "
            f"{REGENERATE}",
        )

    def test_the_document_lists_no_knob_the_scan_cannot_find(self) -> None:
        """A stale entry is the same defect from the other side.

        A knob removed from the code and left in the list makes the count wrong
        in the direction nobody checks, because the list still looks longer
        than the code.
        """

        stale = sorted(documented_knobs() - scanned_knobs())
        self.assertEqual(
            [],
            stale,
            f"docs/tech-stack.md section 6 lists knobs the scan does not find: "
            f"{stale}. {REGENERATE}",
        )

    def test_the_heading_count_is_the_scan_count(self) -> None:
        """The figure that has been published wrong six times."""

        heading = re.search(
            r"^## 6\. Environment knobs — there are ([a-z-]+)\s*$",
            TECH_STACK.read_text(encoding="utf-8"),
            re.M,
        )
        self.assertIsNotNone(
            heading,
            "docs/tech-stack.md section 6's heading no longer spells its count; "
            "this test reads the figure from that line",
        )
        assert heading is not None  # for the type checker
        expected = len(scanned_knobs())
        self.assertEqual(
            spell(expected),
            heading.group(1),
            f"the scan finds {expected} knobs and the heading says "
            f"{heading.group(1)!r}. {REGENERATE}",
        )


@unittest.skipUnless(
    TECH_STACK.is_file() and PLAN_01.is_file(),
    DOCS_ARE_LOCAL.format("docs/tech-stack.md or .agent/plans/01-auth-and-workspaces.md"),
)
class Criterion12(unittest.TestCase):
    """Plan 01's criterion 12, and the note that says a test now checks it."""

    def setUp(self) -> None:
        self.plan = PLAN_01.read_text(encoding="utf-8")

    def test_the_vault_key_is_in_the_scan_and_in_the_document(self) -> None:
        """The criterion's own literal claim, checked rather than asserted."""

        self.assertIn("CREDENTIALS_MASTER_KEY", scanned_knobs())
        self.assertIn("CREDENTIALS_MASTER_KEY", documented_knobs())

    def test_the_plan_records_that_this_test_verifies_it(self) -> None:
        """Criterion 6's technique, applied to the criterion beside it.

        The row's complaint was that criterion 12 reads as verified while
        nothing verified it. A criterion whose verifier exists should say
        which one, in the plan, where the tick is.
        """

        criterion = re.search(
            r"^12\. (.+?)(?=^13\. )", self.plan, re.M | re.S
        )
        self.assertIsNotNone(criterion, "plan 01 no longer has a criterion 12")
        assert criterion is not None
        text = criterion.group(1)
        self.assertIn("tests/test_env_knob_doc.py", text)
        self.assertIn("2026-09-04", text)

    def test_criterion_13_still_says_it_is_a_review_item(self) -> None:
        """The distinction the row is about: a manual claim must say so.

        Criterion 13 labels itself. Criterion 12 did not, and now does not need
        to, because it is checked. If 13 ever gains a verifier this assertion
        is the reminder to relabel it.
        """

        criterion = re.search(r"^13\. (.+?)(?=^\s*$|\n## )", self.plan, re.M | re.S)
        self.assertIsNotNone(criterion, "plan 01 no longer has a criterion 13")
        assert criterion is not None
        self.assertIn("not a test", criterion.group(1))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
