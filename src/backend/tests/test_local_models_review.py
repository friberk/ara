"""Real SQL reproductions for operation ownership and pause/verification admission."""

from datetime import timedelta
from uuid import uuid4

import httpx
import pytest

from app.core.errors import AppError
from app.integrations.model_catalog import local_spec
from app.integrations.ollama import OllamaRuntime
from app.models.jobs import BackgroundJob
from app.models.local_models import ModelInstallation
from app.repositories.jobs import now, recover
from app.repositories.local_models import acquire_use, checkpoint, claim_model_job, finish_model_job
from app.services.local_models import (
    request_delete,
    request_download,
    run_model_job,
    transition_job,
)

# Open-model tests run with EXPERIMENTAL_OPEN_MODELS on (ARA-090).
pytestmark = [pytest.mark.integration, pytest.mark.open_models]
KEY = "ifm-k2-horizon-3.7b"


@pytest.mark.parametrize("new_state", ["verifying", "ready"])
async def test_superseded_failed_retry_cannot_mutate_new_installation(resources, new_state):
    first = await request_download(resources, KEY, uuid4())
    token = await claim_model_job(resources.sessions, first.id, 1)
    await finish_model_job(
        resources.sessions,
        first.id,
        1,
        token,
        error=AppError(409, "MODEL_VALIDATION_FAILED", "Fixture validation failure."),
    )
    newer = await request_download(resources, KEY, uuid4())
    new_token = await claim_model_job(resources.sessions, newer.id, 1)
    await checkpoint(resources.sessions, newer.id, 1, new_token, stage="verifying")
    if new_state == "ready":
        await finish_model_job(resources.sessions, newer.id, 1, new_token)
    with pytest.raises(AppError) as error:
        await transition_job(resources, first.id, "retry", uuid4())
    assert error.value.status_code == 409 and error.value.code == "MODEL_OPERATION_SUPERSEDED"
    async with resources.sessions() as session:
        installation = await session.get(ModelInstallation, KEY)
        assert installation.state == new_state and installation.active_job_id == newer.id
        assert (await session.get(BackgroundJob, first.id)).state == "failed"
        assert (await session.get(BackgroundJob, newer.id)).stage == (
            "completed" if new_state == "ready" else "verifying"
        )


async def test_verification_wins_pause_capability_race_and_retains_exclusive_ownership(
    resources, monkeypatch
):
    job = await request_download(resources, KEY, uuid4())
    token = await claim_model_job(resources.sessions, job.id, 1)
    await checkpoint(resources.sessions, job.id, 1, token, stage="downloading")

    async def supports_pause(self):
        assert await checkpoint(resources.sessions, job.id, 1, token, stage="verifying")
        return True

    async def never_pause(self, operation_id):
        raise AssertionError("Completed pull must not release active verification ownership")

    monkeypatch.setattr(OllamaRuntime, "supports_pause", supports_pause)
    monkeypatch.setattr(OllamaRuntime, "pause", never_pause)
    with pytest.raises(AppError) as error:
        await transition_job(resources, job.id, "pause", uuid4())
    assert error.value.code == "JOB_NOT_PAUSABLE"
    with pytest.raises(AppError):
        await request_delete(resources, "qwen3.8-27b", uuid4())
    async with resources.sessions() as session:
        saved = await session.get(BackgroundJob, job.id)
        assert saved.state == "processing" and saved.stage == "verifying"
        assert saved.lease_token == token


async def test_pause_wins_verification_admission_and_ownership_lasts_until_ack(
    resources, monkeypatch
):
    job = await request_download(resources, KEY, uuid4())
    token = await claim_model_job(resources.sessions, job.id, 1)
    await checkpoint(resources.sessions, job.id, 1, token, stage="downloading")
    async with resources.sessions() as session, session.begin():
        session.add(ModelInstallation(model_key="qwen3.8-27b", state="ready", weights_present=True))

    async def supports_pause(self):
        return True

    async def pause(self, operation_id):
        # An actor must receive refusal before it starts any native verification probe.
        assert not await checkpoint(resources.sessions, job.id, 1, token, stage="verifying")
        with pytest.raises(AppError) as error:
            await acquire_use(resources.sessions, "qwen3.8-27b")
        assert error.value.code == "LOCAL_MODEL_BUSY"
        with pytest.raises(AppError):
            await request_delete(resources, "qwen3.8-27b", uuid4())
        async with resources.sessions() as session:
            saved = await session.get(BackgroundJob, job.id)
            assert saved.state == "processing" and saved.stage == "pausing"
            assert saved.lease_token == token

    monkeypatch.setattr(OllamaRuntime, "supports_pause", supports_pause)
    monkeypatch.setattr(OllamaRuntime, "pause", pause)
    paused = await transition_job(resources, job.id, "pause", uuid4())
    assert paused.state == "paused"


