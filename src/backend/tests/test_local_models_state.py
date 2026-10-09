from uuid import uuid4

import pytest

from app.core.errors import AppError
from app.integrations.model_catalog import local_spec

pytestmark = pytest.mark.integration


async def test_request_identity_and_queued_pause_resume_survive_new_service(resources):
    from app.models.jobs import BackgroundJob
    from app.models.local_models import ModelInstallation
    from app.services.local_models import request_download, transition_job

    key = "ifm-k2-horizon-3.7b"
    identity = uuid4()
    first = await request_download(resources, key, identity)
    assert (await request_download(resources, key, identity)).id == first.id
    with pytest.raises(AppError) as error:
        await request_download(resources, "ifm-k2-horizon-7b", identity)
    assert error.value.code == "MODEL_REQUEST_CONFLICT"
    paused = await transition_job(resources, first.id, "pause", uuid4())
    assert paused.state == "paused"
    async with resources.sessions() as session:
        installation = await session.get(ModelInstallation, key)
        assert installation.state == "paused"
        assert (await session.get(BackgroundJob, first.id)).attempts == 0
    resumed = await transition_job(resources, first.id, "resume", uuid4())
    assert resumed.state == "queued" and resumed.generation == 2
    assert resumed.attempts == 0


async def test_missing_models_are_catalogued_without_hosted_credentials(resources):
    from app.services.local_models import ensure_local_available, list_local_models

    models = await list_local_models(resources, inspect_runtime=False)
    assert len(models) == 6
    assert all(model.installation.state == "missing" for model in models)
    with pytest.raises(AppError) as error:
        await ensure_local_available(resources, local_spec("ifm-k2-horizon-3.7b").key)
    assert error.value.code == "LOCAL_MODEL_NOT_READY"


async def test_model_download_lane_and_generation_lease_are_durable(resources):
    from app.models.local_models import ModelInstallation
    from app.repositories.local_models import acquire_use, claim_model_job, release_use
    from app.services.local_models import request_download

    first = await request_download(resources, "ifm-k2-horizon-3.7b", uuid4())
    second = await request_download(resources, "ifm-k2-horizon-7b", uuid4())
    token = await claim_model_job(resources.sessions, first.id, 1)
    assert token is not None
    assert await claim_model_job(resources.sessions, second.id, 1) is None
    assert await claim_model_job(resources.sessions, first.id, 1) is None
    async with resources.sessions() as session, session.begin():
        installation = await session.get(ModelInstallation, "qwen3.8-27b")
        if installation is None:
            installation = ModelInstallation(model_key="qwen3.8-27b")
            session.add(installation)
        installation.state = "ready"
        installation.weights_present = True
    with pytest.raises(AppError) as error:
        await acquire_use(resources.sessions, "qwen3.8-27b")
    assert error.value.code == "LOCAL_MODEL_BUSY"
    from app.models.jobs import BackgroundJob

    async with resources.sessions() as session, session.begin():
        (await session.get(BackgroundJob, first.id)).state = "failed"
    lease = await acquire_use(resources.sessions, "qwen3.8-27b")
    with pytest.raises(AppError) as error:
        await acquire_use(resources.sessions, "qwen3.8-27b")
    assert error.value.code == "LOCAL_MODEL_BUSY"
    assert await release_use(resources.sessions, lease)


async def test_recovery_preserves_manual_pause_and_transfer_retry_budget(resources):
    from datetime import timedelta

    from app.models.jobs import BackgroundJob
    from app.models.local_models import ModelInstallation
    from app.repositories.jobs import now, recover
    from app.repositories.local_models import claim_model_job
    from app.services.local_models import request_download, transition_job

    job = await request_download(resources, "ifm-k2-horizon-3.7b", uuid4())
    await transition_job(resources, job.id, "pause", uuid4())
    await recover(resources.sessions)
    async with resources.sessions() as session:
        assert (await session.get(BackgroundJob, job.id)).state == "paused"
    for _ in range(4):
        resumed = await transition_job(resources, job.id, "resume", uuid4())
        token = await claim_model_job(resources.sessions, job.id, resumed.generation)
        assert token is not None
        async with resources.sessions() as session, session.begin():
            current = await session.get(BackgroundJob, job.id)
            current.lease_expires_at = now() - timedelta(seconds=1)
        await recover(resources.sessions)
        async with resources.sessions() as session:
            current = await session.get(BackgroundJob, job.id)
            assert current.state == "queued"
            assert current.attempts == 0
            assert (await session.get(ModelInstallation, job.model_key)).state == "queued"
        await transition_job(resources, job.id, "pause", uuid4())


