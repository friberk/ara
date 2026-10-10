"""Deleting papers from the library (ARA-095).

One transaction removes the papers. Foreign keys cascade to their PDFs (documents), pages,
passages, sections, embeddings, indexes, summaries, authors, provider records, PDF retrieval
requests, upload matches and redirects, and clear `documents.doi_owner_paper_id`. The trigger
`chat_papers_last_paper` deletes a chat once its last paper goes; a chat that also covers other
papers keeps them, and its saved citations still read (they name no paper any more).

The same transaction:
- refuses while a chat about these papers is writing an answer (409 CHAT_BUSY);
- settles the papers' queued and running jobs as failed with PAPER_DELETED. That fences their
  workers out, so nothing they finish later is written. A job whose row is locked at that moment
  is skipped; it finds its paper gone when it next writes and settles itself;
- lets an upload that waits for a decision about a deleted library paper go on as its own paper;
- queues one durable `storage_cleanup` job for the stored PDFs. Storage is never called inline,
  and a storage outage retries without bringing any row back.

Locks are taken in the order the rest of the app uses: identity locks, then chats, then papers.
"""

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import delete, exists, func, or_, select

from app.core.errors import AppError
from app.models.jobs import BackgroundJob
from app.models.research import (
    ChatMessage,
    ChatPaper,
    ChatSession,
    Document,
    Paper,
    PaperSource,
    PaperSummary,
    UploadMatch,
)
from app.repositories.jobs import complete, enqueue, fence, now, payload_uuid, retry_locked
from app.repositories.papers import identity_locks
from app.schemas.research import ChatLink, DeletionPreview, PaperLink

PAPER_DELETED = "PAPER_DELETED"
STOPPED = "Stopped because the paper was deleted."
STORAGE_CLEANUP = "storage_cleanup"
# An upload commits its document before it stores the object, and its ingest job waits 120 s
# for that (services/uploads.py). Cleanup of a PDF still uploading waits longer, so the object
# it stores late is removed too.
UPLOADING_DELAY_SECONDS = 300
STORAGE_RETRY_SECONDS = 30


def related_jobs(paper_ids, document_ids, chat_ids):
    """Queued or running jobs about these papers, their PDFs or the chats that go with them."""

    def text(values):
        return [str(value) for value in values]

    return select(BackgroundJob).where(
        BackgroundJob.state.in_(("queued", "processing")),
        or_(
            BackgroundJob.payload["paper_id"].astext.in_(text(paper_ids)),
            BackgroundJob.payload["document_id"].astext.in_(text(document_ids)),
            BackgroundJob.payload["chat_id"].astext.in_(text(chat_ids)),
        ),
    )


async def chat_effects(session, paper_ids) -> tuple[list[ChatSession], list[ChatSession]]:
    """Chats that go with these papers, and chats that keep other papers."""
    links = (
        await session.execute(
            select(ChatPaper.chat_id, ChatPaper.paper_id).where(
                ChatPaper.chat_id.in_(
                    select(ChatPaper.chat_id).where(ChatPaper.paper_id.in_(paper_ids))
                )
            )
        )
    ).all()
    if not links:
        return [], []
    others = {chat_id for chat_id, paper_id in links if paper_id not in set(paper_ids)}
    chats = (
        await session.scalars(
            select(ChatSession)
            .where(ChatSession.id.in_({chat_id for chat_id, _ in links}))
            .order_by(ChatSession.created_at, ChatSession.id)
        )
    ).all()
    return [c for c in chats if c.id not in others], [c for c in chats if c.id in others]


def answering(chat_ids):
    return exists().where(
        ChatMessage.session_id.in_(chat_ids),
        ChatMessage.role == "assistant",
        ChatMessage.state == "processing",
        ChatMessage.lease_expires_at > func.now(),
    )


