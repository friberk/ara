"""Citation compatibility through real isolated persistence and mocked native HTTP."""

import asyncio
import json
import re
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select

from app.models.jobs import BackgroundJob
from app.models.research import ChatMessage, DocumentChunk, PaperSummary
from app.schemas.ai import ChatInput
from app.services import chat, summarization
from tests.test_ai_integration import local_fixture, paper_fixture, summary_job_fixture

pytestmark = pytest.mark.integration


async def generation_fixture(resources, output):
    requests = []

    def provider(request):
        body = json.loads(request.content)
        requests.append(body)
        answer = output(body)
        result = {
            "message": {"content": answer},
            "done": True,
            "done_reason": "stop",
            "prompt_eval_count": 100,
            "eval_count": 50,
        }
        if body["stream"]:
            rows = [{"message": {"content": character}, "done": False} for character in answer]
            rows.append({**result, "message": {"content": ""}})
            return httpx.Response(200, text="\n".join(json.dumps(row) for row in rows))
        return httpx.Response(200, json=result)

    await resources.ollama_generation_http.aclose()
    resources.ollama_generation_http = httpx.AsyncClient(transport=httpx.MockTransport(provider))
    return requests


async def chat_output(resources, assistant, prompt, chunks, replay=False):
    request = SimpleNamespace(is_disconnected=lambda: asyncio.sleep(0, result=False))
    return "".join(
        [
            frame
            async for frame in chat.stream_answer(
                resources, request, assistant, prompt, chunks, replay
            )
        ]
    )


async def test_given_unicode_cited_answer_when_streaming_then_completion_and_storage_are_canonical(
    resources,
):
    spec, _ = await local_fixture(resources)
    _, _, chat_id = await paper_fixture(resources)
    body = ChatInput(
        model=spec.key, reasoning_effort="default", content="What dataset?", request_id=uuid4()
    )
    assistant, prompt, chunks, _ = await chat.prepare(resources, chat_id, body)
    raw = f"The dataset contains twelve examples 【source:{chunks[0].id}】."
    canonical = f"The dataset contains twelve examples [source:{chunks[0].id}]."
    requests = await generation_fixture(resources, lambda body: raw)
    frames = await chat_output(resources, assistant, prompt, chunks)
    assert "message.failed" not in frames
    completed = next(
        frame for frame in frames.split("\n\n") if frame.startswith("event: message.completed")
    )
    assert json.loads(completed.split("\ndata: ", 1)[1])["content"] == canonical
    deltas = [
        json.loads(frame.split("\ndata: ", 1)[1])["text"]
        for frame in frames.split("\n\n")
        if frame.startswith("event: message.delta")
    ]
    assert "".join(deltas) == raw
    async with resources.sessions() as session:
        saved = await session.get(ChatMessage, assistant.id)
        assert saved.state == "completed" and saved.content == canonical
        assert [item["chunk_id"] for item in saved.citations] == [str(chunks[0].id)]
        assert saved.citations[0]["page"] == chunks[0].page
    assert len(requests) == 1


@pytest.mark.parametrize("bad_kind", ["unknown", "foreign", "malformed", "embedded_ascii"])
async def test_given_bad_unicode_marker_with_known_ascii_when_streaming_then_message_fails(
    resources,
    bad_kind,
):
    spec, _ = await local_fixture(resources)
    _, _, chat_id = await paper_fixture(resources)
    _, foreign_document, _ = await paper_fixture(resources)
    async with resources.sessions() as session:
        foreign = await session.scalar(
            select(DocumentChunk).where(DocumentChunk.document_id == foreign_document)
        )
        foreign_id = foreign.id
    body = ChatInput(
        model=spec.key, reasoning_effort="default", content="What dataset?", request_id=uuid4()
    )
    assistant, prompt, chunks, _ = await chat.prepare(resources, chat_id, body)
    bad = {
        "unknown": str(uuid4()),
        "foreign": str(foreign_id),
        "malformed": "not-a-uuid",
        "embedded_ascii": f"{chunks[0].id}]extra",
    }[bad_kind]
    raw = f"Known [source:{chunks[0].id}] and unsupported 【source:{bad}】."
    await generation_fixture(resources, lambda body: raw)
    frames = await chat_output(resources, assistant, prompt, chunks)
    assert "UNGROUNDED_OUTPUT" in frames and "message.completed" not in frames
    async with resources.sessions() as session:
        saved = await session.get(ChatMessage, assistant.id)
        assert saved.state == "failed" and saved.citations == []