async def test_delete_rejects_generation_and_preserves_defaults_and_history(resources):
    from app.models.jobs import BackgroundJob
    from app.models.local_models import ModelInstallation
    from app.models.research import ModelConfiguration
    from app.repositories.local_models import acquire_use, release_use
    from app.services.local_models import request_delete

    key = "ifm-k2-horizon-3.7b"
    async with resources.sessions() as session, session.begin():
        session.add(ModelInstallation(model_key=key, state="ready", weights_present=True))
        session.add(
            ModelConfiguration(
                key="defaults", value={"default_model": key, "reasoning_effort": "default"}
            )
        )
    token = await acquire_use(resources.sessions, key)
    with pytest.raises(AppError) as error:
        await request_delete(resources, key, uuid4())
    assert error.value.code == "LOCAL_MODEL_BUSY"
    await release_use(resources.sessions, token)
    identity = uuid4()
    job = await request_delete(resources, key, identity)
    assert (await request_delete(resources, key, identity)).id == job.id
    async with resources.sessions() as session:
        assert (await session.get(ModelConfiguration, "defaults")).value["default_model"] == key
        assert (await session.get(BackgroundJob, job.id)).kind == "model_delete"


async def test_actor_recovers_inventory_before_pull_and_requires_verified_weights(resources):
    import httpx

    from app.models.jobs import BackgroundJob
    from app.models.local_models import ModelInstallation
    from app.repositories.local_models import claim_model_job
    from app.services.local_models import request_download, run_model_job

    spec = local_spec("ifm-k2-horizon-3.7b")
    calls = []

    def handler(request):
        calls.append(request.url.path)
        if request.url.path == "/api/tags":
            return httpx.Response(
                200, json={"models": [{"name": spec.model_id, "digest": spec.expected_digest}]}
            )
        if request.url.path == "/api/show":
            return httpx.Response(
                200, json={"template": "{{ .Messages }}", "capabilities": ["completion"]}
            )
        if request.url.path == "/api/version":
            return httpx.Response(200, json={"version": "test"})
        if request.url.path == "/api/chat":
            return httpx.Response(
                200, text='{"done":true,"done_reason":"stop","message":{"content":"OK"}}\n'
            )
        raise AssertionError(request.url)

    await resources.http.aclose()
    resources.http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    job = await request_download(resources, spec.key, uuid4())
    token = await claim_model_job(resources.sessions, job.id, job.generation)
    await run_model_job(resources, job.id, job.generation, token)
    assert "/api/ara/pull" not in calls and "/api/pull" not in calls
    async with resources.sessions() as session:
        installation = await session.get(ModelInstallation, spec.key)
        assert installation.state == "ready" and installation.weights_present
        assert installation.validation["runtime_version"] == "test"
        assert (await session.get(BackgroundJob, job.id)).state == "completed"


async def test_verification_failure_retains_weights(resources):
    import httpx

    from app.models.local_models import ModelInstallation
    from app.repositories.local_models import claim_model_job
    from app.services.local_models import request_download, run_model_job

    spec = local_spec("ifm-k2-horizon-3.7b")

    def handler(request):
        if request.url.path == "/api/tags":
            return httpx.Response(
                200, json={"models": [{"name": spec.model_id, "digest": spec.expected_digest}]}
            )
        return httpx.Response(200, json={})

    await resources.http.aclose()
    resources.http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    job = await request_download(resources, spec.key, uuid4())
    token = await claim_model_job(resources.sessions, job.id, job.generation)
    await run_model_job(resources, job.id, job.generation, token)
    async with resources.sessions() as session:
        installation = await session.get(ModelInstallation, spec.key)
        assert installation.state == "failed" and installation.weights_present
        assert installation.error_code == "MODEL_VALIDATION_FAILED"


async def test_dispatcher_routes_model_and_local_generation_to_dedicated_lanes(resources):
    from app.repositories.jobs import enqueue
    from app.services.dispatcher import dispatch_once
    from app.services.local_models import request_download

    async with resources.sessions() as session, session.begin():
        local = await enqueue(session, kind="summary", payload={"model": "qwen3.8-27b"})
        hosted = await enqueue(session, kind="summary", payload={"model": "gpt-5.6-luna"})
    model = await request_download(resources, "ifm-k2-horizon-3.7b", uuid4())
    ordinary, downloads, generations = [], [], []
    await dispatch_once(
        resources.sessions,
        lambda *args: ordinary.append(args),
        model_publish=lambda *args: downloads.append(args),
        local_publish=lambda *args: generations.append(args),
    )
    assert ordinary == [(str(hosted.id), 1)]
    assert downloads == [(str(model.id), 1)]
    assert generations == [(str(local.id), 1)]


