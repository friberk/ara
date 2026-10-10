"""Uncertain runtime I/O keeps global admission fenced through ordinary failures."""

import asyncio
from uuid import uuid4

import httpx
import pytest

from app.core.errors import AppError
from app.models.jobs import BackgroundJob
from app.models.local_models import ModelInstallation
from app.repositories.local_models import acquire_use, claim_model_job, recovery_operations
from app.services.local_models import request_delete, request_download, run_model_job

# Open-model tests run with EXPERIMENTAL_OPEN_MODELS on (ARA-090).
pytestmark = [pytest.mark.integration, pytest.mark.open_models]
KEY = "ifm-k2-horizon-3.7b"


class FailingPull(httpx.AsyncByteStream):
    def __init__(self, failure):
        self.failure = failure

    async def __aiter__(self):
        if self.failure == "timeout":
            await asyncio.Event().wait()
        elif self.failure == "protocol":
            yield b'{"digest":"layer","completed":1,"total":-1}\n'
        else:
            raise httpx.ReadTimeout("fixture stalled read")


@pytest.mark.parametrize(
    "failure,attempts", [("stall", 0), ("timeout", 0), ("stall", 2), ("protocol", 0)]
)
async def test_unconfirmed_failed_transfer_blocks_global_admission_until_ack(
    resources, failure, attempts
):
    job = await request_download(resources, KEY, uuid4())
    waiting = await request_download(resources, "qwen3.8-27b", uuid4())
    async with resources.sessions() as session, session.begin():
        (await session.get(BackgroundJob, job.id)).attempts = attempts
        session.add(
            ModelInstallation(model_key="ifm-k2-horizon-7b", state="ready", weights_present=True)
        )
    token = await claim_model_job(resources.sessions, job.id, 1)
    if failure == "timeout":
        resources.settings.ollama_pull_timeout_seconds = 0.05
    pause_available = False
    stopped = []
    pulls = []

    def handler(request):
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": []})
        if request.url.path == "/api/ara/capabilities":
            return httpx.Response(200, json={"protocol_version": 1, "pull_control": True})
        if request.url.path == "/api/ara/pull":
            pulls.append(request.url.path)
            return httpx.Response(200, stream=FailingPull(failure))
        if request.url.path.endswith("/pause"):
            if not pause_available:
                return httpx.Response(
                    503, json={"error": "fixture stop acknowledgment unavailable"}
                )
            stopped.append(request.url.path.split("/")[-2])
            return httpx.Response(200, json={"state": "paused"})
        raise AssertionError(request.url.path)

    await resources.http.aclose()
    resources.http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    await run_model_job(resources, job.id, 1, token)
    async with resources.sessions() as session:
        current = await session.get(BackgroundJob, job.id)
        original_operation = str(current.runtime_operation_id)
        assert current.state == "queued" and current.stage == "settling"
        assert original_operation in recovery_operations(current.payload)
        assert current.attempts == min(3, attempts + 1)
        generation = current.generation
    with pytest.raises(AppError) as error:
        await acquire_use(resources.sessions, "ifm-k2-horizon-7b")
    assert error.value.code == "LOCAL_MODEL_BUSY"
    with pytest.raises(AppError):
        await request_delete(resources, "ifm-k2-horizon-7b", uuid4())
    assert await claim_model_job(resources.sessions, waiting.id, 1) is None
    pause_available = True
    # Make only the existing cleanup outbox event due, without changing its identity.
    from app.repositories.jobs import now

    async with resources.sessions() as session, session.begin():
        (await session.get(BackgroundJob, job.id)).available_at = now()
    token = await claim_model_job(resources.sessions, job.id, generation)
    assert token is not None
    await run_model_job(resources, job.id, generation, token)
    assert original_operation in stopped
    assert len(pulls) == 1, "Cleanup must not replay transfer or spend another attempt"
    async with resources.sessions() as session:
        current = await session.get(BackgroundJob, job.id)
        assert not recovery_operations(current.payload)
        assert current.attempts == min(3, attempts + 1)
        assert current.state == ("failed" if attempts == 2 or failure == "protocol" else "queued")
    assert await claim_model_job(resources.sessions, waiting.id, 1) is not None


