"""Ingestion persists structured sections and chunks for the current chunk set (ARA-071)."""

from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import func, select, update
from support.structured_pdf import create_structured_pdf

pytestmark = pytest.mark.integration


async def upload(client, resources, tmp_path):
    from app.models.jobs import BackgroundJob

    original = create_structured_pdf(tmp_path / "structured.pdf").read_bytes()
    response = await client.post(
        "/api/v1/documents",
        files={"file": ("structured.pdf", original, "application/pdf")},
        data={"request_id": str(uuid4())},
    )
    assert response.status_code == 202, response.text
    references = response.json()
    async with resources.sessions() as session:
        job = await session.get(BackgroundJob, references["job_id"])
        return references, job.payload


async def ingest(resources, job_id, generation, payload):
    from app.repositories.jobs import claim
    from app.services.ingestion import run_ingest_job

    token = await claim(resources.sessions, job_id, generation)
    assert token is not None
    await run_ingest_job(resources, job_id, generation, token, payload)


async def requeue(resources, job_id, generation):
    from app.models.jobs import BackgroundJob

    async with resources.sessions() as session, session.begin():
        await session.execute(
            update(BackgroundJob)
            .where(BackgroundJob.id == job_id)
            .values(
                state="queued",
                generation=generation,
                attempts=0,
                lease_token=None,
                lease_expires_at=None,
            )
        )


async def count(session, model, document_id):
    return await session.scalar(
        select(func.count()).select_from(model).where(model.document_id == document_id)
    )


def client_for(resources):
    from app.main import create_app

    app = create_app(resources.settings)
    app.state.resources = resources
    return httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test")


async def test_given_structured_pdf_when_ingested_then_sections_and_chunks_persist(
    resources, tmp_path
):
    from app.models.research import Document, DocumentChunk, DocumentPage
    from app.models.retrieval import DocumentSection
    from app.rag.chunking import CHUNK_SET

    async with client_for(resources) as client:
        references, payload = await upload(client, resources, tmp_path)
        document_id = UUID(references["document_id"])
        await ingest(resources, UUID(references["job_id"]), 1, payload)
        async with resources.sessions() as session:
            document = await session.get(Document, document_id)
            assert document.status == "ready"
            assert document.parser == "pymupdf4llm-layout" and document.chunk_set == CHUNK_SET
            assert document.extractor_version == "pymupdf4llm-1.28.2+layout"
            sections = (
                await session.scalars(
                    select(DocumentSection)
                    .where(DocumentSection.document_id == document_id)
                    .order_by(DocumentSection.ordinal)
                )
            ).all()
            chunks = (
                await session.scalars(
                    select(DocumentChunk)
                    .where(DocumentChunk.document_id == document_id)
                    .order_by(DocumentChunk.ordinal)
                )
            ).all()
            pages = await count(session, DocumentPage, document_id)
        assert pages == 4
        assert len(sections) >= 4 and len(chunks) >= 4
        assert {s.chunk_set for s in sections} == {c.chunk_set for c in chunks} == {CHUNK_SET}
        titles = [s.title for s in sections]
        assert titles[-4:] == ["1 Introduction", "2 Method", "3 Results", "References"]
        by_id = {s.id: s for s in sections}
        assert all(by_id[c.section_id].path == c.section_path for c in chunks if c.section_id)
        table = next(c for c in chunks if c.kind == "table")
        assert "Recall@10" in table.text and table.page == 3 and table.bboxes[0][0] == 3
        continuation = next(c for c in chunks if "continues on this page" in c.text)
        assert continuation.section_path[-1] == "2 Method"
        assert (continuation.page, continuation.page_end) == (2, 3)
        assert continuation.heading.endswith("2 Method")
        assert continuation.context_text.startswith("Sparse Retrieval for Scientific QA\n")
        assert any(c.kind == "references" for c in chunks)
        assert all(0 < c.token_count <= 512 for c in chunks)

        source = await client.get(f"/api/v1/documents/{document_id}/chunks/{table.id}")
        assert source.status_code == 200
        body = source.json()
        assert body["page"] == 3 and body["page_end"] == 3 and body["kind"] == "table"
        assert body["section"] == table.heading and body["excerpt"] == table.text
        assert body["bboxes"] == table.bboxes