async def test_progress_layers_persist_across_transfer_attempts_and_fence_expired_owner(resources):
    from datetime import timedelta

    from app.models.jobs import BackgroundJob
    from app.repositories.jobs import now, recover
    from app.repositories.local_models import checkpoint, claim_model_job
    from app.services.local_models import request_download

    job = await request_download(resources, "ifm-k2-horizon-3.7b", uuid4())
    first_token = await claim_model_job(resources.sessions, job.id, 1)
    assert await checkpoint(
        resources.sessions,
        job.id,
        1,
        first_token,
        completed=12,
        total=30,
        layers={"a": [4, 10], "b": [8, 20]},
    )
    async with resources.sessions() as session, session.begin():
        current = await session.get(BackgroundJob, job.id)
        current.lease_expires_at = now() - timedelta(seconds=1)
    assert not await checkpoint(resources.sessions, job.id, 1, first_token, completed=30, total=30)
    await recover(resources.sessions)
    async with resources.sessions() as session:
        recovered = await session.get(BackgroundJob, job.id)
        assert recovered.payload["_pull_layers"] == {"a": [4, 10], "b": [8, 20]}
        second_generation = recovered.generation
    second_token = await claim_model_job(resources.sessions, job.id, second_generation)
    assert second_token != first_token
    assert not await checkpoint(resources.sessions, job.id, 1, first_token, completed=30, total=30)


async def test_processing_pause_is_acknowledged_after_outage_without_claiming_fake_paused(
    resources,
):
    import httpx

    from app.models.jobs import BackgroundJob
    from app.models.local_models import ModelInstallation
    from app.repositories.local_models import claim_model_job
    from app.services.local_models import request_download, transition_job

    requests = []
    outage = True

    def handler(request):
        requests.append(request.url.path)
        if request.url.path == "/api/ara/capabilities":
            return httpx.Response(200, json={"protocol_version": 1, "pull_control": True})
        if outage:
            raise httpx.ConnectError("fixture outage")
        return httpx.Response(200, json={"state": "paused"})

    await resources.http.aclose()
    resources.http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    job = await request_download(resources, "ifm-k2-horizon-3.7b", uuid4())
    token = await claim_model_job(resources.sessions, job.id, 1)
    identity = uuid4()
    with pytest.raises(AppError):
        await transition_job(resources, job.id, "pause", identity)
    async with resources.sessions() as session:
        row = await session.get(ModelInstallation, job.model_key)
        assert row.state == "pausing" and row.desired_state == "paused"
        current = await session.get(BackgroundJob, job.id)
        assert current.state == "processing" and current.lease_token == token
    outage = False
    replayed = await transition_job(resources, job.id, "pause", identity)
    assert replayed.state == "paused"
    async with resources.sessions() as session:
        assert (await session.get(ModelInstallation, job.model_key)).state == "paused"


async def test_concurrent_download_identity_creates_only_one_operation(resources):
    import asyncio

    from sqlalchemy import func, select

    from app.models.jobs import BackgroundJob
    from app.services.local_models import request_download

    identity = uuid4()
    first, second = await asyncio.gather(
        request_download(resources, "ifm-k2-horizon-3.7b", identity),
        request_download(resources, "ifm-k2-horizon-3.7b", identity),
    )
    assert first.id == second.id
    async with resources.sessions() as session:
        assert await session.scalar(select(func.count()).select_from(BackgroundJob)) == 1


