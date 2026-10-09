"""Summaries and follow-up planning use the chat's own model and active effort (ARA-083)."""

import json
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import select

from app.models.research import GenerationReservation, ModelConfiguration
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


async def put_defaults(client, **extra):
    body = {"default_model": "gpt-5.6-luna", "reasoning_effort": "low", **extra}
    return await client.put("/api/v1/settings", json=body)


async def test_given_no_saved_settings_when_reading_then_there_is_no_memory_model(client):
    response = await client.get("/api/v1/settings")
    assert response.status_code == 200
    assert response.json() == {"default_model": "gpt-5.6-luna", "reasoning_effort": "low"}


async def test_given_a_put_without_memory_model_when_saving_then_defaults_round_trip(
    resources, client
):
    body = {"default_model": "gpt-5.6-terra", "reasoning_effort": "high"}
    response = await client.put("/api/v1/settings", json=body)
    assert response.status_code == 200, response.text
    assert response.json() == body
    assert (await client.get("/api/v1/settings")).json() == body
    assert await stored(resources) == body


@pytest.mark.parametrize("key", ["gpt-5.6-sol", "ifm-k2-horizon-7b", "gpt-unknown", ""])
async def test_given_a_put_that_still_carries_memory_model_when_saving_then_it_is_ignored(
    resources, client, key
):
    response = await put_defaults(client, memory_model=key)
    assert response.status_code == 200, response.text
    assert response.json() == {"default_model": "gpt-5.6-luna", "reasoning_effort": "low"}
    assert await stored(resources) == {"default_model": "gpt-5.6-luna", "reasoning_effort": "low"}


async def test_given_stored_defaults_with_a_memory_model_when_reading_then_it_is_not_returned(
    resources, client
):
    stale = {
        "default_model": "gpt-5.6-terra",
        "reasoning_effort": "high",
        "memory_model": "gpt-5.6-sol",
    }
    async with resources.sessions() as session, session.begin():
        session.add(ModelConfiguration(key="defaults", value=stale))
    response = await client.get("/api/v1/settings")
    assert response.status_code == 200
    assert response.json() == {"default_model": "gpt-5.6-terra", "reasoning_effort": "high"}


async def test_given_a_hosted_chat_on_terra_when_it_compacts_then_terra_compacts(
    resources, monkeypatch
):
    requests = hosted_responses(monkeypatch, resources, lambda body: SUMMARY_V1)
    _, _, chat_id = await seed_chat(resources)
    await add_turns(resources, chat_id, turns(3), model="gpt-5.6-terra")
    resources.settings.memory_compaction_ratio = 0.01
    await run_job(resources, await maybe_enqueue(resources, chat_id, "gpt-5.6-terra"))
    (body,) = requests
    assert body["model"] == "gpt-5.6-terra" and body["reasoning"] == {"effort": "none"}
    (memory,) = await memories(resources, chat_id)
    assert memory.model == "gpt-5.6-terra"


async def test_given_a_hosted_chat_on_sol_when_it_plans_then_sol_plans_at_the_chat_effort(
    resources, monkeypatch
):
    from app.services import memory

    requests = hosted_responses(monkeypatch, resources, lambda body: plan_output())
    plan = await memory.plan_query(
        resources,
        model="gpt-5.6-sol",
        effort="high",
        history=rag_history(),
        memory_summary=None,
        question=FOLLOW_UP,
    )
    assert plan.source == "model"
    (body,) = requests
    assert body["model"] == "gpt-5.6-sol" and body["reasoning"] == {"effort": "high"}


async def test_given_a_stored_memory_model_when_a_hosted_chat_plans_then_the_chat_model_is_used(
    resources, monkeypatch
):
    from app.services import memory

    stale = {
        "default_model": "gpt-5.6-luna",
        "reasoning_effort": "low",
        "memory_model": "gpt-5.6-sol",
    }
    async with resources.sessions() as session, session.begin():
        session.add(ModelConfiguration(key="defaults", value=stale))
    requests = hosted_responses(monkeypatch, resources, lambda body: plan_output())
    await memory.plan_query(
        resources,
        model="gpt-5.6-terra",
        effort="high",
        history=rag_history(),
        memory_summary=None,
        question=FOLLOW_UP,
    )
    (body,) = requests
    assert body["model"] == "gpt-5.6-terra"


async def test_given_a_hosted_default_when_a_local_chat_compacts_then_it_stays_local(
    resources, monkeypatch
):
    from app.integrations.model_catalog import local_spec

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


