"""Workspace history (ARA-034) on the opt-in real PostgreSQL fixture, never SQLite."""

from datetime import datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import func, select, text, update

from app.models.research import ChatMessage, ChatSession, Document, DocumentChunk, Paper
from app.repositories.jobs import enqueue, now

pytestmark = pytest.mark.integration


async def ready_paper(resources, title):
    async with resources.sessions() as session, session.begin():
        paper = Paper(title=title, metadata_provenance={})
        session.add(paper)
        await session.flush()
        document = Document(
            paper_id=paper.id,
            status="ready",
            object_key=uuid4().hex,
            sha256=uuid4().hex,
            original_filename="fixture.pdf",
            byte_size=100,
            request_id=uuid4(),
            page_count=1,
        )
        session.add(document)
        await session.flush()
        paper.active_document_id = document.id
        evidence = "Methods: blue condition achieved 87 percent accuracy."
        session.add(
            DocumentChunk(
                document_id=document.id,
                ordinal=0,
                page=1,
                text=evidence,
                chunk_set="test",
                page_end=1,
                context_text=evidence,
                token_count=20,
            )
        )
        return paper.id, document.id


def client_for(resources):
    from app.main import create_app

    app = create_app(resources.settings)
    app.state.resources = resources
    return httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test")


async def message_count(resources, chat_id):
    async with resources.sessions() as session:
        return await session.scalar(
            select(func.count()).select_from(ChatMessage).where(ChatMessage.session_id == chat_id)
        )


async def test_given_chats_on_two_papers_when_listing_then_latest_activity_orders_summaries(
    resources,
):
    """Given chats on two papers, when GET /chats, then latest activity orders the summaries."""
    first_paper, first_document = await ready_paper(resources, "Attention paper")
    second_paper, second_document = await ready_paper(resources, None)
    start = now()
    long_question = "Which   results\nsupport the claim? " + "detail " * 40
    async with resources.sessions() as session, session.begin():
        old = ChatSession(
            paper_id=first_paper,
            document_id=first_document,
            title="Old",
            created_at=start - timedelta(hours=3),
        )
        empty = ChatSession(
            paper_id=first_paper,
            document_id=first_document,
            title="Empty",
            created_at=start - timedelta(minutes=20),
        )
        recent = ChatSession(
            paper_id=second_paper,
            document_id=second_document,
            title="Recent",
            created_at=start - timedelta(hours=1),
        )
        session.add_all([old, empty, recent])
        await session.flush()

        def message(chat, role, content, minutes_ago):
            return ChatMessage(
                session_id=chat.id,
                role=role,
                content=content,
                state="completed",
                citations=[],
                created_at=start - timedelta(minutes=minutes_ago),
            )

        session.add_all(
            [
                message(old, "user", "First question", 50),
                message(old, "assistant", "First answer", 49),
                message(old, "user", long_question, 10),
                message(old, "assistant", "Second answer", 9),
                message(recent, "user", "Short question?", 5),
            ]
        )
        old_id, empty_id, recent_id = old.id, empty.id, recent.id
    async with client_for(resources) as client:
        response = await client.get("/api/v1/chats")
        assert response.status_code == 200, response.text
        items = response.json()["items"]
        assert [item["id"] for item in items] == [str(recent_id), str(old_id), str(empty_id)]
        recent_item, old_item, empty_item = items
        assert set(old_item) == {
            "id",
            "paper_id",
            "document_id",
            "title",
            "title_source",
            "created_at",
            "paper_title",
            "last_activity_at",
            "message_count",
            "last_question_preview",
        }
        assert recent_item["paper_title"] is None and recent_item["message_count"] == 1
        assert recent_item["last_question_preview"] == "Short question?"
        assert old_item["paper_title"] == "Attention paper" and old_item["message_count"] == 4
        preview = old_item["last_question_preview"]
        assert len(preview) <= 140 and preview.endswith("…")
        assert preview.startswith("Which results support the claim? detail detail")
        assert datetime.fromisoformat(old_item["last_activity_at"]) == start - timedelta(minutes=9)
        assert empty_item["message_count"] == 0 and empty_item["last_question_preview"] is None
        assert empty_item["last_activity_at"] == empty_item["created_at"]

        scoped = (await client.get("/api/v1/chats", params={"paper_id": str(first_paper)})).json()
        assert [item["id"] for item in scoped["items"]] == [str(old_id), str(empty_id)]
        paged = (await client.get("/api/v1/chats", params={"limit": 1, "offset": 1})).json()
        assert [item["id"] for item in paged["items"]] == [str(old_id)]
        unknown = await client.get("/api/v1/chats", params={"paper_id": str(uuid4())})
        assert unknown.status_code == 200 and unknown.json() == {"items": []}
        for limit in (0, 101):
            invalid = await client.get("/api/v1/chats", params={"limit": limit})
            assert invalid.status_code == 422 and invalid.json()["code"] == "VALIDATION_ERROR"


