from types import SimpleNamespace
from uuid import uuid4

import pytest


def test_given_unknown_model_when_selecting_then_reject_without_substitution():
    from app.integrations.llm import LLMError, validate_selection

    with pytest.raises(LLMError, match="model"):
        validate_selection("invented", "low")


def test_given_requested_models_when_selecting_then_reasoning_none_is_explicit():
    from app.integrations.llm import validate_selection

    for model in ["gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna"]:
        assert validate_selection(model, "none").key == model


def test_given_citations_when_model_invents_source_then_reject():
    from app.services.retrieval import validate_citations

    chunk = SimpleNamespace(id=uuid4(), document_id=uuid4(), page=4, text="Supported text")
    with pytest.raises(ValueError, match="source"):
        validate_citations(f"claim [source:{uuid4()}]", [chunk], chunk.document_id)
    result = validate_citations(f"claim [source:{chunk.id}]", [chunk], chunk.document_id)
    assert result[0].page == 4
    assert result[0].excerpt == "Supported text"


def test_given_large_document_when_grouping_then_every_chunk_is_covered_in_real_tokens():
    from app.integrations.tokens import TiktokenCounter
    from app.services.retrieval import passage
    from app.services.summarization import batches

    counter = TiktokenCounter("o200k_base")
    # 35,000 bytes but about 7,000 tokens each: two share a 16,000-token batch.
    chunks = [SimpleNamespace(id=uuid4(), page=i + 1, text=" word" * 7000) for i in range(12)]
    groups = batches(chunks, budget=16000, counter=counter)
    assert [len(group) for group in groups] == [2] * 6
    assert all(sum(counter.count(passage(c)) for c in group) <= 16000 for group in groups)
    assert [chunk.id for group in groups for chunk in group] == [chunk.id for chunk in chunks]


def test_given_large_utf8_passage_when_local_batching_then_split_preserves_every_character():
    from app.integrations.tokens import TiktokenCounter
    from app.services.retrieval import passage
    from app.services.summarization import batches

    counter = TiktokenCounter("o200k_base", factor=1.05)
    original = SimpleNamespace(id=uuid4(), document_id=uuid4(), page=7, text="漢字" * 1600)
    groups = batches([original], budget=1000, split_oversize=True, counter=counter)
    fragments = [chunk for group in groups for chunk in group]
    assert "".join(chunk.text for chunk in fragments) == original.text
    assert all(chunk.id == original.id for chunk in fragments)
    assert all(counter.count(passage(chunk)) <= 1000 for chunk in fragments)
    # About 3,400 counted tokens fill four fragments; 9,600 bytes would need ten.
    assert len(fragments) == 4


def test_given_sse_content_when_framing_then_newlines_are_json_escaped():
    import json

    from app.services.chat import event

    frame = event("message.delta", {"text": "hello\nworld"})
    assert frame.endswith("\n\n")
    assert json.loads(frame.split("data: ")[1]) == {"text": "hello\nworld"}


def response_payload(content, status="completed"):
    return {
        "id": "resp_fixture",
        "object": "response",
        "created_at": 1,
        "status": status,
        "model": "gpt-5.6-luna",
        "error": None,
        "output": [
            {
                "id": "msg_fixture",
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": content, "annotations": []}],
            }
        ],
        "usage": {
            "input_tokens": 20,
            "output_tokens": 5,
            "total_tokens": 25,
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens_details": {"reasoning_tokens": 0},
        },
    }


async def test_given_responses_fixture_when_complete_then_store_false_and_exact_model():
    import json

    import httpx

    from app.core.config import Settings
    from app.integrations.llm import HostedLLM

    def handler(request):
        body = json.loads(request.content)
        assert body["model"] == "gpt-5.6-luna"
        assert body["store"] is False and body["reasoning"] == {"effort": "none"}
        assert body["max_output_tokens"] == 4000
        return httpx.Response(200, json=response_payload("Paper answer"))

    transport = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = HostedLLM(Settings(openai_api_key="fixture", _env_file=None), http_client=transport)
    try:
        answer = await adapter.complete("gpt-5.6-luna", "none", "instructions", "evidence")
        assert answer.content == "Paper answer" and answer.usage["total_tokens"] == 25
    finally:
        await adapter.close()


async def test_given_provider_outage_when_request_fails_then_safe_error_and_no_retry():
    import httpx

    from app.core.config import Settings
    from app.integrations.llm import HostedLLM, LLMError

    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(503, json={"error": {"message": "secret key fixture-private"}})

    transport = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = HostedLLM(Settings(openai_api_key="fixture", _env_file=None), http_client=transport)
    try:
        with pytest.raises(LLMError) as failure:
            await adapter.complete("gpt-5.6-luna", "low", "instructions", "evidence")
        assert "fixture-private" not in failure.value.message
        assert len(calls) == 1
    finally:
        await adapter.close()


