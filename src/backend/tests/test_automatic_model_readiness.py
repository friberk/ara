"""Automatic retained-weight preparation uses real isolated PostgreSQL ownership."""

import asyncio
import json
from datetime import timedelta
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import func, select

from app.core.errors import AppError
from app.integrations.model_catalog import local_spec
from app.main import create_app
from app.models.jobs import BackgroundJob, JobOutbox
from app.models.local_models import ModelInstallation
from app.repositories.jobs import enqueue, now, recover
from app.repositories.local_models import acquire_use, claim_model_job, release_use
from app.services import local_models

# Open-model tests run with EXPERIMENTAL_OPEN_MODELS on (ARA-090).
pytestmark = [pytest.mark.integration, pytest.mark.open_models]
KEY = "ifm-k2-horizon-7b"


def validation(key=KEY):
    return {
        "digest": local_spec(key).expected_digest,
        "context_window": 8192,
        "runtime_version": "fixture-current",
        "thinking_schema": 1,
        "thinking": {"values": [False, True, "low", "medium", "high"], "default": "high"},
        "think_mapping": {
            "none": False,
            "on": True,
            "low": "low",
            "medium": "medium",
            "high": "high",
        },
        "reasoning_efforts": ["default", "none", "on", "low", "medium", "high"],
        "supports_streaming": True,
        "supports_structured_output": True,
    }


async def seed(
    resources, *, key=KEY, stale="runtime", state="ready", desired="ready", weights=True
):
    data = validation(key)
    if stale == "runtime":
        data["runtime_version"] = "fixture-old"
    elif stale == "schema":
        data.pop("thinking_schema")
    elif stale == "context":
        data["context_window"] = 4096
    async with resources.sessions() as session, session.begin():
        session.add(
            ModelInstallation(
                model_key=key,
                state=state,
                desired_state=desired,
                weights_present=weights,
                digest=local_spec(key).expected_digest,
                validation=data,
            )
        )


async def runtime_fixture(resources):
    state = {
        "present": True,
        "version": "fixture-current",
        "outage": False,
        "bad_probe": False,
        "extra": [],
        "before_version": None,
    }
    calls = []

    async def provider(request):
        calls.append(request.url.path)
        if state["outage"]:
            raise httpx.ConnectError("synthetic optional runtime outage")
        spec = local_spec(KEY)
        if request.url.path == "/api/tags":
            return httpx.Response(
                200,
                json={
                    "models": [
                        *(
                            [{"name": spec.model_id, "digest": spec.expected_digest}]
                            if state["present"]
                            else []
                        ),
                        *state["extra"],
                    ]
                },
            )
        if request.url.path == "/api/version":
            if state["before_version"]:
                await state["before_version"]()
            return httpx.Response(200, json={"version": state["version"]})
        if request.url.path == "/api/show":
            return httpx.Response(
                200,
                json={
                    "template": "{{ .Messages }}",
                    "capabilities": ["completion"],
                    "thinking": {
                        "values": [False, True, "low", "medium", "high"],
                        "default": "high",
                    },
                    "model_info": {"fixture.context_length": 32768},
                },
            )
        if request.url.path == "/api/chat":
            body = json.loads(request.content)
            content = "" if state["bad_probe"] else '{"ok":true}' if "format" in body else "OK"
            result = {"done": True, "done_reason": "stop", "message": {"content": content}}
            return httpx.Response(200, text=json.dumps(result) + "\n")
        raise AssertionError(f"verify-only operation reached unexpected HTTP {request.url.path}")

    await resources.http.aclose()
    resources.http = httpx.AsyncClient(transport=httpx.MockTransport(provider))
    return state, calls


async def queued_verify(resources):
    async with resources.sessions() as session, session.begin():
        row = await session.get(ModelInstallation, KEY)
        job = await enqueue(
            session, kind="model_download", payload={"model_key": KEY, "verify_only": True}
        )
        job.model_key = KEY
        row.active_job_id, row.state = job.id, "queued"
        return job.id


async def jobs(resources):
    async with resources.sessions() as session:
        return list((await session.scalars(select(BackgroundJob))).all())


