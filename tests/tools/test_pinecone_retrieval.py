from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock, patch

from brief_crew.tools.pinecone_retrieval import retrieve


class PineconeRetrievalTests(unittest.TestCase):
    @patch.dict(os.environ, {"PINECONE_API_KEY": "test-key"})
    @patch("brief_crew.tools.pinecone_retrieval._rerank")
    @patch("brief_crew.tools.pinecone_retrieval.embed_query", return_value=[0.1, 0.2])
    @patch("pinecone.Pinecone")
    def test_forwards_metadata_filter_and_namespace(
        self,
        pinecone: MagicMock,
        embed_query: MagicMock,
        rerank: MagicMock,
    ) -> None:
        index = pinecone.return_value.Index.return_value
        index.query.return_value = {
            "matches": [
                {
                    "score": 0.8,
                    "metadata": {
                        "text": "Clinic scheduling evidence",
                        "url": "https://example.com/market",
                        "branch": "market",
                        "category": "Clinic scheduling software",
                    },
                }
            ]
        }
        rerank.side_effect = lambda query, candidates, top_k: candidates
        metadata_filter = {
            "branch": {"$eq": "market"},
            "category": {"$eq": "Clinic scheduling software"},
        }

        hits = retrieve(
            "clinic scheduling market",
            metadata_filter=metadata_filter,
            namespace="validator-test",
        )

        embed_query.assert_called_once_with("clinic scheduling market")
        index.query.assert_called_once_with(
            vector=[0.1, 0.2],
            top_k=20,
            include_metadata=True,
            filter=metadata_filter,
            namespace="validator-test",
        )
        self.assertEqual(hits[0]["branch"], "market")
        self.assertEqual(hits[0]["category"], "Clinic scheduling software")

    @patch.dict(os.environ, {"PINECONE_API_KEY": "test-key"})
    @patch("brief_crew.tools.pinecone_retrieval.embed_query", return_value=[0.1])
    @patch("pinecone.Pinecone")
    def test_existing_call_remains_unfiltered(
        self,
        pinecone: MagicMock,
        embed_query: MagicMock,
    ) -> None:
        index = pinecone.return_value.Index.return_value
        index.query.return_value = {"matches": []}

        self.assertEqual(retrieve("existing caller"), [])

        embed_query.assert_called_once_with("existing caller")
        index.query.assert_called_once_with(
            vector=[0.1],
            top_k=20,
            include_metadata=True,
        )


if __name__ == "__main__":
    unittest.main()