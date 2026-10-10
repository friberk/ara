"""Paper Q&A answers from hybrid retrieval with short handles and status events (ARA-073)."""

import json
import re
from uuid import uuid4

import httpx
import pytest

from app.models.research import ChatMessage
from tests.support.answers import ask, first_handle, named, parse, use_hosted
from tests.support.chats import new_chat as chat_with_papers
from tests.support.evidence import CHUNK_SET, OPENAI, TITLE, seed_structured
from tests.support.models import hosted_responses
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
    return await chat_with_papers(resources, (paper_id, document_id))


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
    # The default reranker (OpenAI Decisions, served by the test fixture) reorders the evidence.
    assert retrieval["passages_used"] >= 1 and retrieval["reranked"] is True
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
    rerank = trace["rerank"]
    assert rerank["profile"] == "openai-gpt-6-luna" and rerank["skipped"] is None
    assert set(rerank["scores"]) <= {str(chunk_id) for chunk_id in chunk_ids}
    assert rerank["scores"] and rerank["elapsed_ms"] >= 0 and "rerank" in trace["timings_ms"]


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
    assert order[:6] == [
        "message.started",
        "planning",
        "retrieving",
        "reranking",
        "generating",
        "message.delta",
    ]
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
    # The follow-up's planner gets no usable plan and falls back, without a real provider.
    hosted_responses(monkeypatch, resources, lambda body: "not a plan")
    _, events = await ask(resources, chat_id, "And how does dense retrieval compare?")
    assert named(events, "message.completed"), events
    sent = calls[0]["input"]
    assert "[source:" not in json.dumps(sent)
    assert sent[0] == {"role": "user", "content": "Who wrote reference one?"}
    assert sent[1] == {"role": "assistant", "content": "Robertson and Zaragoza (p. 4)."}


async def choose_reranker(resources, reranker) -> None:
    from app.models.research import ModelConfiguration

    async with resources.sessions() as session, session.begin():
        session.add(
            ModelConfiguration(
                key="retrieval", value={"embedding_profile": OPENAI, "reranker": reranker}
            )
        )


async def test_given_reranking_off_when_answering_then_no_stage_and_fusion_order(
    resources, monkeypatch, embeddings
):
    paper_id, document_id, _ = await seed_structured(resources)
    chat_id = await new_chat(resources, paper_id, document_id)
    await choose_reranker(resources, None)
    use_hosted(monkeypatch, resources, [], cite_first)
    prepared, events = await ask(resources, chat_id, "How does BM25 recall compare?")
    stages = [data["stage"] for data in named(events, "message.status")]
    assert stages == ["planning", "retrieving", "generating"]
    (completed,) = named(events, "message.completed")
    assert completed["retrieval"]["reranked"] is False and completed["retrieval"]["note"] is None
    row = await stored(resources, prepared.assistant.id)
    assert row.retrieval["trace"]["rerank"] == {
        "profile": None,
        "query": "How does BM25 recall compare?",
        "skipped": None,
        "scores": {},
        "elapsed_ms": 0,
    }


@pytest.mark.parametrize("planner", ["model", "fallback"])
async def test_given_planned_follow_up_when_reranking_then_passages_are_judged_by_the_question(
    resources, monkeypatch, embeddings, planner
):
    """Regression: every candidate was scored against the first keyword query only."""
    from app.rag import pipeline
    from app.rag.rerank import RerankOutcome

    paper_id, document_id, _ = await seed_structured(resources)
    chat_id = await new_chat(resources, paper_id, document_id)
    use_hosted(monkeypatch, resources, [], cite_first)
    first = "How much does dense retrieval improve recall over BM25?"
    opening, events = await ask(resources, chat_id, first)
    assert named(events, "message.completed")
    follow_up = "And what did it cost to train?"
    standalone = "What did training the dense retriever cost, compared with BM25?"
    queries = ["dense retriever training cost", "BM25 recall comparison"]
    plan = {"standalone_question": standalone, "search_queries": queries}
    hosted_responses(
        monkeypatch,
        resources,
        lambda body: (
            json.dumps({**plan, "needs_paper_evidence": True}) if planner == "model" else "?"
        ),
    )
    seen = []

    async def record(resources, *, query, nodes, reranker):
        seen.append(query)
        return RerankOutcome(nodes=list(nodes), reranked=True, reranker=reranker)

    monkeypatch.setattr(pipeline, "rerank_candidates", record)
    prepared, events = await ask(resources, chat_id, follow_up)
    assert named(events, "message.completed")
    # The planner's standalone question; a failed plan falls back to the follow-up itself,
    # never to the keyword jumble searched in its place.
    expected = standalone if planner == "model" else follow_up
    assert seen == [expected]
    retrieval = (await stored(resources, prepared.assistant.id)).retrieval
    assert retrieval["trace"]["rerank"]["query"] == expected
    # A first turn has no plan, so the reranker judged the question as asked.
    opened = (await stored(resources, opening.assistant.id)).retrieval
    assert opened["trace"]["rerank"]["query"] == first
    if planner == "model":
        assert retrieval["search_queries"] == queries
    else:
        assert retrieval["search_queries"] != [follow_up]


