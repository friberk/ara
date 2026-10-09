"""Long jobs yield their lease without spending retry attempts (ARA-071, ARA-072)."""

import pytest
from sqlalchemy import func, select

from app.models.jobs import BackgroundJob, JobOutbox
from app.repositories.jobs import claim, enqueue, fence

pytestmark = pytest.mark.integration


async def claimed_job(resources):
    async with resources.sessions() as session, session.begin():
        job = await enqueue(session, kind="embed", payload={"index_id": "fixture"})
        identifier = job.id
    token = await claim(resources.sessions, identifier, 1)
    assert token is not None
    return identifier, token


async def test_given_claimed_job_when_continuing_then_next_generation_is_queued_without_attempts(
    resources,
):
    from app.repositories.jobs import continue_locked

    identifier, token = await claimed_job(resources)
    async with resources.sessions() as session, session.begin():
        job = await session.scalar(
            select(BackgroundJob).where(*fence(identifier, 1, token)).with_for_update()
        )
        continue_locked(session, job, stage="embedding", progress=40)
    async with resources.sessions() as session:
        job = await session.get(BackgroundJob, identifier)
        assert (job.state, job.stage, job.progress) == ("queued", "embedding", 40)
        assert job.generation == 2 and job.attempts == 0
        assert job.lease_token is None and job.lease_expires_at is None
        assert job.available_at <= await session.scalar(select(func.now()))
        outbox = (
            await session.scalars(select(JobOutbox).where(JobOutbox.job_id == identifier))
        ).all()
        assert sorted(row.generation for row in outbox) == [1, 2]


async def test_given_continued_job_when_stale_generation_claims_then_it_is_rejected(resources):
    from app.repositories.jobs import continue_locked

    identifier, token = await claimed_job(resources)
    async with resources.sessions() as session, session.begin():
        job = await session.scalar(
            select(BackgroundJob).where(*fence(identifier, 1, token)).with_for_update()
        )
        continue_locked(session, job, stage="embedding", progress=10)
    assert await claim(resources.sessions, identifier, 1) is None
    fresh = await claim(resources.sessions, identifier, 2)
    assert fresh is not None and fresh != token
    async with resources.sessions() as session:
        assert (await session.get(BackgroundJob, identifier)).attempts == 1
