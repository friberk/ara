"""The worker's dispatch of a job: crashes, unknown kinds, repeats and leases.

Drives the real `execute_job` against PostgreSQL; only a job's own handler is replaced where a
test needs it to crash or to wait.
"""

import asyncio
import io
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from minio.error import S3Error
from sqlalchemy import func, select, update
from support.front_matter import toolchain_pdf

from app.models.jobs import BackgroundJob, JobOutbox
from app.models.research import Document
from app.repositories.jobs import claim, complete, enqueue, recover

pytestmark = pytest.mark.integration


@pytest.fixture
def execute(resources, monkeypatch):
    from app.jobs import actors

    monkeypatch.setattr(actors, "_resources", resources)
    return actors.execute_job.fn.__wrapped__


async def queued(resources, kind="summary", payload=None):
    async with resources.sessions() as session, session.begin():
        job = await enqueue(session, kind=kind, payload=payload or {})
        return job.id


async def row(resources, job_id) -> BackgroundJob:
    async with resources.sessions() as session:
        return await session.get(BackgroundJob, job_id)


async def make_due(resources, job_id) -> None:
    """Skip the retry's backoff, as waiting for it would."""
    async with resources.sessions() as session, session.begin():
        await session.execute(
            update(BackgroundJob)
            .where(BackgroundJob.id == job_id)
            .values(available_at=datetime.now(UTC) - timedelta(seconds=1))
        )


def crashing(monkeypatch, module, name):
    calls = []

    async def crash(*args, **kwargs):
        calls.append(args)
        raise RuntimeError("fixture crash")

    monkeypatch.setattr(module, name, crash)
    return calls


async def test_a_crashing_job_retries_and_fails_on_its_third_attempt(
    resources, execute, monkeypatch
):
    """Given a handler that always crashes, the job is retried twice, then settles as failed."""
    from app.services import summarization

    calls = crashing(monkeypatch, summarization, "run_summary_job")
    job_id = await queued(resources)

    for attempt, generation in enumerate((1, 2), start=1):
        await execute(str(job_id), generation)
        job = await row(resources, job_id)
        assert (job.state, job.stage) == ("queued", "retry_wait")
        assert (job.attempts, job.generation) == (attempt, generation + 1)
        assert job.error_code == "JOB_EXECUTION_FAILED" and job.lease_token is None
        await make_due(resources, job_id)

    await execute(str(job_id), 3)
    job = await row(resources, job_id)
    assert (job.state, job.stage, job.attempts) == ("failed", "failed", 3)
    assert job.error_code == "JOB_EXECUTION_FAILED"
    assert job.lease_token is None and job.lease_expires_at is None
    assert len(calls) == 3


async def test_a_failed_job_is_not_run_again_by_a_late_delivery(resources, execute, monkeypatch):
    from app.services import summarization

    calls = crashing(monkeypatch, summarization, "run_summary_job")
    job_id = await queued(resources)
    for generation in (1, 2, 3):
        await execute(str(job_id), generation)
        await make_due(resources, job_id)
    await execute(str(job_id), 3)
    assert len(calls) == 3 and (await row(resources, job_id)).state == "failed"


async def test_an_upload_whose_ingest_keeps_crashing_ends_failed_not_processing(
    resources, execute, monkeypatch
):
    """Given an ingest that always crashes, the paper's PDF ends failed and is not left waiting."""
    from app.services import ingestion
    from app.services.uploads import ingest_pdf_bytes

    crashing(monkeypatch, ingestion, "run_ingest_job")
    accepted = await ingest_pdf_bytes(
        resources, data=toolchain_pdf(), filename="p.pdf", request_id=uuid4(), paper_id=None
    )
    for generation in (1, 2, 3):
        await execute(str(accepted.job_id), generation)
        await make_due(resources, accepted.job_id)
    async with resources.sessions() as session:
        document = await session.get(Document, accepted.document_id)
    assert document.status == "failed" and document.warnings == ["Job execution failed."]
    assert (await row(resources, accepted.job_id)).state == "failed"


async def test_a_worker_killed_mid_job_cannot_leave_it_processing(resources):
    """Given a worker that dies holding the lease each time, recovery ends with a failed job."""
    job_id = await queued(resources)
    for generation in (1, 2, 3):
        assert await claim(resources.sessions, job_id, generation) is not None
        async with resources.sessions() as session, session.begin():
            await session.execute(
                update(BackgroundJob)
                .where(BackgroundJob.id == job_id)
                .values(lease_expires_at=datetime.now(UTC) - timedelta(seconds=1))
            )
        await recover(resources.sessions, open_models=False)
        await make_due(resources, job_id)
    job = await row(resources, job_id)
    assert (job.state, job.attempts) == ("failed", 3)
    assert job.error_code == "LEASE_EXPIRED" and job.lease_token is None


async def test_an_unknown_job_kind_fails_permanently_on_its_first_attempt(resources, execute):
    job_id = await queued(resources, kind="not-a-real-kind")
    await execute(str(job_id), 1)
    job = await row(resources, job_id)
    assert (job.state, job.stage, job.attempts) == ("failed", "failed", 1)
    assert job.error_code == "INVALID_JOB" and job.generation == 1 and job.lease_token is None
    async with resources.sessions() as session:
        deliveries = await session.scalar(
            select(func.count(JobOutbox.job_id)).where(JobOutbox.job_id == job_id)
        )
    assert deliveries == 1


