"""AI persistence checks on the opt-in real PostgreSQL fixture, never SQLite."""

import asyncio
from datetime import timedelta
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import delete, func, select

from app.models.research import (
    ChatMessage,
    ChatSession,
    Document,
    DocumentChunk,
    GenerationReservation,
    Paper,
    PaperSummary,
)
from app.repositories.jobs import claim, enqueue, now

pytestmark = pytest.mark.integration


async def paper_fixture(resources):
    async with resources.sessions() as session, session.begin():
        paper = Paper(title="Traceable research")
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
            page_count=3,
        )
        session.add(document)
        await session.flush()
        paper.active_document_id = document.id
        for index, source in enumerate(
            [
                "Introduction: traceable systems use source evidence.",
                "Methods: blue condition achieved 87 percent accuracy.",
                "Conclusion: measured results require page citations.",
            ]
        ):
            session.add(
                DocumentChunk(
                    document_id=document.id,
                    ordinal=index,
                    page=index + 1,
                    text=source,
                    char_start=0,
                    char_end=len(source),
                    token_estimate=20,
                )
            )
        chat = ChatSession(paper_id=paper.id, document_id=document.id, title="Discussion")
        session.add(chat)
        await session.flush()
        return paper.id, document.id, chat.id


async def test_given_two_documents_when_retrieving_then_scope_is_immutable(resources):
    from app.services.retrieval import retrieve

    _, first, _ = await paper_fixture(resources)
    _, second, _ = await paper_fixture(resources)
    async with resources.sessions() as session:
        chunks = await retrieve(session, first, "blue accuracy")
        assert chunks and {chunk.document_id for chunk in chunks} == {first}
        assert second not in {chunk.document_id for chunk in chunks}
        assert any("87 percent" in chunk.text for chunk in chunks)
        fallback = await retrieve(session, first, "nonexistentterm")
        assert {chunk.page for chunk in fallback} == {1, 2, 3}


async def test_given_metadata_only_when_creating_chat_or_summary_then_ready_gate(resources):
    from app.main import create_app

    async with resources.sessions() as session, session.begin():
        paper = Paper(title="Metadata only")
        session.add(paper)
        await session.flush()
        paper_id = paper.id
    app = create_app(resources.settings)
    app.state.resources = resources
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        response = await client.post(f"/api/v1/papers/{paper_id}/chats", json={})
        assert response.status_code == 409
        response = await client.post(
            f"/api/v1/papers/{paper_id}/summaries",
            json={"model": "gpt-5.6-luna", "reasoning_effort": "low", "request_id": str(uuid4())},
        )
        assert response.status_code == 409


async def test_given_concurrent_budget_reservations_when_cap_exceeded_then_one_allowed(resources):
    from app.integrations.llm import LLMError, reservation_amount, reserve

    async with resources.sessions() as session, session.begin():
        await session.execute(delete(GenerationReservation))
    resources.settings.llm_daily_budget_usd = (
        float(reservation_amount("gpt-5.6-luna", 1000)) + 0.000001
    )
    results = await asyncio.gather(
        reserve(resources, "gpt-5.6-luna", 1000),
        reserve(resources, "gpt-5.6-luna", 1000),
        return_exceptions=True,
    )
    assert sum(isinstance(result, LLMError) for result in results) == 1
    async with resources.sessions() as session:
        assert await session.scalar(select(func.count(GenerationReservation.id))) == 1


async def test_given_partial_request_when_expired_then_replay_never_reserves_again(resources):
    from app.schemas.ai import ChatInput
    from app.services.chat import prepare, save

    _, _, chat_id = await paper_fixture(resources)
    resources.settings.openai_api_key = __import__("pydantic").SecretStr("fixture")
    body = ChatInput(content="What accuracy?", request_id=uuid4())
    first, _, _, replay = await prepare(resources, chat_id, body)
    assert replay is False
    await save(resources, first.id, "partial evidence")
    async with resources.sessions() as session, session.begin():
        message = await session.get(ChatMessage, first.id)
        message.lease_expires_at = now() - timedelta(seconds=1)
        before = await session.scalar(select(func.count(GenerationReservation.id)))
    stored, prompt, _, replay = await prepare(resources, chat_id, body)
    assert replay and prompt is None and stored.id == first.id
    assert stored.state == "interrupted" and stored.content == "partial evidence"
    async with resources.sessions() as session:
        assert await session.scalar(select(func.count(GenerationReservation.id))) == before


