"""Automatic PDF retrieval on save and on first workspace open (ARA-084), on real PostgreSQL."""

import asyncio
from datetime import timedelta
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import func, select
from test_fulltext_integration import app_client

from app.models.fulltext import FullTextRequest
from app.models.jobs import BackgroundJob, JobOutbox
from app.models.research import Paper
from app.repositories.jobs import now
from app.repositories.papers import save_canonical
from app.schemas.research import FullTextLocation, SearchResult

pytestmark = pytest.mark.integration


def openalex(pdf_url=None, doi=None, external_id="W700"):
    work = {
        "id": f"https://openalex.org/{external_id}",
        "display_name": "Automatic retrieval fixture",
        "doi": f"https://doi.org/{doi}" if doi else None,
        "authorships": [],
    }
    if pdf_url:
        work["best_oa_location"] = {
            "pdf_url": pdf_url,
            "is_oa": True,
            "version": "acceptedVersion",
            "source": {"type": "repository"},
        }
    return work


async def serve(resources, work):
    await resources.http.aclose()
    resources.http = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json=work))
    )


async def fulltext_jobs(resources):
    async with resources.sessions() as session:
        return list(
            (
                await session.scalars(
                    select(BackgroundJob)
                    .where(BackgroundJob.kind == "fulltext")
                    .order_by(BackgroundJob.created_at)
                )
            ).all()
        )


async def save(client, external_id="W700"):
    response = await client.post(
        "/api/v1/papers", json={"provider": "openalex", "external_id": external_id}
    )
    assert response.status_code in {200, 201}, response.text
    return response.json()["id"]


async def test_saving_a_listed_open_pdf_starts_one_durable_retrieval(resources):
    """Given provider metadata listing an open PDF, when saved, then one job and its outbox
    event commit with the paper, without a click."""
    await serve(resources, openalex(pdf_url="https://arxiv.org/pdf/700"))
    async with app_client(resources) as client:
        paper_id = await save(client)
        status = (await client.get(f"/api/v1/papers/{paper_id}/fulltext")).json()
    jobs = await fulltext_jobs(resources)
    assert len(jobs) == 1
    assert jobs[0].state == "queued" and jobs[0].payload["paper_id"] == paper_id
    assert status["retrieval_job"]["id"] == str(jobs[0].id)
    async with resources.sessions() as session:
        assert await session.scalar(select(func.count()).select_from(JobOutbox)) == 1
        assert await session.scalar(select(func.count()).select_from(FullTextRequest)) == 1


async def test_a_doi_alone_allows_discovery_but_no_identifier_starts_nothing(resources):
    await serve(resources, openalex(doi="10.1000/discoverable"))
    async with app_client(resources) as client:
        await save(client)
        assert len(await fulltext_jobs(resources)) == 1
        await serve(resources, openalex(external_id="W701"))
        await save(client, "W701")
    assert len(await fulltext_jobs(resources)) == 1


async def test_duplicate_and_concurrent_saves_share_the_single_automatic_job(resources):
    await serve(resources, openalex(pdf_url="https://arxiv.org/pdf/700"))
    async with app_client(resources) as client:
        identifiers = await asyncio.gather(*[save(client) for _ in range(4)])
        await save(client)
    assert len(set(identifiers)) == 1
    assert len(await fulltext_jobs(resources)) == 1


async def test_failed_automatic_retrieval_is_never_restarted_automatically(resources):
    """Given the automatic job failed, when the paper is saved or opened again, then no new
    job starts; a deliberate request with a fresh UUID still can."""
    await serve(resources, openalex(pdf_url="https://arxiv.org/pdf/700"))
    async with app_client(resources) as client:
        paper_id = await save(client)
        (job,) = await fulltext_jobs(resources)
        async with resources.sessions() as session, session.begin():
            failed = await session.get(BackgroundJob, job.id)
            failed.state, failed.result = "failed", {"outcome": "blocked"}
        await save(client)
        opened = await client.post(f"/api/v1/papers/{paper_id}/retrieve-fulltext/automatic")
        assert opened.status_code == 200
        assert opened.json() == {"paper_id": paper_id, "job_id": str(job.id)}
        assert len(await fulltext_jobs(resources)) == 1
        manual = await client.post(
            f"/api/v1/papers/{paper_id}/retrieve-fulltext", json={"request_id": str(uuid4())}
        )
    assert manual.status_code == 202 and manual.json()["job_id"] != str(job.id)


