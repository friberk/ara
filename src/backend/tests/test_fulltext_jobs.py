"""Retrieval executes against real isolated storage/database and the real child parser."""

import asyncio
import subprocess
import sys
from datetime import timedelta
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import func, select
from test_fulltext_integration import app_client

from app.integrations.pdf_download import PDFDownloader
from app.models.jobs import BackgroundJob
from app.models.research import ChatSession, Document, DocumentUploadRequest
from app.repositories.jobs import claim, now
from app.repositories.papers import save_canonical
from app.schemas.research import FullTextLocation, SearchResult


@pytest.fixture
def original_pdf():
    return subprocess.check_output(
        [
            sys.executable,
            "-c",
            "import pymupdf; d=pymupdf.open(); p=d.new_page(); "
            "p.insert_text((72,72),'Evidence: the experiment used Orion-12.'); "
            "d.set_metadata({'title':'Download fixture','author':'Ada Researcher'}); "
            "import sys; sys.stdout.buffer.write(d.tobytes())",
        ]
    )


async def prepare(resources, original_pdf, *, urls=None, response=None):
    urls = ["https://arxiv.org/pdf/one"] if urls is None else urls
    async with resources.sessions() as session, session.begin():
        paper, _ = await save_canonical(
            session,
            SearchResult(
                provider="openalex",
                external_id="W123",
                title="Download fixture",
                locations=[
                    FullTextLocation(pdf_url=url, is_oa=True, version="acceptedVersion")
                    for url in urls
                ],
            ),
        )
        paper_id = paper.id
    await resources.http.aclose()
    resources.http = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json={
                    "id": "https://openalex.org/W123",
                    "display_name": "Download fixture",
                    "locations": [
                        {"pdf_url": url, "is_oa": True, "version": "acceptedVersion"}
                        for url in urls
                    ],
                },
            )
        )
    )

    class Resolver:
        async def resolve(self, _host, _port):
            return ("8.8.8.8",)

    requests = []

    async def respond(request):
        requests.append(request)
        if response:
            return await response(request)
        return httpx.Response(200, stream=httpx.ByteStream(original_pdf))

    await resources.pdf_downloader.aclose()
    resources.pdf_downloader = PDFDownloader(
        ["arxiv.org"], resolver=Resolver(), transport_factory=lambda: httpx.MockTransport(respond)
    )
    return paper_id, requests


async def enqueue_and_claim(resources, paper_id, request_id=None):
    async with app_client(resources) as client:
        accepted = (
            await client.post(
                f"/api/v1/papers/{paper_id}/retrieve-fulltext",
                json={"request_id": str(request_id or uuid4())},
            )
        ).json()
    job_id = UUID(accepted["job_id"])
    token = await claim(resources.sessions, job_id, 1)
    async with resources.sessions() as session:
        job = await session.get(BackgroundJob, job_id)
        return job.id, job.generation, token, dict(job.payload)


async def state(resources, job_id):
    async with resources.sessions() as session:
        return await session.get(BackgroundJob, job_id)


async def test_fulltext_pdf_creates_one_ingest_job(resources, original_pdf):
    from app.integrations.storage import read_object
    from app.services.fulltext import run_fulltext_job
    from app.services.ingestion import run_ingest_job

    paper_id, requests = await prepare(resources, original_pdf)
    args = await enqueue_and_claim(resources, paper_id)
    await run_fulltext_job(resources, *args)
    job = await state(resources, args[0])
    assert job.state == "completed" and job.result["outcome"] == "downloaded"
    async with resources.sessions() as session:
        document = await session.get(Document, job.result["document_id"])
        assert document.acquisition["version"] == "acceptedVersion"
        assert await session.scalar(select(func.count()).select_from(Document)) == 1
        ingest = await session.get(BackgroundJob, job.result["ingest_job_id"])
    assert (
        await resources.storage_call(
            read_object,
            resources.storage,
            resources.settings.minio_bucket,
            document.object_key,
            25 * 1024 * 1024,
        )
        == original_pdf
    )
    token = await claim(resources.sessions, ingest.id, ingest.generation)
    assert token is not None
    await run_ingest_job(resources, ingest.id, ingest.generation, token, ingest.payload)
    async with app_client(resources) as client:
        paper = (await client.get(f"/api/v1/papers/{paper_id}")).json()
        assert paper["document_status"] == "ready"
    assert len(requests) == 1


