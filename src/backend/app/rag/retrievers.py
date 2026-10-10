"""Paper-scoped keyword and vector retrievers: LlamaIndex interfaces over our sessions (ARA-073).

Both always filter the chat's documents, each to its current chunk set, and skip references
unless asked. One search spans every document in scope (per-document metadata filtering,
ARA-088) and returns at most `top_k` passages however many papers a chat has; no paper takes
more than its share, so one long paper cannot fill the list. Each call opens its own session, so
the retrievers can run in parallel.
"""

import math
import re
from collections.abc import Sequence
from uuid import UUID

from llama_index.core.retrievers import BaseRetriever
from llama_index.core.schema import NodeWithScore, QueryBundle, TextNode
from sqlalchemy import func, select, tuple_

from app.models.research import DocumentChunk
from app.models.retrieval import ChunkEmbedding

WORD = re.compile(r"[^\W_]+")
# Bounds the OR fallback for very long questions.
MAX_WORDS = 64


def chunk_node(chunk: DocumentChunk) -> TextNode:
    return TextNode(
        id_=str(chunk.id),
        text=chunk.text,
        metadata={
            "page": chunk.page,
            "page_end": chunk.page_end,
            "section": chunk.heading,
            "kind": chunk.kind,
            "ordinal": chunk.ordinal,
            "document_id": str(chunk.document_id),
            "bboxes": chunk.bboxes,
        },
    )


# A paper's share of one list: an equal part of top k, but never less than the per-paper floor
# of two passages (docs/plans/retrieval-orchestration.md, step 7), so a paper the floor admits
# has candidates for it.
SHARE_FLOOR = 2


class PaperRetriever(BaseRetriever):
    """`scopes` are (document_id, chunk_set) pairs. A search returns at most `top_k` passages,
    each document at most max(SHARE_FLOOR, ceil(top_k / documents)) of them."""

    def __init__(
        self,
        sessions,
        scopes: Sequence[tuple[UUID, str]],
        *,
        top_k: int = 30,
        include_references: bool = False,
    ):
        super().__init__()
        self.sessions, self.scopes = sessions, list(scopes)
        self.top_k, self.include_references = top_k, include_references

    def scoped(self, statement, scopes=None):
        statement = statement.where(
            tuple_(DocumentChunk.document_id, DocumentChunk.chunk_set).in_(scopes or self.scopes)
        )
        if not self.include_references:
            statement = statement.where(DocumentChunk.kind != "references")
        return statement

    async def best(self, session, scored, score, *, descending: bool, scopes=None, limit=None):
        """The best `limit` (default top k) of `scored`, a select of chunk ids and `score`, with
        each document limited to its share; best first."""
        scopes = scopes or self.scopes
        limit = self.top_k if limit is None else limit
        share = max(SHARE_FLOOR, math.ceil(self.top_k / len(scopes)))
        order = score.desc() if descending else score
        position = func.row_number().over(
            partition_by=DocumentChunk.document_id, order_by=(order, DocumentChunk.ordinal)
        )
        ranked = self.scoped(scored.add_columns(position.label("position")), scopes).subquery()
        value = ranked.c.score
        rows = await session.execute(
            select(DocumentChunk, value)
            .join(ranked, ranked.c.id == DocumentChunk.id)
            .where(ranked.c.position <= share)
            .order_by(
                value.desc() if descending else value,
                DocumentChunk.ordinal,
                DocumentChunk.document_id,
            )
            .limit(limit)
        )
        return rows.all()

    def _retrieve(self, query_bundle: QueryBundle) -> list[NodeWithScore]:
        raise NotImplementedError("async only")


class PgLexicalRetriever(PaperRetriever):
    """Weighted full-text search; a document with no passage that has every word may match any.

    Documents that match every word come first, then the any-word matches of the others.
    """

    async def _aretrieve(self, query_bundle: QueryBundle) -> list[NodeWithScore]:
        question = query_bundle.query_str
        async with self.sessions() as session:
            rows = await self.search(session, func.websearch_to_tsquery("english", question))
            # Phase 0: 196 of 300 natural questions matched no passage with every word.
            words = list(dict.fromkeys(WORD.findall(question.lower())))[:MAX_WORDS]
            matched = {chunk.document_id for chunk, _ in rows}
            rest = [scope for scope in self.scopes if scope[0] not in matched]
            if rest and words and len(rows) < self.top_k:
                query = func.to_tsquery("english", " | ".join(words))
                rows += await self.search(session, query, rest, self.top_k - len(rows))
        return [NodeWithScore(node=chunk_node(chunk), score=float(rank)) for chunk, rank in rows]

    async def search(self, session, query, scopes=None, limit=None):
        rank = func.ts_rank_cd(DocumentChunk.search_vector, query, 32)
        scored = select(DocumentChunk.id, rank.label("score")).where(
            DocumentChunk.search_vector.op("@@")(query)
        )
        return await self.best(session, scored, rank, descending=True, scopes=scopes, limit=limit)


class PgVectorRetriever(PaperRetriever):
    """Exact cosine search over one serving profile's vectors; staged `#r` vectors never match."""

    def __init__(self, sessions, scopes: Sequence[tuple[UUID, str]], profile: str, **options):
        super().__init__(sessions, scopes, **options)
        self.profile = profile

    async def _aretrieve(self, query_bundle: QueryBundle) -> list[NodeWithScore]:
        if query_bundle.embedding is None:
            raise ValueError("Vector retrieval needs a query embedding.")
        distance = ChunkEmbedding.embedding.cosine_distance(query_bundle.embedding)
        scored = (
            select(DocumentChunk.id, distance.label("score"))
            .join(ChunkEmbedding, ChunkEmbedding.chunk_id == DocumentChunk.id)
            .where(
                ChunkEmbedding.document_id.in_([document for document, _ in self.scopes]),
                ChunkEmbedding.profile == self.profile,
            )
        )
        async with self.sessions() as session:
            rows = await self.best(session, scored, distance, descending=False)
        return [
            NodeWithScore(node=chunk_node(chunk), score=1 - float(distance))
            for chunk, distance in rows
        ]
