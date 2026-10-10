"""Background work for a deleted paper settles safely (ARA-095).

The deletion commit fails the paper's queued and running jobs with PAPER_DELETED, fencing their
workers out. A job that missed it (its row was locked at that moment, simulated here by deleting
the paper with plain SQL) settles itself when it finds the paper gone. Either way no worker
crashes, no lease recovery loops, and no row is written for the deleted paper.
"""

from uuid import uuid4

import httpx
import pytest
from sqlalchemy import delete, func, select
from support.academic import DOI, openalex_work, providers
from support.front_matter import toolchain_pdf
from test_fulltext_jobs import enqueue_and_claim, original_pdf, prepare  # noqa: F401
from test_paper_deletion_integration import client_for

from app.models.jobs import BackgroundJob
from app.models.memory import ChatMemory, ChatTurnEmbedding
from app.models.research import Document, DocumentPage, Paper, PaperSummary
from app.models.retrieval import ChunkEmbedding, RetrievalIndex
from app.repositories.jobs import claim, enqueue
from tests.support.chats import add_turns, new_chat
from tests.support.evidence import seed_structured

pytestmark = pytest.mark.integration


async def job_row(resources, job_id) -> BackgroundJob:
    async with resources.sessions() as session:
        return await session.get(BackgroundJob, job_id)


async def count(resources, model, *where) -> int:
    async with resources.sessions() as session:
        return await session.scalar(select(func.count()).select_from(model).where(*where))


async def paper_jobs(resources, title: str) -> dict:
    """A ready paper, a chat about only it, and one queued job of every kind that names it."""
    paper, document, _ = await seed_structured(resources, title=title)
    chat = await new_chat(resources, (paper, document))
    (turn,) = await add_turns(resources, chat, [("Why?", "Because.")])
    async with resources.sessions() as session, session.begin():
        index = await session.scalar(
            select(RetrievalIndex.id).where(RetrievalIndex.document_id == document)
        )
        payloads = {
            "ingest": {"document_id": str(document)},
            "summary": {
                "paper_id": str(paper),
                "document_id": str(document),
                "model": "gpt-5.6-luna",
                "reasoning_effort": "low",
            },
            "fulltext": {"paper_id": str(paper), "attachment_request_id": str(uuid4())},
            "metadata": {"paper_id": str(paper), "document_id": str(document), "clues": {}},
            "embed": {
                "index_id": str(index),
                "document_id": str(document),
                "paper_id": str(paper),
                "profile": "openai-3-large",
            },
            "compact_chat": {
                "chat_id": str(chat),
                "through_message_id": str(turn.answer),
                "model": "gpt-5.6-luna",
                "effort": "low",
            },
            "embed_turn": {"message_id": str(turn.answer), "chat_id": str(chat)},
        }
        jobs = {
            kind: (await enqueue(session, kind=kind, payload=payload)).id
            for kind, payload in payloads.items()
        }
    return {"paper": paper, "document": document, "chat": chat, "jobs": jobs}


async def test_deletion_settles_every_queued_and_running_job_of_the_paper(resources):
    """Given queued jobs of every kind and one running job, when the paper is deleted, then each
    fails with PAPER_DELETED and no lease, none can be claimed or dispatched, and another
    paper's jobs are untouched."""
    from app.services.dispatcher import dispatch_once

    gone = await paper_jobs(resources, "Deleted paper")
    kept = await paper_jobs(resources, "Kept paper")
    running = gone["jobs"]["summary"]
    assert await claim(resources.sessions, running, 1) is not None

    async with client_for(resources) as client:
        assert (await client.delete(f"/api/v1/papers/{gone['paper']}")).status_code == 204

    for kind, job_id in gone["jobs"].items():
        job = await job_row(resources, job_id)
        assert (job.state, job.stage, job.error_code) == ("failed", "failed", "PAPER_DELETED"), kind
        assert job.error_message == "Stopped because the paper was deleted."
        assert job.lease_token is None and job.lease_expires_at is None, kind
        title = None if kind in {"compact_chat", "embed_turn"} else "Deleted paper"
        assert job.result == {"outcome": "paper_deleted", "paper_title": title}, kind
        assert await claim(resources.sessions, job_id, job.generation) is None, kind
    for kind, job_id in kept["jobs"].items():
        assert (await job_row(resources, job_id)).state == "queued", kind
    published = []
    await dispatch_once(resources.sessions, lambda job_id, generation: published.append(job_id))
    assert set(published) == {str(job_id) for job_id in kept["jobs"].values()} | {
        str((await storage_cleanup(resources)).id)
    }


