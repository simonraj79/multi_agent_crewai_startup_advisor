from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock, patch

from brief_crew.tools.hn_sentiment import HackerNewsSentimentTool


class _Response:
    def __init__(self, status_code: int, payload: dict[str, object]) -> None:
        self.status_code = status_code
        self._payload = payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self) -> dict[str, object]:
        return self._payload


class HackerNewsSentimentToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tool = HackerNewsSentimentTool()

    @patch("brief_crew.tools.hn_sentiment.requests.get")
    def test_fetches_comment_tree_and_cites_hn_item(self, get: MagicMock) -> None:
        get.side_effect = [
            _Response(200, {"hits": [{"objectID": "123"}]}),
            _Response(
                200,
                {
                    "id": 123,
                    "text": "We <b>pay</b> $200 monthly for clinic intake software.",
                    "created_at": "2026-08-01T00:00:00Z",
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
        self.assertEqual(
            {result["classification"] for result in envelope["results"]},
            {"PAYS", "BUILT_WORKAROUND", "OPINION"},
        )
        self.assertTrue(
            all(
                result["url"] == "https://news.ycombinator.com/item?id=123"
                for result in envelope["results"]
            )
        )
        self.assertNotIn("<", envelope["results"][1]["quote"])

        search_call = get.call_args_list[0]
        self.assertEqual(search_call.args[0], "https://hn.algolia.com/api/v1/search")
        self.assertEqual(search_call.kwargs["params"]["tags"], "story")
        self.assertEqual(
            get.call_args_list[1].args[0],
            "https://hn.algolia.com/api/v1/items/123",
        )

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
        self.assertIn("partial evidence was discarded", envelope["notes"])


if __name__ == "__main__":
    unittest.main()