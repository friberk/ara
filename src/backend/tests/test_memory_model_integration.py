"""The model for conversation summaries and follow-up planning is a stored setting (ARA-077)."""

import json

import httpx
import pytest

from app.models.research import ModelConfiguration
from tests.support.chats import add_turns, seed_chat
from tests.support.models import (
    hosted_responses,
    install_thinking_model,
    local_runtime,
    ollama_reply,
)
from tests.test_compaction_integration import SUMMARY_V1, maybe_enqueue, memories, run_job, turns
from tests.test_query_planner import FOLLOW_UP, plan_output, rag_history

pytestmark = pytest.mark.integration


@pytest.fixture
async def client(resources):
    from app.main import create_app

    app = create_app(resources.settings)
    app.state.resources = resources
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as http:
        yield http


async def stored(resources) -> dict | None:
    async with resources.sessions() as session:
        row = await session.get(ModelConfiguration, "defaults")
        return row.value if row else None


async def save_memory_model(client, key: str) -> None:
    body = {"default_model": "gpt-5.6-luna", "reasoning_effort": "low", "memory_model": key}
    response = await client.put("/api/v1/settings", json=body)
    assert response.status_code == 200, response.text


async def test_given_no_saved_settings_when_reading_then_luna_is_the_memory_model(client):
    response = await client.get("/api/v1/settings")
    assert response.status_code == 200
    assert response.json()["memory_model"] == "gpt-5.6-luna"


async def test_given_a_hosted_chat_model_when_saving_then_it_is_stored_and_read_back(
    resources, client
):
    body = {
        "default_model": "gpt-5.6-luna",
        "reasoning_effort": "low",
        "memory_model": "gpt-5.6-sol",
    }
    response = await client.put("/api/v1/settings", json=body)
    assert response.status_code == 200, response.text
    assert response.json() == body
    assert (await client.get("/api/v1/settings")).json() == body
    assert await stored(resources) == body


@pytest.mark.parametrize("key", ["ifm-k2-horizon-7b", "qwen3-embed-4b", "gpt-unknown", ""])
async def test_given_a_key_outside_the_hosted_chat_catalog_when_saving_then_422(
    resources, client, key
):
    await save_memory_model(client, "gpt-5.6-terra")
    body = {"default_model": "gpt-5.6-luna", "reasoning_effort": "low", "memory_model": key}
    response = await client.put("/api/v1/settings", json=body)
    assert response.status_code == 422
    assert response.json()["code"] == "INVALID_MEMORY_MODEL"
    assert (await stored(resources))["memory_model"] == "gpt-5.6-terra"


async def test_given_a_saved_memory_model_when_saving_defaults_without_it_then_it_is_kept(
    resources, client
):
    await save_memory_model(client, "gpt-5.6-sol")
    # The composer's "set as default" sends only the chat defaults.
    response = await client.put(
        "/api/v1/settings", json={"default_model": "gpt-5.6-terra", "reasoning_effort": "high"}
    )
    assert response.status_code == 200, response.text
    assert response.json()["memory_model"] == "gpt-5.6-sol"
    assert await stored(resources) == {
        "default_model": "gpt-5.6-terra",
        "reasoning_effort": "high",
        "memory_model": "gpt-5.6-sol",
    }


async def test_given_sol_as_memory_model_when_a_hosted_chat_compacts_then_sol_quietly_compacts(
    resources, client, monkeypatch
):
    await save_memory_model(client, "gpt-5.6-sol")
    requests = hosted_responses(monkeypatch, resources, lambda body: SUMMARY_V1)
    _, _, chat_id = await seed_chat(resources)
    await add_turns(resources, chat_id, turns(3), model="gpt-5.6-terra")
    resources.settings.memory_compaction_ratio = 0.01
    await run_job(resources, await maybe_enqueue(resources, chat_id, "gpt-5.6-terra"))
    (body,) = requests
    assert body["model"] == "gpt-5.6-sol" and body["reasoning"] == {"effort": "none"}
    (memory,) = await memories(resources, chat_id)
    assert memory.model == "gpt-5.6-sol"


async def test_given_sol_as_memory_model_when_a_hosted_chat_plans_then_sol_quietly_plans(
    resources, client, monkeypatch
):
    from app.services import memory

    await save_memory_model(client, "gpt-5.6-sol")
    requests = hosted_responses(monkeypatch, resources, lambda body: plan_output())
    plan = await memory.plan_query(
        resources,
        model="gpt-5.6-luna",
        effort="high",
        history=rag_history(),
        memory_summary=None,
        question=FOLLOW_UP,
    )
    assert plan.source == "model"
    (body,) = requests
    assert body["model"] == "gpt-5.6-sol" and body["reasoning"] == {"effort": "none"}


async def test_given_sol_as_memory_model_when_a_local_chat_compacts_then_it_stays_local(
    resources, client, monkeypatch
):
    from app.integrations.model_catalog import local_spec

    await save_memory_model(client, "gpt-5.6-sol")
    spec = local_spec("ifm-k2-horizon-7b")
    await install_thinking_model(resources, spec)
    local, hosted = await local_runtime(
        monkeypatch, resources, spec, lambda body: ollama_reply(SUMMARY_V1)
    )
    _, _, chat_id = await seed_chat(resources)
    await add_turns(resources, chat_id, turns(3), model=spec.key)
    resources.settings.memory_compaction_ratio = 0.01
    await run_job(resources, await maybe_enqueue(resources, chat_id, spec.key))
    assert hosted == [] and [body["model"] for body in local] == [spec.model_id]
    assert "Turn 0 finding" in json.dumps(local[0]["messages"])
    (memory,) = await memories(resources, chat_id)
    assert memory.model == spec.key
