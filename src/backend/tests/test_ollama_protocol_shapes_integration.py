"""ARA-054 protocol failures settle automatic 7B preparation in isolated real SQL."""

import httpx
import pytest
from test_automatic_model_readiness import KEY, jobs, seed
from test_ollama_protocol_shapes import protocol_transport

from app.models.jobs import BackgroundJob
from app.models.local_models import ModelInstallation
from app.repositories.jobs import recover
from app.repositories.local_models import claim_model_job, pending_owner
from app.services import local_models

# Open-model tests run with EXPERIMENTAL_OPEN_MODELS on (ARA-090).
pytestmark = [pytest.mark.integration, pytest.mark.open_models]


@pytest.mark.parametrize(
    "case",
    [
        ("show", "model_info", None),
        ("show", "capabilities", None),
        ("show", "model_info", {"fixture.context_length": "32768"}),
        ("tags", "models", None),
        ("tags", "models", [None]),
        ("probe", "message", None),
        ("stream", None, []),
        ("stream", "message", None),
        ("schema", "message", None),
        ("version", "version", None),
    ],
)
async def test_given_auto_verify_and_malformed_protocol_then_failed_without_recovery_loop(
    resources, case
):
    await seed(resources)
    state, calls, transport = protocol_transport()
    await resources.http.aclose()
    resources.http = httpx.AsyncClient(transport=transport)
    await local_models.reconcile_local_models(resources)
    job = (await jobs(resources))[0]
    assert job.payload["verify_only"] is True and job.payload["automatic"] is True
    state["case"] = case
    token = await claim_model_job(resources.sessions, job.id, job.generation)
    assert token
    await local_models.run_model_job(resources, job.id, job.generation, token)
    async with resources.sessions() as session:
        failed = await session.get(BackgroundJob, job.id)
        row = await session.get(ModelInstallation, KEY)
        assert failed.state == row.state == "failed"
        assert failed.error_code == row.error_code == "MODEL_PROTOCOL_ERROR"
        assert failed.error_message == "The runtime returned an invalid response."
        assert failed.attempts == 1 and failed.generation == job.generation
        assert failed.lease_token is None and failed.lease_expires_at is None
        assert row.weights_present and await pending_owner(session) is None
    await recover(resources.sessions)
    await local_models.reconcile_local_models(resources)
    assert len(await jobs(resources)) == 1
    assert (await jobs(resources))[0].state == "failed"
    assert not any("pull" in path for path in calls)
