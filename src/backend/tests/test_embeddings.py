"""Embedding profiles and the local adapter over LlamaIndex OllamaEmbedding (ARA-072)."""

import json
import math
from contextlib import asynccontextmanager
from types import SimpleNamespace

import httpx
import pytest

from app.core.config import Settings
from app.core.errors import AppError
from tests.support.vectors import fixture_vector


def test_given_profile_keys_when_resolving_then_unknown_keys_are_rejected():
    from app.integrations.embedding_catalog import DEFAULT_PROFILE, PROFILES, embedding_profile

    assert DEFAULT_PROFILE == "openai-3-large"
    assert embedding_profile("qwen3-embed-4b").dimensions == 2560
    assert embedding_profile("qwen3-embed-8b").local_model_key == "qwen3-embedding-8b"
    assert PROFILES["openai-3-large"].query_instruction is None
    with pytest.raises(AppError) as error:
        embedding_profile("bge-small")
    assert (error.value.status_code, error.value.code) == (422, "INVALID_EMBEDDING_PROFILE")


def test_given_profiles_when_batching_then_local_admissions_stay_small():
    from app.integrations.embedding_catalog import PROFILES

    batches = {key: profile.batch_size for key, profile in PROFILES.items()}
    # OpenAI batching is unchanged. Locally, one admission is about 10 s of CPU work at the
    # Phase 0 rates (4B 51 tok/s, 8B 29 tok/s), well inside a search's wait for the slot.
    assert batches == {"openai-3-large": 64, "qwen3-embed-4b": 2, "qwen3-embed-8b": 1}


def ollama_resources(**overrides):
    return SimpleNamespace(settings=Settings(_env_file=None, **overrides))


def ollama_runtime(requests, *, dims=None, scale=1.0):
    def handler(request):
        body = json.loads(request.content)
        requests.append(body)
        texts = [body["input"]] if isinstance(body["input"], str) else body["input"]
        vectors = [
            [scale * value for value in fixture_vector(text, dims or 2560)] for text in texts
        ]
        return httpx.Response(200, json={"model": body["model"], "embeddings": vectors})

    return httpx.MockTransport(handler)


@pytest.fixture
def admitted(monkeypatch):
    from app.services import local_models

    entered = []

    @asynccontextmanager
    async def slot(resources, key, **options):
        entered.append((key, options.get("background", False)))
        yield

    monkeypatch.setattr(local_models, "retrieval_inference_slot", slot)
    return entered


@pytest.mark.open_models
async def test_given_qwen_profile_when_embedding_then_only_queries_carry_the_instruction(admitted):
    from app.integrations.embedding_catalog import QWEN_QUERY, embedding_profile
    from app.integrations.embeddings import create_embedder

    requests = []
    resources = ollama_resources(ollama_num_threads=3)
    embedder = create_embedder(
        resources, embedding_profile("qwen3-embed-4b"), transport=ollama_runtime(requests)
    )
    try:
        await embedder.embed_documents(["Results\n\nRecall improves.", "Method"])
        await embedder.embed_queries(["What improves recall?"])
    finally:
        await embedder.close()
    documents, query = requests
    assert documents["input"] == ["Results\n\nRecall improves.", "Method"]
    assert documents["model"] == "qwen3-embedding:4b-q4_K_M"
    assert query["input"].startswith("Instruct:")
    assert query["input"] == QWEN_QUERY.strip() + " What improves recall?"
    for body in requests:
        assert body["keep_alive"] == "10m" and "dimensions" not in body
        assert body["options"]["num_thread"] == 3
    # Only background jobs embed documents, so they yield to searches; a query waits its turn.
    assert admitted == [("qwen3-embedding-4b", True), ("qwen3-embedding-4b", False)]
    assert embedder.sent_text(" Method \n") == "Method"


@pytest.mark.open_models
async def test_given_wrong_dimensions_when_embedding_then_embedding_is_invalid(admitted):
    from app.integrations.embedding_catalog import embedding_profile
    from app.integrations.embeddings import create_embedder

    embedder = create_embedder(
        ollama_resources(),
        embedding_profile("qwen3-embed-4b"),
        transport=ollama_runtime([], dims=1024),
    )
    try:
        with pytest.raises(AppError) as error:
            await embedder.embed_documents(["Method"])
    finally:
        await embedder.close()
    assert (error.value.status_code, error.value.code) == (502, "EMBEDDING_INVALID")


@pytest.mark.open_models
async def test_given_unnormalized_vectors_when_embedding_then_results_have_unit_length(admitted):
    from app.integrations.embedding_catalog import embedding_profile
    from app.integrations.embeddings import create_embedder

    embedder = create_embedder(
        ollama_resources(),
        embedding_profile("qwen3-embed-4b"),
        transport=ollama_runtime([], scale=7.5),
    )
    try:
        vectors = await embedder.embed_documents(["dense retrieval", "sparse retrieval"])
    finally:
        await embedder.close()
    assert len(vectors) == 2
    for vector in vectors:
        assert math.isclose(math.sqrt(sum(value * value for value in vector)), 1.0, rel_tol=1e-6)


def busy_slot(monkeypatch, *, busy_attempts):
    from app.services import local_models

    attempts = []

    @asynccontextmanager
    async def slot(resources, key, **options):
        attempts.append(key)
        if len(attempts) <= busy_attempts:
            raise AppError(409, "LOCAL_MODEL_BUSY", "A local search request is already running.")
        yield

    monkeypatch.setattr(local_models, "retrieval_inference_slot", slot)
    return attempts


@pytest.mark.open_models
async def test_given_busy_retrieval_slot_when_embedding_then_only_the_admission_waits(monkeypatch):
    """The admission already waited its bounded time; a second wait would double it."""
    from app.integrations.embedding_catalog import embedding_profile
    from app.integrations.embeddings import create_embedder

    attempts = busy_slot(monkeypatch, busy_attempts=1)
    requests = []
    embedder = create_embedder(
        ollama_resources(), embedding_profile("qwen3-embed-4b"), transport=ollama_runtime(requests)
    )
    try:
        with pytest.raises(AppError) as error:
            await embedder.embed_queries(["recall"])
    finally:
        await embedder.close()
    assert error.value.code == "LOCAL_MODEL_BUSY"
    assert len(attempts) == 1 and requests == []


@pytest.mark.open_models
async def test_given_unreachable_runtime_when_embedding_then_runtime_is_unavailable(admitted):
    from app.integrations.embedding_catalog import embedding_profile
    from app.integrations.embeddings import create_embedder

    def refuse(request):
        raise httpx.ConnectError("refused", request=request)

    embedder = create_embedder(
        ollama_resources(),
        embedding_profile("qwen3-embed-4b"),
        transport=httpx.MockTransport(refuse),
    )
    try:
        with pytest.raises(AppError) as error:
            await embedder.embed_documents(["Method"])
    finally:
        await embedder.close()
    assert (error.value.status_code, error.value.code) == (503, "LOCAL_RUNTIME_UNAVAILABLE")