async def test_only_actual_transfer_failures_spend_retry_budget(resources):
    import httpx

    from app.models.jobs import BackgroundJob
    from app.repositories.local_models import checkpoint, claim_model_job, finish_model_job
    from app.services.local_models import request_download, settle_model_failure, transition_job

    job = await request_download(resources, "ifm-k2-horizon-3.7b", uuid4())
    token = await claim_model_job(resources.sessions, job.id, 1)
    await finish_model_job(
        resources.sessions,
        job.id,
        1,
        token,
        error=AppError(503, "LOCAL_RUNTIME_UNAVAILABLE", "Runtime unavailable."),
    )
    async with resources.sessions() as session:
        current = await session.get(BackgroundJob, job.id)
        assert current.state == "queued" and current.attempts == 0

    def handler(request):
        if request.url.path == "/api/ara/capabilities":
            return httpx.Response(200, json={"protocol_version": 1, "pull_control": True})
        return httpx.Response(200, json={"state": "paused"})

    await resources.http.aclose()
    resources.http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    await transition_job(resources, job.id, "pause", uuid4())
    for attempt in range(1, 4):
        resumed = await transition_job(resources, job.id, "resume", uuid4())
        token = await claim_model_job(resources.sessions, job.id, resumed.generation)
        assert token is not None
        await checkpoint(resources.sessions, job.id, resumed.generation, token, stage="downloading")
        await settle_model_failure(
            resources,
            job.id,
            resumed.generation,
            token,
            AppError(504, "MODEL_PULL_STALLED", "Transfer stalled."),
        )
        async with resources.sessions() as session:
            current = await session.get(BackgroundJob, job.id)
            assert current.attempts == attempt
            assert current.state == ("failed" if attempt == 3 else "queued")
        if attempt < 3:
            await transition_job(resources, job.id, "pause", uuid4())


async def test_recovered_pausing_job_keeps_pausing_until_runtime_ack_and_operation_history(
    resources,
):
    from datetime import timedelta

    import httpx

    from app.models.jobs import BackgroundJob
    from app.models.local_models import ModelInstallation
    from app.repositories.jobs import now, recover
    from app.repositories.local_models import claim_model_job
    from app.services.local_models import request_download, run_model_job

    job = await request_download(resources, "ifm-k2-horizon-3.7b", uuid4())
    first_token = await claim_model_job(resources.sessions, job.id, 1)
    async with resources.sessions() as session, session.begin():
        current = await session.get(BackgroundJob, job.id)
        old_operation = str(current.runtime_operation_id)
        current.stage = "pausing"
        current.lease_expires_at = now() - timedelta(seconds=1)
        installation = await session.get(ModelInstallation, job.model_key)
        installation.desired_state, installation.state = "paused", "pausing"
    await recover(resources.sessions)
    second_token = await claim_model_job(resources.sessions, job.id, 2)
    assert second_token and second_token != first_token
    async with resources.sessions() as session:
        current = await session.get(BackgroundJob, job.id)
        assert current.stage == "pausing"
        assert len(current.payload["_operation_history"]) == 2
        assert current.payload["_operation_history"][0]["operation_id"] == old_operation
        assert (await session.get(ModelInstallation, job.model_key)).state == "pausing"
    paths = []

    def handler(request):
        paths.append(request.url.path)
        if request.url.path == "/api/ara/capabilities":
            return httpx.Response(200, json={"protocol_version": 1, "pull_control": True})
        return httpx.Response(200, json={"state": "paused"})

    await resources.http.aclose()
    resources.http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    await run_model_job(resources, job.id, 2, second_token)
    assert f"/api/ara/pulls/{old_operation}/pause" in paths
    assert "/api/ara/pull" not in paths
    async with resources.sessions() as session:
        assert (await session.get(BackgroundJob, job.id)).state == "paused"


async def test_deletion_rejects_active_other_model_maintenance(resources):
    from app.repositories.local_models import claim_model_job
    from app.services.local_models import request_delete, request_download

    job = await request_download(resources, "ifm-k2-horizon-3.7b", uuid4())
    assert await claim_model_job(resources.sessions, job.id, 1)
    with pytest.raises(AppError) as error:
        await request_delete(resources, "qwen3.8-27b", uuid4())
    assert error.value.code == "LOCAL_MODEL_BUSY"


async def test_progress_rollback_and_context_allocation_are_reported_honestly(resources):
    from app.models.jobs import BackgroundJob
    from app.models.local_models import ModelInstallation
    from app.repositories.local_models import checkpoint, claim_model_job
    from app.services.local_models import list_local_models, request_download

    resources.settings.ollama_context_window = 16384
    assert all(
        model.context_window == 16384
        for model in await list_local_models(resources, inspect_runtime=False)
    )
    job = await request_download(resources, "ifm-k2-horizon-3.7b", uuid4())
    token = await claim_model_job(resources.sessions, job.id, 1)
    await checkpoint(resources.sessions, job.id, 1, token, completed=90, total=100)
    await checkpoint(resources.sessions, job.id, 1, token, completed=20, total=100)
    async with resources.sessions() as session:
        assert (await session.get(BackgroundJob, job.id)).completed_bytes == 20
        assert (await session.get(ModelInstallation, job.model_key)).completed_bytes == 20


