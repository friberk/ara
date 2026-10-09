from uuid import uuid4

import httpx
import pytest

from app.main import create_app

pytestmark = pytest.mark.integration


def client_for(resources):
    app = create_app(resources.settings)
    app.state.resources = resources
    return httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test")


async def test_local_model_actions_have_public_idempotent_contract(resources):
    async with client_for(resources) as client:
        models = (await client.get("/api/v1/models")).json()["items"]
        local = [model for model in models if model["provider"] == "ollama"]
        assert len(local) == 3
        assert all(model["installation"]["state"] == "missing" for model in local)
        identity = str(uuid4())
        response = await client.post(
            "/api/v1/models/ifm-k2-horizon-3.7b/download", json={"request_id": identity}
        )
        assert response.status_code == 202
        job_id = response.json()["id"]
        assert (
            await client.post(
                "/api/v1/models/ifm-k2-horizon-3.7b/download", json={"request_id": identity}
            )
        ).json()["id"] == job_id
        paused = await client.post(
            f"/api/v1/jobs/{job_id}/pause", json={"request_id": str(uuid4())}
        )
        assert paused.status_code == 202 and paused.json()["state"] == "paused"
        active = await client.get("/api/v1/jobs?kind=model_download&active=true")
        assert active.status_code == 200 and len(active.json()["items"]) == 1
        resumed = await client.post(
            f"/api/v1/jobs/{job_id}/resume", json={"request_id": str(uuid4())}
        )
        assert resumed.status_code == 202 and resumed.json()["state"] == "queued"
        response = await client.delete(
            "/api/v1/models/qwen3.8-27b/installation", headers={"Idempotency-Key": str(uuid4())}
        )
        assert response.status_code == 202 and response.json()["kind"] == "model_delete"
