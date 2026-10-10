"""Answers use the running summary, recalled turns and planned queries (ARA-077)."""

import json
import re
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import func, select, update

from app.models.jobs import BackgroundJob
from app.models.research import ChatMessage
from app.repositories.jobs import claim
from tests.support.answers import ask, first_handle, named, use_hosted
from tests.support.chats import new_chat as chat_with_papers
from tests.support.evidence import seed_structured
from tests.support.models import (
    hosted_responses,
    install_thinking_model,
    local_runtime,
    ollama_reply,
)
from tests.support.providers import openai_fixture

pytestmark = pytest.mark.integration

FACT_QUESTION = "My project uses Natural Questions. Which baselines suit it?"
FINAL_QUESTION = "Remind me which dataset my project uses?"
FACT = re.compile(r"project uses (Natural Questions)")
HANDLE = re.compile(r"^\[(S\d+)\] ", re.M)


def question(turn: int) -> str:
    if turn == 2:
        return FACT_QUESTION
    if turn == 40:
        return FINAL_QUESTION
    return f"Question {turn}: how does recall change in setting {turn}?"


def local_model(body) -> httpx.Response:
    """One fixture model that plans, compacts and answers, like the chat's local model."""
    messages = body["messages"]
    prompt = messages[-1]["content"]
    if "format" in body:
        asked = prompt.rsplit("Follow-up question: ", 1)[-1]
        plan = {"standalone_question": asked, "search_queries": [asked]}
        return ollama_reply(json.dumps({**plan, "needs_paper_evidence": True}))
    if messages[0]["content"].startswith("You keep a running summary"):
        facts = sorted(set(FACT.findall(prompt)))
        known = "\n".join(f"- The user's project uses {name} (p. 1)." for name in facts)
        return ollama_reply(
            "## User goals\nCompare retrieval settings.\n"
            f"## Established facts (with pages)\n{known or 'None.'}\n"
            "## Questions asked\nHow recall changes.\n## Open threads\nNone.\n"
            "## Preferences/corrections\nNone."
        )
    handle = HANDLE.findall(prompt)[0]
    if prompt.endswith("Question: " + FACT_QUESTION):
        return ollama_reply(
            f"Noted: your project uses Natural Questions, so compare against BM25 [{handle}]."
        )
    filler = "Recall improves steadily as more passages are retrieved in this setting. "
    return ollama_reply(filler * 3 + f"[{handle}].")


@pytest.fixture
def embeddings(resources, monkeypatch):
    """Query and turn embeddings come from the deterministic OpenAI fixture."""
    from app.integrations import embeddings
    from app.rag import pipeline
    from app.services import memory

    calls = []

    def fixture_embedder(resources, profile):
        return embeddings.create_embedder(resources, profile, transport=openai_fixture(calls))

    monkeypatch.setattr(pipeline, "create_embedder", fixture_embedder)
    monkeypatch.setattr(memory, "create_embedder", fixture_embedder)
    return calls


async def new_chat(resources, paper_id, document_id):
    return await chat_with_papers(resources, (paper_id, document_id))


async def run_memory_jobs(resources) -> list[str]:
    """What the workers would do between turns, the reader pausing past the idle delay."""
    from app.services.memory import run_compact_job, run_embed_turn_job

    runners = {"compact_chat": run_compact_job, "embed_turn": run_embed_turn_job}
    waiting = (BackgroundJob.state == "queued", BackgroundJob.kind.in_(runners))
    async with resources.sessions() as session, session.begin():
        await session.execute(update(BackgroundJob).where(*waiting).values(available_at=func.now()))
    async with resources.sessions() as session:
        jobs = (
            await session.scalars(
                select(BackgroundJob).where(*waiting).order_by(BackgroundJob.created_at)
            )
        ).all()
    for job in jobs:
        token = await claim(resources.sessions, job.id, job.generation)
        await runners[job.kind](resources, job.id, job.generation, token, job.payload)
    return [job.kind for job in jobs]


async def conversation(resources, chat_id):
    async with resources.sessions() as session:
        rows = await session.scalars(
            select(ChatMessage)
            .where(ChatMessage.session_id == chat_id)
            .order_by(ChatMessage.created_at, ChatMessage.id)
        )
        return [(message.role, message.content, message.state) for message in rows]


