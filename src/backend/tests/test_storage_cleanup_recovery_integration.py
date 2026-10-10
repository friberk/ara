"""A storage cleanup that failed its attempts is revived by recovery, never by a page (ARA-100)."""

import asyncio
import io
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from minio.error import S3Error
from sqlalchemy import func, select, update
from test_paper_deletion_integration import client_for
from test_paper_deletion_storage_integration import storage_down, stored, uploaded

from app.models.jobs import BackgroundJob, JobOutbox
from app.models.research import Document
from app.repositories.jobs import STORAGE_MAX_REVIVALS, STORAGE_REVIVE_SECONDS, recover
from tests.support.cleanup import cleanup_job, run_cleanup

pytestmark = pytest.mark.integration


async def failed_cleanup(resources, *, age: float = STORAGE_REVIVE_SECONDS + 1, revivals=None):
    """A deleted paper whose cleanup ran out of attempts against an unreachable store."""
    paper, key = await uploaded(resources, "Deleted")
    async with client_for(resources) as client:
        await client.delete(f"/api/v1/papers/{paper}")
    with storage_down(resources):
        for _ in range(3):
            job = await run_cleanup(resources)
    assert (job.state, job.error_code) == ("failed", "STORAGE_UNAVAILABLE")
    async with resources.sessions() as session, session.begin():
        row = await session.get(BackgroundJob, job.id)
        row.updated_at = datetime.now(UTC) - timedelta(seconds=age)
        if revivals is not None:
            row.payload = {**row.payload, "revivals": revivals}
    return key, await cleanup_job(resources)


async def test_recovery_requeues_a_failed_cleanup_and_the_pdf_is_removed(resources):
    """Given a cleanup that failed after its attempts, when recovery runs, then the job is queued
    again with a fresh generation and outbox event, and running it removes the stored PDF."""
    key, failed = await failed_cleanup(resources)
    assert await stored(resources, key)

    await recover(resources.sessions)

    revived = await cleanup_job(resources)
    assert (revived.state, revived.attempts) == ("queued", 0)
    assert revived.generation == failed.generation + 1
    assert revived.payload["revivals"] == 1
    async with resources.sessions() as session:
        assert await session.scalar(
            select(JobOutbox.id).where(
                JobOutbox.job_id == failed.id,
                JobOutbox.generation == revived.generation,
                JobOutbox.delivered_at.is_(None),
            )
        )
    assert (await run_cleanup(resources)).state == "completed"
    assert not await stored(resources, key)


async def test_a_recent_failure_waits_out_the_cooldown(resources):
    _, failed = await failed_cleanup(resources, age=1)
    await recover(resources.sessions)
    assert (await cleanup_job(resources)).generation == failed.generation


async def test_concurrent_recoveries_requeue_a_failed_cleanup_once(resources):
    _, failed = await failed_cleanup(resources)
    await asyncio.gather(*(recover(resources.sessions) for _ in range(4)))
    revived = await cleanup_job(resources)
    assert revived.generation == failed.generation + 1 and revived.payload["revivals"] == 1
    async with resources.sessions() as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(JobOutbox)
                .where(JobOutbox.job_id == failed.id, JobOutbox.generation == revived.generation)
            )
            == 1
        )


async def test_a_cleanup_stops_being_revived_after_its_cap(resources):
    """Given a store that never recovers, then revival is bounded rather than endless."""
    _, failed = await failed_cleanup(resources, revivals=STORAGE_MAX_REVIVALS)
    await recover(resources.sessions)
    assert (await cleanup_job(resources)).state == "failed"


async def test_a_rejected_removal_fails_at_once_and_is_not_revived(resources):
    """Given storage refusing the request (a permanent error), then the job fails on its first
    attempt with its own code and recovery leaves it alone."""
    paper, key = await uploaded(resources, "Deleted")
    async with client_for(resources) as client:
        await client.delete(f"/api/v1/papers/{paper}")

    def refused(*_args, **_kwargs):
        raise S3Error(SimpleNamespace(status=403), "AccessDenied", "Access Denied.", "/", "r", "h")

    resources.storage.remove_object = refused
    try:
        job = await run_cleanup(resources)
    finally:
        del resources.storage.remove_object
    assert (job.state, job.attempts, job.error_code) == ("failed", 1, "STORAGE_REJECTED")
    async with resources.sessions() as session, session.begin():
        await session.execute(
            update(BackgroundJob)
            .where(BackgroundJob.id == job.id)
            .values(updated_at=datetime.now(UTC) - timedelta(days=1))
        )
    await recover(resources.sessions)
    assert (await cleanup_job(resources)).state == "failed"
    assert await stored(resources, key)


async def test_a_cleanup_queued_by_removing_a_detached_pdf_is_revived_too(resources):
    """Given a detached PDF deleted through pdf_removal (ARA-097) whose cleanup failed, then
    recovery queues it again and the object is removed."""
    from app.services.pdf_removal import delete_detached

    paper, _ = await uploaded(resources, "Live")
    key = f"originals/{uuid4()}.pdf"
    async with resources.sessions() as session, session.begin():
        document = Document(
            paper_id=paper,
            status="ready",
            object_key=key,
            sha256=uuid4().hex + uuid4().hex,
            original_filename="older.pdf",
            byte_size=10,
            request_id=uuid4(),
        )
        session.add(document)
        await session.flush()
        assert await delete_detached(session, [document.id]) == [document.id]
    await resources.storage_call(
        resources.storage.put_object, resources.settings.minio_bucket, key, io.BytesIO(b"x"), 1
    )
    with storage_down(resources):
        for _ in range(3):
            failed = await run_cleanup(resources)
    assert (failed.state, failed.error_code) == ("failed", "STORAGE_UNAVAILABLE")
    async with resources.sessions() as session, session.begin():
        (await session.get(BackgroundJob, failed.id)).updated_at = datetime.now(UTC) - timedelta(
            seconds=STORAGE_REVIVE_SECONDS + 1
        )

    await recover(resources.sessions)

    assert (await run_cleanup(resources)).state == "completed"
    assert not await stored(resources, key)
