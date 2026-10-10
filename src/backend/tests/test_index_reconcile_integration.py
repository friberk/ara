"""Indexes follow the default profile, newly verified local embedders and added keys (ARA-072)."""

import asyncio

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import select, update

from app.integrations.model_catalog import local_spec
from app.models.jobs import BackgroundJob
from app.models.local_models import ModelInstallation
from app.models.research import Document, DocumentChunk
from app.models.retrieval import RetrievalIndex
from app.rag.chunking import CHUNK_SET as CURRENT
from app.repositories.jobs import enqueue
from tests.support.papers import CHUNK_SET, OPENAI, QWEN, seed_paper

pytestmark = pytest.mark.integration
EMBEDDER = "qwen3-embedding-4b"


@pytest.fixture
async def client(resources):
    from app.main import create_app

    app = create_app(resources.settings)
    app.state.resources = resources
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as http:
        yield http


def validation(resources) -> dict:
    spec = local_spec(EMBEDDER)
    return {
        "kind": "embedding",
        "digest": spec.expected_digest,
        "runtime_version": "0.40.1-ara.fixture",
        "context_window": resources.settings.ollama_context_window,
        "thinking_schema": 1,
        "embedding_dimensions": 2560,
    }


async def install(resources, *, state="ready") -> None:
    async with resources.sessions() as session, session.begin():
        session.add(
            ModelInstallation(
                model_key=EMBEDDER,
                state=state,
                desired_state="ready",
                weights_present=True,
                digest=local_spec(EMBEDDER).expected_digest,
                validation=validation(resources) if state == "ready" else None,
            )
        )


async def set_index(resources, document_id, profile, **values) -> None:
    async with resources.sessions() as session, session.begin():
        session.add(
            RetrievalIndex(
                document_id=document_id, profile=profile, chunk_set=CHUNK_SET, total=5, **values
            )
        )


async def embed_jobs(resources) -> list[tuple[str, str]]:
    async with resources.sessions() as session:
        jobs = (
            await session.scalars(
                select(BackgroundJob)
                .where(BackgroundJob.kind == "embed")
                .order_by(BackgroundJob.created_at)
            )
        ).all()
    return [(job.payload["document_id"], job.payload["profile"]) for job in jobs]


async def index(resources, document_id, profile) -> RetrievalIndex | None:
    async with resources.sessions() as session:
        return await session.scalar(
            select(RetrievalIndex).where(
                RetrievalIndex.document_id == document_id, RetrievalIndex.profile == profile
            )
        )


@pytest.mark.open_models
async def test_given_papers_following_the_default_when_it_changes_then_each_is_queued_once(
    resources, client
):
    await install(resources)
    _, following = await seed_paper(resources)
    _, pinned = await seed_paper(resources, retrieval_profile=OPENAI)
    for document_id in (following, pinned):
        await set_index(resources, document_id, OPENAI, state="ready", embedded=5)
    url = "/api/v1/retrieval/settings"
    for profile in (QWEN, OPENAI, QWEN):
        saved = await client.put(url, json={"embedding_profile": profile, "reranker": None})
        assert saved.status_code == 200, saved.text
    assert await embed_jobs(resources) == [(str(following), QWEN)]
    assert (await index(resources, following, QWEN)).state == "queued"
    assert await index(resources, pinned, QWEN) is None
    rerank = await client.put(
        url, json={"embedding_profile": QWEN, "reranker": "openai-gpt-6-luna"}
    )
    assert rerank.status_code == 200
    assert len(await embed_jobs(resources)) == 1


@pytest.mark.open_models
async def test_given_uninstalled_default_when_its_model_verifies_then_papers_are_queued(
    resources, client, monkeypatch
):
    from app.repositories.local_models import claim_model_job
    from app.services import local_models

    _, document_id = await seed_paper(resources)
    saved = await client.put(
        "/api/v1/retrieval/settings", json={"embedding_profile": QWEN, "reranker": None}
    )
    assert saved.status_code == 200, saved.text
    # Nothing can embed with a model that is not installed yet.
    assert await embed_jobs(resources) == []

    class VerifyingRuntime:
        async def artifact(self, spec):
            return {"name": spec.model_id, "digest": spec.expected_digest}

        async def verify(self, spec, *, context_window):
            return validation(resources)

        async def pause(self, operation):
            return None

    await install(resources, state="queued")
    async with resources.sessions() as session, session.begin():
        job = await enqueue(
            session, kind="model_download", payload={"model_key": EMBEDDER, "verify_only": True}
        )
        job.model_key = EMBEDDER
        (await session.get(ModelInstallation, EMBEDDER)).active_job_id = job.id
    monkeypatch.setattr(local_models, "runtime", lambda resources: VerifyingRuntime())
    token = await claim_model_job(resources.sessions, job.id, 1)
    await local_models.run_model_job(resources, job.id, 1, token)
    async with resources.sessions() as session:
        assert (await session.get(ModelInstallation, EMBEDDER)).state == "ready"
        assert (await session.get(BackgroundJob, job.id)).state == "completed"
    assert await embed_jobs(resources) == [(str(document_id), QWEN)]