async def deletion_preview(session, paper_ids: Sequence[UUID]) -> DeletionPreview:
    requested = list(dict.fromkeys(paper_ids))
    papers = (
        await session.execute(
            select(Paper.id, Paper.title).where(Paper.id.in_(requested)).order_by(Paper.created_at)
        )
    ).all()
    found = [paper_id for paper_id, _ in papers]
    # A PDF already removed from its paper (ARA-097) holds no file or text, so it is not counted.
    documents = (
        await session.scalars(
            select(Document.id).where(Document.paper_id.in_(found), ~Document.removed)
        )
    ).all()
    deleted, updated = await chat_effects(session, found)
    chats = [chat.id for chat in deleted + updated]
    return DeletionPreview(
        papers=[PaperLink(paper_id=paper_id, title=title) for paper_id, title in papers],
        missing=[paper_id for paper_id in requested if paper_id not in set(found)],
        pdfs=len(documents),
        summaries=await session.scalar(
            select(func.count()).select_from(PaperSummary).where(PaperSummary.paper_id.in_(found))
        ),
        deleted_chats=[ChatLink(id=chat.id, title=chat.title) for chat in deleted],
        updated_chats=[ChatLink(id=chat.id, title=chat.title) for chat in updated],
        active_jobs=await session.scalar(
            select(func.count()).select_from(
                related_jobs(found, documents, [chat.id for chat in deleted]).subquery()
            )
        ),
        answering=bool(chats) and await session.scalar(select(answering(chats))),
    )


async def identity_keys(session, paper_ids) -> list[str]:
    """The identity locks that saving, uploading, attaching and lookups take for these papers."""
    from app.services.upload_match import pending_lock_key

    dois = await session.scalars(
        select(Paper.normalized_doi).where(
            Paper.id.in_(paper_ids), Paper.normalized_doi.is_not(None)
        )
    )
    sources = await session.execute(
        select(PaperSource.provider, PaperSource.external_id).where(
            PaperSource.paper_id.in_(paper_ids)
        )
    )
    digests = await session.scalars(select(Document.sha256).where(Document.paper_id.in_(paper_ids)))
    # Uploads waiting for a decision about these papers, so attach and cancel wait for this.
    placeholders = await session.scalars(
        select(UploadMatch.placeholder_paper_id).where(UploadMatch.library_paper_id.in_(paper_ids))
    )
    return [
        *(pending_lock_key(paper_id) for paper_id in [*paper_ids, *placeholders.all()]),
        *(f"doi:{doi}" for doi in dois.all()),
        *(f"source:{provider}:{external_id}" for provider, external_id in sources.all()),
        *(f"pdf:{digest}" for digest in digests.all()),
    ]


async def settle_jobs(session, paper_ids, documents, chat_ids, titles: dict[UUID, str | None]):
    """Fail the papers' queued and running jobs with PAPER_DELETED, fencing their workers out.

    A row locked by a worker's own transaction is skipped rather than waited for, so this never
    deadlocks with a job that holds its row and waits for these papers.
    """
    paper_of = {document_id: paper_id for document_id, paper_id in documents}
    jobs = (
        await session.scalars(
            related_jobs(paper_ids, paper_of, chat_ids).with_for_update(skip_locked=True)
        )
    ).all()
    for job in jobs:
        paper = payload_uuid(job.payload, "paper_id") or paper_of.get(
            payload_uuid(job.payload, "document_id")
        )
        settle_deleted_locked(job, title=titles.get(paper))


def settle_deleted_locked(job: BackgroundJob, *, title: str | None = None) -> None:
    """Fail a locked job whose paper is gone; Activity names the paper without linking it."""
    job.state = job.stage = "failed"
    job.error_code, job.error_message = PAPER_DELETED, STOPPED
    job.result = {"outcome": "paper_deleted", "paper_title": title}
    job.lease_token = job.lease_expires_at = None
    job.updated_at = now()


async def release_uploads(session, resources, paper_ids) -> None:
    """An upload held because it matched a deleted library paper goes on as its own paper."""
    from app.services.upload_match import continue_upload

    rows = (
        await session.scalars(
            select(UploadMatch)
            .where(
                UploadMatch.library_paper_id.in_(paper_ids),
                UploadMatch.placeholder_paper_id.not_in(paper_ids),
            )
            .order_by(UploadMatch.placeholder_paper_id)
            .with_for_update()
        )
    ).all()
    for row in rows:
        document = await session.scalar(
            select(Document).where(Document.id == row.document_id).with_for_update()
        )
        await session.delete(row)
        await session.flush()
        if document is not None:
            await continue_upload(session, resources, document)