async def test_given_default_chat_when_questions_are_posted_then_only_first_question_titles_it(
    resources,
):
    """Given a default-titled chat, when the first question is posted, then it is titled once."""
    from app.integrations.llm import LLMError
    from app.schemas.ai import ChatInput
    from app.services.chat import prepare, save, title_from_question

    paper_id, _ = await ready_paper(resources, "Titled paper")
    resources.settings.openai_api_key = SecretStr("fixture")

    async def ask(chat_id, content, request_id=None):
        body = ChatInput(content=content, request_id=request_id or uuid4())
        assistant, _, _, replay = await prepare(resources, chat_id, body)
        if not replay:
            await save(resources, assistant.id, "Insufficient evidence.", state="completed")
        return body, replay

    async def stored(chat_id):
        async with resources.sessions() as session:
            chat = await session.get(ChatSession, chat_id)
            return chat.title, chat.title_source

    async with client_for(resources) as client:
        created = await client.post(f"/api/v1/papers/{paper_id}/chats", json={})
        assert created.status_code == 201, created.text
        chat = created.json()
        assert chat["title"] == "Paper discussion" and chat["title_source"] == "default"
        named = await client.post(f"/api/v1/papers/{paper_id}/chats", json={"title": "My notes"})
        assert named.status_code == 201 and named.json()["title_source"] == "manual"

        question = "  What accuracy did the blue condition reach in the main experiment, and why?  "
        expected = title_from_question(question)
        assert expected.endswith("…") and len(expected) <= 60
        first, replay = await ask(chat["id"], question)
        assert replay is False
        assert await stored(chat["id"]) == (expected, "auto")
        listed = (await client.get(f"/api/v1/papers/{paper_id}/chats")).json()["items"]
        assert {"title": expected, "title_source": "auto"}.items() <= next(
            item for item in listed if item["id"] == chat["id"]
        ).items()

        await ask(chat["id"], "A different follow-up question?")
        assert await stored(chat["id"]) == (expected, "auto")

        # The replay path returns before titling, even for a chat that is default again.
        async with resources.sessions() as session, session.begin():
            await session.execute(
                update(ChatSession)
                .where(ChatSession.id == chat["id"])
                .values(title="Paper discussion", title_source="default")
            )
        _, replay = await ask(chat["id"], first.content, first.request_id)
        assert replay is True
        assert await stored(chat["id"]) == ("Paper discussion", "default")
        # A default chat with history takes its title from the first question it holds.
        await ask(chat["id"], "Yet another question?")
        assert await stored(chat["id"]) == (expected, "auto")

        await ask(named.json()["id"], "Does the manual title survive?")
        assert await stored(named.json()["id"]) == ("My notes", "manual")

        # A failed preparation rolls the title back with the user message.
        pending = (await client.post(f"/api/v1/papers/{paper_id}/chats", json={})).json()
        resources.settings.llm_daily_budget_usd = 0
        with pytest.raises(LLMError):
            await ask(pending["id"], "Is this question over budget?")
        assert await stored(pending["id"]) == ("Paper discussion", "default")
        assert await message_count(resources, pending["id"]) == 0
        resources.settings.llm_daily_budget_usd = 5

        renamed = await client.patch(
            f"/api/v1/chats/{chat['id']}", json={"title": "  Accuracy thread  "}
        )
        assert renamed.status_code == 200, renamed.text
        assert renamed.json()["title"] == "Accuracy thread"
        assert renamed.json()["title_source"] == "manual"
        await ask(chat["id"], "Another question after renaming?")
        assert await stored(chat["id"]) == ("Accuracy thread", "manual")

        for body in ({"title": "   "}, {"title": "x" * 201}, {"title": "Ok", "extra": 1}, {}):
            invalid = await client.patch(f"/api/v1/chats/{chat['id']}", json=body)
            assert invalid.status_code == 422, body
        missing = await client.patch(f"/api/v1/chats/{uuid4()}", json={"title": "Gone"})
        assert missing.status_code == 404 and missing.json()["code"] == "CHAT_NOT_FOUND"


