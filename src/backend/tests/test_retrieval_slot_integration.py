"""Retrieval inference has its own short admission slot beside generation (ARA-072)."""

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
                {"name": spec.model_id, "digest": spec.expected_digest, "size": 1}
                for spec in specs
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


async def test_given_retrieval_in_progress_when_second_retrieval_admits_then_it_is_busy(
    resources,
):
    from app.services.local_models import retrieval_inference_slot

    await ready_models(resources, RETRIEVAL)
    async with retrieval_inference_slot(resources, RETRIEVAL):
        with pytest.raises(AppError) as busy:
            async with retrieval_inference_slot(resources, RETRIEVAL):
                pytest.fail("a second retrieval holder must be refused")
        assert busy.value.code == "LOCAL_MODEL_BUSY"
