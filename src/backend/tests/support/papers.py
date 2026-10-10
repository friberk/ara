"""A ready paper with structured chunks, for retrieval and indexing tests."""

from uuid import uuid4

from app.models.research import Document, DocumentChunk, ModelConfiguration, Paper

CHUNK_SET = "layout-v1:fixture"
OPENAI, QWEN = "openai-3-large", "qwen3-embed-4b"
SMALL = "openai-3-small"


async def seed_paper(resources, *, chunks=5):
    async with resources.sessions() as session, session.begin():
        paper = Paper(id=uuid4(), title="Sparse Retrieval")
        session.add(paper)
        await session.flush()
        document = Document(
            id=uuid4(),
            paper_id=paper.id,
            status="ready",
            object_key=f"documents/{uuid4()}.pdf",
            sha256=uuid4().hex + uuid4().hex,
            original_filename="paper.pdf",
            byte_size=10,
            request_id=uuid4(),
            chunk_set=CHUNK_SET,
            parser="pymupdf4llm-layout",
        )
        session.add(document)
        await session.flush()
        paper.active_document_id = document.id
        for ordinal in range(chunks):
            body = f"Passage {ordinal} reports dense retrieval recall {ordinal}."
            session.add(
                DocumentChunk(
                    document_id=document.id,
                    chunk_set=CHUNK_SET,
                    ordinal=ordinal,
                    section_path=["Results"],
                    heading="Results",
                    page=1,
                    page_end=1,
                    text=body,
                    context_text=f"Sparse Retrieval\nResults\n{body}",
                    token_count=12,
                )
            )
    return paper.id, document.id


async def use_library_profile(resources, profile):
    """Store the library-wide embedding model without queueing any work."""
    async with resources.sessions() as session, session.begin():
        await session.merge(
            ModelConfiguration(key="retrieval", value={"embedding_profile": profile})
        )