async def test_given_processing_answer_when_deleting_chat_then_busy_until_lease_expires(
    resources,
):
    """Given a live answer, when DELETE /chats/{id}, then 409; otherwise 204 removes messages."""
    from app.schemas.ai import ChatInput
    from app.services.chat import prepare

    paper_id, _ = await ready_paper(resources, "Deletable paper")
    resources.settings.openai_api_key = SecretStr("fixture")
    async with client_for(resources) as client:
        chat_id = (await client.post(f"/api/v1/papers/{paper_id}/chats", json={})).json()["id"]
        assistant, _, _, _ = await prepare(
            resources, chat_id, ChatInput(content="Still answering?", request_id=uuid4())
        )
        busy = await client.delete(f"/api/v1/chats/{chat_id}")
        assert busy.status_code == 409 and busy.json()["code"] == "CHAT_BUSY"
        assert await message_count(resources, chat_id) == 2

        # A stale lease is interrupted before the busy check, as in message preparation.
        async with resources.sessions() as session, session.begin():
            message = await session.get(ChatMessage, assistant.id)
            message.lease_expires_at = now() - timedelta(seconds=1)
        deleted = await client.delete(f"/api/v1/chats/{chat_id}")
        assert deleted.status_code == 204 and deleted.content == b""
        assert await message_count(resources, chat_id) == 0
        async with resources.sessions() as session:
            assert await session.get(ChatSession, chat_id) is None
        missing = await client.delete(f"/api/v1/chats/{chat_id}")
        assert missing.status_code == 404 and missing.json()["code"] == "CHAT_NOT_FOUND"
        assert (await client.get(f"/api/v1/chats/{chat_id}/messages")).status_code == 404
        assert (await client.get("/api/v1/chats")).json() == {"items": []}
    async with resources.sessions() as session:
        action = await session.scalar(
            text(
                "SELECT confdeltype FROM pg_constraint WHERE contype = 'f' "
                "AND conrelid = 'chat_messages'::regclass "
                "AND confrelid = 'chat_sessions'::regclass"
            )
        )
    assert action == "c"