async def test_given_stream_events_when_provider_completes_then_yield_only_text():
    import json

    import httpx

    from app.core.config import Settings
    from app.integrations.llm import HostedLLM

    events = [
        {
            "type": "response.output_text.delta",
            "delta": "Evidence ",
            "item_id": "msg",
            "output_index": 0,
            "content_index": 0,
            "sequence_number": 0,
        },
        {
            "type": "response.output_text.delta",
            "delta": "answer",
            "item_id": "msg",
            "output_index": 0,
            "content_index": 0,
            "sequence_number": 1,
        },
        {
            "type": "response.completed",
            "response": response_payload("Evidence answer"),
            "sequence_number": 2,
        },
    ]
    wire = "".join("data: " + json.dumps(item) + "\n\n" for item in events)
    transport = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, content=wire, headers={"Content-Type": "text/event-stream"}
            )
        )
    )
    adapter = HostedLLM(Settings(openai_api_key="fixture", _env_file=None), http_client=transport)
    try:
        answer = "".join([part async for part in adapter.stream("gpt-5.6-luna", "low", "i", "e")])
        assert answer == "Evidence answer" and adapter.usage["total_tokens"] == 25
    finally:
        await adapter.close()


def test_given_missing_key_when_constructing_adapter_then_no_provider_call():
    from app.core.config import Settings
    from app.integrations.llm import HostedLLM, LLMError

    with pytest.raises(LLMError, match="OPENAI_API_KEY"):
        HostedLLM(Settings(openai_api_key=None, _env_file=None))


def test_given_over_budget_prompt_when_preparing_request_then_reject():
    import asyncio

    from app.core.config import Settings
    from app.integrations.llm import HostedLLM, LLMError

    adapter = HostedLLM(Settings(openai_api_key="fixture", _env_file=None))
    try:
        with pytest.raises(LLMError, match="context"):
            # Real tokens, not bytes: 64,000 tokens exceed the hosted working cap.
            adapter.parameters("gpt-5.6-luna", "low", "instructions", " word" * 64000)
    finally:
        asyncio.run(adapter.close())


def test_given_invented_summary_source_when_validating_then_safe_grounding_error():
    from app.integrations.llm import LLMError
    from app.services.summarization import supported_citations

    with pytest.raises(LLMError) as failure:
        supported_citations(f"Claim [source:{uuid4()}]", [], uuid4())
    assert failure.value.code == "UNGROUNDED_OUTPUT"


async def test_given_asgi_disconnect_when_anyio_cancels_then_provider_closes_and_partial_flushes(
    monkeypatch,
):
    import asyncio

    from fastapi.responses import StreamingResponse

    from app.services import chat

    closed = []
    saved = []
    delta_sent = asyncio.Event()

    class Provider:
        usage = {}

        async def stream(self, *args):
            yield "Visible partial answer"
            await asyncio.Event().wait()

        async def close(self):
            await asyncio.sleep(0)
            closed.append(True)

    async def save_partial(resources, message_id, content, **kwargs):
        await asyncio.sleep(0)
        saved.append((message_id, content, kwargs.get("state", "processing")))
        return {}

    monkeypatch.setattr(chat, "create_llm", lambda resources, model, **kwargs: Provider())
    monkeypatch.setattr(chat, "save", save_partial)
    from app.core.config import Settings

    resources = SimpleNamespace(
        settings=Settings(openai_api_key="fixture", _env_file=None), llm_slots=asyncio.Semaphore(2)
    )
    assistant = SimpleNamespace(id=uuid4(), model="gpt-5.6-luna", reasoning_effort="low")
    request = SimpleNamespace(is_disconnected=lambda: asyncio.sleep(0, result=False))
    response = StreamingResponse(chat.stream_answer(resources, request, assistant, "evidence", []))

    async def receive():
        await delta_sent.wait()
        return {"type": "http.disconnect"}

    async def send(message):
        if message["type"] == "http.response.body" and b"message.delta" in message["body"]:
            delta_sent.set()

    await asyncio.wait_for(
        response({"type": "http", "asgi": {"spec_version": "2.3"}}, receive, send), timeout=3
    )
    assert closed == [True]
    assert saved[-1] == (assistant.id, "Visible partial answer", "interrupted")


@pytest.mark.parametrize(
    ("question", "limit", "expected"),
    [
        ("  What   accuracy\n did the\tmodel reach?  ", 60, "What accuracy did the model reach"),
        ("Is accuracy above 90%?", 60, "Is accuracy above 90%"),
        ("Why does BERT (2018) work?!", 60, "Why does BERT (2018) work"),
        ("alpha beta, gamma delta", 12, "alpha beta…"),
        ("alpha beta gamma", 13, "alpha beta…"),
        ("x" * 61, 60, "x" * 59 + "…"),
        ("a" * 60, 60, "a" * 60),
        ("???", 60, "???"),
    ],
)
def test_given_question_when_titling_then_deterministic_word_boundary_title(
    question, limit, expected
):
    from app.services.chat import title_from_question

    assert title_from_question(question, limit) == expected


def test_given_long_question_when_titling_then_bounded_and_marked_only_when_shortened():
    from app.services.chat import title_from_question

    question = (
        "How does the proposed retrieval method compare with dense passage retrieval "
        "on open-domain question answering benchmarks?"
    )
    title = title_from_question(question)
    assert title == title_from_question(question)
    assert len(title) <= 60 and title.endswith("…")
    assert question.startswith(title.removesuffix("…"))
    assert not title.removesuffix("…").endswith(" ")
    assert not title_from_question("What accuracy?").endswith("…")
