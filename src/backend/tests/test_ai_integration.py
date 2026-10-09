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
from tests.support.answers import CONNECTED

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
            # Cite the passages a prompt lists, else the handles a summary reduction carries.
            markers = (
                re.findall(r"^(\[S\d+\]) ", prompt, re.M)
                or re.findall(r"\[S\d+\]", prompt)
                or re.findall(r"\[source:[\w-]+\]", prompt)
            )
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


def within_local_budget(resources, spec, requests):
    from app.integrations.context_registry import context_profile
    from app.integrations.tokens import PromptMessage, count_messages

    profile = context_profile(resources, spec.key, "default")
    return all(
        count_messages(
            profile.counter, [PromptMessage(m["role"], m["content"]) for m in body["messages"]]
        )
        <= profile.input_budget
        for body in requests
    )


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
    prepared = await chat.prepare(resources, chat_id, body)
    output = "".join([item async for item in chat.stream_answer(resources, CONNECTED, prepared)])
    assert "message.completed" in output
    assert within_local_budget(resources, spec, requests)
    async with resources.sessions() as session:
        saved = await session.get(ChatMessage, prepared.assistant.id)
        assert (
            saved.configuration["provider"] == "ollama"
            and saved.configuration["artifact_digest"] == spec.expected_digest
        )
        assert saved.configuration["runtime_version"] == "0.40.1-ara.fixture"
        assert saved.configuration["temperature"] == 0.0
        assert {
            key: saved.configuration[key]
            for key in (
                "window",
                "max_output",
                "thinking_allowance",
                "input_budget",
                "tokenizer",
                "token_factor",
            )
        } == {
            "window": 8192,
            "max_output": 2048,
            "thinking_allowance": 0,
            "input_budget": 3072,
            "tokenizer": "o200k_base",
            "token_factor": 1.05,
        }
        assert saved.citations and all(
            c["document_id"] == str(document_id) for c in saved.citations
        )
        assert await session.scalar(select(func.count()).select_from(GenerationReservation)) == 0
    assert (await chat.prepare(resources, chat_id, body)).replay and len(requests) == 1


async def test_given_local_full_paper_when_summarizing_then_every_section_is_reduced_under_context(
    resources,
):
    from app.models.jobs import BackgroundJob
    from app.services import summarization

    spec, requests = await local_fixture(resources)
    paper_id, document_id, _ = await paper_fixture(resources)
    async with resources.sessions() as session, session.begin():
        await session.execute(delete(DocumentChunk).where(DocumentChunk.document_id == document_id))
        for index in range(12):
            # About 1,000 tokens each: real tokens, not bytes, decide the map batches.
            text = f"Section {index}: " + "evidence " * 1000
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
    assert within_local_budget(resources, spec, requests)


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
            # About 2,100 tokens: each section needs its own map batch under the 3,072 budget.
            text = f"Section {index}: " + " word" * 2000
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


def cited_markers(prompt: str) -> str:
    """A fixture summary cites every handle it was shown, else the source markers."""
    import re

    handles = re.findall(r"\[S\d+\]", prompt)
    return " ".join(dict.fromkeys(handles or re.findall(r"\[source:[0-9a-f-]+\]", prompt)))


@pytest.mark.parametrize("busy_kind", ["slot", "http"])
async def test_given_completed_reduction_when_later_group_busy_then_resume_skips_completed_group(
    resources,
    monkeypatch,
    busy_kind,
):
    import json
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
        markers = cited_markers(prompt)
        # About 1,200 tokens: two outputs share a reduction batch, three do not.
        content = markers + " word" * 1100
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

    from app.models.jobs import BackgroundJob
    from app.services import summarization

    spec, _ = await local_fixture(resources)
    identifier, token, payload = await summary_job_fixture(resources, spec, 2)
    calls = []

    def provider(request):
        body = json.loads(request.content)
        calls.append(body)
        prompt = body["messages"][-1]["content"]
        markers = cited_markers(prompt)
        # 2,000-word outputs cannot pair in a reduction; 500-word compressions can.
        words = 500 if prompt.startswith("Compress") and compression == "short" else 2000
        content = markers + " word" * words
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
    assert within_local_budget(resources, spec, calls)
    assert any("Section 0:" in call["messages"][-1]["content"] for call in calls)
    assert any("Section 1:" in call["messages"][-1]["content"] for call in calls)


PROSE = (
    "Retrieval-augmented generation grounds each answer in passages selected from the paper. "
    "The retriever ranks passages by relevance, and the generator cites them while writing. "
) * 6


