"""Persisted full-text state; reads never contact OpenAlex."""

from datetime import timedelta
from uuid import UUID, uuid4, uuid5

from sqlalchemy import exists, select

from app.core.errors import AppError
from app.integrations.openalex_content import MAX_WAIT_SECONDS
from app.models.fulltext import FullTextRequest
from app.models.jobs import BackgroundJob
from app.models.research import Document, Paper, PaperSource
from app.repositories.jobs import enqueue, job_statuses, now
from app.repositories.papers import identity_locks
from app.schemas.fulltext import AutomaticFullText, FullTextAccepted, FullTextStatus

# Each paper has one automatic request identity, so saves, deliveries and restarts replay it.
AUTOMATIC_REQUESTS = UUID("6f1d8a52-3c0e-4f0b-9a57-0d3c5b1e8f84")


def automatic_request_id(paper_id: UUID) -> UUID:
    return uuid5(AUTOMATIC_REQUESTS, str(paper_id))


async def enqueue_automatic(session, paper_id: UUID, *, enabled: bool) -> AutomaticFullText:
    """Start retrieval once for a metadata-only paper with an OpenAlex work or a DOI.

    `enabled` says whether an OpenAlex API key is configured. The paper lock comes first, as
    on save, so concurrent saves and workspace opens queue one job. A paper with any earlier
    attempt keeps manual retries only.
    """
    paper = await session.scalar(select(Paper).where(Paper.id == paper_id).with_for_update())
    if paper is None:
        raise AppError(404, "PAPER_NOT_FOUND", "Paper not found.")
    request_id = automatic_request_id(paper_id)
    existing = await session.get(FullTextRequest, request_id)
    if existing:
        return AutomaticFullText(paper_id=paper_id, job_id=existing.job_id)
    attempted = await session.scalar(
        select(
            exists().where(
                BackgroundJob.kind == "fulltext",
                BackgroundJob.payload["paper_id"].astext == str(paper_id),
            )
        )
    )
    if not enabled or paper.active_document_id or attempted or not await findable(session, paper):
        return AutomaticFullText(paper_id=paper_id, job_id=None)
    accepted = await enqueue_request(session, paper_id, request_id)
    return AutomaticFullText(paper_id=paper_id, job_id=accepted.job_id)


async def findable(session, paper: Paper) -> bool:
    """OpenAlex can find the paper's work: from its saved OpenAlex record, or by DOI."""
    if paper.normalized_doi:
        return True
    return await session.scalar(
        select(exists().where(PaperSource.paper_id == paper.id, PaperSource.provider == "openalex"))
    )


async def enqueue_request(session, paper_id: UUID, request_id: UUID) -> FullTextAccepted:
    await identity_locks(session, [f"fulltext-request:{request_id}"])
    existing = await session.get(FullTextRequest, request_id)
    if existing:
        if existing.paper_id != paper_id:
            raise AppError(
                409, "FULLTEXT_REQUEST_CONFLICT", "This request ID belongs to another paper."
            )
        return FullTextAccepted(paper_id=paper_id, job_id=existing.job_id)
    paper = await session.scalar(select(Paper).where(Paper.id == paper_id).with_for_update())
    if paper is None:
        raise AppError(404, "PAPER_NOT_FOUND", "Paper not found.")
    job = await session.scalar(
        select(BackgroundJob)
        .where(
            BackgroundJob.kind == "fulltext",
            BackgroundJob.payload["paper_id"].astext == str(paper_id),
            BackgroundJob.state.in_(["queued", "processing"]),
        )
        .order_by(BackgroundJob.created_at.desc())
        .limit(1)
    )
    if job is None:
        job = await enqueue(
            session,
            kind="fulltext",
            delay_seconds=await reported_wait(session, paper_id),
            payload={
                "paper_id": str(paper_id),
                "expected_active_document_id": str(paper.active_document_id)
                if paper.active_document_id
                else None,
                "attachment_request_id": str(uuid4()),
            },
        )
    session.add(FullTextRequest(request_id=request_id, paper_id=paper_id, job_id=job.id))
    await session.flush()
    return FullTextAccepted(paper_id=paper_id, job_id=job.id)


async def reported_wait(session, paper_id: UUID) -> float:
    """Seconds left of the wait a rate-limited source reported for this paper's last attempt."""
    last = await session.scalar(
        select(BackgroundJob)
        .where(
            BackgroundJob.kind == "fulltext",
            BackgroundJob.payload["paper_id"].astext == str(paper_id),
        )
        .order_by(BackgroundJob.created_at.desc())
        .limit(1)
    )
    result = (last.result or {}) if last else {}
    if result.get("outcome") != "rate_limited" or not isinstance(result.get("retry_after"), int):
        return 0
    ends = last.updated_at + timedelta(seconds=min(MAX_WAIT_SECONDS, max(0, result["retry_after"])))
    return max(0.0, (ends - now()).total_seconds())


async def fulltext_status(session, paper_id: UUID, *, api_key_configured: bool) -> FullTextStatus:
    paper = await session.get(Paper, paper_id)
    if paper is None:
        raise AppError(404, "PAPER_NOT_FOUND", "Paper not found.")
    job = await session.scalar(
        select(BackgroundJob)
        .where(
            BackgroundJob.kind == "fulltext",
            BackgroundJob.payload["paper_id"].astext == str(paper_id),
        )
        .order_by(BackgroundJob.created_at.desc())
        .limit(1)
    )
    document = (
        await session.get(Document, paper.active_document_id) if paper.active_document_id else None
    )
    return FullTextStatus(
        paper_id=paper_id,
        api_key_configured=api_key_configured,
        retrieval_job=(await job_statuses(session, [job]))[0] if job else None,
        document_id=document.id if document else None,
        ingest_job_id=document.ingest_job_id if document else None,
        acquisition=document.acquisition if document else None,
    )
