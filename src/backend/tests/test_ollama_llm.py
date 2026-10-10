import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest
from pydantic import ValidationError

from app.core.config import Settings

# Open-model tests run with EXPERIMENTAL_OPEN_MODELS on (ARA-090).
pytestmark = pytest.mark.open_models


def test_given_host_endpoint_when_configuring_local_provider_then_hosted_urls_remain_guarded():
    settings = Settings(
        app_env="development", ollama_base_url="http://host.docker.internal:11434", _env_file=None
    )
    assert settings.ollama_base_url == "http://host.docker.internal:11434"
    with pytest.raises(ValidationError):
        Settings(
            app_env="development",
            openai_base_url="http://host.docker.internal:11434",
            _env_file=None,
        )


@pytest.mark.parametrize(
    "overrides",
    [
        {"ollama_context_window": 0},
        {"ollama_max_output_tokens": 0},
        {"ollama_request_timeout_seconds": 0},
        {"ollama_pull_timeout_seconds": 0},
        {"ollama_pull_timeout_seconds": 21601},
        {"ollama_stall_seconds": 0},
        {"ollama_num_threads": 0},
        {"ollama_num_threads": 65},
        {"ollama_memory_limit": "nope"},
        {"ollama_base_url": "file:///tmp/model"},
        {"ollama_base_url": "http://user:secret@localhost:11434"},
        {"ollama_context_window": 2048, "ollama_max_output_tokens": 2048},
    ],
)
def test_given_invalid_local_limits_when_configuring_then_reject(overrides):
    with pytest.raises(ValidationError):
        Settings(**overrides, _env_file=None)


def adapter(client, efforts=("default",)):
    from app.integrations.ollama_llm import OllamaLLM

    return OllamaLLM(
        Settings(openai_api_key=None, _env_file=None),
        "hf.co/IFM/K2-Horizon-7B-GGUF:Q4_K_M",
        http_client=client,
        reasoning_efforts=efforts,
    )


async def test_given_local_schema_when_completing_then_native_limits_and_no_credentials():
    requests = []

    def provider(request):
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "message": {
                    "role": "assistant",
                    "thinking": "private",
                    "content": '{"title":null}',
                },
                "done": True,
                "done_reason": "stop",
                "prompt_eval_count": 5,
                "eval_count": 3,
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
        llm = adapter(client)
        result = await llm.complete(
            "ifm-k2-horizon-7b", "default", "Ground it", "Paper", schema={"type": "object"}
        )
        assert result.content == '{"title":null}'
        assert result.usage == {"input_tokens": 5, "output_tokens": 3, "total_tokens": 8}
        request = requests[0]
        payload = json.loads(request.content)
        assert request.url.path == "/api/chat" and "authorization" not in request.headers
        assert payload["model"] == "hf.co/IFM/K2-Horizon-7B-GGUF:Q4_K_M"
        assert payload["messages"] == [
            {"role": "system", "content": "Ground it"},
            {"role": "user", "content": "Paper"},
        ]
        assert payload["options"] == {
            "num_ctx": 8192,
            "num_predict": 2048,
            "num_thread": 4,
            "temperature": 0.0,
        }
        assert payload["format"] == {"type": "object"} and "think" not in payload
        await llm.close()
        assert not client.is_closed


async def test_given_thinking_stream_when_generating_then_only_answer_is_yielded():
    lines = [
        {
            "message": {"role": "assistant", "thinking": "Internal reasoning", "content": ""},
            "done": False,
        },
        {"message": {"role": "assistant", "content": "Supported "}, "done": False},
        {
            "message": {"role": "assistant", "content": "answer"},
            "done": True,
            "done_reason": "stop",
            "prompt_eval_count": 5,
            "eval_count": 3,
        },
    ]

    def provider(request):
        assert json.loads(request.content)["think"] is False
        return httpx.Response(200, text="\n".join(json.dumps(row) for row in lines))

    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
        llm = adapter(client, ("default", "none"))
        assert [x async for x in llm.stream("ifm-k2-horizon-7b", "none", "System", "Paper")] == [
            "Supported ",
            "answer",
        ]
        assert llm.usage["total_tokens"] == 8