async def test_given_reingest_then_chunks_are_replaced_not_duplicated(resources, tmp_path):
    from app.models.research import DocumentChunk
    from app.models.retrieval import DocumentSection
    from app.rag.chunking import CHUNK_SET

    async with client_for(resources) as client:
        references, payload = await upload(client, resources, tmp_path)
    document_id, job_id = UUID(references["document_id"]), UUID(references["job_id"])
    await ingest(resources, job_id, 1, payload)

    async def snapshot():
        async with resources.sessions() as session:
            chunks = (
                await session.execute(
                    select(DocumentChunk.chunk_set, DocumentChunk.ordinal, DocumentChunk.text)
                    .where(DocumentChunk.document_id == document_id)
                    .order_by(DocumentChunk.ordinal)
                )
            ).all()
            sections = await count(session, DocumentSection, document_id)
            return [tuple(row) for row in chunks], sections

    first = await snapshot()
    assert first[1] >= 4 and {row[0] for row in first[0]} == {CHUNK_SET}
    async with resources.sessions() as session, session.begin():
        session.add(
            DocumentChunk(
                document_id=document_id,
                chunk_set="obsolete-chunk-set",
                ordinal=0,
                page=1,
                page_end=1,
                text="stale window",
                context_text="stale window",
                token_count=2,
            )
        )
    await requeue(resources, job_id, 2)
    await ingest(resources, job_id, 2, payload)
    assert await snapshot() == first


async def test_given_chunks_saved_then_indexing_hook_runs_in_the_same_transaction(
    resources, tmp_path, monkeypatch
):
    from app.models.research import Document, DocumentChunk
    from app.rag import hooks

    calls = []

    async def failing_hook(session, *, document_id, resources=None):
        visible = await count(session, DocumentChunk, document_id)
        calls.append((document_id, visible, session.in_transaction()))
        raise RuntimeError("index bookkeeping failed")

    monkeypatch.setattr(hooks, "after_chunks_persisted", failing_hook)
    async with client_for(resources) as client:
        references, payload = await upload(client, resources, tmp_path)
    document_id = UUID(references["document_id"])
    with pytest.raises(RuntimeError, match="index bookkeeping failed"):
        await ingest(resources, UUID(references["job_id"]), 1, payload)
    assert len(calls) == 1
    called_with, visible, in_transaction = calls[0]
    assert called_with == document_id and visible >= 4 and in_transaction
    async with resources.sessions() as session:
        document = await session.get(Document, document_id)
        persisted = await count(session, DocumentChunk, document_id)
    assert persisted == 0 and document.status != "ready"


async def test_given_pdf_with_control_characters_when_ingested_then_document_is_ready(
    resources, tmp_path
):
    """A live RAG paper failed ingest: a formula's NUL reached PostgreSQL text."""
    from test_pdf_parser_structured import formula_pdf

    from app.models.jobs import BackgroundJob
    from app.models.research import Document, DocumentChunk, DocumentPage

    path = formula_pdf(tmp_path / "control.pdf", formula="Attention(Q, K, V) = softmax\x00(")
    original = path.read_bytes()
    async with client_for(resources) as client:
        response = await client.post(
            "/api/v1/documents",
            files={"file": ("control.pdf", original, "application/pdf")},
            data={"request_id": str(uuid4())},
        )
        assert response.status_code == 202, response.text
        references = response.json()
        async with resources.sessions() as session:
            payload = (await session.get(BackgroundJob, references["job_id"])).payload
        await ingest(resources, UUID(references["job_id"]), 1, payload)
    document_id = UUID(references["document_id"])
    async with resources.sessions() as session:
        assert (await session.get(Document, document_id)).status == "ready"
        texts = (
            await session.scalars(
                select(DocumentChunk.text).where(DocumentChunk.document_id == document_id)
            )
        ).all()
        assert await count(session, DocumentPage, document_id) == 1
    assert any("softmax\ufffd" in text for text in texts)
