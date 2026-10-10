"""A question's pill mentions join their papers to the chat with the question (ARA-096).

Missing papers are added in the transaction that stores the question, so a refused question adds
nothing, and a replayed request UUID never adds papers or generates again.
"""

import json
from uuid import uuid4

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.core.errors import AppError
from app.models.research import ChatMessage, ChatPaper, Paper
from tests.support.answers import ask, first_handle, named, use_hosted
from tests.support.chats import new_chat
from tests.support.evidence import seed_structured
from tests.support.models import hosted_responses
from tests.support.providers import openai_fixture

pytestmark = pytest.mark.integration

LABEL = "Researcher 2024"
QUESTION = f"What does {LABEL} report on recall?"


def mention(paper_id, start: int = 10, label: str = LABEL) -> dict:
    return {"paper_id": str(paper_id), "label": label, "start": start, "end": start + len(label)}


def client_for(resources):
    from app.main import create_app

    app = create_app(resources.settings)
    app.state.resources = resources
    return httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test")


@pytest.fixture
def answers(resources, monkeypatch):
    """Fixture embeddings, a planner without sub-questions and an answer citing one passage."""
    from app.integrations import embeddings
    from app.rag import pipeline

    monkeypatch.setattr(
        pipeline,
        "create_embedder",
        lambda resources, profile: embeddings.create_embedder(
            resources, profile, transport=openai_fixture([])
        ),
    )
    plan = {
        "standalone_question": QUESTION,
        "search_queries": ["recall"],
        "needs_paper_evidence": True,
        "sub_questions": [],
    }
    hosted_responses(monkeypatch, resources, lambda body: json.dumps(plan))
    calls = []
    use_hosted(monkeypatch, resources, calls, lambda body: f"Recall rose [{first_handle(body)}].")
    return calls


async def links(resources, chat_id) -> list[tuple]:
    async with resources.sessions() as session:
        rows = await session.scalars(
            select(ChatPaper).where(ChatPaper.chat_id == chat_id).order_by(ChatPaper.ordinal)
        )
        return [(row.paper_id, row.document_id) for row in rows]


async def messages(resources, chat_id) -> list[ChatMessage]:
    async with resources.sessions() as session:
        return list(
            (
                await session.scalars(
                    select(ChatMessage)
                    .where(ChatMessage.session_id == chat_id)
                    .order_by(ChatMessage.created_at, ChatMessage.role.desc())
                )
            ).all()
        )


async def test_given_a_paper_outside_the_chat_when_a_question_mentions_it_then_it_joins_on_send(
    resources, answers
):
    first, first_pdf, _ = await seed_structured(resources)
    second, second_pdf, _ = await seed_structured(resources, title="Dense Retrieval at Scale")
    chat_id = await new_chat(resources, (first, first_pdf))
    prepared, events = await ask(resources, chat_id, QUESTION, mentions=[mention(second)])
    assert named(events, "message.completed")

    # The paper is pinned to its active PDF and its evidence reached the answer.
    assert await links(resources, chat_id) == [(first, first_pdf), (second, second_pdf)]
    assert prepared.mentioned == [1]
    (request,) = answers
    assert "Paper 2: Dense Retrieval at Scale" in request["input"][-1]["content"]
    user, _ = await messages(resources, chat_id)
    assert user.configuration == {"mentions": [mention(second)]}

    async with client_for(resources) as client:
        history = (await client.get(f"/api/v1/chats/{chat_id}/messages")).json()["items"]
    assert [item["mentions"] for item in history] == [[mention(second)], []]


async def test_given_a_paper_already_in_the_chat_when_mentioned_then_it_is_named_and_not_added(
    resources, answers
):
    first, first_pdf, _ = await seed_structured(resources)
    second, second_pdf, _ = await seed_structured(resources, title="Dense Retrieval at Scale")
    chat_id = await new_chat(resources, (first, first_pdf), (second, second_pdf))
    prepared, _ = await ask(resources, chat_id, QUESTION, mentions=[mention(second)])
    assert prepared.mentioned == [1]
    assert await links(resources, chat_id) == [(first, first_pdf), (second, second_pdf)]


