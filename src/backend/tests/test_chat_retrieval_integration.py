"""Paper Q&A answers from hybrid retrieval with short handles and status events (ARA-073)."""

import json
import re
from uuid import uuid4

import httpx
import pytest

from app.models.research import ChatMessage, ChatSession
from tests.support.answers import ask, first_handle, named, parse, use_hosted
from tests.support.evidence import OPENAI, TITLE, seed_structured
from tests.support.providers import openai_fixture

pytestmark = pytest.mark.integration


@pytest.fixture
def embeddings(resources, monkeypatch):
    """Query embeddings come from the deterministic OpenAI fixture."""
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


async def new_chat(resources, paper_id, document_id) -> object:
    async with resources.sessions() as session, session.begin():
        chat = ChatSession(paper_id=paper_id, document_id=document_id, title="Discussion")
        session.add(chat)
        await session.flush()
        return chat.id


async def stored(resources, message_id) -> ChatMessage:
    async with resources.sessions() as session:
        return await session.get(ChatMessage, message_id)


def cite_first(body) -> list[str]:
    # The handle is split across deltas, so mapping must wait for the closing bracket.
    handle = first_handle(body)
    return ["Dense retrieval improves recall [", handle[:2], handle[2:] + "]."]


async def test_given_ready_index_when_answering_then_hybrid_evidence_is_cited_canonically(
    resources, monkeypatch, embeddings
):
    paper_id, document_id, chunk_ids = await seed_structured(resources)
    chat_id = await new_chat(resources, paper_id, document_id)
    calls = []
    use_hosted(monkeypatch, resources, calls, cite_first)
    question = "How much does dense retrieval improve recall over BM25?"
    prepared, events = await ask(resources, chat_id, question)
    (completed,) = named(events, "message.completed")
    cited = completed["citations"][0]
    assert cited["document_id"] == str(document_id)
    assert completed["content"] == f"Dense retrieval improves recall [source:{cited['chunk_id']}]."
    assert "[S" not in "".join(d["text"] for d in named(events, "message.delta"))
    assert cited["chunk_id"] in {str(chunk_id) for chunk_id in chunk_ids[:4]}
    assert {"section", "page_end", "kind", "bboxes"} <= cited.keys() and cited["section"]
    assert completed["grounding"] == "supported"
    retrieval = completed["retrieval"]
    assert retrieval["mode"] == "hybrid" and retrieval["profile"] == OPENAI
    assert retrieval["search_queries"] == [question]
    assert retrieval["passages_used"] >= 1 and retrieval["reranked"] is False
    assert completed["context"]["input_tokens"] > 0
    assert completed["context"]["output_reserved"] == 4000
    # One query embedding: the bare question, as OpenAI receives it.
    assert [call["input"] for call in embeddings] == [[question]]
    (request,) = calls
    assert TITLE in request["instructions"] and "Ada Researcher" in request["instructions"]
    assert request["input"][-1]["role"] == "user"
    assert request["input"][-1]["content"].endswith("Question: " + question)
    row = await stored(resources, prepared.assistant.id)
    assert row.grounding == "supported" and row.state == "completed"
    trace = row.retrieval["trace"]
    assert trace["queries"] == [question]
    assert {item["retriever"] for item in trace["lists"]} == {"keyword", "vector"}
    assert trace["selected"][first_handle(request)] == cited["chunk_id"]
    assert trace["fused"] and trace["budget"] > 0 and "total" in trace["timings_ms"]


async def test_given_no_ready_index_when_answering_then_keyword_search_explains_why(
    resources, monkeypatch, embeddings
):
    paper_id, document_id, _ = await seed_structured(resources, index_state="embedding")
    chat_id = await new_chat(resources, paper_id, document_id)
    use_hosted(monkeypatch, resources, [], cite_first)
    _, events = await ask(resources, chat_id, "How does BM25 recall compare?")
    (completed,) = named(events, "message.completed")
    retrieval = completed["retrieval"]
    assert retrieval["mode"] == "keyword" and retrieval["profile"] is None
    assert "built" in retrieval["note"]
    assert embeddings == []


