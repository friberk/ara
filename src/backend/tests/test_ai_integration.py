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


async def local_fixture(resources):
    import json
    import re

    from app.integrations.model_catalog import local_spec
    from app.models.local_models import ModelInstallation, ModelUse

    spec = local_spec("ifm-k2-horizon-7b")
    resources.settings.openai_api_key = None
    requests = []

    def provider(request):
        if request.url.path == "/api/tags":
            return httpx.Response(
                200,
                json={
                    "models": [
                        {
                            "name": spec.model_id,
                            "digest": spec.expected_digest,
                            "size": spec.download_bytes,
                        }
                    ]
                },
            )
        if request.url.path == "/api/version":
            return httpx.Response(200, json={"version": "0.40.1-ara.fixture"})
        if request.url.path == "/api/chat":
            payload = json.loads(request.content)
            requests.append(payload)
            prompt = payload["messages"][-1]["content"]
            markers = re.findall(r"\[source:[\w-]+\]", prompt)
            answer = "Supported sections: " + " ".join(dict.fromkeys(markers))
            result = {
                "message": {"role": "assistant", "content": answer},
                "done": True,
                "done_reason": "stop",
                "prompt_eval_count": 100,
                "eval_count": 50,
            }
            if payload["stream"]:
                return httpx.Response(200, text=json.dumps(result) + "\n")
            return httpx.Response(200, json=result)
        return httpx.Response(404)

    for name in ("http", "ollama_generation_http"):
        await getattr(resources, name).aclose()
        setattr(resources, name, httpx.AsyncClient(transport=httpx.MockTransport(provider)))
    async with resources.sessions() as session, session.begin():
        await session.execute(delete(ModelUse))
        await session.execute(delete(ModelInstallation))
        session.add(
            ModelInstallation(
                model_key=spec.key,
                state="ready",
                weights_present=True,
                digest=spec.expected_digest,
                validation={
                    "digest": spec.expected_digest,
                    "context_window": 8192,
                    "runtime_version": "0.40.1-ara.fixture",
                    "reasoning_efforts": ["default"],
                    "thinking_schema": 1,
                    "thinking": None,
                    "think_mapping": {},
                    "supports_streaming": True,
                    "supports_structured_output": True,
                },
            )
        )
    return spec, requests


async def test_given_local_chat_when_answering_then_provenance_citations_and_uuid_replay(
    resources,
):
    from app.schemas.ai import ChatInput
    from app.services import chat

    spec, requests = await local_fixture(resources)
    _, document_id, chat_id = await paper_fixture(resources)
    body = ChatInput(
        model=spec.key, reasoning_effort="default", content="What accuracy?", request_id=uuid4()
    )
    assistant, prompt, chunks, replay = await chat.prepare(resources, chat_id, body)
    request = type(
        "Request", (), {"is_disconnected": lambda self: asyncio.sleep(0, result=False)}
    )()
    output = "".join(
        [
            item
            async for item in chat.stream_answer(
                resources, request, assistant, prompt, chunks, replay
            )
        ]
    )
    assert "message.completed" in output
    async with resources.sessions() as session:
        saved = await session.get(ChatMessage, assistant.id)
        assert (
            saved.configuration["provider"] == "ollama"
            and saved.configuration["artifact_digest"] == spec.expected_digest
        )
        assert saved.configuration["runtime_version"] == "0.40.1-ara.fixture"
        assert saved.configuration["temperature"] == 0.0
        assert (
            saved.configuration["input_limit"] == 5632
            and saved.configuration["output_limit"] == 2048
        )
        assert saved.citations and all(
            c["document_id"] == str(document_id) for c in saved.citations
        )
        assert await session.scalar(select(func.count()).select_from(GenerationReservation)) == 0
    _, _, _, replay = await chat.prepare(resources, chat_id, body)
    assert replay and len(requests) == 1