async def test_given_summary_unknown_paid_outcome_when_worker_recovers_then_no_new_generation(
    resources,
):
    from app.models.jobs import BackgroundJob
    from app.services.summarization import run_summary_job

    paper_id, document_id, _ = await paper_fixture(resources)
    resources.settings.openai_api_key = __import__("pydantic").SecretStr("fixture")
    payload = {
        "paper_id": str(paper_id),
        "document_id": str(document_id),
        "model": "gpt-5.6-luna",
        "reasoning_effort": "low",
        "request_id": str(uuid4()),
        "paid_call_inflight": True,
    }
    async with resources.sessions() as session, session.begin():
        job = await enqueue(session, kind="summary", payload=payload)
        job_id = job.id
    token = await claim(resources.sessions, job_id, 1)
    await run_summary_job(resources, job_id, 1, token, payload)
    async with resources.sessions() as session:
        job = await session.get(BackgroundJob, job_id)
        assert job.state == "failed" and job.error_code == "GENERATION_OUTCOME_UNKNOWN"
        assert await session.scalar(select(func.count(PaperSummary.id))) == 0


async def test_given_stream_when_completed_then_final_persisted_and_uuid_replay_is_free(
    resources, monkeypatch
):
    import json
    import re

    from pydantic import SecretStr

    from app.integrations.llm import HostedLLM
    from app.schemas.ai import ChatInput
    from app.services import chat
    from tests.test_ai import response_payload

    _, document_id, chat_id = await paper_fixture(resources)
    resources.settings.openai_api_key = SecretStr("fixture")
    calls = []

    def provider(request):
        body = json.loads(request.content)
        calls.append(body)
        source = re.findall(r"\[source:([\w-]+)\]", body["input"])[0]
        output = f"The paper supplies evidence [source:{source}]."
        events = [
            {
                "type": "response.output_text.delta",
                "delta": output,
                "item_id": "msg",
                "output_index": 0,
                "content_index": 0,
                "sequence_number": 0,
            },
            {
                "type": "response.completed",
                "response": response_payload(output),
                "sequence_number": 1,
            },
        ]
        wire = "".join("data: " + json.dumps(item) + "\n\n" for item in events)
        return httpx.Response(200, content=wire, headers={"Content-Type": "text/event-stream"})

    monkeypatch.setattr(
        chat,
        "HostedLLM",
        lambda settings: HostedLLM(
            settings, http_client=httpx.AsyncClient(transport=httpx.MockTransport(provider))
        ),
    )
    request = type(
        "Request", (), {"is_disconnected": lambda self: asyncio.sleep(0, result=False)}
    )()
    body = ChatInput(content="What accuracy?", request_id=uuid4())
    assistant, prompt, chunks, replay = await chat.prepare(resources, chat_id, body)
    frames = chat.stream_answer(resources, request, assistant, prompt, chunks, replay)
    assert "message.started" in await anext(frames)
    async with resources.sessions() as session:
        stored = await session.get(ChatMessage, assistant.id)
        assert stored.state == "processing" and stored.content == ""
    assert "message.delta" in await anext(frames)
    async with resources.sessions() as session:
        stored = await session.get(ChatMessage, assistant.id)
        assert stored.state == "processing"
    completed = await anext(frames)
    assert "message.completed" in completed
    async with resources.sessions() as session:
        stored = await session.get(ChatMessage, assistant.id)
        assert stored.state == "completed"
        assert stored.citations[0]["document_id"] == str(document_id)
    await frames.aclose()
    existing, prompt, chunks, replay = await chat.prepare(resources, chat_id, body)
    assert replay and existing.id == assistant.id
    replayed = "".join(
        [
            frame
            async for frame in chat.stream_answer(
                resources, request, existing, prompt, chunks, replay
            )
        ]
    )
    assert "message.completed" in replayed and len(calls) == 1


async def test_given_summary_fixture_when_generated_then_domain_and_job_complete_together(
    resources, monkeypatch
):
    import json
    import re

    from pydantic import SecretStr

    from app.integrations.llm import HostedLLM
    from app.models.jobs import BackgroundJob
    from app.services import summarization
    from tests.test_ai import response_payload

    paper_id, document_id, _ = await paper_fixture(resources)
    resources.settings.openai_api_key = SecretStr("fixture")
    seen_inputs = []

    def provider(request):
        prompt = json.loads(request.content)["input"]
        seen_inputs.append(prompt)
        citations = re.findall(r"\[source:([\w-]+)\]", prompt)
        content = "Supported full paper summary: " + " ".join(
            f"[source:{identifier}]" for identifier in citations
        )
        return httpx.Response(200, json=response_payload(content))

    monkeypatch.setattr(
        summarization,
        "HostedLLM",
        lambda settings: HostedLLM(
            settings, http_client=httpx.AsyncClient(transport=httpx.MockTransport(provider))
        ),
    )
    payload = {
        "paper_id": str(paper_id),
        "document_id": str(document_id),
        "model": "gpt-5.6-luna",
        "reasoning_effort": "low",
        "request_id": str(uuid4()),
    }
    async with resources.sessions() as session, session.begin():
        job = await enqueue(session, kind="summary", payload=payload)
        job_id = job.id
    token = await claim(resources.sessions, job_id, 1)
    await summarization.run_summary_job(resources, job_id, 1, token, payload)
    async with resources.sessions() as session:
        job = await session.get(BackgroundJob, job_id)
        assert job.state == "completed"
        summary = await session.get(PaperSummary, job.result["summary_id"])
        assert summary.document_id == document_id and len(summary.citations) == 3
        assert summary.configuration["covered_chunks"] == 3 and summary.usage["total_tokens"] == 25
        assert "87 percent" in seen_inputs[0] and "Conclusion" in seen_inputs[0]
    await summarization.run_summary_job(resources, job_id, 1, token, payload)
    assert len(seen_inputs) == 1


