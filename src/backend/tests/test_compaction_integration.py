"""Versioned running summaries of long conversations on real PostgreSQL (ARA-077)."""

import asyncio
import json
from uuid import uuid4

import httpx
import pytest
from pydantic import ValidationError
from sqlalchemy import func, select

from app.core.config import Settings
from app.models.jobs import BackgroundJob
from app.models.memory import ChatMemory
from app.repositories.jobs import claim, enqueue
from tests.support.chats import add_turns, seed_chat, snapshot
from tests.support.models import (
    hosted_responses,
    install_thinking_model,
    local_runtime,
    ollama_reply,
)

pytestmark = pytest.mark.integration

SUMMARY_V1 = (
    "## User goals\nCompare recall across passages.\n"
    "## Established facts (with pages)\nPassage 0 reports recall 0 (p. 1).\n"
    "## Questions asked\nWhat is recall?\n## Open threads\nNone.\n"
    "## Preferences/corrections\nNone."
)
SUMMARY_V2 = SUMMARY_V1.replace("None.\n## Pref", "Datasets.\n## Pref")


def turns(count: int, start: int = 0):
    """Turns of similar size (about a hundred tokens each); answers cite page 1."""
    result = []
    for index in range(start, start + count):
        chunk = uuid4()
        citation = {"chunk_id": str(chunk), "document_id": str(uuid4()), "page": 1, "excerpt": "x"}
        answer = f"Turn {index} finding: " + "recall improves steadily " * 20 + f"[source:{chunk}]."
        result.append((f"Question {index}: how does recall change?", answer, [citation]))
    return result


async def maybe_enqueue(resources, chat_id, model="gpt-5.6-luna"):
    from app.services.memory import maybe_enqueue_compaction

    async with resources.sessions() as session, session.begin():
        job = await maybe_enqueue_compaction(session, chat_id, model, settings=resources.settings)
        return job.id if job else None


async def compact_jobs(resources):
    async with resources.sessions() as session:
        return (
            await session.scalars(
                select(BackgroundJob)
                .where(BackgroundJob.kind == "compact_chat")
                .order_by(BackgroundJob.created_at)
            )
        ).all()


async def run_job(resources, job_id):
    from app.services.memory import run_compact_job

    async with resources.sessions() as session:
        job = await session.get(BackgroundJob, job_id)
        generation, payload = job.generation, job.payload
    token = await claim(resources.sessions, job_id, generation)
    assert token is not None
    await run_compact_job(resources, job_id, generation, token, payload)
    return generation, token, payload


async def memories(resources, chat_id):
    async with resources.sessions() as session:
        return (
            await session.scalars(
                select(ChatMemory)
                .where(ChatMemory.session_id == chat_id)
                .order_by(ChatMemory.version)
            )
        ).all()


async def load_job(resources, job_id):
    async with resources.sessions() as session:
        return await session.get(BackgroundJob, job_id)


def test_given_settings_when_loading_then_compaction_ratio_defaults_and_validates(monkeypatch):
    assert Settings(app_env="test").memory_compaction_ratio == 0.6
    monkeypatch.setenv("MEMORY_COMPACTION_RATIO", "0.05")
    assert Settings(app_env="test").memory_compaction_ratio == 0.05
    monkeypatch.setenv("MEMORY_COMPACTION_RATIO", "0")
    with pytest.raises(ValidationError):
        Settings(app_env="test")


async def test_given_unsummarized_turns_below_threshold_when_turn_completes_then_no_job(
    resources,
):
    _, _, chat_id = await seed_chat(resources)
    await add_turns(resources, chat_id, turns(3))
    assert await maybe_enqueue(resources, chat_id) is None
    assert await compact_jobs(resources) == []


async def test_given_turns_over_threshold_when_turn_completes_then_one_job_for_oldest_half(
    resources,
):
    _, _, chat_id = await seed_chat(resources)
    added = await add_turns(resources, chat_id, turns(3))
    resources.settings.memory_compaction_ratio = 0.01
    job_id = await maybe_enqueue(resources, chat_id)
    assert job_id is not None
    job = await load_job(resources, job_id)
    # The oldest half by tokens; the newest turn always stays verbatim.
    assert job.payload == {
        "chat_id": str(chat_id),
        "through_message_id": str(added[0].answer),
        "model": "gpt-5.6-luna",
    }
    assert await maybe_enqueue(resources, chat_id) is None
    assert [job.id for job in await compact_jobs(resources)] == [job_id]


async def test_given_single_long_turn_when_over_threshold_then_newest_turn_is_kept(resources):
    _, _, chat_id = await seed_chat(resources)
    await add_turns(resources, chat_id, turns(1))
    resources.settings.memory_compaction_ratio = 0.01
    assert await maybe_enqueue(resources, chat_id) is None


