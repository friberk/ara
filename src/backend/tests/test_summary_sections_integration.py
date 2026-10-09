"""Paper summaries over structured chunks with short passage handles (ARA-073)."""

import json
import re
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import select

from app.models.jobs import BackgroundJob
from app.models.research import DocumentChunk, PaperSummary
from app.repositories.jobs import claim, enqueue
from app.services import summarization
from tests.test_ai_integration import cited_markers

pytestmark = pytest.mark.integration

SOURCE = re.compile(r"\[source:([0-9a-f-]{36})\]")


async def summary_job(resources, paper_id, document_id, model, effort):
    payload = {
        "paper_id": str(paper_id),
        "document_id": str(document_id),
        "model": model,
        "reasoning_effort": effort,
        "request_id": str(uuid4()),
    }
    async with resources.sessions() as session, session.begin():
        job = await enqueue(session, kind="summary", payload=payload)
        identifier = job.id
    token = await claim(resources.sessions, identifier, 1)
    return identifier, token, payload


def hosted_fixture(resources, monkeypatch):
    """A hosted model that cites every passage handle (or source marker) in its prompt."""
    from pydantic import SecretStr

    from app.integrations.llm import HostedLLM
    from tests.test_ai import response_payload

    prompts = []

    def provider(request):
        prompt = json.loads(request.content)["input"]
        prompts.append(prompt)
        return httpx.Response(200, json=response_payload("Summary: " + cited_markers(prompt)))

    resources.settings.openai_api_key = SecretStr("fixture")
    monkeypatch.setattr(
        summarization,
        "create_llm",
        lambda resources, model, **kwargs: HostedLLM(
            resources.settings,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(provider)),
        ),
    )
    return prompts


async def finished_summary(resources, identifier):
    async with resources.sessions() as session:
        job = await session.get(BackgroundJob, identifier)
        assert job.state == "completed", (job.error_code, job.error_message)
        summary = await session.get(PaperSummary, job.result["summary_id"])
        chunks = (
            await session.scalars(
                select(DocumentChunk).where(DocumentChunk.document_id == summary.document_id)
            )
        ).all()
    return summary, {chunk.id: chunk for chunk in chunks}


async def test_given_structured_paper_when_summarized_then_sections_are_cited_canonically(
    resources, monkeypatch, tmp_path
):
    from tests.test_ingestion_chunks_integration import client_for, ingest, upload

    async with client_for(resources) as client:
        references, ingest_payload = await upload(client, resources, tmp_path)
    await ingest(resources, UUID(references["job_id"]), 1, ingest_payload)
    prompts = hosted_fixture(resources, monkeypatch)
    identifier, token, payload = await summary_job(
        resources, references["paper_id"], references["document_id"], "gpt-5.6-luna", "low"
    )
    await summarization.run_summary_job(resources, identifier, 1, token, payload)
    summary, chunks = await finished_summary(resources, identifier)
    # The model saw short handles, never chunk UUIDs.
    assert re.search(r"^\[S1\] ", prompts[0], re.M) and "[source:" not in prompts[0]
    cited = [UUID(identifier) for identifier in SOURCE.findall(summary.content)]
    assert cited and set(cited) <= set(chunks)
    assert re.search(r"\[S\d+\]", summary.content) is None
    sections = {chunks[chunk_id].heading for chunk_id in cited}
    assert len(sections) >= 2
    titles = {item["section"].rsplit(" > ", 1)[-1] for item in summary.citations}
    assert {"1 Introduction", "2 Method", "3 Results"} <= titles
