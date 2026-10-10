"""Removing a paper's PDF from the reader (ARA-097).

DELETE /papers/{id}/pdf detaches every PDF of the paper, the current one and earlier versions,
and the reader returns to its upload state. Summaries of those PDFs go, their queued and running
work stops, and ARA-095's durable `storage_cleanup` job removes the stored files. A PDF that no
chat pins is deleted with its pages, passages, sections, embeddings and indexes. A chat pins the
PDF it was asked about (`chat_papers.document_id`, NOT NULL, migration 0010), so a pinned PDF
keeps its row, emptied and marked removed: the chat stays readable, its saved answers keep their
quoted passages, and it takes no new questions.
"""

import hashlib
import io
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select, update
from test_paper_deletion_integration import citation, client_for, count, full_paper

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
from app.models.retrieval import ChunkEmbedding, DocumentSection, RetrievalIndex
from app.repositories.jobs import enqueue
from tests.support.chats import add_turns, new_chat
from tests.support.cleanup import cleanup_job, run_cleanup
from tests.support.evidence import seed_structured

pytestmark = pytest.mark.integration

PDF = b"%PDF-1.7\n% ARA-097 removal fixture\n"


async def content_rows(resources, documents) -> dict[str, int]:
    """Rows that hold a PDF's text, structure and search index."""
    return {
        "pages": await count(resources, DocumentPage, DocumentPage.document_id.in_(documents)),
        "sections": await count(
            resources, DocumentSection, DocumentSection.document_id.in_(documents)
        ),
        "chunks": await count(resources, DocumentChunk, DocumentChunk.document_id.in_(documents)),
        "embeddings": await count(
            resources, ChunkEmbedding, ChunkEmbedding.document_id.in_(documents)
        ),
        "indexes": await count(
            resources, RetrievalIndex, RetrievalIndex.document_id.in_(documents)
        ),
        "upload_requests": await count(
            resources, DocumentUploadRequest, DocumentUploadRequest.document_id.in_(documents)
        ),
    }


async def keys(resources, *documents) -> list[str]:
    async with resources.sessions() as session:
        return sorted(
            (
                await session.scalars(select(Document.object_key).where(Document.id.in_(documents)))
            ).all()
        )


async def test_removing_the_pdf_detaches_every_version_and_queues_storage_cleanup(resources):
    """Given a paper whose current PDF a chat pins and an earlier version no chat uses, when its
    PDF is removed, then the paper has no PDF, the earlier version is deleted, the pinned one keeps
    an empty removed row, summaries go, and one cleanup job names both stored files."""
    seeded = await full_paper(resources, "Removed PDF paper", work_id="W1")
    other = await full_paper(resources, "Untouched paper", work_id="W2")
    pinned, older = seeded["document"], seeded["older"]
    stored_keys = await keys(resources, pinned, older)
    untouched = await content_rows(resources, [other["document"], other["older"]])

    async with client_for(resources) as client:
        response = await client.delete(f"/api/v1/papers/{seeded['paper']}/pdf")
        detail = await client.get(f"/api/v1/papers/{seeded['paper']}")
        fulltext = await client.get(f"/api/v1/papers/{seeded['paper']}/fulltext")

    assert response.status_code == 204, response.text
    assert detail.json()["document_status"] == "metadata_only"
    assert detail.json()["active_document_id"] is None
    assert detail.json()["file_name"] is None
    assert fulltext.json()["document_id"] is None
    assert await count(resources, Document, Document.id == older) == 0
    assert await count(resources, Document, Document.id == pinned) == 1
    assert set((await content_rows(resources, [pinned, older])).values()) == {0}
    assert await count(resources, PaperSummary, PaperSummary.paper_id == seeded["paper"]) == 0
    assert await count(resources, Paper, Paper.id == seeded["paper"]) == 1
    # Another paper's PDFs are untouched.
    assert await content_rows(resources, [other["document"], other["older"]]) == untouched
    job = await cleanup_job(resources)
    assert job is not None and job.state == "queued"
    assert job.payload["object_keys"] == stored_keys
    assert job.payload["paper_titles"] == ["Removed PDF paper"]