@pytest.mark.parametrize("stale", ["runtime", "schema", "context"])
async def test_given_stale_installed_7b_when_reconciled_then_one_durable_verify_is_queued(
    resources, stale
):
    await seed(resources, stale=stale)
    await runtime_fixture(resources)
    await local_models.reconcile_local_models(resources)
    await local_models.reconcile_local_models(resources)
    found = await jobs(resources)
    assert len(found) == 1
    assert found[0].kind == "model_download" and found[0].payload["verify_only"] is True
    async with resources.sessions() as session:
        row = await session.get(ModelInstallation, KEY)
        assert (
            row.state == "queued"
            and row.desired_state == "ready"
            and row.active_job_id == found[0].id
        )
        assert await session.scalar(select(func.count()).select_from(JobOutbox)) == 1


async def test_given_fresh_model_when_reconciled_then_no_job_and_no_get_side_effect(resources):
    await seed(resources, stale=None)
    _, calls = await runtime_fixture(resources)
    await local_models.reconcile_local_models(resources)
    assert await jobs(resources) == []
    listed = await local_models.list_local_models(resources)
    assert next(model for model in listed if model.key == KEY).status == "available"
    assert await jobs(resources) == []
    assert "/api/chat" not in calls


async def test_given_concurrent_inspection_when_reconciled_then_one_job_and_outbox(resources):
    await seed(resources)
    state, _ = await runtime_fixture(resources)
    all_inspected = asyncio.Event()
    inspected = 0

    async def synchronize():
        nonlocal inspected
        inspected += 1
        if inspected == 2:
            all_inspected.set()
        await all_inspected.wait()

    state["before_version"] = synchronize
    await asyncio.wait_for(
        asyncio.gather(
            local_models.reconcile_local_models(resources),
            local_models.reconcile_local_models(resources),
        ),
        timeout=5,
    )
    assert len(await jobs(resources)) == 1
    async with resources.sessions() as session:
        assert await session.scalar(select(func.count()).select_from(JobOutbox)) == 1


@pytest.mark.parametrize("change", ["validated", "newer_validation", "user_pause", "deleted"])
async def test_given_row_changes_during_inspection_when_reconciled_then_newer_intent_wins(
    resources, change
):
    await seed(resources)
    state, _ = await runtime_fixture(resources)

    async def mutate():
        async with resources.sessions() as session, session.begin():
            row = await session.get(ModelInstallation, KEY)
            if change in {"validated", "newer_validation"}:
                row.validation = {
                    **validation(),
                    **(
                        {"runtime_version": "newer-success"} if change == "newer_validation" else {}
                    ),
                }
            elif change == "user_pause":
                row.desired_state = "paused"
            else:
                row.state, row.desired_state, row.weights_present = "missing", "missing", False

    state["before_version"] = mutate
    await local_models.reconcile_local_models(resources)
    assert await jobs(resources) == []


@pytest.mark.parametrize(
    "state,desired,weights",
    [
        ("missing", "ready", False),
        ("paused", "paused", True),
        ("failed", "ready", True),
        ("ready", "missing", True),
        ("ready", "paused", True),
    ],
)
async def test_given_user_or_failed_installation_when_reconciled_then_intent_is_preserved(
    resources, state, desired, weights
):
    await seed(resources, state=state, desired=desired, weights=weights)
    _, calls = await runtime_fixture(resources)
    await local_models.reconcile_local_models(resources)
    assert await jobs(resources) == [] and calls == []


@pytest.mark.parametrize("busy", ["inference", "maintenance", "cleanup", "own_queued"])
async def test_given_busy_runtime_when_reconciled_then_preparation_is_deferred(resources, busy):
    await seed(resources)
    await runtime_fixture(resources)
    lease = None
    if busy == "inference":
        lease = await acquire_use(resources.sessions, KEY)
    else:
        async with resources.sessions() as session, session.begin():
            job = await enqueue(session, kind="model_download", payload={"model_key": KEY})
            job.model_key = KEY
            if busy == "maintenance":
                job.state, job.lease_expires_at = "processing", now() + timedelta(seconds=60)
            elif busy == "cleanup":
                job.payload = {**job.payload, "_recovery_operation_ids": [str(uuid4())]}
            else:
                (await session.get(ModelInstallation, KEY)).active_job_id = job.id
    before = len(await jobs(resources))
    await local_models.reconcile_local_models(resources)
    assert len(await jobs(resources)) == before
    if lease:
        await release_use(resources.sessions, lease)