async def test_old_uuid_replays_denial_new_uuid_succeeds(resources, original_pdf):
    from app.services.fulltext import run_fulltext_job

    granted = False

    async def respond(_request):
        return (
            httpx.Response(200, stream=httpx.ByteStream(original_pdf))
            if granted
            else httpx.Response(403)
        )

    paper_id, requests = await prepare(resources, original_pdf, response=respond)
    old_id = uuid4()
    args = await enqueue_and_claim(resources, paper_id, old_id)
    await run_fulltext_job(resources, *args)
    first = await state(resources, args[0])
    assert first.state == "failed" and first.result["outcome"] == "blocked"
    granted = True
    new_args = await enqueue_and_claim(resources, paper_id)
    await run_fulltext_job(resources, *new_args)
    assert (await state(resources, new_args[0])).result["outcome"] == "downloaded"
    async with app_client(resources) as client:
        old = await client.post(
            f"/api/v1/papers/{paper_id}/retrieve-fulltext", json={"request_id": str(old_id)}
        )
        assert old.json()["job_id"] == str(args[0])
    assert len(requests) == 2


async def test_denied_candidate_falls_back_and_preserves_attempts(resources, original_pdf):
    from app.services.fulltext import run_fulltext_job

    async def respond(request):
        return (
            httpx.Response(401)
            if request.url.path.endswith("first")
            else httpx.Response(200, stream=httpx.ByteStream(original_pdf))
        )

    paper_id, _ = await prepare(
        resources,
        original_pdf,
        urls=["https://arxiv.org/pdf/first", "https://arxiv.org/pdf/second"],
        response=respond,
    )
    args = await enqueue_and_claim(resources, paper_id)
    await run_fulltext_job(resources, *args)
    async with app_client(resources) as client:
        status = (await client.get(f"/api/v1/papers/{paper_id}/fulltext")).json()
    assert status["retrieval_job"]["result"]["outcome"] == "downloaded"
    assert [item["outcome"] for item in status["attempts"]] == ["access_required", "downloaded"]


@pytest.mark.parametrize(("status", "outcome"), [(429, "rate_limited"), (200, "invalid_pdf")])
async def test_access_failure_never_creates_invalid_document(
    resources, original_pdf, status, outcome
):
    from app.services.fulltext import run_fulltext_job

    async def respond(_request):
        return httpx.Response(
            status,
            headers={"Retry-After": "60", "Content-Type": "text/html"},
            stream=httpx.ByteStream(b"<html>sign in</html>"),
        )

    paper_id, _ = await prepare(resources, original_pdf, response=respond)
    args = await enqueue_and_claim(resources, paper_id)
    await run_fulltext_job(resources, *args)
    job = await state(resources, args[0])
    assert job.state == "failed" and job.result["outcome"] == outcome
    if status == 429:
        assert job.result["retry_after"] == 60
    async with resources.sessions() as session:
        assert await session.scalar(select(func.count()).select_from(Document)) == 0


async def test_missing_direct_link_finishes_without_ingestion(resources, original_pdf):
    from app.services.fulltext import run_fulltext_job

    paper_id, requests = await prepare(resources, original_pdf, urls=[])
    args = await enqueue_and_claim(resources, paper_id)
    await run_fulltext_job(resources, *args)
    job = await state(resources, args[0])
    assert job.state == "failed" and job.result["outcome"] == "no_pdf_link"
    assert requests == []


async def test_existing_ready_pdf_skips_network_and_preserves_history(resources, original_pdf):
    from app.services.fulltext import run_fulltext_job
    from app.services.uploads import ingest_pdf_bytes

    paper_id, requests = await prepare(resources, original_pdf)
    accepted = await ingest_pdf_bytes(
        resources, data=original_pdf, filename="manual.pdf", request_id=uuid4(), paper_id=paper_id
    )
    async with resources.sessions() as session, session.begin():
        document = await session.get(Document, accepted.document_id)
        document.status = "ready"
        chat = ChatSession(paper_id=paper_id, document_id=document.id)
        session.add(chat)
        await session.flush()
        chat_id = chat.id
    args = await enqueue_and_claim(resources, paper_id)
    await run_fulltext_job(resources, *args)
    job = await state(resources, args[0])
    assert job.state == "completed" and job.result["outcome"] == "already_attached"
    assert requests == []
    async with resources.sessions() as session:
        assert (await session.get(ChatSession, chat_id)).document_id == accepted.document_id