async def test_the_cleanup_job_removes_the_stored_pdf_even_though_a_chat_keeps_its_row(resources):
    """Given a removed PDF a chat pins, when the cleanup job runs, then its stored file is
    removed: the emptied row no longer names the object."""
    seeded = await full_paper(resources, "Removed PDF paper", work_id="W1")
    (key,) = await keys(resources, seeded["document"])
    await resources.storage_call(
        resources.storage.put_object,
        resources.settings.minio_bucket,
        key,
        io.BytesIO(PDF),
        len(PDF),
        content_type="application/pdf",
    )
    async with client_for(resources) as client:
        assert (await client.delete(f"/api/v1/papers/{seeded['paper']}/pdf")).status_code == 204
    done = await run_cleanup(resources)
    assert done.state == "completed"
    assert done.result == {"removed": 2, "kept": 0}


async def test_a_chat_pinned_to_the_removed_pdf_stays_readable_and_takes_no_new_questions(
    resources,
):
    """Given a chat over the paper with a cited answer, when the PDF is removed, then the chat and
    its quoted passages still read, it says its PDF was removed, the cited passage and the file
    answer 404 PDF_REMOVED, and a new question is refused."""
    from app.services.chat import chat_scopes

    seeded = await full_paper(resources, "Removed PDF paper", work_id="W1")
    async with client_for(resources) as client:
        assert (await client.delete(f"/api/v1/papers/{seeded['paper']}/pdf")).status_code == 204
        chat = await client.get(f"/api/v1/chats/{seeded['chat']}")
        listed = await client.get(f"/api/v1/papers/{seeded['paper']}/chats")
        history = await client.get(f"/api/v1/chats/{seeded['chat']}/messages")
        passage = await client.get(
            f"/api/v1/documents/{seeded['document']}/chunks/{seeded['chunks'][1]}"
        )
        download = await client.get(f"/api/v1/documents/{seeded['document']}/download")
        facts = await client.get(f"/api/v1/documents/{seeded['document']}")

    assert chat.status_code == 200, chat.text
    assert [paper["pdf_removed"] for paper in chat.json()["papers"]] == [True]
    assert [paper["pdf_removed"] for paper in listed.json()["items"][0]["papers"]] == [True]
    answer = history.json()["items"][-1]
    assert [item["excerpt"] for item in answer["citations"]] == ["A cited passage."]
    assert answer["citations"][0]["paper_id"] == str(seeded["paper"])
    for response in (passage, download, facts):
        assert response.status_code == 404, response.text
        assert response.json()["code"] == "PDF_REMOVED"
    async with resources.sessions() as session:
        with pytest.raises(HTTPException) as refused:
            await chat_scopes(session, seeded["chat"])
    assert refused.value.status_code == 409


async def test_a_chat_on_another_pdf_of_another_paper_is_unaffected(resources):
    """Given a chat over two papers, when one paper's PDF is removed, then only that paper's
    link says so."""
    first, first_pdf, _ = await seed_structured(resources, title="First paper")
    second, second_pdf, _ = await seed_structured(resources, title="Second paper")
    chat_id = await new_chat(resources, (first, first_pdf), (second, second_pdf))
    async with client_for(resources) as client:
        assert (await client.delete(f"/api/v1/papers/{first}/pdf")).status_code == 204
        chat = await client.get(f"/api/v1/chats/{chat_id}")
    assert [(paper["paper_id"], paper["pdf_removed"]) for paper in chat.json()["papers"]] == [
        (str(first), True),
        (str(second), False),
    ]


