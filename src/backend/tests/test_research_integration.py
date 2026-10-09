import asyncio
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select

pytestmark = pytest.mark.integration


async def test_concurrent_canonical_save_deduplicates_doi_and_preserves_manual_overrides(resources):
    """Given concurrent provider identities sharing a DOI, when saved, then one paper survives."""
    from app.repositories.papers import paper_detail, patch_paper, save_canonical
    from app.schemas.research import PaperPatch, SearchResult

    async def save(provider, external_id):
        async with resources.sessions() as session, session.begin():
            return await save_canonical(
                session,
                SearchResult(
                    provider=provider,
                    external_id=external_id,
                    title="Canonical title",
                    authors=["Original Author"],
                    doi="10.1000/dedup",
                ),
            )

    first, second = await asyncio.gather(
        save("openalex", "W123"), save("semantic_scholar", "abc123")
    )
    assert first[0].id == second[0].id
    async with resources.sessions() as session, session.begin():
        await patch_paper(
            session, first[0].id, PaperPatch(title="My correction", authors=["Manual Author"])
        )
    await save("openalex", "W123")
    async with resources.sessions() as session:
        paper = await paper_detail(session, first[0].id)
    assert paper.title == "My correction" and paper.authors == ["Manual Author"]
    assert len(paper.sources) == 2 and paper.document_status == "metadata_only"
    assert paper.metadata_provenance["title"]["source"] == "manual"


async def test_pdf_upload_child_extraction_original_download_and_paper_isolated_chunks(resources):
    """Given a known PDF, when ingested, then original bytes and physical pages persist."""
    import pymupdf

    from app.main import create_app
    from app.models.jobs import BackgroundJob
    from app.models.research import DocumentChunk
    from app.repositories.jobs import claim
    from app.services.ingestion import run_ingest_job

    document = pymupdf.open()
    document.set_metadata({"title": "Original PDF Title", "author": "Known Author"})
    for text in [
        "Abstract\nGrounded citations refer to physical pages.\nIntroduction\nPDF evidence.",
        "Results\nThe experiment obtained 87 percent accuracy on page two.",
    ]:
        document.new_page().insert_text((72, 72), text)
    original = document.tobytes()
    document.close()
    app = create_app(resources.settings)
    app.state.resources = resources
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        request_id = str(uuid4())
        response = await client.post(
            "/api/v1/documents",
            files={"file": ("../original.pdf", original, "application/pdf")},
            data={"request_id": request_id},
        )
        assert response.status_code == 202, response.text
        references = response.json()
        repeated = await client.post(
            "/api/v1/documents",
            files={"file": ("same.pdf", original, "application/pdf")},
            data={"request_id": request_id},
        )
        assert repeated.json() == references
        async with resources.sessions() as session:
            job = await session.get(BackgroundJob, references["job_id"])
            job_id, payload, generation = job.id, job.payload, job.generation
        token = await claim(resources.sessions, job_id, generation)
        await run_ingest_job(resources, job_id, generation, token, payload)
        paper = (await client.get(f"/api/v1/papers/{references['paper_id']}")).json()
        assert paper["title"] == "Original PDF Title" and paper["authors"] == ["Known Author"]
        assert paper["year"] is None and paper["document_status"] == "ready"
        downloaded = await client.get(f"/api/v1/documents/{references['document_id']}/download")
        assert (
            downloaded.content == original
            and downloaded.headers["content-type"] == "application/pdf"
        )
        async with resources.sessions() as session:
            # Section-aware chunks may span pages: page is the first, page_end the last.
            chunk = await session.scalar(
                select(DocumentChunk).where(
                    DocumentChunk.document_id == references["document_id"],
                    DocumentChunk.text.contains("87 percent"),
                )
            )
        citation = await client.get(
            f"/api/v1/documents/{references['document_id']}/chunks/{chunk.id}"
        )
        assert citation.json()["page"] <= 2 and citation.json()["page_end"] == 2
        assert "87 percent" in citation.json()["excerpt"]
        wrong_document = await client.get(f"/api/v1/documents/{uuid4()}/chunks/{chunk.id}")
        assert wrong_document.status_code == 404
        completed = (await client.get(f"/api/v1/jobs/{job_id}")).json()
        assert completed["state"] == "completed"


