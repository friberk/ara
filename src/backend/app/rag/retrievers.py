"""Paper-scoped keyword and vector retrievers: LlamaIndex interfaces over our sessions (ARA-073).

Both always filter the chat's documents, each to its current chunk set, and skip references
unless asked. One search spans every document in scope (per-document metadata filtering,
ARA-088) and returns at most `top_k` passages however many papers a chat has; no paper takes
more than its share, so one long paper cannot fill the list. Each call opens its own session, so
the retrievers can run in parallel. The summary retrievers search section summaries (ARA-079)
the same way, beside the chunks (RAPTOR's collapsed tree).
"""

import math
import re
from collections.abc import Sequence
from uuid import UUID

from llama_index.core.retrievers import BaseRetriever
from llama_index.core.schema import NodeWithScore, QueryBundle, TextNode
from sqlalchemy import func, select, tuple_

from app.models.research import DocumentChunk
from app.models.retrieval import ChunkEmbedding, SectionSummary, SectionSummaryEmbedding

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


# Source markers stay in a summary's metadata; reranking and display read its plain text.
MARKER = re.compile(r"\s*\[source:[^\]]+\]")


def summary_node(summary: SectionSummary) -> TextNode:
    return TextNode(
        id_=str(summary.id),
        text=MARKER.sub("", summary.content),
        metadata={
            "page": summary.page,
            "page_end": summary.page_end,
            "section": summary.title,
            "kind": "summary",
            "ordinal": summary.ordinal,
            "document_id": str(summary.document_id),
            "bboxes": [],
            "content": summary.content,
            "sources": list(summary.sources),
        },
    )


# A paper's share of one list: an equal part of top k, but never less than the per-paper floor
# of two passages (docs/plans/retrieval-orchestration.md, step 7), so a paper the floor admits
# has candidates for it.
SHARE_FLOOR = 2


class PaperRetriever(BaseRetriever):
    """`scopes` are (document_id, chunk_set) pairs. A search returns at most `top_k` passages,
    each document at most max(SHARE_FLOOR, ceil(top_k / documents)) of them."""

    table = DocumentChunk
    vectors, vector_key = ChunkEmbedding, ChunkEmbedding.chunk_id

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

    @staticmethod
    def node(row) -> TextNode:
        return chunk_node(row)

    def scoped(self, statement, scopes=None):
        table = self.table
        statement = statement.where(
            tuple_(table.document_id, table.chunk_set).in_(scopes or self.scopes)
        )
        if table is DocumentChunk and not self.include_references:
            statement = statement.where(DocumentChunk.kind != "references")
        return statement

    async def best(self, session, scored, score, *, descending: bool, scopes=None, limit=None):
        """The best `limit` (default top k) of `scored`, a select of chunk ids and `score`, with
        each document limited to its share; best first."""
        scopes, table = scopes or self.scopes, self.table
        limit = self.top_k if limit is None else limit
        share = max(SHARE_FLOOR, math.ceil(self.top_k / len(scopes)))
        order = score.desc() if descending else score
        position = func.row_number().over(
            partition_by=table.document_id, order_by=(order, table.ordinal)
        )
        ranked = self.scoped(scored.add_columns(position.label("position")), scopes).subquery()
        value = ranked.c.score
        rows = await session.execute(
            select(table, value)
            .join(ranked, ranked.c.id == table.id)
            .where(ranked.c.position <= share)
            .order_by(value.desc() if descending else value, table.ordinal, table.document_id)
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
        return [NodeWithScore(node=self.node(row), score=float(rank)) for row, rank in rows]

    async def search(self, session, query, scopes=None, limit=None):
        rank = func.ts_rank_cd(self.table.search_vector, query, 32)
        scored = select(self.table.id, rank.label("score")).where(
            self.table.search_vector.op("@@")(query)
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
        # Read from the class: a column attribute on an instance would load a mapped value.
        vectors, key = self.vectors, type(self).vector_key
        distance = vectors.embedding.cosine_distance(query_bundle.embedding)
        scored = (
            select(self.table.id, distance.label("score"))
            .join(vectors, key == self.table.id)
            .where(
                vectors.document_id.in_([document for document, _ in self.scopes]),
                vectors.profile == self.profile,
            )
        )
        async with self.sessions() as session:
            rows = await self.best(session, scored, distance, descending=False)
        return [
            NodeWithScore(node=self.node(row), score=1 - float(distance)) for row, distance in rows
        ]


class SummaryScope:
    """Search section summaries instead of chunks, with the same filters and shares (ARA-079)."""

    table = SectionSummary
    vectors, vector_key = SectionSummaryEmbedding, SectionSummaryEmbedding.summary_id

    @staticmethod
    def node(row) -> TextNode:
        return summary_node(row)


class PgSummaryLexicalRetriever(SummaryScope, PgLexicalRetriever):
    pass


class PgSummaryVectorRetriever(SummaryScope, PgVectorRetriever):
    pass
