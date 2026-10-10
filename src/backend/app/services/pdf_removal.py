"""Removing a paper's PDF from the reader (ARA-097).

The paper stays; every PDF of it, the current one and earlier versions, goes, so the reader
returns to its upload state. One transaction:
- refuses while a chat that uses one of those PDFs is writing an answer (409 CHAT_BUSY);
- detaches the paper's current PDF;
- settles the PDFs' queued and running jobs as failed with PDF_REMOVED, fencing their workers out
  (rows locked by a worker's own transaction are skipped, as in services/deletion.py);
- deletes the PDFs' summaries;
- deletes each PDF that no chat pins, with its pages, passages, sections, embeddings and indexes
  (foreign-key cascades);
- empties each PDF a chat pins and marks it removed. `chat_papers.document_id` is NOT NULL
  (migration 0010), so the row stays for the chat: its saved answers keep their quoted passages,
  its passages and file answer 404 PDF_REMOVED, and it takes no new questions because the PDF is
  no longer ready. The row's file key and digest change, so the same file can be uploaded again;
- queues ARA-095's durable `storage_cleanup` job for the stored files.

Locks follow the order the rest of the app uses: identity locks, then chats, then the paper.
"""

from uuid import UUID, uuid4

from sqlalchemy import delete, func, select

from app.core.errors import AppError
from app.models.jobs import BackgroundJob
from app.models.research import (
    REMOVED_PDF_PREFIX,
    ChatPaper,
    ChatSession,
    Document,
    DocumentChunk,
    DocumentPage,
    DocumentUploadRequest,
    Paper,
    PaperSummary,
    UploadMatch,
)
from app.models.retrieval import ChunkEmbedding, DocumentSection, RetrievalIndex
from app.repositories.jobs import enqueue, now
from app.repositories.papers import identity_locks
from app.schemas.research import ChatLink, PdfRemovalPreview
from app.services.deletion import (
    STORAGE_CLEANUP,
    UPLOADING_DELAY_SECONDS,
    answering,
    related_jobs,
)

PDF_REMOVED = "PDF_REMOVED"
STOPPED = "Stopped because the PDF was removed."
REMOVED = "This PDF was removed. Saved answers keep their quoted passages."


def pdf_removed_error() -> AppError:
    return AppError(404, PDF_REMOVED, REMOVED)


def paper_pdfs(paper_id: UUID):
    """The paper's PDFs that are still there."""
    return select(Document).where(Document.paper_id == paper_id, ~Document.removed)


def using_chats(document_ids):
    return select(ChatPaper.chat_id).where(ChatPaper.document_id.in_(document_ids))


async def removal_preview(session, paper_id: UUID) -> PdfRemovalPreview:
    if await session.get(Paper, paper_id) is None:
        raise AppError(404, "PAPER_NOT_FOUND", "Paper not found.")
    documents = (await session.scalars(paper_pdfs(paper_id).with_only_columns(Document.id))).all()
    chats = (
        await session.scalars(
            select(ChatSession)
            .where(ChatSession.id.in_(using_chats(documents)))
            .order_by(ChatSession.created_at, ChatSession.id)
        )
    ).all()
    return PdfRemovalPreview(
        pdfs=len(documents),
        summaries=await session.scalar(
            select(func.count())
            .select_from(PaperSummary)
            .where(PaperSummary.document_id.in_(documents))
        ),
        chats=[ChatLink(id=chat.id, title=chat.title) for chat in chats],
        active_jobs=await session.scalar(
            select(func.count()).select_from(related_jobs([], documents, []).subquery())
        ),
        answering=bool(chats) and await session.scalar(select(answering([c.id for c in chats]))),
    )


def settle_removed_locked(job: BackgroundJob) -> None:
    """Fail a locked job whose PDF was removed."""
    job.state = job.stage = "failed"
    job.error_code, job.error_message = PDF_REMOVED, STOPPED
    job.result = {"outcome": "pdf_removed"}
    job.lease_token = job.lease_expires_at = None
    job.updated_at = now()


async def empty_pinned(session, pinned: list[UUID]) -> None:
    """Delete what a pinned PDF held and mark its row removed, freeing its key and digest."""
    for model in (
        DocumentPage,
        DocumentChunk,
        ChunkEmbedding,
        DocumentSection,
        RetrievalIndex,
        DocumentUploadRequest,
        UploadMatch,
    ):
        await session.execute(delete(model).where(model.document_id.in_(pinned)))
    for document in (await session.scalars(select(Document).where(Document.id.in_(pinned)))).all():
        document.status = "failed"
        document.object_key = f"{REMOVED_PDF_PREFIX}{document.id}"
        document.sha256 = f"removed:{document.id.hex}"
        document.request_id = uuid4()
        document.warnings = [REMOVED]
        document.chunk_set = document.parser = None


async def remove_pdfs(session, paper_id: UUID) -> None:
    """Remove every PDF of the paper; a paper without one is left as it is."""
    from app.services.chat import expire
    from app.services.upload_match import pending_lock_key

    if await session.get(Paper, paper_id) is None:
        raise AppError(404, "PAPER_NOT_FOUND", "Paper not found.")
    digests = (await session.scalars(paper_pdfs(paper_id).with_only_columns(Document.sha256))).all()
    # Uploads, retrievals and match decisions for this paper wait for the removal.
    await identity_locks(session, [pending_lock_key(paper_id), *(f"pdf:{d}" for d in digests)])
    owned = select(Document.id).where(Document.paper_id == paper_id, ~Document.removed)
    chat_ids = (
        await session.scalars(
            select(ChatSession.id)
            .where(ChatSession.id.in_(using_chats(owned)))
            .order_by(ChatSession.id)
            .with_for_update()
        )
    ).all()
    for chat_id in chat_ids:
        await expire(session, chat_id)
    if chat_ids and await session.scalar(select(answering(chat_ids))):
        raise AppError(
            409, "CHAT_BUSY", "Wait for the current answer to finish before removing the PDF."
        )
    paper = await session.scalar(
        select(Paper)
        .where(Paper.id == paper_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if paper is None:
        raise AppError(404, "PAPER_NOT_FOUND", "Paper not found.")
    documents = (await session.scalars(paper_pdfs(paper_id).order_by(Document.id))).all()
    paper.active_document_id = None
    if not documents:
        return
    paper.updated_at = now()
    ids = [document.id for document in documents]
    stored = sorted(document.object_key for document in documents)
    uploading = any(document.status == "uploading" for document in documents)
    jobs = (
        await session.scalars(related_jobs([], ids, []).with_for_update(skip_locked=True))
    ).all()
    for job in jobs:
        settle_removed_locked(job)
    await session.execute(delete(PaperSummary).where(PaperSummary.document_id.in_(ids)))
    pinned = set(
        (
            await session.scalars(
                select(ChatPaper.document_id).where(ChatPaper.document_id.in_(ids)).distinct()
            )
        ).all()
    )
    if pinned:
        await empty_pinned(session, sorted(pinned))
    await session.execute(delete(Document).where(Document.id.in_(set(ids) - pinned)))
    await enqueue(
        session,
        kind=STORAGE_CLEANUP,
        payload={"object_keys": stored, "paper_titles": [paper.title]},
        delay_seconds=UPLOADING_DELAY_SECONDS if uploading else 0,
    )