async def test_queued_user_pause_settles_failed_transfer_before_releasing_admission(resources):
    from app.repositories.local_models import checkpoint, finish_model_job, release_use
    from app.services.local_models import transition_job

    job = await request_download(resources, KEY, uuid4())
    token = await claim_model_job(resources.sessions, job.id, 1)
    await checkpoint(resources.sessions, job.id, 1, token, stage="downloading")
    await finish_model_job(
        resources.sessions,
        job.id,
        1,
        token,
        error=AppError(502, "MODEL_PROTOCOL_ERROR", "Invalid transfer progress."),
    )
    async with resources.sessions() as session, session.begin():
        current = await session.get(BackgroundJob, job.id)
        operation = str(current.runtime_operation_id)
        assert current.state == "queued" and operation in recovery_operations(current.payload)
        session.add(
            ModelInstallation(model_key="ifm-k2-horizon-7b", state="ready", weights_present=True)
        )
    acknowledged = []

    def handler(request):
        if request.url.path == "/api/ara/capabilities":
            return httpx.Response(200, json={"protocol_version": 1, "pull_control": True})
        acknowledged.append(request.url.path.split("/")[-2])
        return httpx.Response(200, json={"state": "paused"})

    await resources.http.aclose()
    resources.http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    paused = await transition_job(resources, job.id, "pause", uuid4())
    assert paused.state == "paused" and operation in acknowledged
    async with resources.sessions() as session:
        assert not recovery_operations((await session.get(BackgroundJob, job.id)).payload)
    lease = await acquire_use(resources.sessions, "ifm-k2-horizon-7b")
    assert await release_use(resources.sessions, lease)


async def test_multiple_cleanup_obligations_are_drained_in_order_without_new_transfer(resources):
    from app.repositories.jobs import now
    from app.repositories.local_models import checkpoint, finish_model_job, pending_owner

    first = await request_download(resources, KEY, uuid4())
    token = await claim_model_job(resources.sessions, first.id, 1)
    await checkpoint(resources.sessions, first.id, 1, token, stage="downloading")
    await finish_model_job(
        resources.sessions,
        first.id,
        1,
        token,
        error=AppError(502, "MODEL_PROTOCOL_ERROR", "First uncertain transfer."),
    )
    # Model a preexisting second orphan from before global admission was repaired.
    from app.repositories.jobs import enqueue

    async with resources.sessions() as session, session.begin():
        second = await enqueue(
            session,
            kind="model_download",
            payload={
                "model_key": "ifm-k2-horizon-7b",
                "_recovery_operation_ids": [str(uuid4())],
                "_model_failure": {
                    "code": "MODEL_PROTOCOL_ERROR",
                    "message": "Second uncertain transfer.",
                    "status": 502,
                },
            },
        )
        second.model_key = "ifm-k2-horizon-7b"
        session.add(
            ModelInstallation(model_key=second.model_key, state="queued", active_job_id=second.id)
        )
        (await session.get(BackgroundJob, first.id)).available_at = now()
        assert await pending_owner(session) == first.id
    acknowledged = []

    def handler(request):
        if request.url.path == "/api/ara/capabilities":
            return httpx.Response(200, json={"protocol_version": 1, "pull_control": True})
        assert request.url.path.endswith("/pause"), "Cleanup must not begin a new transfer"
        acknowledged.append(request.url.path.split("/")[-2])
        return httpx.Response(200, json={"state": "paused"})

    await resources.http.aclose()
    resources.http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    assert await claim_model_job(resources.sessions, second.id, 1) is None
    token = await claim_model_job(resources.sessions, first.id, 2)
    assert token is not None
    await run_model_job(resources, first.id, 2, token)
    token = await claim_model_job(resources.sessions, second.id, 1)
    assert token is not None
    await run_model_job(resources, second.id, 1, token)
    async with resources.sessions() as session:
        assert await pending_owner(session) is None
        assert (await session.get(BackgroundJob, first.id)).state == "failed"
        assert (await session.get(BackgroundJob, second.id)).state == "failed"
    assert len(acknowledged) >= 2
