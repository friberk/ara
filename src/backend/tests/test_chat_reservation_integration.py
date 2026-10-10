"""Answers reserve a realistic prompt bound on the daily ledger, not the whole window (ARA-076)."""

from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.models.research import ChatMessage, ChatSession, GenerationReservation
from tests.support.answers import ask, first_handle, named, use_hosted
from tests.support.evidence import seed_structured
from tests.support.models import hosted_responses

pytestmark = pytest.mark.integration


@pytest.fixture
def reserved(monkeypatch):
    """Input tokens passed to the ledger, per call to `reserve`."""
    from app.services import chat

    calls, original = [], chat.reserve

    async def spy(resources, model, input_tokens):
        calls.append((model, input_tokens))
        await original(resources, model, input_tokens)

    monkeypatch.setattr(chat, "reserve", spy)
    return calls


async def chat_with_history(resources) -> object:
    from app.repositories.jobs import now

    paper_id, document_id, _ = await seed_structured(resources, profile=None)
    earlier = now() - timedelta(minutes=5)
    async with resources.sessions() as session, session.begin():
        chat = ChatSession(paper_id=paper_id, document_id=document_id, title="Discussion")
        session.add(chat)
        await session.flush()
        session.add_all(
            [
                ChatMessage(
                    session_id=chat.id,
                    role=role,
                    content=content,
                    state="completed",
                    model="gpt-5.6-luna" if role == "assistant" else None,
                    reasoning_effort="low" if role == "assistant" else None,
                    request_id=uuid4(),
                    created_at=earlier + timedelta(seconds=index),
                )
                for index, (role, content) in enumerate(
                    [
                        ("user", "What does the paper study?"),
                        ("assistant", "Sparse retrieval for scientific question answering."),
                    ]
                )
            ]
        )
        return chat.id


async def ledger_rows(resources) -> int:
    async with resources.sessions() as session:
        return await session.scalar(select(func.count()).select_from(GenerationReservation))


def counted(body) -> int:
    from app.integrations.context_registry import hosted_profile
    from app.integrations.tokens import PromptMessage, count_messages

    counter = hosted_profile(body["model"], "none").counter
    messages = [PromptMessage("system", body["instructions"])] + [
        PromptMessage("user" if item["role"] == "developer" else item["role"], item["content"])
        for item in body["input"]
    ]
    return count_messages(counter, messages)


async def test_given_hosted_question_when_preparing_then_the_reservation_bounds_the_prompt(
    resources, monkeypatch, reserved
):
    from app.integrations.context_registry import hosted_profile

    chat_id = await chat_with_history(resources)
    calls = []
    use_hosted(monkeypatch, resources, calls, lambda body: f"Answer [{first_handle(body)}].")
    hosted_responses(monkeypatch, resources, lambda body: "not a plan")  # planning falls back
    _, events = await ask(resources, chat_id, "How does BM25 recall compare with dense vectors?")
    assert named(events, "message.completed")
    ((model, tokens),) = reserved
    budget = hosted_profile(model, "low").input_budget
    assert counted(calls[0]) <= tokens < budget
    # The bound is realistic: well under a third of the 272K working budget here.
    assert tokens < budget // 3


@pytest.mark.open_models
async def test_given_local_question_when_preparing_then_nothing_is_reserved(resources, reserved):
    from tests.test_ai_integration import local_fixture, paper_fixture

    spec, _ = await local_fixture(resources)
    _, _, chat_id = await paper_fixture(resources)
    _, events = await ask(
        resources, chat_id, "What accuracy?", model=spec.key, reasoning_effort="default"
    )
    assert named(events, "message.completed")
    assert await ledger_rows(resources) == 0


async def test_given_replayed_request_when_preparing_then_nothing_more_is_reserved(
    resources, monkeypatch, reserved
):
    chat_id = await chat_with_history(resources)
    use_hosted(monkeypatch, resources, [], lambda body: f"Answer [{first_handle(body)}].")
    hosted_responses(monkeypatch, resources, lambda body: "not a plan")  # planning falls back
    question, request_id = "How does BM25 recall compare?", uuid4()
    await ask(resources, chat_id, question, request_id=request_id)
    rows = await ledger_rows(resources)
    replay, _ = await ask(resources, chat_id, question, request_id=request_id)
    assert replay.replay and len(reserved) == 1 and await ledger_rows(resources) == rows
