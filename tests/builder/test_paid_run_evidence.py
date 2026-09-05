"""The two paid-run deliverables, checked mechanically rather than read.

Two defects in shipped gallery templates were found by spending money, and
neither was visible to any suite in this repository: `sequential-pipeline`
dropped its source URLs between the analyst and the writer, and
`news-to-social`'s writer leaked its own scratch-pad reasoning into the
deliverable. Both were repaired in the templates' PROMPTS
(`frontend/src/data/templates/`), and a prompt has no unit test.

**So this file is the regression guard, and it works the only way one can
here.** It reads the committed evidence of the two paid runs that verified the
repairs and re-runs the checks over their result bodies. A later prompt edit
that regresses the shape does not fail this file by itself - nothing here calls
a model. What it does is make the standard EXPLICIT and executable, so the next
paid run has a check to be measured against instead of a reading, and so a
future session that regenerates an evidence file with a worse body fails here
rather than in prose.

**No network, no model, no credential.** It reads `benchmarks/live/*.json` and
nothing else, and it is deliberately hostile to the two ways a check like this
passes for the wrong reason:

* Every set is RECOMPUTED from the utterance and the body in the file. The
  `citation_check` / `shape_check` blocks the evidence carries are checked
  against the recomputation rather than trusted, so a hand-edited summary
  cannot make a bad body look good.
* An absent or empty evidence file FAILS. It does not skip. A guard that
  vanishes with its input is the shape `gotchas` 20 is about.

The evidence for the two runs this file governs:

    benchmarks/live/2026-09-05-sequential-pipeline-prompts.json
    benchmarks/live/2026-09-05-news-to-social-prompts.json

The five OLDER `2026-09-05-*.json` files are NOT governed here and must not be:
they are the evidence of the runs that FOUND these defects, and a guard that
made them pass would be a guard that could not tell the two apart.
"""

from __future__ import annotations

import json
import pathlib
import re
import unittest

REPO = pathlib.Path(__file__).resolve().parents[2]
LIVE = REPO / "benchmarks" / "live"

SEQUENTIAL = LIVE / "2026-09-05-sequential-pipeline-prompts.json"
NEWS = LIVE / "2026-09-05-news-to-social-prompts.json"

#: Deliberately greedy about the trailing character class. A Markdown URL in
#: these bodies is either bare or inside `(...)`, and eating the closing paren
#: would make two spellings of one URL look like two URLs.
URL = re.compile(r"https?://[^\s<>\)\]\"',]+")

#: The openers a model uses when it is narrating rather than writing. Every one
#: of these was in the leaked body of run `d69c6986`, or is the same shape as
#: something that was: it opened mid-sentence with `Let's check the sentence
#: count for Long:` and `Sentence 1: ...`.
LEAK_PATTERNS = (
    r"Okay",
    r"OK",
    r"Here",
    r"I ",
    r"Let me",
    r"Let's",
    r"First,",
    r"The user",
    r"Now ",
    r"Wait",
    r"So,",
    r"Alright",
    r"Sentence \d",
    r"Check",
    r"Checking",
    r"Draft",
    r"Note:",
)
LEAK = re.compile(r"^\s*(?:" + "|".join(LEAK_PATTERNS) + r")", re.IGNORECASE)

#: `# Short` is capped at 280 characters because that is what the template's own
#: prompt asks for; the number lives in the prompt and is restated here rather
#: than imported, because there is nothing in `src/` to import it from - the
#: prompt is TypeScript in the author's document.
SHORT_MAX_CHARS = 280
MAX_HASHTAGS = 3


def _load(path: pathlib.Path) -> dict:
    if not path.exists():
        raise AssertionError(
            f"{path.name} is missing. This file is the evidence of a paid run and "
            "cannot be regenerated for free; recover it from git rather than "
            "deleting the test."
        )
    return json.loads(path.read_text(encoding="utf-8"))


