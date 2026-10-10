"""Section summaries: generated once per top-level section, cited, costed and embedded (ARA-079).

They are written like the automatic paper summary (ARA-084): the saved default model and effort,
a durable job, no other model, and nothing at all when that model cannot run.
"""

import json
import re
from uuid import UUID

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import func, select

from app.models.jobs import BackgroundJob
from app.models.research import Document, ModelConfiguration
from app.models.retrieval import SectionSummary, SectionSummaryEmbedding
from app.repositories.jobs import claim
from tests.support.papers import use_library_profile
from tests.support.providers import openai_fixture
from tests.support.sections import seed_sections
from tests.test_ai import response_payload

pytestmark = pytest.mark.integration

PASSAGE = re.compile(r"^\[(S\d+)\] ", re.M)
SMALL = "openai-3-small"


async def save_defaults(resources, model="gpt-5.6-terra", effort="high"):
    async with resources.sessions() as session, session.begin():
        await session.merge(
            ModelConfiguration(
                key="defaults", value={"default_model": model, "reasoning_effort": effort}
            )
        )


def hosted(resources):
    resources.settings.openai_api_key = SecretStr("fixture-key")


async def section_jobs(resources) -> list[BackgroundJob]:
    async with resources.sessions() as session:
        return list(
            (
                await session.scalars(
                    select(BackgroundJob)
                    .where(BackgroundJob.kind == "section_summaries")
                    .order_by(BackgroundJob.created_at)
                )
            ).all()
        )


async def queue(resources, document_id):
    from app.services.section_summaries import queue_section_summaries

    async with resources.sessions() as session, session.begin():
        document = await session.get(Document, document_id)
        return await queue_section_summaries(session, resources, document)


@pytest.fixture
def model(resources, monkeypatch):
    """The section summarizer's hosted calls; `answer(body)` returns the text."""
    from app.integrations.llm import HostedLLM
    from app.services import section_summaries

    calls, answers = [], []

    def provider(request):
        body = json.loads(request.content)
        calls.append(body)
        return httpx.Response(200, json=response_payload(answers[0](body)))

    monkeypatch.setattr(
        section_summaries,
        "create_llm",
        lambda resources, model, **kwargs: HostedLLM(
            resources.settings,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(provider)),
        ),
    )

    def script(answer):
        answers[:] = [answer]
        return calls

    return script


@pytest.fixture
def embeddings(resources, monkeypatch):
    from app.integrations import embeddings
    from app.services import section_summaries

    calls = []
    monkeypatch.setattr(
        section_summaries,
        "create_embedder",
        lambda resources, profile: embeddings.create_embedder(
            resources, profile, transport=openai_fixture(calls)
        ),
    )
    return calls


def cite_first_two(body) -> str:
    handles = PASSAGE.findall(body["input"][-1]["content"])[:2]
    return "The section reports its findings " + "".join(f"[{h}]" for h in handles) + "."


async def run(resources, job):
    from app.services.section_summaries import run_section_summaries_job

    token = await claim(resources.sessions, job.id, job.generation)
    assert token is not None
    await run_section_summaries_job(resources, job.id, job.generation, token, dict(job.payload))
    async with resources.sessions() as session:
        return await session.get(BackgroundJob, job.id)


async def test_given_sections_when_choosing_then_only_top_level_body_sections_with_room_qualify(
    resources,
):
    from app.services.section_summaries import load_eligible

    _, document_id, chunks = await seed_sections(resources)
    async with resources.sessions() as session:
        document = await session.get(Document, document_id)
        eligible = await load_eligible(session, document)
    # The abstract is already a summary, the introduction is one passage, references are not
    # content, and 2.1 belongs to 2 Method.
    assert [item.section.title for item in eligible] == ["2 Method", "3 Limitations"]
    method, limitations = eligible
    assert [chunk.id for chunk in method.chunks] == [
        *chunks[("2 Method",)],
        *chunks[("2 Method", "2.1 Dense baseline")],
    ]
    assert [chunk.id for chunk in limitations.chunks] == chunks[("3 Limitations",)]