async def test_upload_rejects_invalid_signature_and_stores_scanned_failure(resources):
    import pymupdf

    from app.main import create_app
    from app.models.jobs import BackgroundJob
    from app.repositories.jobs import claim
    from app.services.ingestion import run_ingest_job

    app = create_app(resources.settings)
    app.state.resources = resources
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        invalid = await client.post(
            "/api/v1/documents",
            files={"file": ("wrong.pdf", b"Not a PDF", "application/pdf")},
            data={"request_id": str(uuid4())},
        )
        assert invalid.status_code == 415 and invalid.json()["code"] == "INVALID_PDF_SIGNATURE"
        document = pymupdf.open()
        document.new_page()
        original = document.tobytes()
        document.close()
        response = await client.post(
            "/api/v1/documents",
            files={"file": ("scan.pdf", original, "application/pdf")},
            data={"request_id": str(uuid4())},
        )
        async with resources.sessions() as session:
            job = await session.get(BackgroundJob, response.json()["job_id"])
            job_id, payload = job.id, job.payload
        token = await claim(resources.sessions, job_id, 1)
        await run_ingest_job(resources, job_id, 1, token, payload)
        state = (await client.get(f"/api/v1/jobs/{job_id}")).json()
        assert state["state"] == "failed" and state["error"]["code"] == "OCR_REQUIRED"
        paper = (await client.get(f"/api/v1/papers/{response.json()['paper_id']}")).json()
        assert paper["document_status"] == "failed"


async def test_eligible_failed_job_retry_is_durable_and_paid_retry_is_blocked(resources):
    from app.main import create_app
    from app.models.jobs import JobOutbox
    from app.repositories.jobs import enqueue

    async with resources.sessions() as session, session.begin():
        job = await enqueue(session, kind="canary", payload={"message": "retry"})
        job.state, job.stage, job.attempts = "failed", "failed", 3
        job.error_code, job.error_message = "JOB_EXECUTION_FAILED", "Execution failed."
        job_id = job.id
        summary = await enqueue(session, kind="summary", payload={"paid_call_inflight": True})
        summary.state, summary.stage = "failed", "failed"
        summary.error_code = "GENERATION_OUTCOME_UNKNOWN"
        summary_id = summary.id
    app = create_app(resources.settings)
    app.state.resources = resources
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        retried = await client.post(f"/api/v1/jobs/{job_id}/retry")
        assert retried.status_code == 202, retried.text
        assert retried.json()["state"] == "queued" and retried.json()["attempts"] == 0
        assert retried.json()["generation"] == 2
        active = await client.post(f"/api/v1/jobs/{job_id}/retry")
        assert active.status_code == 409
        paid = await client.post(f"/api/v1/jobs/{summary_id}/retry")
        assert paid.status_code == 409 and paid.json()["code"] == "NEW_GENERATION_REQUEST_REQUIRED"
    async with resources.sessions() as session:
        outbox = await session.scalar(
            select(JobOutbox).where(JobOutbox.job_id == job_id, JobOutbox.generation == 2)
        )
        assert outbox is not None and outbox.delivered_at is None


async def test_duplicate_pdf_request_uuid_cannot_be_reused_for_different_original(resources):
    import pymupdf

    from app.main import create_app

    def synthetic(text):
        document = pymupdf.open()
        document.new_page().insert_text((72, 72), text)
        data = document.tobytes()
        document.close()
        return data

    original, other = synthetic("Original research evidence"), synthetic("Other research evidence")
    app = create_app(resources.settings)
    app.state.resources = resources
    first_id, duplicate_id = str(uuid4()), str(uuid4())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        first = await client.post(
            "/api/v1/documents",
            files={"file": ("original.pdf", original, "application/pdf")},
            data={"request_id": first_id},
        )
        duplicate = await client.post(
            "/api/v1/documents",
            files={"file": ("original.pdf", original, "application/pdf")},
            data={"request_id": duplicate_id},
        )
        assert duplicate.status_code == 202 and duplicate.json() == first.json()
        conflicting = await client.post(
            "/api/v1/documents",
            files={"file": ("other.pdf", other, "application/pdf")},
            data={"request_id": duplicate_id},
        )
        assert conflicting.status_code == 409
        assert conflicting.json()["code"] == "UPLOAD_REQUEST_CONFLICT"