async def test_manual_upload_supersedes_download(resources, original_pdf):
    from app.services.fulltext import run_fulltext_job
    from app.services.uploads import ingest_pdf_bytes

    started, release = asyncio.Event(), asyncio.Event()

    async def respond(_request):
        started.set()
        await release.wait()
        return httpx.Response(200, stream=httpx.ByteStream(original_pdf))

    paper_id, _ = await prepare(resources, original_pdf, response=respond)
    args = await enqueue_and_claim(resources, paper_id)
    task = asyncio.create_task(run_fulltext_job(resources, *args))
    await asyncio.wait_for(started.wait(), 2)
    manual = await ingest_pdf_bytes(
        resources,
        data=original_pdf + b"\n% manual version\n",
        filename="manual.pdf",
        request_id=uuid4(),
        paper_id=paper_id,
    )
    release.set()
    await task
    job = await state(resources, args[0])
    assert job.result["outcome"] == "superseded"
    async with app_client(resources) as client:
        assert (await client.get(f"/api/v1/papers/{paper_id}")).json()["active_document_id"] == str(
            manual.document_id
        )


async def test_attachment_rejects_lost_lease_before_creating_document(resources, original_pdf):
    from app.services.uploads import AttachmentGuard, AttachmentLeaseLost, ingest_pdf_bytes

    paper_id, _ = await prepare(resources, original_pdf)
    args = await enqueue_and_claim(resources, paper_id)
    async with resources.sessions() as session, session.begin():
        job = await session.get(BackgroundJob, args[0])
        job.lease_expires_at = now() - timedelta(seconds=1)
    with pytest.raises(AttachmentLeaseLost):
        await ingest_pdf_bytes(
            resources,
            data=original_pdf,
            filename="remote.pdf",
            request_id=uuid4(),
            paper_id=paper_id,
            guard=AttachmentGuard(args[0], args[1], args[2], None),
        )
    async with resources.sessions() as session:
        assert await session.scalar(select(func.count()).select_from(Document)) == 0


async def test_duplicate_delivery_has_one_document_and_ingest(resources, original_pdf):
    from app.services.fulltext import run_fulltext_job

    paper_id, requests = await prepare(resources, original_pdf)
    args = await enqueue_and_claim(resources, paper_id)
    await run_fulltext_job(resources, *args)
    await run_fulltext_job(resources, *args)
    async with resources.sessions() as session:
        assert await session.scalar(select(func.count()).select_from(Document)) == 1
        assert (
            await session.scalar(
                select(func.count())
                .select_from(BackgroundJob)
                .where(BackgroundJob.kind == "ingest")
            )
            == 1
        )
    assert len(requests) == 1


async def test_crash_after_attachment_reuses_checkpoint(resources, original_pdf, monkeypatch):
    from app.repositories.jobs import recover
    from app.services import fulltext

    paper_id, requests = await prepare(resources, original_pdf)
    args = await enqueue_and_claim(resources, paper_id)
    actual_attach = fulltext.ingest_pdf_bytes

    async def crash(*call_args, **kwargs):
        await actual_attach(*call_args, **kwargs)
        raise RuntimeError("simulated crash after attachment commit")

    monkeypatch.setattr(fulltext, "ingest_pdf_bytes", crash)
    with pytest.raises(RuntimeError, match="simulated crash"):
        await fulltext.run_fulltext_job(resources, *args)
    monkeypatch.setattr(fulltext, "ingest_pdf_bytes", actual_attach)
    async with resources.sessions() as session, session.begin():
        job = await session.get(BackgroundJob, args[0])
        job.lease_expires_at = now() - timedelta(seconds=1)
    await recover(resources.sessions)
    async with resources.sessions() as session, session.begin():
        job = await session.get(BackgroundJob, args[0])
        job.available_at = now()
        generation, payload = job.generation, dict(job.payload)
    token = await claim(resources.sessions, args[0], generation)
    await fulltext.run_fulltext_job(resources, args[0], generation, token, payload)
    assert (await state(resources, args[0])).result["outcome"] == "downloaded"
    assert len(requests) == 1
    async with resources.sessions() as session:
        assert await session.scalar(select(func.count()).select_from(Document)) == 1
        assert (
            await session.scalar(
                select(func.count())
                .select_from(BackgroundJob)
                .where(BackgroundJob.kind == "ingest")
            )
            == 1
        )
        assert await session.scalar(select(func.count()).select_from(DocumentUploadRequest)) == 1


