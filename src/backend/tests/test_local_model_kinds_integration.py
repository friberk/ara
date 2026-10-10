"""Model listings carry kinds; verified local embedders become retrieval profiles (ARA-072)."""

import httpx
import pytest

from app.integrations.model_catalog import local_spec
from app.models.local_models import ModelInstallation

# Open-model tests run with EXPERIMENTAL_OPEN_MODELS on (ARA-090).
pytestmark = [pytest.mark.integration, pytest.mark.open_models]


@pytest.fixture
async def client(resources):
    from app.main import create_app

    app = create_app(resources.settings)
    app.state.resources = resources
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as http:
        yield http


async def test_given_catalog_when_listing_models_then_every_item_has_a_kind(resources, client):
    from app.services.local_models import list_local_models

    response = await client.get("/api/v1/models")
    assert response.status_code == 200, response.text
    kinds = {item["key"]: item["kind"] for item in response.json()["items"]}
    assert kinds["gpt-5.6-luna"] == "chat" and kinds["ifm-k2-horizon-7b"] == "chat"
    assert kinds["qwen3-embedding-4b"] == kinds["qwen3-embedding-8b"] == "embedding"
    assert kinds["qwen3-reranker-0.6b"] == "reranker"
    local = await list_local_models(resources, inspect_runtime=False)
    assert len(local) == 6


async def test_given_verified_local_embedder_when_listing_profiles_then_it_is_available(
    resources, client
):
    spec = local_spec("qwen3-embedding-4b")
    async with resources.sessions() as session, session.begin():
        session.add(
            ModelInstallation(
                model_key=spec.key,
                state="ready",
                weights_present=True,
                digest=spec.expected_digest,
                validation={
                    "kind": "embedding",
                    "digest": spec.expected_digest,
                    "runtime_version": "0.40.1-ara.fixture",
                    "context_window": resources.settings.ollama_context_window,
                    "thinking_schema": 1,
                    "embedding_dimensions": 2560,
                },
            )
        )
        session.add(ModelInstallation(model_key="qwen3-embedding-8b", state="downloading"))
    items = {
        item["key"]: item
        for item in (await client.get("/api/v1/retrieval/profiles")).json()["items"]
    }
    assert items["qwen3-embed-4b"]["status"] == "available"
    assert items["qwen3-embed-4b"]["unavailable_reason"] is None
    assert items["qwen3-embed-8b"]["status"] == "unavailable"
    assert items["qwen3-embed-8b"]["unavailable_reason"] == "Wait for the model download to finish."
