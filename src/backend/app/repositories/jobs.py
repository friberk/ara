import random
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import func, select, update

from app.models.jobs import BackgroundJob, JobOutbox


def now() -> datetime:
    return datetime.now(UTC)


async def enqueue(session, *, kind: str, payload: dict) -> BackgroundJob:
    job = BackgroundJob(kind=kind, payload=payload, state="queued", generation=1)
    session.add(job)
    await session.flush()
    session.add(JobOutbox(job_id=job.id, generation=job.generation))
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


def retry_locked(session, job: BackgroundJob, *, code: str, message: str) -> None:
    job.lease_token = None
    job.lease_expires_at = None
    job.updated_at = now()
    job.error_code, job.error_message = code, message
    if job.attempts >= 3:
        job.state, job.stage = "failed", "failed"
        return
    job.state, job.stage = "queued", "retry_wait"
    job.generation += 1
    job.available_at = now() + timedelta(seconds=2**job.attempts + random.uniform(0, 1))
    session.add(JobOutbox(job_id=job.id, generation=job.generation, available_at=job.available_at))


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
        return True


async def recover(sessions) -> None:
    async with sessions() as session, session.begin():
        expired = (
            await session.scalars(
                select(BackgroundJob)
                .where(
                    BackgroundJob.state == "processing",
                    BackgroundJob.lease_expires_at <= func.now(),
                )
                .with_for_update(skip_locked=True)
                .limit(100)
            )
        ).all()
        for job in expired:
            retry_locked(
                session, job, code="LEASE_EXPIRED", message="Worker lease expired; recovering."
            )
            await mark_terminal_document(session, job)
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
