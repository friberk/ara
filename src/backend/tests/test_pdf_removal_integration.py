"""Removing a paper's PDF from the reader, and deleting PDFs nothing uses any more (ARA-097).

DELETE /papers/{id}/pdf detaches the paper's current PDF, so the reader returns to its upload
state and new conversations need a new PDF. Older conversations continue as they are: a PDF a
chat pins stays whole (pages, passages, sections, embeddings, indexes, section summaries, its
summaries and its stored file), and the chat keeps asking about it. Every PDF of the paper that
no chat pins is deleted, with its summaries, its queued work and, through ARA-095's durable
`storage_cleanup`, its stored file. The same clean-up runs when a chat that pinned a PDF is
deleted or drops that paper. Uploading a kept PDF's file again makes it the paper's PDF again.
"""

import hashlib
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select, update
from test_paper_deletion_integration import client_for, count, full_paper

from app.models.jobs import BackgroundJob
from app.models.research import (
    ChatMessage,
    ChatPaper,
    ChatSession,
    Document,
    DocumentChunk,
    DocumentPage,
    DocumentUploadRequest,
    Paper,
    PaperSummary,
)
from app.models.retrieval import (
    ChunkEmbedding,
    DocumentSection,
    RetrievalIndex,
    SectionSummary,
)
from app.repositories.jobs import enqueue
from tests.support.chats import new_chat
from tests.support.cleanup import cleanup_job
from tests.support.evidence import seed_structured

pytestmark = pytest.mark.integration

PDF = b"%PDF-1.7\n% ARA-097 removal fixture\n"


async def contents(resources, documents) -> dict[str, int]:
    """Rows that hold PDFs' text, structure, search index and summaries."""
    where = {
        "pages": (DocumentPage, DocumentPage.document_id),
        "sections": (DocumentSection, DocumentSection.document_id),
        "chunks": (DocumentChunk, DocumentChunk.document_id),
        "embeddings": (ChunkEmbedding, ChunkEmbedding.document_id),
        "indexes": (RetrievalIndex, RetrievalIndex.document_id),
        "section_summaries": (SectionSummary, SectionSummary.document_id),
        "summaries": (PaperSummary, PaperSummary.document_id),
        "upload_requests": (DocumentUploadRequest, DocumentUploadRequest.document_id),
    }
    return {
        name: await count(resources, model, column.in_(documents))
        for name, (model, column) in where.items()
    }


async def with_section_summary(resources, document_id) -> None:
    async with resources.sessions() as session, session.begin():
        section = DocumentSection(
            document_id=document_id,
            chunk_set="layout-v1:evidence",
            ordinal=1,
            title="Results",
            level=1,
            page=2,
            page_end=2,
        )
        session.add(section)
        await session.flush()
        session.add(
            SectionSummary(
                document_id=document_id,
                section_id=section.id,
                chunk_set=section.chunk_set,
                title="Results",
                page=2,
                page_end=2,
                ordinal=0,
                content="A summary.",
                sources=[],
                context_text="A summary.",
                token_count=2,
                model="gpt-5.6-luna",
                reasoning_effort="low",
                usage={},
            )
        )


async def with_summary(resources, paper_id, document_id) -> None:
    async with resources.sessions() as session, session.begin():
        session.add(
            PaperSummary(
                paper_id=paper_id,
                document_id=document_id,
                model="gpt-5.6-luna",
                reasoning_effort="low",
                content="An earlier summary.",
                citations=[],
            )
        )


async def stored_as(resources, document_id, data: bytes) -> None:
    """Give a seeded PDF the digest of `data` and the completed ingest an upload leaves."""
    async with resources.sessions() as session, session.begin():
        job = await enqueue(session, kind="ingest", payload={"document_id": str(document_id)})
        job.state, job.stage, job.progress = "completed", "completed", 100
        await session.execute(
            update(Document)
            .where(Document.id == document_id)
            .values(sha256=hashlib.sha256(data).hexdigest(), ingest_job_id=job.id)
        )


async def document(resources, document_id) -> Document | None:
    async with resources.sessions() as session:
        return await session.get(Document, document_id)


async def cleanups(resources) -> int:
    return await count(resources, BackgroundJob, BackgroundJob.kind == "storage_cleanup")


