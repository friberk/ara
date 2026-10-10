"""Stored PDFs of deleted papers are removed by a durable job, never inline (ARA-095)."""

import io
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from minio.error import S3Error
from sqlalchemy import delete, func, select
from support.front_matter import toolchain_pdf
from test_metadata_enrichment_integration import ingested
from test_paper_deletion_integration import client_for

from app.models.jobs import BackgroundJob, JobOutbox
from app.models.research import Document, Paper
from app.repositories.jobs import claim, enqueue
from tests.support.cleanup import cleanup_job, run_cleanup

pytestmark = pytest.mark.integration


async def stored(resources, key) -> bool:
    try:
        await resources.storage_call(
            resources.storage.stat_object, resources.settings.minio_bucket, key
        )
    except S3Error as error:
        assert error.code == "NoSuchKey"
        return False
    return True


TITLES = {
    "Deleted": ("Quantum annealing schedules",),
    "Kept": ("Bayesian hierarchical forecasting",),
    "Live": ("Coral reef acoustics",),
    "Gone": ("Glacier calving dynamics",),
}


async def uploaded(resources, name: str):
    """A paper with a processed PDF stored in MinIO; returns (paper_id, object key)."""
    accepted = await ingested(
        resources,
        toolchain_pdf(stamp=None, title_lines=TITLES[name], body=f"{name} {uuid4()}"),
    )
    async with resources.sessions() as session:
        document = await session.get(Document, accepted.document_id)
        return accepted.paper_id, document.object_key


async def test_deletion_queues_cleanup_in_its_commit_and_the_job_removes_the_pdf(resources):
    """Given two uploaded papers, when one is deleted, then a cleanup job and its outbox event
    commit with the deletion, the object stays until the job runs, and only it is removed."""
    paper, key = await uploaded(resources, "Deleted")
    _, kept_key = await uploaded(resources, "Kept")
    async with client_for(resources) as client:
        assert (await client.delete(f"/api/v1/papers/{paper}")).status_code == 204

    job = await cleanup_job(resources)
    assert job is not None and job.state == "queued"
    assert job.payload["object_keys"] == [key]
    async with resources.sessions() as session:
        events = await session.scalar(
            select(func.count()).select_from(JobOutbox).where(JobOutbox.job_id == job.id)
        )
    assert events == 1
    assert await stored(resources, key)

    done = await run_cleanup(resources)
    assert done.state == "completed" and done.result == {"removed": 1, "kept": 0}
    assert not await stored(resources, key)
    assert await stored(resources, kept_key)


async def test_a_duplicate_delivery_removes_nothing_and_a_rerun_is_harmless(resources):
    from app.services.deletion import run_storage_cleanup_job

    paper, key = await uploaded(resources, "Deleted")
    async with client_for(resources) as client:
        await client.delete(f"/api/v1/papers/{paper}")
    job = await cleanup_job(resources)
    token = await claim(resources.sessions, job.id, job.generation)
    # A second delivery of the same event cannot claim the job.
    assert await claim(resources.sessions, job.id, job.generation) is None
    await run_storage_cleanup_job(resources, job.id, job.generation, uuid4(), job.payload)
    assert await stored(resources, key)
    await run_storage_cleanup_job(resources, job.id, job.generation, token, job.payload)
    assert not await stored(resources, key)
    # Removing objects that are already gone succeeds.
    async with resources.sessions() as session, session.begin():
        again = await enqueue(session, kind="storage_cleanup", payload=dict(job.payload))
    rerun = await run_cleanup(resources)
    assert rerun.id == again.id and rerun.state == "completed"


@contextmanager
def storage_down(resources):
    """Removal fails as an unreachable store would; restored before the fixture's teardown."""

    def unavailable(*_args, **_kwargs):
        raise ConnectionError("storage is down")

    resources.storage.remove_object = unavailable
    try:
        yield
    finally:
        del resources.storage.remove_object


