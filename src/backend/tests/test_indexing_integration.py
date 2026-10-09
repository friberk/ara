"""Resumable blue/green embedding indexes per document, profile and chunk set (ARA-072)."""

import hashlib
from contextlib import asynccontextmanager
from dataclasses import replace
from uuid import uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import func, select, text

from app.models.jobs import BackgroundJob, JobOutbox
from app.models.research import DocumentChunk, ModelConfiguration
from app.models.retrieval import ChunkEmbedding, RetrievalIndex
from app.repositories.jobs import claim
from tests.support.papers import CHUNK_SET, OPENAI, QWEN, seed_paper
from tests.support.providers import ollama_fixture, openai_fixture

pytestmark = pytest.mark.integration


@pytest.fixture
def providers(resources, monkeypatch):
    """Route embedders to deterministic fixtures and use small batches."""
    from app.integrations import embeddings
    from app.integrations.embedding_catalog import embedding_profile
    from app.rag import indexing
    from app.services import local_models

    resources.settings.openai_api_key = SecretStr("http-fixture-only")
    calls = {"openai": [], "ollama": []}

    def fixture_embedder(resources, profile):
        transport = (
            openai_fixture(calls["openai"])
            if profile.provider == "openai"
            else ollama_fixture(calls["ollama"])
        )
        return embeddings.create_embedder(resources, profile, transport=transport)

    @asynccontextmanager
    async def slot(resources, key, **options):
        yield

    monkeypatch.setattr(indexing, "create_embedder", fixture_embedder)
    monkeypatch.setattr(
        indexing, "embedding_profile", lambda key: replace(embedding_profile(key), batch_size=2)
    )
    monkeypatch.setattr(local_models, "retrieval_inference_slot", slot)
    return calls


async def ensure(resources, document_id, profile, **options):
    from app.rag.indexing import ensure_index

    async with resources.sessions() as session, session.begin():
        index = await ensure_index(session, document_id, profile, **options)
        return index.id, index.job_id


async def run_job(resources, job_id):
    from app.rag.indexing import run_embed_job

    async with resources.sessions() as session:
        job = await session.get(BackgroundJob, job_id)
        generation, payload = job.generation, job.payload
    token = await claim(resources.sessions, job_id, generation)
    assert token is not None
    await run_embed_job(resources, job_id, generation, token, payload)
    return generation, token


async def load(resources, model, identifier):
    async with resources.sessions() as session:
        return await session.get(model, identifier)


async def embedding_count(resources, document_id, profile):
    async with resources.sessions() as session:
        return await session.scalar(
            select(func.count())
            .select_from(ChunkEmbedding)
            .where(ChunkEmbedding.document_id == document_id, ChunkEmbedding.profile == profile)
        )


async def serving(resources, document_id, preferred):
    from app.rag.indexing import ready_index

    async with resources.sessions() as session:
        index = await ready_index(session, document_id, preferred)
        return index.profile if index else None


async def test_given_ready_document_when_embedding_then_index_is_ready_with_vectors(
    resources, providers
):
    from app.integrations.embedding_catalog import embedding_profile
    from app.integrations.embeddings import create_embedder

    paper_id, document_id = await seed_paper(resources)
    index_id, job_id = await ensure(resources, document_id, OPENAI)
    index = await load(resources, RetrievalIndex, index_id)
    assert (index.state, index.total, index.chunk_set) == ("queued", 5, CHUNK_SET)
    job = await load(resources, BackgroundJob, job_id)
    assert job.kind == "embed"
    assert job.payload == {
        "index_id": str(index_id),
        "document_id": str(document_id),
        "paper_id": str(paper_id),
        "profile": OPENAI,
    }
    await run_job(resources, job_id)
    index = await load(resources, RetrievalIndex, index_id)
    assert (index.state, index.embedded, index.total) == ("ready", 5, 5)
    job = await load(resources, BackgroundJob, job_id)
    assert (job.state, job.progress) == ("completed", 100)
    assert len(providers["openai"]) == 3  # batches of two
    async with resources.sessions() as session:
        rows = (
            await session.execute(
                select(DocumentChunk.context_text, ChunkEmbedding.input_hash)
                .join(ChunkEmbedding, ChunkEmbedding.chunk_id == DocumentChunk.id)
                .where(ChunkEmbedding.profile == OPENAI)
            )
        ).all()
    assert len(rows) == 5
    embedder = create_embedder(resources, embedding_profile(OPENAI))
    await embedder.close()
    for context_text, input_hash in rows:
        sent = embedder.sent_text(context_text)
        assert "\n" not in sent
        assert input_hash == hashlib.sha256(sent.encode()).hexdigest()


