"""Paper-scoped keyword and vector retrievers: LlamaIndex interfaces over our sessions (ARA-073).

Both always filter the chat's document and its current chunk set and skip references unless
asked. Each call opens its own session, so the retrievers can run in parallel.
"""

import re
from uuid import UUID

from llama_index.core.retrievers import BaseRetriever
from llama_index.core.schema import NodeWithScore, QueryBundle, TextNode
from sqlalchemy import func, select

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


class PaperRetriever(BaseRetriever):
    def __init__(
        self,
        sessions,
        document_id: UUID,
        chunk_set: str,
        *,
        top_k: int = 30,
        include_references: bool = False,
    ):
        super().__init__()
        self.sessions, self.document_id, self.chunk_set = sessions, document_id, chunk_set
        self.top_k, self.include_references = top_k, include_references

    def scoped(self, statement):
        statement = statement.where(
            DocumentChunk.document_id == self.document_id,
            DocumentChunk.chunk_set == self.chunk_set,
        )
        if not self.include_references:
            statement = statement.where(DocumentChunk.kind != "references")
        return statement

    def _retrieve(self, query_bundle: QueryBundle) -> list[NodeWithScore]:
        raise NotImplementedError("async only")


class PgLexicalRetriever(PaperRetriever):
    """Weighted full-text search; when no passage has every word, any word may match."""

    async def _aretrieve(self, query_bundle: QueryBundle) -> list[NodeWithScore]:
        question = query_bundle.query_str
        async with self.sessions() as session:
            rows = await self.search(session, func.websearch_to_tsquery("english", question))
            # Phase 0: 196 of 300 natural questions matched no passage with every word.
            words = list(dict.fromkeys(WORD.findall(question.lower())))[:MAX_WORDS]
            if not rows and words:
                rows = await self.search(session, func.to_tsquery("english", " | ".join(words)))
        return [NodeWithScore(node=chunk_node(chunk), score=float(rank)) for chunk, rank in rows]

    async def search(self, session, query):
        rank = func.ts_rank_cd(DocumentChunk.search_vector, query, 32)
        rows = await session.execute(
            self.scoped(select(DocumentChunk, rank))
            .where(DocumentChunk.search_vector.op("@@")(query))
            .order_by(rank.desc(), DocumentChunk.ordinal)
            .limit(self.top_k)
        )
        return rows.all()


class PgVectorRetriever(PaperRetriever):
    """Exact cosine search over one serving profile's vectors; staged `#r` vectors never match."""

    def __init__(self, sessions, document_id: UUID, chunk_set: str, profile: str, **options):
        super().__init__(sessions, document_id, chunk_set, **options)
        self.profile = profile

    async def _aretrieve(self, query_bundle: QueryBundle) -> list[NodeWithScore]:
        if query_bundle.embedding is None:
            raise ValueError("Vector retrieval needs a query embedding.")
        distance = ChunkEmbedding.embedding.cosine_distance(query_bundle.embedding)
        async with self.sessions() as session:
            rows = await session.execute(
                self.scoped(select(DocumentChunk, distance))
                .join(ChunkEmbedding, ChunkEmbedding.chunk_id == DocumentChunk.id)
                .where(
                    ChunkEmbedding.document_id == self.document_id,
                    ChunkEmbedding.profile == self.profile,
                )
                .order_by(distance, DocumentChunk.ordinal)
                .limit(self.top_k)
            )
            rows = rows.all()
        return [
            NodeWithScore(node=chunk_node(chunk), score=1 - float(distance))
            for chunk, distance in rows
        ]