async def test_given_same_query_with_different_case_and_spacing_when_recorded_then_one_item(
    resources,
):
    """Given repeated submissions, when POST /search-history, then the latest spelling wins."""
    async with client_for(resources) as client:
        first = await client.post(
            "/api/v1/search-history",
            json={"provider": "openalex", "query": "  Retrieval   Augmented Generation "},
        )
        assert first.status_code == 200, first.text
        item = first.json()
        assert set(item) == {"id", "provider", "query", "created_at", "last_searched_at"}
        assert item["query"] == "Retrieval   Augmented Generation"
        second = await client.post(
            "/api/v1/search-history",
            json={"provider": "openalex", "query": "retrieval augmented\tGENERATION"},
        )
        assert second.status_code == 200, second.text
        latest = second.json()
        assert latest["id"] == item["id"] and latest["query"] == "retrieval augmented\tGENERATION"
        assert latest["created_at"] == item["created_at"]
        assert datetime.fromisoformat(latest["last_searched_at"]) > datetime.fromisoformat(
            item["last_searched_at"]
        )
        other = await client.post(
            "/api/v1/search-history",
            json={"provider": "semantic_scholar", "query": "retrieval augmented generation"},
        )
        assert other.status_code == 200 and other.json()["id"] != item["id"]
        # Casefolding may expand text beyond the 300-character input limit.
        expanded = await client.post(
            "/api/v1/search-history", json={"provider": "openalex", "query": "ß" * 300}
        )
        assert expanded.status_code == 200, expanded.text

        history = (await client.get("/api/v1/search-history")).json()["items"]
        assert [entry["id"] for entry in history] == [
            expanded.json()["id"],
            other.json()["id"],
            item["id"],
        ]
        limited = (await client.get("/api/v1/search-history", params={"limit": 1})).json()
        assert [entry["id"] for entry in limited["items"]] == [expanded.json()["id"]]
        for limit in (0, 101):
            invalid = await client.get("/api/v1/search-history", params={"limit": limit})
            assert invalid.status_code == 422
        for body in (
            {"provider": "openalex", "query": "   "},
            {"provider": "openalex", "query": "x" * 301},
            {"provider": "google", "query": "retrieval"},
            {"provider": "openalex", "query": "retrieval", "extra": True},
        ):
            invalid = await client.post("/api/v1/search-history", json=body)
            assert invalid.status_code == 422, body

        removed = await client.delete(f"/api/v1/search-history/{item['id']}")
        assert removed.status_code == 204 and removed.content == b""
        missing = await client.delete(f"/api/v1/search-history/{item['id']}")
        assert missing.status_code == 404 and missing.json()["code"] == "SEARCH_HISTORY_NOT_FOUND"
        cleared = await client.delete("/api/v1/search-history")
        assert cleared.status_code == 204
        assert (await client.get("/api/v1/search-history")).json() == {"items": []}


async def test_given_saved_paper_when_same_work_is_searched_then_hit_carries_saved_paper_id(
    resources,
):
    """Given saved papers, when searched, then hits match by provider record or by DOI."""
    from app.repositories.papers import save_canonical
    from app.schemas.research import SearchResult

    async with resources.sessions() as session, session.begin():
        by_source, _ = await save_canonical(
            session, SearchResult(provider="openalex", external_id="W100", title="Saved")
        )
        by_doi, _ = await save_canonical(
            session,
            SearchResult(
                provider="semantic_scholar",
                external_id="s2-shared",
                title="Saved elsewhere",
                doi="10.1000/shared",
            ),
        )
        # The same external id from another provider is a different record.
        await save_canonical(
            session, SearchResult(provider="semantic_scholar", external_id="W300", title="Other")
        )
        source_id, doi_id = by_source.id, by_doi.id
    requests = []

    def provider(request):
        requests.append(request.url.path)
        return httpx.Response(
            200,
            json={
                "meta": {"count": 3, "next_cursor": None},
                "results": [
                    {"id": "https://openalex.org/W100", "display_name": "Saved"},
                    {
                        "id": "https://openalex.org/W200",
                        "display_name": "Saved elsewhere",
                        "doi": "https://doi.org/10.1000/SHARED",
                    },
                    {"id": "https://openalex.org/W300", "display_name": "Unsaved"},
                ],
            },
        )

    await resources.http.aclose()
    resources.http = httpx.AsyncClient(transport=httpx.MockTransport(provider))
    async with client_for(resources) as client:
        response = await client.get("/api/v1/search", params={"provider": "openalex", "q": "x"})
        assert response.status_code == 200, response.text
        items = response.json()["items"]
        assert [item["external_id"] for item in items] == ["W100", "W200", "W300"]
        assert [item["saved_paper_id"] for item in items] == [str(source_id), str(doi_id), None]
        detail = (await client.get(f"/api/v1/papers/{source_id}")).json()
        assert "saved_paper_id" not in detail["sources"][0]
        # Searching is free of side effects; only explicit submissions are recorded.
        assert (await client.get("/api/v1/search-history")).json() == {"items": []}
    assert requests == ["/works"]