@pytest.mark.parametrize("desired", ["ready", "paused"])
async def test_worker_and_fresh_runtime_restart_settles_tombstone_and_resumes(resources, desired):
    import json

    spec = local_spec(KEY)
    job = await request_download(resources, KEY, uuid4())
    token = await claim_model_job(resources.sessions, job.id, 1)
    await checkpoint(
        resources.sessions, job.id, 1, token, stage="downloading", completed=10, total=100
    )
    async with resources.sessions() as session, session.begin():
        saved = await session.get(BackgroundJob, job.id)
        old_operation = str(saved.runtime_operation_id)
        saved.lease_expires_at = now() - timedelta(seconds=1)
        installation = await session.get(ModelInstallation, KEY)
        installation.desired_state = desired
        if desired == "paused":
            installation.state = saved.stage = "pausing"
    await recover(resources.sessions)
    token = await claim_model_job(resources.sessions, job.id, 2)
    present = False
    tombstones = set()
    pulls = []

    def handler(request):
        nonlocal present
        if request.url.path == "/api/tags":
            return httpx.Response(
                200,
                json={
                    "models": [{"name": spec.model_id, "digest": spec.expected_digest}]
                    if present
                    else []
                },
            )
        if request.url.path == "/api/ara/capabilities":
            return httpx.Response(200, json={"protocol_version": 1, "pull_control": True})
        if request.url.path.endswith("/pause"):
            # Fresh daemon has no old operation; atomic tombstone fences its late delivery.
            tombstones.add(request.url.path.split("/")[-2])
            return httpx.Response(200, json={"state": "paused"})
        if request.url.path == "/api/ara/pull":
            operation = json.loads(request.content)["operation_id"]
            if operation in tombstones:
                return httpx.Response(409, json={"error": "operation was already settled"})
            pulls.append(operation)
            present = True
            return httpx.Response(
                200, text='{"status":"success","digest":"layer","completed":100,"total":100}\n'
            )
        if request.url.path == "/api/show":
            return httpx.Response(
                200, json={"template": "{{ .Messages }}", "capabilities": ["completion"]}
            )
        if request.url.path == "/api/version":
            return httpx.Response(200, json={"version": "fresh-runtime"})
        body = json.loads(request.content)
        content = '{"ok":true}' if body.get("format") else "OK"
        return httpx.Response(
            200,
            text=json.dumps({"done": True, "done_reason": "stop", "message": {"content": content}})
            + "\n",
        )

    await resources.http.aclose()
    resources.http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    await run_model_job(resources, job.id, 2, token)
    assert old_operation in tombstones
    async with resources.sessions() as session:
        current = await session.get(BackgroundJob, job.id)
        assert current.state == ("completed" if desired == "ready" else "paused")
        assert current.payload.get("recovery_operation_id") is None
    if desired == "paused":
        assert not pulls
        resumed = await transition_job(resources, job.id, "resume", uuid4())
        token = await claim_model_job(resources.sessions, job.id, resumed.generation)
        await run_model_job(resources, job.id, resumed.generation, token)
    assert len(pulls) == 1 and pulls[0] != old_operation
    async with resources.sessions() as session:
        assert (await session.get(ModelInstallation, KEY)).state == "ready"


async def test_recovery_pause_settles_current_and_abandoned_operations_before_releasing(
    resources, monkeypatch
):
    job = await request_download(resources, KEY, uuid4())
    token = await claim_model_job(resources.sessions, job.id, 1)
    await checkpoint(resources.sessions, job.id, 1, token, stage="downloading")
    async with resources.sessions() as session, session.begin():
        saved = await session.get(BackgroundJob, job.id)
        old_operation = str(saved.runtime_operation_id)
        saved.lease_expires_at = now() - timedelta(seconds=1)
    await recover(resources.sessions)
    token = await claim_model_job(resources.sessions, job.id, 2)
    async with resources.sessions() as session:
        current_operation = str((await session.get(BackgroundJob, job.id)).runtime_operation_id)
    calls = []

    async def supports_pause(self):
        return True

    async def pause(self, operation_id):
        calls.append(operation_id)
        async with resources.sessions() as session:
            saved = await session.get(BackgroundJob, job.id)
            assert saved.state == "processing" and saved.lease_token == token

    monkeypatch.setattr(OllamaRuntime, "supports_pause", supports_pause)
    monkeypatch.setattr(OllamaRuntime, "pause", pause)
    paused = await transition_job(resources, job.id, "pause", uuid4())
    assert calls == [current_operation, old_operation]
    assert paused.state == "paused"


async def test_pending_pause_refuses_new_transfer_admission(resources):
    job = await request_download(resources, KEY, uuid4())
    token = await claim_model_job(resources.sessions, job.id, 1)
    async with resources.sessions() as session, session.begin():
        row = await session.get(ModelInstallation, KEY)
        row.desired_state, row.state = "paused", "pausing"
    assert not await checkpoint(resources.sessions, job.id, 1, token, stage="downloading")