def sdk_stream_fixture(monkeypatch, module, content, calls):
    import json

    from app.integrations.llm import HostedLLM
    from tests.test_ai import response_payload

    events = [
        {
            "type": "response.output_text.delta",
            "delta": content,
            "item_id": "msg",
            "output_index": 0,
            "content_index": 0,
            "sequence_number": 0,
        },
        {"type": "response.completed", "response": response_payload(content), "sequence_number": 1},
    ]
    wire = "".join("data: " + json.dumps(item) + "\n\n" for item in events)

    def provider(request):
        calls.append(request)
        return httpx.Response(200, content=wire, headers={"Content-Type": "text/event-stream"})

    monkeypatch.setattr(
        module,
        "HostedLLM",
        lambda settings: HostedLLM(
            settings, http_client=httpx.AsyncClient(transport=httpx.MockTransport(provider))
        ),
    )


async def test_given_disconnect_when_stream_closes_then_partial_flushes_and_replay_is_free(
    resources, monkeypatch
):
    from pydantic import SecretStr

    from app.schemas.ai import ChatInput
    from app.services import chat

    _, _, chat_id = await paper_fixture(resources)
    resources.settings.openai_api_key = SecretStr("fixture")
    calls = []
    sdk_stream_fixture(monkeypatch, chat, "Visible partial answer", calls)
    request = type(
        "Request", (), {"is_disconnected": lambda self: asyncio.sleep(0, result=False)}
    )()
    body = ChatInput(content="What accuracy?", request_id=uuid4())
    assistant, prompt, chunks, replay = await chat.prepare(resources, chat_id, body)
    stream = chat.stream_answer(resources, request, assistant, prompt, chunks, replay)
    await anext(stream)
    assert "Visible partial answer" in await anext(stream)
    await stream.aclose()
    async with resources.sessions() as session:
        stored = await session.get(ChatMessage, assistant.id)
        assert stored.state == "interrupted" and stored.content == "Visible partial answer"
    stored, prompt, chunks, replay = await chat.prepare(resources, chat_id, body)
    frames = "".join(
        [
            frame
            async for frame in chat.stream_answer(
                resources, request, stored, prompt, chunks, replay
            )
        ]
    )
    assert "message.failed" in frames and len(calls) == 1


async def test_given_invented_citation_when_stream_finishes_then_fail_with_safe_grounding_code(
    resources, monkeypatch
):
    from pydantic import SecretStr

    from app.schemas.ai import ChatInput
    from app.services import chat

    _, _, chat_id = await paper_fixture(resources)
    resources.settings.openai_api_key = SecretStr("fixture")
    calls = []
    sdk_stream_fixture(monkeypatch, chat, f"Claim [source:{uuid4()}]", calls)
    request = type(
        "Request", (), {"is_disconnected": lambda self: asyncio.sleep(0, result=False)}
    )()
    body = ChatInput(content="What accuracy?", request_id=uuid4())
    assistant, prompt, chunks, replay = await chat.prepare(resources, chat_id, body)
    frames = "".join(
        [
            frame
            async for frame in chat.stream_answer(
                resources, request, assistant, prompt, chunks, replay
            )
        ]
    )
    assert "UNGROUNDED_OUTPUT" in frames and "message.completed" not in frames
    async with resources.sessions() as session:
        stored = await session.get(ChatMessage, assistant.id)
        assert stored.state == "failed" and stored.citations == []