@pytest.mark.parametrize(
    ("body", "code"),
    [
        ('{"message":{"content":"answer"},"done":false}', "MODEL_INTERRUPTED"),
        (
            '{"message":{"content":"partial"},"done":true,"done_reason":"length"}',
            "MODEL_INCOMPLETE",
        ),
        (
            '{"message":{"thinking":"secret","content":""},"done":true,"done_reason":"stop"}',
            "MODEL_INCOMPLETE",
        ),
        ('{"error":"private path /models/secret"}', "MODEL_REQUEST_FAILED"),
        ("not json", "MODEL_RESPONSE_INVALID"),
        ('{"message":{"content":null},"done":false}', "MODEL_RESPONSE_INVALID"),
    ],
)
async def test_given_invalid_local_stream_when_generating_then_safe_failure(body, code):
    from app.integrations.llm import LLMError

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, text=body))
    ) as client:
        with pytest.raises(LLMError) as failure:
            _ = [
                x
                async for x in adapter(client).stream(
                    "ifm-k2-horizon-7b", "default", "System", "Paper"
                )
            ]
        assert failure.value.code == code
        assert "/models/secret" not in failure.value.message


async def test_given_unsupported_effort_or_context_when_generating_then_no_http_request():
    from app.integrations.llm import LLMError

    requests = []
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: requests.append(request))
    ) as client:
        llm = adapter(client)
        with pytest.raises(LLMError) as failure:
            await llm.complete("ifm-k2-horizon-7b", "low", "System", "Paper")
        assert failure.value.code == "INVALID_REASONING"
        with pytest.raises(LLMError) as failure:
            # Real tokens, not bytes: 6,000 tokens exceed the 3,072-token local input budget.
            await llm.complete("ifm-k2-horizon-7b", "default", "System", " word" * 6000)
        assert failure.value.code == "CONTEXT_LIMIT"
        assert requests == []


async def test_given_stream_cancel_when_task_is_cancelled_then_response_closes():
    started, closed = asyncio.Event(), asyncio.Event()

    class Pending(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'{"message":{"content":"partial"},"done":false}\n'
            started.set()
            await asyncio.Event().wait()

        async def aclose(self):
            closed.set()

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=Pending()))
    ) as client:

        async def consume():
            return [
                x
                async for x in adapter(client).stream(
                    "ifm-k2-horizon-7b", "default", "System", "Paper"
                )
            ]

        task = asyncio.create_task(consume())
        ready = asyncio.create_task(started.wait())
        await asyncio.wait({ready, task}, timeout=2, return_when=asyncio.FIRST_COMPLETED)
        if task.done():
            ready.cancel()
            await task
        assert started.is_set()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert closed.is_set()


def test_given_local_model_when_budgeting_then_output_and_safety_are_reserved():
    from app.integrations.llm import model_limits, validate_selection

    resources = SimpleNamespace(settings=Settings(_env_file=None))
    assert model_limits(resources, "ifm-k2-horizon-7b") == (3072, 2048)
    assert model_limits(resources, "gpt-5.6-luna") == (64000, 4000)
    assert validate_selection("ifm-k2-horizon-7b", "default").provider == "ollama"


async def test_given_local_model_when_reserving_then_no_hosted_budget_or_session_required():
    from app.integrations.llm import reserve

    await reserve(
        SimpleNamespace(settings=Settings(openai_api_key=None, _env_file=None)),
        "ifm-k2-horizon-7b",
        100,
    )


