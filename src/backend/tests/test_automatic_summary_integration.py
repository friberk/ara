"""A PDF that becomes ready is summarized once with the saved defaults (ARA-084)."""

import subprocess
import sys
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import func, select
from test_fulltext_integration import app_client

from app.models.jobs import BackgroundJob, JobOutbox
from app.models.research import (
    Document,
    GenerationReservation,
    ModelConfiguration,
    PaperSummary,
)
from app.repositories.jobs import claim, enqueue

pytestmark = pytest.mark.integration


@pytest.fixture
def original_pdf():
    # Title and author metadata keep ingestion from asking a model for bibliographic fields.
    return subprocess.check_output(
        [
            sys.executable,
            "-c",
            "import pymupdf; d=pymupdf.open(); p=d.new_page(); "
            "p.insert_text((72,72),'Results: the probe reached 91 percent recall.'); "
            "d.set_metadata({'title':'Summary fixture','author':'Ada Researcher'}); "
            "import sys; sys.stdout.buffer.write(d.tobytes())",
        ]
    )


async def save_defaults(resources, model, effort):
    async with resources.sessions() as session, session.begin():
        session.add(
            ModelConfiguration(
                key="defaults",
                value={
                    "default_model": model,
                    "reasoning_effort": effort,
                    "memory_model": "gpt-5.6-luna",
                },
            )
        )


def hosted(resources):
    resources.settings.openai_api_key = SecretStr("fixture-key")


async def run_ingest(resources, job_id):
    from app.services.ingestion import run_ingest_job

    async with resources.sessions() as session:
        job = await session.get(BackgroundJob, job_id)
    token = await claim(resources.sessions, job.id, job.generation)
    assert token is not None
    await run_ingest_job(resources, job.id, job.generation, token, dict(job.payload))
    return job.id, job.generation, token, dict(job.payload)


async def ingest(resources, original_pdf):
    from app.services.uploads import ingest_pdf_bytes

    accepted = await ingest_pdf_bytes(
        resources, data=original_pdf, filename="paper.pdf", request_id=uuid4(), paper_id=None
    )
    delivery = await run_ingest(resources, accepted.job_id)
    async with resources.sessions() as session:
        assert (await session.get(Document, accepted.document_id)).status == "ready"
    return accepted, delivery


async def summary_jobs(resources):
    async with resources.sessions() as session:
        return list(
            (
                await session.scalars(select(BackgroundJob).where(BackgroundJob.kind == "summary"))
            ).all()
        )


async def blocked(resources, paper_id):
    async with app_client(resources) as client:
        response = await client.get(f"/api/v1/papers/{paper_id}/summaries")
    assert response.status_code == 200, response.text
    return response.json()["blocked"]


async def test_a_newly_ready_pdf_starts_one_summary_with_the_saved_defaults(
    resources, original_pdf
):
    """Given a hosted default saved as terra/high, when an uploaded PDF becomes ready, then
    exactly one summary job is queued with those settings, even if delivered twice."""
    from app.services.ingestion import run_ingest_job
    from app.services.summarization import automatic_summary_request

    hosted(resources)
    await save_defaults(resources, "gpt-5.6-terra", "high")
    accepted, delivery = await ingest(resources, original_pdf)
    await run_ingest_job(resources, *delivery)
    (job,) = await summary_jobs(resources)
    assert job.state == "queued"
    assert job.payload == {
        "model": "gpt-5.6-terra",
        "reasoning_effort": "high",
        "request_id": str(automatic_summary_request(accepted.document_id)),
        "paper_id": str(accepted.paper_id),
        "document_id": str(accepted.document_id),
        "automatic": True,
    }
    async with resources.sessions() as session:
        assert await session.scalar(
            select(func.count()).select_from(JobOutbox).where(JobOutbox.job_id == job.id)
        )
    assert await blocked(resources, accepted.paper_id) is None


