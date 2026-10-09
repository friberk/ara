"""Re-ingest ready documents whose chunks predate the current chunk set (ARA-071)."""

import asyncio
import os
import sys
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import func, select, update
from support.structured_pdf import create_structured_pdf

pytestmark = pytest.mark.integration

PRIOR_PAYLOAD = {"metadata_attempted": True, "metadata_result": {"title": "Inferred"}}


async def ready_documents(resources, chunk_sets, *, status="ready"):
    """Documents with a completed original ingest job and one stored chunk each."""
    from app.models.jobs import BackgroundJob
    from app.models.research import Document, DocumentChunk, Paper

    identifiers = []
    async with resources.sessions() as session, session.begin():
        paper = Paper(title="Reindex fixture", metadata_provenance={})
        session.add(paper)
        await session.flush()
        for chunk_set in chunk_sets:
            document = Document(
                paper_id=paper.id,
                status=status,
                object_key=f"reindex-fixture/{uuid4()}.pdf",
                sha256=uuid4().hex * 2,
                original_filename="reindex.pdf",
                byte_size=1,
                request_id=uuid4(),
                page_count=1,
                warnings=[],
                chunk_set=chunk_set,
            )
            session.add(document)
            await session.flush()
            job = BackgroundJob(
                kind="ingest",
                state="completed",
                stage="completed",
                progress=100,
                payload={"document_id": str(document.id), **PRIOR_PAYLOAD},
            )
            session.add(job)
            await session.flush()
            document.ingest_job_id = job.id
            session.add(
                DocumentChunk(
                    document_id=document.id,
                    chunk_set=chunk_set or "legacy-page-window-v0",
                    ordinal=0,
                    page=1,
                    page_end=1,
                    text="previous chunk",
                    context_text="previous chunk",
                    token_count=2,
                )
            )
            identifiers.append(document.id)
    return identifiers


async def queued_ingest_jobs(resources):
    from app.models.jobs import BackgroundJob, JobOutbox

    async with resources.sessions() as session:
        jobs = (
            await session.scalars(
                select(BackgroundJob).where(
                    BackgroundJob.kind == "ingest", BackgroundJob.state == "queued"
                )
            )
        ).all()
        outbox = await session.scalar(
            select(func.count())
            .select_from(JobOutbox)
            .where(JobOutbox.job_id.in_([job.id for job in jobs]))
        )
        return jobs, outbox


async def test_given_old_chunk_sets_when_reindexed_twice_then_two_jobs_are_queued(resources):
    from app.models.research import Document
    from app.rag.chunking import CHUNK_SET
    from app.services.reindex import enqueue_reindex

    stale = await ready_documents(resources, ["legacy-page-window-v0", None])
    current = await ready_documents(resources, [CHUNK_SET])
    processing = await ready_documents(resources, ["legacy-page-window-v0"], status="processing")

    assert await enqueue_reindex(resources) == 2
    assert await enqueue_reindex(resources) == 0
    jobs, outbox = await queued_ingest_jobs(resources)
    assert sorted(UUID(job.payload["document_id"]) for job in jobs) == sorted(stale)
    assert outbox == 2
    for job in jobs:
        assert job.payload == {"document_id": job.payload["document_id"], **PRIOR_PAYLOAD}
    async with resources.sessions() as session:
        documents = {
            document.id: document for document in (await session.scalars(select(Document))).all()
        }
    assert {documents[i].ingest_job_id for i in stale} == {job.id for job in jobs}
    assert all(documents[i].status == "ready" for i in stale + current)
    assert documents[processing[0]].status == "processing"


async def test_given_concurrent_reindex_runs_then_each_document_is_queued_once(resources):
    from app.services.reindex import enqueue_reindex

    await ready_documents(resources, ["legacy-page-window-v0"] * 3)
    counts = await asyncio.gather(*(enqueue_reindex(resources) for _ in range(3)))
    assert sum(counts) == 3
    jobs, _ = await queued_ingest_jobs(resources)
    assert len(jobs) == 3


async def test_given_failed_reindex_then_ready_document_keeps_serving_old_chunks(resources):
    from app.models.research import Document, DocumentChunk
    from app.repositories.jobs import claim
    from app.services.ingestion import run_ingest_job
    from app.services.reindex import enqueue_reindex

    [document_id] = await ready_documents(resources, ["legacy-page-window-v0"])
    assert await enqueue_reindex(resources) == 1
    [job], _ = await queued_ingest_jobs(resources)
    token = await claim(resources.sessions, job.id, job.generation)
    await run_ingest_job(resources, job.id, job.generation, token, job.payload)  # no stored PDF
    async with resources.sessions() as session:
        document = await session.get(Document, document_id)
        chunks = (
            await session.scalars(
                select(DocumentChunk.text).where(DocumentChunk.document_id == document_id)
            )
        ).all()
        failed = await session.get(type(job), job.id)
    assert failed.state == "failed" and failed.error_code == "STORAGE_OBJECT_MISSING"
    assert document.status == "ready" and document.warnings == []
    assert chunks == ["previous chunk"]


async def test_given_reindex_job_runs_then_document_moves_to_the_current_chunk_set(
    resources, tmp_path
):
    from app.main import create_app
    from app.models.jobs import BackgroundJob
    from app.models.research import Document
    from app.rag.chunking import CHUNK_SET
    from app.repositories.jobs import claim
    from app.services.ingestion import run_ingest_job
    from app.services.reindex import enqueue_reindex

    pdf = create_structured_pdf(tmp_path / "s.pdf")
    app = create_app(resources.settings)
    app.state.resources = resources
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/documents",
            files={"file": ("s.pdf", pdf.read_bytes(), "application/pdf")},
            data={"request_id": str(uuid4())},
        )
    references = response.json()
    document_id = UUID(references["document_id"])
    async with resources.sessions() as session:
        upload_job = await session.get(BackgroundJob, references["job_id"])
        payload = upload_job.payload
    token = await claim(resources.sessions, upload_job.id, 1)
    await run_ingest_job(resources, upload_job.id, 1, token, payload)
    async with resources.sessions() as session, session.begin():
        await session.execute(
            update(Document).where(Document.id == document_id).values(chunk_set="older")
        )

    assert await enqueue_reindex(resources) == 1
    [job], _ = await queued_ingest_jobs(resources)
    token = await claim(resources.sessions, job.id, job.generation)
    await run_ingest_job(resources, job.id, job.generation, token, job.payload)
    async with resources.sessions() as session:
        document = await session.get(Document, document_id)
    assert document.status == "ready" and document.chunk_set == CHUNK_SET
    assert await enqueue_reindex(resources) == 0


async def test_reindex_module_runs_as_a_command(resources):
    await ready_documents(resources, ["legacy-page-window-v0"])
    environment = {**os.environ, "DATABASE_URL": resources.settings.database_url.get_secret_value()}
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "app.services.reindex",
        env=environment,
        stdout=asyncio.subprocess.PIPE,
    )
    stdout, _ = await process.communicate()
    assert process.returncode == 0
    assert stdout.decode().strip() == "Queued 1 document(s) for re-indexing."