async def test_given_local_full_paper_when_summarizing_then_every_section_is_reduced_under_context(
    resources,
):
    from app.integrations.llm import estimate_tokens
    from app.models.jobs import BackgroundJob
    from app.services import summarization

    spec, requests = await local_fixture(resources)
    paper_id, document_id, _ = await paper_fixture(resources)
    async with resources.sessions() as session, session.begin():
        await session.execute(delete(DocumentChunk).where(DocumentChunk.document_id == document_id))
        for index in range(12):
            text = f"Section {index}: " + "evidence " * 240
            session.add(
                DocumentChunk(
                    document_id=document_id,
                    ordinal=index,
                    page=index + 1,
                    text=text,
                    chunk_set="test",
                    page_end=index + 1,
                    context_text=text,
                    token_count=len(text),
                )
            )
    payload = {
        "paper_id": str(paper_id),
        "document_id": str(document_id),
        "model": spec.key,
        "reasoning_effort": "default",
        "request_id": str(uuid4()),
    }
    async with resources.sessions() as session, session.begin():
        job = await enqueue(session, kind="summary", payload=payload)
        identifier = job.id
    token = await claim(resources.sessions, identifier, 1)
    await summarization.run_summary_job(resources, identifier, 1, token, payload)
    async with resources.sessions() as session:
        job = await session.get(BackgroundJob, identifier)
        assert job.state == "completed", (job.error_code, job.error_message)
        summary = await session.get(PaperSummary, job.result["summary_id"])
        assert len(summary.citations) == 12 and summary.configuration["covered_chunks"] == 12
        assert summary.configuration["artifact_digest"] == spec.expected_digest
        assert await session.scalar(select(func.count()).select_from(GenerationReservation)) == 0
    assert len(requests) > 2 and any(
        "Section 11:" in x["messages"][-1]["content"] for x in requests
    )
    assert all(sum(estimate_tokens(m["content"]) for m in x["messages"]) <= 5632 for x in requests)


async def test_given_busy_local_summary_when_worker_runs_then_job_does_not_fail_or_spend_attempt(
    resources,
):
    from app.integrations.llm import LLMError
    from app.models.jobs import BackgroundJob
    from app.repositories.local_models import acquire_use, release_use
    from app.services import summarization

    spec, requests = await local_fixture(resources)
    paper_id, document_id, _ = await paper_fixture(resources)
    use = await acquire_use(resources.sessions, spec.key)
    payload = {
        "paper_id": str(paper_id),
        "document_id": str(document_id),
        "model": spec.key,
        "reasoning_effort": "default",
        "request_id": str(uuid4()),
    }
    async with resources.sessions() as session, session.begin():
        job = await enqueue(session, kind="summary", payload=payload)
        identifier = job.id
    token = await claim(resources.sessions, identifier, 1)
    try:
        with pytest.raises(LLMError) as failure:
            await summarization.run_summary_job(resources, identifier, 1, token, payload)
        assert failure.value.code == "LOCAL_MODEL_BUSY"
        async with resources.sessions() as session:
            job = await session.get(BackgroundJob, identifier)
            assert job.state == "processing" and not job.payload.get("paid_call_inflight")
        assert requests == []
    finally:
        await release_use(resources.sessions, use)


async def test_given_local_default_when_extracting_metadata_then_no_hosted_key_needed(
    resources,
):
    import json

    from app.integrations.llm import extract_metadata, metadata_available
    from app.models.research import ModelConfiguration

    spec, _ = await local_fixture(resources)
    async with resources.sessions() as session, session.begin():
        session.add(
            ModelConfiguration(
                key="defaults", value={"default_model": spec.key, "reasoning_effort": "default"}
            )
        )
    requests = []

    def provider(request):
        requests.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "message": {
                    "content": json.dumps(
                        {
                            "title": "Traceable Research",
                            "authors": ["Ada Example"],
                            "year": 2024,
                            "abstract": None,
                            "doi": None,
                        }
                    )
                },
                "done": True,
                "done_reason": "stop",
            },
        )

    await resources.ollama_generation_http.aclose()
    resources.ollama_generation_http = httpx.AsyncClient(transport=httpx.MockTransport(provider))
    assert await metadata_available(resources)
    metadata = await extract_metadata(resources, "Traceable Research\nAda Example\n2024")
    assert metadata["title"] == "Traceable Research" and metadata["authors"] == ["Ada Example"]
    assert requests[0]["model"] == spec.model_id and "format" in requests[0]
    async with resources.sessions() as session:
        assert await session.scalar(select(func.count()).select_from(GenerationReservation)) == 0