async def test_given_over_budget_document_when_summarized_then_map_reduce_covers_all_chunks(
    resources, monkeypatch
):
    import json
    import re

    from pydantic import SecretStr

    from app.integrations.llm import HostedLLM
    from app.models.jobs import BackgroundJob
    from app.services import summarization
    from tests.test_ai import response_payload

    paper_id, document_id, _ = await paper_fixture(resources)
    resources.settings.openai_api_key = SecretStr("fixture")
    async with resources.sessions() as session, session.begin():
        for index in range(3, 15):
            source = f"Section {index}: full-coverage evidence. " * 200
            session.add(
                DocumentChunk(
                    document_id=document_id,
                    ordinal=index,
                    page=index + 1,
                    text=source,
                    char_start=0,
                    char_end=len(source),
                    token_estimate=1700,
                )
            )
    seen_inputs = []

    def provider(request):
        prompt = json.loads(request.content)["input"]
        seen_inputs.append(prompt)
        sources = re.findall(r"\[source:([\w-]+)\]", prompt)
        answer = "Complete covered sections: " + " ".join(
            f"[source:{source}]" for source in sources
        )
        return httpx.Response(200, json=response_payload(answer))

    monkeypatch.setattr(
        summarization,
        "HostedLLM",
        lambda settings: HostedLLM(
            settings, http_client=httpx.AsyncClient(transport=httpx.MockTransport(provider))
        ),
    )
    payload = {
        "paper_id": str(paper_id),
        "document_id": str(document_id),
        "model": "gpt-5.6-luna",
        "reasoning_effort": "low",
        "request_id": str(uuid4()),
    }
    async with resources.sessions() as session, session.begin():
        job = await enqueue(session, kind="summary", payload=payload)
        job_id = job.id
    token = await claim(resources.sessions, job_id, 1)
    await summarization.run_summary_job(resources, job_id, 1, token, payload)
    async with resources.sessions() as session:
        job = await session.get(BackgroundJob, job_id)
        assert job.state == "completed", job.error_code
        summary = await session.get(PaperSummary, job.result["summary_id"])
        assert len(summary.citations) == 15 and summary.configuration["covered_chunks"] == 15
        assert len(job.payload["partials"]) > 1 and job.payload["paid_call_inflight"] is False
    assert len(seen_inputs) > 2 and any("Section 14:" in prompt for prompt in seen_inputs)
    assert seen_inputs[-1].startswith("Combine every section")


async def test_given_asgi_level_cancellation_when_disconnected_then_database_retains_partial(
    resources, monkeypatch
):
    import json

    from fastapi.responses import StreamingResponse
    from pydantic import SecretStr

    from app.integrations.llm import HostedLLM
    from app.schemas.ai import ChatInput
    from app.services import chat

    _, _, chat_id = await paper_fixture(resources)
    resources.settings.openai_api_key = SecretStr("fixture")
    delta_sent = asyncio.Event()
    closed = []
    calls = []
    output = "Visible answer before ASGI disconnect"
    payload = {
        "type": "response.output_text.delta",
        "delta": output,
        "item_id": "msg",
        "output_index": 0,
        "content_index": 0,
        "sequence_number": 0,
    }

    class PendingStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield ("data: " + json.dumps(payload) + "\n\n").encode()
            await asyncio.Event().wait()

        async def aclose(self):
            await asyncio.sleep(0)

    class AwaitingTransport(httpx.MockTransport):
        async def aclose(self):
            await asyncio.sleep(0)
            closed.append(True)
            await super().aclose()

    def provider(request):
        calls.append(request)
        return httpx.Response(
            200, stream=PendingStream(), headers={"Content-Type": "text/event-stream"}
        )

    monkeypatch.setattr(
        chat,
        "HostedLLM",
        lambda settings: HostedLLM(
            settings, http_client=httpx.AsyncClient(transport=AwaitingTransport(provider))
        ),
    )
    request = type(
        "Request", (), {"is_disconnected": lambda self: asyncio.sleep(0, result=False)}
    )()
    body = ChatInput(content="What accuracy?", request_id=uuid4())
    assistant, prompt, chunks, replay = await chat.prepare(resources, chat_id, body)
    response = StreamingResponse(
        chat.stream_answer(resources, request, assistant, prompt, chunks, replay)
    )

    async def receive():
        await delta_sent.wait()
        return {"type": "http.disconnect"}

    async def send(message):
        if message["type"] == "http.response.body" and b"message.delta" in message["body"]:
            delta_sent.set()

    await asyncio.wait_for(
        response({"type": "http", "asgi": {"spec_version": "2.3"}}, receive, send), timeout=5
    )
    assert closed == [True]
    async with resources.sessions() as session:
        stored = await session.get(ChatMessage, assistant.id)
        assert stored.state == "interrupted" and stored.content == output
    existing, prompt, chunks, replay = await chat.prepare(resources, chat_id, body)
    assert replay and existing.id == assistant.id and existing.state == "interrupted"
    assert len(calls) == 1