async def test_reingesting_a_ready_document_never_starts_a_summary(resources, original_pdf):
    """Given a ready PDF whose summary did not start, when startup re-ingestion or a retry
    makes it ready again, then no summary starts even though generation is now possible."""
    from app.services.reindex import enqueue_reindex

    accepted, _ = await ingest(resources, original_pdf)
    assert await summary_jobs(resources) == []
    hosted(resources)
    async with resources.sessions() as session, session.begin():
        (await session.get(Document, accepted.document_id)).chunk_set = "layout-v0:outdated"
    assert await enqueue_reindex(resources) == 1
    async with resources.sessions() as session:
        document = await session.get(Document, accepted.document_id)
    await run_ingest(resources, document.ingest_job_id)
    async with resources.sessions() as session, session.begin():
        retry = await enqueue(
            session, kind="ingest", payload={"document_id": str(accepted.document_id)}
        )
    await run_ingest(resources, retry.id)
    assert await summary_jobs(resources) == []


async def test_a_local_default_that_is_not_ready_starts_nothing_paid(resources, original_pdf):
    """Given a hosted key but a saved local default without weights, when the PDF becomes
    ready, then nothing starts (no hosted fallback) and the reason is reported."""
    hosted(resources)
    await save_defaults(resources, "ifm-k2-horizon-7b", "default")
    accepted, _ = await ingest(resources, original_pdf)
    assert await summary_jobs(resources) == []
    reason = await blocked(resources, accepted.paper_id)
    assert reason["code"] == "LOCAL_MODEL_NOT_READY"
    assert reason["model"] == "ifm-k2-horizon-7b" and reason["message"]


async def test_a_ready_local_default_summarizes_locally(resources, original_pdf):
    from test_ai_integration import local_fixture

    spec, _ = await local_fixture(resources)
    await save_defaults(resources, spec.key, "default")
    accepted, _ = await ingest(resources, original_pdf)
    (job,) = await summary_jobs(resources)
    assert job.payload["model"] == spec.key and job.payload["reasoning_effort"] == "default"


async def test_unconfigured_hosted_generation_starts_nothing(resources, original_pdf):
    resources.settings.openai_api_key = None
    accepted, _ = await ingest(resources, original_pdf)
    assert await summary_jobs(resources) == []
    assert (await blocked(resources, accepted.paper_id))["code"] == "MODEL_NOT_CONFIGURED"


async def test_a_spent_daily_budget_starts_nothing(resources, original_pdf):
    hosted(resources)
    async with resources.sessions() as session, session.begin():
        session.add(
            GenerationReservation(
                model="gpt-5.6-luna", amount=Decimal(str(resources.settings.llm_daily_budget_usd))
            )
        )
    accepted, _ = await ingest(resources, original_pdf)
    assert await summary_jobs(resources) == []
    assert (await blocked(resources, accepted.paper_id))["code"] == "DAILY_BUDGET_EXCEEDED"


async def test_summarized_running_or_replaced_documents_are_skipped(resources):
    """Given a document with a summary, a running summary job, or a newer active PDF, when
    the ready hook runs, then it queues nothing."""
    from app.models.research import Paper
    from app.services.summarization import queue_automatic_summary
    from tests.support.papers import seed_paper

    hosted(resources)
    summarized, running, replaced = [await seed_paper(resources) for _ in range(3)]
    async with resources.sessions() as session, session.begin():
        session.add(
            PaperSummary(
                paper_id=summarized[0],
                document_id=summarized[1],
                model="gpt-5.6-luna",
                reasoning_effort="low",
                content="Earlier summary.",
            )
        )
        await enqueue(
            session,
            kind="summary",
            payload={
                "model": "gpt-5.6-luna",
                "reasoning_effort": "low",
                "request_id": str(uuid4()),
                "paper_id": str(running[0]),
                "document_id": str(running[1]),
            },
        )
        (await session.get(Paper, replaced[0])).active_document_id = uuid4()
    for _, document_id in (summarized, running, replaced):
        async with resources.sessions() as session, session.begin():
            document = await session.get(Document, document_id)
            assert await queue_automatic_summary(session, resources, document) is None
    assert len(await summary_jobs(resources)) == 1
    for paper_id, _ in (summarized, running):
        assert await blocked(resources, paper_id) is None
