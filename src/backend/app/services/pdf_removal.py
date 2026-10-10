"""Removing a paper's PDF from the reader, and deleting PDFs nothing uses any more (ARA-097).

Removing the PDF detaches it: the paper has no current PDF, so the reader returns to its upload
state and new conversations need a new PDF. Older conversations continue as they are. A chat
pins the PDF it was asked about (`chat_papers.document_id`, ARA-088), and a pinned PDF stays
whole, with its pages, passages, sections, embeddings, indexes, section summaries, summaries and
stored file; the chat keeps asking about it.

One rule then decides what goes: a PDF that is no paper's current PDF and that no chat pins is
deleted (`delete_detached`). Its rows go by cascade, its summaries first (they have no cascade),
its queued and running jobs fail with PDF_REMOVED, and ARA-095's durable `storage_cleanup`
removes its stored file. It runs when a PDF is removed, when a chat is deleted and when a chat
drops a paper. Uploading a kept PDF's file again makes it current again (services/uploads.py).

Locks follow the order the rest of the app uses: identity locks (`pdf:<sha256>` of the PDFs
that may go), then chats, then papers. Callers that lock a chat take the identity locks first.
"""

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import delete, func, select

from app.core.errors import AppError
from app.models.jobs import BackgroundJob
from app.models.research import ChatPaper, ChatSession, Document, Paper, PaperSummary
from app.repositories.jobs import now
from app.repositories.papers import identity_locks
from app.schemas.research import ChatLink, PdfRemovalPreview
from app.services.deletion import answering, queue_storage_cleanup, related_jobs

PDF_REMOVED = "PDF_REMOVED"
STOPPED = "Stopped because the PDF was removed."


def pinned_by_chats(document_ids):
    return select(ChatPaper.document_id).where(ChatPaper.document_id.in_(document_ids))


def using_chats(document_ids):
    return select(ChatPaper.chat_id).where(ChatPaper.document_id.in_(document_ids))


async def lock_pdfs(session, document_ids: Sequence[UUID]) -> None:
    """Take the identity locks uploads take for these PDFs, so one cannot bring a PDF back while
    it is being deleted. Call it before locking any chat."""
    digests = await session.scalars(select(Document.sha256).where(Document.id.in_(document_ids)))
    await identity_locks(session, [f"pdf:{digest}" for digest in digests.all()])


async def delete_detached(session, document_ids: Sequence[UUID]) -> list[UUID]:
    """Delete those of these PDFs that no paper reads and no chat pins; returns their IDs."""
    if not document_ids:
        return []
    await session.flush()
    documents = (
        await session.scalars(
            select(Document)
            .where(
                Document.id.in_(document_ids),
                Document.id.not_in(
                    select(Paper.active_document_id).where(Paper.active_document_id.is_not(None))
                ),
                Document.id.not_in(pinned_by_chats(document_ids)),
            )
            .order_by(Document.id)
            .with_for_update()
        )
    ).all()
    if not documents:
        return []
    ids = [document.id for document in documents]
    jobs = await session.scalars(related_jobs([], ids, []).with_for_update(skip_locked=True))
    for job in jobs.all():
        settle_removed_locked(job)
    titles = await session.scalars(
        select(Paper.title).where(Paper.id.in_({document.paper_id for document in documents}))
    )
    await queue_storage_cleanup(session, documents, paper_titles=titles.all())
    await session.execute(delete(PaperSummary).where(PaperSummary.document_id.in_(ids)))
    await session.execute(delete(Document).where(Document.id.in_(ids)))
    return ids


def settle_removed_locked(job: BackgroundJob) -> None:
    """Fail a locked job whose PDF was deleted."""
    job.state = job.stage = "failed"
    job.error_code, job.error_message = PDF_REMOVED, STOPPED
    job.result = {"outcome": "pdf_removed"}
    job.lease_token = job.lease_expires_at = None
    job.updated_at = now()


async def removal_preview(session, paper_id: UUID) -> PdfRemovalPreview:
    if await session.get(Paper, paper_id) is None:
        raise AppError(404, "PAPER_NOT_FOUND", "Paper not found.")
    documents = (
        await session.scalars(select(Document.id).where(Document.paper_id == paper_id))
    ).all()
    kept = set((await session.scalars(pinned_by_chats(documents))).all())
    deleted = [document for document in documents if document not in kept]
    chats = (
        await session.scalars(
            select(ChatSession)
            .where(ChatSession.id.in_(using_chats(documents)))
            .order_by(ChatSession.created_at, ChatSession.id)
        )
    ).all()
    return PdfRemovalPreview(
        deleted_pdfs=len(deleted),
        kept_pdfs=len(kept),
        summaries=await session.scalar(
            select(func.count())
            .select_from(PaperSummary)
            .where(PaperSummary.document_id.in_(deleted))
        ),
        chats=[ChatLink(id=chat.id, title=chat.title) for chat in chats],
        active_jobs=await session.scalar(
            select(func.count()).select_from(related_jobs([], deleted, []).subquery())
        ),
        answering=bool(chats) and await session.scalar(select(answering([c.id for c in chats]))),
    )


async def remove_pdfs(session, paper_id: UUID) -> None:
    """Detach the paper's current PDF and delete its PDFs that no chat pins; a repeat changes
    nothing."""
    from app.services.chat import expire
    from app.services.upload_match import pending_lock_key

    if await session.get(Paper, paper_id) is None:
        raise AppError(404, "PAPER_NOT_FOUND", "Paper not found.")
    owned = select(Document.id).where(Document.paper_id == paper_id)
    # Uploads, retrievals and match decisions for this paper wait for the removal.
    await identity_locks(session, [pending_lock_key(paper_id)])
    await lock_pdfs(session, (await session.scalars(owned)).all())
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
    if paper.active_document_id is not None:
        paper.active_document_id = None
        paper.updated_at = now()
    await delete_detached(session, (await session.scalars(owned)).all())
