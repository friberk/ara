import random
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import func, select, update

from app.models.jobs import BackgroundJob, JobOutbox
from app.schemas.jobs import JobStatus

# A storage cleanup that ran out of attempts against an unreachable store is queued again by
# recovery after this wait, at most this many times (ARA-100).
STORAGE_REVIVE_SECONDS = 600
STORAGE_MAX_REVIVALS = 48


def now() -> datetime:
    return datetime.now(UTC)


async def enqueue(session, *, kind: str, payload: dict, delay_seconds: float = 0) -> BackgroundJob:
    # Dispatch and claim both wait for `available_at`, which defaults to the database's now.
    later = {"available_at": now() + timedelta(seconds=delay_seconds)} if delay_seconds else {}
    job = BackgroundJob(kind=kind, payload=payload, state="queued", generation=1, **later)
    session.add(job)
    await session.flush()
    session.add(JobOutbox(job_id=job.id, generation=job.generation, **later))
    await session.flush()
    return job


async def claim(sessions, job_id: UUID, generation: int, lease_seconds: int = 60) -> UUID | None:
    token = uuid4()
    async with sessions() as session, session.begin():
        statement = (
            update(BackgroundJob)
            .where(
                BackgroundJob.id == job_id,
                BackgroundJob.generation == generation,
                BackgroundJob.state == "queued",
                BackgroundJob.attempts < 3,
                BackgroundJob.available_at <= func.now(),
            )
            .values(
                state="processing",
                stage="processing",
                attempts=BackgroundJob.attempts + 1,
                lease_token=token,
                lease_expires_at=now() + timedelta(seconds=lease_seconds),
                updated_at=func.now(),
            )
            .returning(BackgroundJob.id)
        )
        return token if (await session.scalar(statement)) is not None else None


def fence(job_id: UUID, generation: int, token: UUID):
    return (
        BackgroundJob.id == job_id,
        BackgroundJob.generation == generation,
        BackgroundJob.lease_token == token,
        BackgroundJob.state == "processing",
        BackgroundJob.lease_expires_at > func.now(),
    )


async def heartbeat(sessions, job_id, generation, token, lease_seconds=60) -> bool:
    async with sessions() as session, session.begin():
        result = await session.scalar(
            update(BackgroundJob)
            .where(*fence(job_id, generation, token))
            .values(
                lease_expires_at=now() + timedelta(seconds=lease_seconds), updated_at=func.now()
            )
            .returning(BackgroundJob.id)
        )
        return result is not None


async def complete(sessions, job_id, generation, token, result: dict) -> bool:
    async with sessions() as session, session.begin():
        saved = await session.scalar(
            update(BackgroundJob)
            .where(*fence(job_id, generation, token))
            .values(
                state="completed",
                stage="completed",
                progress=100,
                result=result,
                error_code=None,
                error_message=None,
                lease_token=None,
                lease_expires_at=None,
                updated_at=func.now(),
            )
            .returning(BackgroundJob.id)
        )
        return saved is not None


def retry_locked(
    session, job: BackgroundJob, *, code: str, message: str, delay_seconds: float | None = None
) -> None:
    if job.kind in {"model_download", "model_delete"}:
        # Process restarts and lost dispatches do not spend transfer retry attempts.
        from app.repositories.local_models import recovery_operations

        pending = recovery_operations(job.payload)
        if job.runtime_operation_id and job.stage in {"downloading", "pausing"}:
            pending.append(str(job.runtime_operation_id))
        pending = list(dict.fromkeys(pending))
        job.payload = {
            **job.payload,
            "_recovery_operation_ids": pending,
            "recovery_operation_id": pending[0] if pending else None,
        }
        job.lease_token = job.lease_expires_at = None
        job.state, job.stage = "queued", "recovering"
        job.generation += 1
        job.available_at = job.updated_at = now()
        session.add(
            JobOutbox(job_id=job.id, generation=job.generation, available_at=job.available_at)
        )
        return
    job.lease_token = None
    job.lease_expires_at = None
    job.updated_at = now()
    job.error_code, job.error_message = code, message
    if job.attempts >= 3:
        job.state, job.stage = "failed", "failed"
        return
    job.state, job.stage = "queued", "retry_wait"
    job.generation += 1
    if delay_seconds is None:
        delay_seconds = 2**job.attempts + random.uniform(0, 1)
    job.available_at = now() + timedelta(seconds=delay_seconds)
    session.add(JobOutbox(job_id=job.id, generation=job.generation, available_at=job.available_at))


