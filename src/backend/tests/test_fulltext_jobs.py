"""Retrieval executes against real isolated storage/database and the real child parser.

PDFs come only from OpenAlex's content endpoint (ARA-087); the transport is mocked.
"""

import asyncio
import json
import subprocess
import sys
from datetime import timedelta
from uuid import UUID, uuid4

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import func, select
from test_fulltext_integration import app_client

from app.integrations.openalex_content import ContentDownloader
from app.models.jobs import BackgroundJob
from app.models.research import ChatSession, Document, DocumentUploadRequest
from app.repositories.jobs import claim, now
from app.repositories.papers import save_canonical
from app.schemas.research import SearchResult

KEY = "fixture-openalex-key"
SIGNED = (
    "https://a452eddbbe06eb7d02f4879cee70d29c.r2.cloudflarestorage.com"
    "/openalex-pdfs/W123.pdf?X-Amz-Signature=fixture-signature"
)


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


def stored_copy(original_pdf):
    """OpenAlex's documented answer: a redirect from the content endpoint to signed storage."""

    async def respond(request):
        if request.headers["Host"] == "content.openalex.org":
            return httpx.Response(302, headers={"Location": SIGNED})
        return httpx.Response(200, stream=httpx.ByteStream(original_pdf))

    return respond


class Resolver:
    async def resolve(self, _host, _port):
        return ("8.8.8.8",)


async def prepare(resources, original_pdf, *, stored=True, response=None, key=KEY, source=None):
    """A saved paper, OpenAlex's free lookup and its content endpoint.

    Returns the paper and the content-endpoint requests, one per download attempt.
    """
    resources.settings.openalex_api_key = SecretStr(key) if key else None
    async with resources.sessions() as session, session.begin():
        paper, _ = await save_canonical(
            session,
            source
            or SearchResult(provider="openalex", external_id="W123", title="Download fixture"),
        )
        paper_id = paper.id
    lookups = []

    def lookup(request):
        lookups.append(request)
        return httpx.Response(
            200, json={"id": "https://openalex.org/W123", "has_content": {"pdf": stored}}
        )

    await resources.http.aclose()
    resources.http = httpx.AsyncClient(transport=httpx.MockTransport(lookup))
    downloads = []
    answer = response or stored_copy(original_pdf)

    async def respond(request):
        if request.headers["Host"] == "content.openalex.org":
            downloads.append(request)
        return await answer(request)

    await resources.pdf_downloader.aclose()
    resources.pdf_downloader = ContentDownloader(
        resolver=Resolver(), transport_factory=lambda: httpx.MockTransport(respond)
    )
    resources.lookups = lookups
    return paper_id, downloads


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


async def test_a_stored_openalex_pdf_creates_one_ingest_job(resources, original_pdf):
    from app.integrations.storage import read_object
    from app.services.fulltext import run_fulltext_job
    from app.services.ingestion import run_ingest_job

    paper_id, downloads = await prepare(resources, original_pdf)
    args = await enqueue_and_claim(resources, paper_id)
    await run_fulltext_job(resources, *args)
    job = await state(resources, args[0])
    assert job.state == "completed" and job.result["outcome"] == "downloaded"
    async with resources.sessions() as session:
        document = await session.get(Document, job.result["document_id"])
        assert await session.scalar(select(func.count()).select_from(Document)) == 1
        ingest = await session.get(BackgroundJob, job.result["ingest_job_id"])
    assert document.acquisition["provider"] == "openalex"
    assert document.acquisition["source"] == "content"
    assert document.acquisition["work_id"] == "W123"
    # Neither the API key nor the signed storage link is persisted anywhere.
    persisted = json.dumps([document.acquisition, job.payload, job.result])
    assert KEY not in persisted and "fixture-signature" not in persisted
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
    assert len(downloads) == 1
    assert [request.url.path for request in resources.lookups] == ["/works/W123"]


