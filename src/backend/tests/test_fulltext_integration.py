"""Retrieval requests use real isolated database state and no live providers."""

import asyncio
from uuid import uuid4

import httpx
from sqlalchemy import func, select

from app.main import create_app
from app.models.jobs import BackgroundJob, JobOutbox
from app.models.research import Paper


async def seed_paper(resources):
    async with resources.sessions() as session, session.begin():
        paper = Paper(title="Access fixture", metadata_provenance={})
        session.add(paper)
        await session.flush()
        return paper.id


def app_client(resources):
    app = create_app(resources.settings)
    app.state.resources = resources
    return httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test")


async def test_fulltext_post_atomically_creates_paper_job_and_outbox(resources):
    """Given a saved paper, when requested, then durable retrieval exists before dispatch."""
    paper_id = await seed_paper(resources)
    async with app_client(resources) as client:
        response = await client.post(
            f"/api/v1/papers/{paper_id}/retrieve-fulltext", json={"request_id": str(uuid4())}
        )
    assert response.status_code == 202, response.text
    assert response.json()["paper_id"] == str(paper_id)
    async with resources.sessions() as session:
        job = await session.get(BackgroundJob, response.json()["job_id"])
        assert job.kind == "fulltext" and job.state == "queued"
        assert job.payload["paper_id"] == str(paper_id)
        assert job.payload["attachment_request_id"]
        assert await session.scalar(select(func.count()).select_from(JobOutbox)) == 1


async def test_fulltext_uuid_replays_original_job(resources):
    paper_id, request_id = await seed_paper(resources), str(uuid4())
    async with app_client(resources) as client:
        first = await client.post(
            f"/api/v1/papers/{paper_id}/retrieve-fulltext", json={"request_id": request_id}
        )
        assert first.status_code == 202
        repeat = await client.post(
            f"/api/v1/papers/{paper_id}/retrieve-fulltext", json={"request_id": request_id}
        )
    assert repeat.status_code == 202 and repeat.json() == first.json()
    async with resources.sessions() as session:
        assert await session.scalar(select(func.count()).select_from(BackgroundJob)) == 1


async def test_fulltext_uuid_other_paper_conflicts(resources):
    first_id, second_id = await seed_paper(resources), await seed_paper(resources)
    request_id = str(uuid4())
    async with app_client(resources) as client:
        first = await client.post(
            f"/api/v1/papers/{first_id}/retrieve-fulltext", json={"request_id": request_id}
        )
        assert first.status_code == 202
        conflict = await client.post(
            f"/api/v1/papers/{second_id}/retrieve-fulltext", json={"request_id": request_id}
        )
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "FULLTEXT_REQUEST_CONFLICT"


async def test_concurrent_requests_share_active_job(resources):
    paper_id = await seed_paper(resources)
    async with app_client(resources) as client:
        replies = await asyncio.gather(
            *[
                client.post(
                    f"/api/v1/papers/{paper_id}/retrieve-fulltext",
                    json={"request_id": str(uuid4())},
                )
                for _ in range(4)
            ]
        )
    assert all(reply.status_code == 202 for reply in replies)
    assert len({reply.json()["job_id"] for reply in replies}) == 1
    async with resources.sessions() as session:
        assert await session.scalar(select(func.count()).select_from(BackgroundJob)) == 1


async def test_new_uuid_after_denial_creates_new_job(resources):
    paper_id, request_id = await seed_paper(resources), str(uuid4())
    async with app_client(resources) as client:
        first = await client.post(
            f"/api/v1/papers/{paper_id}/retrieve-fulltext", json={"request_id": request_id}
        )
        assert first.status_code == 202
        async with resources.sessions() as session, session.begin():
            job = await session.get(BackgroundJob, first.json()["job_id"])
            job.state, job.error_code = "failed", "FULLTEXT_BLOCKED"
        new = await client.post(
            f"/api/v1/papers/{paper_id}/retrieve-fulltext", json={"request_id": str(uuid4())}
        )
        old = await client.post(
            f"/api/v1/papers/{paper_id}/retrieve-fulltext", json={"request_id": request_id}
        )
    assert new.status_code == 202 and new.json()["job_id"] != first.json()["job_id"]
    assert old.json() == first.json()


async def test_fulltext_reads_saved_state_without_provider_requests(resources):
    paper_id = await seed_paper(resources)
    async with app_client(resources) as client:
        response = await client.get(f"/api/v1/papers/{paper_id}/fulltext")
    assert response.status_code == 200
    assert response.json()["availability"] == "unknown"
    assert response.json()["retrieval_job"] is None
    assert response.json()["attempts"] == []


async def test_fulltext_rejects_browser_url_and_unknown_paper(resources):
    async with app_client(resources) as client:
        unsafe = await client.post(
            f"/api/v1/papers/{uuid4()}/retrieve-fulltext",
            json={"request_id": str(uuid4()), "url": "http://127.0.0.1/secret"},
        )
        missing = await client.get(f"/api/v1/papers/{uuid4()}/fulltext")
    assert unsafe.status_code == 422
    assert missing.status_code == 404 and missing.json()["code"] == "PAPER_NOT_FOUND"