async def test_a_new_upload_after_removal_becomes_the_current_pdf_even_with_the_same_file(
    resources,
):
    """Given a removed PDF a chat pins, when the same file is uploaded again, then it is a new
    PDF that becomes current, not a duplicate of the removed one."""
    seeded = await full_paper(resources, "Removed PDF paper", work_id="W1")
    async with resources.sessions() as session, session.begin():
        await session.execute(
            update(Document)
            .where(Document.id == seeded["document"])
            .values(sha256=hashlib.sha256(PDF).hexdigest())
        )
    async with client_for(resources) as client:
        assert (await client.delete(f"/api/v1/papers/{seeded['paper']}/pdf")).status_code == 204
        response = await client.post(
            "/api/v1/documents",
            files={"file": ("again.pdf", PDF, "application/pdf")},
            data={"request_id": str(uuid4()), "paper_id": str(seeded["paper"])},
        )
        detail = await client.get(f"/api/v1/papers/{seeded['paper']}")

    assert response.status_code == 202, response.text
    accepted = response.json()
    assert accepted["duplicate"] is False
    assert accepted["document_id"] != str(seeded["document"])
    assert detail.json()["active_document_id"] == accepted["document_id"]
    assert detail.json()["document_status"] == "processing"
    assert detail.json()["file_name"] == "again.pdf"


async def test_the_preview_says_what_goes_and_changes_nothing(resources):
    """Given two PDFs, a summary, a chat that uses the current PDF and a queued summary job, the
    preview counts each and deletes nothing."""
    seeded = await full_paper(resources, "Removed PDF paper", work_id="W1")
    async with resources.sessions() as session, session.begin():
        await enqueue(
            session,
            kind="summary",
            payload={"paper_id": str(seeded["paper"]), "document_id": str(seeded["document"])},
        )
    before = await content_rows(resources, [seeded["document"], seeded["older"]])
    async with client_for(resources) as client:
        response = await client.get(f"/api/v1/papers/{seeded['paper']}/pdf/removal-preview")
        missing = await client.get(f"/api/v1/papers/{uuid4()}/pdf/removal-preview")
    assert response.status_code == 200, response.text
    assert response.json() == {
        "pdfs": 2,
        "summaries": 1,
        "chats": [{"id": str(seeded["chat"]), "title": "About Removed PDF paper"}],
        "active_jobs": 1,
        "answering": False,
    }
    assert missing.status_code == 404 and missing.json()["code"] == "PAPER_NOT_FOUND"
    assert await content_rows(resources, [seeded["document"], seeded["older"]]) == before


async def test_removal_waits_for_an_answer_being_written_from_the_pdf(resources):
    """Given a chat that uses the PDF and is still answering, then the preview says so and the
    removal answers 409 CHAT_BUSY without changing anything."""
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
    assert await count(resources, Document, Document.id == seeded["older"]) == 1
    assert await cleanup_job(resources) is None