async def test_given_local_model_when_creating_provider_then_native_adapter_without_hosted_key():
    from app.integrations.llm import create_llm, validate_selection
    from app.integrations.ollama_llm import OllamaLLM

    async with httpx.AsyncClient() as client:
        resources = SimpleNamespace(
            settings=Settings(openai_api_key=None, _env_file=None), ollama_generation_http=client
        )
        llm = create_llm(
            resources,
            "ifm-k2-horizon-7b",
            selection=validate_selection("ifm-k2-horizon-7b", "default"),
        )
        assert isinstance(llm, OllamaLLM)
        assert (
            llm.parameters("ifm-k2-horizon-7b", "default", "System", "Paper")["model"]
            == "hf.co/IFM/K2-Horizon-7B-GGUF:Q4_K_M"
        )


async def test_given_owned_local_client_when_closing_then_client_is_closed():
    from app.integrations.ollama_llm import OllamaLLM

    llm = OllamaLLM(Settings(_env_file=None), "fixture")
    await llm.close()
    assert llm.client.is_closed


async def test_given_intermediate_output_limit_when_completing_then_native_allocation_is_bounded():
    requests = []

    def provider(request):
        requests.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "message": {"content": "Short supported section."},
                "done": True,
                "done_reason": "stop",
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
        await adapter(client).complete(
            "ifm-k2-horizon-7b", "default", "System", "Paper", max_output_tokens=128
        )
    assert requests[0]["options"]["num_predict"] == 128


@pytest.mark.parametrize("limit", [0, 2049])
async def test_given_invalid_intermediate_allocation_when_completing_then_reject_before_http(limit):
    from app.integrations.llm import LLMError

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: pytest.fail("invalid allocation reached HTTP")
        )
    ) as client:
        with pytest.raises(LLMError) as failure:
            await adapter(client).complete(
                "ifm-k2-horizon-7b", "default", "System", "Paper", max_output_tokens=limit
            )
        assert failure.value.code == "CONTEXT_LIMIT"


async def test_given_local_key_when_hosted_adapter_is_called_then_no_paid_request():
    from app.integrations.llm import HostedLLM, LLMError
    from tests.test_ai import response_payload

    requests = []

    def provider(request):
        requests.append(request)
        return httpx.Response(200, json=response_payload("Hosted output"))

    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
        hosted = HostedLLM(
            Settings(openai_api_key="fixture-hosted", _env_file=None), http_client=client
        )
        with pytest.raises(LLMError) as failure:
            await hosted.complete("ifm-k2-horizon-7b", "low", "System", "Paper")
        assert failure.value.code == "INVALID_MODEL" and requests == []


@pytest.mark.parametrize("status", [404, 500, 503])
async def test_given_local_http_failure_when_generating_then_safe_actionable_error(status):
    from app.integrations.llm import LLMError

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(status, text="private"))
    ) as client:
        with pytest.raises(LLMError) as failure:
            await adapter(client).complete("ifm-k2-horizon-7b", "default", "System", "Paper")
        assert failure.value.code == (
            "LOCAL_MODEL_BUSY" if status == 503 else "MODEL_REQUEST_FAILED"
        )
        assert failure.value.status == (429 if status == 503 else 502)
        assert "private" not in failure.value.message


async def test_given_unavailable_local_model_when_validating_then_safe_failure_without_fallback(
    monkeypatch,
):
    from app.core.errors import AppError
    from app.integrations.llm import LLMError, validate_model_available
    from app.services import local_models

    async def unavailable(resources, model):
        raise AppError(409, "LOCAL_MODEL_NOT_READY", "Install this local model in Settings.")

    monkeypatch.setattr(local_models, "ensure_local_available", unavailable)
    with pytest.raises(LLMError) as failure:
        await validate_model_available(
            SimpleNamespace(settings=Settings(_env_file=None)), "ifm-k2-horizon-7b", "default"
        )
    assert failure.value.code == "LOCAL_MODEL_NOT_READY" and failure.value.status == 409


