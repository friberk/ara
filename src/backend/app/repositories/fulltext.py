"""Persisted full-text state; reads never contact a provider or PDF host."""

from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.core.errors import AppError
from app.models.fulltext import FullTextAttempt, FullTextRequest
from app.models.jobs import BackgroundJob
from app.models.research import Document, Paper, PaperSource
from app.repositories.jobs import enqueue, fence, job_statuses
from app.repositories.papers import identity_locks
from app.schemas.fulltext import (
    DownloadResult,
    FullTextAccepted,
    FullTextAttemptView,
    FullTextCandidate,
    FullTextStatus,
)
from app.schemas.research import SearchResult


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


async def record_attempt(
    session,
    *,
    job_id: UUID,
    generation: int,
    lease_token: UUID,
    ordinal: int,
    candidate: FullTextCandidate,
    result: DownloadResult,
) -> bool:
    owned = await session.scalar(
        select(BackgroundJob).where(*fence(job_id, generation, lease_token)).with_for_update()
    )
    if owned is None:
        return False
    await session.execute(
        insert(FullTextAttempt)
        .values(
            id=uuid4(),
            job_id=job_id,
            generation=generation,
            ordinal=ordinal,
            provider=candidate.provider,
            candidate=candidate.model_dump(mode="json"),
            response_status=result.response_status,
            outcome=result.outcome,
            reason=result.reason[:400],
        )
        .on_conflict_do_nothing(constraint="uq_fulltext_attempt")
    )
    return True


async def fulltext_status(session, paper_id: UUID) -> FullTextStatus:
    paper = await session.get(Paper, paper_id)
    if paper is None:
        raise AppError(404, "PAPER_NOT_FOUND", "Paper not found.")
    sources = list(
        (await session.scalars(select(PaperSource).where(PaperSource.paper_id == paper_id))).all()
    )
    snapshots = [SearchResult.model_validate(item.metadata_snapshot) for item in sources]
    locations = [location for source in snapshots for location in source.locations][:32]
    availability = (
        "open_copy_reported"
        if any(
            source.is_open_access is True
            or any(location.is_oa is True for location in source.locations)
            for source in snapshots
        )
        else "publisher_link_only"
        if any(source.external_url or source.doi or source.pdf_url for source in snapshots)
        else "unknown"
    )
    job = await session.scalar(
        select(BackgroundJob)
        .where(
            BackgroundJob.kind == "fulltext",
            BackgroundJob.payload["paper_id"].astext == str(paper_id),
        )
        .order_by(BackgroundJob.created_at.desc())
        .limit(1)
    )
    attempts = (
        list(
            (
                await session.scalars(
                    select(FullTextAttempt)
                    .where(FullTextAttempt.job_id == job.id)
                    .order_by(FullTextAttempt.generation, FullTextAttempt.ordinal)
                    .limit(24)
                )
            ).all()
        )
        if job
        else []
    )
    document = (
        await session.get(Document, paper.active_document_id) if paper.active_document_id else None
    )
    return FullTextStatus(
        paper_id=paper_id,
        availability=availability,
        locations=locations,
        retrieval_job=(await job_statuses(session, [job]))[0] if job else None,
        document_id=document.id if document else None,
        ingest_job_id=document.ingest_job_id if document else None,
        last_checked_at=attempts[-1].checked_at if attempts else job.updated_at if job else None,
        acquisition=document.acquisition if document else None,
        attempts=[
            FullTextAttemptView(
                provider=item.provider,
                source_label=item.candidate["source_label"],
                version=item.candidate["location"].get("version"),
                is_oa=item.candidate["location"].get("is_oa"),
                license=item.candidate["location"].get("license"),
                response_status=item.response_status,
                outcome=item.outcome,
                reason=item.reason,
                checked_at=item.checked_at,
            )
            for item in attempts
        ],
    )