async def test_removal_detaches_the_pdf_keeps_what_a_chat_uses_and_deletes_the_rest(resources):
    """Given a current PDF a chat pins and an earlier version no chat uses, when the PDF is
    removed, then the paper has no PDF, the pinned PDF stays whole, the earlier version goes
    with its content and summary, and one cleanup job names only its stored file."""
    seeded = await full_paper(resources, "Removed PDF paper", work_id="W1")
    pinned, older = seeded["document"], seeded["older"]
    await with_section_summary(resources, pinned)
    await with_section_summary(resources, older)
    await with_summary(resources, seeded["paper"], older)
    before = await document(resources, pinned)
    kept = await contents(resources, [pinned])
    (older_key,) = [(await document(resources, older)).object_key]

    async with client_for(resources) as client:
        response = await client.delete(f"/api/v1/papers/{seeded['paper']}/pdf")
        detail = await client.get(f"/api/v1/papers/{seeded['paper']}")

    assert response.status_code == 204, response.text
    assert detail.json()["document_status"] == "metadata_only"
    assert detail.json()["active_document_id"] is None
    after = await document(resources, pinned)
    assert (after.status, after.object_key, after.sha256) == (
        before.status,
        before.object_key,
        before.sha256,
    )
    assert await contents(resources, [pinned]) == kept
    assert kept["section_summaries"] == 1 and kept["summaries"] == 1
    assert await document(resources, older) is None
    assert set((await contents(resources, [older])).values()) == {0}
    job = await cleanup_job(resources)
    assert job.state == "queued" and job.payload["object_keys"] == [older_key]
    assert job.payload["paper_titles"] == ["Removed PDF paper"]


async def test_older_chats_keep_reading_citing_and_asking_about_their_pdf(resources):
    """Given a chat over the paper, when its PDF is removed, then the chat still lists it with
    its pinned PDF, its passages, file facts and search scope stay, and nothing marks it."""
    from app.services.chat import chat_scopes

    seeded = await full_paper(resources, "Removed PDF paper", work_id="W1")
    async with client_for(resources) as client:
        assert (await client.delete(f"/api/v1/papers/{seeded['paper']}/pdf")).status_code == 204
        chat = await client.get(f"/api/v1/chats/{seeded['chat']}")
        history = await client.get(f"/api/v1/chats/{seeded['chat']}/messages")
        passage = await client.get(
            f"/api/v1/documents/{seeded['document']}/chunks/{seeded['chunks'][1]}"
        )
        facts = await client.get(f"/api/v1/documents/{seeded['document']}")

    assert chat.status_code == 200, chat.text
    assert chat.json()["papers"][0]["document_id"] == str(seeded["document"])
    assert "pdf_removed" not in chat.json()["papers"][0]
    answer = history.json()["items"][-1]
    assert answer["citations"][0]["paper_id"] == str(seeded["paper"])
    assert passage.status_code == 200, passage.text
    assert facts.status_code == 200 and facts.json()["status"] == "ready"
    async with resources.sessions() as session:
        scopes, _ = await chat_scopes(session, seeded["chat"])
    assert [scope.document_id for scope in scopes] == [seeded["document"]]


async def test_a_pdf_no_chat_uses_is_deleted_with_its_section_summaries(resources):
    """Given a paper whose PDF no chat uses, when it is removed, then the PDF and everything it
    held go, and its stored file is queued for removal."""
    paper, pdf, _ = await seed_structured(resources, title="Unused PDF paper")
    await with_section_summary(resources, pdf)
    await with_summary(resources, paper, pdf)
    key = (await document(resources, pdf)).object_key
    async with client_for(resources) as client:
        assert (await client.delete(f"/api/v1/papers/{paper}/pdf")).status_code == 204
    assert await document(resources, pdf) is None
    assert set((await contents(resources, [pdf])).values()) == {0}
    assert (await cleanup_job(resources)).payload["object_keys"] == [key]


async def test_the_same_file_uploaded_again_brings_the_kept_pdf_back(resources):
    """Given a removed PDF a chat keeps, when the same file is uploaded into the paper again,
    then that PDF is the paper's current one again, with nothing re-read."""
    seeded = await full_paper(resources, "Removed PDF paper", work_id="W1")
    await stored_as(resources, seeded["document"], PDF)
    async with client_for(resources) as client:
        assert (await client.delete(f"/api/v1/papers/{seeded['paper']}/pdf")).status_code == 204
        response = await client.post(
            "/api/v1/documents",
            files={"file": ("again.pdf", PDF, "application/pdf")},
            data={"request_id": str(uuid4()), "paper_id": str(seeded["paper"])},
        )
        detail = await client.get(f"/api/v1/papers/{seeded['paper']}")
    assert response.status_code == 202, response.text
    assert response.json()["document_id"] == str(seeded["document"])
    assert response.json()["duplicate"] is False
    assert detail.json()["active_document_id"] == str(seeded["document"])
    assert detail.json()["document_status"] == "ready"


