from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock, patch

from brief_crew.indexing import index_documents
from brief_crew.schemas import ScopedIdea, ValidationReport, Verdict


class IndexingBoundaryTests(unittest.TestCase):
    @patch.dict(os.environ, {"PINECONE_API_KEY": "test-key"})
    @patch("brief_crew.indexing.embed_documents", return_value=[[0.1, 0.2]])
    @patch("pinecone.Pinecone")
    def test_adds_shared_and_per_source_metadata(
        self,
        pinecone: MagicMock,
        embed_documents: MagicMock,
    ) -> None:
        written = index_documents(
            documents=[
                {
                    "text": "A directly retrieved market claim.",
                    "url": "https://example.com/source",
                    "publisher": "Example Research",
                    "published_date": "2026-08-01",
                    "metadata": {
                        "retrieved_at": "2026-08-29T00:00:00Z",
                        "source_payload": '{"claim": "retrieved"}',
                    },
                }
            ],
            topic="Clinic scheduling software",
            source_run_id="run-123",
            namespace="validator-test",
            metadata={
                "branch": "market",
                "category": "Clinic scheduling software",
                "idea_hash": "idea-456",
            },
        )

        self.assertEqual(written, 1)
        embed_documents.assert_called_once_with(
            ["A directly retrieved market claim."]
        )
        upsert = pinecone.return_value.Index.return_value.upsert
        vectors = upsert.call_args.kwargs["vectors"]
        self.assertEqual(upsert.call_args.kwargs["namespace"], "validator-test")
        self.assertEqual(vectors[0]["metadata"]["branch"], "market")
        self.assertEqual(
            vectors[0]["metadata"]["category"], "Clinic scheduling software"
        )
        self.assertEqual(vectors[0]["metadata"]["idea_hash"], "idea-456")
        self.assertEqual(vectors[0]["metadata"]["source_run_id"], "run-123")
        self.assertEqual(
            vectors[0]["metadata"]["retrieved_at"], "2026-08-29T00:00:00Z"
        )

    @patch("brief_crew.indexing.embed_documents")
    def test_rejects_generated_models_and_unsupported_objects_before_embedding(
        self,
        embed_documents: MagicMock,
    ) -> None:
        unsupported = (
            ScopedIdea.model_construct(),
            Verdict.model_construct(),
            ValidationReport.model_construct(),
            object(),
        )

        for value in unsupported:
            with self.subTest(value=type(value).__name__):
                with self.assertRaises(TypeError):
                    index_documents(  # type: ignore[arg-type]
                        value,
                        topic="test",
                        source_run_id="run",
                    )

        with self.assertRaises(TypeError):
            index_documents(  # type: ignore[list-item]
                [ScopedIdea.model_construct()],
                topic="test",
                source_run_id="run",
            )
        embed_documents.assert_not_called()


if __name__ == "__main__":
    unittest.main()