async def test_given_key_added_after_upload_when_reconciled_then_unavailable_indexes_requeue(
    resources,
):
    from app.rag.indexing import reconcile_indexes

    _, document_id = await seed_paper(resources)
    await set_index(
        resources,
        document_id,
        OPENAI,
        state="unavailable",
        error_code="MODEL_NOT_CONFIGURED",
        error_message="Add an OpenAI API key on the server.",
    )
    resources.settings.openai_api_key = None
    assert await reconcile_indexes(resources) == 0
    assert (await index(resources, document_id, OPENAI)).state == "unavailable"
    # The key arrives with a restart; startup reconciles again.
    resources.settings.openai_api_key = SecretStr("http-fixture-only")
    assert await reconcile_indexes(resources) == 1
    rebuilt = await index(resources, document_id, OPENAI)
    assert (rebuilt.state, rebuilt.error_code, rebuilt.total) == ("queued", None, 5)
    assert await reconcile_indexes(resources) == 0
    assert await embed_jobs(resources) == [(str(document_id), OPENAI)]


async def test_given_mixed_documents_when_reconciled_then_only_missing_available_indexes_queue(
    resources,
):
    from app.rag.indexing import reconcile_indexes

    resources.settings.openai_api_key = SecretStr("http-fixture-only")
    _, missing = await seed_paper(resources)
    _, ready = await seed_paper(resources)
    await set_index(resources, ready, OPENAI, state="ready", embedded=5)
    _, failed = await seed_paper(resources)
    await set_index(
        resources,
        failed,
        OPENAI,
        state="failed",
        error_code="EMBEDDING_FAILED",
        error_message="The embedding request failed.",
    )
    _, uninstalled = await seed_paper(resources, retrieval_profile=QWEN)
    _, processing = await seed_paper(resources)
    _, unchunked = await seed_paper(resources)
    _, reingesting = await seed_paper(resources)
    async with resources.sessions() as session, session.begin():
        (await session.get(Document, processing)).status = "processing"
        (await session.get(Document, unchunked)).chunk_set = None
        # A queued re-ingest replaces the chunks and indexes them itself.
        await enqueue(session, kind="ingest", payload={"document_id": str(reingesting)})

    assert await reconcile_indexes(resources) == 1
    assert await embed_jobs(resources) == [(str(missing), OPENAI)]
    assert (await index(resources, failed, OPENAI)).state == "failed"
    assert await index(resources, uninstalled, QWEN) is None


async def test_given_concurrent_reconciliations_then_each_index_is_queued_once(resources):
    from app.rag.indexing import reconcile_indexes

    resources.settings.openai_api_key = SecretStr("http-fixture-only")
    documents = [(await seed_paper(resources))[1] for _ in range(3)]
    counts = await asyncio.gather(*(reconcile_indexes(resources) for _ in range(3)))
    assert sum(counts) == 3
    assert sorted(await embed_jobs(resources)) == sorted((str(d), OPENAI) for d in documents)


async def test_given_a_paper_without_an_index_when_the_api_starts_then_its_index_is_queued(
    resources, monkeypatch
):
    from app import main
    from app.services import reindex

    prepared = asyncio.Event()

    async def idle(*args, **options):
        await asyncio.Event().wait()

    async def prepare(resources):
        await reindex.prepare_search(resources)
        prepared.set()

    # The dispatcher would publish to the broker; this test only watches startup preparation.
    monkeypatch.setattr(main, "dispatcher_loop", idle)
    monkeypatch.setattr(main, "prepare_search", prepare)
    resources.settings.openai_api_key = SecretStr("http-fixture-only")
    _, document_id = await seed_paper(resources)
    async with resources.sessions() as session, session.begin():
        # At the current chunk set the document needs no re-ingest, only its index.
        (await session.get(Document, document_id)).chunk_set = CURRENT
        await session.execute(
            update(DocumentChunk)
            .where(DocumentChunk.document_id == document_id)
            .values(chunk_set=CURRENT)
        )
    app = main.create_app(resources.settings)
    async with app.router.lifespan_context(app):
        await asyncio.wait_for(prepared.wait(), 10)
    assert await embed_jobs(resources) == [(str(document_id), OPENAI)]


async def test_given_an_unreachable_database_when_preparing_search_then_it_retries(
    resources, monkeypatch
):
    from app.services import reindex

    attempts = []

    async def flaky(resources):
        attempts.append(len(attempts))
        if len(attempts) == 1:
            raise ConnectionError("synthetic database outage")
        return 0

    monkeypatch.setattr(reindex, "reconcile_indexes", flaky)
    resources.settings.recovery_interval_seconds = 0.01
    await asyncio.wait_for(reindex.prepare_search(resources), 5)
    assert attempts == [0, 1]
