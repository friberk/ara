"""Evidence for one answer: hybrid search, fusion, expansion and packing (ARA-073).

Retrieval stays inside the chat's immutable document and that document's current chunk set.
Without a ready index it searches by keywords and says why; it never reads a half-built index.
"""

import asyncio
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from uuid import UUID

from llama_index.core.schema import NodeWithScore, QueryBundle, TextNode
from sqlalchemy import select

from app.core.errors import AppError
from app.integrations.embedding_catalog import PROFILES, embedding_profile
from app.integrations.embeddings import create_embedder
from app.integrations.tokens import TokenCounter
from app.models.research import DocumentChunk
from app.models.retrieval import RetrievalIndex
from app.rag.fusion import reciprocal_rank_fusion
from app.rag.indexing import ready_index
from app.rag.packing import Passage, pack_evidence, render_evidence
from app.rag.retrievers import PgLexicalRetriever, PgVectorRetriever, chunk_node
from app.schemas.ai import RetrievalSummary

TOP_K = 30
MAX_PASSAGES = 16
BUILDING_NOTE = "Searched by keywords until the search index is built."
UNAVAILABLE_NOTE = "Searched by keywords because the search index is unavailable."
MODEL_DOWN_NOTE = "Searched by keywords because the search model is unavailable right now."
OPENING_NOTE = "No passage matched the question, so the paper's opening passages were used."


@dataclass
class EvidenceResult:
    passages: list[Passage]
    summary: RetrievalSummary
    trace: dict
    ranked: list[NodeWithScore] = field(default_factory=list)
    neighbours: dict[str, list[TextNode]] = field(default_factory=dict)
    counter: TokenCounter | None = None
    # One vector per query, in `summary.profile`; None when searching by keywords only.
    vectors: list[list[float]] | None = None

    def pack(self, budget: int) -> list[Passage]:
        self.passages = pack_evidence(
            self.ranked,
            budget=budget,
            counter=self.counter,
            neighbours=self.neighbours,
            max_passages=MAX_PASSAGES,
        )
        chosen = {str(item.chunk_id) for item in self.passages}
        self.summary.passages_used = len(self.passages)
        self.summary.limited_by_context = any(
            item.node.node_id not in chosen for item in self.ranked[:MAX_PASSAGES]
        )
        self.trace["selected"] = {item.handle: str(item.chunk_id) for item in self.passages}
        self.trace["budget"] = budget
        return self.passages

    def block(self, budget: int) -> str:
        """The `evidence_block` for answer assembly, which may grant less than retrieval used."""
        return render_evidence(self.pack(budget))


def elapsed(start: float) -> int:
    return round((time.monotonic() - start) * 1000)


def ranks(items: Sequence[NodeWithScore]) -> list:
    return [[item.node.node_id, rank, item.score] for rank, item in enumerate(items[:TOP_K], 1)]


async def keyword_note(session, document_id: UUID, chunk_set: str, preferred: str) -> str:
    state = await session.scalar(
        select(RetrievalIndex.state).where(
            RetrievalIndex.document_id == document_id,
            RetrievalIndex.profile == preferred,
            RetrievalIndex.chunk_set == chunk_set,
        )
    )
    return UNAVAILABLE_NOTE if state in {"failed", "unavailable"} else BUILDING_NOTE


async def embed_queries(resources, profile: str, queries: list[str]) -> list[list[float]]:
    embedder = create_embedder(resources, embedding_profile(profile))
    try:
        return await embedder.embed_queries(queries)
    finally:
        await embedder.close()


def scoped(document_id: UUID, chunk_set: str):
    return select(DocumentChunk).where(
        DocumentChunk.document_id == document_id,
        DocumentChunk.chunk_set == chunk_set,
        DocumentChunk.kind != "references",
    )


