"""Aliases roundtrip through list; raw legacy preferences, payloads and replay stay intact."""

import asyncio
from uuid import uuid4

import httpx
import pytest
from test_reasoning_aliases import current_validation

from app.main import create_app
from app.models.jobs import BackgroundJob
from app.models.local_models import ModelInstallation
from app.models.research import ChatMessage, ModelConfiguration
from app.schemas.ai import ChatInput, ModelPage
from app.services import chat
from tests.test_ai_integration import local_fixture, paper_fixture

pytestmark = pytest.mark.integration


async def install_alias_controls(resources):
    spec, requests = await local_fixture(resources)
    async with resources.sessions() as session, session.begin():
        row = await session.get(ModelInstallation, spec.key)
        row.validation = {
            **row.validation,
            **current_validation(spec.key),
            "runtime_version": row.validation["runtime_version"],
        }
    return spec, requests


async def test_given_verified_7b_when_listing_then_aliases_roundtrip_and_hosted_stay_empty(
    resources,
):
    spec, requests = await install_alias_controls(resources)
    app = create_app(resources.settings)
    app.state.resources = resources
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/v1/models")
        assert response.status_code == 200
        page = ModelPage.model_validate(response.json())
        model = next(item for item in page.items if item.key == spec.key)
        assert model.reasoning_aliases == {"default": "high", "on": "high"}
        assert model.reasoning_efforts == ["default", "none", "on", "low", "medium", "high"]
        assert all(item.reasoning_aliases == {} for item in page.items if item.provider == "openai")
    assert requests == []


@pytest.mark.parametrize("effort", ["default", "on"])
async def test_given_legacy_setting_when_listing_aliases_then_raw_save_and_summary_replay_unchanged(
    resources, effort
):
    spec, requests = await install_alias_controls(resources)
    paper_id, _, _ = await paper_fixture(resources)
    app = create_app(resources.settings)
    app.state.resources = resources
    preference = {"default_model": spec.key, "reasoning_effort": effort}
    saved = preference
    body = {"model": spec.key, "reasoning_effort": effort, "request_id": str(uuid4())}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        assert (await client.put("/api/v1/settings", json=preference)).json() == saved
        assert (await client.get("/api/v1/settings")).json() == saved
        first = await client.post(f"/api/v1/papers/{paper_id}/summaries", json=body)
        assert first.status_code == 202, first.text
        identifier = first.json()["job_id"]
        async with resources.sessions() as session, session.begin():
            row = await session.get(ModelInstallation, spec.key)
            row.state, row.weights_present, row.validation = "missing", False, None
        replay = await client.post(f"/api/v1/papers/{paper_id}/summaries", json=body)
        assert replay.status_code == 202 and replay.json()["job_id"] == identifier
        assert (await client.get("/api/v1/settings")).json() == saved
    async with resources.sessions() as session:
        assert (await session.get(ModelConfiguration, "defaults")).value == saved
        job = await session.get(BackgroundJob, identifier)
        assert job.payload["reasoning_effort"] == effort
    assert requests == []


@pytest.mark.parametrize("effort,effective", [("default", "high"), ("on", True)])
async def test_given_legacy_chat_when_aliases_exist_then_payload_history_and_replay_preserved(
    resources, effort, effective
):
    spec, requests = await install_alias_controls(resources)
    _, _, chat_id = await paper_fixture(resources)
    body = ChatInput(
        model=spec.key, reasoning_effort=effort, content="What accuracy?", request_id=uuid4()
    )
    prepared = await chat.prepare(resources, chat_id, body)
    request = type(
        "Request", (), {"is_disconnected": lambda self: asyncio.sleep(0, result=False)}
    )()
    output = "".join([event async for event in chat.stream_answer(resources, request, prepared)])
    assert "message.completed" in output
    assert len(requests) == 1
    if effort == "default":
        assert "think" not in requests[0]
    else:
        assert requests[0]["think"] is True
    async with resources.sessions() as session, session.begin():
        saved = await session.get(ChatMessage, prepared.assistant.id)
        assert saved.reasoning_effort == saved.configuration["reasoning_effort"] == effort
        assert saved.configuration["effective_think"] == effective
        assert type(saved.configuration["effective_think"]) is type(effective)
        assert saved.configuration["think_parameter_omitted"] is (effort == "default")
        row = await session.get(ModelInstallation, spec.key)
        row.state, row.weights_present, row.validation = "missing", False, None
    replayed = await chat.prepare(resources, chat_id, body)
    assert replayed.replay and replayed.assistant.id == prepared.assistant.id
    assert len(requests) == 1
