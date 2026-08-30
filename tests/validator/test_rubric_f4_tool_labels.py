"""Rubric review F4: the tools report evidence, never a schema label.

The finding, in the reviewer's words: *"three of the four floors and the entire
VALIDATE gate turn on labels the tools pre-compute by substring match, shipped in
the envelope under the same field names the schema uses - so copying them is the
cheapest valid output a cheap-tier branch agent can produce."*

Two heuristics did it. ``_relevance`` assigned ``SOLVES_ENTIRELY`` on 75% query
word overlap, so a dead student demo named after the query could fire
``FLOOR_ALREADY_FREE`` - a REJECT - and adding one word to the Scoper's query
turned the same repository into ``PARTIAL``. ``_classify`` assigned ``PAYS`` to
any comment containing the substring ``pay``, so D=4 and D=5's "someone acted on
it" clause reduced to whether ``Payload`` appeared in a sentence.

This module pins the three properties that make copying impossible rather than
merely discouraged. They are cheap to check and would each fail loudly if a
future edit reintroduced a label, which is the point: nothing else in the suite
can tell a judged label from a copied one.
"""

from __future__ import annotations

import unittest

from pydantic import ValidationError

from brief_crew.schemas import Repo, Thread
from brief_crew.tools.github_feasibility import _query_term_overlap
from brief_crew.tools.hn_sentiment import (
    _query_terms_present,
    _signal_terms_matched,
)

#: Every value the two schema fields accept. None may appear in an envelope.
RELEVANCE_LABELS = frozenset({"SOLVES_ENTIRELY", "PARTIAL", "IRRELEVANT"})
CLASSIFICATION_LABELS = frozenset(
    {"HAS_PROBLEM", "PAYS", "BUILT_WORKAROUND", "OPINION", "OFF_TOPIC"}
)

ABANDONED_DEMO = {
    "name": "clinic-scheduling",
    "full_name": "acme/clinic-scheduling",
    "description": "A demo clinic scheduling app, abandoned",
    "topics": [],
}


class ToolsDoNotEmitSchemaLabelsTests(unittest.TestCase):
    """Property 1: no envelope value is a member of either schema enum."""

    def test_repository_overlap_is_never_a_relevance_label(self) -> None:
        overlap = _query_term_overlap("clinic scheduling", ABANDONED_DEMO)
        flat = {str(v) for value in overlap.values() for v in value}
        self.assertEqual(flat & RELEVANCE_LABELS, set())

    def test_signal_terms_are_never_classification_labels(self) -> None:
        matched = _signal_terms_matched(
            "We pay for this and built my own workaround because of the problem."
        )
        self.assertEqual({m.upper() for m in matched} & CLASSIFICATION_LABELS, set())
        self.assertIn("pay", matched)

    def test_the_relevance_heuristic_is_gone_entirely(self) -> None:
        # Not merely renamed: a private helper still returning the label would
        # be one edit away from being re-exported into the envelope.
        import brief_crew.tools.github_feasibility as gh
        import brief_crew.tools.hn_sentiment as hn

        self.assertFalse(hasattr(gh, "_relevance"))
        self.assertFalse(hasattr(hn, "_classify"))


class EnvelopeRowsAreNotSchemaRowsTests(unittest.TestCase):
    """Property 2: an envelope row cannot be pasted into the schema.

    `Repo` and `Thread` both set ``extra="forbid"``, so the evidence key is
    rejected outright and the judgement key is missing. Copying does not
    validate - it raises - which is a far stronger guarantee than a prompt
    asking the analyst not to copy.
    """

    def test_a_repository_row_is_rejected_by_repo(self) -> None:
        row = {
            "name": "acme/clinic-scheduling",
            "url": "https://github.com/acme/clinic-scheduling",
            "license_permits_commercial": True,
            "months_since_push": 2,
            "archived": False,
            "query_term_overlap": _query_term_overlap("clinic scheduling", ABANDONED_DEMO),
        }
        with self.assertRaises(ValidationError) as caught:
            Repo.model_validate(row)
        message = str(caught.exception)
        self.assertIn("query_term_overlap", message)

    def test_a_thread_row_is_rejected_by_thread(self) -> None:
        row = {
            "quote": "We pay $400 a month for this.",
            "url": "https://news.ycombinator.com/item?id=1",
            "date": "2026-01-01",
            "date_is_retrieval_time": False,
            "points": 10,
            "num_comments": 2,
            "signal_terms_matched": _signal_terms_matched("We pay $400 a month for this."),
            "query_terms_present": True,
        }
        with self.assertRaises(ValidationError):
            Thread.model_validate(row)