QUESTION = "How does BM25 recall compare with dense retrieval?"


async def evidence(resources, document_id, *, budget=8000, reranker="openai-gpt-6-luna"):
    from pydantic import SecretStr

    from app.integrations.tokens import TiktokenCounter
    from app.rag.pipeline import Scope, retrieve_evidence

    # The ready OpenAI index embeds queries through the fixture, which needs a configured key.
    resources.settings.openai_api_key = SecretStr("http-fixture-only")
    return await retrieve_evidence(
        resources,
        scopes=[Scope(document_id, CHUNK_SET)],
        preferred_profile=OPENAI,
        queries=["BM25 recall dense retrieval"],
        question=QUESTION,
        budget=budget,
        counter=TiktokenCounter(),
        reranker=reranker,
    )


async def test_given_reranked_order_when_packing_then_evidence_follows_the_outcome(
    resources, monkeypatch, embeddings
):
    from dataclasses import replace

    from app.integrations.tokens import TiktokenCounter
    from app.rag import pipeline
    from app.rag.rerank import RerankOutcome

    seen = []

    async def reverse(resources, *, query, nodes, reranker):
        seen.append((query, reranker, [item.node.node_id for item in nodes]))
        return RerankOutcome(nodes=list(reversed(nodes)), reranked=True, reranker=reranker)

    _, document_id, _ = await seed_structured(resources)
    fused = (await evidence(resources, document_id, reranker=None)).ranked
    monkeypatch.setattr(pipeline, "rerank_candidates", reverse)
    roomy = await evidence(resources, document_id)
    ((query, reranker, ids),) = seen
    assert (query, reranker) == (QUESTION, "openai-gpt-6-luna")
    assert ids == [item.node.node_id for item in fused]
    assert [item.node.node_id for item in roomy.ranked] == ids[::-1]
    assert roomy.summary.reranked is True
    # A budget for one passage keeps the reranker's first choice, the last fused one.
    first = next(item for item in roomy.passages if str(item.chunk_id) == ids[-1])
    one = TiktokenCounter().count(replace(first, handle="S16").render()) + 1
    tight = await evidence(resources, document_id, budget=one)
    assert [str(item.chunk_id) for item in tight.passages] == [ids[-1]]


@pytest.mark.parametrize(
    ("skipped", "note"),
    [
        ("LOCAL_MODEL_NOT_READY", "Reranking was unavailable, so results use the hybrid order."),
        ("RERANKER_FAILED", "Reranking was unavailable, so results use the hybrid order."),
        # Without an OpenAI key the default reranker cannot be offered; Settings explains it.
        ("MODEL_NOT_CONFIGURED", None),
    ],
)
async def test_given_skipped_reranker_when_retrieving_then_only_relevant_reasons_are_noted(
    resources, monkeypatch, embeddings, skipped, note
):
    from app.rag import pipeline
    from app.rag.rerank import RerankOutcome

    async def skip(resources, *, query, nodes, reranker):
        return RerankOutcome(
            nodes=list(nodes), reranked=False, reranker=reranker, skipped=skipped, elapsed_ms=3
        )

    monkeypatch.setattr(pipeline, "rerank_candidates", skip)
    _, document_id, _ = await seed_structured(resources)
    result = await evidence(resources, document_id)
    assert result.summary.reranked is False and result.summary.note == note
    assert result.trace["rerank"] == {
        "profile": "openai-gpt-6-luna",
        "query": QUESTION,
        "skipped": skipped,
        "scores": {},
        "elapsed_ms": 3,
    }
