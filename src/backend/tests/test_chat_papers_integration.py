"""Chats over several library papers: creation, adding, removing and listing (ARA-088)."""

from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import select

from app.models.research import ChatMessage, ChatPaper, Document, Paper
from tests.support.evidence import seed_structured

pytestmark = pytest.mark.integration


def client_for(resources):
    from app.main import create_app

    app = create_app(resources.settings)
    app.state.resources = resources
    return httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test")


async def papers(resources, count: int) -> list[tuple]:
    return [await seed_structured(resources, title=f"Paper {index}") for index in range(count)]


def included(chat: dict) -> list[tuple[str, str]]:
    return [(item["paper_id"], item["document_id"]) for item in chat["papers"]]


async def test_given_two_ready_papers_when_creating_then_the_chat_covers_both_in_order(resources):
    """Given two ready papers, when POST /chats, then both are pinned and listed under each."""
    (first, first_pdf, _), (second, second_pdf, _) = await papers(resources, 2)
    async with client_for(resources) as client:
        created = await client.post("/api/v1/chats", json={"paper_ids": [str(second), str(first)]})
        assert created.status_code == 201, created.text
        chat = created.json()
        assert chat["paper_id"] == str(second)
        assert included(chat) == [(str(second), str(second_pdf)), (str(first), str(first_pdf))]
        assert chat["papers"][0] == {
            "paper_id": str(second),
            "document_id": str(second_pdf),
            "title": "Paper 1",
            "first_author": "Ada Researcher",
            "year": 2024,
            "added_at": chat["papers"][0]["added_at"],
            # Its pinned PDF is still there (ARA-097).
            "pdf_removed": False,
        }
        assert chat["title_source"] == "default" and "document_id" not in chat
        for paper in (first, second):
            listed = (await client.get("/api/v1/chats", params={"paper_id": str(paper)})).json()
            assert [item["id"] for item in listed["items"]] == [chat["id"]]
            assert included(listed["items"][0]) == included(chat)
            legacy = (await client.get(f"/api/v1/papers/{paper}/chats")).json()["items"]
            assert [item["id"] for item in legacy] == [chat["id"]]


async def test_given_invalid_paper_lists_when_creating_then_nothing_is_created(resources):
    """Unknown, unready or repeated papers are refused before a chat exists; any number of
    ready papers is accepted (no cap, user decision on 2026-10-10)."""
    ready = [paper for paper, _, _ in await papers(resources, 6)]
    async with resources.sessions() as session, session.begin():
        bare = Paper(title="Metadata only", metadata_provenance={})
        session.add(bare)
        await session.flush()
        bare_id = bare.id
    async with client_for(resources) as client:
        missing = await client.post("/api/v1/chats", json={"paper_ids": [str(uuid4())]})
        assert missing.status_code == 404 and missing.json()["code"] == "PAPER_NOT_FOUND"
        unready = await client.post(
            "/api/v1/chats", json={"paper_ids": [str(ready[0]), str(bare_id)]}
        )
        assert unready.status_code == 409 and unready.json()["code"] == "PAPER_NOT_READY"
        assert "Metadata only" in unready.json()["message"]
        for paper_ids in ([], [ready[0], ready[0]]):
            refused = await client.post(
                "/api/v1/chats", json={"paper_ids": [str(item) for item in paper_ids]}
            )
            assert refused.status_code == 422, paper_ids
        assert (await client.get("/api/v1/chats")).json() == {"items": []}
        six = await client.post("/api/v1/chats", json={"paper_ids": [str(item) for item in ready]})
        assert six.status_code == 201, six.text
        assert [item["paper_id"] for item in six.json()["papers"]] == [str(item) for item in ready]


async def test_given_a_chat_when_papers_are_added_then_each_pins_its_pdf_at_that_moment(
    resources,
):
    """A paper added mid-chat pins its active PDF then; later uploads do not move the chat."""
    seeded = await papers(resources, 6)
    (first, _, _), (second, second_pdf, _) = seeded[:2]
    async with client_for(resources) as client:
        chat = (await client.post("/api/v1/chats", json={"paper_ids": [str(first)]})).json()
        added = await client.post(
            f"/api/v1/chats/{chat['id']}/papers", json={"paper_id": str(second)}
        )
        assert added.status_code == 200, added.text
        assert [item["paper_id"] for item in added.json()["papers"]] == [str(first), str(second)]
        assert added.json()["papers"][1]["document_id"] == str(second_pdf)
        again = await client.post(
            f"/api/v1/chats/{chat['id']}/papers", json={"paper_id": str(second)}
        )
        assert again.status_code == 200 and again.json()["papers"] == added.json()["papers"]

        # A newer PDF of the second paper does not change what this chat reads.
        async with resources.sessions() as session, session.begin():
            newer = Document(
                paper_id=second,
                status="ready",
                object_key=uuid4().hex,
                sha256=uuid4().hex,
                original_filename="newer.pdf",
                byte_size=10,
                request_id=uuid4(),
                chunk_set="layout-v1:evidence",
            )
            session.add(newer)
            await session.flush()
            (await session.get(Paper, second)).active_document_id = newer.id
        listed = (await client.get("/api/v1/chats", params={"paper_id": str(second)})).json()
        assert listed["items"][0]["papers"][1]["document_id"] == str(second_pdf)

        for paper, _, _ in seeded[2:5]:
            assert (
                await client.post(
                    f"/api/v1/chats/{chat['id']}/papers", json={"paper_id": str(paper)}
                )
            ).status_code == 200
        sixth = await client.post(
            f"/api/v1/chats/{chat['id']}/papers", json={"paper_id": str(seeded[5][0])}
        )
        assert sixth.status_code == 200 and len(sixth.json()["papers"]) == 6
        unknown = await client.post(
            f"/api/v1/chats/{chat['id']}/papers", json={"paper_id": str(uuid4())}
        )
        assert unknown.status_code == 404 and unknown.json()["code"] == "PAPER_NOT_FOUND"
        gone = await client.post(f"/api/v1/chats/{uuid4()}/papers", json={"paper_id": str(first)})
        assert gone.status_code == 404 and gone.json()["code"] == "CHAT_NOT_FOUND"