@pytest.mark.open_models
async def test_given_forty_local_turns_when_asking_about_turn_two_then_memory_carries_it(
    resources, monkeypatch, embeddings
):
    from app.integrations.context_registry import context_profile
    from app.integrations.model_catalog import local_spec
    from app.integrations.tokens import PromptMessage, count_messages
    from app.services.context import RECALL_PREFIX, SUMMARY_PREFIX

    spec = local_spec("ifm-k2-horizon-7b")
    await install_thinking_model(resources, spec)
    local, hosted = await local_runtime(monkeypatch, resources, spec, local_model)
    paper_id, document_id, _ = await seed_structured(resources)
    chat_id = await new_chat(resources, paper_id, document_id)
    sent, upkeep = [], []
    for turn in range(1, 41):
        _, events = await ask(
            resources, chat_id, question(turn), model=spec.key, reasoning_effort="default"
        )
        (completed,) = named(events, "message.completed")
        sent += [
            ("user", question(turn), "completed"),
            ("assistant", completed["content"], "completed"),
        ]
        upkeep += await run_memory_jobs(resources)
    assert "compact_chat" in upkeep and upkeep.count("embed_turn") == 40
    answer = [body for body in local if body["stream"]][-1]
    messages = answer["messages"]
    assert messages[-1]["content"].endswith("Question: " + FINAL_QUESTION)
    (summary,) = [m["content"] for m in messages if m["content"].startswith(SUMMARY_PREFIX)]
    assert "The user's project uses Natural Questions" in summary
    (recall,) = [m["content"] for m in messages if m["content"].startswith(RECALL_PREFIX)]
    assert FACT_QUESTION in recall and "Question 39" not in recall
    # Every request to the 8k local model fits its input budget.
    limits = context_profile(
        resources,
        spec.key,
        "default",
        thinking={"values": [True, False], "default": True},
    )
    assert limits.input_budget == 3072
    for body in local:
        prompt = [PromptMessage(m["role"], m["content"]) for m in body["messages"]]
        assert count_messages(limits.counter, prompt) <= limits.input_budget
    # Summarized turns are not resent verbatim, so the unsummarized recent turns fit whole.
    resent = [m["content"] for m in messages if m["role"] == "user"][:-1]
    assert resent and "Question 3:" not in " ".join(resent) and FACT_QUESTION not in resent
    context = completed["context"]
    assert context["summary_version"] >= 1 and context["recalled_turns"] >= 1
    assert context["truncated"] is False
    assert context["recent_turns"] >= 1 and context["input_tokens"] <= 3072
    assert hosted == []
    # Compaction and recall never alter the stored conversation.
    assert await conversation(resources, chat_id) == sent


async def test_given_hosted_follow_up_when_answering_then_planned_queries_drive_retrieval(
    resources, monkeypatch, embeddings
):
    paper_id, document_id, _ = await seed_structured(resources)
    chat_id = await new_chat(resources, paper_id, document_id)
    planned = {
        "standalone_question": "How much does dense retrieval improve recall over BM25?",
        "search_queries": ["dense retrieval recall BM25"],
        "needs_paper_evidence": True,
    }
    planner = hosted_responses(monkeypatch, resources, lambda body: json.dumps(planned))
    answers = []
    use_hosted(monkeypatch, resources, answers, lambda body: f"Dense wins [{first_handle(body)}].")
    await ask(resources, chat_id, "What does the paper compare?")
    assert planner == []  # The first turn is searched as asked.
    request_id = uuid4()
    _, events = await ask(resources, chat_id, "How much did it improve?", request_id=request_id)
    (completed,) = named(events, "message.completed")
    retrieval = completed["retrieval"]
    assert retrieval["standalone_query"] == planned["standalone_question"]
    assert retrieval["search_queries"] == planned["search_queries"]
    assert embeddings[-1]["input"] == planned["search_queries"]
    (plan_request,) = planner
    assert plan_request["model"] == "gpt-5.6-luna"
    assert "What does the paper compare?" in json.dumps(plan_request["input"])
    assert answers[-1]["input"][-1]["content"].startswith(
        f'Paper passages (retrieved for: "{planned["standalone_question"]}")'
    )
    # A replayed request UUID never plans, retrieves or generates again.
    await ask(resources, chat_id, "How much did it improve?", request_id=request_id)
    assert len(planner) == 1 and len(answers) == 2


async def test_given_completed_and_failed_answers_then_only_completed_turns_queue_upkeep(
    resources, monkeypatch, embeddings
):
    paper_id, document_id, _ = await seed_structured(resources)
    chat_id = await new_chat(resources, paper_id, document_id)
    replies = iter(["Cited [{}].", "No citation at all."])
    use_hosted(monkeypatch, resources, [], lambda body: next(replies).format(first_handle(body)))
    hosted_responses(monkeypatch, resources, lambda body: "not a plan")
    first, events = await ask(resources, chat_id, "What does the paper compare?")
    assert named(events, "message.completed")
    second, events = await ask(resources, chat_id, "And the latency?")
    assert named(events, "message.failed")
    async with resources.sessions() as session:
        jobs = (
            await session.scalars(select(BackgroundJob).where(BackgroundJob.kind == "embed_turn"))
        ).all()
    assert [job.payload["message_id"] for job in jobs] == [str(first.assistant.id)]


async def test_given_upkeep_cannot_be_queued_when_answer_completes_then_it_still_completes(
    resources, monkeypatch, embeddings
):
    from app.services import memory

    paper_id, document_id, _ = await seed_structured(resources)
    chat_id = await new_chat(resources, paper_id, document_id)
    use_hosted(monkeypatch, resources, [], lambda body: f"Cited [{first_handle(body)}].")

    async def broken(*args, **kwargs):
        raise RuntimeError("queue unavailable")

    monkeypatch.setattr(memory, "enqueue_embed_turn", broken)
    prepared, events = await ask(resources, chat_id, "What does the paper compare?")
    assert named(events, "message.completed") and not named(events, "message.failed")
    async with resources.sessions() as session:
        stored = await session.get(ChatMessage, prepared.assistant.id)
    assert stored.state == "completed"