async def test_given_unfinished_index_when_ensuring_again_then_one_job_serves_it(
    resources, providers
):
    _, document_id = await seed_paper(resources)
    first = await ensure(resources, document_id, OPENAI)
    assert await ensure(resources, document_id, OPENAI) == first
    await run_job(resources, first[1])
    assert await ensure(resources, document_id, OPENAI) == first
    async with resources.sessions() as session:
        jobs = await session.scalar(
            select(func.count()).select_from(BackgroundJob).where(BackgroundJob.kind == "embed")
        )
    assert jobs == 1


async def test_given_duplicate_or_stale_delivery_when_running_then_nothing_is_rewritten(
    resources, providers
):
    from app.rag.indexing import run_embed_job

    _, document_id = await seed_paper(resources)
    index_id, job_id = await ensure(resources, document_id, OPENAI)
    generation, token = await run_job(resources, job_id)
    requests = len(providers["openai"])
    async with resources.sessions() as session:
        payload = (await session.get(BackgroundJob, job_id)).payload
    # A redelivered message for the finished generation holds no live lease.
    await run_embed_job(resources, job_id, generation, token, payload)
    assert len(providers["openai"]) == requests
    assert await embedding_count(resources, document_id, OPENAI) == 5
    # A worker whose lease was taken over writes nothing.
    _, other_document = await seed_paper(resources)
    other_index, other_job = await ensure(resources, other_document, OPENAI)
    stale = await claim(resources.sessions, other_job, 1)
    async with resources.sessions() as session, session.begin():
        job = await session.get(BackgroundJob, other_job)
        job.lease_token, other_payload = uuid4(), job.payload
    await run_embed_job(resources, other_job, 1, stale, other_payload)
    assert await embedding_count(resources, other_document, OPENAI) == 0
    assert (await load(resources, RetrievalIndex, other_index)).state == "queued"
    assert len(providers["openai"]) == requests


async def test_given_time_budget_spent_when_embedding_then_job_continues_without_attempts(
    resources, providers, monkeypatch
):
    from app.rag import indexing

    _, document_id = await seed_paper(resources)
    index_id, job_id = await ensure(resources, document_id, OPENAI)
    monkeypatch.setattr(indexing, "WORK_SECONDS", 0)
    await run_job(resources, job_id)
    job = await load(resources, BackgroundJob, job_id)
    assert (job.state, job.stage, job.generation, job.attempts) == ("queued", "embedding", 2, 0)
    assert job.progress == 40
    index = await load(resources, RetrievalIndex, index_id)
    assert (index.state, index.embedded) == ("embedding", 2)
    monkeypatch.setattr(indexing, "WORK_SECONDS", 240)
    await run_job(resources, job_id)
    assert (await load(resources, RetrievalIndex, index_id)).state == "ready"
    assert await embedding_count(resources, document_id, OPENAI) == 5
    assert len(providers["openai"]) == 3


async def test_given_profile_switch_while_answering_then_old_index_serves_until_new_is_ready(
    resources, providers, monkeypatch
):
    """Review Focus 3: a question never sees a half-built index."""
    from app.rag import indexing

    _, document_id = await seed_paper(resources)
    _, first_job = await ensure(resources, document_id, OPENAI)
    await run_job(resources, first_job)
    in_flight = await serving(resources, document_id, OPENAI)
    _, second_job = await ensure(resources, document_id, QWEN)
    assert await serving(resources, document_id, QWEN) == OPENAI
    monkeypatch.setattr(indexing, "WORK_SECONDS", 0)
    await run_job(resources, second_job)
    assert await embedding_count(resources, document_id, QWEN) == 2
    assert await serving(resources, document_id, QWEN) == OPENAI
    assert in_flight == OPENAI and await embedding_count(resources, document_id, OPENAI) == 5
    monkeypatch.setattr(indexing, "WORK_SECONDS", 240)
    await run_job(resources, second_job)
    assert await serving(resources, document_id, QWEN) == QWEN
    assert await serving(resources, document_id, OPENAI) == OPENAI
    assert providers["ollama"][0]["model"] == "qwen3-embedding:4b-q4_K_M"


