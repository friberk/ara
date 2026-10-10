"""Answers over several papers: sub-questions, per-paper evidence and citations (ARA-088)."""

import json
import re
from uuid import uuid4

import pytest

from tests.support.answers import ask, named, use_hosted
from tests.support.chats import new_chat
from tests.support.evidence import OPENAI, TITLE, seed_structured
from tests.support.models import hosted_responses
from tests.support.providers import openai_fixture

pytestmark = pytest.mark.integration

DENSE_TITLE = "Dense Passage Retrieval for Open-Domain QA"
DENSE = [
    (
        "Abstract",
        "front_matter",
        1,
        1,
        "We evaluate dense passage retrieval against BM25 on open-domain questions. Dense "
        "retrieval reaches higher recall with a trained bi-encoder.",
    ),
    (
        "1 Introduction",
        "text",
        1,
        2,
        "Open-domain question answering needs a retriever that finds a few relevant passages "
        "among millions of candidates.",
    ),
    (
        "2 Experiments",
        "text",
        2,
        2,
        "BM25 reaches 59 percent top-20 recall while the dense retriever reaches 79 percent on "
        "Natural Questions.",
    ),
    (
        "3 Analysis",
        "text",
        3,
        3,
        "Dense retrieval fails on rare entity names where lexical overlap matters most.",
    ),
]
COMPARE = "How does BM25 recall differ between the two papers?"
GROUP = re.compile(r"^Paper (\d+): .*$", re.M)
HANDLE = re.compile(r"^\[(S\d+)\] ", re.M)


@pytest.fixture
def embeddings(resources, monkeypatch):
    from app.integrations import embeddings
    from app.rag import pipeline

    calls = []
    monkeypatch.setattr(
        pipeline,
        "create_embedder",
        lambda resources, profile: embeddings.create_embedder(
            resources, profile, transport=openai_fixture(calls)
        ),
    )
    return calls


def groups(prompt: str) -> dict[int, list[str]]:
    """Handles under each "Paper N:" header of the evidence block."""
    found, current = {}, None
    for line in prompt.splitlines():
        if header := GROUP.match(line):
            current = int(header[1])
            found[current] = []
        elif (handle := HANDLE.match(line + " ")) and current is not None:
            found[current].append(handle[1])
    return found


def plan(sub_questions) -> str:
    return json.dumps(
        {
            "standalone_question": COMPARE,
            "search_queries": ["BM25 recall"],
            "needs_paper_evidence": True,
            "sub_questions": sub_questions,
        }
    )


def cite_each_paper(body) -> str:
    handles = groups(body["input"][-1]["content"])
    first, second = handles[1][0], handles[2][0]
    return f"Paper 1 reports 0.61 recall [{first}]; paper 2 reports 59 percent [{second}]."


async def test_given_a_comparative_question_when_answering_then_each_paper_is_searched_and_cited(
    resources, monkeypatch, embeddings
):
    sparse, sparse_pdf, _ = await seed_structured(resources)
    dense, dense_pdf, _ = await seed_structured(resources, title=DENSE_TITLE, sections=DENSE)
    chat_id = await new_chat(resources, (sparse, sparse_pdf), (dense, dense_pdf))
    asks = [
        {"paper": 1, "question": "What recall does BM25 reach on the scientific benchmark?"},
        {"paper": 2, "question": "What top-20 recall does BM25 reach on Natural Questions?"},
    ]
    planner = hosted_responses(monkeypatch, resources, lambda body: plan(asks))
    calls = []
    use_hosted(monkeypatch, resources, calls, cite_each_paper)
    prepared, events = await ask(resources, chat_id, COMPARE)
    (completed,) = named(events, "message.completed")

    # The planner runs on the first turn of a multi-paper chat and knows both papers.
    (planned,) = planner
    assert TITLE in planned["instructions"] and DENSE_TITLE in planned["instructions"]
    schema = planned["text"]["format"]["schema"]
    assert "sub_questions" in schema["required"]
    # One embedding model embeds the search query and each sub-question once.
    assert {call["model"] for call in embeddings} == {"text-embedding-3-large"}
    assert [text for call in embeddings for text in call["input"]] == [
        "BM25 recall",
        asks[0]["question"],
        asks[1]["question"],
    ]
    (request,) = calls
    assert TITLE in request["instructions"] and DENSE_TITLE in request["instructions"]
    evidence = groups(request["input"][-1]["content"])
    assert sorted(evidence) == [1, 2]
    assert all(len(handles) >= 2 for handles in evidence.values())
    assert {item["document_id"] for item in completed["citations"]} == {
        str(sparse_pdf),
        str(dense_pdf),
    }
    assert completed["grounding"] == "supported"
    retrieval = completed["retrieval"]
    assert retrieval["mode"] == "hybrid" and retrieval["profile"] == OPENAI
    assert retrieval["sub_questions"] == [item["question"] for item in asks]
    trace = await stored_trace(resources, prepared.assistant.id)
    scoped = [item for item in trace["lists"] if item.get("paper")]
    assert {(item["paper"], item["retriever"]) for item in scoped} == {
        (1, "keyword"),
        (1, "vector"),
        (2, "keyword"),
        (2, "vector"),
    }
    assert trace["papers"] == {str(sparse_pdf): len(evidence[1]), str(dense_pdf): len(evidence[2])}


async def stored_trace(resources, message_id) -> dict:
    from app.models.research import ChatMessage

    async with resources.sessions() as session:
        return (await session.get(ChatMessage, message_id)).retrieval["trace"]


async def test_given_a_source_from_a_paper_outside_the_chat_when_validating_then_it_fails(
    resources, monkeypatch, embeddings
):
    sparse, sparse_pdf, _ = await seed_structured(resources)
    dense, dense_pdf, _ = await seed_structured(resources, title=DENSE_TITLE, sections=DENSE)
    _, _, foreign = await seed_structured(resources, title="Elsewhere in the library")
    chat_id = await new_chat(resources, (sparse, sparse_pdf), (dense, dense_pdf))
    hosted_responses(monkeypatch, resources, lambda body: plan([]))
    use_hosted(monkeypatch, resources, [], lambda body: f"Recall rose [source:{foreign[3]}].")
    _, events = await ask(resources, chat_id, COMPARE)
    (failed,) = named(events, "message.failed")
    assert failed["code"] == "UNGROUNDED_OUTPUT"


@pytest.mark.open_models
async def test_given_several_papers_when_asking_a_local_model_then_hosted_models_are_required(
    resources,
):
    from app.integrations.llm import LLMError
    from app.schemas.ai import ChatInput
    from app.services import chat

    sparse, sparse_pdf, _ = await seed_structured(resources)
    dense, dense_pdf, _ = await seed_structured(resources, title=DENSE_TITLE, sections=DENSE)
    chat_id = await new_chat(resources, (sparse, sparse_pdf), (dense, dense_pdf))
    body = ChatInput(
        content=COMPARE,
        request_id=uuid4(),
        model="ifm-k2-horizon-7b",
        reasoning_effort="default",
    )
    with pytest.raises(LLMError) as refused:
        await chat.prepare(resources, chat_id, body)
    assert (refused.value.code, refused.value.status) == ("MULTI_PAPER_LOCAL", 409)
    assert "hosted model" in refused.value.message