@pytest.mark.parametrize("version", [None, "", " ", 1, True, {"bad": "version"}])
async def test_given_malformed_runtime_version_when_reconciled_then_no_target_is_invented(
    resources, version
):
    await seed(resources, stale="schema")
    state, _ = await runtime_fixture(resources)
    state["version"] = version
    await local_models.reconcile_local_models(resources)
    assert await jobs(resources) == []


async def test_given_runtime_outage_or_one_bad_model_when_reconciled_then_other_work_stays_safe(
    resources,
):
    await seed(resources)
    state, _ = await runtime_fixture(resources)
    state["outage"] = True
    await local_models.reconcile_local_models(resources)
    assert await jobs(resources) == []
    state["outage"] = False
    await seed(resources, key="qwen3.8-27b")
    state["extra"] = [{"name": local_spec("qwen3.8-27b").model_id, "digest": "drift"}]
    await local_models.reconcile_local_models(resources)
    assert [job.model_key for job in await jobs(resources)] == [KEY]


async def test_given_verify_only_claim_when_paused_then_verifying_stage_and_pause_is_refused(
    resources,
):
    await seed(resources)
    identifier = await queued_verify(resources)
    await runtime_fixture(resources)
    with pytest.raises(AppError) as paused:
        await local_models.transition_job(resources, identifier, "pause", uuid4())
    assert paused.value.code == "JOB_NOT_PAUSABLE"
    token = await claim_model_job(resources.sessions, identifier, 1)
    assert token
    async with resources.sessions() as session:
        job = await session.get(BackgroundJob, identifier)
        row = await session.get(ModelInstallation, KEY)
        assert job.stage == row.state == "verifying"
    with pytest.raises(AppError) as paused:
        await local_models.transition_job(resources, identifier, "pause", uuid4())
    assert paused.value.code == "JOB_NOT_PAUSABLE"


async def test_given_retained_verify_job_when_running_then_verified_without_transfer(resources):
    await seed(resources)
    identifier = await queued_verify(resources)
    _, calls = await runtime_fixture(resources)
    token = await claim_model_job(resources.sessions, identifier, 1)
    await local_models.run_model_job(resources, identifier, 1, token)
    async with resources.sessions() as session:
        assert (await session.get(BackgroundJob, identifier)).state == "completed"
        row = await session.get(ModelInstallation, KEY)
        assert row.state == "ready" and row.validation["runtime_version"] == "fixture-current"
    assert "/api/chat" in calls and not any("pull" in path for path in calls)


async def test_given_disappeared_weights_when_verify_retried_then_never_pull(resources):
    await seed(resources)
    identifier = await queued_verify(resources)
    state, calls = await runtime_fixture(resources)
    state["present"] = False
    token = await claim_model_job(resources.sessions, identifier, 1)
    await local_models.run_model_job(resources, identifier, 1, token)
    async with resources.sessions() as session:
        job = await session.get(BackgroundJob, identifier)
        row = await session.get(ModelInstallation, KEY)
        assert job.state == "failed" and job.error_code == "MODEL_WEIGHTS_MISSING"
        assert not row.weights_present
    retried = await local_models.transition_job(resources, identifier, "retry", uuid4())
    assert (await jobs(resources))[0].payload["verify_only"] is True
    token = await claim_model_job(resources.sessions, identifier, retried.generation)
    await local_models.run_model_job(resources, identifier, retried.generation, token)
    assert (await jobs(resources))[0].state == "failed"
    assert not any("pull" in path for path in calls)


async def test_given_interrupted_verification_when_recovered_then_intent_and_no_pull_are_preserved(
    resources,
):
    await seed(resources)
    identifier = await queued_verify(resources)
    state, calls = await runtime_fixture(resources)
    first = await claim_model_job(resources.sessions, identifier, 1)
    async with resources.sessions() as session, session.begin():
        job = await session.get(BackgroundJob, identifier)
        job.lease_expires_at = now() - timedelta(seconds=1)
    await recover(resources.sessions)
    state["present"] = False
    current = (await jobs(resources))[0]
    assert current.payload["verify_only"] is True and current.attempts == 0
    token = await claim_model_job(resources.sessions, identifier, current.generation)
    assert token != first
    await local_models.run_model_job(resources, identifier, current.generation, token)
    assert (await jobs(resources))[0].error_code == "MODEL_WEIGHTS_MISSING"
    assert not any("pull" in path for path in calls)