async def storage_cleanup(resources) -> BackgroundJob:
    async with resources.sessions() as session:
        return await session.scalar(
            select(BackgroundJob).where(BackgroundJob.kind == "storage_cleanup")
        )


async def test_activity_names_a_deleted_papers_jobs_without_linking_them(resources):
    gone = await paper_jobs(resources, "Deleted paper")
    async with client_for(resources) as client:
        await client.delete(f"/api/v1/papers/{gone['paper']}")
        listed = (await client.get("/api/v1/jobs")).json()["items"]
        summary = (await client.get(f"/api/v1/jobs/{gone['jobs']['summary']}")).json()
    by_id = {item["id"]: item for item in listed}
    for kind in ("ingest", "summary", "fulltext", "metadata"):
        item = by_id[str(gone["jobs"][kind])]
        assert item["paper_id"] is None and item["paper_title"] == "Deleted paper", kind
        assert item["error"] == {
            "code": "PAPER_DELETED",
            "message": "Stopped because the paper was deleted.",
        }
    assert summary["paper_id"] is None and summary["paper_title"] == "Deleted paper"


async def test_fenced_out_workers_write_nothing_after_the_deletion(resources):
    """Given running jobs of every kind, when the paper is deleted and their workers carry on
    with their old leases, then they return quietly and write no row."""
    from app.rag.indexing import run_embed_job
    from app.services.fulltext import run_fulltext_job
    from app.services.ingestion import run_ingest_job
    from app.services.memory import run_compact_job, run_embed_turn_job
    from app.services.metadata import run_metadata_job
    from app.services.summarization import run_summary_job

    runners = {
        "ingest": run_ingest_job,
        "summary": run_summary_job,
        "fulltext": run_fulltext_job,
        "metadata": run_metadata_job,
        "embed": run_embed_job,
        "compact_chat": run_compact_job,
        "embed_turn": run_embed_turn_job,
    }
    gone = await paper_jobs(resources, "Deleted paper")
    leases = {
        kind: await claim(resources.sessions, job_id, 1) for kind, job_id in gone["jobs"].items()
    }
    async with client_for(resources) as client:
        assert (await client.delete(f"/api/v1/papers/{gone['paper']}")).status_code == 204
    requests = []
    await resources.http.aclose()
    resources.http = providers(requests)
    for kind, job_id in gone["jobs"].items():
        job = await job_row(resources, job_id)
        await runners[kind](resources, job_id, 1, leases[kind], dict(job.payload))
        after = await job_row(resources, job_id)
        assert (after.state, after.error_code) == ("failed", "PAPER_DELETED"), kind
    assert requests == []
    for model, column in (
        (Document, Document.paper_id),
        (PaperSummary, PaperSummary.paper_id),
    ):
        assert await count(resources, model, column == gone["paper"]) == 0
    assert await count(resources, DocumentPage) == 0
    assert await count(resources, ChunkEmbedding) == 0
    assert await count(resources, ChatMemory) == 0
    assert await count(resources, ChatTurnEmbedding) == 0


async def gone_without_settlement(resources, paper_id):
    """The paper disappears while its job keeps its lease, as when the job's row was locked
    during the deletion commit."""
    async with resources.sessions() as session, session.begin():
        await session.execute(delete(Paper).where(Paper.id == paper_id))


async def test_an_ingest_whose_paper_is_deleted_while_it_parses_settles_itself(
    resources, monkeypatch
):
    """Given an upload being read, when its paper is deleted mid-parse without settling the job,
    then the final write finds it gone, fails the job with PAPER_DELETED and stores no page."""
    from app.services import ingestion
    from app.services.uploads import ingest_pdf_bytes

    accepted = await ingest_pdf_bytes(
        resources,
        data=toolchain_pdf(stamp=None),
        filename="a.pdf",
        request_id=uuid4(),
        paper_id=None,
    )
    parse = ingestion.parse_in_child

    async def parse_then_delete(data, *args, **kwargs):
        parsed = await parse(data, *args, **kwargs)
        await gone_without_settlement(resources, accepted.paper_id)
        return parsed

    monkeypatch.setattr(ingestion, "parse_in_child", parse_then_delete)
    job = await job_row(resources, accepted.job_id)
    token = await claim(resources.sessions, job.id, job.generation)
    await ingestion.run_ingest_job(resources, job.id, job.generation, token, dict(job.payload))
    after = await job_row(resources, job.id)
    assert (after.state, after.error_code) == ("failed", "PAPER_DELETED")
    assert after.lease_token is None
    assert await count(resources, DocumentPage) == 0
    assert await count(resources, Paper) == 0