async def test_given_verified_xhigh_when_selecting_local_then_native_level_is_preserved(
    monkeypatch,
):
    from app.integrations.llm import create_llm, validate_model_available, validate_selection
    from app.services import local_models

    async def available(resources, model):
        selected = validate_selection(model, "default")
        selected.reasoning_efforts = ["default", "xhigh"]
        return selected

    monkeypatch.setattr(local_models, "ensure_local_available", available)
    async with httpx.AsyncClient() as client:
        resources = SimpleNamespace(
            settings=Settings(_env_file=None), ollama_generation_http=client
        )
        selected = await validate_model_available(resources, "qwen3.8-27b", "xhigh")
        llm = create_llm(resources, "qwen3.8-27b", selection=selected)
        assert llm.parameters("qwen3.8-27b", "xhigh", "System", "Paper")["think"] == "xhigh"


async def test_given_busy_local_runtime_when_acquiring_then_interactive_busy_is_429(monkeypatch):
    from contextlib import asynccontextmanager

    from app.core.errors import AppError
    from app.integrations.llm import LLMError, generation_slots
    from app.services import local_models

    @asynccontextmanager
    async def busy(resources, model):
        raise AppError(409, "LOCAL_MODEL_BUSY", "Local generation is busy; try again.")
        yield

    monkeypatch.setattr(local_models, "local_inference_slot", busy)
    with pytest.raises(LLMError) as failure:
        async with generation_slots(SimpleNamespace(), "ifm-k2-horizon-7b"):
            pytest.fail("busy runtime must not grant a slot")
    assert failure.value.code == "LOCAL_MODEL_BUSY" and failure.value.status == 429


async def test_given_local_answer_when_streaming_then_native_provider_completes_without_hosted_key(
    monkeypatch,
):
    from contextlib import asynccontextmanager

    from app.integrations.llm import validate_selection
    from app.services import chat, local_models
    from tests.support.answers import offline_answer

    @asynccontextmanager
    async def slot(resources, model):
        yield

    async def available(resources, model):
        return validate_selection(model, "default")

    async def persist(resources, message_id, content, **kwargs):
        return {"content": content, "state": kwargs.get("state", "processing")}

    monkeypatch.setattr(local_models, "local_inference_slot", slot)
    monkeypatch.setattr(local_models, "ensure_local_available", available)
    monkeypatch.setattr(chat, "save", persist)
    body = "\n".join(
        json.dumps(x)
        for x in [
            {"message": {"thinking": "private", "content": ""}, "done": False},
            {
                "message": {"content": "[insufficient-evidence] Evidence is insufficient."},
                "done": True,
                "done_reason": "stop",
            },
        ]
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, text=body))
    ) as client:
        resources = SimpleNamespace(
            settings=Settings(openai_api_key=None, _env_file=None), ollama_generation_http=client
        )
        request = SimpleNamespace(is_disconnected=lambda: asyncio.sleep(0, result=False))
        prepared = offline_answer(monkeypatch, resources, "ifm-k2-horizon-7b", "default")
        output = "".join(
            [event async for event in chat.stream_answer(resources, request, prepared)]
        )
    assert "event: message.completed" in output and "private" not in output
    assert "Evidence is insufficient." in output and "insufficient-evidence" not in output


async def test_given_length_limited_reply_then_only_an_opt_in_caller_accepts_it_as_truncated():
    """Answers must finish; a running summary may keep the lines it completed (ARA-077)."""
    from app.integrations.llm import LLMError
    from app.integrations.tokens import PromptMessage

    body = {
        "message": {"role": "assistant", "content": "## User goals\n- Partial"},
        "done": True,
        "done_reason": "length",
        "prompt_eval_count": 90,
        "eval_count": 400,
    }
    messages = [PromptMessage("system", "Summarize."), PromptMessage("user", "Turns.")]
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=body))
    ) as client:
        local = adapter(client)
        with pytest.raises(LLMError) as strict:
            await local.complete_messages("ifm-k2-horizon-7b", "default", messages)
        accepted = await local.complete_messages(
            "ifm-k2-horizon-7b", "default", messages, accept_truncated=True
        )
    assert strict.value.code == "MODEL_INCOMPLETE"
    assert (accepted.content, accepted.truncated) == ("## User goals\n- Partial", True)
    assert accepted.usage["output_tokens"] == 400