async def delete_papers(
    session, resources, paper_ids: Sequence[UUID]
) -> tuple[list[UUID], list[UUID]]:
    """Delete the papers that exist; returns (deleted, missing), each in request order."""
    from app.services.chat import expire

    requested = list(dict.fromkeys(paper_ids))
    await identity_locks(session, await identity_keys(session, requested))
    chat_ids = (
        await session.scalars(
            select(ChatSession.id)
            .where(
                ChatSession.id.in_(
                    select(ChatPaper.chat_id).where(ChatPaper.paper_id.in_(requested))
                )
            )
            .order_by(ChatSession.id)
            .with_for_update()
        )
    ).all()
    for chat_id in chat_ids:
        await expire(session, chat_id)
    if chat_ids and await session.scalar(select(answering(chat_ids))):
        raise AppError(409, "CHAT_BUSY", "Wait for the current answer to finish before deleting.")
    papers = (
        await session.scalars(
            select(Paper)
            .where(Paper.id.in_(requested))
            .order_by(Paper.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).all()
    titles = {paper.id: paper.title for paper in papers}
    deleted = [paper_id for paper_id in requested if paper_id in titles]
    missing = [paper_id for paper_id in requested if paper_id not in titles]
    if not deleted:
        return deleted, missing
    documents = (
        await session.execute(
            select(Document.id, Document.paper_id, Document.object_key, Document.status).where(
                Document.paper_id.in_(deleted)
            )
        )
    ).all()
    gone_chats, _ = await chat_effects(session, deleted)
    await settle_jobs(
        session,
        deleted,
        [(row.id, row.paper_id) for row in documents],
        [chat.id for chat in gone_chats],
        titles,
    )
    await release_uploads(session, resources, deleted)
    await queue_storage_cleanup(
        session, documents, paper_titles=[titles[paper_id] for paper_id in deleted]
    )
    await session.execute(delete(Paper).where(Paper.id.in_(deleted)))
    return deleted, missing


async def queue_storage_cleanup(
    session, documents: Sequence, *, paper_titles: Sequence[str | None] = ()
) -> BackgroundJob | None:
    """Queue removal of these documents' stored PDFs in the caller's transaction, which also
    deletes their rows; nothing when there are none.

    Deleting papers uses it, and so can removing a single PDF. Each item needs `object_key` and
    `status`; a PDF still uploading waits out the upload grace first.
    """
    if not documents:
        return None
    uploading = any(document.status == "uploading" for document in documents)
    return await enqueue(
        session,
        kind=STORAGE_CLEANUP,
        payload={
            "object_keys": sorted(document.object_key for document in documents),
            "paper_titles": list(paper_titles),
        },
        delay_seconds=UPLOADING_DELAY_SECONDS if uploading else 0,
    )


async def run_storage_cleanup_job(resources, job_id, generation, token, payload) -> None:
    """Remove deleted papers' stored PDFs. Removing a missing object succeeds, so a repeat is a
    no-op; an object a live document still names is kept."""
    keys = [key for key in payload.get("object_keys") or [] if isinstance(key, str)]
    async with resources.sessions() as session:
        if await session.scalar(select(BackgroundJob.id).where(*fence(job_id, generation, token))):
            # Keys are per document (`originals/<document>.pdf`), so this guards a key reused
            # by a row that still exists, never an object two papers share.
            kept = set(
                (
                    await session.scalars(
                        select(Document.object_key).where(Document.object_key.in_(keys))
                    )
                ).all()
            )
        else:
            return  # A duplicate or stale delivery holds no lease and removes nothing.
    try:
        for key in keys:
            if key not in kept:
                await resources.storage_call(
                    resources.storage.remove_object, resources.settings.minio_bucket, key
                )
    except Exception:
        async with resources.sessions() as session, session.begin():
            job = await session.scalar(
                select(BackgroundJob).where(*fence(job_id, generation, token)).with_for_update()
            )
            if job is not None:
                retry_locked(
                    session,
                    job,
                    code="STORAGE_UNAVAILABLE",
                    message="Storage is unavailable, so the deleted PDFs are not removed yet.",
                    delay_seconds=STORAGE_RETRY_SECONDS * 2 ** max(0, job.attempts - 1),
                )
        return
    await complete(
        resources.sessions,
        job_id,
        generation,
        token,
        {"removed": len([key for key in keys if key not in kept]), "kept": len(kept)},
    )