PLANNER_OUTPUT = 300
HIGH_HEADROOM = 4096


async def test_given_a_hosted_chat_at_high_when_it_plans_then_high_runs_with_room_to_reason(
    resources, monkeypatch
):
    from app.services import memory

    requests = hosted_responses(monkeypatch, resources, lambda body: plan_output())
    plan = await memory.plan_query(
        resources,
        model="gpt-5.6-sol",
        effort="high",
        history=rag_history(),
        memory_summary=None,
        question=FOLLOW_UP,
    )
    assert plan.source == "model"
    (body,) = requests
    assert body["reasoning"] == {"effort": "high"}
    # Reasoning tokens count against the limit, so the allowance leaves room beyond the answer.
    assert body["max_output_tokens"] == PLANNER_OUTPUT + HIGH_HEADROOM
    async with resources.sessions() as session:
        (reserved,) = (await session.scalars(select(GenerationReservation.amount))).all()
    assert reserved >= Decimal("20") * (PLANNER_OUTPUT + HIGH_HEADROOM) / 1_000_000


async def test_given_a_hosted_turn_at_medium_when_compacting_then_the_queued_effort_is_used(
    resources, monkeypatch
):
    requests = hosted_responses(monkeypatch, resources, lambda body: SUMMARY_V1)
    _, _, chat_id = await seed_chat(resources)
    await add_turns(resources, chat_id, turns(3), model="gpt-5.6-terra")
    resources.settings.memory_compaction_ratio = 0.01
    job_id = await maybe_enqueue(resources, chat_id, "gpt-5.6-terra", "medium")
    _, _, payload = await run_job(resources, job_id)
    assert payload["effort"] == "medium"
    (body,) = requests
    assert body["model"] == "gpt-5.6-terra" and body["reasoning"] == {"effort": "medium"}
    assert body["max_output_tokens"] >= 1024 + 2048
    async with resources.sessions() as session:
        (reserved,) = (await session.scalars(select(GenerationReservation.amount))).all()
    assert reserved >= Decimal("12") * body["max_output_tokens"] / 1_000_000


async def test_given_a_local_chat_with_thinking_on_when_it_plans_then_thinking_and_schema_are_sent(
    resources, monkeypatch
):
    from app.integrations.model_catalog import local_spec
    from app.services import memory

    spec = local_spec("ifm-k2-horizon-7b")
    await install_thinking_model(resources, spec)
    local, hosted = await local_runtime(
        monkeypatch, resources, spec, lambda body: ollama_reply(plan_output())
    )
    plan = await memory.plan_query(
        resources,
        model=spec.key,
        effort="on",
        history=rag_history(),
        memory_summary=None,
        question=FOLLOW_UP,
    )
    assert plan.source == "model" and hosted == []
    (body,) = local
    assert body["think"] is True and "search_queries" in body["format"]["properties"]
    thinking = resources.settings.ollama_thinking_tokens
    assert body["options"]["num_predict"] == PLANNER_OUTPUT + thinking


async def test_given_a_local_turn_with_thinking_on_when_compacting_then_it_thinks(
    resources, monkeypatch
):
    from app.integrations.model_catalog import local_spec

    spec = local_spec("ifm-k2-horizon-7b")
    await install_thinking_model(resources, spec)
    local, hosted = await local_runtime(
        monkeypatch, resources, spec, lambda body: ollama_reply(SUMMARY_V1)
    )
    _, _, chat_id = await seed_chat(resources)
    await add_turns(resources, chat_id, turns(3), model=spec.key)
    resources.settings.memory_compaction_ratio = 0.01
    job_id = await maybe_enqueue(resources, chat_id, spec.key, "on")
    await run_job(resources, job_id)
    assert hosted == [] and local[0]["think"] is True


def test_given_a_thinking_planner_when_timing_it_then_the_limit_outlasts_a_cpu_model(resources):
    from app.services.memory import PLANNER_TIMEOUT_SECONDS, planner_timeout

    settings = resources.settings
    assert planner_timeout(settings, local=False, thinks=False) == PLANNER_TIMEOUT_SECONDS
    assert planner_timeout(settings, local=False, thinks=True) > PLANNER_TIMEOUT_SECONDS
    assert planner_timeout(settings, local=True, thinks=True) >= 300
    assert planner_timeout(settings, local=True, thinks=False) == PLANNER_TIMEOUT_SECONDS