async def test_given_a_ready_pdf_when_queueing_then_one_job_uses_the_saved_defaults_once(
    resources,
):
    hosted(resources)
    await save_defaults(resources)
    paper_id, document_id, _ = await seed_sections(resources)
    job = await queue(resources, document_id)
    assert job is not None and job.kind == "section_summaries"
    assert job.payload["model"] == "gpt-5.6-terra"
    assert job.payload["reasoning_effort"] == "high"
    assert job.payload["document_id"] == str(document_id)
    assert job.payload["paper_id"] == str(paper_id)
    # Queueing again, as a duplicate delivery or a restart would, adds nothing.
    assert await queue(resources, document_id) is None
    assert len(await section_jobs(resources)) == 1


@pytest.mark.parametrize("setup", ["no-key", "local-default", "not-active"])
async def test_given_a_default_that_cannot_run_when_queueing_then_nothing_starts(resources, setup):
    if setup != "no-key":
        hosted(resources)
    if setup == "local-default":
        # Open models are off, so a saved local default never falls back to a paid model.
        await save_defaults(resources, "ifm-k2-horizon-7b", "default")
    _, document_id, _ = await seed_sections(resources, active=setup != "not-active")
    assert await queue(resources, document_id) is None
    assert await section_jobs(resources) == []


async def test_given_the_job_when_it_runs_then_each_section_is_summarized_cited_and_embedded(
    resources, model, embeddings
):
    from app.services.costs import call_cost

    hosted(resources)
    await save_defaults(resources, "gpt-5.6-luna", "low")
    await use_library_profile(resources, SMALL)
    _, document_id, chunks = await seed_sections(resources)
    calls = model(cite_first_two)
    job = await run(resources, await queue(resources, document_id))

    assert job.state == "completed", (job.error_code, job.error_message)
    assert len(calls) == 2
    assert all(body["model"] == "gpt-5.6-luna" for body in calls)
    async with resources.sessions() as session:
        rows = (
            await session.scalars(select(SectionSummary).order_by(SectionSummary.ordinal))
        ).all()
        vectors = await session.scalar(
            select(func.count())
            .select_from(SectionSummaryEmbedding)
            .where(SectionSummaryEmbedding.profile == SMALL)
        )
    assert [row.title for row in rows] == ["2 Method", "3 Limitations"]
    method_chunks = {*chunks[("2 Method",)], *chunks[("2 Method", "2.1 Dense baseline")]}
    for row, own in zip(rows, (method_chunks, set(chunks[("3 Limitations",)])), strict=True):
        cited = {UUID(item) for item in re.findall(r"\[source:([^\]]+)\]", row.content)}
        # Every citation is one of the section's own chunks, as validated when it was written.
        assert cited and cited <= own and {UUID(item) for item in row.sources} == cited
        assert row.model == "gpt-5.6-luna" and row.reasoning_effort == "low"
        assert row.usage["input_tokens"] == 20 and row.usage["output_tokens"] == 5
    assert (rows[0].page, rows[0].page_end) == (2, 3)
    # Cost is recorded: per summary in its usage, and for the job as a whole.
    usage = {"input_tokens": 40, "output_tokens": 10}
    assert job.result["sections"] == 2
    assert job.result["usage"]["input_tokens"] == 40
    assert job.result["cost_usd"] == str(call_cost("gpt-5.6-luna", usage))
    # Embedded with the library-wide model, beside the chunks.
    assert vectors == 2 and job.result["embedding"]["profile"] == SMALL
    assert [call["model"] for call in embeddings] == ["text-embedding-3-small"]


async def test_given_a_section_summary_without_valid_citations_when_running_then_it_is_skipped(
    resources, model, embeddings
):
    hosted(resources)
    await save_defaults(resources, "gpt-5.6-luna", "low")
    _, document_id, _ = await seed_sections(resources)

    def answer(body):
        prompt = body["input"][-1]["content"]
        if "3 Limitations" in prompt:
            return "The section lists limitations [S9]."
        return cite_first_two(body)

    model(answer)
    job = await run(resources, await queue(resources, document_id))
    assert job.state == "completed"
    async with resources.sessions() as session:
        titles = (await session.scalars(select(SectionSummary.title))).all()
    assert titles == ["2 Method"]
    assert len(job.result["skipped"]) == 1