def _utterance(evidence: dict, node: str) -> str:
    """What a node actually said, from its `NODE_END` frame.

    NOT from a tool frame: a tool frame carries a bounded `output_preview` -
    notes, counts, status - and never the tool's result rows, so "every URL in
    the body came from a tool result" is not answerable from the frame stream
    for any template. The researcher's own utterance is the closest ground
    truth there is, and it is what the writer was actually handed.
    """

    text = (evidence.get("utterances") or {}).get(node)
    if text:
        return str(text)
    for frame in evidence.get("frame_stream") or ():
        if frame.get("event_type") == "NODE_END" and frame.get("node_id") == node:
            return str(frame["details"]["result"])
    raise AssertionError(f"no utterance for node {node!r} in the evidence")


def _sources_section(text: str) -> str:
    """Everything after the last `## Sources` heading, or ``''``."""

    marker = "## Sources"
    return text.rsplit(marker, 1)[1] if marker in text else ""


class SequentialPipelineSourcesTests(unittest.TestCase):
    """The URLs survive `research -> analyse -> write`.

    Paid-run defect 4: they did not. The analyst rewrote every URL as
    "(Fact 1)", and the writer's sources section honestly reported
    *"the source analysis did not carry external URLs"* over a body with zero
    links after a search that fetched three threads.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.evidence = _load(SEQUENTIAL)
        cls.body = cls.evidence["result"]["markdown_body"]
        cls.research = _utterance(cls.evidence, "research")
        cls.analysis = _utterance(cls.evidence, "analyse")

    def test_the_run_this_evidence_records_completed(self) -> None:
        self.assertEqual(self.evidence["status"], "completed")
        self.assertIsNone(self.evidence["error"])
        self.assertGreater(self.evidence["usage"]["cost_usd"], 0.0)

    def test_the_researcher_returned_urls_at_all(self) -> None:
        """The control. Without it every check below passes over an empty set."""

        self.assertGreaterEqual(len(set(URL.findall(self.research))), 3)

    def test_the_analyst_carries_every_url_it_used_into_a_sources_section(self) -> None:
        section = _sources_section(self.analysis)
        self.assertTrue(section, "the analyst wrote no '## Sources' section")
        carried = set(URL.findall(section))
        research = set(URL.findall(self.research))
        self.assertTrue(carried, "the analyst's Sources section carries no URL")
        self.assertEqual(
            carried - research,
            set(),
            "the analyst invented a URL the research never returned",
        )

    def test_the_body_cites_only_urls_the_analyst_passed_on(self) -> None:
        cited = set(URL.findall(self.body))
        carried = set(URL.findall(_sources_section(self.analysis)))
        self.assertEqual(cited - carried, set(), "fabricated citations in the body")

    def test_the_body_drops_none_of_the_analyst_s_urls(self) -> None:
        cited = set(URL.findall(self.body))
        carried = set(URL.findall(_sources_section(self.analysis)))
        self.assertEqual(carried - cited, set(), "the writer dropped a source")

    def test_the_body_ends_with_a_sources_list_carrying_them_all(self) -> None:
        listed = set(URL.findall(_sources_section(self.body)))
        carried = set(URL.findall(_sources_section(self.analysis)))
        self.assertEqual(listed, carried)

    def test_the_evidence_s_own_summary_agrees_with_the_recomputation(self) -> None:
        """The summary block is checked, not trusted."""

        check = self.evidence["citation_check"]
        self.assertEqual(check["fabricated_vs_analyst"], [])
        self.assertEqual(check["dropped_vs_analyst"], [])
        self.assertEqual(
            sorted(set(URL.findall(self.body))), check["urls_in_body"]
        )
        self.assertEqual(
            sorted(set(URL.findall(_sources_section(self.analysis)))),
            check["urls_in_analyst_sources"],
        )


class NewsToSocialShapeTests(unittest.TestCase):
    """The deliverable is the two sections and nothing else.

    Paid-run evidence `d69c6986` returned 633 characters of the writer's own
    working - *"Let's check the sentence count for Long: Sentence 1: ..."* -
    as the whole `markdown_body`, on a completed run that satisfied every
    assertion `e2e/templates.spec.ts` makes.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.evidence = _load(NEWS)
        cls.body = cls.evidence["result"]["markdown_body"]
        cls.research = _utterance(cls.evidence, "research")

    def test_the_run_this_evidence_records_completed(self) -> None:
        self.assertEqual(self.evidence["status"], "completed")
        self.assertIsNone(self.evidence["error"])
        self.assertGreater(self.evidence["usage"]["cost_usd"], 0.0)

    def test_it_starts_with_the_short_heading_and_nothing_before_it(self) -> None:
        self.assertTrue(
            self.body.startswith("# Short"),
            f"body opens with {self.body[:80]!r}",
        )

    def test_there_is_exactly_one_of_each_heading(self) -> None:
        self.assertEqual(len(re.findall(r"(?m)^# Short\s*$", self.body)), 1)
        self.assertEqual(len(re.findall(r"(?m)^# Long\s*$", self.body)), 1)

    def test_the_short_section_fits_a_post(self) -> None:
        short = self.body.split("\n# Long", 1)[0][len("# Short"):].strip()
        self.assertTrue(short, "the Short section is empty")
        self.assertLessEqual(len(short), SHORT_MAX_CHARS, short)

    def test_no_line_is_the_writer_narrating_itself(self) -> None:
        leaked = [line for line in self.body.split("\n") if LEAK.match(line)]
        self.assertEqual(leaked, [], "scratch-pad reasoning in the deliverable")

    def test_at_most_three_hashtags(self) -> None:
        tags = re.findall(r"(?<!\w)#\w+", self.body)
        self.assertLessEqual(len(tags), MAX_HASHTAGS, tags)

    def test_every_url_in_the_body_is_one_the_researcher_reported(self) -> None:
        cited = set(URL.findall(self.body))
        self.assertTrue(cited, "the post cites nothing")
        self.assertEqual(cited - set(URL.findall(self.research)), set())

    def test_the_researcher_dated_every_item_it_reported(self) -> None:
        """The 7-day half of the repair, checked by its observable consequence.

        The window itself cannot be checked from here - HN Algolia's relevance
        search is not date-ranked, and what the prompt now requires is that the
        window be APPLIED and the ages be VISIBLE. So the assertion is that
        every reported item carries a date, which is what makes the writer's
        "skip any item that carries no date" rule enforceable at all.
        """

        items = len(URL.findall(self.research))
        dates = re.findall(r"\d{4}-\d{2}-\d{2}", self.research)
        self.assertGreaterEqual(items, 1)
        self.assertGreaterEqual(len(dates), items)

    def test_the_evidence_s_own_summary_agrees_with_the_recomputation(self) -> None:
        check = self.evidence["shape_check"]
        self.assertTrue(check["starts_with_short_heading"])
        self.assertEqual(check["leak_pattern_matches"], [])
        self.assertEqual(check["urls_not_in_research"], [])
        self.assertLessEqual(check["short_section_chars"], SHORT_MAX_CHARS)


class LeakPatternTests(unittest.TestCase):
    """The leak regex catches the line that actually shipped.

    Without this, `test_no_line_is_the_writer_narrating_itself` is a test that
    passes because its pattern matches nothing, which is the failure mode
    `gotchas`' "tests that pass for the wrong reason" section is about.
    """

    def test_it_matches_the_lines_from_the_leaked_run(self) -> None:
        for line in (
            "    Let's check the sentence count for Long:",
            "    Sentence 1: Developers are tackling agent fragility",
            "Here is the post:",
            "Okay, I will write the two sections.",
        ):
            with self.subTest(line=line):
                self.assertIsNotNone(LEAK.match(line))

    def test_it_leaves_the_deliverable_s_own_lines_alone(self) -> None:
        for line in (
            "# Short",
            "# Long",
            "As AI agents take over writing the code between input and output,",
            "Agent frameworks are shifting focus to solve production bottlenecks.",
        ):
            with self.subTest(line=line):
                self.assertIsNone(LEAK.match(line))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