async def test_storage_failure_can_recover_with_stable_attachment_uuid(resources, original_pdf):
    from minio import Minio

    from app.core.errors import AppError
    from app.repositories.jobs import fail
    from app.services.fulltext import run_fulltext_job

    paper_id, requests = await prepare(resources, original_pdf)
    args = await enqueue_and_claim(resources, paper_id)
    actual_storage = resources.storage
    resources.storage = Minio(
        "127.0.0.1:1",
        access_key="fixture",
        secret_key="fixture-only",
        secure=False,
        http_client=resources.storage_pool,
    )
    try:
        with pytest.raises(AppError):
            await run_fulltext_job(resources, *args)
    finally:
        resources.storage = actual_storage
    await fail(resources.sessions, args[0], args[1], args[2])
    async with resources.sessions() as session, session.begin():
        job = await session.get(BackgroundJob, args[0])
        job.available_at = now()
        generation, payload = job.generation, dict(job.payload)
    token = await claim(resources.sessions, args[0], generation)
    await run_fulltext_job(resources, args[0], generation, token, payload)
    assert (await state(resources, args[0])).result["outcome"] == "downloaded"
    async with resources.sessions() as session:
        assert await session.scalar(select(func.count()).select_from(Document)) == 1
        child = await session.scalar(select(BackgroundJob).where(BackgroundJob.kind == "ingest"))
        assert child.state == "queued" and child.generation == 2
    assert len(requests) == 2


async def test_actor_routes_fulltext_to_default_worker(resources, original_pdf, monkeypatch):
    from app.jobs import actors

    paper_id, _ = await prepare(resources, original_pdf)
    async with app_client(resources) as client:
        accepted = (
            await client.post(
                f"/api/v1/papers/{paper_id}/retrieve-fulltext", json={"request_id": str(uuid4())}
            )
        ).json()
    monkeypatch.setattr(actors, "_resources", resources)
    await actors.execute_job.fn.__wrapped__(accepted["job_id"], 1)
    assert (await state(resources, accepted["job_id"])).state == "completed"


async def test_crash_before_storage_restores_original_without_new_document(
    resources, original_pdf, monkeypatch
):
    from app.repositories.jobs import recover
    from app.services.fulltext import run_fulltext_job

    paper_id, requests = await prepare(resources, original_pdf)
    args = await enqueue_and_claim(resources, paper_id)
    actual_call = resources.storage_call

    async def interrupt(function, *call_args, **kwargs):
        if function == resources.storage.put_object:
            raise asyncio.CancelledError
        return await actual_call(function, *call_args, **kwargs)

    monkeypatch.setattr(resources, "storage_call", interrupt)
    with pytest.raises(asyncio.CancelledError):
        await run_fulltext_job(resources, *args)
    monkeypatch.setattr(resources, "storage_call", actual_call)
    async with resources.sessions() as session, session.begin():
        job = await session.get(BackgroundJob, args[0])
        job.lease_expires_at = now() - timedelta(seconds=1)
    await recover(resources.sessions)
    async with resources.sessions() as session, session.begin():
        job = await session.get(BackgroundJob, args[0])
        job.available_at = now()
        generation, payload = job.generation, dict(job.payload)
    token = await claim(resources.sessions, args[0], generation)
    await run_fulltext_job(resources, args[0], generation, token, payload)
    async with resources.sessions() as session:
        document = await session.scalar(select(Document))
        assert await session.scalar(select(func.count()).select_from(Document)) == 1
    objects = await resources.storage_call(
        lambda: list(
            resources.storage.list_objects(resources.settings.minio_bucket, recursive=True)
        )
    )
    assert [obj.object_name for obj in objects] == [document.object_key]
    assert (await state(resources, args[0])).result["outcome"] == "downloaded"
    assert len(requests) == 2