async def test_given_an_uncertain_paid_call_when_the_job_resumes_then_it_is_never_resent(
    resources, model
):
    from app.repositories.jobs import now

    hosted(resources)
    await save_defaults(resources, "gpt-5.6-luna", "low")
    _, document_id, _ = await seed_sections(resources)
    job = await queue(resources, document_id)
    async with resources.sessions() as session, session.begin():
        row = await session.get(BackgroundJob, job.id)
        row.payload = {**row.payload, "paid_call_inflight": True}
        row.updated_at = now()
    calls = model(cite_first_two)
    async with resources.sessions() as session:
        job = await session.get(BackgroundJob, job.id)
    settled = await run(resources, job)
    assert calls == []
    assert (settled.state, settled.error_code) == ("failed", "GENERATION_OUTCOME_UNKNOWN")


async def test_given_existing_ready_pdfs_when_backfilling_then_each_is_queued_once(resources):
    from app.rag.chunking import CHUNK_SET
    from app.services.section_summaries import backfill_section_summaries

    hosted(resources)
    await save_defaults(resources, "gpt-5.6-luna", "low")
    _, first, _ = await seed_sections(resources, chunk_set=CHUNK_SET)
    _, second, _ = await seed_sections(resources, title="Dense Retrieval", chunk_set=CHUNK_SET)
    # Not the paper's PDF any more, or waiting to be read again with the current chunker.
    await seed_sections(resources, title="Old copy", active=False, chunk_set=CHUNK_SET)
    await seed_sections(resources, title="Outdated reading")
    assert await backfill_section_summaries(resources) == 2
    assert await backfill_section_summaries(resources) == 0
    jobs = await section_jobs(resources)
    assert sorted(job.payload["document_id"] for job in jobs) == sorted([str(first), str(second)])


async def test_given_no_key_when_backfilling_then_nothing_is_queued_until_one_arrives(resources):
    from app.rag.chunking import CHUNK_SET
    from app.services.section_summaries import backfill_section_summaries

    await save_defaults(resources, "gpt-5.6-luna", "low")
    await seed_sections(resources, chunk_set=CHUNK_SET)
    assert await backfill_section_summaries(resources) == 0
    hosted(resources)
    assert await backfill_section_summaries(resources) == 1


async def test_given_new_chunks_when_the_ingestion_hook_runs_then_section_summaries_are_queued(
    resources,
):
    from app.rag import hooks

    hosted(resources)
    await save_defaults(resources, "gpt-5.6-luna", "low")
    _, document_id, _ = await seed_sections(resources)
    async with resources.sessions() as session, session.begin():
        await hooks.after_chunks_persisted(session, document_id=document_id, resources=resources)
    (job,) = await section_jobs(resources)
    assert job.payload["document_id"] == str(document_id)


async def test_given_a_pdf_read_by_ingestion_then_it_asks_for_its_section_summaries(
    resources, tmp_path, monkeypatch
):
    from support.structured_pdf import create_structured_pdf

    from app.services import section_summaries
    from app.services.uploads import ingest_pdf_bytes
    from tests.test_automatic_summary_integration import run_ingest

    asked = []

    async def record(session, resources, document):
        asked.append(document.id)

    monkeypatch.setattr(section_summaries, "queue_section_summaries", record)
    data = create_structured_pdf(tmp_path / "structured.pdf").read_bytes()
    from uuid import uuid4

    accepted = await ingest_pdf_bytes(
        resources, data=data, filename="paper.pdf", request_id=uuid4(), paper_id=None
    )
    await run_ingest(resources, accepted.job_id)
    assert asked == [accepted.document_id]


async def test_given_a_section_summaries_job_when_the_worker_takes_it_then_it_runs(
    resources, monkeypatch
):
    from app.jobs import actors
    from app.repositories.jobs import enqueue
    from app.services import section_summaries

    ran = []

    async def runner(resources, job_id, generation, token, payload):
        ran.append(payload["document_id"])

    monkeypatch.setattr(actors, "_resources", resources)
    monkeypatch.setattr(section_summaries, "run_section_summaries_job", runner)
    async with resources.sessions() as session, session.begin():
        job = await enqueue(session, kind="section_summaries", payload={"document_id": "d"})
    await actors.execute_job.fn.__wrapped__(str(job.id), 1)
    assert ran == ["d"]