async def test_given_ready_index_when_rebuilding_then_old_vectors_serve_until_swap(
    resources, providers, monkeypatch
):
    from app.rag import indexing

    _, document_id = await seed_paper(resources)
    index_id, job_id = await ensure(resources, document_id, OPENAI)
    await run_job(resources, job_id)
    rebuild_id, rebuild_job = await ensure(resources, document_id, OPENAI, rebuild=True)
    assert rebuild_id != index_id and rebuild_job != job_id
    rebuild = await load(resources, RetrievalIndex, rebuild_id)
    assert rebuild.chunk_set == CHUNK_SET + "#r" and rebuild.state == "queued"
    assert await ensure(resources, document_id, OPENAI, rebuild=True) == (rebuild_id, rebuild_job)
    monkeypatch.setattr(indexing, "WORK_SECONDS", 0)
    await run_job(resources, rebuild_job)
    assert await embedding_count(resources, document_id, OPENAI) == 5
    assert await embedding_count(resources, document_id, OPENAI + "#r") == 2
    assert await serving(resources, document_id, OPENAI) == OPENAI
    monkeypatch.setattr(indexing, "WORK_SECONDS", 240)
    await run_job(resources, rebuild_job)
    assert await embedding_count(resources, document_id, OPENAI) == 5
    assert await embedding_count(resources, document_id, OPENAI + "#r") == 0
    assert await load(resources, RetrievalIndex, rebuild_id) is None
    index = await load(resources, RetrievalIndex, index_id)
    assert (index.state, index.embedded, index.job_id) == ("ready", 5, rebuild_job)
    assert (await load(resources, BackgroundJob, rebuild_job)).state == "completed"


async def test_given_missing_openai_key_when_embedding_then_index_is_unavailable(
    resources, providers
):
    _, document_id = await seed_paper(resources)
    index_id, job_id = await ensure(resources, document_id, OPENAI)
    resources.settings.openai_api_key = None
    await run_job(resources, job_id)
    index = await load(resources, RetrievalIndex, index_id)
    assert (index.state, index.error_code) == ("unavailable", "MODEL_NOT_CONFIGURED")
    assert index.error_message == "Add an OpenAI API key on the server."
    job = await load(resources, BackgroundJob, job_id)
    assert (job.state, job.attempts) == ("completed", 1)
    assert providers["openai"] == []


async def test_given_uninstalled_local_model_when_embedding_then_index_is_unavailable(
    resources,
):
    # Real admission refuses an uninstalled model before any runtime request.
    _, document_id = await seed_paper(resources)
    index_id, job_id = await ensure(resources, document_id, QWEN)
    await run_job(resources, job_id)
    index = await load(resources, RetrievalIndex, index_id)
    assert index.state == "unavailable"
    assert (index.error_code, index.error_message) == (
        "LOCAL_MODEL_NOT_READY",
        "Download and verify this local model first.",
    )
    assert (await load(resources, BackgroundJob, job_id)).state == "completed"


async def test_given_busy_local_runtime_when_embedding_then_job_waits_without_attempts(
    resources, providers, monkeypatch
):
    from app.core.errors import AppError
    from app.services import local_models

    @asynccontextmanager
    async def busy(resources, key, **options):
        raise AppError(409, "LOCAL_MODEL_BUSY", "A search is waiting for the local runtime.")
        yield

    monkeypatch.setattr(local_models, "retrieval_inference_slot", busy)
    _, document_id = await seed_paper(resources)
    index_id, job_id = await ensure(resources, document_id, QWEN)
    await run_job(resources, job_id)
    job = await load(resources, BackgroundJob, job_id)
    assert (job.state, job.stage, job.generation, job.attempts) == (
        "queued",
        "local_runtime_wait",
        2,
        0,
    )
    # The busy runtime is polled at a bounded pace, not on every dispatch.
    async with resources.sessions() as session:
        assert job.available_at > await session.scalar(select(func.now() + text("interval '5s'")))
        outbox = await session.scalar(
            select(JobOutbox).where(JobOutbox.job_id == job_id, JobOutbox.generation == 2)
        )
    assert outbox.available_at == job.available_at
    assert (await load(resources, RetrievalIndex, index_id)).state == "queued"


