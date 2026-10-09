"""Native thinking settings and provenance on isolated real PostgreSQL."""

import asyncio
from contextlib import asynccontextmanager
from uuid import uuid4

import httpx
import pytest

from app.integrations.llm import generation_configuration
from app.main import create_app
from app.models.jobs import BackgroundJob
from app.models.local_models import ModelInstallation
from app.models.research import ChatMessage, ModelConfiguration
from app.schemas.ai import ChatInput
from app.services import chat, summarization
from tests.test_ai_integration import local_fixture, paper_fixture, summary_job_fixture

pytestmark = pytest.mark.integration


async def install_controls(resources):
    spec, requests = await local_fixture(resources)
    async with resources.sessions() as session, session.begin():
        row = await session.get(ModelInstallation, spec.key)
        row.validation = {
            **row.validation,
            "thinking_schema": 1,
            "thinking": {"values": [False, True, "quick", "deliberate"], "default": "deliberate"},
            "think_mapping": {
                "none": False,
                "on": True,
                "quick": "quick",
                "deliberate": "deliberate",
            },
            "reasoning_efforts": ["default", "none", "on", "quick", "deliberate"],
        }
    return spec, requests


async def test_given_native_controls_when_saving_then_validate_known_names_and_preserve_defaults(
    resources,
):
    spec, _ = await install_controls(resources)
    app = create_app(resources.settings)
    app.state.resources = resources
    body = {"default_model": spec.key, "reasoning_effort": "deliberate"}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.put("/api/v1/settings", json=body)
        assert response.status_code == 200, response.text
        assert response.json() == body
        unknown = await client.put(
            "/api/v1/settings", json={**body, "reasoning_effort": "invented"}
        )
        assert unknown.status_code == 422
        assert unknown.json()["code"] == "INVALID_REASONING"
        models = (await client.get("/api/v1/models")).json()["items"]
        native = next(item for item in models if item["key"] == spec.key)
        assert native["thinking"] == {
            "values": [False, True, "quick", "deliberate"],
            "default": "deliberate",
        }
    async with resources.sessions() as session, session.begin():
        row = await session.get(ModelInstallation, spec.key)
        row.state, row.weights_present, row.validation = "missing", False, None
    restarted = create_app(resources.settings)
    restarted.state.resources = resources
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=restarted), base_url="http://test"
    ) as client:
        assert (await client.get("/api/v1/settings")).json() == body
        assert (await client.put("/api/v1/settings", json=body)).status_code == 200
        unknown = await client.put(
            "/api/v1/settings", json={**body, "reasoning_effort": "invented"}
        )
        assert unknown.status_code == 422
    async with resources.sessions() as session:
        assert (await session.get(ModelConfiguration, "defaults")).value == body


@pytest.mark.parametrize(
    ("effort", "effective"),
    [("default", "deliberate"), ("none", False), ("on", True), ("quick", "quick")],
)
async def test_given_native_choice_when_streaming_then_snapshot_effective_value_and_omission(
    resources, effort, effective
):
    spec, requests = await install_controls(resources)
    _, _, chat_id = await paper_fixture(resources)
    body = ChatInput(
        model=spec.key, reasoning_effort=effort, content="What accuracy?", request_id=uuid4()
    )
    assistant, prompt, chunks, replay = await chat.prepare(resources, chat_id, body)
    request = type(
        "Request", (), {"is_disconnected": lambda self: asyncio.sleep(0, result=False)}
    )()
    output = "".join(
        [
            item
            async for item in chat.stream_answer(
                resources, request, assistant, prompt, chunks, replay
            )
        ]
    )
    assert "message.completed" in output
    async with resources.sessions() as session:
        saved = await session.get(ChatMessage, assistant.id)
        assert saved.state == "completed"
        assert saved.configuration["reasoning_effort"] == effort
        assert saved.configuration["effective_think"] == effective
        assert saved.configuration["think_parameter_omitted"] is (effort == "default")
        assert saved.configuration["thinking"]["default"] == "deliberate"
    if effort == "default":
        assert "think" not in requests[0]
    else:
        assert requests[0]["think"] == effective
        assert type(requests[0]["think"]) is type(effective)