async def test_actor_cancels_fetch_when_lease_is_lost(resources, original_pdf, monkeypatch):
    from app.jobs import actors

    started, stopped = asyncio.Event(), asyncio.Event()

    async def stall(_request):
        started.set()
        try:
            await asyncio.sleep(10)
        finally:
            stopped.set()

    paper_id, _ = await prepare(resources, original_pdf, response=stall)
    resources.settings.heartbeat_seconds = 1
    async with app_client(resources) as client:
        accepted = (
            await client.post(
                f"/api/v1/papers/{paper_id}/retrieve-fulltext", json={"request_id": str(uuid4())}
            )
        ).json()
    monkeypatch.setattr(actors, "_resources", resources)
    task = asyncio.create_task(actors.execute_job.fn.__wrapped__(accepted["job_id"], 1))
    try:
        await asyncio.wait_for(started.wait(), 2)
        async with resources.sessions() as session, session.begin():
            job = await session.get(BackgroundJob, accepted["job_id"])
            job.lease_expires_at = now() - timedelta(seconds=1)
        done, _ = await asyncio.wait([task], timeout=2)
        assert task in done, "A lost lease must stop the outstanding fetch immediately"
        assert stopped.is_set()
        async with resources.sessions() as session:
            assert await session.scalar(select(func.count()).select_from(Document)) == 0
    finally:
        if not task.done():
            task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


@pytest.mark.parametrize("storage_error", [False, True])
async def test_late_storage_callback_cannot_mutate_after_lease_loss(
    resources, original_pdf, monkeypatch, storage_error
):
    from app.core.errors import AppError
    from app.services.fulltext import run_fulltext_job

    paper_id, _ = await prepare(resources, original_pdf)
    args = await enqueue_and_claim(resources, paper_id)
    actual_call = resources.storage_call

    async def late(function, *call_args, **kwargs):
        if function == resources.storage.put_object:
            async with resources.sessions() as session, session.begin():
                job = await session.get(BackgroundJob, args[0])
                job.lease_expires_at = now() - timedelta(seconds=1)
            if storage_error:
                raise RuntimeError("late storage failure")
        return await actual_call(function, *call_args, **kwargs)

    monkeypatch.setattr(resources, "storage_call", late)
    try:
        await run_fulltext_job(resources, *args)
    except AppError:
        pass
    async with resources.sessions() as session:
        document = await session.scalar(select(Document))
        child = await session.get(BackgroundJob, document.ingest_job_id)
        assert document.status == "uploading"
        assert child.state == "queued" and child.available_at > now()


async def test_exhausted_recovery_finishes_and_retains_metadata(resources, original_pdf):
    from app.repositories.jobs import recover

    paper_id, requests = await prepare(resources, original_pdf)
    args = await enqueue_and_claim(resources, paper_id)
    async with resources.sessions() as session, session.begin():
        job = await session.get(BackgroundJob, args[0])
        job.attempts = 3
        job.lease_expires_at = now() - timedelta(seconds=1)
    await recover(resources.sessions)
    async with app_client(resources) as client:
        status = (await client.get(f"/api/v1/papers/{paper_id}/fulltext")).json()
        paper = (await client.get(f"/api/v1/papers/{paper_id}")).json()
    assert status["retrieval_job"]["state"] == "failed"
    assert paper["document_status"] == "metadata_only" and paper["title"] == "Download fixture"
    assert requests == []


async def test_overall_deadline_stops_slow_discovery(resources, original_pdf, monkeypatch):
    from app.services import fulltext

    paper_id, requests = await prepare(resources, original_pdf)
    await resources.http.aclose()

    async def slow(_request):
        await asyncio.sleep(10)

    resources.http = httpx.AsyncClient(transport=httpx.MockTransport(slow))
    monkeypatch.setattr(fulltext, "JOB_SECONDS", 0.05)
    args = await enqueue_and_claim(resources, paper_id)
    await asyncio.wait_for(fulltext.run_fulltext_job(resources, *args), 1)
    job = await state(resources, args[0])
    assert job.state == "failed" and job.result["outcome"] == "unavailable"
    assert requests == []


async def test_recovery_after_object_write_wakes_existing_ingest(
    resources, original_pdf, monkeypatch
):
    from app.repositories.jobs import recover
    from app.services.fulltext import run_fulltext_job

    paper_id, requests = await prepare(resources, original_pdf)
    args = await enqueue_and_claim(resources, paper_id)
    actual_call = resources.storage_call

    async def interrupt(function, *call_args, **kwargs):
        value = await actual_call(function, *call_args, **kwargs)
        if function == resources.storage.put_object:
            raise asyncio.CancelledError
        return value

    monkeypatch.setattr(resources, "storage_call", interrupt)
    with pytest.raises(asyncio.CancelledError):
        await run_fulltext_job(resources, *args)
    monkeypatch.setattr(resources, "storage_call", actual_call)
    async with resources.sessions() as session, session.begin():
        job = await session.get(BackgroundJob, args[0])
        job.lease_expires_at = now() - timedelta(seconds=1)
    await recover(resources.sessions)
    async with resources.sessions() as session, session.begin():
        job = await session.get(BackgroundJob, args[0])
        job.available_at = now()
        generation, payload = job.generation, dict(job.payload)
    token = await claim(resources.sessions, args[0], generation)
    await run_fulltext_job(resources, args[0], generation, token, payload)
    async with resources.sessions() as session:
        document = await session.scalar(select(Document))
        child = await session.get(BackgroundJob, document.ingest_job_id)
        assert child.available_at <= now()
        assert document.status == "processing"
    assert len(requests) == 1


