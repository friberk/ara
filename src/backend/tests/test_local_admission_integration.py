"""A local question waits a bounded time for background local work (ARA-077)."""

from contextlib import AsyncExitStack
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import func, select

from app.models.local_models import ModelUse
from app.models.research import ChatMessage, ChatSession
from tests.support.answers import CONNECTED, named, parse
from tests.test_ai_integration import local_fixture, paper_fixture

pytestmark = pytest.mark.integration


def question(spec) -> dict:
    return {
        "model": spec.key,
        "reasoning_effort": "default",
        "content": "What accuracy?",
        "request_id": str(uuid4()),
    }


async def post(resources, chat_id, body) -> httpx.Response:
    from app.main import create_app

    app = create_app(resources.settings)
    app.state.resources = resources
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        return await client.post(f"/api/v1/chats/{chat_id}/messages/stream", json=body)


async def answering_elsewhere(resources, paper_id, document_id, model: str) -> None:
    """Another chat streaming a local answer: an interactive holder the reader can see."""
    async with resources.sessions() as session, session.begin():
        other = ChatSession(paper_id=paper_id, document_id=document_id, title="Other")
        session.add(other)
        await session.flush()
        session.add(
            ChatMessage(
                session_id=other.id,
                role="assistant",
                content="",
                state="processing",
                model=model,
                reasoning_effort="default",
                citations=[],
                request_id=uuid4(),
                lease_expires_at=datetime.now(UTC) + timedelta(seconds=60),
            )
        )


async def uses(resources) -> int:
    async with resources.sessions() as session:
        return await session.scalar(select(func.count()).select_from(ModelUse))


async def test_given_another_local_answer_holds_the_slot_when_asking_then_429_at_once(resources):
    from app.repositories.local_models import acquire_use, release_use

    spec, requests = await local_fixture(resources)
    paper_id, document_id, chat_id = await paper_fixture(resources)
    await answering_elsewhere(resources, paper_id, document_id, spec.key)
    token = await acquire_use(resources.sessions, spec.key)
    try:
        response = await post(resources, chat_id, question(spec))
    finally:
        await release_use(resources.sessions, token)
    assert response.status_code == 429, response.text
    assert response.json()["code"] == "LOCAL_MODEL_BUSY"
    assert requests == []


async def test_given_background_work_outlasts_the_wait_when_asking_then_busy_after_waiting(
    resources, monkeypatch
):
    from app.repositories.local_models import acquire_use, release_use
    from app.services import chat

    monkeypatch.setattr(chat, "LOCAL_ADMISSION_WAIT_SECONDS", 0.3)
    monkeypatch.setattr(chat, "ADMISSION_POLL_SECONDS", 0.05)
    spec, requests = await local_fixture(resources)
    _, _, chat_id = await paper_fixture(resources)
    # A conversation summary holds the slot; no answer is visibly running.
    token = await acquire_use(resources.sessions, spec.key)
    try:
        response = await post(resources, chat_id, question(spec))
    finally:
        await release_use(resources.sessions, token)
    assert response.status_code == 200, response.text
    events = parse(response.text.split("\n\n"))
    assert [event for event, _ in events] == ["message.started", "message.status", "message.failed"]
    assert named(events, "message.status")[0]["stage"] == "waiting"
    (failed,) = named(events, "message.failed")
    assert failed["code"] == "LOCAL_MODEL_BUSY"
    assert failed["message"] == "A local generation is already running."
    assert requests == []
    async with resources.sessions() as session:
        answer = await session.get(ChatMessage, failed["message_id"])
    assert answer.state == "failed"


async def test_given_background_work_ends_while_waiting_then_the_question_is_answered(
    resources, monkeypatch
):
    from app.repositories.local_models import acquire_use, release_use
    from app.schemas.ai import ChatInput
    from app.services import chat

    monkeypatch.setattr(chat, "ADMISSION_POLL_SECONDS", 0.05)
    spec, requests = await local_fixture(resources)
    _, _, chat_id = await paper_fixture(resources)
    token = await acquire_use(resources.sessions, spec.key)
    prepared = await chat.prepare(resources, chat_id, ChatInput(**question(spec)))
    slots, frames = AsyncExitStack(), []
    try:
        async for frame in chat.stream_answer(
            resources, CONNECTED, prepared, inference_slot=slots, wait_for_slot=True
        ):
            frames.append(frame)
            if parse([frame]) == [
                ("message.status", {"message_id": str(prepared.assistant.id), "stage": "waiting"})
            ]:
                # Nothing reaches the runtime while the summary holds it.
                assert requests == []
                await release_use(resources.sessions, token)
    finally:
        await slots.aclose()
    events = parse(frames)
    stages = [data["stage"] for data in named(events, "message.status")]
    assert stages[0] == "waiting" and stages[-1] == "generating" and "planning" in stages
    assert named(events, "message.completed") and len(requests) == 1
    assert await uses(resources) == 0


async def test_given_a_lost_runtime_lease_cancels_the_producer_then_the_answer_fails_not_hangs(
    resources, monkeypatch
):
    import asyncio

    from app.schemas.ai import ChatInput
    from app.services import chat

    spec, requests = await local_fixture(resources)
    _, _, chat_id = await paper_fixture(resources)
    prepared = await chat.prepare(resources, chat_id, ChatInput(**question(spec)))

    async def lose_lease(*args, **kwargs):
        # What the slot's heartbeat does to its owner, here the producer, on a lost lease.
        asyncio.current_task().cancel()
        await asyncio.sleep(1)

    monkeypatch.setattr(chat, "retrieve_evidence", lose_lease)
    async with asyncio.timeout(30):
        frames = [
            frame
            async for frame in chat.stream_answer(
                resources, CONNECTED, prepared, inference_slot=AsyncExitStack()
            )
        ]
    (failed,) = named(parse(frames), "message.failed")
    assert failed["code"] == "LOCAL_MODEL_LEASE_LOST" and requests == []
