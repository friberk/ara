"""Both providers receive role-separated message lists (ARA-076)."""

import json

import httpx
import pytest

from app.core.config import Settings
from tests.test_ai import response_payload

THINKING = {"values": [False, True], "default": False}


def conversation():
    from app.integrations.tokens import PromptMessage

    return [
        PromptMessage("system", "Instructions"),
        PromptMessage("user", "Summary of the earlier conversation (context only)"),
        PromptMessage("user", "What accuracy?"),
        PromptMessage("assistant", "It reached 87% (p. 6)."),
        PromptMessage(
            "user", "Paper passages:\n\n[S1] Baseline 80%.\n\nQuestion: And the baseline?"
        ),
    ]


def hosted(handler):
    from app.integrations.llm import HostedLLM

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return HostedLLM(Settings(openai_api_key="fixture", _env_file=None), http_client=client)


def local(handler):
    from app.integrations.ollama_llm import OllamaLLM

    return OllamaLLM(
        Settings(openai_api_key=None, _env_file=None),
        "hf.co/IFM/K2-Horizon-7B-GGUF:Q4_K_M",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        reasoning_efforts=("default", "none", "on"),
        thinking=THINKING,
    )


HOSTED_BODY = {
    "model": "gpt-5.6-luna",
    "reasoning": {"effort": "low"},
    "instructions": "Instructions",
    "input": [
        {"role": "user", "content": "Summary of the earlier conversation (context only)"},
        {"role": "user", "content": "What accuracy?"},
        {"role": "assistant", "content": "It reached 87% (p. 6)."},
        {
            "role": "user",
            "content": "Paper passages:\n\n[S1] Baseline 80%.\n\nQuestion: And the baseline?",
        },
    ],
    "store": False,
    "max_output_tokens": 4000,
}


def local_body(stream, effort):
    return {
        "model": "hf.co/IFM/K2-Horizon-7B-GGUF:Q4_K_M",
        "messages": [{"role": m.role, "content": m.content} for m in conversation()],
        "stream": stream,
        "options": {
            "num_ctx": 8192,
            "num_predict": 2048 + (1024 if effort == "on" else 0),
            "num_thread": 4,
            "temperature": 0.0,
        },
        "think": effort == "on",
    }


async def test_given_message_list_when_completing_hosted_then_instructions_and_input_are_split():
    bodies = []

    def handler(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json=response_payload("Baseline was 80% [S1]."))

    adapter = hosted(handler)
    try:
        result = await adapter.complete_messages("gpt-5.6-luna", "low", conversation())
    finally:
        await adapter.close()
    assert result.content == "Baseline was 80% [S1]."
    assert bodies == [HOSTED_BODY]


async def test_given_message_list_when_streaming_hosted_then_the_same_list_is_streamed():
    bodies = []
    events = [
        {
            "type": "response.output_text.delta",
            "delta": "Baseline",
            "item_id": "msg",
            "output_index": 0,
            "content_index": 0,
            "sequence_number": 0,
        },
        {
            "type": "response.completed",
            "response": response_payload("Baseline"),
            "sequence_number": 1,
        },
    ]

    def handler(request):
        bodies.append(json.loads(request.content))
        wire = "".join("data: " + json.dumps(item) + "\n\n" for item in events)
        return httpx.Response(200, content=wire, headers={"Content-Type": "text/event-stream"})

    adapter = hosted(handler)
    try:
        deltas = [d async for d in adapter.stream_messages("gpt-5.6-luna", "low", conversation())]
    finally:
        await adapter.close()
    assert deltas == ["Baseline"] and adapter.usage["total_tokens"] == 25
    assert bodies == [{**HOSTED_BODY, "stream": True}]