async def test_given_old_failed_unicode_answer_when_replayed_then_failure_is_not_promoted(
    resources,
):
    spec, _ = await local_fixture(resources)
    _, _, chat_id = await paper_fixture(resources)
    body = ChatInput(
        model=spec.key, reasoning_effort="default", content="What dataset?", request_id=uuid4()
    )
    assistant, _, chunks, _ = await chat.prepare(resources, chat_id, body)
    raw = f"Twelve examples 【source:{chunks[0].id}】."
    await chat.save(resources, assistant.id, raw, state="failed")
    requests = await generation_fixture(
        resources, lambda body: pytest.fail("failed replay reached inference")
    )
    replay, prompt, selected, reused = await chat.prepare(resources, chat_id, body)
    assert reused and replay.id == assistant.id
    frames = await chat_output(resources, replay, prompt, selected, reused)
    assert "PREVIOUS_GENERATION_INTERRUPTED" in frames and "message.completed" not in frames
    async with resources.sessions() as session:
        saved = await session.get(ChatMessage, assistant.id)
        assert saved.state == "failed" and saved.content == raw and saved.citations == []
    assert requests == []


@pytest.mark.parametrize("map_size", [100, 2000])
async def test_given_unicode_summary_when_generating_then_checkpoints_and_final_are_canonical(
    resources,
    monkeypatch,
    map_size,
):
    spec, _ = await local_fixture(resources)
    identifier, token, payload = await summary_job_fixture(resources, spec, 2)
    snapshots = []
    real_checkpoint = summarization.checkpoint

    async def capture(resources, job_id, generation, token, payload, stage, progress):
        await real_checkpoint(resources, job_id, generation, token, payload, stage, progress)
        async with resources.sessions() as session:
            snapshots.append((await session.get(BackgroundJob, job_id)).payload)

    monkeypatch.setattr(summarization, "checkpoint", capture)

    def output(body):
        prompt = body["messages"][-1]["content"]
        identifiers = list(dict.fromkeys(re.findall(r"\[source:([0-9a-f-]{36})\]", prompt)))
        assert identifiers
        prefix = "Supported result " + " ".join(
            f"【source:{identifier}】" for identifier in identifiers
        )
        # Real tokens: 2,000-word sections exceed the reduction share and need compression.
        return prefix + " word" * map_size if prompt.startswith("Summarize") else prefix

    requests = await generation_fixture(resources, output)
    await summarization.run_summary_job(resources, identifier, 1, token, payload)
    async with resources.sessions() as session:
        job = await session.get(BackgroundJob, identifier)
        assert job.state == "completed", (job.error_code, job.error_message)
        summary = await session.get(PaperSummary, job.result["summary_id"])
        assert "【source:" not in summary.content and "[source:" in summary.content
        assert len(summary.citations) == 2
    assert len(requests) >= 3
    if map_size == 2000:
        assert any(body["messages"][-1]["content"].startswith("Compress") for body in requests)
    for snapshot in snapshots:
        contents = [
            *snapshot.get("partials", []),
            *snapshot.get("reduced", []),
            *snapshot.get("reduction_results", []),
        ]
        if snapshot.get("compression"):
            contents.append(snapshot["compression"]["candidate"])
        assert all("【source:" not in content and "[source:" in content for content in contents)


@pytest.mark.parametrize("phase", ["map", "reduction"])
@pytest.mark.parametrize("bad_kind", ["unknown", "foreign", "malformed"])
async def test_given_bad_unicode_summary_source_when_generating_then_no_bad_checkpoint_or_replay(
    resources,
    phase,
    bad_kind,
):
    spec, _ = await local_fixture(resources)
    identifier, token, payload = await summary_job_fixture(resources, spec, 2)
    _, foreign_document, _ = await paper_fixture(resources)
    async with resources.sessions() as session:
        foreign = await session.scalar(
            select(DocumentChunk).where(DocumentChunk.document_id == foreign_document)
        )
        foreign_id = foreign.id
    bad = {"unknown": str(uuid4()), "foreign": str(foreign_id), "malformed": "not-a-uuid"}[bad_kind]

    def output(body):
        prompt = body["messages"][-1]["content"]
        ids = list(dict.fromkeys(re.findall(r"\[source:([0-9a-f-]{36})\]", prompt)))
        valid = "Supported " + " ".join(f"[source:{id}]" for id in ids)
        is_bad = prompt.startswith("Summarize") if phase == "map" else prompt.startswith("Combine")
        return valid + f" unsupported 【source:{bad}】" if is_bad else valid

    requests = await generation_fixture(resources, output)
    await summarization.run_summary_job(resources, identifier, 1, token, payload)
    async with resources.sessions() as session:
        job = await session.get(BackgroundJob, identifier)
        assert job.state == "failed" and job.error_code == "UNGROUNDED_OUTPUT"
        assert not job.result
        assert not job.payload.get("reduction_results")
        assert len(job.payload.get("partials", [])) == (0 if phase == "map" else 2)
        original_payload = job.payload
    count = len(requests)
    await summarization.run_summary_job(resources, identifier, 1, token, payload)
    assert len(requests) == count
    async with resources.sessions() as session:
        failed = await session.get(BackgroundJob, identifier)
        assert failed.state == "failed" and failed.payload == original_payload