async def test_given_busy_local_runtime_when_posting_chat_then_http_429_without_generation(
    resources,
):
    from app.main import create_app
    from app.repositories.local_models import acquire_use, release_use

    spec, requests = await local_fixture(resources)
    _, _, chat_id = await paper_fixture(resources)
    token = await acquire_use(resources.sessions, spec.key)
    app = create_app(resources.settings)
    app.state.resources = resources
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                f"/api/v1/chats/{chat_id}/messages/stream",
                json={
                    "model": spec.key,
                    "reasoning_effort": "default",
                    "content": "What accuracy?",
                    "request_id": str(uuid4()),
                },
            )
        assert response.status_code == 429, response.text
        assert response.json()["code"] == "LOCAL_MODEL_BUSY"
        assert requests == []
    finally:
        await release_use(resources.sessions, token)


async def test_given_runtime_503_when_local_summary_starts_then_rejection_clears_inflight(
    resources,
):
    from app.integrations.llm import LLMError
    from app.models.jobs import BackgroundJob
    from app.services import summarization

    spec, _ = await local_fixture(resources)
    paper_id, document_id, _ = await paper_fixture(resources)
    await resources.ollama_generation_http.aclose()
    resources.ollama_generation_http = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(503, json={"error": "busy"}))
    )
    payload = {
        "paper_id": str(paper_id),
        "document_id": str(document_id),
        "model": spec.key,
        "reasoning_effort": "default",
        "request_id": str(uuid4()),
    }
    async with resources.sessions() as session, session.begin():
        job = await enqueue(session, kind="summary", payload=payload)
        identifier = job.id
    token = await claim(resources.sessions, identifier, 1)
    with pytest.raises(LLMError) as failure:
        await summarization.run_summary_job(resources, identifier, 1, token, payload)
    assert failure.value.code == "LOCAL_MODEL_BUSY"
    async with resources.sessions() as session:
        job = await session.get(BackgroundJob, identifier)
        assert job.state == "processing" and job.payload["paid_call_inflight"] is False


async def summary_job_fixture(resources, spec, count):
    paper_id, document_id, _ = await paper_fixture(resources)
    async with resources.sessions() as session, session.begin():
        await session.execute(delete(DocumentChunk).where(DocumentChunk.document_id == document_id))
        for index in range(count):
            text = f"Section {index}: " + "x" * 4000
            session.add(
                DocumentChunk(
                    document_id=document_id,
                    ordinal=index,
                    page=index + 1,
                    text=text,
                    chunk_set="test",
                    page_end=index + 1,
                    context_text=text,
                    token_count=len(text),
                )
            )
        payload = {
            "paper_id": str(paper_id),
            "document_id": str(document_id),
            "model": spec.key,
            "reasoning_effort": "default",
            "request_id": str(uuid4()),
        }
        job = await enqueue(session, kind="summary", payload=payload)
        identifier = job.id
    token = await claim(resources.sessions, identifier, 1)
    return identifier, token, payload


@pytest.mark.parametrize("busy_kind", ["slot", "http"])
async def test_given_completed_reduction_when_later_group_busy_then_resume_skips_completed_group(
    resources,
    monkeypatch,
    busy_kind,
):
    import json
    import re
    from collections import Counter
    from contextlib import asynccontextmanager

    from app.integrations.llm import LLMError
    from app.models.jobs import BackgroundJob
    from app.services import summarization

    spec, _ = await local_fixture(resources)
    identifier, token, payload = await summary_job_fixture(resources, spec, 4)
    prompts, admissions = [], 0
    real_slots = summarization.generation_slots

    @asynccontextmanager
    async def slots(resources, model):
        nonlocal admissions
        admissions += 1
        if busy_kind == "slot" and admissions == 6:
            raise LLMError("LOCAL_MODEL_BUSY", "Busy", 429)
        async with real_slots(resources, model):
            yield

    monkeypatch.setattr(summarization, "generation_slots", slots)

    def provider(request):
        prompt = json.loads(request.content)["messages"][-1]["content"]
        prompts.append(prompt)
        if busy_kind == "http" and len(prompts) == 6:
            return httpx.Response(503, json={"error": "busy"})
        markers = " ".join(dict.fromkeys(re.findall(r"\[source:[0-9a-f-]+\]", prompt)))
        content = markers + " " + "z" * (1999 - len(markers))
        return httpx.Response(
            200,
            json={
                "message": {"content": content},
                "done": True,
                "done_reason": "stop",
                "prompt_eval_count": 100,
                "eval_count": 100,
            },
        )

    await resources.ollama_generation_http.aclose()
    resources.ollama_generation_http = httpx.AsyncClient(transport=httpx.MockTransport(provider))
    with pytest.raises(LLMError) as failure:
        await summarization.run_summary_job(resources, identifier, 1, token, payload)
    assert failure.value.code == "LOCAL_MODEL_BUSY"
    first_reduction_prompt = next(p for p in prompts if p.startswith("Combine every section"))
    async with resources.sessions() as session:
        job = await session.get(BackgroundJob, identifier)
        assert job.payload["paid_call_inflight"] is False
    await summarization.run_summary_job(resources, identifier, 1, token, payload)
    async with resources.sessions() as session:
        job = await session.get(BackgroundJob, identifier)
        assert job.state == "completed", job.error_code
        summary = await session.get(PaperSummary, job.result["summary_id"])
        assert len(summary.citations) == 4 and summary.configuration["covered_chunks"] == 4
    assert Counter(prompts)[first_reduction_prompt] == 1


