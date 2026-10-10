"""One wider retry when the first answer reports insufficient evidence (ARA-094).

Adapts Self-Route (Li et al., EMNLP 2024): the model's own judgement that the evidence is
insufficient escalates once, here to wider retrieval rather than whole documents.
"""

import json

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import select

from app.models.research import ChatMessage, GenerationReservation
from tests.support.answers import ask, named
from tests.support.chats import new_chat
from tests.support.evidence import seed_structured
from tests.test_ai import response_payload

pytestmark = pytest.mark.integration

FILLER = "Paragraph {n} of the evaluation discusses recall at ten passages for the benchmark."
SECTIONS = [
    ("1 Introduction", "text", 1, 1, "Researchers compare lexical and dense retrieval."),
    *[("2 Evaluation", "text", 2 + n, 2 + n, FILLER.format(n=n)) for n in range(8)],
]
# Synthetic reranker scores by ordinal: two strong passages, then a middle band that the first
# pass prunes (below 0.5 of the best) and the retry keeps (at least 0.25 of it).
SCORES = {0: 0.95, 1: 0.9, 3: 0.4, 5: 0.35, 7: 0.3, 2: 0.05, 4: 0.04, 6: 0.03, 8: 0.02}
INSUFFICIENT = "[insufficient-evidence] The passages do not give the recall figure."
USAGE = [
    {"input_tokens": 1111, "output_tokens": 77},
    {"input_tokens": 2222, "output_tokens": 99},
]


def streamed(calls: list, answers: list[str]):
    """A Responses stream whose n-th call answers answers[n] with USAGE[n]."""

    def handler(request):
        body = json.loads(request.content)
        index = len(calls)
        calls.append(body)
        text = answers[index]
        completed = response_payload(text)
        completed["usage"] = {**completed["usage"], **USAGE[index]}
        events = [
            {
                "type": "response.output_text.delta",
                "delta": text,
                "item_id": "msg",
                "output_index": 0,
                "content_index": 0,
                "sequence_number": 0,
            },
            {"type": "response.completed", "response": completed, "sequence_number": 1},
        ]
        wire = "".join("data: " + json.dumps(item) + "\n\n" for item in events)
        return httpx.Response(200, content=wire, headers={"Content-Type": "text/event-stream"})

    return httpx.MockTransport(handler)


@pytest.fixture
def answers(resources, monkeypatch):
    """Set the model's answers in order; returns the list of request bodies."""
    from app.integrations.llm import HostedLLM
    from app.services import chat

    resources.settings.openai_api_key = SecretStr("http-fixture-only")
    calls, scripted = [], []
    monkeypatch.setattr(
        chat,
        "create_llm",
        lambda resources, model, **kwargs: HostedLLM(
            resources.settings,
            http_client=httpx.AsyncClient(transport=streamed(calls, scripted)),
        ),
    )

    def script(*texts: str) -> list:
        scripted.extend(texts)
        return calls

    return script


@pytest.fixture
def scored(monkeypatch):
    """The reranker returns SCORES, best first, for every candidate."""
    from app.rag import pipeline
    from app.rag.rerank import RerankOutcome

    async def rerank(resources, *, query, nodes, reranker):
        nodes = sorted(nodes, key=lambda item: -SCORES[item.node.metadata["ordinal"]])
        scores = {item.node.node_id: SCORES[item.node.metadata["ordinal"]] for item in nodes}
        return RerankOutcome(nodes=nodes, reranked=True, reranker=reranker, scores=scores)

    monkeypatch.setattr(pipeline, "rerank_candidates", rerank)


async def paper_chat(resources):
    paper_id, document_id, chunk_ids = await seed_structured(
        resources, sections=SECTIONS, profile=None
    )
    return await new_chat(resources, (paper_id, document_id)), chunk_ids


def handles(body) -> list[str]:
    import re

    return re.findall(r"^\[(S\d+)\] ", body["input"][-1]["content"], re.M)


async def stored(resources, message_id) -> ChatMessage:
    async with resources.sessions() as session:
        return await session.get(ChatMessage, message_id)


QUESTION = "What recall does the evaluation report at ten passages?"