class SubstringMatchesNoLongerDecideTests(unittest.TestCase):
    """Property 3: the reviewer's two worked examples no longer fire.

    Both are word-boundary failures rather than judgement failures, so they are
    fixed at the source: reporting the matched terms would otherwise have moved
    the substring problem into the evidence instead of removing it.
    """

    def test_payload_does_not_match_pay(self) -> None:
        # The reviewer's example. `PAYS` on a product name would have supported
        # D=4/D=5's "someone acted" clause.
        self.assertEqual(_signal_terms_matched("Payload CMS handles this already."), [])

    def test_a_real_payment_still_matches(self) -> None:
        self.assertIn("pay", _signal_terms_matched("We pay $400/mo and it is worth it."))

    def test_unpaid_does_not_match_paid(self) -> None:
        self.assertEqual(_signal_terms_matched("unpaid interns do the scheduling"), [])

    def test_multi_word_signal_terms_still_match(self) -> None:
        self.assertIn("cost us", _signal_terms_matched("it cost us a fortune"))

    def test_the_overlap_no_longer_moves_when_the_query_lengthens(self) -> None:
        # The sharpest half of F4: the same repository scored SOLVES_ENTIRELY
        # against a two-word query and PARTIAL against a three-word one, so the
        # hardest verdict the system issues moved with how many words the Scoper
        # happened to write. The evidence is now identical in both cases.
        short = _query_term_overlap("clinic scheduling", ABANDONED_DEMO)
        longer = _query_term_overlap("clinic scheduling assistant", ABANDONED_DEMO)
        self.assertEqual(short["matched"], longer["matched"])
        self.assertEqual(short["matched"], ["clinic", "scheduling"])

    def test_off_topic_is_reported_as_an_observation_not_a_label(self) -> None:
        # `OFF_TOPIC` gates the usable-thread count D=0 and D=1 rest on, so it
        # stays mechanical - but as the observation, not the conclusion.
        self.assertFalse(_query_terms_present("Payload CMS is great.", "clinic scheduling"))
        self.assertTrue(_query_terms_present("clinic staff hate this", "clinic scheduling"))



class EnvelopesCarryNoLabelTests(unittest.TestCase):
    """Property 4: the emitted ENVELOPE contains no schema label anywhere.

    The three property classes above test the helpers. Reverting the emit site
    alone - putting a hardcoded ``"relevance": "SOLVES_ENTIRELY"`` back into the
    envelope while leaving the helpers intact - slipped past all of them and was
    caught by exactly one assertion in the tool suite. That is too thin a thread
    for the finding this module exists to hold closed, so this drives the real
    tool and scans every value it emits.
    """

    def _github_envelope(self) -> dict:
        import json
        from unittest.mock import MagicMock, patch

        from brief_crew.tools.github_feasibility import GitHubFeasibilityTool

        class _Response:
            status_code = 200
            headers: dict[str, str] = {}

            def __init__(self, payload: object) -> None:
                self._payload = payload

            def json(self) -> object:
                return self._payload

            def raise_for_status(self) -> None:
                return None

        search_item = {
            "full_name": "acme/clinic-scheduling",
            "html_url": "https://github.com/acme/clinic-scheduling",
        }
        repository = {
            "name": "clinic-scheduling",
            "full_name": "acme/clinic-scheduling",
            "html_url": "https://github.com/acme/clinic-scheduling",
            "description": "A demo clinic scheduling app, abandoned",
            "topics": [],
            "license": {"spdx_id": "MIT"},
            "pushed_at": "2026-06-01T00:00:00Z",
            "archived": False,
        }
        with patch("brief_crew.tools.github_feasibility.requests.get") as get, patch.dict(
            "brief_crew.tools.github_feasibility._TOKEN_BUCKETS",
            {False: MagicMock()},
            clear=True,
        ), patch.dict("os.environ", {}, clear=True):
            get.side_effect = [_Response({"items": [search_item]}), _Response(repository)]
            return json.loads(GitHubFeasibilityTool()._run("clinic scheduling", limit=1))

    @staticmethod
    def _all_strings(value: object) -> set[str]:
        if isinstance(value, str):
            return {value}
        if isinstance(value, dict):
            return {s for v in value.values() for s in EnvelopesCarryNoLabelTests._all_strings(v)}
        if isinstance(value, list):
            return {s for v in value for s in EnvelopesCarryNoLabelTests._all_strings(v)}
        return set()

    def test_no_repository_row_carries_a_relevance_label(self) -> None:
        envelope = self._github_envelope()
        self.assertEqual(envelope["status"], "ok")
        self.assertTrue(envelope["results"])
        for row in envelope["results"]:
            with self.subTest(row=row.get("name")):
                self.assertNotIn("relevance", row)
                self.assertIn("query_term_overlap", row)
                self.assertEqual(self._all_strings(row) & RELEVANCE_LABELS, set())

if __name__ == "__main__":
    unittest.main()
