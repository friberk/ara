"""Seams between ingestion and indexing, so their owners can work on separate branches (ARA-070)."""

from uuid import UUID


async def after_chunks_persisted(session, *, document_id: UUID | None) -> None:
    """Called inside the ingestion transaction after new chunks are saved.

    Queues embedding of the new chunk set for the paper's effective profile (ARA-072).
    """
    from app.models.research import Document, Paper
    from app.rag.indexing import effective_profile, ensure_index

    document = await session.get(Document, document_id) if document_id else None
    if document is None or document.chunk_set is None:
        return
    paper = await session.get(Paper, document.paper_id)
    profile, _ = await effective_profile(session, paper)
    await ensure_index(session, document.id, profile)