async def test_given_active_summary_job_when_filtering_jobs_then_paper_link_is_returned(
    resources,
):
    """Given linked jobs, when GET /jobs is filtered, then each job names its paper."""
    linked_paper, linked_document = await ready_paper(resources, "Linked paper")
    other_paper, other_document = await ready_paper(resources, "Other paper")

    def summary(paper_id, document_id):
        return {
            "paper_id": str(paper_id),
            "document_id": str(document_id),
            "model": "gpt-5.6-luna",
            "reasoning_effort": "low",
            "request_id": str(uuid4()),
        }

    async with resources.sessions() as session, session.begin():
        active = await enqueue(
            session, kind="summary", payload=summary(linked_paper, linked_document)
        )
        finished = await enqueue(
            session, kind="summary", payload=summary(linked_paper, linked_document)
        )
        finished.state, finished.stage, finished.progress = "completed", "completed", 100
        waiting = await enqueue(
            session, kind="ingest", payload={"document_id": str(linked_document)}
        )
        waiting.stage = "retry_wait"
        failed = await enqueue(session, kind="ingest", payload={"document_id": str(other_document)})
        failed.state, failed.stage, failed.attempts = "failed", "failed", 3
        failed.error_code, failed.error_message = "JOB_EXECUTION_FAILED", "Execution failed."
        other = await enqueue(session, kind="summary", payload=summary(other_paper, other_document))
        canary = await enqueue(session, kind="canary", payload={"message": "unlinked"})
        ids = {
            name: str(job.id)
            for name, job in {
                "active": active,
                "finished": finished,
                "waiting": waiting,
                "failed": failed,
                "other": other,
                "canary": canary,
            }.items()
        }
    async with client_for(resources) as client:
        response = await client.get(
            "/api/v1/jobs",
            params={"paper_id": str(linked_paper), "kind": "summary", "active": "true"},
        )
        assert response.status_code == 200, response.text
        items = response.json()["items"]
        assert [item["id"] for item in items] == [ids["active"]]
        assert items[0]["paper_id"] == str(linked_paper)
        assert items[0]["paper_title"] == "Linked paper"

        linked = (await client.get("/api/v1/jobs", params={"paper_id": str(linked_paper)})).json()
        assert {item["id"] for item in linked["items"]} == {
            ids["active"],
            ids["finished"],
            ids["waiting"],
        }
        assert {item["paper_title"] for item in linked["items"]} == {"Linked paper"}
        ingest = (
            await client.get("/api/v1/jobs", params={"kind": "ingest", "active": "true"})
        ).json()
        assert [item["id"] for item in ingest["items"]] == [ids["waiting"]]
        assert ingest["items"][0]["paper_id"] == str(linked_paper)
        inactive = (await client.get("/api/v1/jobs", params={"active": "false"})).json()
        assert {item["id"] for item in inactive["items"]} == {ids["finished"], ids["failed"]}

        single = (await client.get(f"/api/v1/jobs/{ids['other']}")).json()
        assert single["paper_id"] == str(other_paper) and single["paper_title"] == "Other paper"
        unlinked = (await client.get(f"/api/v1/jobs/{ids['canary']}")).json()
        assert unlinked["paper_id"] is None and unlinked["paper_title"] is None
        retried = await client.post(f"/api/v1/jobs/{ids['failed']}/retry")
        assert retried.status_code == 202, retried.text
        assert retried.json()["paper_id"] == str(other_paper)
        assert retried.json()["paper_title"] == "Other paper"
        invalid = await client.get("/api/v1/jobs", params={"kind": "canary"})
        assert invalid.status_code == 422


async def test_given_browser_origin_when_deleting_then_preflight_allowed_and_foreign_rejected():
    """Given CORS settings, when DELETE is preflighted or sent cross-origin, then guard holds."""
    from app.core.config import Settings
    from app.main import create_app

    settings = Settings(_env_file=None)
    app = create_app(settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        preflight = await client.options(
            f"/api/v1/chats/{uuid4()}",
            headers={"Origin": settings.cors_origins[0], "Access-Control-Request-Method": "DELETE"},
        )
        assert preflight.status_code == 200, preflight.text
        assert "DELETE" in preflight.headers["access-control-allow-methods"]
        for path in (f"/api/v1/chats/{uuid4()}", "/api/v1/search-history"):
            rejected = await client.delete(path, headers={"Origin": "https://untrusted.example"})
            assert rejected.status_code == 403
            assert rejected.json()["code"] == "ORIGIN_NOT_ALLOWED"