async def test_given_keyword_search_without_matches_when_answering_then_opening_passages_serve(
    resources, monkeypatch
):
    paper_id, document_id, chunk_ids = await seed_structured(resources, profile=None)
    chat_id = await new_chat(resources, paper_id, document_id)
    calls = []
    use_hosted(monkeypatch, resources, calls, cite_first)
    _, events = await ask(resources, chat_id, "What is it about?")
    (completed,) = named(events, "message.completed")
    assert completed["citations"][0]["chunk_id"] == str(chunk_ids[0])
    assert "opening" in completed["retrieval"]["note"]
    assert "[S1] Abstract · p. 1" in calls[0]["input"][-1]["content"]


async def test_given_stream_when_answering_then_status_stages_precede_the_answer(
    resources, monkeypatch, embeddings
):
    from app.main import create_app

    paper_id, document_id, _ = await seed_structured(resources)
    chat_id = await new_chat(resources, paper_id, document_id)
    use_hosted(monkeypatch, resources, [], cite_first)
    app = create_app(resources.settings)
    app.state.resources = resources
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            f"/api/v1/chats/{chat_id}/messages/stream",
            json={
                "model": "gpt-5.6-luna",
                "reasoning_effort": "low",
                "content": "How does BM25 recall compare?",
                "request_id": str(uuid4()),
            },
        )
    assert response.status_code == 200, response.text
    events = parse(response.text.split("\n\n"))
    order = [
        data.get("stage", event)
        for event, data in events
        if event in {"message.started", "message.status", "message.delta"}
    ]
    assert order[:5] == ["message.started", "planning", "retrieving", "generating", "message.delta"]
    message_id = named(events, "message.started")[0]["message_id"]
    assert {data["message_id"] for data in named(events, "message.status")} == {message_id}
    assert named(events, "message.completed")


async def test_given_generation_starts_then_retrieval_trace_is_already_persisted(
    resources, monkeypatch, embeddings
):
    from app.schemas.ai import ChatInput
    from app.services import chat
    from tests.support.answers import CONNECTED

    paper_id, document_id, _ = await seed_structured(resources)
    chat_id = await new_chat(resources, paper_id, document_id)
    use_hosted(monkeypatch, resources, [], cite_first)
    body = ChatInput(content="How does BM25 recall compare?", request_id=uuid4())
    prepared = await chat.prepare(resources, chat_id, body)
    row = await stored(resources, prepared.assistant.id)
    assert row.retrieval == {} and row.state == "processing"
    stream = chat.stream_answer(resources, CONNECTED, prepared)
    async for frame in stream:
        if '"stage": "generating"' in frame:
            break
    row = await stored(resources, prepared.assistant.id)
    await stream.aclose()
    assert row.retrieval["mode"] == "hybrid" and row.retrieval["trace"]["selected"]
    assert row.context["input_tokens"] > 0


async def test_given_replayed_request_when_streaming_then_nothing_is_retrieved_or_generated(
    resources, monkeypatch, embeddings
):
    from app.services import chat

    paper_id, document_id, _ = await seed_structured(resources)
    chat_id = await new_chat(resources, paper_id, document_id)
    calls, retrievals = [], []
    use_hosted(monkeypatch, resources, calls, cite_first)
    original = chat.retrieve_evidence

    async def counted(*args, **kwargs):
        retrievals.append(kwargs)
        return await original(*args, **kwargs)

    monkeypatch.setattr(chat, "retrieve_evidence", counted)
    request_id = uuid4()
    question = "How does BM25 recall compare?"
    first, events = await ask(resources, chat_id, question, request_id=request_id)
    assert named(events, "message.completed")
    replay, events = await ask(resources, chat_id, question, request_id=request_id)
    assert replay.replay and replay.assistant.id == first.assistant.id
    assert named(events, "message.completed")[0]["retrieval"]["mode"] == "hybrid"
    assert named(events, "message.status") == []
    assert (len(retrievals), len(calls), len(embeddings)) == (1, 1, 1)