async def test_given_local_profile_when_indexing_then_each_admission_embeds_few_passages(
    resources, providers, monkeypatch
):
    """Regression: a 16-passage batch held the search slot for about 1.5 minutes on CPU."""
    from app.integrations.embedding_catalog import embedding_profile
    from app.rag import indexing
    from app.services import local_models

    held = []

    @asynccontextmanager
    async def slot(resources, key, **options):
        before = len(providers["ollama"])
        yield
        sent = [call["input"] for call in providers["ollama"][before:]]
        passages = sum(1 if isinstance(texts, str) else len(texts) for texts in sent)
        held.append((options.get("background"), passages))

    # The catalog's own batches, not the fixture's small ones.
    monkeypatch.setattr(indexing, "embedding_profile", embedding_profile)
    monkeypatch.setattr(local_models, "retrieval_inference_slot", slot)
    _, document_id = await seed_paper(resources)
    index_id, job_id = await ensure(resources, document_id, QWEN)
    await run_job(resources, job_id)
    assert (await load(resources, RetrievalIndex, index_id)).state == "ready"
    # Background admissions of two passages yield the slot to a waiting search between them.
    assert held == [(True, 2), (True, 2), (True, 1)]


async def test_given_provider_failure_when_attempts_run_out_then_index_fails(
    resources, providers, monkeypatch
):
    from app.core.errors import AppError
    from app.integrations import embeddings
    from app.rag import indexing
    from app.repositories.jobs import fail

    def failing(resources, profile):
        return embeddings.create_embedder(
            resources, profile, transport=openai_fixture([], status=400)
        )

    monkeypatch.setattr(indexing, "create_embedder", failing)
    _, document_id = await seed_paper(resources)
    index_id, job_id = await ensure(resources, document_id, OPENAI)
    for _ in range(3):
        async with resources.sessions() as session, session.begin():
            job = await session.get(BackgroundJob, job_id)
            job.available_at = func.now()  # skip the retry backoff
            generation, payload = job.generation, job.payload
        token = await claim(resources.sessions, job_id, generation)
        with pytest.raises(AppError) as error:
            await indexing.run_embed_job(resources, job_id, generation, token, payload)
        assert error.value.code == "EMBEDDING_FAILED"
        # The worker actor routes unexpected errors through fail().
        await fail(resources.sessions, job_id, generation, token)
    index = await load(resources, RetrievalIndex, index_id)
    assert (index.state, index.error_code) == ("failed", "EMBEDDING_FAILED")
    assert (await load(resources, BackgroundJob, job_id)).state == "failed"


async def test_given_profile_choices_when_chunks_persist_then_hook_indexes_effective_profile(
    resources,
):
    from app.rag.hooks import after_chunks_persisted

    default_paper, default_document = await seed_paper(resources)
    override_paper, override_document = await seed_paper(resources, retrieval_profile=OPENAI)
    async with resources.sessions() as session, session.begin():
        await after_chunks_persisted(session, document_id=default_document)
    async with resources.sessions() as session, session.begin():
        session.add(
            ModelConfiguration(
                key="retrieval", value={"embedding_profile": QWEN, "reranker_enabled": False}
            )
        )
    async with resources.sessions() as session, session.begin():
        await after_chunks_persisted(session, document_id=default_document)
        await after_chunks_persisted(session, document_id=override_document)
        await after_chunks_persisted(session, document_id=None)
    async with resources.sessions() as session:
        indexes = (
            await session.execute(select(RetrievalIndex.document_id, RetrievalIndex.profile))
        ).all()
    assert sorted((str(d), p) for d, p in indexes) == sorted(
        [
            (str(default_document), OPENAI),
            (str(default_document), QWEN),
            (str(override_document), OPENAI),
        ]
    )