async def test_an_ingest_that_starts_after_its_paper_is_gone_settles_as_deleted(resources):
    from app.services.ingestion import run_ingest_job
    from app.services.uploads import ingest_pdf_bytes

    accepted = await ingest_pdf_bytes(
        resources,
        data=toolchain_pdf(stamp=None),
        filename="a.pdf",
        request_id=uuid4(),
        paper_id=None,
    )
    await gone_without_settlement(resources, accepted.paper_id)
    job = await job_row(resources, accepted.job_id)
    token = await claim(resources.sessions, job.id, job.generation)
    await run_ingest_job(resources, job.id, job.generation, token, dict(job.payload))
    after = await job_row(resources, job.id)
    assert (after.state, after.error_code) == ("failed", "PAPER_DELETED")


async def test_a_pdf_download_for_a_deleted_paper_settles_as_deleted(resources, original_pdf):  # noqa: F811
    """Given a retrieval running when its paper disappears, then it fails with PAPER_DELETED
    instead of reporting an invalid PDF, and no document is stored."""
    from app.services.fulltext import run_fulltext_job

    paper_id, downloads = await prepare(resources, original_pdf)
    job_id, generation, token, payload = await enqueue_and_claim(resources, paper_id)
    await gone_without_settlement(resources, paper_id)
    await run_fulltext_job(resources, job_id, generation, token, payload)
    after = await job_row(resources, job_id)
    assert (after.state, after.error_code) == ("failed", "PAPER_DELETED")
    assert downloads == [] and await count(resources, Document) == 0


async def test_a_pdf_download_whose_paper_goes_while_it_downloads_settles_as_deleted(
    resources,
    original_pdf,  # noqa: F811
):
    from app.services.fulltext import run_fulltext_job

    paper_id, _downloads = await prepare(resources, original_pdf)
    job_id, generation, token, payload = await enqueue_and_claim(resources, paper_id)
    fetch = resources.pdf_downloader.fetch

    async def fetch_then_delete(*args, **kwargs):
        downloaded = await fetch(*args, **kwargs)
        await gone_without_settlement(resources, paper_id)
        return downloaded

    resources.pdf_downloader.fetch = fetch_then_delete
    await run_fulltext_job(resources, job_id, generation, token, payload)
    after = await job_row(resources, job_id)
    assert (after.state, after.error_code) == ("failed", "PAPER_DELETED")
    assert await count(resources, Document) == 0


async def test_a_lookup_for_a_deleted_paper_asks_no_provider(resources):
    from app.services.metadata import run_metadata_job

    paper, document, _ = await seed_structured(resources, title="Deleted paper")
    async with resources.sessions() as session, session.begin():
        job = await enqueue(
            session,
            kind="metadata",
            payload={
                "paper_id": str(paper),
                "document_id": str(document),
                "clues": {"title": "Deleted paper", "doi": DOI},
            },
        )
    token = await claim(resources.sessions, job.id, job.generation)
    await gone_without_settlement(resources, paper)
    requests = []
    await resources.http.aclose()
    resources.http = providers(
        requests,
        openalex=lambda request: httpx.Response(200, json={"results": [openalex_work()]}),
    )
    await run_metadata_job(resources, job.id, job.generation, token, dict(job.payload))
    after = await job_row(resources, job.id)
    assert (after.state, after.error_code) == ("failed", "PAPER_DELETED")
    assert requests == []


@pytest.mark.parametrize("kind", ["summary", "embed"])
async def test_summary_and_index_jobs_whose_paper_vanished_settle_and_write_nothing(
    resources, kind
):
    """These runners already end when their PDF or index is gone; nothing is written."""
    from app.rag.indexing import run_embed_job
    from app.services.summarization import run_summary_job

    gone = await paper_jobs(resources, "Deleted paper")
    job_id = gone["jobs"][kind]
    token = await claim(resources.sessions, job_id, 1)
    await gone_without_settlement(resources, gone["paper"])
    job = await job_row(resources, job_id)
    runner = run_summary_job if kind == "summary" else run_embed_job
    await runner(resources, job_id, 1, token, dict(job.payload))
    after = await job_row(resources, job_id)
    assert after.state in {"failed", "completed"} and after.lease_token is None
    assert await count(resources, PaperSummary) == 0
    assert await count(resources, ChunkEmbedding) == 0