async def test_the_same_file_uploaded_from_home_brings_back_a_paper_without_a_pdf(resources):
    """Given a kept PDF whose paper has no PDF, when its file is uploaded without choosing a
    paper, then that paper opens with the PDF current again."""
    seeded = await full_paper(resources, "Removed PDF paper", work_id="W1")
    await stored_as(resources, seeded["document"], PDF)
    async with client_for(resources) as client:
        assert (await client.delete(f"/api/v1/papers/{seeded['paper']}/pdf")).status_code == 204
        response = await client.post(
            "/api/v1/documents",
            files={"file": ("again.pdf", PDF, "application/pdf")},
            data={"request_id": str(uuid4())},
        )
        detail = await client.get(f"/api/v1/papers/{seeded['paper']}")
    assert response.json()["paper_id"] == str(seeded["paper"])
    assert detail.json()["active_document_id"] == str(seeded["document"])


async def test_the_same_file_after_a_full_removal_is_a_new_pdf(resources):
    """Given a removed PDF no chat kept, when the same file is uploaded again, then it is a new
    PDF that becomes current and is read again."""
    paper, pdf, _ = await seed_structured(resources, title="Unused PDF paper")
    async with resources.sessions() as session, session.begin():
        await session.execute(
            update(Document)
            .where(Document.id == pdf)
            .values(sha256=hashlib.sha256(PDF).hexdigest())
        )
    async with client_for(resources) as client:
        assert (await client.delete(f"/api/v1/papers/{paper}/pdf")).status_code == 204
        response = await client.post(
            "/api/v1/documents",
            files={"file": ("again.pdf", PDF, "application/pdf")},
            data={"request_id": str(uuid4()), "paper_id": str(paper)},
        )
        detail = await client.get(f"/api/v1/papers/{paper}")
    assert response.status_code == 202, response.text
    assert response.json()["document_id"] != str(pdf)
    assert detail.json()["document_status"] == "processing"


async def test_the_preview_says_what_goes_and_what_stays_and_changes_nothing(resources):
    seeded = await full_paper(resources, "Removed PDF paper", work_id="W1")
    await with_summary(resources, seeded["paper"], seeded["older"])
    async with resources.sessions() as session, session.begin():
        await enqueue(
            session,
            kind="summary",
            payload={"paper_id": str(seeded["paper"]), "document_id": str(seeded["older"])},
        )
        await enqueue(
            session,
            kind="summary",
            payload={"paper_id": str(seeded["paper"]), "document_id": str(seeded["document"])},
        )
    before = await contents(resources, [seeded["document"], seeded["older"]])
    async with client_for(resources) as client:
        response = await client.get(f"/api/v1/papers/{seeded['paper']}/pdf/removal-preview")
        missing = await client.get(f"/api/v1/papers/{uuid4()}/pdf/removal-preview")
    assert response.status_code == 200, response.text
    assert response.json() == {
        "deleted_pdfs": 1,
        "kept_pdfs": 1,
        "summaries": 1,
        "chats": [{"id": str(seeded["chat"]), "title": "About Removed PDF paper"}],
        "active_jobs": 1,
        "answering": False,
    }
    assert missing.status_code == 404 and missing.json()["code"] == "PAPER_NOT_FOUND"
    assert await contents(resources, [seeded["document"], seeded["older"]]) == before


async def test_removal_waits_for_an_answer_being_written_from_the_pdf(resources):
    seeded = await full_paper(resources, "Removed PDF paper", work_id="W1")
    async with resources.sessions() as session, session.begin():
        session.add(
            ChatMessage(
                session_id=seeded["chat"],
                role="assistant",
                state="processing",
                lease_expires_at=datetime.now(UTC) + timedelta(minutes=5),
            )
        )
    async with client_for(resources) as client:
        preview = await client.get(f"/api/v1/papers/{seeded['paper']}/pdf/removal-preview")
        response = await client.delete(f"/api/v1/papers/{seeded['paper']}/pdf")
        detail = await client.get(f"/api/v1/papers/{seeded['paper']}")
    assert preview.json()["answering"] is True
    assert response.status_code == 409 and response.json()["code"] == "CHAT_BUSY"
    assert detail.json()["active_document_id"] == str(seeded["document"])
    assert await document(resources, seeded["older"]) is not None
    assert await cleanup_job(resources) is None


