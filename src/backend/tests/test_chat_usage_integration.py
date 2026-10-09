"""The context and cost meter beside the composer reads one usage record per chat (ARA-085)."""

import json
from decimal import Decimal
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select, update

from app.integrations.context_registry import context_profile
from app.integrations.model_catalog import LOCAL_MODELS
from app.models.memory import ChatMemory
from app.models.research import ChatMessage
from app.services.costs import call_cost, embedding_cost, rerank_cost
from tests.support.answers import ask, first_handle, named, use_hosted
from tests.support.chats import add_turns, seed_chat
from tests.support.evidence import seed_structured
from tests.support.models import hosted_responses
from tests.support.providers import openai_fixture
from tests.test_long_conversation_integration import new_chat

pytestmark = pytest.mark.integration

LUNA, SOL = "gpt-5.6-luna", "gpt-5.6-sol"
LOCAL = next(iter(LOCAL_MODELS))
EMBED, RERANK = "openai-3-large", "openai-gpt-6-luna"


@pytest.fixture
async def client(resources):
    from app.main import create_app

    app = create_app(resources.settings)
    app.state.resources = resources
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as http:
        yield http


async def usage(client, chat_id, model=LUNA, effort="low"):
    return await client.get(
        f"/api/v1/chats/{chat_id}/usage", params={"model": model, "reasoning_effort": effort}
    )


def dollars(amount: Decimal) -> str:
    return format(amount.quantize(Decimal("0.00000001")), "f")


async def record(resources, message_id, **fields) -> None:
    async with resources.sessions() as session, session.begin():
        await session.execute(
            update(ChatMessage).where(ChatMessage.id == message_id).values(**fields)
        )


async def test_given_a_chat_with_no_turns_when_reading_usage_then_it_is_empty_and_free(
    resources, client
):
    _, _, chat_id = await seed_chat(resources)
    response = await usage(client, chat_id)
    assert response.status_code == 200, response.text
    body = response.json()
    profile = context_profile(resources, LUNA, "low")
    assert body["context"] == {
        "used_tokens": None,
        "input_budget": profile.input_budget,
        "window": profile.window,
        "model": LUNA,
    }
    assert body["cost"]["total"] == "0.00000000"
    assert body["cost"]["local"] is False and body["cost"]["unrecorded_turns"] == 0


async def test_given_an_unknown_chat_when_reading_usage_then_404(client):
    assert (await usage(client, uuid4())).status_code == 404


async def test_given_a_bad_model_when_reading_usage_then_422(resources, client):
    _, _, chat_id = await seed_chat(resources)
    assert (await usage(client, chat_id, "no-such-model")).status_code == 422


async def test_given_recorded_calls_when_reading_usage_then_the_cost_sums_each_kind_by_catalog(
    resources, client
):
    _, _, chat_id = await seed_chat(resources)
    first, second = await add_turns(
        resources, chat_id, [("What is it?", "A study."), ("And the result?", "Better.")]
    )
    billed_embedding = {"profile": EMBED, "tokens": 40_000}
    billed_rerank = {"profile": RERANK, "tokens": 90_000}
    await record(
        resources,
        first.answer,
        model=SOL,
        usage={"input_tokens": 3_000, "output_tokens": 400},
        context={"window": 1, "input_tokens": 2_500, "output_reserved": 1},
        retrieval={"billed": {"embedding": billed_embedding, "rerank": billed_rerank}},
    )
    planner = {"model": LUNA, "input_tokens": 700, "output_tokens": 60}
    await record(
        resources,
        second.answer,
        model=LUNA,
        usage={"input_tokens": 5_000, "output_tokens": 800},
        context={"window": 1, "input_tokens": 4_321, "output_reserved": 1},
        retrieval={
            "billed": {"planner": planner, "embedding": billed_embedding, "rerank": billed_rerank}
        },
    )
    async with resources.sessions() as session, session.begin():
        session.add(
            ChatMemory(
                session_id=chat_id,
                version=1,
                through_message_id=first.answer,
                summary="- The study.",
                token_count=4,
                model=LUNA,
                prompt_version="test",
                usage={"input_tokens": 6_000, "output_tokens": 300},
            )
        )

    body = (await usage(client, chat_id, LUNA)).json()

    answers = call_cost(SOL, {"input_tokens": 3_000, "output_tokens": 400}) + call_cost(
        LUNA, {"input_tokens": 5_000, "output_tokens": 800}
    )
    planning = call_cost(LUNA, planner)
    compaction = call_cost(LUNA, {"input_tokens": 6_000, "output_tokens": 300})
    embeddings = embedding_cost(EMBED, 40_000) * 2
    reranking = rerank_cost(RERANK, 90_000) * 2
    cost = body["cost"]
    assert cost["answers"] == dollars(answers)
    assert cost["planning"] == dollars(planning)
    assert cost["compaction"] == dollars(compaction)
    assert cost["embeddings"] == dollars(embeddings)
    assert cost["reranking"] == dollars(reranking)
    assert cost["total"] == dollars(answers + planning + compaction + embeddings + reranking)
    assert cost["local"] is False and cost["unrecorded_turns"] == 0
    # "Used" is what the latest completed turn sent.
    assert body["context"]["used_tokens"] == 4_321


