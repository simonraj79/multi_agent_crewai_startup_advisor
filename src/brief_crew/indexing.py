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


# Where a page divides into blocks: before a markdown heading, or at a blank
# line.
_BLOCK_SPLIT_RE = re.compile(r"\n(?=#{1,6}\s)|\n\s*\n")
_HEADING_RE = re.compile(r"^#{1,6}\s")
# Boundaries a chunk may start or end on, best first: a paragraph break, the
# end of a sentence, a word break. Anywhere a passage can begin without
# beginning mid-word.
_BOUNDARY_RES = (
    re.compile(r"\n\s*\n"),
    re.compile(r"(?<=[.!?])\s+"),
    re.compile(r"\s+"),
)


def _structural_blocks(text: str) -> list[str]:
    """Structural blocks, with every heading glued to the text it introduces.

    Splitting leaves a heading as a block of its own whenever a blank line
    follows it - which is how markdown is normally written. Left that way the
    greedy packing below can close a chunk on the heading and open the next one
    on its body, so a retrieved passage arrives with its title in a different
    vector and the title matches a query the passage cannot answer. Folding
    right makes the pair atomic, so no packing decision can separate them.
    """
    raw = [block.strip() for block in _BLOCK_SPLIT_RE.split(text) if block.strip()]
    folded: list[str] = []
    for block in reversed(raw):
        # A bare heading is a single line: `## Findings`, not `## Findings`
        # plus the lines under it, which the split already keeps together.
        if folded and "\n" not in block and _HEADING_RE.match(block):
            folded[0] = f"{block}\n\n{folded[0]}"
        else:
            folded.insert(0, block)
    return folded


def _cut_point(text: str) -> int:
    """Where to cut a single block that is longer than a whole chunk.

    The last boundary that still leaves a usable chunk behind, so an unavoidable
    cut lands between sentences rather than inside a word. A block with no
    boundary at all - a minified blob, or a pydantic repr of a page - has
    nowhere better to go than the character limit.
    """
    window = text[:_MAX_CHARS]
    for pattern in _BOUNDARY_RES:
        matches = [m for m in pattern.finditer(window) if m.start() >= _MIN_CHARS]
        if matches:
            return matches[-1].start()
    return _MAX_CHARS


def _resume_at(text: str, cut: int) -> int:
    """Index the next chunk starts at, repeating a boundary-aligned overlap.

    An overlap sliced blindly off the tail begins mid-word, which is the
    mid-sentence passage this is supposed to stop producing. If the window
    holds no boundary, repeat nothing rather than repeat half a word - and
    never return an index that fails to advance, or the caller loops forever.
    """
    start = max(0, cut - _OVERLAP_CHARS)
    for pattern in _BOUNDARY_RES:
        match = pattern.search(text[start:cut])
        if match:
            return min(start + match.end(), cut)
    return cut


def _overlap_tail(chunk: str) -> str:
    """The tail of `chunk` the next chunk repeats, starting at a boundary."""
    return chunk[_resume_at(chunk, len(chunk)) :].strip()


def chunk_markdown(text: str) -> list[str]:
    """Split on structural boundaries, not a fixed character count.

    Embedding a whole page as one vector produces a single blurry centroid that
    matches everything weakly and nothing strongly. Splitting on headings and
    paragraphs keeps each chunk about one thing; the overlap keeps a fact that
    straddles a boundary from being lost.

    Three things have to hold for a retrieved passage to be readable on its own:
    a heading stays with the text beneath it, an overlap starts at a boundary,
    and an unavoidable mid-block cut lands at one too. Character-count chunking
    fails all three, which is what it was doing to every scraped page for as
    long as the page arrived as a single unstructured blob.
    """
    if not text or not text.strip():
        return []

    chunks: list[str] = []
    current = ""
    for block in _structural_blocks(text):
        candidate = f"{current}\n\n{block}".strip() if current else block
        if len(candidate) <= _MAX_CHARS:
            current = candidate
            continue
        if current:
            chunks.append(current)
            # Carry a tail of the previous chunk forward as overlap.
            overlap = _overlap_tail(current)
            current = f"{overlap}\n\n{block}".strip() if overlap else block
        else:
            current = block
        # A single oversized block still has to be cut somewhere.
        while len(current) > _MAX_CHARS:
            cut = _cut_point(current)
            chunks.append(current[:cut].strip())
            current = current[_resume_at(current, cut) :].strip()

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