async def test_given_a_replayed_request_uuid_then_mentions_neither_add_papers_nor_generate_again(
    resources, answers
):
    first, first_pdf, _ = await seed_structured(resources)
    second, _, _ = await seed_structured(resources, title="Dense Retrieval at Scale")
    chat_id = await new_chat(resources, (first, first_pdf))
    request_id = uuid4()
    _, events = await ask(
        resources, chat_id, QUESTION, request_id=request_id, mentions=[mention(second)]
    )
    (answer,) = named(events, "message.completed")
    async with client_for(resources) as client:
        removed = await client.delete(f"/api/v1/chats/{chat_id}/papers/{second}")
        assert removed.status_code == 200, removed.text

    replay, events = await ask(
        resources, chat_id, QUESTION, request_id=request_id, mentions=[mention(second)]
    )
    assert replay.replay
    assert named(events, "message.completed")[0]["id"] == answer["id"]
    assert len(answers) == 1
    assert await links(resources, chat_id) == [(first, first_pdf)]

    # The same UUID with other mentions is a different message.
    for other in ([], [mention(first)]):
        with pytest.raises(HTTPException) as conflict:
            await ask(resources, chat_id, QUESTION, request_id=request_id, mentions=other)
        assert conflict.value.status_code == 409


async def test_given_a_question_that_is_refused_then_its_mentioned_papers_are_not_added(
    resources, answers
):
    from app.integrations.llm import LLMError

    first, first_pdf, _ = await seed_structured(resources)
    second, _, _ = await seed_structured(resources, title="Dense Retrieval at Scale")
    async with resources.sessions() as session, session.begin():
        bare = Paper(title="Metadata only", metadata_provenance={})
        session.add(bare)
        await session.flush()
        bare_id = bare.id
    chat_id = await new_chat(resources, (first, first_pdf))

    # Mentions are validated against the library before anything is stored.
    both = f"Does {LABEL} agree with {LABEL}?"
    for paper_id, status, code in (
        (uuid4(), 404, "PAPER_NOT_FOUND"),
        (bare_id, 409, "PAPER_NOT_READY"),
    ):
        with pytest.raises(AppError) as refused:
            await ask(
                resources, chat_id, both, mentions=[mention(second, 5), mention(paper_id, 32)]
            )
        assert (refused.value.status_code, refused.value.code) == (status, code)
    assert await links(resources, chat_id) == [(first, first_pdf)]
    assert await messages(resources, chat_id) == []

    # The budget refuses the question after its papers were added: the transaction takes them back.
    resources.settings.llm_daily_budget_usd = 0
    with pytest.raises(LLMError) as spent:
        await ask(resources, chat_id, QUESTION, mentions=[mention(second)])
    assert spent.value.code == "DAILY_BUDGET_EXCEEDED"
    assert await links(resources, chat_id) == [(first, first_pdf)]
    assert await messages(resources, chat_id) == []


@pytest.mark.open_models
async def test_given_a_mention_that_makes_a_chat_several_papers_then_local_models_are_refused(
    resources,
):
    from app.integrations.llm import LLMError

    first, first_pdf, _ = await seed_structured(resources)
    second, _, _ = await seed_structured(resources, title="Dense Retrieval at Scale")
    chat_id = await new_chat(resources, (first, first_pdf))
    with pytest.raises(LLMError) as refused:
        await ask(
            resources,
            chat_id,
            QUESTION,
            mentions=[mention(second)],
            model="ifm-k2-horizon-7b",
            reasoning_effort="default",
        )
    assert (refused.value.code, refused.value.status) == ("MULTI_PAPER_LOCAL", 409)
    assert await links(resources, chat_id) == [(first, first_pdf)]