async def test_given_the_api_starting_when_search_is_prepared_then_summaries_are_backfilled(
    resources, monkeypatch
):
    from app.services import reindex, section_summaries

    backfilled = []

    async def record(resources):
        backfilled.append(True)
        return 0

    monkeypatch.setattr(section_summaries, "backfill_section_summaries", record)
    await reindex.prepare_search(resources)
    assert backfilled == [True]


async def test_given_section_summary_jobs_when_listed_or_retried_then_they_belong_to_the_paper(
    resources,
):
    from test_fulltext_integration import app_client

    from app.repositories.jobs import now

    hosted(resources)
    await save_defaults(resources, "gpt-5.6-luna", "low")
    paper_id, document_id, _ = await seed_sections(resources)
    job = await queue(resources, document_id)
    async with resources.sessions() as session, session.begin():
        row = await session.get(BackgroundJob, job.id)
        row.state, row.error_code, row.updated_at = "failed", "LEASE_EXPIRED", now()
    async with app_client(resources) as client:
        listed = await client.get("/api/v1/jobs", params={"paper_id": str(paper_id)})
        retried = await client.post(f"/api/v1/jobs/{job.id}/retry")
    assert listed.status_code == 200, listed.text
    (item,) = [entry for entry in listed.json()["items"] if entry["id"] == str(job.id)]
    assert item["paper_id"] == str(paper_id)
    # A paid generation is never replayed by a retry.
    assert retried.status_code == 409
    assert retried.json()["code"] == "NEW_GENERATION_REQUEST_REQUIRED"


def test_given_a_local_default_when_dispatching_then_section_summaries_use_the_local_lane():
    from app.services.dispatcher import LOCAL_GENERATION_KINDS

    assert "section_summaries" in LOCAL_GENERATION_KINDS


async def add_summary(resources, document_id, section_path, profile=None):
    """A stored summary of the section at `section_path`, optionally with a vector."""
    from app.integrations.embedding_catalog import PROFILES
    from app.models.retrieval import DocumentSection
    from tests.support.vectors import fixture_vector

    async with resources.sessions() as session, session.begin():
        section = await session.scalar(
            select(DocumentSection).where(
                DocumentSection.document_id == document_id,
                DocumentSection.path == list(section_path),
            )
        )
        summary = SectionSummary(
            document_id=document_id,
            section_id=section.id,
            chunk_set=section.chunk_set,
            title=" > ".join(section_path),
            page=section.page,
            page_end=section.page_end,
            ordinal=0,
            content="A summary.",
            sources=[],
            context_text="A summary.",
            token_count=3,
            model="gpt-5.6-luna",
            reasoning_effort="low",
            usage={},
        )
        session.add(summary)
        await session.flush()
        if profile is not None:
            session.add(
                SectionSummaryEmbedding(
                    summary_id=summary.id,
                    profile=profile,
                    document_id=document_id,
                    embedding=fixture_vector("A summary.", PROFILES[profile].dimensions),
                    input_hash="fixture",
                )
            )
        return summary.id


async def test_given_a_new_library_model_when_its_index_is_built_then_summaries_move_with_it(
    resources, monkeypatch
):
    """Summaries are embedded beside the chunks by the index job, and an older model's summary
    vectors go when its chunk vectors do (ARA-091)."""
    from app.integrations import embeddings
    from app.rag import indexing
    from tests.test_indexing_integration import ensure, run_job

    hosted(resources)
    calls = []
    monkeypatch.setattr(
        indexing,
        "create_embedder",
        lambda resources, profile: embeddings.create_embedder(
            resources, profile, transport=openai_fixture(calls)
        ),
    )
    _, document_id, _ = await seed_sections(resources, profile="openai-3-large")
    summary_id = await add_summary(resources, document_id, ["3 Limitations"], "openai-3-large")
    await use_library_profile(resources, SMALL)
    _, job_id = await ensure(resources, document_id, SMALL)
    await run_job(resources, job_id)
    async with resources.sessions() as session:
        profiles = (
            await session.scalars(
                select(SectionSummaryEmbedding.profile).where(
                    SectionSummaryEmbedding.summary_id == summary_id
                )
            )
        ).all()
    assert profiles == [SMALL]