async def test_given_turns_without_records_when_reading_usage_then_they_are_counted_not_priced(
    resources, client
):
    _, _, chat_id = await seed_chat(resources)
    old, new = await add_turns(resources, chat_id, [("Old?", "Old."), ("New?", "New.")])
    await record(resources, new.answer, usage={"input_tokens": 1_000_000, "output_tokens": 0})
    body = (await usage(client, chat_id)).json()
    assert body["cost"]["total"] == dollars(
        call_cost(LUNA, {"input_tokens": 1_000_000, "output_tokens": 0})
    )
    assert body["cost"]["unrecorded_turns"] == 1
    assert body["context"]["used_tokens"] is None  # the latest turn recorded no context


async def test_given_a_local_chat_when_reading_usage_then_it_costs_nothing_and_says_local(
    resources, client
):
    _, _, chat_id = await seed_chat(resources)
    (turn,) = await add_turns(resources, chat_id, [("Q?", "A.")], model=LOCAL)
    await record(
        resources,
        turn.answer,
        usage={"input_tokens": 2_000, "output_tokens": 300},
        context={"window": 8192, "input_tokens": 1_900, "output_reserved": 2048},
        retrieval={
            "billed": {"planner": {"model": LOCAL, "input_tokens": 400, "output_tokens": 30}}
        },
    )
    body = (await usage(client, chat_id, LOCAL, "default")).json()
    assert body["cost"]["total"] == "0.00000000" and body["cost"]["local"] is True
    assert body["context"]["used_tokens"] == 1_900


async def test_given_a_model_switch_when_reading_usage_then_the_budget_follows_the_model(
    resources, client
):
    _, _, chat_id = await seed_chat(resources)
    hosted = (await usage(client, chat_id, LUNA)).json()["context"]
    local = (await usage(client, chat_id, LOCAL, "default")).json()["context"]
    assert hosted["input_budget"] == context_profile(resources, LUNA, "low").input_budget
    assert local["input_budget"] == context_profile(resources, LOCAL, "none").input_budget
    assert hosted["input_budget"] != local["input_budget"]
    assert local["window"] == resources.settings.ollama_context_window and local["model"] == LOCAL


@pytest.fixture
def embeddings(resources, monkeypatch):
    from app.integrations import embeddings
    from app.rag import pipeline
    from app.services import memory

    calls = []

    def fixture_embedder(resources, profile):
        return embeddings.create_embedder(resources, profile, transport=openai_fixture(calls))

    monkeypatch.setattr(pipeline, "create_embedder", fixture_embedder)
    monkeypatch.setattr(memory, "create_embedder", fixture_embedder)
    return calls


async def test_given_a_hosted_follow_up_when_answering_then_each_billed_call_is_recorded(
    resources, monkeypatch, embeddings
):
    paper_id, document_id, _ = await seed_structured(resources)
    chat_id = await new_chat(resources, paper_id, document_id)
    plan = {
        "standalone_question": "How much does dense retrieval improve recall over BM25?",
        "search_queries": ["dense retrieval recall BM25"],
        "needs_paper_evidence": True,
    }
    hosted_responses(monkeypatch, resources, lambda body: json.dumps(plan))
    use_hosted(monkeypatch, resources, [], lambda body: f"Dense wins [{first_handle(body)}].")
    await ask(resources, chat_id, "What does the paper compare?")
    _, events = await ask(resources, chat_id, "How much did it improve?")
    (completed,) = named(events, "message.completed")

    async with resources.sessions() as session:
        rows = (
            await session.scalars(select(ChatMessage).where(ChatMessage.id.in_([completed["id"]])))
        ).all()
    (message,) = rows
    billed = message.retrieval["billed"]
    assert billed["planner"] == {"model": LUNA, "input_tokens": 20, "output_tokens": 5}
    assert billed["embedding"]["profile"] == EMBED and billed["embedding"]["tokens"] > 0
    assert billed["rerank"]["profile"] == RERANK and billed["rerank"]["tokens"] > 0