async def test_upload_can_resume_after_real_storage_connection_failure(resources):
    import pymupdf
    from minio import Minio

    from app.integrations.storage import read_object
    from app.main import create_app
    from app.models.research import Document

    document = pymupdf.open()
    document.new_page().insert_text((72, 72), "Storage recovery preserves the original evidence.")
    original = document.tobytes()
    document.close()
    actual_storage = resources.storage
    resources.storage = Minio(
        "127.0.0.1:1",
        access_key="unused",
        secret_key="unused-secret",
        secure=False,
        http_client=resources.storage_pool,
    )
    app = create_app(resources.settings)
    app.state.resources = resources
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        failed = await client.post(
            "/api/v1/documents",
            files={"file": ("recover.pdf", original, "application/pdf")},
            data={"request_id": str(uuid4())},
        )
        assert failed.status_code == 503
        resources.storage = actual_storage
        retried = await client.post(
            "/api/v1/documents",
            files={"file": ("recover.pdf", original, "application/pdf")},
            data={"request_id": str(uuid4())},
        )
        assert retried.status_code == 202, retried.text
        status = (await client.get(f"/api/v1/jobs/{retried.json()['job_id']}")).json()
        assert status["state"] == "queued" and status["generation"] == 2
        async with resources.sessions() as session:
            saved = await session.get(Document, retried.json()["document_id"])
            key = saved.object_key
        restored = await resources.storage_call(
            read_object, resources.storage, resources.settings.minio_bucket, key, 1024 * 1024
        )
        assert restored == original
        from uuid import UUID

        from app.repositories.jobs import claim
        from app.services.ingestion import run_ingest_job

        job_id = UUID(retried.json()["job_id"])
        token = await claim(resources.sessions, job_id, 2)
        await run_ingest_job(
            resources, job_id, 2, token, {"document_id": retried.json()["document_id"]}
        )
        paper = (await client.get(f"/api/v1/papers/{retried.json()['paper_id']}")).json()
        assert paper["document_status"] == "ready"


async def test_configured_metadata_fallback_uses_actual_http_and_copies_evidence(resources):
    import json
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    import pymupdf
    from pydantic import SecretStr

    from app.main import create_app
    from app.models.jobs import BackgroundJob
    from app.repositories.jobs import claim
    from app.services.ingestion import run_ingest_job

    requests = []

    class Provider(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append(request)
            metadata = {
                "title": "Traceable Research Systems",
                "authors": ["Ada Researcher"],
                "year": 2024,
                "abstract": None,
                "doi": "10.5555/cs593.fixture",
            }
            body = json.dumps(
                {
                    "id": "resp_metadata_fixture",
                    "object": "response",
                    "created_at": 0,
                    "status": "completed",
                    "model": "gpt-5.6-luna",
                    "output": [
                        {
                            "id": "msg_metadata",
                            "type": "message",
                            "role": "assistant",
                            "status": "completed",
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": json.dumps(metadata),
                                    "annotations": [],
                                }
                            ],
                        }
                    ],
                    "usage": {"input_tokens": 10, "output_tokens": 20, "total_tokens": 30},
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    resources.settings.openai_api_key = SecretStr("http-fixture-only")
    resources.settings.openai_base_url = f"http://127.0.0.1:{server.server_port}/v1"
    document = pymupdf.open()
    document.new_page().insert_text(
        (72, 72),
        "Traceable Research Systems\nAda Researcher\n2024\n"
        "DOI: 10.5555/cs593.fixture\nEvidence for metadata extraction.",
    )
    original = document.tobytes()
    document.close()
    app = create_app(resources.settings)
    app.state.resources = resources
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/v1/documents",
                files={"file": ("unknown-metadata.pdf", original, "application/pdf")},
                data={"request_id": str(uuid4())},
            )
            async with resources.sessions() as session:
                job = await session.get(BackgroundJob, response.json()["job_id"])
                job_id, payload = job.id, job.payload
            token = await claim(resources.sessions, job_id, 1)
            await run_ingest_job(resources, job_id, 1, token, payload)
            paper = (await client.get(f"/api/v1/papers/{response.json()['paper_id']}")).json()
            assert paper["title"] == "Traceable Research Systems"
            assert paper["authors"] == ["Ada Researcher"] and paper["year"] == 2024
            assert paper["document_status"] == "ready"
            assert len(requests) == 1 and requests[0]["store"] is False
    finally:
        await asyncio.to_thread(server.shutdown)
        server.server_close()
        thread.join(timeout=2)