async def test_given_checkpointed_default_when_native_default_changes_then_generation_stops(
    resources, monkeypatch
):
    spec, requests = await install_controls(resources)
    identifier, token, payload = await summary_job_fixture(resources, spec, 2)
    real_slots = summarization.generation_slots

    @asynccontextmanager
    async def change_after_release(resources, model):
        async with real_slots(resources, model):
            yield
        async with resources.sessions() as session, session.begin():
            row = await session.get(ModelInstallation, model)
            row.validation = {
                **row.validation,
                "thinking": {**row.validation["thinking"], "default": "quick"},
            }

    monkeypatch.setattr(summarization, "generation_slots", change_after_release)
    await summarization.run_summary_job(resources, identifier, 1, token, payload)
    async with resources.sessions() as session:
        job = await session.get(BackgroundJob, identifier)
        assert job.state == "failed"
        assert job.error_code == "MODEL_CONFIGURATION_CHANGED"
        assert job.payload["_generation_configuration"]["effective_think"] == "deliberate"
    assert len(requests) == 1
    assert (await generation_configuration(resources, spec.key, "default"))[
        "effective_think"
    ] == "quick"


async def test_given_old_validation_at_same_version_when_selecting_then_revalidation_is_required(
    resources,
):
    from app.integrations.llm import LLMError, validate_model_available

    spec, _ = await install_controls(resources)
    async with resources.sessions() as session, session.begin():
        row = await session.get(ModelInstallation, spec.key)
        row.validation = {
            key: value
            for key, value in row.validation.items()
            if key not in {"thinking_schema", "thinking", "think_mapping"}
        }
    with pytest.raises(LLMError) as failure:
        await validate_model_available(resources, spec.key, "default")
    assert failure.value.code == "LOCAL_MODEL_REVALIDATION_REQUIRED"


async def test_given_saved_native_name_when_verified_controls_change_then_saving_rechecks_support(
    resources,
):
    spec, _ = await install_controls(resources)
    app = create_app(resources.settings)
    app.state.resources = resources
    body = {"default_model": spec.key, "reasoning_effort": "deliberate"}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        assert (await client.put("/api/v1/settings", json=body)).status_code == 200
        async with resources.sessions() as session, session.begin():
            row = await session.get(ModelInstallation, spec.key)
            row.validation = {
                **row.validation,
                "thinking": {"values": ["quick"], "default": "quick"},
                "think_mapping": {"quick": "quick"},
                "reasoning_efforts": ["default", "quick"],
            }
        response = await client.put("/api/v1/settings", json=body)
        assert response.status_code == 422
        assert response.json()["code"] == "INVALID_REASONING"
        # The old preference remains readable until the user chooses its replacement.
        assert (await client.get("/api/v1/settings")).json() == body


@pytest.mark.parametrize(
    "unverified",
    [
        {"reasoning_efforts": ["default", "xhigh"]},
        {
            "thinking_schema": 1,
            "thinking": {"values": ["low"], "default": "low"},
            "think_mapping": {"low": "low"},
            "reasoning_efforts": ["default", "low", "xhigh"],
        },
        {
            "thinking_schema": 1,
            "thinking": {"values": ["low", "xhigh"], "default": "low"},
            "think_mapping": {"xhigh": "high"},
            "reasoning_efforts": ["default", "xhigh"],
        },
        {
            "thinking_schema": 1,
            "thinking": {"values": ["xhigh"]},
            "think_mapping": {"xhigh": "xhigh"},
            "reasoning_efforts": ["default", "xhigh"],
        },
    ],
)
async def test_given_unverified_native_list_when_saving_then_no_new_control_is_authorized(
    resources, unverified
):
    spec, _ = await local_fixture(resources)
    async with resources.sessions() as session, session.begin():
        row = await session.get(ModelInstallation, spec.key)
        row.validation = unverified
    app = create_app(resources.settings)
    app.state.resources = resources
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.put(
            "/api/v1/settings", json={"default_model": spec.key, "reasoning_effort": "xhigh"}
        )
        assert response.status_code == 422
        assert response.json()["code"] == "INVALID_REASONING"
    async with resources.sessions() as session:
        assert await session.get(ModelConfiguration, "defaults") is None