async def replace_chunks(resources, document_id, texts):
    from uuid import UUID

    async with resources.sessions() as session, session.begin():
        await session.execute(delete(DocumentChunk).where(DocumentChunk.document_id == document_id))
        for index, text in enumerate(texts):
            session.add(
                DocumentChunk(
                    id=UUID(int=index + 1),
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


def sent_handles(request) -> list[str]:
    import re

    return re.findall(r"^\[(S\d+)\] ", request["messages"][-1]["content"], re.M)


async def test_given_prose_evidence_when_answering_locally_then_tokens_fit_more_than_bytes(
    resources,
):
    from app.integrations.context_registry import context_profile
    from tests.support.answers import ask, named

    spec, requests = await local_fixture(resources)
    _, document_id, chat_id = await paper_fixture(resources)
    await replace_chunks(resources, document_id, [f"Passage {i}: {PROSE}" for i in range(10)])
    _, events = await ask(
        resources,
        chat_id,
        "How does retrieval ground answers?",
        model=spec.key,
        reasoning_effort="default",
    )
    assert named(events, "message.completed")
    profile = context_profile(resources, spec.key, "default")
    assert len(sent_handles(requests[0])) == 10
    # Byte counting could never fit these passages in the 3,072-token local budget.
    assert len(requests[0]["messages"][-1]["content"].encode()) > profile.input_budget
    assert within_local_budget(resources, spec, requests)


async def test_given_more_evidence_than_local_budget_when_answering_then_request_still_fits(
    resources,
):
    from tests.support.answers import ask, named

    spec, requests = await local_fixture(resources)
    _, document_id, chat_id = await paper_fixture(resources)
    await replace_chunks(resources, document_id, [f"Passage {i}: {PROSE}" for i in range(30)])
    _, events = await ask(
        resources,
        chat_id,
        "How does retrieval ground answers?",
        model=spec.key,
        reasoning_effort="default",
    )
    (completed,) = named(events, "message.completed")
    retrieval = completed["retrieval"]
    assert retrieval["limited_by_context"] is True
    assert retrieval["passages_found"] == 30 > retrieval["passages_used"] >= 10
    assert len(sent_handles(requests[0])) == retrieval["passages_used"]
    assert within_local_budget(resources, spec, requests)
    assert completed["context"]["input_tokens"] <= 3072


@pytest.mark.parametrize(("words", "whole"), [(2000, True), (12000, False)])
async def test_given_local_metadata_evidence_when_extracting_then_real_tokens_bound_it(
    resources, words, whole
):
    import json

    from app.integrations.context_registry import context_profile
    from app.integrations.llm import extract_metadata
    from app.integrations.tokens import PromptMessage, count_messages
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
        result = {"title": None, "authors": None, "year": None, "abstract": None, "doi": None}
        return httpx.Response(
            200,
            json={"message": {"content": json.dumps(result)}, "done": True, "done_reason": "stop"},
        )

    await resources.ollama_generation_http.aclose()
    resources.ollama_generation_http = httpx.AsyncClient(transport=httpx.MockTransport(provider))
    evidence = "Traceable Research\nAda Example\n2024\n" + " word" * words
    await extract_metadata(resources, evidence)
    sent = requests[0]["messages"]
    # 2,000 words are about 10 KB: byte counting cut them near 2.8 KB.
    assert (sent[-1]["content"] == evidence) is whole
    assert evidence.startswith(sent[-1]["content"])
    profile = context_profile(resources, spec.key, "default")
    messages = [PromptMessage(m["role"], m["content"]) for m in sent]
    assert count_messages(profile.counter, messages) <= profile.input_budget


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
            chunk_set="test",
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
    from app.integrations.tokens import TiktokenCounter
    from app.rag.pipeline import retrieve_evidence

    _, first, _ = await paper_fixture(resources)
    _, second, _ = await paper_fixture(resources)

    async def passages(question):
        result = await retrieve_evidence(
            resources,
            document_id=first,
            chunk_set="test",
            preferred_profile="openai-3-large",
            queries=[question],
            question=question,
            budget=4000,
            counter=TiktokenCounter(),
        )
        return result.passages

    found = await passages("blue accuracy")
    assert found and {item.document_id for item in found} == {first}
    assert any("87 percent" in item.text for item in found)
    fallback = await passages("nonexistentterm")
    assert {item.page for item in fallback} == {1, 2, 3}
    assert second not in {item.document_id for item in fallback}


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
    first = await prepare(resources, chat_id, body)
    assert first.replay is False
    await save(resources, first.assistant.id, "partial evidence")
    async with resources.sessions() as session, session.begin():
        message = await session.get(ChatMessage, first.assistant.id)
        message.lease_expires_at = now() - timedelta(seconds=1)
        before = await session.scalar(select(func.count(GenerationReservation.id)))
    again = await prepare(resources, chat_id, body)
    stored = again.assistant
    assert again.replay and stored.id == first.assistant.id
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
    from app.schemas.ai import ChatInput
    from app.services import chat
    from tests.support.answers import first_handle, use_hosted

    _, document_id, chat_id = await paper_fixture(resources)
    calls = []
    use_hosted(
        monkeypatch,
        resources,
        calls,
        lambda body: f"The paper supplies evidence [{first_handle(body)}].",
    )
    body = ChatInput(content="What accuracy?", request_id=uuid4())
    prepared = await chat.prepare(resources, chat_id, body)
    frames = chat.stream_answer(resources, CONNECTED, prepared)
    assert "message.started" in await anext(frames)
    async with resources.sessions() as session:
        stored = await session.get(ChatMessage, prepared.assistant.id)
        assert stored.state == "processing" and stored.content == ""
    frame = await anext(frames)
    while "message.status" in frame:
        frame = await anext(frames)
    assert "message.delta" in frame
    async with resources.sessions() as session:
        stored = await session.get(ChatMessage, prepared.assistant.id)
        assert stored.state == "processing"
    completed = await anext(frames)
    assert "message.completed" in completed
    async with resources.sessions() as session:
        stored = await session.get(ChatMessage, prepared.assistant.id)
        assert stored.state == "completed"
        assert stored.citations[0]["document_id"] == str(document_id)
    await frames.aclose()
    existing = await chat.prepare(resources, chat_id, body)
    assert existing.replay and existing.assistant.id == prepared.assistant.id
    replayed = "".join(
        [frame async for frame in chat.stream_answer(resources, CONNECTED, existing)]
    )
    assert "message.completed" in replayed and len(calls) == 1


async def test_given_summary_fixture_when_generated_then_domain_and_job_complete_together(
    resources, monkeypatch
):
    import json

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
        content = "Supported full paper summary: " + cited_markers(prompt)
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
    body = ChatInput(content="What accuracy?", request_id=uuid4())
    prepared = await chat.prepare(resources, chat_id, body)
    stream = chat.stream_answer(resources, CONNECTED, prepared)
    frame = await anext(stream)
    while "message.delta" not in frame:
        frame = await anext(stream)
    assert "Visible partial answer" in frame
    await stream.aclose()
    async with resources.sessions() as session:
        stored = await session.get(ChatMessage, prepared.assistant.id)
        assert stored.state == "interrupted" and stored.content == "Visible partial answer"
    again = await chat.prepare(resources, chat_id, body)
    frames = "".join([frame async for frame in chat.stream_answer(resources, CONNECTED, again)])
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
    body = ChatInput(content="What accuracy?", request_id=uuid4())
    prepared = await chat.prepare(resources, chat_id, body)
    frames = "".join([frame async for frame in chat.stream_answer(resources, CONNECTED, prepared)])
    assert "UNGROUNDED_OUTPUT" in frames and "message.completed" not in frames
    async with resources.sessions() as session:
        stored = await session.get(ChatMessage, prepared.assistant.id)
        assert stored.state == "failed" and stored.citations == []


async def test_given_over_budget_document_when_summarized_then_map_reduce_covers_all_chunks(
    resources, monkeypatch
):
    import json

    from pydantic import SecretStr

    from app.integrations.llm import HostedLLM
    from app.models.jobs import BackgroundJob
    from app.services import summarization
    from tests.test_ai import response_payload

    paper_id, document_id, _ = await paper_fixture(resources)
    resources.settings.openai_api_key = SecretStr("fixture")
    async with resources.sessions() as session, session.begin():
        for index in range(3, 15):
            source = f"Section {index}: full-coverage evidence. " * 800
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
        answer = "Complete covered sections: " + cited_markers(prompt)
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
    body = ChatInput(content="What accuracy?", request_id=uuid4())
    prepared = await chat.prepare(resources, chat_id, body)
    response = StreamingResponse(chat.stream_answer(resources, CONNECTED, prepared))

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
        stored = await session.get(ChatMessage, prepared.assistant.id)
        assert stored.state == "interrupted" and stored.content == output
    existing = await chat.prepare(resources, chat_id, body)
    assert existing.replay and existing.assistant.id == prepared.assistant.id
    assert existing.assistant.state == "interrupted" and len(calls) == 1


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