async def test_jobs_filter_fulltext_by_paper(resources):
    paper_id = await seed_paper(resources)
    async with app_client(resources) as client:
        accepted = await client.post(
            f"/api/v1/papers/{paper_id}/retrieve-fulltext", json={"request_id": str(uuid4())}
        )
        assert accepted.status_code == 202
        listed = await client.get(f"/api/v1/jobs?kind=fulltext&paper_id={paper_id}")
        assert listed.status_code == 200
        assert [item["id"] for item in listed.json()["items"]] == [accepted.json()["job_id"]]
        assert listed.json()["items"][0]["paper_title"] == "Access fixture"
        assert (await client.get(f"/api/v1/jobs?kind=fulltext&paper_id={uuid4()}")).json()[
            "items"
        ] == []


async def test_generic_retry_requires_new_fulltext_request(resources):
    paper_id = await seed_paper(resources)
    async with resources.sessions() as session, session.begin():
        job = BackgroundJob(
            kind="fulltext",
            state="failed",
            payload={"paper_id": str(paper_id)},
            error_code="JOB_EXECUTION_FAILED",
        )
        session.add(job)
        await session.flush()
        job_id = job.id
    async with app_client(resources) as client:
        response = await client.post(f"/api/v1/jobs/{job_id}/retry", json={})
    assert response.status_code == 409
    assert response.json()["code"] == "NEW_FULLTEXT_REQUEST_REQUIRED"


async def test_fulltext_attempt_rejects_expired_lease(resources):
    from datetime import timedelta

    from app.models.fulltext import FullTextAttempt
    from app.repositories.fulltext import record_attempt
    from app.repositories.jobs import claim, now
    from app.schemas.fulltext import DownloadResult, FullTextCandidate
    from app.schemas.research import FullTextLocation

    paper_id = await seed_paper(resources)
    async with app_client(resources) as client:
        accepted = (
            await client.post(
                f"/api/v1/papers/{paper_id}/retrieve-fulltext", json={"request_id": str(uuid4())}
            )
        ).json()
    job_id = accepted["job_id"]
    token = await claim(resources.sessions, job_id, 1)
    async with resources.sessions() as session, session.begin():
        job = await session.get(BackgroundJob, job_id)
        job.lease_expires_at = now() - timedelta(seconds=1)
    async with resources.sessions() as session, session.begin():
        saved = await record_attempt(
            session,
            job_id=job_id,
            generation=1,
            lease_token=token,
            ordinal=0,
            candidate=FullTextCandidate(
                provider="openalex",
                external_id="W123",
                source_label="OpenAlex",
                url="https://arxiv.org/pdf/1",
                location=FullTextLocation(),
            ),
            result=DownloadResult("blocked", response_status=403, reason="Download blocked."),
        )
        assert saved is False
        assert await session.scalar(select(func.count()).select_from(FullTextAttempt)) == 0


async def test_fulltext_attempt_persists_once_and_returns_safe_status(resources):
    from app.models.fulltext import FullTextAttempt
    from app.repositories.fulltext import record_attempt
    from app.repositories.jobs import claim
    from app.schemas.fulltext import DownloadResult, FullTextCandidate
    from app.schemas.research import FullTextLocation

    paper_id = await seed_paper(resources)
    async with app_client(resources) as client:
        accepted = (
            await client.post(
                f"/api/v1/papers/{paper_id}/retrieve-fulltext", json={"request_id": str(uuid4())}
            )
        ).json()
        token = await claim(resources.sessions, accepted["job_id"], 1)
        values = dict(
            job_id=accepted["job_id"],
            generation=1,
            lease_token=token,
            ordinal=0,
            candidate=FullTextCandidate(
                provider="semantic_scholar",
                external_id="s2",
                source_label="Semantic Scholar",
                url="https://arxiv.org/pdf/1",
                location=FullTextLocation(version="acceptedVersion"),
            ),
            result=DownloadResult("blocked", response_status=403, reason="Download blocked."),
        )
        for _ in range(2):
            async with resources.sessions() as session, session.begin():
                assert await record_attempt(session, **values)
        status = (await client.get(f"/api/v1/papers/{paper_id}/fulltext")).json()
        assert len(status["attempts"]) == 1
        assert status["attempts"][0]["outcome"] == "blocked"
        assert status["attempts"][0]["version"] == "acceptedVersion"
        assert "url" not in status["attempts"][0]
    async with resources.sessions() as session:
        assert await session.scalar(select(func.count()).select_from(FullTextAttempt)) == 1


async def test_readiness_rejects_previous_schema(resources):
    from sqlalchemy import text

    from app.services.health import readiness

    async with resources.sessions() as session, session.begin():
        await session.execute(text("UPDATE alembic_version SET version_num='0005_local_models'"))
    try:
        assert (await readiness(resources))["database"] == "unavailable"
    finally:
        async with resources.sessions() as session, session.begin():
            await session.execute(text("UPDATE alembic_version SET version_num='0006_fulltext'"))
