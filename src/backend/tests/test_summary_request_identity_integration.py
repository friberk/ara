"""A new summary is a new generation; only a repeated request ID replays one (ARA-117)."""

from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import func, select, update

from app.models.jobs import BackgroundJob
from tests.support.evidence import seed_structured

pytestmark = pytest.mark.integration


async def finish(resources, job_id) -> None:
    async with resources.sessions() as session, session.begin():
        await session.execute(
            update(BackgroundJob)
            .where(BackgroundJob.id == job_id)
            .values(state="completed", stage="completed", progress=100)
        )


async def test_given_a_finished_summary_when_requested_again_then_only_a_new_id_generates(
    resources,
):
    from app.main import create_app

    resources.settings.openai_api_key = SecretStr("http-fixture-only")
    paper_id, _, _ = await seed_structured(resources)
    app = create_app(resources.settings)
    app.state.resources = resources
    settings = {"model": "gpt-5.6-luna", "reasoning_effort": "low"}
    first_id, second_id = str(uuid4()), str(uuid4())
    url = f"/api/v1/papers/{paper_id}/summaries"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        first = await client.post(url, json={**settings, "request_id": first_id})
        assert first.status_code == 202, first.text
        await finish(resources, first.json()["job_id"])
        second = await client.post(url, json={**settings, "request_id": second_id})
        assert second.status_code == 202, second.text
        await finish(resources, second.json()["job_id"])
        replay = await client.post(url, json={**settings, "request_id": first_id})
    assert second.json()["job_id"] != first.json()["job_id"]
    assert replay.status_code == 202 and replay.json()["job_id"] == first.json()["job_id"]
    async with resources.sessions() as session:
        jobs = await session.scalar(
            select(func.count(BackgroundJob.id)).where(BackgroundJob.kind == "summary")
        )
    assert jobs == 2