@pytest.mark.parametrize("outage_oldest", [False, True])
async def test_repeated_restart_retains_every_unsettled_operation_until_all_ack(
    resources, outage_oldest
):
    job = await request_download(resources, KEY, uuid4())
    token = await claim_model_job(resources.sessions, job.id, 1)
    await checkpoint(resources.sessions, job.id, 1, token, stage="downloading")
    identities = []
    for generation in (1, 2, 3):
        async with resources.sessions() as session, session.begin():
            current = await session.get(BackgroundJob, job.id)
            identities.append(str(current.runtime_operation_id))
            current.stage = "pausing"
            current.lease_expires_at = now() - timedelta(seconds=1)
            row = await session.get(ModelInstallation, KEY)
            row.desired_state, row.state = "paused", "pausing"
        await recover(resources.sessions)
        token = await claim_model_job(resources.sessions, job.id, generation + 1)
    async with resources.sessions() as session:
        identities.append(str((await session.get(BackgroundJob, job.id)).runtime_operation_id))
    acknowledged = []

    def handler(request):
        if request.url.path == "/api/ara/capabilities":
            return httpx.Response(200, json={"protocol_version": 1, "pull_control": True})
        operation = request.url.path.split("/")[-2]
        if outage_oldest and operation == identities[0]:
            raise httpx.ConnectError("fixture oldest operation unavailable")
        acknowledged.append(operation)
        return httpx.Response(200, json={"state": "paused"})

    await resources.http.aclose()
    resources.http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    await run_model_job(resources, job.id, 4, token)
    if outage_oldest:
        async with resources.sessions() as session:
            current = await session.get(BackgroundJob, job.id)
            assert current.state == "processing" and current.stage == "pausing"
            assert current.lease_token == token
        outage_oldest = False
        await run_model_job(resources, job.id, 4, token)
    assert set(identities) <= set(acknowledged)
    async with resources.sessions() as session:
        current = await session.get(BackgroundJob, job.id)
        assert current.state == "paused"
        assert not current.payload.get("_recovery_operation_ids")
        assert current.payload.get("recovery_operation_id") is None


async def test_queued_recovery_pause_refreshes_current_operation_claimed_during_capability_http(
    resources, monkeypatch
):
    job = await request_download(resources, KEY, uuid4())
    token = await claim_model_job(resources.sessions, job.id, 1)
    await checkpoint(resources.sessions, job.id, 1, token, stage="downloading")
    async with resources.sessions() as session, session.begin():
        saved = await session.get(BackgroundJob, job.id)
        abandoned = str(saved.runtime_operation_id)
        saved.lease_expires_at = now() - timedelta(seconds=1)
    await recover(resources.sessions)
    newly_claimed = []
    acknowledged = []

    async def supports_pause(self):
        token = await claim_model_job(resources.sessions, job.id, 2)
        assert token is not None
        async with resources.sessions() as session:
            newly_claimed.append(
                str((await session.get(BackgroundJob, job.id)).runtime_operation_id)
            )
        return True

    async def pause(self, operation_id):
        acknowledged.append(operation_id)

    monkeypatch.setattr(OllamaRuntime, "supports_pause", supports_pause)
    monkeypatch.setattr(OllamaRuntime, "pause", pause)
    paused = await transition_job(resources, job.id, "pause", uuid4())
    assert paused.state == "paused"
    assert acknowledged == [newly_claimed[0], abandoned]


async def test_inventory_success_recovery_still_settles_all_predecessors_before_native_probe(
    resources,
):
    import json

    spec = local_spec(KEY)
    job = await request_download(resources, KEY, uuid4())
    token = await claim_model_job(resources.sessions, job.id, 1)
    await checkpoint(resources.sessions, job.id, 1, token, stage="downloading")
    async with resources.sessions() as session, session.begin():
        current = await session.get(BackgroundJob, job.id)
        predecessor = str(current.runtime_operation_id)
        current.lease_expires_at = now() - timedelta(seconds=1)
    await recover(resources.sessions)
    token = await claim_model_job(resources.sessions, job.id, 2)
    acknowledged = []

    def handler(request):
        if request.url.path == "/api/ara/capabilities":
            return httpx.Response(200, json={"protocol_version": 1, "pull_control": True})
        if request.url.path.endswith("/pause"):
            acknowledged.append(request.url.path.split("/")[-2])
            return httpx.Response(200, json={"state": "paused"})
        if request.url.path == "/api/tags":
            return httpx.Response(
                200, json={"models": [{"name": spec.model_id, "digest": spec.expected_digest}]}
            )
        if request.url.path == "/api/show":
            return httpx.Response(
                200, json={"template": "{{ .Messages }}", "capabilities": ["completion"]}
            )
        if request.url.path == "/api/version":
            return httpx.Response(200, json={"version": "fixture"})
        assert predecessor in acknowledged, "Prior operation must settle before native inference"
        body = json.loads(request.content)
        content = '{"ok":true}' if body.get("format") else "OK"
        return httpx.Response(
            200,
            text=json.dumps({"done": True, "done_reason": "stop", "message": {"content": content}})
            + "\n",
        )

    await resources.http.aclose()
    resources.http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    await run_model_job(resources, job.id, 2, token)
    async with resources.sessions() as session:
        current = await session.get(BackgroundJob, job.id)
        assert current.state == "completed"
        assert not current.payload.get("_recovery_operation_ids")