@pytest.mark.parametrize("compression", ["short", "ignores_bound"])
async def test_given_long_valid_map_outputs_when_reducing_then_bounded_compression_keeps_sections(
    resources,
    compression,
):
    import json
    import re

    from app.integrations.llm import estimate_tokens
    from app.models.jobs import BackgroundJob
    from app.services import summarization

    spec, _ = await local_fixture(resources)
    identifier, token, payload = await summary_job_fixture(resources, spec, 2)
    calls = []

    def provider(request):
        body = json.loads(request.content)
        calls.append(body)
        prompt = body["messages"][-1]["content"]
        markers = " ".join(dict.fromkeys(re.findall(r"\[source:[0-9a-f-]+\]", prompt)))
        size = 1000 if prompt.startswith("Compress") and compression == "short" else 3000
        content = markers + " " + "z" * (size - len(markers) - 1)
        return httpx.Response(
            200,
            json={
                "message": {"content": content},
                "done": True,
                "done_reason": "stop",
                "prompt_eval_count": 100,
                "eval_count": 100,
            },
        )

    await resources.ollama_generation_http.aclose()
    resources.ollama_generation_http = httpx.AsyncClient(transport=httpx.MockTransport(provider))
    await summarization.run_summary_job(resources, identifier, 1, token, payload)
    async with resources.sessions() as session:
        job = await session.get(BackgroundJob, identifier)
        if compression == "short":
            assert job.state == "completed", job.error_code
            summary = await session.get(PaperSummary, job.result["summary_id"])
            assert len(summary.citations) == 2 and summary.configuration["covered_chunks"] == 2
            assert (
                sum(call["messages"][-1]["content"].startswith("Compress") for call in calls) == 2
            )
            assert calls[-1]["messages"][-1]["content"].startswith("Combine every section")
        else:
            assert job.state == "failed" and job.error_code == "SUMMARY_COMPRESSION_FAILED"
            assert len(calls) == 5 and job.payload["paid_call_inflight"] is False
    assert all(
        sum(estimate_tokens(message["content"]) for message in call["messages"]) <= 5632
        for call in calls
    )
    assert any("Section 0:" in call["messages"][-1]["content"] for call in calls)
    assert any("Section 1:" in call["messages"][-1]["content"] for call in calls)