@pytest.mark.parametrize("termination", ["expired_lease", "actor_failure"])
async def test_terminal_ingest_failure_updates_document_and_job_atomically(resources, termination):
    from datetime import UTC, datetime, timedelta

    import pymupdf

    from app.main import create_app
    from app.models.jobs import BackgroundJob
    from app.repositories.jobs import claim, fail, recover

    document = pymupdf.open()
    document.new_page().insert_text((72, 72), "Terminal failure must stop paper polling.")
    original = document.tobytes()
    document.close()
    app = create_app(resources.settings)
    app.state.resources = resources
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/documents",
            files={"file": ("terminal.pdf", original, "application/pdf")},
            data={"request_id": str(uuid4())},
        )
        from uuid import UUID

        job_id = UUID(response.json()["job_id"])
        token = await claim(resources.sessions, job_id, 1)
        async with resources.sessions() as session, session.begin():
            job = await session.get(BackgroundJob, job_id)
            job.attempts = 3
            if termination == "expired_lease":
                job.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        if termination == "expired_lease":
            await recover(resources.sessions)
        else:
            await fail(resources.sessions, job_id, 1, token)
        state = (await client.get(f"/api/v1/jobs/{job_id}")).json()
        paper = (await client.get(f"/api/v1/papers/{response.json()['paper_id']}")).json()
        assert state["state"] == "failed" and state["attempts"] == 3
        assert paper["document_status"] == "failed"


async def test_missing_retained_original_can_be_reuploaded_and_ingested(resources):
    from uuid import UUID

    import pymupdf

    from app.main import create_app
    from app.models.jobs import BackgroundJob
    from app.models.research import Document
    from app.repositories.jobs import claim
    from app.services.ingestion import run_ingest_job

    document = pymupdf.open()
    document.new_page().insert_text((72, 72), "Recover a missing retained original safely.")
    original = document.tobytes()
    document.close()
    app = create_app(resources.settings)
    app.state.resources = resources
    request_id = str(uuid4())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        first = await client.post(
            "/api/v1/documents",
            files={"file": ("missing.pdf", original, "application/pdf")},
            data={"request_id": request_id},
        )
        references = first.json()
        job_id = UUID(references["job_id"])
        async with resources.sessions() as session:
            saved = await session.get(Document, references["document_id"])
            key = saved.object_key
            job = await session.get(BackgroundJob, job_id)
            payload = job.payload
        await resources.storage_call(
            resources.storage.remove_object, resources.settings.minio_bucket, key
        )
        token = await claim(resources.sessions, job_id, 1)
        await run_ingest_job(resources, job_id, 1, token, payload)
        failed = (await client.get(f"/api/v1/jobs/{job_id}")).json()
        assert failed["state"] == "failed" and failed["error"]["code"] == "STORAGE_OBJECT_MISSING"
        resumed = await client.post(
            "/api/v1/documents",
            files={"file": ("missing.pdf", original, "application/pdf")},
            data={"request_id": request_id},
        )
        assert resumed.json() == references
        token = await claim(resources.sessions, job_id, 2)
        await run_ingest_job(resources, job_id, 2, token, payload)
        paper = (await client.get(f"/api/v1/papers/{references['paper_id']}")).json()
        assert paper["document_status"] == "ready"
        assert (
            await client.get(f"/api/v1/documents/{references['document_id']}/download")
        ).content == original


