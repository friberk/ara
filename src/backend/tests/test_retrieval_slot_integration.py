"""Retrieval inference has its own short admission slot beside generation (ARA-072)."""

import asyncio
import time
from datetime import timedelta
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import delete, select

from app.core.errors import AppError
from app.integrations.model_catalog import local_spec
from app.models.jobs import BackgroundJob
from app.models.local_models import ModelInstallation, ModelUse
from app.repositories.jobs import now

pytestmark = pytest.mark.integration
CHAT, RETRIEVAL = "ifm-k2-horizon-7b", "ifm-k2-horizon-3.7b"


async def ready_models(resources, *keys):
    specs = [local_spec(key) for key in keys]

    def runtime(request):
        if request.url.path == "/api/tags":
            models = [
                {"name": spec.model_id, "digest": spec.expected_digest, "size": 1} for spec in specs
            ]
            return httpx.Response(200, json={"models": models})
        if request.url.path == "/api/version":
            return httpx.Response(200, json={"version": "0.40.1-ara.fixture"})
        return httpx.Response(404)

    await resources.http.aclose()
    resources.http = httpx.AsyncClient(transport=httpx.MockTransport(runtime))
    async with resources.sessions() as session, session.begin():
        await session.execute(delete(ModelUse))
        for spec in specs:
            session.add(
                ModelInstallation(
                    model_key=spec.key,
                    state="ready",
                    weights_present=True,
                    digest=spec.expected_digest,
                    validation={
                        "digest": spec.expected_digest,
                        "context_window": resources.settings.ollama_context_window,
                        "runtime_version": "0.40.1-ara.fixture",
                        "thinking_schema": 1,
                    },
                )
            )


async def test_given_generation_in_progress_when_retrieval_admits_then_both_slots_are_held(
    resources,
):
    from app.repositories.local_models import acquire_use, release_use
    from app.services.local_models import request_download, retrieval_inference_slot

    await ready_models(resources, CHAT, RETRIEVAL)
    generation = await acquire_use(resources.sessions, CHAT)
    try:
        async with retrieval_inference_slot(resources, RETRIEVAL):
            async with resources.sessions() as session:
                uses = {use.slot: use for use in (await session.scalars(select(ModelUse))).all()}
            assert set(uses) == {"inference", "retrieval"}
            assert uses["retrieval"].model_key == RETRIEVAL
            assert uses["retrieval"].expires_at <= now() + timedelta(seconds=31)
            # Model mutations stay fenced while retrieval inference runs.
            with pytest.raises(AppError) as busy:
                await request_download(resources, "qwen3.8-27b", uuid4())
            assert busy.value.code == "LOCAL_MODEL_BUSY"
        async with resources.sessions() as session:
            remaining = (await session.scalars(select(ModelUse.slot))).all()
        assert remaining == ["inference"]
    finally:
        await release_use(resources.sessions, generation)


async def test_given_model_download_processing_when_retrieval_admits_then_runtime_is_busy(
    resources,
):
    from app.services.local_models import retrieval_inference_slot

    await ready_models(resources, RETRIEVAL)
    async with resources.sessions() as session, session.begin():
        session.add(
            BackgroundJob(
                kind="model_download",
                model_key="qwen3.8-27b",
                payload={"model_key": "qwen3.8-27b"},
                state="processing",
                lease_token=uuid4(),
                lease_expires_at=now() + timedelta(seconds=60),
            )
        )
    with pytest.raises(AppError) as busy:
        async with retrieval_inference_slot(resources, RETRIEVAL):
            pytest.fail("retrieval must not run during model maintenance")
    assert busy.value.code == "LOCAL_MODEL_BUSY"


async def test_given_retrieval_held_past_the_wait_when_search_admits_then_it_is_busy(
    resources, monkeypatch
):
    from app.services import local_models
    from app.services.local_models import retrieval_inference_slot

    monkeypatch.setattr(local_models, "RETRIEVAL_WAIT_SECONDS", 0.6, raising=False)
    await ready_models(resources, RETRIEVAL)
    async with retrieval_inference_slot(resources, RETRIEVAL):
        started = time.monotonic()
        with pytest.raises(AppError) as busy:
            async with retrieval_inference_slot(resources, RETRIEVAL):
                pytest.fail("a second retrieval holder must be refused")
        assert busy.value.code == "LOCAL_MODEL_BUSY"
        # The search waited its bounded time before falling back.
        assert 0.6 <= time.monotonic() - started < 3


async def test_given_background_embedding_when_a_search_waits_then_the_search_enters_next(
    resources, monkeypatch
):
    """Regression: a search retried once after 1 s while background batches held the slot."""
    from app.repositories.local_models import acquire_use, release_use
    from app.services import local_models
    from app.services.local_models import retrieval_inference_slot

    monkeypatch.setattr(local_models, "RETRIEVAL_POLL_SECONDS", 1.0, raising=False)
    await ready_models(resources, RETRIEVAL)
    batch = await acquire_use(resources.sessions, RETRIEVAL, slot="retrieval", lease_seconds=30)
    entered = []

    async def search():
        async with retrieval_inference_slot(resources, RETRIEVAL):
            entered.append(time.monotonic())

    waiting = asyncio.create_task(search())
    await asyncio.sleep(0.3)
    assert not waiting.done()  # the search waits instead of falling back
    await release_use(resources.sessions, batch)
    released = time.monotonic()
    # The next background batch yields while the search sleeps between attempts.
    with pytest.raises(AppError) as yielded:
        async with retrieval_inference_slot(resources, RETRIEVAL, background=True):
            pytest.fail("background embedding must yield to a waiting search")
    assert yielded.value.code == "LOCAL_MODEL_BUSY"
    assert yielded.value.message == "A search is waiting for the local runtime."
    await asyncio.wait_for(waiting, 5)
    assert entered and entered[0] - released < 2


async def test_given_no_waiting_search_when_background_admits_then_it_holds_the_slot(resources):
    from app.services.local_models import retrieval_inference_slot

    await ready_models(resources, RETRIEVAL)
    async with retrieval_inference_slot(resources, RETRIEVAL, background=True):
        async with resources.sessions() as session:
            uses = (await session.scalars(select(ModelUse))).all()
        assert [(use.slot, use.model_key) for use in uses] == [("retrieval", RETRIEVAL)]


async def test_given_cancel_after_admission_commits_then_the_lease_is_released(
    resources, monkeypatch
):
    """A rerank deadline or a closed browser can cancel the caller just after the lease row
    commits, before the token returns; that lease must not block the slot until it expires."""
    from app.services import local_models
    from app.services.local_models import retrieval_inference_slot

    await ready_models(resources, RETRIEVAL)
    committed, real = asyncio.Event(), local_models.acquire_use

    async def slow_close(*args, **options):
        token = await real(*args, **options)
        committed.set()
        await asyncio.sleep(0.2)  # the session is still closing when the cancel arrives
        return token

    monkeypatch.setattr(local_models, "acquire_use", slow_close)

    async def search():
        async with retrieval_inference_slot(resources, RETRIEVAL):
            await asyncio.sleep(5)

    task = asyncio.create_task(search())
    await committed.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.sleep(0.5)
    async with resources.sessions() as session:
        assert (await session.scalars(select(ModelUse))).all() == []