async def test_work_on_deleted_pdfs_stops_and_work_on_kept_pdfs_carries_on(resources):
    """Given queued jobs for the earlier version and for the PDF a chat keeps, when the PDF is
    removed, then the earlier version's jobs fail with PDF_REMOVED and the kept PDF's stay."""
    seeded = await full_paper(resources, "Removed PDF paper", work_id="W1")
    async with resources.sessions() as session, session.begin():
        stopped = [
            (await enqueue(session, kind=kind, payload=payload)).id
            for kind, payload in (
                ("ingest", {"document_id": str(seeded["older"])}),
                (
                    "summary",
                    {"paper_id": str(seeded["paper"]), "document_id": str(seeded["older"])},
                ),
            )
        ]
        running = await session.get(BackgroundJob, stopped[0])
        running.state, running.lease_token = "processing", uuid4()
        running.lease_expires_at = datetime.now(UTC) + timedelta(minutes=5)
        carried = (
            await enqueue(
                session,
                kind="embed",
                payload={"document_id": str(seeded["document"]), "index_id": str(uuid4())},
            )
        ).id
    async with client_for(resources) as client:
        assert (await client.delete(f"/api/v1/papers/{seeded['paper']}/pdf")).status_code == 204
    async with resources.sessions() as session:
        rows = (
            await session.scalars(select(BackgroundJob).where(BackgroundJob.id.in_(stopped)))
        ).all()
        assert {(row.state, row.error_code, row.lease_token) for row in rows} == {
            ("failed", "PDF_REMOVED", None)
        }
        assert (await session.get(BackgroundJob, carried)).state == "queued"


async def test_a_repeat_changes_nothing_and_an_unknown_paper_answers_404(resources):
    seeded = await full_paper(resources, "Removed PDF paper", work_id="W1")
    async with client_for(resources) as client:
        assert (await client.delete(f"/api/v1/papers/{seeded['paper']}/pdf")).status_code == 204
        again = await client.delete(f"/api/v1/papers/{seeded['paper']}/pdf")
        preview = await client.get(f"/api/v1/papers/{seeded['paper']}/pdf/removal-preview")
        unknown = await client.delete(f"/api/v1/papers/{uuid4()}/pdf")
    assert again.status_code == 204
    assert preview.json()["deleted_pdfs"] == 0 and preview.json()["kept_pdfs"] == 1
    assert unknown.status_code == 404 and unknown.json()["code"] == "PAPER_NOT_FOUND"
    assert await cleanups(resources) == 1
    assert await document(resources, seeded["document"]) is not None


async def test_deleting_the_last_chat_of_a_kept_pdf_deletes_the_pdf(resources):
    """Given a removed PDF two chats keep, when one chat is deleted, then the PDF stays; when the
    other is deleted too, then the PDF goes and its file is queued for removal."""
    seeded = await full_paper(resources, "Removed PDF paper", work_id="W1")
    second = await new_chat(resources, (seeded["paper"], seeded["document"]), title="Second")
    async with client_for(resources) as client:
        assert (await client.delete(f"/api/v1/papers/{seeded['paper']}/pdf")).status_code == 204
        jobs = await cleanups(resources)
        assert (await client.delete(f"/api/v1/chats/{second}")).status_code == 204
        assert await document(resources, seeded["document"]) is not None
        assert await cleanups(resources) == jobs
        key = (await document(resources, seeded["document"])).object_key
        assert (await client.delete(f"/api/v1/chats/{seeded['chat']}")).status_code == 204
    assert await document(resources, seeded["document"]) is None
    assert set((await contents(resources, [seeded["document"]])).values()) == {0}
    assert (await cleanup_job(resources)).payload["object_keys"] == [key]


async def test_deleting_a_chat_keeps_the_papers_current_pdf(resources):
    paper, pdf, _ = await seed_structured(resources, title="Current PDF paper")
    chat = await new_chat(resources, (paper, pdf))
    async with client_for(resources) as client:
        assert (await client.delete(f"/api/v1/chats/{chat}")).status_code == 204
    assert await document(resources, pdf) is not None
    assert await cleanups(resources) == 0