def continue_locked(
    session, job: BackgroundJob, *, stage: str, progress: int, delay_seconds: float = 0
) -> None:
    """Yield a long job's lease to the next generation without spending a retry attempt."""
    job.lease_token = job.lease_expires_at = None
    job.state, job.stage, job.progress = "queued", stage, progress
    job.attempts = 0
    job.generation += 1
    job.updated_at = now()
    job.available_at = job.updated_at + timedelta(seconds=delay_seconds)
    session.add(JobOutbox(job_id=job.id, generation=job.generation, available_at=job.available_at))


async def mark_terminal_index(session, job: BackgroundJob) -> None:
    """An embed job out of attempts leaves its index failed, keeping the provider's error."""
    if job.kind != "embed" or job.state != "failed":
        return
    from app.models.retrieval import RetrievalIndex

    index_id = payload_uuid(job.payload, "index_id")
    if index_id is None:
        return
    await session.execute(
        update(RetrievalIndex)
        .where(RetrievalIndex.id == index_id, RetrievalIndex.job_id == job.id)
        .values(
            state="failed",
            error_code=func.coalesce(RetrievalIndex.error_code, job.error_code),
            error_message=func.coalesce(RetrievalIndex.error_message, job.error_message),
            updated_at=func.now(),
        )
    )


async def mark_terminal_document(session, job: BackgroundJob) -> None:
    if job.kind != "ingest" or job.state != "failed":
        return
    from app.models.research import Document

    try:
        document_id = UUID(job.payload["document_id"])
    except (KeyError, TypeError, ValueError):
        return
    await session.execute(
        update(Document)
        .where(
            Document.id == document_id, Document.ingest_job_id == job.id, Document.status != "ready"
        )
        .values(status="failed", warnings=[job.error_message or "PDF extraction failed."])
    )


async def fail(sessions, job_id, generation, token, *, permanent: bool = False) -> bool:
    async with sessions() as session, session.begin():
        job = await session.scalar(
            select(BackgroundJob).where(*fence(job_id, generation, token)).with_for_update()
        )
        if job is None:
            return False
        if permanent:
            job.state, job.stage = "failed", "failed"
            job.error_code, job.error_message = "INVALID_JOB", "This job type is unsupported."
            job.lease_token, job.lease_expires_at = None, None
            job.updated_at = now()
        else:
            retry_locked(session, job, code="JOB_EXECUTION_FAILED", message="Job execution failed.")
        await mark_terminal_document(session, job)
        await mark_terminal_index(session, job)
        return True


async def recover(sessions, *, open_models: bool = True) -> None:
    statement = select(BackgroundJob).where(
        BackgroundJob.state == "processing", BackgroundJob.lease_expires_at <= func.now()
    )
    if not open_models:
        # Open-model work keeps its unsettled state until the flag is on again (ARA-090).
        from app.integrations.open_models import lane_jobs

        statement = statement.where(~lane_jobs())
    async with sessions() as session, session.begin():
        expired = (
            await session.scalars(statement.with_for_update(skip_locked=True).limit(100))
        ).all()
        for job in expired:
            retry_locked(
                session, job, code="LEASE_EXPIRED", message="Worker lease expired; recovering."
            )
            if job.kind in {"model_download", "model_delete"}:
                from app.models.local_models import ModelInstallation

                installation = await session.get(
                    ModelInstallation, job.model_key, with_for_update=True
                )
                if installation and installation.active_job_id == job.id:
                    installation.state = (
                        "pausing" if installation.desired_state == "paused" else "queued"
                    )
                    installation.updated_at = now()
            await mark_terminal_document(session, job)
            await mark_terminal_index(session, job)
        await revive_storage_cleanups(session)
        # Delivered events can be lost in Redis or remain unclaimed after a worker crash.
        # Redelivery preserves generation and attempts; an atomic claim defeats duplicates.
        await session.execute(
            update(JobOutbox)
            .where(
                JobOutbox.delivered_at < now() - timedelta(seconds=60),
                JobOutbox.job_id.in_(
                    select(BackgroundJob.id).where(BackgroundJob.state == "queued")
                ),
            )
            .values(delivered_at=None)
        )


