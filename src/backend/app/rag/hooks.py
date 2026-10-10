"""Seams between ingestion and indexing, so their owners can work on separate branches (ARA-070)."""

from uuid import UUID


async def after_chunks_persisted(session, *, document_id: UUID | None, resources=None) -> None:
    """Called inside the ingestion transaction after new chunks are saved.

    Queues embedding of the new chunk set for the library embedding model (ARA-072) and, with
    `resources`, its section summaries with the saved default model (ARA-079).
    """
    from app.models.research import Document
    from app.rag.indexing import default_profile, ensure_index
    from app.services import section_summaries

    document = await session.get(Document, document_id) if document_id else None
    if document is None or document.chunk_set is None:
        return
    await ensure_index(session, document.id, await default_profile(session))
    if resources is not None:
        await section_summaries.queue_section_summaries(session, resources, document)
