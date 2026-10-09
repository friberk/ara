"""Migration 0006: pgvector, structured chunks, indexes and conversation memory (ARA-070)."""

from uuid import uuid4

import pytest
from sqlalchemy import func, select, text

pytestmark = pytest.mark.integration


async def table_columns(session, table):
    rows = await session.scalars(
        text("select column_name from information_schema.columns where table_name = :table"),
        {"table": table},
    )
    return set(rows.all())


async def test_given_migrated_database_then_vector_and_new_tables_exist(resources):
    async with resources.sessions() as session:
        extensions = set((await session.scalars(text("select extname from pg_extension"))).all())
        assert "vector" in extensions
        tables = set(
            (
                await session.scalars(
                    text("select tablename from pg_tables where schemaname = 'public'")
                )
            ).all()
        )
        assert {
            "document_sections",
            "chunk_embeddings",
            "retrieval_indexes",
            "chat_memories",
            "chat_turn_embeddings",
        } <= tables
        chunks = await table_columns(session, "document_chunks")
        assert {
            "chunk_set",
            "section_id",
            "section_path",
            "heading",
            "kind",
            "page",
            "page_end",
            "text",
            "context_text",
            "bboxes",
            "token_count",
            "search_vector",
        } <= chunks
        assert not {"char_start", "char_end", "token_estimate"} & chunks
        assert "retrieval_profile" in await table_columns(session, "papers")
        assert {"parser", "chunk_set"} <= await table_columns(session, "documents")
        assert {"retrieval", "context", "grounding"} <= await table_columns(
            session, "chat_messages"
        )


async def seed_document(session):
    from app.models.research import Document, Paper

    paper = Paper(id=uuid4(), title="Schema fixture")
    document = Document(
        id=uuid4(),
        paper_id=paper.id,
        status="ready",
        object_key=f"documents/{uuid4()}.pdf",
        sha256=uuid4().hex + uuid4().hex,
        original_filename="fixture.pdf",
        byte_size=10,
        request_id=uuid4(),
        chunk_set="test-set",
        parser="pymupdf4llm-layout",
    )
    session.add(paper)
    await session.flush()  # no ORM relationship orders the inserts, so flush the parent first
    session.add(document)
    await session.flush()
    return paper, document


def chunk(document_id, ordinal, heading, body):
    from app.models.research import DocumentChunk

    return DocumentChunk(
        document_id=document_id,
        chunk_set="test-set",
        ordinal=ordinal,
        section_path=[heading] if heading else [],
        heading=heading,
        kind="text",
        page=1,
        page_end=1,
        text=body,
        context_text=f"{heading}\n{body}",
        token_count=len(body.split()),
    )


async def test_given_heading_match_when_searching_then_it_outranks_body_match(resources):
    from app.models.research import DocumentChunk

    async with resources.sessions() as session, session.begin():
        _, document = await seed_document(session)
        session.add_all(
            [
                chunk(document.id, 0, "Methods", "We discuss attention once in passing."),
                chunk(document.id, 1, "Attention", "We discuss the mechanism once in passing."),
            ]
        )
    query = func.websearch_to_tsquery("english", "attention")
    async with resources.sessions() as session:
        ranked = (
            await session.scalars(
                select(DocumentChunk.ordinal)
                .where(
                    DocumentChunk.document_id == document.id,
                    DocumentChunk.search_vector.op("@@")(query),
                )
                .order_by(func.ts_rank_cd(DocumentChunk.search_vector, query).desc())
            )
        ).all()
    assert ranked == [1, 0]


async def test_given_halfvec_embeddings_when_ordered_by_cosine_then_nearest_first(resources):
    from app.models.research import DocumentChunk
    from app.models.retrieval import ChunkEmbedding

    async with resources.sessions() as session, session.begin():
        _, document = await seed_document(session)
        rows = [chunk(document.id, index, "Section", f"text {index}") for index in range(3)]
        session.add_all(rows)
        await session.flush()
        vectors = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.7, 0.7, 0.0]]
        for row, vector in zip(rows, vectors, strict=True):
            session.add(
                ChunkEmbedding(
                    chunk_id=row.id,
                    profile="fixture",
                    document_id=document.id,
                    embedding=vector,
                    input_hash="0" * 64,
                )
            )
    async with resources.sessions() as session:
        nearest = (
            await session.scalars(
                select(DocumentChunk.ordinal)
                .join(ChunkEmbedding, ChunkEmbedding.chunk_id == DocumentChunk.id)
                .where(ChunkEmbedding.profile == "fixture")
                .order_by(ChunkEmbedding.embedding.cosine_distance([1.0, 0.1, 0.0]))
            )
        ).all()
    assert nearest == [0, 2, 1]


async def test_given_deleted_document_then_chunks_embeddings_and_indexes_cascade(resources):
    from app.models.research import Document, DocumentChunk
    from app.models.retrieval import ChunkEmbedding, RetrievalIndex

    async with resources.sessions() as session, session.begin():
        _, document = await seed_document(session)
        row = chunk(document.id, 0, "Section", "text")
        session.add(row)
        await session.flush()
        session.add(
            ChunkEmbedding(
                chunk_id=row.id,
                profile="fixture",
                document_id=document.id,
                embedding=[1.0, 0.0],
                input_hash="0" * 64,
            )
        )
        session.add(
            RetrievalIndex(document_id=document.id, profile="fixture", chunk_set="test-set")
        )
    async with resources.sessions() as session, session.begin():
        await session.delete(await session.get(Document, document.id))
    async with resources.sessions() as session:
        for model in (DocumentChunk, ChunkEmbedding, RetrievalIndex):
            count = await session.scalar(
                select(func.count()).select_from(model).where(model.document_id == document.id)
            )
            assert count == 0, model.__name__