async def revive_storage_cleanups(session) -> None:
    """Queue storage cleanups that ran out of attempts against an unreachable store again.

    No page offers a retry (ARA-100), so recovery does, or the stored PDFs of deleted papers
    would leak. Only the transient failure qualifies; a refused request fails permanently. Each
    revival waits out a cooldown and counts in the payload, so a store that never answers stops
    being asked. The row lock with skip-locked makes concurrent recoveries revive a job once.
    """
    revivals = func.coalesce(BackgroundJob.payload["revivals"].as_integer(), 0)
    failed = (
        await session.scalars(
            select(BackgroundJob)
            .where(
                BackgroundJob.kind == "storage_cleanup",
                BackgroundJob.state == "failed",
                BackgroundJob.error_code == "STORAGE_UNAVAILABLE",
                BackgroundJob.updated_at <= now() - timedelta(seconds=STORAGE_REVIVE_SECONDS),
                revivals < STORAGE_MAX_REVIVALS,
            )
            .with_for_update(skip_locked=True)
            .limit(100)
        )
    ).all()
    for job in failed:
        requeue_failed_locked(session, job)


def requeue_failed_locked(session, job: BackgroundJob, **payload) -> None:
    """Queue a failed job again in place, counting the revival in its payload.

    Fresh attempts, the next generation and a new outbox event, as a manual retry does. The
    caller holds the row lock; `payload` replaces fields of the job's payload.
    """
    revivals = int(job.payload.get("revivals") or 0) + 1
    job.payload = {**job.payload, **payload, "revivals": revivals}
    job.state, job.stage, job.attempts = "queued", "retry_wait", 0
    job.generation += 1
    job.lease_token = job.lease_expires_at = None
    job.available_at = job.updated_at = now()
    session.add(JobOutbox(job_id=job.id, generation=job.generation, available_at=job.available_at))


def payload_uuid(payload: dict, key: str) -> UUID | None:
    try:
        return UUID(payload[key])
    except (KeyError, TypeError, ValueError):
        return None


async def job_statuses(session, jobs: list[BackgroundJob]) -> list[JobStatus]:
    """Link summary and embed jobs through their payload paper, ingest jobs via their document."""
    from app.models.research import Document, Paper

    documents = {payload_uuid(job.payload, "document_id") for job in jobs if job.kind == "ingest"}
    documents.discard(None)
    document_papers = (
        dict(
            (
                await session.execute(
                    select(Document.id, Document.paper_id).where(Document.id.in_(documents))
                )
            ).all()
        )
        if documents
        else {}
    )

    def linked_paper(job: BackgroundJob) -> UUID | None:
        if job.kind in {"summary", "section_summaries", "fulltext", "embed", "metadata"}:
            return payload_uuid(job.payload, "paper_id")
        if job.kind == "ingest":
            return document_papers.get(payload_uuid(job.payload, "document_id"))
        return None

    paper_of = {job.id: linked_paper(job) for job in jobs}
    papers = set(paper_of.values()) - {None}
    titles = (
        dict(
            (await session.execute(select(Paper.id, Paper.title).where(Paper.id.in_(papers)))).all()
        )
        if papers
        else {}
    )
    statuses = []
    for job in jobs:
        status = JobStatus.model_validate(job)
        paper_id = paper_of.get(job.id)
        # A deleted paper leaves no link rather than one that would 404; a job its deletion
        # stopped still names it (ARA-095).
        if paper_id in titles:
            status.paper_id, status.paper_title = paper_id, titles[paper_id]
        elif isinstance(job.result, dict) and isinstance(job.result.get("paper_title"), str):
            status.paper_title = job.result["paper_title"]
        statuses.append(status)
    return statuses
