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


def test_given_utf8_context_when_budgeting_then_bytes_are_conservative():
    from app.integrations.llm import estimate_tokens

    assert estimate_tokens("漢" * 100) >= 300


def test_given_citations_when_model_invents_source_then_reject():
    from app.services.retrieval import validate_citations

    chunk = SimpleNamespace(id=uuid4(), document_id=uuid4(), page=4, text="Supported text")
    with pytest.raises(ValueError, match="source"):
        validate_citations(f"claim [source:{uuid4()}]", [chunk], chunk.document_id)
    result = validate_citations(f"claim [source:{chunk.id}]", [chunk], chunk.document_id)
    assert result[0].page == 4
    assert result[0].excerpt == "Supported text"


def test_given_large_document_when_grouping_then_every_chunk_is_covered():
    from app.services.summarization import batches

    chunks = [SimpleNamespace(id=uuid4(), page=i + 1, text="x" * 7000) for i in range(12)]
    groups = batches(chunks, budget=16000)
    assert len(groups) > 1
    assert [chunk.id for group in groups for chunk in group] == [chunk.id for chunk in chunks]


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
            adapter.parameters("gpt-5.6-luna", "low", "instructions", "x" * 32000)
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

    monkeypatch.setattr(chat, "HostedLLM", lambda settings: Provider())
    monkeypatch.setattr(chat, "save", save_partial)
    resources = SimpleNamespace(settings=None, llm_slots=asyncio.Semaphore(2))
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
