"""Run the durable storage cleanup that paper deletion queues (ARA-095)."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update

from app.models.jobs import BackgroundJob


async def cleanup_job(resources) -> BackgroundJob | None:
    async with resources.sessions() as session:
        return await session.scalar(
            select(BackgroundJob)
            .where(BackgroundJob.kind == "storage_cleanup")
            .order_by(BackgroundJob.created_at.desc())
            .limit(1)
        )


async def run_cleanup(resources) -> BackgroundJob:
    """Claim and run the latest cleanup job as the worker would, skipping any scheduled wait."""
    from app.repositories.jobs import claim
    from app.services.deletion import run_storage_cleanup_job

    job = await cleanup_job(resources)
    async with resources.sessions() as session, session.begin():
        await session.execute(
            update(BackgroundJob)
            .where(BackgroundJob.id == job.id)
            .values(available_at=datetime.now(UTC) - timedelta(seconds=1))
        )
    token = await claim(resources.sessions, job.id, job.generation)
    assert token is not None
    await run_storage_cleanup_job(resources, job.id, job.generation, token, job.payload)
    return await cleanup_job(resources)