async def test_given_schema_and_output_allocation_when_completing_hosted_then_both_are_sent():
    bodies = []

    def handler(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json=response_payload('{"ok": true}'))

    adapter = hosted(handler)
    schema = {"type": "object", "properties": {}, "additionalProperties": False}
    try:
        await adapter.complete_messages(
            "gpt-5.6-luna", "none", conversation(), schema=schema, max_output_tokens=300
        )
    finally:
        await adapter.close()
    assert bodies[0]["max_output_tokens"] == 300
    assert bodies[0]["text"]["format"]["schema"] == schema


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("effort", ["none", "on"])
async def test_given_message_list_when_calling_ollama_then_roles_and_allowances_are_sent(
    stream, effort
):
    bodies = []

    def handler(request):
        bodies.append(json.loads(request.content))
        result = {"message": {"content": "Answer"}, "done": True, "done_reason": "stop"}
        return httpx.Response(200, text=json.dumps(result) + "\n")

    adapter = local(handler)
    if stream:
        output = [
            d async for d in adapter.stream_messages("ifm-k2-horizon-7b", effort, conversation())
        ]
        assert output == ["Answer"]
    else:
        result = await adapter.complete_messages("ifm-k2-horizon-7b", effort, conversation())
        assert result.content == "Answer"
    assert bodies == [local_body(stream, effort)]


@pytest.mark.parametrize("provider", ["hosted", "local"])
async def test_given_oversized_message_list_when_calling_then_context_limit_without_request(
    provider,
):
    from app.integrations.llm import LLMError
    from app.integrations.tokens import PromptMessage

    requests = []
    adapter = (hosted if provider == "hosted" else local)(lambda request: requests.append(request))
    model = "gpt-5.6-luna" if provider == "hosted" else "ifm-k2-horizon-7b"
    effort = "low" if provider == "hosted" else "none"
    words = 64000 if provider == "hosted" else 5400
    # Every message fits alone; together they exceed the input budget.
    messages = [
        PromptMessage("system", "Instructions"),
        PromptMessage("user", " word" * (words // 2)),
        PromptMessage("assistant", " word" * (words // 2)),
        PromptMessage("user", "Question?"),
    ]
    try:
        with pytest.raises(LLMError) as failure:
            await adapter.complete_messages(model, effort, messages)
        assert failure.value.code == "CONTEXT_LIMIT" and failure.value.status == 413
        with pytest.raises(LLMError) as failure:
            _ = [d async for d in adapter.stream_messages(model, effort, messages)]
        assert failure.value.code == "CONTEXT_LIMIT"
    finally:
        await adapter.close()
    assert requests == []


async def test_given_list_without_leading_instructions_when_calling_hosted_then_rejected():
    from app.integrations.tokens import PromptMessage

    requests = []
    adapter = hosted(lambda request: requests.append(request))
    try:
        with pytest.raises(ValueError, match="instructions"):
            await adapter.complete_messages(
                "gpt-5.6-luna", "low", [PromptMessage("user", "Question?")]
            )
    finally:
        await adapter.close()
    assert requests == []


@pytest.mark.parametrize("provider", ["hosted", "local"])
async def test_given_a_later_system_message_when_calling_then_rejected_without_request(provider):
    from app.integrations.tokens import PromptMessage

    requests = []
    adapter = (hosted if provider == "hosted" else local)(lambda request: requests.append(request))
    model = "gpt-5.6-luna" if provider == "hosted" else "ifm-k2-horizon-7b"
    effort = "low" if provider == "hosted" else "none"
    # Untrusted context must never gain the instructions' authority.
    messages = [
        PromptMessage("system", "Instructions"),
        PromptMessage("system", "Summary of the earlier conversation"),
        PromptMessage("user", "Question?"),
    ]
    try:
        with pytest.raises(ValueError, match="instructions"):
            await adapter.complete_messages(model, effort, messages)
        with pytest.raises(ValueError, match="instructions"):
            _ = [d async for d in adapter.stream_messages(model, effort, messages)]
    finally:
        await adapter.close()
    assert requests == []