@pytest.mark.parametrize("output", ["unknown_handle", "foreign_source"])
async def test_given_unsupplied_citation_when_streaming_then_answer_fails_ungrounded(
    resources, monkeypatch, embeddings, output
):
    paper_id, document_id, _ = await seed_structured(resources)
    _, _, foreign = await seed_structured(resources)
    chat_id = await new_chat(resources, paper_id, document_id)
    answer = {
        "unknown_handle": "Claim [S99].",
        "foreign_source": f"Claim [source:{foreign[2]}].",
    }[output]
    use_hosted(monkeypatch, resources, [], lambda body: answer)
    prepared, events = await ask(resources, chat_id, "How does BM25 recall compare?")
    (failed,) = named(events, "message.failed")
    assert failed["code"] == "UNGROUNDED_OUTPUT" and not named(events, "message.completed")
    row = await stored(resources, prepared.assistant.id)
    assert row.state == "failed" and row.citations == [] and row.grounding is None


async def test_given_uncited_answer_when_streaming_then_answer_fails_ungrounded(
    resources, monkeypatch, embeddings
):
    paper_id, document_id, _ = await seed_structured(resources)
    chat_id = await new_chat(resources, paper_id, document_id)
    use_hosted(monkeypatch, resources, [], lambda body: "The paper is insufficient.")
    _, events = await ask(resources, chat_id, "How does BM25 recall compare?")
    assert named(events, "message.failed")[0]["code"] == "UNGROUNDED_OUTPUT"


async def test_given_sentinel_when_streaming_then_answer_completes_as_insufficient(
    resources, monkeypatch, embeddings
):
    paper_id, document_id, _ = await seed_structured(resources)
    chat_id = await new_chat(resources, paper_id, document_id)
    use_hosted(
        monkeypatch,
        resources,
        [],
        lambda body: ["[insufficient-", "evidence] The paper does not report energy use."],
    )
    prepared, events = await ask(resources, chat_id, "How much energy does BM25 use?")
    (completed,) = named(events, "message.completed")
    assert completed["grounding"] == "insufficient" and completed["citations"] == []
    assert completed["content"] == "The paper does not report energy use."
    row = await stored(resources, prepared.assistant.id)
    assert row.grounding == "insufficient" and row.content == completed["content"]


async def test_given_old_answer_with_source_marker_when_asking_again_then_it_is_not_resent(
    resources, monkeypatch, embeddings
):
    """Regression: a previous answer's markers were resent, copied and rejected as ungrounded."""
    from datetime import timedelta

    from app.repositories.jobs import now

    paper_id, document_id, chunk_ids = await seed_structured(resources)
    chat_id = await new_chat(resources, paper_id, document_id)
    earlier = now() - timedelta(minutes=5)
    async with resources.sessions() as session, session.begin():
        session.add_all(
            [
                ChatMessage(
                    session_id=chat_id,
                    role="user",
                    content="Who wrote reference one?",
                    state="completed",
                    request_id=uuid4(),
                    created_at=earlier,
                ),
                ChatMessage(
                    session_id=chat_id,
                    role="assistant",
                    content=f"Robertson and Zaragoza [source:{chunk_ids[4]}].",
                    state="completed",
                    model="gpt-5.6-luna",
                    reasoning_effort="low",
                    citations=[
                        {
                            "chunk_id": str(chunk_ids[4]),
                            "document_id": str(document_id),
                            "page": 4,
                            "excerpt": "[1] S. Robertson",
                        }
                    ],
                    request_id=uuid4(),
                    created_at=earlier + timedelta(seconds=1),
                ),
            ]
        )
    calls = []

    def copy_everything(body):
        # A careless model repeats every marker it sees next to its own citation.
        seen = set(re.findall(r"source:([0-9a-f-]{36})", json.dumps(body["input"])))
        copied = " ".join(f"[source:{identifier}]" for identifier in seen)
        return f"Dense retrieval wins [{first_handle(body)}]. {copied}".strip()

    use_hosted(monkeypatch, resources, calls, copy_everything)
    _, events = await ask(resources, chat_id, "And how does dense retrieval compare?")
    assert named(events, "message.completed"), events
    sent = calls[0]["input"]
    assert "[source:" not in json.dumps(sent)
    assert sent[0] == {"role": "user", "content": "Who wrote reference one?"}
    assert sent[1] == {"role": "assistant", "content": "Robertson and Zaragoza (p. 4)."}
