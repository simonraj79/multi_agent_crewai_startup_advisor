from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock, patch

import requests

from brief_crew.tools.hn_sentiment import _SIGNAL_TERMS, HackerNewsSentimentTool

_ALL_SIGNAL_TERMS = {term for terms in _SIGNAL_TERMS.values() for term in terms}


class _Response:
    def __init__(self, status_code: int, payload: dict[str, object]) -> None:
        self.status_code = status_code
        self._payload = payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self) -> dict[str, object]:
        return self._payload


ENVELOPE_KEYS = {
    "status",
    "tool",
    "query",
    "retrieved_at",
    "result_count",
    "results",
    "notes",
}


class HackerNewsSentimentToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tool = HackerNewsSentimentTool()

    @patch("brief_crew.tools.hn_sentiment.requests.get")
    def test_fetches_comment_tree_and_cites_hn_item(self, get: MagicMock) -> None:
        get.side_effect = [
            # A realistic Algolia story hit: `points` and `num_comments` are
            # already in the response this tool fetches to find the thread.
            _Response(
                200,
                {
                    "hits": [
                        {
                            "objectID": "123",
                            "title": "Clinic intake is still fax and paper",
                            "author": "someone",
                            "points": 214,
                            "num_comments": 87,
                            "created_at": "2026-08-01T00:00:00Z",
                        }
                    ]
                },
            ),
            _Response(
                200,
                {
                    "id": 123,
                    "text": "We <b>pay</b> $200 monthly for clinic intake software.",
                    "created_at": "2026-08-01T00:00:00Z",
                    "points": 214,
                    "children": [
                        {
                            "id": 124,
                            "text": "Our workaround is a <i>spreadsheet</i>.<p>It takes hours.</p>",
                            "created_at_i": 1_754_003_200,
                            "children": [
                                {
                                    "id": 125,
                                    "text": "Clinic intake automation seems useful.",
                                    "created_at": "2026-08-02T00:00:00Z",
                                    "children": [],
                                }
                            ],
                        }
                    ],
                },
            ),
        ]

        envelope = json.loads(
            self.tool._run("  clinic intake automation  ", story_limit=1, comments_per_story=5)
        )

        self.assertEqual(envelope["status"], "ok")
        self.assertEqual(envelope["tool"], "analyze_community_sentiment")
        self.assertEqual(envelope["query"], "clinic intake automation")
        self.assertEqual(envelope["result_count"], 3)
        # Matched signal WORDS, not classifications. `PAYS` is the analyst's
        # conclusion to draw; the tool only says which terms it saw.
        matched = {
            term
            for result in envelope["results"]
            for term in result["signal_terms_matched"]
        }
        self.assertTrue(matched <= _ALL_SIGNAL_TERMS, matched - _ALL_SIGNAL_TERMS)
        self.assertTrue(
            all("query_terms_present" in result for result in envelope["results"])
        )
        self.assertTrue(
            all(
                result["url"] == "https://news.ycombinator.com/item?id=123"
                for result in envelope["results"]
            )
        )
        self.assertNotIn("<", envelope["results"][1]["quote"])
        # Story-level signals, carried on every row cited to that story.
        self.assertEqual(
            [(result["points"], result["num_comments"]) for result in envelope["results"]],
            [(214, 87)] * 3,
        )
        # Every item in this fixture dates itself, one way or the other.
        self.assertEqual(
            [result["date_is_retrieval_time"] for result in envelope["results"]],
            [False, False, False],
        )

        search_call = get.call_args_list[0]
        self.assertEqual(search_call.args[0], "https://hn.algolia.com/api/v1/search")
        self.assertEqual(search_call.kwargs["params"]["tags"], "story")
        self.assertEqual(
            get.call_args_list[1].args[0],
            "https://hn.algolia.com/api/v1/items/123",
        )

    @patch("brief_crew.tools.hn_sentiment.requests.get")
    def test_an_undated_item_is_flagged_not_dated_today(self, get: MagicMock) -> None:
        """The Demand ladder scores on "dated within 24 months", and a fallback
        date is always within 24 months. The flag is what stops an item of
        unknown age carrying D's upper anchors."""
        get.side_effect = [
            _Response(200, {"hits": [{"objectID": "77", "points": 5, "num_comments": 2}]}),
            _Response(
                200,
                {
                    "id": 77,
                    "text": "We pay a contractor to do this by hand every month.",
                    "created_at": "2026-08-01T00:00:00Z",
                    "children": [
                        # No created_at and no created_at_i: Algolia dates this
                        # comment neither way.
                        {"id": 78, "text": "Our workaround is a spreadsheet.", "children": []}
                    ],
                },
            ),
        ]

        envelope = json.loads(self.tool._run("clinic intake", story_limit=1))

        self.assertEqual(envelope["status"], "ok")
        dated, undated = envelope["results"]
        self.assertIs(dated["date_is_retrieval_time"], False)
        self.assertEqual(dated["date"], "2026-08-01T00:00:00Z")
        self.assertIs(undated["date_is_retrieval_time"], True)
        self.assertEqual(undated["date"], envelope["retrieved_at"])
        self.assertIn("never dated within 24 months", envelope["notes"])

    @patch("brief_crew.tools.hn_sentiment.requests.get")
    def test_story_score_falls_back_to_the_item_root(self, get: MagicMock) -> None:
        """`/items` carries `points` even when the search hit omits it."""
        get.side_effect = [
            _Response(200, {"hits": [{"objectID": "321", "num_comments": 0}]}),
            _Response(
                200,
                {
                    "id": 321,
                    "text": "We built our own scheduler.",
                    "created_at": "2026-08-01T00:00:00Z",
                    "points": 0,
                    "children": [],
                },
            ),
        ]

        envelope = json.loads(self.tool._run("clinic scheduler", story_limit=1))

        self.assertEqual(envelope["status"], "ok")
        # A genuine zero is a zero. Only an unreported field is null.
        self.assertEqual(envelope["results"][0]["points"], 0)
        self.assertEqual(envelope["results"][0]["num_comments"], 0)
        self.assertNotIn("null rather than zero", envelope["notes"])

    @patch("brief_crew.tools.hn_sentiment.requests.get")
    def test_unreported_story_metrics_stay_null_not_zero(self, get: MagicMock) -> None:
        get.side_effect = [
            _Response(200, {"hits": [{"objectID": "999"}]}),
            _Response(
                200,
                {
                    "id": 999,
                    "text": "This problem wastes time every week.",
                    "created_at": "2026-08-01T00:00:00Z",
                    # Neither payload reports a score, and a string is not a count.
                    "num_comments": "many",
                    "children": [],
                },
            ),
        ]

        envelope = json.loads(self.tool._run("clinic intake", story_limit=1))

        self.assertEqual(envelope["status"], "ok")
        self.assertIsNone(envelope["results"][0]["points"])
        self.assertIsNone(envelope["results"][0]["num_comments"])
        self.assertIn("null rather than zero", envelope["notes"])

    @patch("brief_crew.tools.hn_sentiment.requests.get")
    def test_empty_and_failed_envelopes_invent_no_fields(self, get: MagicMock) -> None:
        get.side_effect = [
            _Response(200, {"hits": [{"objectID": "1"}]}),
            _Response(200, {"id": 1, "children": []}),
        ]
        empty = json.loads(self.tool._run("clinic intake", story_limit=1))

        self.assertEqual(empty["status"], "empty")
        self.assertEqual(empty["results"], [])
        self.assertEqual(empty["result_count"], 0)
        self.assertEqual(set(empty), ENVELOPE_KEYS)

        get.side_effect = requests.ConnectionError("no route to host")
        failed = json.loads(self.tool._run("clinic intake", story_limit=1))

        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["results"], [])
        self.assertEqual(set(failed), ENVELOPE_KEYS)
        self.assertIn("ConnectionError", failed["notes"])

    @patch("brief_crew.tools.hn_sentiment.requests.get")
    def test_comment_tree_429_discards_partial_results(self, get: MagicMock) -> None:
        get.side_effect = [
            _Response(200, {"hits": [{"objectID": "123"}, {"objectID": "456"}]}),
            _Response(
                200,
                {
                    "children": [
                        {
                            "text": "We pay for this.",
                            "created_at": "2026-08-01T00:00:00Z",
                            "children": [],
                        }
                    ]
                },
            ),
            _Response(429, {}),
        ]

        envelope = json.loads(self.tool._run("clinic intake", story_limit=2))

        self.assertEqual(envelope["status"], "rate_limited")
        self.assertEqual(envelope["results"], [])
        self.assertEqual(envelope["result_count"], 0)
        self.assertEqual(set(envelope), ENVELOPE_KEYS)
        self.assertIn("partial evidence was discarded", envelope["notes"])


if __name__ == "__main__":
    unittest.main()