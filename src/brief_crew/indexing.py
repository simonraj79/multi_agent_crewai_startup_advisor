"""Chunk, embed and upsert scraped material - the write-back half of the cache.

This is plumbing, not a tool, and deliberately so. There is no decision content
in "chunk this page and write it to the index", so exposing it as a tool would
only create something the agent can forget to call, mis-call, or skip. It runs
as a Flow step (`@listen(scrape_web)`), always, with no model in the loop.

Two rules from agents/06-retrieval-layer.md that are easy to get wrong:

  * **Index what was scraped, not what was used.** Write-back must not be
    conditional on the brief being good, or the cache only ever accumulates
    material that already worked - which biases what future runs can find.
  * **`published_date` and `indexed_at` are not optional.** Without them the
    staleness gate cannot work, and the cache silently turns month-old facts into
    "current" ones. That is the worst failure this architecture can produce,
    because the brief looks perfectly well-sourced while being wrong.

`source_run_id` is on every upsert so a bad run is revocable: deleting everything
one run wrote is then a single filtered delete. Without it, it is irrevocable.
"""

from __future__ import annotations

import hashlib
import os
import re
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any, Iterable

from pydantic import BaseModel

from brief_crew.config import (
    CHUNK_MAX_TOKENS,
    CHUNK_MIN_TOKENS,
    CHUNK_OVERLAP_TOKENS,
    PINECONE_INDEX_NAME,
)
from brief_crew.embeddings import embed_documents

# Rough token estimate. Chunking targets retrieval precision (200-800 tokens),
# not the 8,192-token embedding ceiling, so approximate sizing is sufficient -
# the limit is nowhere near binding.
_CHARS_PER_TOKEN = 4
_MIN_CHARS = CHUNK_MIN_TOKENS * _CHARS_PER_TOKEN
_MAX_CHARS = CHUNK_MAX_TOKENS * _CHARS_PER_TOKEN
_OVERLAP_CHARS = CHUNK_OVERLAP_TOKENS * _CHARS_PER_TOKEN


def chunk_markdown(text: str) -> list[str]:
    """Split on structural boundaries, not a fixed character count.

    Embedding a whole page as one vector produces a single blurry centroid that
    matches everything weakly and nothing strongly. Splitting on headings and
    paragraphs keeps each chunk about one thing; the overlap keeps a fact that
    straddles a boundary from being lost.
    """
    if not text or not text.strip():
        return []

    # Prefer markdown headings as boundaries, then blank lines.
    blocks = [b.strip() for b in re.split(r"\n(?=#{1,6}\s)|\n\s*\n", text) if b.strip()]

    chunks: list[str] = []
    current = ""
    for block in blocks:
        candidate = f"{current}\n\n{block}".strip() if current else block
        if len(candidate) <= _MAX_CHARS:
            current = candidate
            continue
        if current:
            chunks.append(current)
            # Carry a tail of the previous chunk forward as overlap.
            current = f"{current[-_OVERLAP_CHARS:]}\n\n{block}".strip()
        else:
            current = block
        # A single oversized block still has to be cut somewhere.
        while len(current) > _MAX_CHARS:
            chunks.append(current[:_MAX_CHARS])
            current = current[_MAX_CHARS - _OVERLAP_CHARS :]

    if current:
        chunks.append(current)

    # Fold a runt tail into its predecessor rather than indexing a fragment.
    if len(chunks) > 1 and len(chunks[-1]) < _MIN_CHARS:
        chunks[-2] = f"{chunks[-2]}\n\n{chunks[-1]}"
        chunks.pop()
    return chunks


def _vector_id(url: str, chunk: str, metadata: Mapping[str, Any]) -> str:
    discriminator = "\n".join(
        str(metadata.get(key, "")) for key in ("branch", "category")
    )
    digest = hashlib.sha256(
        f"{url}\n{chunk}\n{discriminator}".encode()
    ).hexdigest()[:32]
    return f"{digest}"


def _metadata_dict(value: Any, label: str) -> dict[str, str | int | float | bool]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise TypeError(f"{label} must be a mapping of Pinecone metadata values")

    normalized: dict[str, str | int | float | bool] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not key:
            raise TypeError(f"{label} keys must be non-empty strings")
        if not isinstance(item, (str, int, float, bool)):
            raise TypeError(
                f"{label}[{key!r}] has unsupported type {type(item).__name__}"
            )
        normalized[key] = item
    return normalized


def _validated_documents(documents: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    from brief_crew.schemas import ScopedIdea, ValidationReport, Verdict

    forbidden = (ScopedIdea, Verdict, ValidationReport)
    if isinstance(documents, forbidden):
        raise TypeError(
            f"{type(documents).__name__} is generated validator output, not source evidence"
        )
    if isinstance(documents, (str, bytes, Mapping, BaseModel)):
        raise TypeError("documents must be an iterable of source-evidence mappings")

    validated: list[dict[str, Any]] = []
    for position, document in enumerate(documents):
        if isinstance(document, forbidden):
            raise TypeError(
                f"documents[{position}] is {type(document).__name__}, not source evidence"
            )
        if isinstance(document, BaseModel) or not isinstance(document, Mapping):
            raise TypeError(
                f"documents[{position}] has unsupported type {type(document).__name__}; "
                "expected a source-evidence mapping"
            )
        normalized = dict(document)
        for field in ("text", "url", "publisher", "published_date"):
            value = normalized.get(field, "")
            if not isinstance(value, str):
                raise TypeError(f"documents[{position}].{field} must be a string")
        normalized["metadata"] = _metadata_dict(
            normalized.get("metadata"), f"documents[{position}].metadata"
        )
        validated.append(normalized)
    return validated


def index_documents(
    documents: Iterable[dict[str, Any]],
    topic: str,
    source_run_id: str,
    namespace: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> int:
    """Chunk, embed and upsert. Returns the number of vectors written.

    Each document is ``{"text": ..., "url": ..., "publisher": ..., "published_date": ...}``.
    ``namespace`` is worth setting per group in a classroom: it costs nothing and
    removes the blast radius of one group poisoning another's retrieval entirely.
    """
    validated_documents = _validated_documents(documents)
    shared_metadata = _metadata_dict(metadata, "metadata")
    indexed_at = datetime.now(timezone.utc).isoformat()

    chunks: list[str] = []
    metadatas: list[dict[str, Any]] = []
    for doc in validated_documents:
        url = doc.get("url") or ""
        for chunk in chunk_markdown(doc.get("text") or ""):
            chunks.append(chunk)
            metadatas.append(
                {
                    **shared_metadata,
                    **doc["metadata"],
                    "text": chunk,
                    "url": url,
                    "publisher": doc.get("publisher") or "",
                    "published_date": doc.get("published_date") or "",
                    "indexed_at": indexed_at,
                    "topic": topic,
                    "source_run_id": source_run_id,
                }
            )

    if not chunks:
        return 0

    vectors_raw = embed_documents(chunks)
    payload = [
        {
            "id": _vector_id(md["url"], chunk, md),
            "values": vec,
            "metadata": md,
        }
        for chunk, vec, md in zip(chunks, vectors_raw, metadatas)
    ]

    from pinecone import Pinecone

    pc = Pinecone(api_key=os.environ["PINECONE_API_KEY"])
    index = pc.Index(PINECONE_INDEX_NAME)
    for start in range(0, len(payload), 100):
        index.upsert(vectors=payload[start : start + 100], namespace=namespace)

    return len(payload)