async def test_retrieval_can_reuse_older_document_after_failed_replacement(resources, original_pdf):
    from app.services.fulltext import run_fulltext_job
    from app.services.ingestion import run_ingest_job
    from app.services.uploads import ingest_pdf_bytes

    paper_id, _ = await prepare(resources, original_pdf)
    good = await ingest_pdf_bytes(
        resources, data=original_pdf, filename="good.pdf", request_id=uuid4(), paper_id=paper_id
    )
    async with resources.sessions() as session:
        child = await session.get(BackgroundJob, good.job_id)
    token = await claim(resources.sessions, child.id, child.generation)
    await run_ingest_job(resources, child.id, child.generation, token, child.payload)
    bad = await ingest_pdf_bytes(
        resources,
        data=original_pdf + b"\n% replacement\n",
        filename="bad.pdf",
        request_id=uuid4(),
        paper_id=paper_id,
    )
    async with resources.sessions() as session, session.begin():
        document = await session.get(Document, bad.document_id)
        document.status = "failed"
    args = await enqueue_and_claim(resources, paper_id)
    await run_fulltext_job(resources, *args)
    assert (await state(resources, args[0])).result["outcome"] == "downloaded"
    async with app_client(resources) as client:
        paper = (await client.get(f"/api/v1/papers/{paper_id}")).json()
    assert (
        paper["active_document_id"] == str(good.document_id) and paper["document_status"] == "ready"
    )


async def test_rate_limited_lookup_reports_the_providers_wait_not_an_outage(
    resources, original_pdf
):
    """Given no listed PDF and a rate-limited Semantic Scholar lookup, when retrieval ends,
    then it reports that provider's wait instead of a generic outage (ARA-084)."""
    from app.services.fulltext import run_fulltext_job

    paper_id, requests = await prepare(resources, original_pdf, urls=[])
    async with resources.sessions() as session, session.begin():
        from app.models.research import Paper

        paper = await session.get(Paper, paper_id)
        paper.doi = paper.normalized_doi = "10.1000/limited"

    def respond(request):
        if request.url.host == "api.semanticscholar.org":
            return httpx.Response(429, headers={"Retry-After": "45"})
        return httpx.Response(
            200,
            json={
                "id": "https://openalex.org/W123",
                "display_name": "Download fixture",
                "doi": "https://doi.org/10.1000/limited",
            },
        )

    await resources.http.aclose()
    resources.http = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    args = await enqueue_and_claim(resources, paper_id)
    await run_fulltext_job(resources, *args)
    job = await state(resources, args[0])
    assert job.state == "failed"
    assert job.result == {"outcome": "rate_limited", "retry_after": 45}
    assert "Semantic Scholar" in job.error_message
    assert job.payload["discovery_warnings"], "lookup warnings must survive a no-candidate finish"
    assert requests == []


async def test_status_names_the_host_a_download_is_coming_from(resources, original_pdf):
    """Given a download in progress, when status is read, then it names the source host so
    the workspace can say where the PDF is coming from (ARA-084)."""
    from app.services.fulltext import run_fulltext_job

    started, release = asyncio.Event(), asyncio.Event()

    async def respond(_request):
        started.set()
        await release.wait()
        return httpx.Response(200, stream=httpx.ByteStream(original_pdf))

    paper_id, _ = await prepare(resources, original_pdf, response=respond)
    args = await enqueue_and_claim(resources, paper_id)
    task = asyncio.create_task(run_fulltext_job(resources, *args))
    try:
        await asyncio.wait_for(started.wait(), 2)
        async with app_client(resources) as client:
            status = (await client.get(f"/api/v1/papers/{paper_id}/fulltext")).json()
        assert status["retrieval_job"]["stage"] == "fetching_pdf"
        assert status["source_host"] == "arxiv.org"
    finally:
        release.set()
        await task
