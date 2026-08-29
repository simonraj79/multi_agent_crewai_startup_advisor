"""OpenRouter embeddings, called directly - deliberately NOT through CrewAI.

Why direct. ``chromadb``'s OpenAI embedding function forwards the ``dimensions``
parameter only when the model name contains the literal ``"text-embedding-3"``::

    if self.dimensions is not None and "text-embedding-3" in self.model_name:
        embedding_params["dimensions"] = self.dimensions

``google/gemini-embedding-2`` fails that substring test, so routing through
CrewAI's embedder would silently drop ``dimensions=768`` and send 3072-dim
vectors at a 768-dim index. No error - just a wall of failed upserts a long way
from the cause. See agents/00-shared-config.md §4.

This module is the ONLY place either prefix constant is applied. Indexing and
querying must use the matching pair, and if they drift nothing raises: retrieval
quality just quietly drops, which is the hardest class of bug to notice in a
system whose output is prose.
"""

from __future__ import annotations

import os

import requests

from brief_crew.config import (
    DOC_PREFIX,
    EMBED_DIMENSIONS,
    EMBED_ENDPOINT,
    EMBED_MODEL,
    QUERY_PREFIX,
)

_TIMEOUT = 60


def _embed(texts: list[str]) -> list[list[float]]:
    """One batched call. One request per chunk is pure latency and overhead."""
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError(
            "OPENROUTER_API_KEY is not set. It serves every LLM *and* all "
            "embeddings in this project - see agents/00-shared-config.md §1."
        )

    response = requests.post(
        EMBED_ENDPOINT,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": EMBED_MODEL,
            "input": texts,
            "dimensions": EMBED_DIMENSIONS,
        },
        timeout=_TIMEOUT,
    )
    response.raise_for_status()
    payload = response.json()

    # Preserve request order explicitly rather than trusting response order.
    ordered = sorted(payload["data"], key=lambda item: item["index"])
    vectors = [item["embedding"] for item in ordered]

    for vector in vectors:
        if len(vector) != EMBED_DIMENSIONS:
            raise RuntimeError(
                f"Expected {EMBED_DIMENSIONS}-dim vectors, got {len(vector)}. "
                "The `dimensions` parameter was dropped somewhere - upserting "
                "these would fail against the 768-dim index."
            )
    return vectors


def embed_documents(chunks: list[str]) -> list[list[float]]:
    """Embed text for INDEXING. Always paired with :func:`embed_query`."""
    return _embed([f"{DOC_PREFIX}{chunk}" for chunk in chunks])


def embed_query(query: str) -> list[float]:
    """Embed text for QUERYING. Always paired with :func:`embed_documents`.

    ``gemini-embedding-2`` removed the structured ``task_type`` field that
    ``gemini-embedding-001`` had; Google's guidance is to put the task
    instruction in the prompt text instead. So this asymmetry is a string
    convention, and OpenRouter gives no field that would enforce it.
    """
    return _embed([f"{QUERY_PREFIX}{query}"])[0]
