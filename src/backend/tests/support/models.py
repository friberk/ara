"""Hosted and local generation fixtures for memory tests (ARA-077)."""

import json

import httpx
from pydantic import SecretStr
from sqlalchemy import delete

RUNTIME_VERSION = "0.40.1-ara.fixture"


def hosted_responses(monkeypatch, resources, output):
    """Responses fixture for app.services.memory; `output(body)` returns the answer text."""
    from app.integrations.llm import HostedLLM
    from app.services import memory
    from tests.test_ai import response_payload

    resources.settings.openai_api_key = SecretStr("fixture")
    requests = []

    async def provider(request):
        body = json.loads(request.content)
        requests.append(body)
        text = output(body)
        if not isinstance(text, str):
            text = await text
        return httpx.Response(200, json=response_payload(text))

    monkeypatch.setattr(
        memory,
        "create_llm",
        lambda resources, model, **kwargs: HostedLLM(
            resources.settings,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(provider)),
        ),
    )
    return requests


async def install_thinking_model(resources, spec):
    """A ready local model whose verified controls can switch thinking off."""
    from app.models.local_models import ModelInstallation, ModelUse

    async with resources.sessions() as session, session.begin():
        await session.execute(delete(ModelUse))
        await session.execute(delete(ModelInstallation))
        session.add(
            ModelInstallation(
                model_key=spec.key,
                state="ready",
                weights_present=True,
                digest=spec.expected_digest,
                validation={
                    "digest": spec.expected_digest,
                    "context_window": 8192,
                    "runtime_version": RUNTIME_VERSION,
                    "reasoning_efforts": ["default", "on", "none"],
                    "thinking_schema": 1,
                    "thinking": {"values": [True, False], "default": True},
                    "think_mapping": {"on": True, "none": False},
                    "supports_streaming": True,
                    "supports_structured_output": True,
                },
            )
        )


def ollama_reply(content: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "message": {"role": "assistant", "content": content},
            "done": True,
            "done_reason": "stop",
            "prompt_eval_count": 90,
            "eval_count": 30,
        },
    )


async def local_runtime(monkeypatch, resources, spec, reply):
    """Serve the local runtime from a fixture and trap any hosted client.

    Returns the /api/chat bodies and the hosted construction attempts.
    """
    from app.integrations import llm

    resources.settings.openai_api_key = SecretStr("a hosted key exists but must stay unused")
    local, hosted = [], []

    def ollama(request):
        if request.url.path == "/api/tags":
            model = {"name": spec.model_id, "digest": spec.expected_digest}
            return httpx.Response(200, json={"models": [{**model, "size": spec.download_bytes}]})
        if request.url.path == "/api/version":
            return httpx.Response(200, json={"version": RUNTIME_VERSION})
        if request.url.path == "/api/chat":
            body = json.loads(request.content)
            local.append(body)
            return reply(body)
        return httpx.Response(404)

    def trap(*args, **kwargs):
        hosted.append(args)
        raise AssertionError("a local chat must never call a hosted model")

    for name in ("http", "ollama_generation_http"):
        await getattr(resources, name).aclose()
        setattr(resources, name, httpx.AsyncClient(transport=httpx.MockTransport(ollama)))
    monkeypatch.setattr(llm, "HostedLLM", trap)
    return local, hosted