async def test_deleting_the_last_chat_of_an_earlier_version_deletes_it(resources):
    """Given a chat pinned to a PDF that a replacement superseded, when the chat is deleted,
    then that earlier version goes, and the current PDF stays."""
    paper, old, _ = await seed_structured(resources, title="Replaced PDF paper")
    chat = await new_chat(resources, (paper, old))
    _, current, _ = await seed_structured(resources, title="Holder")
    async with resources.sessions() as session, session.begin():
        await session.execute(update(Document).where(Document.id == current).values(paper_id=paper))
        await session.execute(
            update(Paper).where(Paper.id == paper).values(active_document_id=current)
        )
    async with client_for(resources) as client:
        assert (await client.delete(f"/api/v1/chats/{chat}")).status_code == 204
    assert await document(resources, old) is None
    assert await document(resources, current) is not None


async def test_dropping_a_paper_from_a_chat_deletes_its_pdf_when_nothing_else_uses_it(resources):
    """Given a chat over two papers whose second paper's PDF was removed, when that paper is
    dropped from the chat, then its kept PDF goes; the first paper's PDF stays."""
    first, first_pdf, _ = await seed_structured(resources, title="First paper")
    second, second_pdf, _ = await seed_structured(resources, title="Second paper")
    chat = await new_chat(resources, (first, first_pdf), (second, second_pdf))
    async with client_for(resources) as client:
        assert (await client.delete(f"/api/v1/papers/{second}/pdf")).status_code == 204
        assert await document(resources, second_pdf) is not None
        dropped = await client.delete(f"/api/v1/chats/{chat}/papers/{second}")
    assert dropped.status_code == 200, dropped.text
    assert await document(resources, second_pdf) is None
    assert await document(resources, first_pdf) is not None
    assert await count(resources, ChatPaper, ChatPaper.chat_id == chat) == 1
    assert await count(resources, ChatSession, ChatSession.id == chat) == 1


async def test_dropping_a_paper_keeps_its_current_pdf(resources):
    first, first_pdf, _ = await seed_structured(resources, title="First paper")
    second, second_pdf, _ = await seed_structured(resources, title="Second paper")
    chat = await new_chat(resources, (first, first_pdf), (second, second_pdf))
    async with client_for(resources) as client:
        assert (await client.delete(f"/api/v1/chats/{chat}/papers/{second}")).status_code == 200
    assert await document(resources, second_pdf) is not None
    assert await cleanups(resources) == 0


async def test_document_facts_name_the_file_its_pages_size_and_source(resources):
    """The reader's PDF menu reads one PDF's file facts (ARA-097)."""
    paper, pdf, _ = await seed_structured(resources, title="Facts paper")
    async with resources.sessions() as session, session.begin():
        await session.execute(
            update(Document)
            .where(Document.id == pdf)
            .values(acquisition={"method": "provider_download", "provider": "openalex"})
        )
    async with client_for(resources) as client:
        response = await client.get(f"/api/v1/documents/{pdf}")
        missing = await client.get(f"/api/v1/documents/{uuid4()}")
    assert response.status_code == 200, response.text
    body = response.json()
    assert {
        key: body[key]
        for key in ("id", "paper_id", "file_name", "page_count", "byte_size", "status")
    } == {
        "id": str(pdf),
        "paper_id": str(paper),
        "file_name": "structured.pdf",
        "page_count": 4,
        "byte_size": 10,
        "status": "ready",
    }
    assert body["acquisition"]["provider"] == "openalex"
    assert missing.status_code == 404 and missing.json()["code"] == "DOCUMENT_NOT_FOUND"


async def test_deleting_the_paper_later_takes_its_kept_pdf(resources):
    seeded = await full_paper(resources, "Removed PDF paper", work_id="W1")
    async with client_for(resources) as client:
        assert (await client.delete(f"/api/v1/papers/{seeded['paper']}/pdf")).status_code == 204
        preview = await client.get(f"/api/v1/papers/{seeded['paper']}/deletion-preview")
        assert (await client.delete(f"/api/v1/papers/{seeded['paper']}")).status_code == 204
    assert preview.json()["pdfs"] == 1
    assert await count(resources, Document, Document.paper_id == seeded["paper"]) == 0
    assert await count(resources, ChatSession, ChatSession.id == seeded["chat"]) == 0
    assert await count(resources, Paper, Paper.id == seeded["paper"]) == 0
