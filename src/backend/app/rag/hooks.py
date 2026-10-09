"""Seams between ingestion and indexing, so their owners can work on separate branches (ARA-070)."""

from uuid import UUID


async def after_chunks_persisted(session, *, document_id: UUID | None) -> None:
    """Called inside the ingestion transaction after new chunks are saved.

    ARA-072 replaces this body with `ensure_index(...)` for the paper's effective profile.
    """
    return None