async def test_given_permanent_verify_failure_when_reconciled_again_then_no_failure_loop(resources):
    await seed(resources)
    state, _ = await runtime_fixture(resources)
    state["bad_probe"] = True
    await local_models.reconcile_local_models(resources)
    job = (await jobs(resources))[0]
    token = await claim_model_job(resources.sessions, job.id, 1)
    await local_models.run_model_job(resources, job.id, 1, token)
    assert (await jobs(resources))[0].state == "failed"
    await local_models.reconcile_local_models(resources)
    assert len(await jobs(resources)) == 1


async def test_given_transient_verify_outage_when_retried_then_three_failures_are_bounded(
    resources,
):
    await seed(resources)
    identifier = await queued_verify(resources)
    state, _ = await runtime_fixture(resources)
    state["outage"] = True
    for attempt in range(1, 4):
        async with resources.sessions() as session, session.begin():
            (await session.get(BackgroundJob, identifier)).available_at = now()
        current = (await jobs(resources))[0]
        token = await claim_model_job(resources.sessions, identifier, current.generation)
        assert token
        await local_models.run_model_job(resources, identifier, current.generation, token)
        after = (await jobs(resources))[0]
        assert after.attempts == attempt
        assert after.state == ("failed" if attempt == 3 else "queued")
        assert after.payload["verify_only"] is True


async def test_given_stale_verify_history_when_listing_then_operations_and_honest_copy_are_exposed(
    resources,
):
    await seed(resources, stale="schema")
    await runtime_fixture(resources)
    listed = next(
        model for model in await local_models.list_local_models(resources) if model.key == KEY
    )
    assert listed.unavailable_code == "LOCAL_MODEL_REVALIDATION_REQUIRED"
    assert "automatically" in listed.unavailable_reason
    assert listed.reasoning_efforts == ["default"]
    assert await jobs(resources) == []
    identifier = await queued_verify(resources)
    app = create_app(resources.settings)
    app.state.resources = resources
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        listed = next(
            item
            for item in (await client.get("/api/v1/models")).json()["items"]
            if item["key"] == KEY
        )
        assert listed["installation"]["operation"] == "verify"
        assert (await client.get(f"/api/v1/jobs/{identifier}")).json()[
            "model_operation"
        ] == "verify"
        assert (await client.get("/api/v1/jobs")).json()["items"][0]["model_operation"] == "verify"
        async with resources.sessions() as session, session.begin():
            job = await session.get(BackgroundJob, identifier)
            job.state, job.stage = "failed", "failed"
            (await session.get(ModelInstallation, KEY)).state = "failed"
        listed = next(
            item
            for item in (await client.get("/api/v1/models")).json()["items"]
            if item["key"] == KEY
        )
        assert listed["installation"]["operation"] == "verify"
        async with resources.sessions() as session, session.begin():
            job = await session.get(BackgroundJob, identifier)
            job.state, job.stage = "completed", "completed"
            (await session.get(ModelInstallation, KEY)).state = "ready"
        listed = next(
            item
            for item in (await client.get("/api/v1/models")).json()["items"]
            if item["key"] == KEY
        )
        assert listed["installation"]["operation"] is None
        assert (await client.get(f"/api/v1/jobs/{identifier}")).json()[
            "model_operation"
        ] == "verify"


@pytest.mark.parametrize("stale", ["schema", "context"])
async def test_given_stale_model_and_runtime_offline_when_listing_then_outage_is_reported(
    resources, stale
):
    await seed(resources, stale=stale)
    state, calls = await runtime_fixture(resources)
    state["outage"] = True
    listed = next(
        model for model in await local_models.list_local_models(resources) if model.key == KEY
    )
    assert listed.status == "unavailable"
    assert listed.unavailable_code == "LOCAL_RUNTIME_UNAVAILABLE"
    assert await jobs(resources) == [] and "/api/chat" not in calls


@pytest.mark.parametrize("version", [None, {"bad": "version"}])
async def test_given_invalid_version_when_listing_then_no_automatic_preparation_is_claimed(
    resources, version
):
    await seed(resources, stale=None)
    state, _ = await runtime_fixture(resources)
    state["version"] = version
    listed = next(
        model for model in await local_models.list_local_models(resources) if model.key == KEY
    )
    assert listed.unavailable_code == "LOCAL_RUNTIME_UNAVAILABLE"
    assert await jobs(resources) == []