async def opening_nodes(resources, document_id: UUID, chunk_set: str) -> list[NodeWithScore]:
    async with resources.sessions() as session:
        chunks = await session.scalars(
            scoped(document_id, chunk_set).order_by(DocumentChunk.ordinal).limit(MAX_PASSAGES)
        )
        return [NodeWithScore(node=chunk_node(chunk), score=0.0) for chunk in chunks]


async def neighbour_nodes(
    resources, document_id: UUID, chunk_set: str, ranked: Sequence[NodeWithScore]
) -> dict[str, list[TextNode]]:
    """The passages just before and after each candidate, when they share its section."""
    wanted = {item.node.metadata["ordinal"] + step for item in ranked for step in (-1, 1)}
    async with resources.sessions() as session:
        rows = await session.scalars(
            scoped(document_id, chunk_set).where(DocumentChunk.ordinal.in_(wanted))
        )
        nearby = {chunk.ordinal: chunk for chunk in rows}
    found = {}
    for item in ranked:
        ordinal, section = item.node.metadata["ordinal"], item.node.metadata["section"]
        same = [
            chunk_node(nearby[step])
            for step in (ordinal - 1, ordinal + 1)
            if step in nearby and nearby[step].heading == section
        ]
        if same:
            found[item.node.node_id] = same
    return found


async def retrieve_evidence(
    resources,
    *,
    document_id: UUID,
    chunk_set: str,
    preferred_profile: str,
    queries: list[str],
    budget: int,
    counter: TokenCounter,
) -> EvidenceResult:
    started = time.monotonic()
    timings = {}
    summary = RetrievalSummary(mode="keyword", search_queries=list(queries))
    async with resources.sessions() as session:
        index = await ready_index(session, document_id, preferred_profile)
        if index is None:
            summary.note = await keyword_note(session, document_id, chunk_set, preferred_profile)
    vectors = None
    if index is not None:
        clock = time.monotonic()
        try:
            vectors = await embed_queries(resources, index.profile, list(queries))
        except AppError:
            summary.note = MODEL_DOWN_NOTE
        else:
            summary.mode, summary.profile = "hybrid", index.profile
            if index.profile != preferred_profile:
                summary.note = (
                    f"Searched with {PROFILES[index.profile].display_name} until "
                    f"{PROFILES[preferred_profile].display_name} is ready."
                )
        timings["embed"] = elapsed(clock)
    clock = time.monotonic()
    searches = []
    for position, query in enumerate(queries):
        keyword = PgLexicalRetriever(resources.sessions, document_id, chunk_set, top_k=TOP_K)
        searches.append(("keyword", query, keyword.aretrieve(query)))
        if vectors is not None:
            vector = PgVectorRetriever(
                resources.sessions, document_id, chunk_set, index.profile, top_k=TOP_K
            )
            bundle = QueryBundle(query_str=query, embedding=vectors[position])
            searches.append(("vector", query, vector.aretrieve(bundle)))
    # Each retriever call opens its own session, so the searches run in parallel.
    results = await asyncio.gather(*(search for _, _, search in searches))
    timings["search"] = elapsed(clock)
    fused = reciprocal_rank_fusion(results)
    ranked = fused
    if not ranked:
        ranked = await opening_nodes(resources, document_id, chunk_set)
        summary.note = " ".join(filter(None, [summary.note, OPENING_NOTE]))
    summary.passages_found = len(fused)
    neighbours = await neighbour_nodes(resources, document_id, chunk_set, ranked[:MAX_PASSAGES])
    trace = {
        "queries": list(queries),
        "mode": summary.mode,
        "profile": summary.profile,
        "lists": [
            {"retriever": kind, "query": query, "results": ranks(found)}
            for (kind, query, _), found in zip(searches, results, strict=True)
        ],
        "fused": [[item.node.node_id, item.score] for item in fused[:TOP_K]],
        "reranked": [],
        "timings_ms": timings,
    }
    result = EvidenceResult([], summary, trace, ranked, neighbours, counter, vectors)
    result.pack(budget)
    timings["total"] = elapsed(started)
    return result
