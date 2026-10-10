"""Five papers, a long conversation and a comparison stay inside every call's budget (ARA-088).

The planner call and the synthesis (answer) call are the model calls of a multi-paper answer;
sub-questions only search. Budgets come from the selected model's context profile, never a fixed
number, and one run shrinks that profile so floors must route.
"""

import json
import re
from dataclasses import replace

import pytest

from app.integrations.tokens import PromptMessage, count_messages
from app.models.research import ChatMessage, PaperSummary
from tests.support.answers import ask, named, use_hosted
from tests.support.chats import add_turns, new_chat
from tests.support.evidence import seed_structured
from tests.support.models import hosted_responses
from tests.support.providers import openai_fixture

pytestmark = pytest.mark.integration

MODEL, EFFORT = "gpt-5.6-luna", "low"
NAMES = ["Sparse", "Dense", "Hybrid", "Late", "Learned"]
SUMMARY = "FULL-SUMMARY-TEXT " * 400
GROUP = re.compile(r"^Paper (\d+): ", re.M)
HANDLE = re.compile(r"^\[(S\d+)\] ", re.M)
QUESTION = "Compare how all five papers measure retrieval recall and which reports the best."


def sections(name: str) -> list[tuple]:
    """Twenty passages of about 400 tokens each, all about recall, so every paper competes."""
    body = (
        f"The {name} retriever is evaluated on recall at ten passages and on latency. "
        "Recall improves when more candidate passages are scored by the reranker. " * 18
    )
    return [(f"{n} Results {n}", "text", n + 1, n + 1, body) for n in range(20)]


def groups(prompt: str) -> dict[int, int]:
    """Number of passages under each "Paper N:" header."""
    found, current = {}, None
    for line in prompt.splitlines():
        if header := GROUP.match(line):
            current = int(header[1])
            found[current] = 0
        elif HANDLE.match(line) and current is not None:
            found[current] += 1
    return found


def sent(counter, body: dict) -> int:
    messages = [PromptMessage("system", body["instructions"])] + [
        PromptMessage(item["role"], item["content"]) for item in body["input"]
    ]
    return count_messages(counter, messages)


@pytest.fixture
def embeddings(resources, monkeypatch):
    from app.integrations import embeddings
    from app.rag import pipeline

    monkeypatch.setattr(
        pipeline,
        "create_embedder",
        lambda resources, profile: embeddings.create_embedder(
            resources, profile, transport=openai_fixture([])
        ),
    )


async def long_chat(resources):
    """Five papers with summaries, and verbatim history just under the compaction threshold."""
    from app.integrations.context_registry import context_profile
    from app.services.memory import memory_shares, turn_cost

    pairs = []
    for name in NAMES:
        paper_id, document_id, _ = await seed_structured(
            resources, title=f"{name} Retrieval Study", sections=sections(name)
        )
        pairs.append((paper_id, document_id))
        async with resources.sessions() as session, session.begin():
            session.add(
                PaperSummary(
                    paper_id=paper_id,
                    document_id=document_id,
                    model=MODEL,
                    reasoning_effort=EFFORT,
                    content=SUMMARY,
                )
            )
    chat_id = await new_chat(resources, *pairs)
    profile = context_profile(resources, MODEL, EFFORT)
    limit = resources.settings.memory_compaction_ratio * memory_shares(profile).recent
    question = "How does recall change in this setting?"
    answer = "Recall rose in every setting we compared across the papers. " * 120
    size = turn_cost(
        profile.counter,
        (
            ChatMessage(role="user", content=question, citations=[]),
            ChatMessage(role="assistant", content=answer, citations=[]),
        ),
    )
    turns = int(limit // size)
    await add_turns(resources, chat_id, [(question, answer)] * turns)
    return chat_id, pairs, profile, turns


def comparison_plan(body) -> str:
    return json.dumps(
        {
            "standalone_question": QUESTION,
            "search_queries": ["retrieval recall measurement", "best recall"],
            "needs_paper_evidence": True,
            "sub_questions": [
                {"paper": number, "question": f"How does the {name} paper measure recall?"}
                for number, name in enumerate(NAMES, start=1)
            ],
        }
    )


def cite_every_group(body) -> str:
    prompt = body["input"][-1]["content"]
    handles = HANDLE.findall(prompt)
    return "All five papers report recall at ten passages " + "".join(f"[{h}]" for h in handles)


@pytest.mark.parametrize("budget", [None, 6000], ids=["profile", "shrunk-profile"])
async def test_given_five_papers_a_long_chat_and_a_comparison_then_every_call_fits_its_budget(
    resources, monkeypatch, embeddings, budget
):
    from app.services import chat, memory

    chat_id, pairs, profile, turns = await long_chat(resources)
    assert turns >= 2
    if budget is not None:
        shrunk = replace(profile, input_budget=budget)
        for module in (chat, memory):
            monkeypatch.setattr(module, "context_profile", lambda *args, **kwargs: shrunk)
        profile = shrunk
    planner = hosted_responses(monkeypatch, resources, comparison_plan)
    calls = []
    use_hosted(monkeypatch, resources, calls, cite_every_group)
    prepared, events = await ask(resources, chat_id, QUESTION, model=MODEL, reasoning_effort=EFFORT)
    (completed,) = named(events, "message.completed")

    (plan,) = planner
    (answer,) = calls
    for body in (plan, answer):
        assert sent(profile.counter, body) <= profile.input_budget
        assert "FULL-SUMMARY-TEXT" not in json.dumps(body)
    assert completed["context"]["input_tokens"] <= profile.input_budget
    # The verbatim history reached its share of the prompt.
    assert completed["context"]["recent_turns"] >= 1
    evidence = groups(answer["input"][-1]["content"])
    answering = sorted(evidence)
    assert all(count >= 2 for count in evidence.values())
    if budget is None:
        assert answering == [1, 2, 3, 4, 5]
    else:
        # Not every floor fits, so the most relevant papers answer and the note says so.
        assert len(answering) < 5
        assert "most relevant papers" in completed["retrieval"]["note"]
    assert {item["document_id"] for item in completed["citations"]} == {
        str(pairs[number - 1][1]) for number in answering
    }