async def test_heartbeat_outage_cancels_http_and_managed_operation(resources, monkeypatch):
    import asyncio

    import httpx

    from app.repositories import jobs
    from app.services.local_models import execute_model_attempt, request_download

    calls = []
    cancelled = []

    async def handler(request):
        calls.append(request.url.path)
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": []})
        if request.url.path == "/api/ara/capabilities":
            return httpx.Response(200, json={"protocol_version": 1, "pull_control": True})
        if request.url.path == "/api/ara/pull":
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.append(True)
                raise
        return httpx.Response(200, json={"state": "paused"})

    async def lost_heartbeat(*args, **kwargs):
        raise RuntimeError("fixture PostgreSQL heartbeat outage")

    monkeypatch.setattr(jobs, "heartbeat", lost_heartbeat)
    await resources.http.aclose()
    resources.http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    job = await request_download(resources, "ifm-k2-horizon-3.7b", uuid4())
    async with asyncio.timeout(12):
        await execute_model_attempt(resources, job.id, 1)
    assert cancelled == [True]
    assert any(path.startswith("/api/ara/pulls/") and path.endswith("/pause") for path in calls)


async def test_latest_migration_is_ready_with_real_services(resources):
    from app.services.health import readiness

    checks = await readiness(resources)
    assert checks == {"database": "ok", "storage": "ok", "redis": "ok"}


async def test_attempt_deadline_stops_managed_transfer_before_requeue(resources):
    import asyncio

    import httpx

    from app.models.jobs import BackgroundJob
    from app.repositories.local_models import claim_model_job
    from app.services.local_models import request_download, run_model_job

    resources.settings.ollama_pull_timeout_seconds = 0.05
    calls = []

    async def handler(request):
        calls.append(request.url.path)
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": []})
        if request.url.path == "/api/ara/capabilities":
            return httpx.Response(200, json={"protocol_version": 1, "pull_control": True})
        if request.url.path == "/api/ara/pull":
            await asyncio.Event().wait()
        return httpx.Response(200, json={"state": "paused"})

    await resources.http.aclose()
    resources.http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    job = await request_download(resources, "ifm-k2-horizon-3.7b", uuid4())
    token = await claim_model_job(resources.sessions, job.id, 1)
    await run_model_job(resources, job.id, 1, token)
    assert any(path.startswith("/api/ara/pulls/") and path.endswith("/pause") for path in calls)
    async with resources.sessions() as session:
        current = await session.get(BackgroundJob, job.id)
        assert current.state == "queued" and current.error_code == "MODEL_ATTEMPT_TIMEOUT"


@pytest.mark.parametrize("pause_outage", [False, True])
async def test_pausing_recovered_queued_transfer_requires_old_operation_ack(
    resources, pause_outage
):
    from datetime import timedelta

    import httpx

    from app.models.jobs import BackgroundJob
    from app.repositories.jobs import now, recover
    from app.repositories.local_models import checkpoint, claim_model_job
    from app.services.local_models import request_download, transition_job

    job = await request_download(resources, "ifm-k2-horizon-3.7b", uuid4())
    token = await claim_model_job(resources.sessions, job.id, 1)
    await checkpoint(resources.sessions, job.id, 1, token, stage="downloading")
    async with resources.sessions() as session, session.begin():
        current = await session.get(BackgroundJob, job.id)
        operation = str(current.runtime_operation_id)
        current.lease_expires_at = now() - timedelta(seconds=1)
    await recover(resources.sessions)
    paths = []

    def handler(request):
        paths.append(request.url.path)
        if request.url.path == "/api/ara/capabilities":
            return httpx.Response(200, json={"protocol_version": 1, "pull_control": True})
        if pause_outage:
            raise httpx.ConnectError("fixture outage")
        return httpx.Response(200, json={"state": "paused"})

    await resources.http.aclose()
    resources.http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    identity = uuid4()
    if pause_outage:
        with pytest.raises(AppError):
            await transition_job(resources, job.id, "pause", identity)
        pause_outage = False
    paused = await transition_job(resources, job.id, "pause", identity)
    assert paused.state == "paused"
    assert f"/api/ara/pulls/{operation}/pause" in paths
