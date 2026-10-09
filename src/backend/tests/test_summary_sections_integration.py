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


HEADINGS = ("1 Introduction", "2 Method", "3 Results")
PARTS = [f"{heading} part {part}" for heading in HEADINGS for part in range(3)]


async def local_sections_job(resources):
    """A local summary job over three sections of three passages each."""
    from tests.support.evidence import seed_structured
    from tests.test_ai_integration import local_fixture

    spec, requests = await local_fixture(resources)
    # About 650 counted tokens per passage: a section fits the local budget, two sections do
    # not, and four passages would.
    sections = [
        (heading, "text", page, page, f"{heading} part {part}: " + " word" * 600)
        for page, heading in enumerate(HEADINGS, start=1)
        for part in range(3)
    ]
    paper_id, document_id, _ = await seed_structured(
        resources, sections=sections, profile=None, index_state=None
    )
    job = await summary_job(resources, paper_id, document_id, spec.key, "default")
    return spec, requests, job


async def test_given_sections_when_summarizing_locally_then_batches_keep_whole_sections_in_budget(
    resources,
):
    from tests.test_ai_integration import within_local_budget

    spec, requests, (identifier, token, payload) = await local_sections_job(resources)
    await summarization.run_summary_job(resources, identifier, 1, token, payload)
    summary, _ = await finished_summary(resources, identifier)
    prompts = [body["messages"][-1]["content"] for body in requests]
    parts = [f"{part}:" for part in PARTS]
    assert [
        [part for part in parts if part in prompt]
        for prompt in prompts
        if prompt.startswith("Summarize")
    ] == [parts[0:3], parts[3:6], parts[6:9]]
    assert within_local_budget(resources, spec, requests)
    assert len(summary.citations) == 9


async def test_given_section_summaries_when_reducing_then_prompt_shows_handles_not_uuids(
    resources,
):
    from tests.test_ai_integration import within_local_budget

    spec, requests, (identifier, token, payload) = await local_sections_job(resources)
    await summarization.run_summary_job(resources, identifier, 1, token, payload)
    summary, _ = await finished_summary(resources, identifier)
    prompts = [body["messages"][-1]["content"] for body in requests]
    (reduction,) = [prompt for prompt in prompts if prompt.startswith("Combine")]
    # Each map batch cited its passages; the reduction shows them by document-wide handle.
    assert re.findall(r"\[S\d+\]", reduction) == [f"[S{n}]" for n in range(1, 10)]
    assert "source:" not in reduction
    assert within_local_budget(resources, spec, requests)
    assert len(summary.citations) == 9


async def test_given_restart_before_reduction_when_resumed_then_handles_name_the_same_passages(
    resources, monkeypatch
):
    from contextlib import asynccontextmanager

    from app.integrations.llm import LLMError

    _, requests, (identifier, token, payload) = await local_sections_job(resources)
    real_slots = summarization.generation_slots
    admissions = 0

    @asynccontextmanager
    async def busy_reduction(resources, model):
        nonlocal admissions
        admissions += 1
        # Three map batches are admitted; the runtime is busy when the reduction starts.
        if admissions == 4:
            raise LLMError("LOCAL_MODEL_BUSY", "Busy", 429)
        async with real_slots(resources, model):
            yield

    monkeypatch.setattr(summarization, "generation_slots", busy_reduction)
    with pytest.raises(LLMError):
        await summarization.run_summary_job(resources, identifier, 1, token, payload)
    async with resources.sessions() as session:
        partials = (await session.get(BackgroundJob, identifier)).payload["partials"]
    # Checkpoints store canonical sources, never handle numbers.
    assert len(partials) == 3 and re.search(r"\[S\d+\]", " ".join(partials)) is None
    # A restarted worker rebuilds the handles from the database alone.
    await summarization.run_summary_job(resources, identifier, 1, token, payload)
    summary, chunks = await finished_summary(resources, identifier)
    prompts = [body["messages"][-1]["content"] for body in requests]
    maps = "\n".join(prompt for prompt in prompts if prompt.startswith("Summarize"))
    labelled = dict(re.findall(r"^\[(S\d+)\] .*\n(.+?):", maps, re.M))
    (reduction,) = [prompt for prompt in prompts if prompt.startswith("Combine")]
    resumed = [labelled[handle] for handle in re.findall(r"\[(S\d+)\]", reduction)]
    stored = [chunks[UUID(i)].text.split(":")[0] for i in SOURCE.findall(summary.content)]
    assert resumed == stored == PARTS
    assert len(prompts) == 4


# Two 2,100-token passages, [S1] and [S2], each in its own map batch: [S2] belongs to the
# other map batch, and [S3] names no passage of the paper.
@pytest.mark.parametrize(("phase", "handle"), [("map", "[S2]"), ("reduction", "[S3]")])
async def test_given_unsupplied_handle_when_summarizing_then_ungrounded_and_nothing_checkpointed(
    resources, phase, handle
):
    from tests.test_ai_integration import local_fixture, summary_job_fixture
    from tests.test_citation_markers_integration import generation_fixture

    spec, _ = await local_fixture(resources)
    identifier, token, payload = await summary_job_fixture(resources, spec, 2)

    def output(body):
        prompt = body["messages"][-1]["content"]
        valid = "Supported " + cited_markers(prompt)
        bad = prompt.startswith("Summarize" if phase == "map" else "Combine")
        return f"{valid} and {handle}" if bad else valid

    requests = await generation_fixture(resources, output)
    await summarization.run_summary_job(resources, identifier, 1, token, payload)
    async with resources.sessions() as session:
        job = await session.get(BackgroundJob, identifier)
        assert job.state == "failed" and job.error_code == "UNGROUNDED_OUTPUT"
        assert not job.result and not job.payload.get("reduction_results")
        assert len(job.payload.get("partials", [])) == (0 if phase == "map" else 2)
    count = len(requests)
    await summarization.run_summary_job(resources, identifier, 1, token, payload)
    assert len(requests) == count


async def test_given_reduction_citing_a_real_handle_it_was_not_shown_then_ungrounded(resources):
    from tests.test_ai_integration import local_fixture, summary_job_fixture
    from tests.test_citation_markers_integration import generation_fixture

    spec, _ = await local_fixture(resources)
    identifier, token, payload = await summary_job_fixture(resources, spec, 3)

    def output(body):
        prompt = body["messages"][-1]["content"]
        if prompt.startswith("Summarize"):
            # About 1,160 counted tokens per section: two share a reduction, three do not.
            return "Supported " + cited_markers(prompt) + " word" * 1100
        # A short handle is easy to guess: [S3] is a real passage this reduction never saw.
        return "Supported " + cited_markers(prompt) + ("" if "[S3]" in prompt else " and [S3]")

    requests = await generation_fixture(resources, output)
    await summarization.run_summary_job(resources, identifier, 1, token, payload)
    reduction = requests[3]["messages"][-1]["content"]
    assert reduction.startswith("Combine") and re.findall(r"\[S\d+\]", reduction) == [
        "[S1]",
        "[S2]",
    ]
    async with resources.sessions() as session:
        job = await session.get(BackgroundJob, identifier)
        assert job.state == "failed" and job.error_code == "UNGROUNDED_OUTPUT"
        assert len(job.payload["partials"]) == 3 and not job.payload.get("reduction_results")
