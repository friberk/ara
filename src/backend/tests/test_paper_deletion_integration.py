"""Deleting papers from the library (ARA-095).

A deletion removes the paper and, through the existing foreign-key cascades, its PDFs, pages,
passages, search indexes, summaries, provider records and upload state. A chat whose only papers
are deleted goes with them (trigger `chat_papers_last_paper`); a chat over other papers keeps
them and its saved citations.
"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select, update

from app.models.fulltext import FullTextRequest
from app.models.jobs import BackgroundJob
from app.models.memory import ChatMemory
from app.models.research import (
    ChatMessage,
    ChatPaper,
    ChatSession,
    Document,
    DocumentChunk,
    DocumentPage,
    DocumentUploadRequest,
    Paper,
    PaperAuthor,
    PaperRedirect,
    PaperSource,
    PaperSummary,
)
from app.models.retrieval import ChunkEmbedding, DocumentSection, RetrievalIndex
from app.repositories.jobs import enqueue
from tests.support.chats import add_turns, new_chat
from tests.support.evidence import seed_structured

pytestmark = pytest.mark.integration


def client_for(resources):
    import httpx

    from app.main import create_app

    app = create_app(resources.settings)
    app.state.resources = resources
    return httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test")


async def count(resources, model, *where) -> int:
    async with resources.sessions() as session:
        return await session.scalar(select(func.count()).select_from(model).where(*where))


def citation(document_id, chunk_id, excerpt="A cited passage.") -> dict:
    return {
        "chunk_id": str(chunk_id),
        "document_id": str(document_id),
        "page": 2,
        "excerpt": excerpt,
    }


async def full_paper(resources, title: str, *, work_id: str) -> dict:
    """A ready paper with everything that hangs off one: an earlier PDF version with pages and
    sections, passages, embeddings, an index, a summary, a provider record and a retrieval
    request, plus a single-paper chat with a summarized answer."""
    paper_id, document_id, chunks = await seed_structured(resources, title=title)
    async with resources.sessions() as session, session.begin():
        older = Document(
            id=uuid4(),
            paper_id=paper_id,
            status="ready",
            object_key=f"originals/{uuid4()}.pdf",
            sha256=uuid4().hex + uuid4().hex,
            original_filename="older.pdf",
            byte_size=10,
            request_id=uuid4(),
        )
        session.add(older)
        await session.flush()
        session.add(DocumentUploadRequest(request_id=uuid4(), document_id=older.id))
        session.add(DocumentPage(document_id=document_id, page=1, text="Page one."))
        session.add(
            DocumentSection(
                document_id=document_id,
                chunk_set="layout-v1:evidence",
                ordinal=0,
                title="Abstract",
                level=1,
                page=1,
                page_end=1,
            )
        )
        session.add(
            PaperSource(
                paper_id=paper_id,
                provider="openalex",
                external_id=work_id,
                metadata_snapshot={"provider": "openalex", "external_id": work_id, "title": title},
            )
        )
        session.add(
            PaperSummary(
                paper_id=paper_id,
                document_id=document_id,
                model="gpt-5.6-luna",
                reasoning_effort="low",
                content="A summary [source:x].",
                citations=[citation(document_id, chunks[0])],
            )
        )
        job = await enqueue(session, kind="fulltext", payload={"paper_id": str(paper_id)})
        job.state = "completed"
        session.add(FullTextRequest(request_id=uuid4(), paper_id=paper_id, job_id=job.id))
    chat_id = await new_chat(resources, (paper_id, document_id), title=f"About {title}")
    (turn,) = await add_turns(
        resources, chat_id, [("What is it?", "It is X.", [citation(document_id, chunks[1])])]
    )
    async with resources.sessions() as session, session.begin():
        session.add(
            ChatMemory(
                session_id=chat_id,
                version=1,
                through_message_id=turn.answer,
                summary="- X.",
                token_count=2,
                model="gpt-5.6-luna",
                prompt_version="test",
            )
        )
    return {
        "paper": paper_id,
        "document": document_id,
        "older": older.id,
        "chunks": chunks,
        "chat": chat_id,
    }


async def remaining(resources, seeded: dict) -> dict[str, int]:
    """Rows still naming the seeded paper, its PDFs or its chat."""
    paper, chat = seeded["paper"], seeded["chat"]
    documents = [seeded["document"], seeded["older"]]
    return {
        "papers": await count(resources, Paper, Paper.id == paper),
        "authors": await count(resources, PaperAuthor, PaperAuthor.paper_id == paper),
        "sources": await count(resources, PaperSource, PaperSource.paper_id == paper),
        "documents": await count(resources, Document, Document.id.in_(documents)),
        "upload_requests": await count(
            resources, DocumentUploadRequest, DocumentUploadRequest.document_id.in_(documents)
        ),
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
        "summaries": await count(resources, PaperSummary, PaperSummary.paper_id == paper),
        "fulltext_requests": await count(
            resources, FullTextRequest, FullTextRequest.paper_id == paper
        ),
        "chats": await count(resources, ChatSession, ChatSession.id == chat),
        "chat_links": await count(resources, ChatPaper, ChatPaper.paper_id == paper),
        "messages": await count(resources, ChatMessage, ChatMessage.session_id == chat),
        "memories": await count(resources, ChatMemory, ChatMemory.session_id == chat),
    }


async def test_deleting_a_paper_removes_it_and_everything_that_hangs_off_it(resources):
    """Given a paper with PDFs, passages, an index, a summary and a chat about only it, when it
    is deleted, then all of it goes and another paper is untouched."""
    gone = await full_paper(resources, "Deleted paper", work_id="W1")
    kept = await full_paper(resources, "Kept paper", work_id="W2")
    async with resources.sessions() as session, session.begin():
        # The kept paper's upload named the deleted paper as its DOI's owner (ARA-092), and a
        # retired placeholder redirects to the deleted paper.
        await session.execute(
            update(Document)
            .where(Document.id == kept["document"])
            .values(doi_owner_paper_id=gone["paper"])
        )
        session.add(PaperRedirect(old_paper_id=uuid4(), paper_id=gone["paper"]))
    before = await remaining(resources, kept)

    async with client_for(resources) as client:
        response = await client.delete(f"/api/v1/papers/{gone['paper']}")

    assert response.status_code == 204, response.text
    assert set((await remaining(resources, gone)).values()) == {0}
    assert await count(resources, PaperRedirect, PaperRedirect.paper_id == gone["paper"]) == 0
    assert await remaining(resources, kept) == before
    async with resources.sessions() as session:
        assert (await session.get(Document, kept["document"])).doi_owner_paper_id is None


async def test_a_chat_over_other_papers_keeps_them_and_its_saved_citations(resources):
    """Given a chat over two papers whose answer cites both, when the first paper is deleted,
    then the chat keeps the other paper, moves to it, and its citations stay readable."""
    first, first_pdf, first_chunks = await seed_structured(resources, title="First paper")
    second, second_pdf, second_chunks = await seed_structured(resources, title="Second paper")
    chat_id = await new_chat(resources, (first, first_pdf), (second, second_pdf))
    cited = [
        citation(first_pdf, first_chunks[0], "From the first paper."),
        citation(second_pdf, second_chunks[0], "From the second paper."),
    ]
    await add_turns(resources, chat_id, [("Compare them.", "They differ.", cited)])

    async with client_for(resources) as client:
        assert (await client.delete(f"/api/v1/papers/{first}")).status_code == 204
        chat = await client.get(f"/api/v1/chats/{chat_id}")
        history = await client.get(f"/api/v1/chats/{chat_id}/messages")

    assert chat.status_code == 200, chat.text
    assert chat.json()["paper_id"] == str(second)
    assert [item["paper_id"] for item in chat.json()["papers"]] == [str(second)]
    answer = history.json()["items"][-1]
    assert [item["excerpt"] for item in answer["citations"]] == [
        "From the first paper.",
        "From the second paper.",
    ]
    # The deleted paper is no longer named; its saved excerpt still reads.
    assert [item["paper_id"] for item in answer["citations"]] == [None, str(second)]


async def test_a_deleted_paper_answers_404_everywhere_and_a_repeat_is_safe(resources):
    seeded = await full_paper(resources, "Deleted paper", work_id="W1")
    paper = seeded["paper"]
    async with client_for(resources) as client:
        assert (await client.delete(f"/api/v1/papers/{paper}")).status_code == 204
        again = await client.delete(f"/api/v1/papers/{paper}")
        detail = await client.get(f"/api/v1/papers/{paper}")
        fulltext = await client.get(f"/api/v1/papers/{paper}/fulltext")
        preview = await client.get(f"/api/v1/papers/{paper}/deletion-preview")
        listed = (await client.get("/api/v1/papers")).json()["items"]
        chats = (await client.get("/api/v1/chats")).json()["items"]
        chat = await client.get(f"/api/v1/chats/{seeded['chat']}")
    assert again.status_code == 404 and again.json()["code"] == "PAPER_NOT_FOUND"
    assert detail.status_code == 404 and fulltext.status_code == 404
    assert preview.status_code == 404
    assert listed == [] and chats == []
    assert chat.status_code == 404


async def test_the_preview_names_what_would_go_and_deletes_nothing(resources):
    """Given a paper with two PDFs, a summary, its own chat and a chat shared with another
    paper, the preview counts each of them and changes nothing."""
    seeded = await full_paper(resources, "Deleted paper", work_id="W1")
    other, other_pdf, _ = await seed_structured(resources, title="Other paper")
    shared = await new_chat(
        resources, (other, other_pdf), (seeded["paper"], seeded["document"]), title="Both"
    )
    async with resources.sessions() as session, session.begin():
        await enqueue(
            session,
            kind="summary",
            payload={"paper_id": str(seeded["paper"]), "document_id": str(seeded["document"])},
        )
    before = await remaining(resources, seeded)
    async with client_for(resources) as client:
        response = await client.get(f"/api/v1/papers/{seeded['paper']}/deletion-preview")
    assert response.status_code == 200, response.text
    assert response.json() == {
        "papers": [{"paper_id": str(seeded["paper"]), "title": "Deleted paper"}],
        "missing": [],
        "pdfs": 2,
        "summaries": 1,
        "deleted_chats": [{"id": str(seeded["chat"]), "title": "About Deleted paper"}],
        "updated_chats": [{"id": str(shared), "title": "Both"}],
        "active_jobs": 1,
        "answering": False,
    }
    assert await remaining(resources, seeded) == before


async def test_several_papers_are_deleted_together_with_one_combined_preview(resources):
    """Given papers A, B and C, a chat over A and B and one over B and C, when A and B are
    deleted together, then the A+B chat goes, the B+C chat keeps C, and C stays."""
    a = await full_paper(resources, "Paper A", work_id="W1")
    b = await full_paper(resources, "Paper B", work_id="W2")
    c = await full_paper(resources, "Paper C", work_id="W3")
    both = await new_chat(resources, (a["paper"], a["document"]), (b["paper"], b["document"]))
    keeps_c = await new_chat(resources, (b["paper"], b["document"]), (c["paper"], c["document"]))
    missing = uuid4()
    ids = [str(a["paper"]), str(b["paper"]), str(missing)]
    before = await remaining(resources, c)
    async with client_for(resources) as client:
        preview = await client.post("/api/v1/papers/deletion-preview", json={"paper_ids": ids})
        deleted = await client.post("/api/v1/papers/delete", json={"paper_ids": ids})
        repeat = await client.post("/api/v1/papers/delete", json={"paper_ids": ids})
        empty = await client.post("/api/v1/papers/delete", json={"paper_ids": []})

    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert {item["paper_id"] for item in body["papers"]} == {str(a["paper"]), str(b["paper"])}
    assert body["missing"] == [str(missing)]
    assert body["pdfs"] == 4 and body["summaries"] == 2
    assert {item["id"] for item in body["deleted_chats"]} == {
        str(a["chat"]),
        str(b["chat"]),
        str(both),
    }
    assert [item["id"] for item in body["updated_chats"]] == [str(keeps_c)]
    assert deleted.status_code == 200, deleted.text
    assert set(deleted.json()["deleted"]) == {str(a["paper"]), str(b["paper"])}
    assert deleted.json()["missing"] == [str(missing)]
    assert repeat.json() == {"deleted": [], "missing": ids}
    assert empty.status_code == 422
    for seeded in (a, b):
        assert set((await remaining(resources, seeded)).values()) == {0}
    assert await count(resources, ChatSession, ChatSession.id == both) == 0
    assert await remaining(resources, c) == before
    async with resources.sessions() as session:
        links = (
            await session.scalars(select(ChatPaper.paper_id).where(ChatPaper.chat_id == keeps_c))
        ).all()
    assert links == [c["paper"]]


async def test_deletion_waits_for_an_answer_that_is_still_being_written(resources):
    """Given a chat answering now, deletion refuses with CHAT_BUSY and removes nothing; an
    answer whose lease expired is interrupted and no longer blocks."""
    seeded = await full_paper(resources, "Busy paper", work_id="W1")
    async with resources.sessions() as session, session.begin():
        answer = ChatMessage(
            session_id=seeded["chat"],
            role="assistant",
            state="processing",
            lease_expires_at=datetime.now(UTC) + timedelta(minutes=5),
        )
        session.add(answer)
    async with client_for(resources) as client:
        preview = await client.get(f"/api/v1/papers/{seeded['paper']}/deletion-preview")
        refused = await client.delete(f"/api/v1/papers/{seeded['paper']}")
        assert preview.json()["answering"] is True
        assert refused.status_code == 409 and refused.json()["code"] == "CHAT_BUSY"
        assert await count(resources, Paper, Paper.id == seeded["paper"]) == 1
        async with resources.sessions() as session, session.begin():
            stale = await session.get(ChatMessage, answer.id)
            stale.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        assert (await client.delete(f"/api/v1/papers/{seeded['paper']}")).status_code == 204


async def test_an_unknown_paper_cannot_be_previewed_or_deleted(resources):
    async with client_for(resources) as client:
        missing = uuid4()
        assert (await client.delete(f"/api/v1/papers/{missing}")).status_code == 404
        assert (await client.get(f"/api/v1/papers/{missing}/deletion-preview")).status_code == 404


async def test_an_upload_waiting_on_a_deleted_library_paper_goes_on_as_its_own_paper(resources):
    """Given an upload held for Replace or Cancel against a library paper, when that paper is
    deleted, then the upload is listed as its own paper and is read now."""
    from test_upload_match_integration import pending_upload

    saved, _original, accepted = await pending_upload(resources)
    async with client_for(resources) as client:
        assert (await client.delete(f"/api/v1/papers/{saved}")).status_code == 204
        listed = [item["id"] for item in (await client.get("/api/v1/papers")).json()["items"]]
        pending = (await client.get("/api/v1/uploads/matches")).json()["items"]
        paper = (await client.get(f"/api/v1/papers/{accepted.paper_id}")).json()
    assert listed == [str(accepted.paper_id)] and pending == []
    assert paper["upload_match"] is None and paper["document_status"] == "processing"
    async with resources.sessions() as session:
        document = await session.get(Document, accepted.document_id)
        job = await session.get(BackgroundJob, document.ingest_job_id)
    assert job.id != accepted.job_id and job.kind == "ingest" and job.state == "queued"
