"""A failed section-summary job is revived at startup, at most three times (ARA-105)."""

import asyncio
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select
from test_section_summaries_integration import (
    hosted,
    queue,
    save_defaults,
    section_jobs,
)

from app.models.jobs import BackgroundJob, JobOutbox
from tests.support.sections import seed_sections

pytestmark = pytest.mark.integration


async def failed_job(resources, *, revivals=None, model="gpt-5.6-luna", effort="low"):
    """A ready PDF whose only section-summary job ran out of attempts."""
    from app.rag.chunking import CHUNK_SET

    hosted(resources)
    await save_defaults(resources, model, effort)
    _, document_id, _ = await seed_sections(resources, chunk_set=CHUNK_SET)
    job = await queue(resources, document_id)
    async with resources.sessions() as session, session.begin():
        row = await session.get(BackgroundJob, job.id)
        row.state, row.stage, row.attempts = "failed", "failed", 3
        row.error_code, row.updated_at = "LEASE_EXPIRED", datetime.now(UTC)
        if revivals is not None:
            row.payload = {**row.payload, "revivals": revivals}
    return document_id, job


async def backfill(resources) -> int:
    from app.services.section_summaries import backfill_section_summaries

    return await backfill_section_summaries(resources)


async def test_given_a_failed_job_when_the_api_starts_then_it_is_revived_with_the_current_default(
    resources,
):
    _, failed = await failed_job(resources)
    await save_defaults(resources, "gpt-5.6-luna", "high")

    assert await backfill(resources) == 1

    (job,) = await section_jobs(resources)
    assert job.id == failed.id
    assert (job.state, job.attempts, job.generation) == ("queued", 0, failed.generation + 1)
    assert job.payload["revivals"] == 1
    assert (job.payload["model"], job.payload["reasoning_effort"]) == ("gpt-5.6-luna", "high")
    async with resources.sessions() as session:
        assert await session.scalar(
            select(JobOutbox.id).where(
                JobOutbox.job_id == job.id,
                JobOutbox.generation == job.generation,
                JobOutbox.delivered_at.is_(None),
            )
        )
    assert await backfill(resources) == 0  # now queued: nothing changes


async def test_given_three_revivals_when_the_api_starts_again_then_nothing_is_queued(resources):
    _, failed = await failed_job(resources, revivals=3)
    assert await backfill(resources) == 0
    (job,) = await section_jobs(resources)
    assert (job.state, job.generation, job.payload["revivals"]) == ("failed", failed.generation, 3)


async def test_given_a_default_that_cannot_summarize_then_the_job_and_counter_stay(resources):
    _, failed = await failed_job(resources, revivals=1)
    resources.settings.openai_api_key = None  # the saved default can no longer run
    assert await backfill(resources) == 0
    (job,) = await section_jobs(resources)
    assert (job.state, job.generation, job.payload["revivals"]) == ("failed", failed.generation, 1)


async def test_given_concurrent_startups_then_a_failed_job_is_revived_once(resources):
    _, failed = await failed_job(resources)
    revived = await asyncio.gather(*(backfill(resources) for _ in range(4)))
    assert sum(revived) == 1
    (job,) = await section_jobs(resources)
    assert job.generation == failed.generation + 1 and job.payload["revivals"] == 1
    async with resources.sessions() as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(JobOutbox)
                .where(JobOutbox.job_id == job.id, JobOutbox.generation == job.generation)
            )
            == 1
        )


async def test_given_older_failed_history_then_only_the_newest_row_is_revived(resources):
    document_id, newest = await failed_job(resources)
    async with resources.sessions() as session, session.begin():
        older = BackgroundJob(
            kind="section_summaries",
            payload=dict(newest.payload),
            state="failed",
            generation=1,
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        session.add(older)
    assert await backfill(resources) == 1
    jobs = {job.id: job for job in await section_jobs(resources)}
    assert jobs[newest.id].state == "queued" and jobs[older.id].state == "failed"


async def test_given_a_queued_or_finished_reading_then_nothing_changes(resources):
    document_id, job = await failed_job(resources)
    async with resources.sessions() as session, session.begin():
        (await session.get(BackgroundJob, job.id)).state = "queued"
    assert await backfill(resources) == 0
    async with resources.sessions() as session, session.begin():
        (await session.get(BackgroundJob, job.id)).state = "completed"
    assert await backfill(resources) == 0
    (row,) = await section_jobs(resources)
    assert (row.state, row.generation) == ("completed", job.generation)