async def test_given_compaction_when_delivered_twice_then_one_version_and_messages_unchanged(
    resources, monkeypatch
):
    requests = hosted_responses(monkeypatch, resources, lambda body: SUMMARY_V1)
    _, _, chat_id = await seed_chat(resources)
    added = await add_turns(resources, chat_id, turns(3), model="gpt-5.6-sol")
    before = await snapshot(resources, chat_id)
    resources.settings.memory_compaction_ratio = 0.01
    job_id = await maybe_enqueue(resources, chat_id, "gpt-5.6-sol")
    generation, token, payload = await run_job(resources, job_id)
    from app.services.memory import run_compact_job

    # A redelivery of the finished generation holds no lease and calls nothing.
    await run_compact_job(resources, job_id, generation, token, payload)
    (memory,) = await memories(resources, chat_id)
    assert (memory.version, memory.through_message_id) == (1, added[0].answer)
    assert memory.summary == SUMMARY_V1 and memory.model == "gpt-5.6-luna"
    assert memory.prompt_version == "1" and memory.token_count > 0
    assert len(requests) == 1
    (body,) = requests
    assert body["model"] == "gpt-5.6-luna" and body["reasoning"] == {"effort": "none"}
    sent = body["instructions"] + json.dumps(body["input"])
    for heading in (
        "User goals",
        "Established facts (with pages)",
        "Questions asked",
        "Open threads",
        "Preferences/corrections",
    ):
        assert heading in sent
    # Only the evicted turn, with citations rendered as page references.
    assert "Turn 0 finding" in sent and "(p. 1)" in sent and "[source:" not in sent
    assert "Turn 1 finding" not in sent and "Turn 2 finding" not in sent
    job = await load_job(resources, job_id)
    assert job.state == "completed" and job.result == {"version": 1}
    assert await snapshot(resources, chat_id) == before


async def test_given_racing_duplicate_jobs_when_both_generate_then_one_summary_version(
    resources, monkeypatch
):
    from app.services.memory import run_compact_job

    arrived, both = [], asyncio.Event()

    async def output(body):
        arrived.append(body)
        if len(arrived) == 2:
            both.set()
        await asyncio.wait_for(both.wait(), 10)
        return SUMMARY_V1

    hosted_responses(monkeypatch, resources, output)
    _, _, chat_id = await seed_chat(resources)
    added = await add_turns(resources, chat_id, turns(3))
    payload = {
        "chat_id": str(chat_id),
        "through_message_id": str(added[0].answer),
        "model": "gpt-5.6-luna",
    }
    claims = []
    for _ in range(2):
        async with resources.sessions() as session, session.begin():
            job = await enqueue(session, kind="compact_chat", payload=payload)
        claims.append((job.id, await claim(resources.sessions, job.id, 1)))
    await asyncio.gather(
        *(run_compact_job(resources, job_id, 1, token, payload) for job_id, token in claims)
    )
    (memory,) = await memories(resources, chat_id)
    assert memory.version == 1 and len(arrived) == 2
    states = sorted([(await load_job(resources, job_id)).result for job_id, _ in claims], key=str)
    assert states == [{"skipped": True}, {"version": 1}]


async def test_given_summary_v1_when_compacting_again_then_v2_builds_on_v1(resources, monkeypatch):
    outputs = iter([SUMMARY_V1, SUMMARY_V2])
    requests = hosted_responses(monkeypatch, resources, lambda body: next(outputs))
    _, _, chat_id = await seed_chat(resources)
    added = await add_turns(resources, chat_id, turns(3))
    resources.settings.memory_compaction_ratio = 0.01
    await run_job(resources, await maybe_enqueue(resources, chat_id))
    added += await add_turns(resources, chat_id, turns(3, start=3))
    job_id = await maybe_enqueue(resources, chat_id)
    assert (await load_job(resources, job_id)).payload["through_message_id"] == str(added[2].answer)
    await run_job(resources, job_id)
    first, second = await memories(resources, chat_id)
    assert (second.version, second.through_message_id, second.summary) == (
        2,
        added[2].answer,
        SUMMARY_V2,
    )
    sent = json.dumps(requests[1]["input"])
    assert json.dumps(SUMMARY_V1)[1:-1] in sent
    assert "Turn 1 finding" in sent and "Turn 2 finding" in sent
    assert "Turn 0 finding" not in sent and "Turn 3 finding" not in sent


async def test_given_covered_range_when_stale_job_runs_then_it_skips_without_a_call(
    resources, monkeypatch
):
    requests = hosted_responses(monkeypatch, resources, lambda body: SUMMARY_V1)
    _, _, chat_id = await seed_chat(resources)
    added = await add_turns(resources, chat_id, turns(4))
    later = {
        "chat_id": str(chat_id),
        "through_message_id": str(added[1].answer),
        "model": "gpt-5.6-luna",
    }
    earlier = {**later, "through_message_id": str(added[0].answer)}
    async with resources.sessions() as session, session.begin():
        later_job = await enqueue(session, kind="compact_chat", payload=later)
        earlier_job = await enqueue(session, kind="compact_chat", payload=earlier)
    await run_job(resources, later_job.id)
    await run_job(resources, earlier_job.id)
    (memory,) = await memories(resources, chat_id)
    assert memory.through_message_id == added[1].answer and len(requests) == 1
    assert (await load_job(resources, earlier_job.id)).result == {"skipped": True}