async def test_a_semantic_scholar_paper_resolves_its_openalex_work_by_doi(resources, original_pdf):
    from app.services.fulltext import run_fulltext_job

    paper_id, downloads = await prepare(
        resources,
        original_pdf,
        source=SearchResult(
            provider="semantic_scholar", external_id="s2-paper", doi="10.1000/doi-only"
        ),
    )
    args = await enqueue_and_claim(resources, paper_id)
    await run_fulltext_job(resources, *args)
    assert (await state(resources, args[0])).result["outcome"] == "downloaded"
    assert [request.url.path for request in resources.lookups] == ["/works/doi:10.1000/doi-only"]
    assert downloads[0].url.path == "/works/W123.pdf"


async def test_no_stored_copy_contacts_no_other_host(resources, original_pdf):
    from app.services.fulltext import run_fulltext_job

    paper_id, downloads = await prepare(resources, original_pdf, stored=False)
    args = await enqueue_and_claim(resources, paper_id)
    await run_fulltext_job(resources, *args)
    job = await state(resources, args[0])
    assert job.state == "failed" and job.result["outcome"] == "not_stored"
    assert downloads == []
    async with resources.sessions() as session:
        assert await session.scalar(select(func.count()).select_from(Document)) == 0


async def test_a_job_without_a_key_downloads_nothing(resources, original_pdf):
    """Given a queued job whose key was since removed, when it runs, then it stops at once."""
    from app.services.fulltext import run_fulltext_job

    paper_id, downloads = await prepare(resources, original_pdf)
    args = await enqueue_and_claim(resources, paper_id)
    resources.settings.openalex_api_key = None
    await run_fulltext_job(resources, *args)
    job = await state(resources, args[0])
    assert job.state == "failed" and job.result["outcome"] == "api_key_required"
    assert downloads == [] and resources.lookups == []


@pytest.mark.parametrize(
    ("status", "headers", "wait"),
    [(429, {"Retry-After": "40"}, 40), (500, {}, None)],
)
async def test_lookup_refusals_finish_once_without_a_retry_loop(
    resources, original_pdf, status, headers, wait
):
    from app.services.fulltext import run_fulltext_job

    paper_id, downloads = await prepare(resources, original_pdf)
    await resources.http.aclose()
    resources.http = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _request: httpx.Response(status, headers=headers))
    )
    args = await enqueue_and_claim(resources, paper_id)
    await run_fulltext_job(resources, *args)
    job = await state(resources, args[0])
    assert job.state == "failed" and job.generation == 1
    assert job.result == {
        "outcome": "rate_limited" if status == 429 else "unavailable",
        "retry_after": wait,
    }
    assert downloads == []


async def test_old_uuid_replays_denial_new_uuid_succeeds(resources, original_pdf):
    from app.services.fulltext import run_fulltext_job

    granted = False
    stored = stored_copy(original_pdf)

    async def respond(request):
        return await stored(request) if granted else httpx.Response(503)

    paper_id, requests = await prepare(resources, original_pdf, response=respond)
    old_id = uuid4()
    args = await enqueue_and_claim(resources, paper_id, old_id)
    await run_fulltext_job(resources, *args)
    first = await state(resources, args[0])
    assert first.state == "failed" and first.result["outcome"] == "unavailable"
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


@pytest.mark.parametrize(("status", "outcome"), [(429, "rate_limited"), (200, "invalid_pdf")])
async def test_access_failure_never_creates_invalid_document(
    resources, original_pdf, status, outcome
):
    from app.services.fulltext import run_fulltext_job

    async def respond(request):
        if status == 200 and request.headers["Host"] == "content.openalex.org":
            return httpx.Response(302, headers={"Location": SIGNED})
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

    stored = stored_copy(original_pdf)

    async def respond(request):
        started.set()
        await release.wait()
        return await stored(request)

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


async def test_overall_deadline_stops_a_slow_lookup(resources, original_pdf, monkeypatch):
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
