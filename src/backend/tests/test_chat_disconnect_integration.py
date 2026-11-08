"""Whether a paid answer stops when the client leaves, through the real middleware stack.

The app runs under real uvicorn and the client is a raw TCP socket, so the disconnect is a real
one. Only the model's HTTP stream is a fixture, paced so that a generation left running is seen
to keep going. The unit tests of this path pass a fake request and skip the middleware.
"""

import asyncio
import contextlib
import json
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr
from support.live_api import live_api

from app.models.research import ChatMessage
from tests.support.answers import first_handle
from tests.support.chats import new_chat
from tests.support.evidence import seed_structured
from tests.support.providers import openai_fixture
from tests.test_ai import response_payload

pytestmark = pytest.mark.integration

FILLER_FRAMES = 400
FRAME_SECONDS = 0.02


class PacedAnswer(httpx.AsyncByteStream):
    """A provider stream that keeps producing tokens until it is closed."""

    def __init__(self, frames: list[bytes]):
        self.frames, self.sent, self.finished = frames, 0, False
        self.closed = asyncio.Event()

    async def __aiter__(self):
        for frame in self.frames:
            self.sent += 1
            yield frame
            await asyncio.sleep(FRAME_SECONDS)
        self.finished = True

    async def aclose(self):
        self.closed.set()


def delta(text: str, index: int) -> bytes:
    event = {
        "type": "response.output_text.delta",
        "delta": text,
        "item_id": "msg",
        "output_index": 0,
        "content_index": 0,
        "sequence_number": index,
    }
    return ("data: " + json.dumps(event) + "\n\n").encode()


@pytest.fixture
def provider(resources, monkeypatch):
    """The model, mocked at HTTP. `calls` holds one PacedAnswer per generation."""
    from app.integrations import embeddings
    from app.integrations.llm import HostedLLM
    from app.rag import pipeline
    from app.services import chat

    resources.settings.openai_api_key = SecretStr("http-fixture-only")
    monkeypatch.setattr(
        pipeline,
        "create_embedder",
        lambda resources, profile: embeddings.create_embedder(
            resources, profile, transport=openai_fixture([])
        ),
    )
    calls: list[PacedAnswer] = []
    settings = {"filler": FILLER_FRAMES}

    def respond(request):
        body = json.loads(request.content)
        texts = ["Words. "] * settings["filler"] + [f"Recall improves [{first_handle(body)}]."]
        frames = [delta(text, index) for index, text in enumerate(texts)]
        done = {
            "type": "response.completed",
            "response": response_payload("".join(texts)),
            "sequence_number": len(texts),
        }
        frames.append(("data: " + json.dumps(done) + "\n\n").encode())
        answer = PacedAnswer(frames)
        calls.append(answer)
        return httpx.Response(200, stream=answer, headers={"Content-Type": "text/event-stream"})

    monkeypatch.setattr(
        chat,
        "create_llm",
        lambda resources, model, **kwargs: HostedLLM(
            resources.settings,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
        ),
    )
    return calls, settings


async def open_answer(port: int, chat_id):
    body = json.dumps(
        {
            "model": "gpt-5.6-luna",
            "reasoning_effort": "low",
            "content": "How does BM25 recall compare?",
            "request_id": str(uuid4()),
        }
    ).encode()
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(
        (
            f"POST /api/v1/chats/{chat_id}/messages/stream HTTP/1.1\r\nHost: 127.0.0.1\r\n"
            f"Connection: close\r\nContent-Type: application/json\r\n"
            f"Content-Length: {len(body)}\r\n\r\n"
        ).encode()
        + body
    )
    await writer.drain()
    return reader, writer


async def leave(writer) -> None:
    writer.close()
    await writer.wait_closed()


async def assistant_state(resources, chat_id) -> tuple[str, str]:
    from sqlalchemy import select

    async with resources.sessions() as session:
        row = await session.scalar(
            select(ChatMessage).where(
                ChatMessage.session_id == chat_id, ChatMessage.role == "assistant"
            )
        )
    return row.state, row.content


async def settled_state(resources, chat_id) -> tuple[str, str]:
    """The answer's state once it stops being `processing`, or `processing` after 5 seconds."""
    with contextlib.suppress(TimeoutError):
        async with asyncio.timeout(5):
            while (await assistant_state(resources, chat_id))[0] == "processing":  # noqa: ASYNC110
                await asyncio.sleep(0.02)
    return await assistant_state(resources, chat_id)


async def seeded_chat(resources):
    paper_id, document_id, _ = await seed_structured(resources)
    return await new_chat(resources, (paper_id, document_id))


async def test_a_client_gone_mid_answer_stops_the_paid_stream(resources, provider):
    """Given a client that leaves after the first tokens, the provider stream is closed early."""
    calls, _ = provider
    chat_id = await seeded_chat(resources)
    async with live_api(resources) as port:
        reader, writer = await open_answer(port, chat_id)
        await asyncio.wait_for(reader.readuntil(b"message.delta"), 15)
        await leave(writer)
        (answer,) = calls
        sent_when_left = answer.sent
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(answer.closed.wait(), 3)
        sent_when_closed = answer.sent
        await asyncio.sleep(0.2)  # A stream that is really over sends nothing more.
        state, content = await settled_state(resources, chat_id)
    assert answer.closed.is_set() and not answer.finished, (
        f"the provider kept streaming: {answer.sent} of {len(answer.frames)} frames"
    )
    # 50 frames is a second of generation at this pace, against 8 for the whole answer.
    assert sent_when_closed - sent_when_left < 50 and answer.sent == sent_when_closed
    assert state == "interrupted" and content.startswith("Words.")


async def test_a_client_gone_before_generation_never_calls_the_model(
    resources, provider, monkeypatch
):
    """Given a client that leaves while evidence is retrieved, no paid generation starts."""
    from app.services import chat

    calls, _ = provider
    chat_id = await seeded_chat(resources)
    reached, release = asyncio.Event(), asyncio.Event()
    retrieve = chat.retrieve_evidence

    async def gated(*args, **kwargs):
        reached.set()
        await release.wait()
        return await retrieve(*args, **kwargs)

    monkeypatch.setattr(chat, "retrieve_evidence", gated)
    async with live_api(resources) as port:
        reader, writer = await open_answer(port, chat_id)
        await asyncio.wait_for(reader.readuntil(b"message.started"), 15)
        await asyncio.wait_for(reached.wait(), 5)
        await leave(writer)
        await asyncio.sleep(0.3)  # Let the server see the disconnect before retrieval goes on.
        release.set()
        state, _ = await settled_state(resources, chat_id)
        await asyncio.sleep(0.5)
    assert calls == []
    assert state == "interrupted"


async def test_a_client_that_stays_receives_the_whole_answer(resources, provider):
    """The control: over the same socket path, the provider runs to the end."""
    calls, settings = provider
    settings["filler"] = 5
    chat_id = await seeded_chat(resources)
    async with live_api(resources) as port:
        reader, writer = await open_answer(port, chat_id)
        received = await asyncio.wait_for(reader.read(), 15)
        await leave(writer)
    (answer,) = calls
    assert b"message.completed" in received and b"message.failed" not in received
    assert answer.finished and answer.sent == len(answer.frames)
    assert (await assistant_state(resources, chat_id))[0] == "completed"