async def test_a_storage_outage_retries_and_never_brings_rows_back(resources):
    """Given storage failing, the job waits and retries within its attempts, the paper stays
    deleted, and a failure after the last attempt can still be retried through the jobs API."""
    paper, key = await uploaded(resources, "Deleted")
    async with client_for(resources) as client:
        await client.delete(f"/api/v1/papers/{paper}")

    before = datetime.now(UTC)
    with storage_down(resources):
        waiting = await run_cleanup(resources)
        assert (waiting.state, waiting.stage) == ("queued", "retry_wait")
        assert waiting.error_code == "STORAGE_UNAVAILABLE" and waiting.generation == 2
        assert waiting.available_at >= before + timedelta(seconds=29)
        async with resources.sessions() as session:
            assert await session.get(Paper, paper) is None
            assert await session.scalar(select(func.count()).select_from(Document)) == 0
            assert await session.scalar(
                select(JobOutbox.id).where(
                    JobOutbox.job_id == waiting.id, JobOutbox.generation == 2
                )
            )
        await run_cleanup(resources)
        failed = await run_cleanup(resources)
    assert failed.state == "failed" and failed.attempts == 3
    assert failed.error_code == "STORAGE_UNAVAILABLE"
    assert await stored(resources, key)

    async with client_for(resources) as client:
        retried = await client.post(f"/api/v1/jobs/{failed.id}/retry", json={})
    assert retried.status_code == 202, retried.text
    done = await run_cleanup(resources)
    assert done.state == "completed"
    assert not await stored(resources, key)
    async with resources.sessions() as session:
        assert await session.get(Paper, paper) is None


async def test_an_object_a_live_document_still_names_is_kept(resources):
    _, live_key = await uploaded(resources, "Live")
    gone, gone_key = await uploaded(resources, "Gone")
    async with client_for(resources) as client:
        await client.delete(f"/api/v1/papers/{gone}")
    job = await cleanup_job(resources)
    async with resources.sessions() as session, session.begin():
        (await session.get(BackgroundJob, job.id)).payload = {"object_keys": [gone_key, live_key]}
    done = await run_cleanup(resources)
    assert done.result == {"removed": 1, "kept": 1}
    assert await stored(resources, live_key) and not await stored(resources, gone_key)


async def test_a_pdf_still_uploading_is_removed_after_the_upload_grace(resources):
    """An upload commits its document before storing the object, so cleanup waits past the
    ingest grace and removes an object stored late."""
    async with resources.sessions() as session, session.begin():
        paper = Paper(title="Uploading", metadata_provenance={})
        session.add(paper)
        await session.flush()
        document = Document(
            paper_id=paper.id,
            status="uploading",
            object_key=f"originals/{uuid4()}.pdf",
            sha256=uuid4().hex + uuid4().hex,
            original_filename="late.pdf",
            byte_size=10,
            request_id=uuid4(),
        )
        session.add(document)
        await session.flush()
        paper.active_document_id = document.id
    before = datetime.now(UTC)
    async with client_for(resources) as client:
        assert (await client.delete(f"/api/v1/papers/{paper.id}")).status_code == 204
    job = await cleanup_job(resources)
    assert job.available_at >= before + timedelta(seconds=290)


async def test_one_documents_object_can_be_cleaned_up_on_its_own(resources):
    """The cleanup is callable for a single document, as removing one PDF of a paper will need
    (ARA-097): after the document row goes, its object is removed and the paper's others stay."""
    from app.services.deletion import queue_storage_cleanup

    paper, current_key = await uploaded(resources, "Live")
    older = Document(
        paper_id=paper,
        status="ready",
        object_key=f"originals/{uuid4()}.pdf",
        sha256=uuid4().hex + uuid4().hex,
        original_filename="older.pdf",
        byte_size=10,
        request_id=uuid4(),
    )
    await resources.storage_call(
        resources.storage.put_object,
        resources.settings.minio_bucket,
        older.object_key,
        io.BytesIO(b"%PDF-1.4 older"),
        14,
    )
    async with resources.sessions() as session, session.begin():
        session.add(older)
    async with resources.sessions() as session, session.begin():
        await session.execute(delete(Document).where(Document.id == older.id))
        job = await queue_storage_cleanup(session, [older])
    assert job.payload["object_keys"] == [older.object_key]
    done = await run_cleanup(resources)
    assert done.state == "completed" and done.result == {"removed": 1, "kept": 0}
    assert not await stored(resources, older.object_key)
    assert await stored(resources, current_key)