async def test_work_on_the_removed_pdfs_stops_and_other_work_carries_on(resources):
    """Given queued ingest, index, summary and lookup jobs for the PDFs, and a summary for another
    paper, when the PDF is removed, then the PDFs' jobs fail with PDF_REMOVED and no lease, and the
    other paper's job stays queued."""
    seeded = await full_paper(resources, "Removed PDF paper", work_id="W1")
    other = await full_paper(resources, "Untouched paper", work_id="W2")
    async with resources.sessions() as session, session.begin():
        stopped = [
            (await enqueue(session, kind=kind, payload=payload)).id
            for kind, payload in (
                ("ingest", {"document_id": str(seeded["older"])}),
                ("embed", {"document_id": str(seeded["document"]), "index_id": str(uuid4())}),
                (
                    "summary",
                    {"paper_id": str(seeded["paper"]), "document_id": str(seeded["document"])},
                ),
                (
                    "metadata",
                    {"paper_id": str(seeded["paper"]), "document_id": str(seeded["older"])},
                ),
            )
        ]
        running = await session.get(BackgroundJob, stopped[0])
        running.state, running.lease_token = "processing", uuid4()
        running.lease_expires_at = datetime.now(UTC) + timedelta(minutes=5)
        kept = (
            await enqueue(
                session,
                kind="summary",
                payload={"paper_id": str(other["paper"]), "document_id": str(other["document"])},
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
        assert {row.result["outcome"] for row in rows} == {"pdf_removed"}
        assert (await session.get(BackgroundJob, kept)).state == "queued"


async def test_a_failed_ingest_of_a_removed_pdf_cannot_be_retried(resources):
    """Given an ingest that failed retryably before the PDF was removed, when it is retried, then
    the retry is refused and the removed PDF stays removed."""
    seeded = await full_paper(resources, "Removed PDF paper", work_id="W1")
    async with resources.sessions() as session, session.begin():
        job = await enqueue(
            session, kind="ingest", payload={"document_id": str(seeded["document"])}
        )
        job.state, job.stage, job.error_code = "failed", "failed", "STORAGE_UNAVAILABLE"
        job_id = job.id
    async with client_for(resources) as client:
        assert (await client.delete(f"/api/v1/papers/{seeded['paper']}/pdf")).status_code == 204
        retry = await client.post(f"/api/v1/jobs/{job_id}/retry")
    assert retry.status_code == 409 and retry.json()["code"] == "PDF_REMOVED"
    async with resources.sessions() as session:
        assert (await session.get(Document, seeded["document"])).status == "failed"
        assert (await session.get(BackgroundJob, job_id)).state == "failed"


async def test_a_repeat_changes_nothing_and_an_unknown_paper_answers_404(resources):
    seeded = await full_paper(resources, "Removed PDF paper", work_id="W1")
    async with client_for(resources) as client:
        assert (await client.delete(f"/api/v1/papers/{seeded['paper']}/pdf")).status_code == 204
        again = await client.delete(f"/api/v1/papers/{seeded['paper']}/pdf")
        preview = await client.get(f"/api/v1/papers/{seeded['paper']}/pdf/removal-preview")
        unknown = await client.delete(f"/api/v1/papers/{uuid4()}/pdf")
    assert again.status_code == 204
    assert preview.json() == {
        "pdfs": 0,
        "summaries": 0,
        "chats": [],
        "active_jobs": 0,
        "answering": False,
    }
    assert unknown.status_code == 404 and unknown.json()["code"] == "PAPER_NOT_FOUND"
    async with resources.sessions() as session:
        cleanups = await session.scalar(
            select(func.count())
            .select_from(BackgroundJob)
            .where(BackgroundJob.kind == "storage_cleanup")
        )
    assert cleanups == 1


async def test_deleting_the_paper_later_takes_the_removed_rows_and_counts_no_pdfs(resources):
    """Given a paper whose PDF was removed, then its deletion preview counts no PDFs, and deleting
    it removes the emptied row and the chat about only it."""
    seeded = await full_paper(resources, "Removed PDF paper", work_id="W1")
    async with client_for(resources) as client:
        assert (await client.delete(f"/api/v1/papers/{seeded['paper']}/pdf")).status_code == 204
        preview = await client.get(f"/api/v1/papers/{seeded['paper']}/deletion-preview")
        assert (await client.delete(f"/api/v1/papers/{seeded['paper']}")).status_code == 204
    assert preview.json()["pdfs"] == 0
    assert await count(resources, Document, Document.paper_id == seeded["paper"]) == 0
    assert await count(resources, ChatSession, ChatSession.id == seeded["chat"]) == 0
    assert await count(resources, ChatPaper, ChatPaper.paper_id == seeded["paper"]) == 0


async def test_document_facts_name_the_file_its_pages_size_and_source(resources):
    """The reader's PDF menu reads one PDF's file facts (ARA-097)."""
    paper, document, _ = await seed_structured(resources, title="Facts paper")
    async with resources.sessions() as session, session.begin():
        await session.execute(
            update(Document)
            .where(Document.id == document)
            .values(acquisition={"method": "provider_download", "provider": "openalex"})
        )
    async with client_for(resources) as client:
        response = await client.get(f"/api/v1/documents/{document}")
        missing = await client.get(f"/api/v1/documents/{uuid4()}")
    assert response.status_code == 200, response.text
    body = response.json()
    assert {
        key: body[key]
        for key in ("id", "paper_id", "file_name", "page_count", "byte_size", "status")
    } == {
        "id": str(document),
        "paper_id": str(paper),
        "file_name": "structured.pdf",
        "page_count": 4,
        "byte_size": 10,
        "status": "ready",
    }
    assert body["acquisition"]["provider"] == "openalex"
    assert missing.status_code == 404 and missing.json()["code"] == "DOCUMENT_NOT_FOUND"


async def test_removed_citations_still_read_in_saved_answers(resources):
    """Given an answer citing the removed PDF beside another paper's PDF, the saved excerpts of
    both still read after the removal."""
    first, first_pdf, first_chunks = await seed_structured(resources, title="First paper")
    second, second_pdf, second_chunks = await seed_structured(resources, title="Second paper")
    chat_id = await new_chat(resources, (first, first_pdf), (second, second_pdf))
    cited = [
        citation(first_pdf, first_chunks[0], "From the first paper."),
        citation(second_pdf, second_chunks[0], "From the second paper."),
    ]
    await add_turns(resources, chat_id, [("Compare them.", "They differ.", cited)])
    async with client_for(resources) as client:
        assert (await client.delete(f"/api/v1/papers/{first}/pdf")).status_code == 204
        history = await client.get(f"/api/v1/chats/{chat_id}/messages")
    answer = history.json()["items"][-1]
    assert [(item["excerpt"], item["paper_id"]) for item in answer["citations"]] == [
        ("From the first paper.", str(first)),
        ("From the second paper.", str(second)),
    ]


async def test_an_ingest_that_missed_the_removal_writes_nothing_into_the_removed_row(
    resources, monkeypatch
):
    """Given a PDF being read again (a reindex) whose job row was locked when its PDF was
    removed, when the read finishes, then it finds the row removed, fails with PDF_REMOVED and
    stores no page in it."""
    from support.front_matter import toolchain_pdf

    from app.repositories.jobs import claim
    from app.services import ingestion
    from app.services.uploads import ingest_pdf_bytes

    accepted = await ingest_pdf_bytes(
        resources,
        data=toolchain_pdf(stamp=None),
        filename="a.pdf",
        request_id=uuid4(),
        paper_id=None,
    )
    parse = ingestion.parse_in_child

    async def parse_then_remove(data, *args, **kwargs):
        parsed = await parse(data, *args, **kwargs)
        # As the removal leaves a row a chat pins, without reaching this job's locked row.
        async with resources.sessions() as session, session.begin():
            await session.execute(
                update(Document)
                .where(Document.id == accepted.document_id)
                .values(status="failed", object_key=f"removed/{accepted.document_id}")
            )
        return parsed

    monkeypatch.setattr(ingestion, "parse_in_child", parse_then_remove)
    async with resources.sessions() as session:
        job = await session.get(BackgroundJob, accepted.job_id)
    token = await claim(resources.sessions, job.id, job.generation)
    await ingestion.run_ingest_job(resources, job.id, job.generation, token, dict(job.payload))
    async with resources.sessions() as session:
        after = await session.get(BackgroundJob, job.id)
        document = await session.get(Document, accepted.document_id)
    assert (after.state, after.error_code, after.lease_token) == ("failed", "PDF_REMOVED", None)
    assert document.status == "failed"
    assert (
        await count(resources, DocumentPage, DocumentPage.document_id == accepted.document_id) == 0
    )