@pytest.mark.parametrize("cached_stage", ["partials", "reduced", "reduction_results"])
async def test_given_active_unicode_checkpoint_when_resuming_then_new_checkpoints_are_canonical(
    resources,
    monkeypatch,
    cached_stage,
):
    from app.integrations.llm import generation_configuration

    spec, _ = await local_fixture(resources)
    identifier, token, payload = await summary_job_fixture(resources, spec, 2)
    configuration = await generation_configuration(resources, spec.key, "default")
    async with resources.sessions() as session, session.begin():
        chunks = list(
            (
                await session.scalars(
                    select(DocumentChunk)
                    .where(DocumentChunk.document_id == payload["document_id"])
                    .order_by(DocumentChunk.ordinal)
                )
            ).all()
        )
        canonical = [f"Supported [source:{chunk.id}]" for chunk in chunks]
        unicode = [f"Supported 【source:{chunk.id}】" for chunk in chunks]
        job = await session.get(BackgroundJob, identifier)
        cache = {"partials": canonical, "_generation_configuration": configuration}
        cache[cached_stage] = (
            [" ".join(unicode)] if cached_stage == "reduction_results" else unicode
        )
        if cached_stage == "reduction_results":
            cache["reduced"] = canonical
        job.payload = {**job.payload, **cache}
    snapshots = []
    real_checkpoint = summarization.checkpoint

    async def capture(resources, job_id, generation, token, payload, stage, progress):
        await real_checkpoint(resources, job_id, generation, token, payload, stage, progress)
        async with resources.sessions() as session:
            snapshots.append((await session.get(BackgroundJob, job_id)).payload)

    monkeypatch.setattr(summarization, "checkpoint", capture)
    requests = await generation_fixture(resources, lambda body: " ".join(unicode))
    await summarization.run_summary_job(resources, identifier, 1, token, payload)
    async with resources.sessions() as session:
        job = await session.get(BackgroundJob, identifier)
        assert job.state == "completed", (job.error_code, job.error_message)
        summary = await session.get(PaperSummary, job.result["summary_id"])
        assert "【source:" not in summary.content and len(summary.citations) == 2
    assert snapshots
    assert all(
        "【source:" not in content
        for snapshot in snapshots
        for key in ("partials", "reduced", "reduction_results")
        for content in snapshot.get(key, [])
    )
    assert all("【source:" not in body["messages"][-1]["content"] for body in requests)
    assert len(requests) == (0 if cached_stage == "reduction_results" else 1)


async def test_given_unknown_unicode_cached_source_when_resuming_then_no_new_generation(
    resources,
):
    from app.integrations.llm import generation_configuration

    spec, _ = await local_fixture(resources)
    identifier, token, payload = await summary_job_fixture(resources, spec, 2)
    configuration = await generation_configuration(resources, spec.key, "default")
    async with resources.sessions() as session, session.begin():
        chunks = list(
            (
                await session.scalars(
                    select(DocumentChunk)
                    .where(DocumentChunk.document_id == payload["document_id"])
                    .order_by(DocumentChunk.ordinal)
                )
            ).all()
        )
        job = await session.get(BackgroundJob, identifier)
        job.payload = {
            **job.payload,
            "_generation_configuration": configuration,
            "partials": [
                f"Known [source:{chunk.id}] unknown 【source:{uuid4()}】" for chunk in chunks
            ],
        }
    requests = await generation_fixture(
        resources, lambda body: f"Supported [source:{chunks[0].id}]"
    )
    await summarization.run_summary_job(resources, identifier, 1, token, payload)
    async with resources.sessions() as session:
        job = await session.get(BackgroundJob, identifier)
        assert job.state == "failed" and job.error_code == "UNGROUNDED_OUTPUT"
    assert requests == []