async def test_given_an_insufficient_first_answer_when_answering_then_one_wider_retry_replaces_it(
    resources, answers, scored
):
    from app.services.costs import Spend, message_spend

    chat_id, _ = await paper_chat(resources)
    calls = answers(INSUFFICIENT, "Recall at ten is reported [S3].")
    prepared, events = await ask(resources, chat_id, QUESTION)

    assert len(calls) == 2
    stages = [data["stage"] for data in named(events, "message.status")]
    assert stages.index("widening") > stages.index("generating")
    first, second = (handles(body) for body in calls)
    # Lower bar, twice the cap, whole sections: the retry sees more passages.
    assert len(second) > len(first)
    (completed,) = named(events, "message.completed")
    assert completed["grounding"] == "supported"
    assert completed["content"].startswith("Recall at ten is reported [source:")
    retrieval = completed["retrieval"]
    assert retrieval["retried"] is True
    assert retrieval["passages_used"] == len(second)
    row = await stored(resources, prepared.assistant.id)
    assert row.content == completed["content"] and "insufficient" not in row.content
    assert row.usage["input_tokens"] == 2222
    first_call = row.retrieval["billed"]["first_answer"]
    assert first_call["model"] == "gpt-5.6-luna" and first_call["input_tokens"] == 1111
    assert row.retrieval["trace"]["first_pass"]["passages"] == len(first)
    assert row.retrieval["trace"]["pass"] == "retry"
    # The chat meter prices both answer calls.
    spend = Spend()
    message_spend(spend, row.state, row.model, row.usage, row.retrieval["billed"])
    single = Spend()
    message_spend(single, row.state, row.model, row.usage, {})
    assert spend.answers > single.answers > 0
    # Both calls were reserved on the daily ledger.
    async with resources.sessions() as session:
        reserved = (await session.scalars(select(GenerationReservation.model))).all()
    assert reserved.count("gpt-5.6-luna") == 2


async def test_given_a_supported_first_answer_when_answering_then_it_never_retries(
    resources, answers, scored
):
    chat_id, _ = await paper_chat(resources)
    calls = answers("Recall is reported [S1].")
    prepared, events = await ask(resources, chat_id, QUESTION)
    assert len(calls) == 1
    assert "widening" not in [data["stage"] for data in named(events, "message.status")]
    (completed,) = named(events, "message.completed")
    assert completed["retrieval"]["retried"] is False
    row = await stored(resources, prepared.assistant.id)
    assert "first_answer" not in row.retrieval["billed"]


async def test_given_an_insufficient_answer_and_nothing_wider_when_answering_then_it_stands(
    resources, answers, monkeypatch
):
    """Every candidate already scored above the retry bar and was sent: widening adds nothing,
    so the first answer is final and no second call is made."""
    from app.rag import pipeline
    from app.rag.rerank import RerankOutcome

    async def flat(resources, *, query, nodes, reranker):
        scores = {item.node.node_id: 0.9 for item in nodes}
        return RerankOutcome(nodes=list(nodes), reranked=True, reranker=reranker, scores=scores)

    monkeypatch.setattr(pipeline, "rerank_candidates", flat)
    paper_id, document_id, _ = await seed_structured(resources, profile=None)
    chat_id = await new_chat(resources, (paper_id, document_id))
    calls = answers(INSUFFICIENT)
    _, events = await ask(resources, chat_id, "What does the paper conclude about BM25 recall?")
    assert len(calls) == 1
    (completed,) = named(events, "message.completed")
    assert completed["grounding"] == "insufficient"
    assert completed["retrieval"]["retried"] is False


async def test_given_a_retried_answer_when_its_request_is_replayed_then_nothing_is_generated(
    resources, answers, scored
):
    from uuid import uuid4

    chat_id, _ = await paper_chat(resources)
    calls = answers(INSUFFICIENT, "Recall at ten is reported [S3].")
    request_id = uuid4()
    _, events = await ask(resources, chat_id, QUESTION, request_id=request_id)
    (completed,) = named(events, "message.completed")
    assert len(calls) == 2
    _, replay = await ask(resources, chat_id, QUESTION, request_id=request_id)
    (again,) = named(replay, "message.completed")
    assert len(calls) == 2
    assert again["content"] == completed["content"]
    assert "message.delta" not in [event for event, _ in replay]


async def test_given_no_budget_left_for_the_retry_when_answering_then_the_first_answer_stands(
    resources, answers, scored, monkeypatch
):
    from app.integrations import llm
    from app.services import chat

    chat_id, _ = await paper_chat(resources)
    calls = answers(INSUFFICIENT, "never sent")
    seen = []

    async def reserve(resources, model, tokens):
        seen.append(tokens)
        if len(seen) > 1:
            raise llm.LLMError("DAILY_BUDGET_EXCEEDED", "The daily AI budget has been reached.")

    monkeypatch.setattr(chat, "reserve", reserve)
    _, events = await ask(resources, chat_id, QUESTION)
    assert len(calls) == 1 and len(seen) == 2
    (completed,) = named(events, "message.completed")
    assert completed["grounding"] == "insufficient"
    assert completed["retrieval"]["retried"] is False