async def legacy_paper(resources, *, pdf_url="https://arxiv.org/pdf/legacy", doi=None):
    """A metadata-only paper saved before automatic retrieval existed."""
    async with resources.sessions() as session, session.begin():
        paper, _ = await save_canonical(
            session,
            SearchResult(
                provider="openalex",
                external_id=f"W{uuid4().int % 10**9}",
                title="Legacy fixture",
                doi=doi,
                locations=[FullTextLocation(pdf_url=pdf_url, is_oa=True)] if pdf_url else [],
            ),
        )
        return str(paper.id)


async def test_opening_a_legacy_paper_starts_retrieval_once(resources):
    """Given a paper saved before this change with no attempt, when its workspace asks
    repeatedly and concurrently, then exactly one job exists and every answer names it."""
    paper_id = await legacy_paper(resources)
    async with app_client(resources) as client:
        replies = await asyncio.gather(
            *[
                client.post(f"/api/v1/papers/{paper_id}/retrieve-fulltext/automatic")
                for _ in range(3)
            ]
        )
        again = await client.post(f"/api/v1/papers/{paper_id}/retrieve-fulltext/automatic")
    jobs = await fulltext_jobs(resources)
    assert len(jobs) == 1
    assert {reply.json()["job_id"] for reply in [*replies, again]} == {str(jobs[0].id)}


async def test_earlier_manual_attempts_attached_pdfs_and_bare_papers_are_left_alone(resources):
    attempted = await legacy_paper(resources)
    bare = await legacy_paper(resources, pdf_url=None)
    attached = await legacy_paper(resources)
    async with resources.sessions() as session, session.begin():
        (await session.get(Paper, attached)).active_document_id = uuid4()
    async with app_client(resources) as client:
        manual = await client.post(
            f"/api/v1/papers/{attempted}/retrieve-fulltext", json={"request_id": str(uuid4())}
        )
        assert manual.status_code == 202
        for paper_id in (attempted, bare, attached):
            reply = await client.post(f"/api/v1/papers/{paper_id}/retrieve-fulltext/automatic")
            assert reply.status_code == 200
            assert reply.json() == {"paper_id": paper_id, "job_id": None}
        missing = await client.post(f"/api/v1/papers/{uuid4()}/retrieve-fulltext/automatic")
    assert missing.status_code == 404
    assert [job.id for job in await fulltext_jobs(resources)] == [UUID(manual.json()["job_id"])]


async def test_a_deliberate_retry_waits_out_the_sources_reported_limit(resources):
    """Given a rate-limited failure with a 120-second wait, when a new request arrives early,
    then its job and dispatch event become available only after that wait."""
    paper_id = await legacy_paper(resources)
    async with app_client(resources) as client:
        first = await client.post(f"/api/v1/papers/{paper_id}/retrieve-fulltext/automatic")
        async with resources.sessions() as session, session.begin():
            job = await session.get(BackgroundJob, first.json()["job_id"])
            job.state, job.stage = "failed", "failed"
            job.result = {"outcome": "rate_limited", "retry_after": 120}
            job.updated_at = now()
        retry = await client.post(
            f"/api/v1/papers/{paper_id}/retrieve-fulltext", json={"request_id": str(uuid4())}
        )
    async with resources.sessions() as session:
        job = await session.get(BackgroundJob, retry.json()["job_id"])
        event = await session.scalar(select(JobOutbox).where(JobOutbox.job_id == job.id))
    assert job.available_at >= now() + timedelta(seconds=110)
    assert event.available_at == job.available_at