async def test_given_exact_local_evidence_budget_when_preparing_chat_then_assembled_prompt_fits(
    resources,
):
    from uuid import UUID

    from app.integrations.llm import create_llm, estimate_tokens, validate_selection
    from app.schemas.ai import ChatInput
    from app.services import chat
    from app.services.retrieval import INSTRUCTIONS

    spec, _ = await local_fixture(resources)
    _, document_id, chat_id = await paper_fixture(resources)
    async with resources.sessions() as session, session.begin():
        await session.execute(delete(DocumentChunk).where(DocumentChunk.document_id == document_id))
        for index, size in enumerate((2474, 2475)):
            session.add(
                DocumentChunk(
                    id=UUID(int=index + 1),
                    document_id=document_id,
                    ordinal=index,
                    page=index + 1,
                    text="x" * size,
                    chunk_set="test",
                    page_end=index + 1,
                    context_text="x" * size,
                    token_count=size,
                )
            )
    body = ChatInput(model=spec.key, reasoning_effort="default", content="?", request_id=uuid4())
    _, prompt, chunks, _ = await chat.prepare(resources, chat_id, body)
    assert len(chunks) == 2
    assert estimate_tokens(INSTRUCTIONS + prompt) == 5632
    create_llm(resources, spec.key, selection=validate_selection(spec.key, "default")).parameters(
        spec.key, "default", INSTRUCTIONS, prompt
    )


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
                    chunk_set="test",
                    page_end=index + 1,
                    context_text=source,
                    token_count=20,
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
        "create_llm",
        lambda resources, model, **kwargs: HostedLLM(
            resources.settings,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(provider)),
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
        "create_llm",
        lambda resources, model, **kwargs: HostedLLM(
            resources.settings,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(provider)),
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
        "create_llm",
        lambda resources, model, **kwargs: HostedLLM(
            resources.settings,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(provider)),
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
                    chunk_set="test",
                    page_end=index + 1,
                    context_text=source,
                    token_count=1700,
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
        "create_llm",
        lambda resources, model, **kwargs: HostedLLM(
            resources.settings,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(provider)),
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
        "create_llm",
        lambda resources, model, **kwargs: HostedLLM(
            resources.settings, http_client=httpx.AsyncClient(transport=AwaitingTransport(provider))
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


async def test_given_completed_summary_when_weights_deleted_then_provenance_survives(
    resources, monkeypatch
):
    from contextlib import asynccontextmanager

    from app.models.jobs import BackgroundJob
    from app.models.local_models import ModelInstallation
    from app.services import summarization

    spec, requests = await local_fixture(resources)
    identifier, token, payload = await summary_job_fixture(resources, spec, 1)
    real_slots = summarization.generation_slots

    @asynccontextmanager
    async def delete_after_release(resources, model):
        async with real_slots(resources, model):
            yield
        # Deletion is permitted once admission ends, before final summary persistence.
        async with resources.sessions() as session, session.begin():
            row = await session.get(ModelInstallation, model, with_for_update=True)
            row.state, row.desired_state = "missing", "missing"
            row.weights_present, row.digest, row.validation = False, None, None

    monkeypatch.setattr(summarization, "generation_slots", delete_after_release)
    await summarization.run_summary_job(resources, identifier, 1, token, payload)
    async with resources.sessions() as session:
        job = await session.get(BackgroundJob, identifier)
        assert job.state == "completed", job.error_code
        summary = await session.get(PaperSummary, job.result["summary_id"])
        assert summary.configuration["artifact_digest"] == spec.expected_digest
        assert summary.configuration["runtime_version"] == "0.40.1-ara.fixture"
        snapshot = job.payload["_generation_configuration"]
        assert snapshot["artifact_digest"] == spec.expected_digest
        assert summary.configuration == {**snapshot, "covered_chunks": 1}
    assert len(requests) == 1


async def test_given_checkpointed_summary_when_effective_settings_change_then_no_mixed_generation(
    resources, monkeypatch
):
    from contextlib import asynccontextmanager

    from app.models.jobs import BackgroundJob
    from app.services import summarization

    spec, requests = await local_fixture(resources)
    identifier, token, payload = await summary_job_fixture(resources, spec, 2)
    real_slots = summarization.generation_slots

    @asynccontextmanager
    async def change_after_release(resources, model):
        async with real_slots(resources, model):
            yield
        resources.settings.ollama_num_threads = 2

    monkeypatch.setattr(summarization, "generation_slots", change_after_release)
    await summarization.run_summary_job(resources, identifier, 1, token, payload)
    async with resources.sessions() as session:
        job = await session.get(BackgroundJob, identifier)
        assert job.state == "failed"
        assert job.error_code == "MODEL_CONFIGURATION_CHANGED"
        assert job.payload["_generation_configuration"]["num_thread"] == 4
        assert job.payload["paid_call_inflight"] is False
    assert len(requests) == 1


async def test_given_legacy_summary_checkpoint_without_provenance_then_no_configuration_is_invented(
    resources,
):
    from app.models.jobs import BackgroundJob
    from app.services import summarization

    spec, requests = await local_fixture(resources)
    identifier, token, payload = await summary_job_fixture(resources, spec, 1)
    async with resources.sessions() as session, session.begin():
        chunk = await session.scalar(select(DocumentChunk))
        job = await session.get(BackgroundJob, identifier)
        job.payload = {**job.payload, "partials": [f"Supported result [source:{chunk.id}]"]}
    await summarization.run_summary_job(resources, identifier, 1, token, payload)
    async with resources.sessions() as session:
        job = await session.get(BackgroundJob, identifier)
        assert job.state == "failed"
        assert job.error_code == "GENERATION_PROVENANCE_UNKNOWN"
    assert requests == []