async def test_given_a_removed_paper_when_history_is_read_then_citations_remain_and_name_it(
    resources,
):
    """Removing the URL's paper moves the chat's first paper; the last paper stays."""
    (first, first_pdf, first_chunks), (second, _, _) = await papers(resources, 2)
    async with client_for(resources) as client:
        chat = (
            await client.post("/api/v1/chats", json={"paper_ids": [str(first), str(second)]})
        ).json()
        citation = {
            "chunk_id": str(first_chunks[1]),
            "document_id": str(first_pdf),
            "page": 2,
            "excerpt": "Researchers ask precise questions.",
        }
        async with resources.sessions() as session, session.begin():
            for role, content, cited in (
                ("user", "What do researchers ask?", []),
                ("assistant", f"Precise questions [source:{first_chunks[1]}].", [citation]),
            ):
                session.add(
                    ChatMessage(
                        session_id=chat["id"],
                        role=role,
                        content=content,
                        state="completed",
                        citations=cited,
                        request_id=uuid4(),
                    )
                )
        removed = await client.delete(f"/api/v1/chats/{chat['id']}/papers/{first}")
        assert removed.status_code == 200, removed.text
        assert removed.json()["paper_id"] == str(second)
        assert [item["paper_id"] for item in removed.json()["papers"]] == [str(second)]
        under_first = (await client.get("/api/v1/chats", params={"paper_id": str(first)})).json()
        assert under_first == {"items": []}
        history = (await client.get(f"/api/v1/chats/{chat['id']}/messages")).json()["items"]
        (answer,) = [item for item in history if item["role"] == "assistant"]
        assert answer["content"].endswith(f"[source:{first_chunks[1]}].")
        assert answer["citations"][0]["chunk_id"] == str(first_chunks[1])
        assert answer["citations"][0]["paper_id"] == str(first)

        last = await client.delete(f"/api/v1/chats/{chat['id']}/papers/{second}")
        assert last.status_code == 409 and last.json()["code"] == "LAST_CHAT_PAPER"
        absent = await client.delete(f"/api/v1/chats/{chat['id']}/papers/{first}")
        assert absent.status_code == 404 and absent.json()["code"] == "CHAT_PAPER_NOT_FOUND"
    async with resources.sessions() as session:
        rows = (await session.scalars(select(ChatPaper.paper_id))).all()
    assert rows == [second]


async def test_given_a_deleted_paper_then_its_one_paper_chats_go_and_others_keep_their_papers(
    resources,
):
    """As when a chat belonged to one paper: deleting the paper deletes chats left without one."""
    from sqlalchemy import delete

    from app.models.research import ChatSession

    (first, _, _), (second, _, _) = await papers(resources, 2)
    async with client_for(resources) as client:
        alone = (await client.post("/api/v1/chats", json={"paper_ids": [str(first)]})).json()
        shared = (
            await client.post("/api/v1/chats", json={"paper_ids": [str(first), str(second)]})
        ).json()
    async with resources.sessions() as session, session.begin():
        await session.execute(delete(Paper).where(Paper.id == first))
    async with resources.sessions() as session:
        assert await session.get(ChatSession, alone["id"]) is None
        assert await session.get(ChatSession, shared["id"]) is not None
        rows = (await session.execute(select(ChatPaper.chat_id, ChatPaper.paper_id))).all()
    assert [tuple(row) for row in rows] == [(UUID(shared["id"]), second)]


async def test_given_a_chat_id_when_reading_the_chat_then_its_papers_and_activity_return(resources):
    """A chat link from any of its papers can find the chat's first paper (its canonical URL)."""
    (first, _, _), (second, _, _) = await papers(resources, 2)
    async with client_for(resources) as client:
        chat = (
            await client.post("/api/v1/chats", json={"paper_ids": [str(first), str(second)]})
        ).json()
        found = await client.get(f"/api/v1/chats/{chat['id']}")
        assert found.status_code == 200, found.text
        body = found.json()
        assert body["paper_id"] == str(first) and included(body) == included(chat)
        assert body["message_count"] == 0 and body["last_activity_at"] == chat["created_at"]
        missing = await client.get(f"/api/v1/chats/{uuid4()}")
        assert missing.status_code == 404 and missing.json()["code"] == "CHAT_NOT_FOUND"
