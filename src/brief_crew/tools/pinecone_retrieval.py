"""`retrieve_and_rerank` - the one custom tool in this project.

CrewAI cannot reach Pinecone natively. Confirmed by source inspection of
1.15.18::

    SupportedProvider = Literal["chromadb", "qdrant"]
    # crewai/rag/config/optional_imports/types.py

and there are zero ``pinecone`` references anywhere in ``crewai`` or
``crewai_tools``. So retrieval goes through a ``BaseTool`` calling the Pinecone
SDK directly, and CrewAI's ``embedder=`` config is off the critical path
entirely - it configures only the Chroma-backed Knowledge/Memory stores, which
this design does not use.

Four steps inside one call: embed -> query 20 -> rerank -> return 5. Retrieving
20 and returning 5 is deliberate. The reranker needs candidates to discriminate
between, but every chunk handed to the agent becomes prompt tokens in every
subsequent call of the run.

Reranking lives *here*, not in an agent. A cross-encoder scoring call has zero
reasoning content; wrapping it in an Agent buys a role, a backstory and an LLM
call around a pure function. See agents/06-retrieval-layer.md.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from typing import Any, Type

from crewai.tools import BaseTool, EnvVar
from pydantic import BaseModel, Field

from brief_crew.config import (
    PINECONE_INDEX_NAME,
    RERANK_MODEL,
    RETRIEVE_CANDIDATES,
    RETRIEVE_TOP_K,
)
from brief_crew.embeddings import embed_query


class RetrieveRerankInput(BaseModel):
    """Input schema for retrieve_and_rerank."""

    query: str = Field(
        ...,
        description="The topic or question to search the indexed corpus for.",
    )
    top_k: int = Field(
        default=RETRIEVE_TOP_K,
        description="How many reranked chunks to return. Keep small; every chunk "
        "returned becomes prompt tokens for the rest of the run.",
    )


def _rerank(query: str, candidates: list[dict[str, Any]], top_k: int) -> list[dict[str, Any]]:
    """Cohere cross-encoder pass over the Pinecone candidates.

    Not an optimisation. Measured on this index, cosine scores for a good match
    and an irrelevant one span 0.06 - there is no defensible cutoff inside that
    band. The reranked scores span 0.28. The reranker is what makes the router's
    threshold implementable at all.
    """
    import cohere

    client = cohere.ClientV2(api_key=os.environ["COHERE_API_KEY"])
    response = client.rerank(
        model=RERANK_MODEL,
        query=query,
        documents=[c["text"] for c in candidates],
        top_n=min(top_k, len(candidates)),
    )

    reranked: list[dict[str, Any]] = []
    for result in response.results:
        hit = dict(candidates[result.index])
        hit["rerank_score"] = float(result.relevance_score)
        reranked.append(hit)
    return reranked


def retrieve(
    query: str,
    top_k: int = RETRIEVE_TOP_K,
    *,
    metadata_filter: Mapping[str, Any] | None = None,
    namespace: str | None = None,
) -> list[dict[str, Any]]:
    """Embed, query Pinecone, rerank, truncate. Returns hits as plain dicts.

    Exposed as a plain function as well as a tool because the Track B Flow calls
    it directly from its ``@start`` step, with no agent involved. Validator
    callers can isolate branch/category evidence with ``metadata_filter`` and a
    per-user ``namespace``; existing callers issue the same unfiltered query.
    """
    from pinecone import Pinecone

    vector = embed_query(query)

    pc = Pinecone(api_key=os.environ["PINECONE_API_KEY"])
    index = pc.Index(PINECONE_INDEX_NAME)
    query_options: dict[str, Any] = dict(
        vector=vector,
        top_k=RETRIEVE_CANDIDATES,
        include_metadata=True,
    )
    if metadata_filter is not None:
        query_options["filter"] = dict(metadata_filter)
    if namespace is not None:
        query_options["namespace"] = namespace
    response = index.query(**query_options)

    candidates: list[dict[str, Any]] = []
    for match in response.get("matches", []):
        metadata = match.get("metadata") or {}
        text = metadata.get("text")
        if not text:
            continue
        candidate = dict(metadata)
        candidate["text"] = text
        candidate["cosine_score"] = float(match.get("score", 0.0))
        candidates.append(candidate)

    if not candidates:
        return []
    return _rerank(query, candidates, top_k)


class PineconeRetrieveRerankTool(BaseTool):
    name: str = "retrieve_and_rerank"
    description: str = (
        "Search the indexed corpus for material already gathered on a topic. "
        "Returns up to five reranked passages, each with its source URL, "
        "publisher, publication date, the date it was indexed, and a relevance "
        "score. Use this BEFORE searching the live web. Judge what comes back on "
        "both relevance and freshness: material indexed more than 60 days ago is "
        "a lead, not a current fact."
    )
    args_schema: Type[BaseModel] = RetrieveRerankInput
    env_vars: list[EnvVar] = [
        EnvVar(name="PINECONE_API_KEY", description="Pinecone vector store", required=True),
        EnvVar(name="OPENROUTER_API_KEY", description="Embeddings via OpenRouter", required=True),
        EnvVar(name="COHERE_API_KEY", description="Stage-2 reranking", required=True),
    ]

    def _run(self, query: str, top_k: int = RETRIEVE_TOP_K) -> str:
        try:
            hits = retrieve(query, top_k=top_k)
        except Exception as exc:  # surfaced to the agent, not swallowed
            # A silent tool failure is what produces fabricated citations: the
            # agent carries on and invents what the call would have returned.
            return (
                f"RETRIEVAL FAILED: {type(exc).__name__}: {exc}. "
                "Treat the corpus as empty and search the live web instead. "
                "Do NOT report any cached fact - you received none."
            )

        if not hits:
            return (
                "No indexed material found for this query. The corpus is empty "
                "for this topic. Search the live web."
            )

        # The agent is being asked to judge freshness, so it needs the dates as
        # much as the text. JSON keeps the field boundaries unambiguous.
        return json.dumps(hits, indent=2, default=str)
