"""Embedding models share the managed local catalog and runtime (ARA-070, ARA-072)."""

import json

import httpx
import pytest

from app.core.errors import AppError
from app.integrations.model_catalog import LOCAL_MODELS, local_spec

EMBED_4B = "qwen3-embedding-4b"
# Phase 0 S1 pins (scratchpad/spikes/s1/REPORT.md, "Digests and sizes").
PINS = {
    EMBED_4B: (
        "qwen3-embedding:4b-q4_K_M",
        "df5bd2e3c74cd8d069d21dc038f1b359fcdc9458fce1c99bd43c9eb1518ff907",
        2496704041,
        2560,
    ),
    "qwen3-embedding-8b": (
        "qwen3-embedding:8b-q4_K_M",
        "64b933495768fbd3b87c20583d379728a07471e0c66733a9df87cd1901b3c44b",
        4676805193,
        4096,
    ),
}


def test_given_catalog_then_embedding_models_are_pinned_and_chat_models_keep_their_kind():
    for key, (model_id, digest, size, dims) in PINS.items():
        spec = local_spec(key)
        assert (spec.kind, spec.model_id, spec.expected_digest) == ("embedding", model_id, digest)
        assert (spec.download_bytes, spec.embedding_dimensions) == (size, dims)
    kinds = {spec.key: spec.kind for spec in LOCAL_MODELS.values()}
    assert {key for key, kind in kinds.items() if kind == "chat"} == {
        "ifm-k2-horizon-3.7b",
        "ifm-k2-horizon-7b",
        "qwen3.8-27b",
    }
    assert "reranker" not in kinds.values()


def test_given_embedding_model_when_selecting_for_generation_then_it_is_rejected():
    from app.integrations.llm import LLMError, validate_selection

    with pytest.raises(LLMError) as error:
        validate_selection(EMBED_4B, "default")
    assert (error.value.code, error.value.status) == ("INVALID_MODEL", 422)


def embedding_runtime(spec, requests, *, capabilities=("tools", "embedding"), dims=None):
    def handler(request):
        requests.append(request.url.path)
        if request.url.path == "/api/tags":
            return httpx.Response(
                200, json={"models": [{"name": spec.model_id, "digest": spec.expected_digest}]}
            )
        if request.url.path == "/api/show":
            return httpx.Response(
                200,
                json={
                    "template": "",
                    "capabilities": list(capabilities),
                    "model_info": {"qwen3.context_length": 40960},
                },
            )
        if request.url.path == "/api/version":
            return httpx.Response(200, json={"version": "0.40.1-ara.fixture"})
        if request.url.path == "/api/embed":
            body = json.loads(request.content)
            requests.append(body)
            size = dims or spec.embedding_dimensions
            return httpx.Response(200, json={"embeddings": [[0.5] * size]})
        return httpx.Response(404, json={"error": "unexpected probe"})

    return httpx.MockTransport(handler)


async def test_given_embedding_model_when_verifying_then_dimensions_are_probed_without_chat():
    from app.integrations.ollama import OllamaRuntime

    spec, requests = local_spec(EMBED_4B), []
    async with httpx.AsyncClient(transport=embedding_runtime(spec, requests)) as client:
        validation = await OllamaRuntime(client, "http://runtime", probe_threads=3).verify(
            spec, context_window=8192
        )
    assert validation == {
        "kind": "embedding",
        "digest": spec.expected_digest,
        "runtime_version": "0.40.1-ara.fixture",
        "context_window": 8192,
        "thinking_schema": 1,
        "embedding_dimensions": 2560,
        "reasoning_efforts": ["default"],
        "supports_streaming": False,
        "supports_structured_output": False,
    }
    assert "/api/chat" not in requests
    probe = next(item for item in requests if isinstance(item, dict))
    assert probe["model"] == spec.model_id and probe["input"] == "probe"
    assert probe["keep_alive"] == 0 and probe["options"]["num_thread"] == 3


@pytest.mark.parametrize(
    ("capabilities", "dims"), [(("tools", "embedding"), 1024), (("completion",), None)]
)
async def test_given_wrong_embedding_runtime_when_verifying_then_validation_fails(
    capabilities, dims
):
    from app.integrations.ollama import OllamaRuntime

    spec = local_spec(EMBED_4B)
    transport = embedding_runtime(spec, [], capabilities=capabilities, dims=dims)
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(AppError) as error:
            await OllamaRuntime(client, "http://runtime").verify(spec, context_window=8192)
    assert error.value.code == "MODEL_VALIDATION_FAILED"


def test_given_verified_embedding_installation_then_model_reports_its_kind():
    from app.models.local_models import ModelInstallation
    from app.services.local_models import model_dto

    spec = local_spec(EMBED_4B)
    row = ModelInstallation(
        model_key=spec.key,
        state="ready",
        weights_present=True,
        completed_bytes=spec.download_bytes,
        digest=spec.expected_digest,
        validation={
            "kind": "embedding",
            "digest": spec.expected_digest,
            "runtime_version": "0.40.1-ara.fixture",
            "context_window": 8192,
            "thinking_schema": 1,
            "embedding_dimensions": 2560,
            "reasoning_efforts": ["default"],
            "supports_streaming": False,
            "supports_structured_output": False,
        },
    )
    model = model_dto(spec, row)
    assert (model.kind, model.status, model.reasoning_efforts) == (
        "embedding",
        "available",
        ["default"],
    )
    assert model.installation.download_bytes == 2496704041
    assert model_dto(local_spec("ifm-k2-horizon-7b"), None).kind == "chat"