async def test_a_repeated_delivery_while_running_does_not_run_the_job_twice(
    resources, execute, monkeypatch
):
    """Given a job already running, a second delivery of it returns without calling the handler."""
    from app.services import summarization

    started, release, calls = asyncio.Event(), asyncio.Event(), []

    async def handler(resources, job_id, generation, token, payload):
        calls.append(job_id)
        started.set()
        await release.wait()
        await complete(resources.sessions, job_id, generation, token, {"done": True})

    monkeypatch.setattr(summarization, "run_summary_job", handler)
    job_id = await queued(resources)
    first = asyncio.create_task(execute(str(job_id), 1))
    await asyncio.wait_for(started.wait(), 3)

    await asyncio.wait_for(execute(str(job_id), 1), 3)

    assert len(calls) == 1 and (await row(resources, job_id)).state == "processing"
    release.set()
    await asyncio.wait_for(first, 3)
    assert len(calls) == 1 and (await row(resources, job_id)).state == "completed"


async def test_a_repeated_delivery_after_completion_does_nothing(resources, execute, monkeypatch):
    from app.services import summarization

    calls = []

    async def handler(resources, job_id, generation, token, payload):
        calls.append(job_id)
        await complete(resources.sessions, job_id, generation, token, {"done": True})

    monkeypatch.setattr(summarization, "run_summary_job", handler)
    job_id = await queued(resources)
    await execute(str(job_id), 1)
    await execute(str(job_id), 1)
    assert len(calls) == 1


async def test_a_long_job_keeps_renewing_its_lease(resources, execute, monkeypatch):
    """Given a job that outlasts several heartbeats, its lease is extended each time."""
    from app.services import summarization

    resources.settings.heartbeat_seconds = 0.03
    renewed = []

    async def handler(resources, job_id, generation, token, payload):
        first = (await row(resources, job_id)).lease_expires_at
        latest = first
        async with asyncio.timeout(3):
            while len(renewed) < 3:
                await asyncio.sleep(0.01)
                current = (await row(resources, job_id)).lease_expires_at
                if current > latest:
                    renewed.append(current)
                    latest = current
        await complete(resources.sessions, job_id, generation, token, {"done": True})

    monkeypatch.setattr(summarization, "run_summary_job", handler)
    job_id = await queued(resources)
    await execute(str(job_id), 1)
    assert len(renewed) == 3 and (await row(resources, job_id)).state == "completed"


async def test_storage_cleanup_jobs_reach_their_handler_and_remove_the_file(resources, execute):
    """Given a deleted paper's cleanup job, the worker removes the stored file for real."""
    bucket, key = resources.settings.minio_bucket, f"originals/{uuid4()}.pdf"
    await resources.storage_call(
        resources.storage.put_object, bucket, key, io.BytesIO(b"%PDF-1.7"), 8
    )
    job_id = await queued(resources, kind="storage_cleanup", payload={"object_keys": [key]})
    await execute(str(job_id), 1)
    assert (await row(resources, job_id)).state == "completed"
    with pytest.raises(S3Error) as missing:
        await resources.storage_call(resources.storage.stat_object, bucket, key)
    assert missing.value.code == "NoSuchKey"


async def test_embed_jobs_reach_their_handler_with_the_jobs_lease(resources, execute, monkeypatch):
    from app.rag import indexing

    seen = []

    async def handler(resources, job_id, generation, token, payload):
        seen.append((job_id, generation, token is not None, payload))
        await complete(resources.sessions, job_id, generation, token, {"done": True})

    monkeypatch.setattr(indexing, "run_embed_job", handler)
    payload = {"index_id": str(uuid4())}
    job_id = await queued(resources, kind="embed", payload=payload)
    await execute(str(job_id), 1)
    assert seen == [(job_id, 1, True, payload)]
    assert (await row(resources, job_id)).state == "completed"


async def test_a_first_crash_leaves_the_upload_in_progress_and_the_retry_rescues_it(
    resources, execute, monkeypatch
):
    """Given an ingest that crashes once, the PDF is not shown as failed while a retry is coming."""
    from app.repositories.papers import paper_detail
    from app.services import ingestion
    from app.services.uploads import ingest_pdf_bytes

    real = ingestion.run_ingest_job
    calls = []

    async def crashes_once(*args, **kwargs):
        calls.append(args)
        if len(calls) == 1:
            raise RuntimeError("fixture crash")
        return await real(*args, **kwargs)

    monkeypatch.setattr(ingestion, "run_ingest_job", crashes_once)
    accepted = await ingest_pdf_bytes(
        resources, data=toolchain_pdf(), filename="p.pdf", request_id=uuid4(), paper_id=None
    )

    async def facts():
        async with resources.sessions() as session:
            document = await session.get(Document, accepted.document_id)
            paper = await paper_detail(session, accepted.paper_id)
        return document.status, document.warnings, paper.document_status

    before = await facts()
    await execute(str(accepted.job_id), 1)

    assert (await row(resources, accepted.job_id)).state == "queued"
    assert await facts() == before and before[2] == "processing"

    await make_due(resources, accepted.job_id)
    await execute(str(accepted.job_id), 2)

    job = await row(resources, accepted.job_id)
    assert (job.state, job.attempts, job.error_code) == ("completed", 2, None)
    assert (await facts())[0::2] == ("ready", "ready")