async def test_pdf_upload_size_limit_rejects_before_persisting_document(resources):
    from app.main import create_app
    from app.models.research import Document
    from app.services.uploads import MAX_UPLOAD_BYTES

    app = create_app(resources.settings)
    app.state.resources = resources
    oversized = b"%PDF-1.7\n" + b"x" * MAX_UPLOAD_BYTES
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/documents",
            files={"file": ("too-big.pdf", oversized, "application/pdf")},
            data={"request_id": str(uuid4())},
        )
    assert response.status_code == 413 and response.json()["code"] == "PDF_SIZE_LIMIT"
    async with resources.sessions() as session:
        assert await session.scalar(select(Document.id)) is None


async def test_canonical_paper_route_refetches_provider_and_rejects_browser_metadata(resources):
    from app.main import create_app

    requests = []

    def provider(request):
        requests.append(request.url.path)
        return httpx.Response(
            200,
            json={
                "id": "https://openalex.org/W567",
                "display_name": "Canonical server title",
                "publication_year": 2024,
                "doi": "https://doi.org/10.1000/canonical",
                "authorships": [],
                "abstract_inverted_index": None,
            },
        )

    await resources.http.aclose()
    resources.http = httpx.AsyncClient(transport=httpx.MockTransport(provider))
    app = create_app(resources.settings)
    app.state.resources = resources
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        invalid = await client.post(
            "/api/v1/papers",
            json={"provider": "openalex", "external_id": "W567", "title": "Untrusted title"},
        )
        assert invalid.status_code == 422 and not requests
        first = await client.post(
            "/api/v1/papers", json={"provider": "openalex", "external_id": "W567"}
        )
        second = await client.post(
            "/api/v1/papers", json={"provider": "openalex", "external_id": "W567"}
        )
        assert first.status_code == 201 and second.status_code == 200
        assert (
            first.json()["title"] == "Canonical server title"
            and first.json()["id"] == second.json()["id"]
        )
        library = (await client.get("/api/v1/papers?q=Canonical")).json()
        assert (
            len(library["items"]) == 1 and library["items"][0]["document_status"] == "metadata_only"
        )
    assert requests == ["/works/W567", "/works/W567"]


async def test_citation_excerpt_preserves_late_evidence_and_denies_another_document(resources):
    """Given late chunk evidence, when opened, then the complete selected source stays visible."""
    from app.main import create_app
    from app.models.research import Document, DocumentChunk, Paper

    support = "The measured threshold is 9.75 and supports the answer on physical page seven."
    text = "Background context. " * 90 + support + " Further discussion." * 30
    assert text.index(support) > 1200 and len(text) <= 3200
    async with resources.sessions() as session, session.begin():
        paper = Paper(title="Citation evidence fixture", metadata_provenance={})
        session.add(paper)
        await session.flush()
        documents = [
            Document(
                paper_id=paper.id,
                status="ready",
                object_key=f"citation-fixture/{uuid4()}.pdf",
                sha256=uuid4().hex * 2,
                original_filename="citation.pdf",
                byte_size=1,
                request_id=uuid4(),
                page_count=7,
                warnings=[],
            )
            for _ in range(2)
        ]
        session.add_all(documents)
        await session.flush()
        chunk = DocumentChunk(
            document_id=documents[0].id,
            page=7,
            text=text,
            ordinal=0,
            chunk_set="test",
            page_end=7,
            context_text=text,
            token_count=len(text),
        )
        session.add(chunk)
        await session.flush()
        document_id, other_document_id, chunk_id = documents[0].id, documents[1].id, chunk.id
    app = create_app(resources.settings)
    app.state.resources = resources
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        response = await client.get(f"/api/v1/documents/{document_id}/chunks/{chunk_id}")
        assert response.status_code == 200
        citation = response.json()
        assert support in citation["excerpt"]
        assert citation["excerpt"] == text
        assert citation["page"] == 7 and citation["document_id"] == str(document_id)
        denied = await client.get(f"/api/v1/documents/{other_document_id}/chunks/{chunk_id}")
        assert denied.status_code == 404 and denied.json()["code"] == "CITATION_NOT_FOUND"
        assert support not in denied.text
