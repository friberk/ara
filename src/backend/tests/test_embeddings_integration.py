"""Hosted embeddings over LlamaIndex OpenAIEmbedding reserve budget first (ARA-072)."""

import math
from decimal import Decimal

import pytest
from pydantic import SecretStr
from sqlalchemy import select

from app.core.errors import AppError
from app.models.research import GenerationReservation
from tests.support.providers import openai_fixture

pytestmark = pytest.mark.integration


def hosted(resources):
    resources.settings.openai_api_key = SecretStr("http-fixture-only")
    return resources


async def test_given_openai_profile_when_embedding_documents_then_cost_is_reserved_first(
    resources,
):
    from app.integrations.embedding_catalog import embedding_profile
    from app.integrations.embeddings import create_embedder

    requests = []
    embedder = create_embedder(
        hosted(resources), embedding_profile("openai-3-large"), transport=openai_fixture(requests)
    )
    texts = ["Results\n\nDense retrieval improves recall.", "Method"]
    try:
        vectors = await embedder.embed_documents(texts)
    finally:
        await embedder.close()
    assert [len(vector) for vector in vectors] == [3072, 3072]
    assert all(math.isclose(sum(v * v for v in vector), 1.0, rel_tol=1e-5) for vector in vectors)
    (body,) = requests
    assert body["model"] == "text-embedding-3-large" and "dimensions" not in body
    assert body["input"] == [embedder.sent_text(text) for text in texts]
    assert body["input"][0] == "Results  Dense retrieval improves recall."
    async with resources.sessions() as session:
        (reservation,) = (await session.scalars(select(GenerationReservation))).all()
    assert reservation.model == "embedding:openai-3-large"
    assert Decimal(0) < reservation.amount < Decimal("0.0001")


async def test_given_openai_profile_when_embedding_queries_then_text_is_sent_bare(resources):
    from app.integrations.embedding_catalog import embedding_profile
    from app.integrations.embeddings import create_embedder

    requests = []
    embedder = create_embedder(
        hosted(resources), embedding_profile("openai-3-large"), transport=openai_fixture(requests)
    )
    try:
        (vector,) = await embedder.embed_queries(["What improves recall?"])
    finally:
        await embedder.close()
    assert len(vector) == 3072
    assert requests[0]["input"] == ["What improves recall?"]


async def test_given_spent_daily_budget_when_embedding_then_no_request_is_sent(resources):
    from app.integrations.embedding_catalog import embedding_profile
    from app.integrations.embeddings import create_embedder

    async with resources.sessions() as session, session.begin():
        cap = Decimal(str(resources.settings.llm_daily_budget_usd))
        session.add(GenerationReservation(model="gpt-5.6-luna", amount=cap))
    requests = []
    embedder = create_embedder(
        hosted(resources), embedding_profile("openai-3-large"), transport=openai_fixture(requests)
    )
    try:
        with pytest.raises(AppError) as error:
            await embedder.embed_documents(["Method"])
    finally:
        await embedder.close()
    assert (error.value.status_code, error.value.code) == (429, "DAILY_BUDGET_EXCEEDED")
    assert requests == []


async def test_given_no_openai_key_when_creating_embedder_then_model_is_not_configured(
    resources,
):
    from app.integrations.embedding_catalog import embedding_profile
    from app.integrations.embeddings import create_embedder

    resources.settings.openai_api_key = None
    with pytest.raises(AppError) as error:
        create_embedder(resources, embedding_profile("openai-3-large"))
    assert (error.value.status_code, error.value.code) == (503, "MODEL_NOT_CONFIGURED")


async def test_given_failing_provider_when_embedding_then_it_retries_once_and_fails(resources):
    from app.integrations.embedding_catalog import embedding_profile
    from app.integrations.embeddings import create_embedder

    requests = []
    embedder = create_embedder(
        hosted(resources),
        embedding_profile("openai-3-large"),
        transport=openai_fixture(requests, status=500),
    )
    try:
        with pytest.raises(AppError) as error:
            await embedder.embed_documents(["Method"])
    finally:
        await embedder.close()
    assert (error.value.status_code, error.value.code) == (502, "EMBEDDING_FAILED")
    assert len(requests) == 2