async def test_given_local_chat_when_compacting_then_local_model_and_no_hosted_call(
    resources, monkeypatch
):
    from app.integrations.model_catalog import local_spec

    spec = local_spec("ifm-k2-horizon-7b")
    await install_thinking_model(resources, spec)
    local, hosted = await local_runtime(
        monkeypatch, resources, spec, lambda body: ollama_reply(SUMMARY_V1)
    )
    _, _, chat_id = await seed_chat(resources)
    added = await add_turns(resources, chat_id, turns(3), model=spec.key)
    resources.settings.memory_compaction_ratio = 0.01
    job_id = await maybe_enqueue(resources, chat_id, spec.key)
    await run_job(resources, job_id)
    (memory,) = await memories(resources, chat_id)
    assert (memory.model, memory.through_message_id) == (spec.key, added[0].answer)
    assert hosted == []
    (body,) = local
    assert body["model"] == spec.model_id and body["think"] is False
    assert "Turn 0 finding" in json.dumps(body["messages"])


async def test_given_busy_local_runtime_when_compacting_then_job_waits_without_attempts(
    resources, monkeypatch
):
    from app.integrations.model_catalog import local_spec
    from app.repositories.local_models import acquire_use, release_use

    spec = local_spec("ifm-k2-horizon-7b")
    await install_thinking_model(resources, spec)
    local, hosted = await local_runtime(
        monkeypatch, resources, spec, lambda body: ollama_reply(SUMMARY_V1)
    )
    _, _, chat_id = await seed_chat(resources)
    await add_turns(resources, chat_id, turns(3), model=spec.key)
    resources.settings.memory_compaction_ratio = 0.01
    job_id = await maybe_enqueue(resources, chat_id, spec.key)
    use = await acquire_use(resources.sessions, spec.key)
    try:
        await run_job(resources, job_id)
    finally:
        await release_use(resources.sessions, use)
    job = await load_job(resources, job_id)
    assert (job.state, job.stage, job.attempts, job.generation) == (
        "queued",
        "local_runtime_wait",
        0,
        2,
    )
    assert not job.payload.get("paid_call_inflight")
    assert local == [] and hosted == [] and await memories(resources, chat_id) == []


async def test_given_interrupted_paid_call_when_redelivered_then_no_new_generation(
    resources, monkeypatch
):
    requests = hosted_responses(monkeypatch, resources, lambda body: SUMMARY_V1)
    _, _, chat_id = await seed_chat(resources)
    added = await add_turns(resources, chat_id, turns(3))
    payload = {
        "chat_id": str(chat_id),
        "through_message_id": str(added[0].answer),
        "model": "gpt-5.6-luna",
        "paid_call_inflight": True,
    }
    async with resources.sessions() as session, session.begin():
        job = await enqueue(session, kind="compact_chat", payload=payload)
    await run_job(resources, job.id)
    job = await load_job(resources, job.id)
    assert (job.state, job.error_code) == ("failed", "GENERATION_OUTCOME_UNKNOWN")
    assert requests == [] and await memories(resources, chat_id) == []


@pytest.fixture
async def client(resources):
    from app.main import create_app

    app = create_app(resources.settings)
    app.state.resources = resources
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as http:
        yield http


async def test_given_summary_when_reading_chat_memory_then_summary_and_covered_messages(
    resources, monkeypatch, client
):
    hosted_responses(monkeypatch, resources, lambda body: SUMMARY_V1)
    _, _, chat_id = await seed_chat(resources)
    await add_turns(resources, chat_id, turns(3))
    response = await client.get(f"/api/v1/chats/{chat_id}/memory")
    assert response.status_code == 200, response.text
    assert response.json() == {"memory": None, "total_messages": 6}
    resources.settings.memory_compaction_ratio = 0.01
    await run_job(resources, await maybe_enqueue(resources, chat_id))
    response = await client.get(f"/api/v1/chats/{chat_id}/memory")
    assert response.status_code == 200, response.text
    state = response.json()
    assert state["total_messages"] == 6
    memory = state["memory"]
    assert (memory["version"], memory["summary"], memory["summarized_messages"]) == (
        1,
        SUMMARY_V1,
        2,
    )
    assert memory["model"] == "gpt-5.6-luna" and memory["created_at"]
    missing = await client.get(f"/api/v1/chats/{uuid4()}/memory")
    assert missing.status_code == 404
    async with resources.sessions() as session:
        assert await session.scalar(select(func.count()).select_from(ChatMemory)) == 1
