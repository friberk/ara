"""Open models sit behind EXPERIMENTAL_OPEN_MODELS, off by default (ARA-090).

With the flag off nothing open-model is offered, mounted, dispatched or prepared. Stored references
to open models stay readable, report themselves unavailable and never switch to a paid model.
"""

import asyncio
from contextlib import suppress
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import func, select

from app.core.config import Settings
from app.integrations.model_catalog import local_spec
from app.models.jobs import BackgroundJob, JobOutbox
from app.models.local_models import ModelInstallation
from app.models.research import GenerationReservation, ModelConfiguration
from app.repositories.jobs import enqueue, now
from tests.support.evidence import CHUNK_SET, seed_structured
from tests.support.papers import OPENAI, QWEN, seed_paper, use_library_profile

LOCAL_CHAT = "ifm-k2-horizon-7b"
SMALL = "openai-3-small"
LOCAL_RERANKER = "qwen3-rerank-0.6b"
HOSTED_RERANKER = "openai-gpt-6-luna"
DISABLED = "OPEN_MODELS_DISABLED"


def client_for(resources):
    from app.main import create_app

    app = create_app(resources.settings)
    app.state.resources = resources
    return httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test")


async def store(resources, key: str, value: dict) -> None:
    async with resources.sessions() as session, session.begin():
        session.add(ModelConfiguration(key=key, value=value))


async def install_ready(resources, key: str) -> None:
    """A verified installation row, as an earlier flag-on session would have left it."""
    spec = local_spec(key)
    async with resources.sessions() as session, session.begin():
        session.add(
            ModelInstallation(
                model_key=key,
                state="ready",
                desired_state="ready",
                weights_present=True,
                digest=spec.expected_digest,
                validation={
                    "digest": spec.expected_digest,
                    "context_window": resources.settings.ollama_context_window,
                    "runtime_version": "0.40.1-ara.fixture",
                    "thinking_schema": 1,
                    "reasoning_efforts": ["default"],
                    "supports_streaming": True,
                    "supports_structured_output": True,
                },
            )
        )


async def jobs_of(resources, *kinds) -> list[BackgroundJob]:
    async with resources.sessions() as session:
        return list(
            (
                await session.scalars(select(BackgroundJob).where(BackgroundJob.kind.in_(kinds)))
            ).all()
        )


def test_given_no_setting_when_loading_settings_then_open_models_are_off(monkeypatch):
    monkeypatch.delenv("EXPERIMENTAL_OPEN_MODELS", raising=False)
    assert Settings(_env_file=None).experimental_open_models is False
    monkeypatch.setenv("EXPERIMENTAL_OPEN_MODELS", "true")
    assert Settings(_env_file=None).experimental_open_models is True


@pytest.mark.integration
async def test_given_flag_off_when_reading_features_and_models_then_only_hosted_models(resources):
    async with client_for(resources) as client:
        features = await client.get("/api/v1/features")
        assert features.status_code == 200 and features.json() == {"open_models": False}
        models = (await client.get("/api/v1/models")).json()["items"]
        assert models and {model["provider"] for model in models} == {"openai"}
        assert all(model["installation"] is None for model in models)
        profiles = (await client.get("/api/v1/retrieval/profiles")).json()
        assert [item["key"] for item in profiles["items"]] == [OPENAI, SMALL]
        assert [item["key"] for item in profiles["rerankers"]] == [HOSTED_RERANKER]


@pytest.mark.integration
@pytest.mark.open_models
async def test_given_flag_on_when_reading_features_and_models_then_open_models_return(resources):
    async with client_for(resources) as client:
        assert (await client.get("/api/v1/features")).json() == {"open_models": True}
        models = (await client.get("/api/v1/models")).json()["items"]
        assert {model["key"] for model in models if model["provider"] == "ollama"} >= {LOCAL_CHAT}
        profiles = (await client.get("/api/v1/retrieval/profiles")).json()
        assert QWEN in {item["key"] for item in profiles["items"]}
        assert LOCAL_RERANKER in {item["key"] for item in profiles["rerankers"]}


@pytest.mark.integration
async def test_given_flag_off_when_calling_model_operations_then_they_do_not_exist(resources):
    async with resources.sessions() as session, session.begin():
        # Unsettled work left by an earlier flag-on session.
        download = await enqueue(
            session, kind="model_download", payload={"model_key": LOCAL_CHAT, "request_id": "x"}
        )
        download.model_key = LOCAL_CHAT
    async with client_for(resources) as client:
        request = {"request_id": str(uuid4())}
        assert (
            await client.post(f"/api/v1/models/{LOCAL_CHAT}/download", json=request)
        ).status_code == 404
        deleted = await client.delete(
            f"/api/v1/models/{LOCAL_CHAT}/installation", headers={"Idempotency-Key": str(uuid4())}
        )
        assert deleted.status_code == 404
        for action in ("pause", "resume", "retry"):
            response = await client.post(f"/api/v1/jobs/{download.id}/{action}", json=request)
            assert response.status_code == 404, action
        assert (await client.get(f"/api/v1/jobs/{download.id}")).status_code == 404
        listed = (await client.get("/api/v1/jobs")).json()["items"]
        assert all(job["kind"] not in {"model_download", "model_delete"} for job in listed)
    (job,) = await jobs_of(resources, "model_download", "model_delete")
    # The existing operation is untouched: still queued in its first generation.
    assert (job.id, job.state, job.generation) == (download.id, "queued", 1)


@pytest.mark.integration
async def test_given_saved_local_default_when_flag_off_then_it_is_unavailable_never_paid(
    resources,
):
    from pydantic import SecretStr

    resources.settings.openai_api_key = SecretStr("http-fixture-only")
    await install_ready(resources, LOCAL_CHAT)
    await store(resources, "defaults", {"default_model": LOCAL_CHAT, "reasoning_effort": "default"})
    paper_id, document_id, _ = await seed_structured(resources)
    async with client_for(resources) as client:
        saved = (await client.get("/api/v1/settings")).json()
        assert saved == {"default_model": LOCAL_CHAT, "reasoning_effort": "default"}
        models = {
            item["key"]: item for item in (await client.get("/api/v1/models")).json()["items"]
        }
        local = models[LOCAL_CHAT]
        assert local["status"] == "unavailable" and local["unavailable_code"] == DISABLED
        assert "hosted model" in local["unavailable_reason"] and local["installation"] is None
        assert {key for key, item in models.items() if item["provider"] == "ollama"} == {LOCAL_CHAT}
        rejected = await client.put(
            "/api/v1/settings",
            json={"default_model": "ifm-k2-horizon-3.7b", "reasoning_effort": "default"},
        )
        assert rejected.status_code == 409 and rejected.json()["code"] == DISABLED
        summary = await client.post(
            f"/api/v1/papers/{paper_id}/summaries",
            json={"model": LOCAL_CHAT, "reasoning_effort": "default", "request_id": str(uuid4())},
        )
        assert summary.status_code == 409 and summary.json()["code"] == DISABLED
        page = (await client.get(f"/api/v1/papers/{paper_id}/summaries")).json()
        assert page["blocked"]["code"] == DISABLED and page["blocked"]["model"] == LOCAL_CHAT
        chat = await client.post(f"/api/v1/papers/{paper_id}/chats", json={})
        chat_id = chat.json()["id"]
        answer = await client.post(
            f"/api/v1/chats/{chat_id}/messages/stream",
            json={
                "content": "What is it about?",
                "model": LOCAL_CHAT,
                "reasoning_effort": "default",
                "request_id": str(uuid4()),
            },
        )
        assert answer.status_code == 409 and answer.json()["code"] == DISABLED
        usage = await client.get(
            f"/api/v1/chats/{chat_id}/usage",
            params={"model": LOCAL_CHAT, "reasoning_effort": "default"},
        )
        assert usage.status_code == 409 and usage.json()["code"] == DISABLED
    assert await jobs_of(resources, "summary") == []
    async with resources.sessions() as session:
        assert await session.scalar(select(func.count()).select_from(GenerationReservation)) == 0
    assert document_id


@pytest.mark.integration
async def test_given_saved_local_retrieval_when_flag_off_then_reported_and_preserved(resources):
    await store(resources, "retrieval", {"embedding_profile": QWEN, "reranker": LOCAL_RERANKER})
    async with client_for(resources) as client:
        profiles = (await client.get("/api/v1/retrieval/profiles")).json()
        assert profiles["default_profile"] == QWEN
        embedders = {item["key"]: item for item in profiles["items"]}
        rerankers = {item["key"]: item for item in profiles["rerankers"]}
        assert set(embedders) == {OPENAI, SMALL, QWEN} and set(rerankers) == {
            HOSTED_RERANKER,
            LOCAL_RERANKER,
        }
        for saved in (embedders[QWEN], rerankers[LOCAL_RERANKER]):
            assert saved["status"] == "unavailable" and saved["local_model_key"] is None
            assert saved["unavailable_reason"].startswith("Open models are turned off")
        assert (await client.get("/api/v1/retrieval/settings")).json()["reranker"] == (
            LOCAL_RERANKER
        )
        chosen = await client.put(
            "/api/v1/retrieval/settings",
            json={"embedding_profile": QWEN, "reranker": None},
        )
        assert chosen.status_code == 200
        rejected = await client.put(
            "/api/v1/retrieval/settings",
            json={"embedding_profile": "qwen3-embed-8b", "reranker": None},
        )
        assert rejected.status_code == 409 and rejected.json()["code"] == DISABLED
        again = await client.put(
            "/api/v1/retrieval/settings",
            json={"embedding_profile": OPENAI, "reranker": LOCAL_RERANKER},
        )
        assert again.status_code == 409 and again.json()["code"] == DISABLED


@pytest.mark.integration
async def test_given_local_library_model_when_flag_off_then_keyword_search_explains(resources):
    paper_id, document_id, _ = await seed_structured(resources, profile=QWEN)
    await use_library_profile(resources, QWEN)
    async with client_for(resources) as client:
        state = (await client.get(f"/api/v1/papers/{paper_id}/retrieval")).json()
        assert state["effective_profile"] == QWEN and state["mode"] == "keyword"
        assert "Open models are turned off" in state["mode_note"]
        assert "hosted search model" in state["mode_note"]
        (index,) = state["indexes"]
        assert index["state"] == "unavailable" and index["error"]["code"] == DISABLED
        rebuilt = await client.post(
            f"/api/v1/papers/{paper_id}/retrieval/rebuild", json={"request_id": str(uuid4())}
        )
        assert rebuilt.status_code == 409 and rebuilt.json()["code"] == DISABLED
    assert await jobs_of(resources, "embed") == []
    assert document_id


@pytest.mark.integration
async def test_given_flag_off_when_estimating_a_switch_then_only_hosted_models_are_priced(
    resources,
):
    await seed_structured(resources)
    async with client_for(resources) as client:
        url = "/api/v1/retrieval/reindex-estimate"
        hosted = await client.get(url, params={"profile": SMALL})
        assert hosted.status_code == 200 and hosted.json()["papers"] == 1
        local = await client.get(url, params={"profile": QWEN})
        assert local.status_code == 409 and local.json()["code"] == DISABLED


@pytest.mark.integration
@pytest.mark.open_models
async def test_given_flag_on_when_estimating_a_local_switch_then_it_is_free(resources):
    await seed_structured(resources)
    async with client_for(resources) as client:
        local = await client.get("/api/v1/retrieval/reindex-estimate", params={"profile": QWEN})
        assert local.status_code == 200
        assert (local.json()["papers"], local.json()["estimated_cost_usd"]) == (1, 0)


@pytest.mark.integration
@pytest.mark.parametrize("preferred", [QWEN, OPENAI])
async def test_given_ready_local_index_when_flag_off_then_answers_search_by_keywords(
    resources, monkeypatch, preferred
):
    from app.integrations.tokens import TiktokenCounter
    from app.rag import pipeline

    _, document_id, _ = await seed_structured(resources, profile=QWEN)
    embedded = []
    monkeypatch.setattr(
        pipeline, "create_embedder", lambda *args, **kwargs: embedded.append(args) or None
    )
    result = await pipeline.retrieve_evidence(
        resources,
        document_id=document_id,
        chunk_set=CHUNK_SET,
        preferred_profile=preferred,
        queries=["BM25 recall dense retrieval"],
        question="How does BM25 recall compare?",
        budget=8000,
        counter=TiktokenCounter(),
        reranker=None,
    )
    assert result.summary.mode == "keyword" and result.summary.profile is None
    assert embedded == [] and result.passages
    if preferred == QWEN:
        assert "open models are turned off" in result.summary.note


@pytest.mark.integration
async def test_given_saved_local_reranker_when_flag_off_then_answers_are_not_reranked(
    resources, monkeypatch
):
    from app.models.research import ChatSession
    from app.schemas.ai import ChatInput
    from app.services import chat
    from tests.support.answers import use_hosted

    paper_id, document_id, _ = await seed_structured(resources)
    await store(resources, "retrieval", {"embedding_profile": OPENAI, "reranker": LOCAL_RERANKER})
    async with resources.sessions() as session, session.begin():
        conversation = ChatSession(paper_id=paper_id, document_id=document_id, title="Q")
        session.add(conversation)
        await session.flush()
    use_hosted(monkeypatch, resources, [], lambda body: "Unused.")
    prepared = await chat.prepare(
        resources,
        conversation.id,
        ChatInput(content="What is it about?", request_id=uuid4(), model="gpt-5.6-luna"),
    )
    assert prepared.reranker is None


@pytest.mark.integration
async def test_given_local_default_profile_when_flag_off_then_reconcile_queues_nothing(
    resources,
):
    from app.integrations.embedding_catalog import PROFILES
    from app.integrations.embeddings import create_embedder
    from app.rag.indexing import UNAVAILABLE, reconcile_indexes

    await install_ready(resources, "qwen3-embedding-4b")
    await store(resources, "retrieval", {"embedding_profile": QWEN})
    await seed_paper(resources)
    assert await reconcile_indexes(resources) == 0
    assert await jobs_of(resources, "embed") == []
    with pytest.raises(Exception) as raised:
        create_embedder(resources, PROFILES[QWEN])
    assert raised.value.code == DISABLED and DISABLED in UNAVAILABLE


@pytest.mark.integration
async def test_given_flag_off_when_dispatching_then_open_model_lanes_are_held(resources):
    from app.services.dispatcher import dispatch_once

    async with resources.sessions() as session, session.begin():
        download = await enqueue(session, kind="model_download", payload={"model_key": LOCAL_CHAT})
        download.model_key = LOCAL_CHAT
        local_summary = await enqueue(
            session, kind="summary", payload={"model": LOCAL_CHAT, "paper_id": str(uuid4())}
        )
        hosted = await enqueue(
            session, kind="summary", payload={"model": "gpt-5.6-luna", "paper_id": str(uuid4())}
        )
        expired = await enqueue(session, kind="model_delete", payload={"model_key": LOCAL_CHAT})
        expired.model_key, expired.state = LOCAL_CHAT, "processing"
        expired.lease_token, expired.lease_expires_at = uuid4(), now() - timedelta(minutes=5)
    published, held = [], []
    await dispatch_once(
        resources.sessions,
        lambda job_id, generation: published.append(job_id),
        model_publish=lambda job_id, generation: held.append(job_id),
        local_publish=lambda job_id, generation: held.append(job_id),
        open_models=False,
    )
    assert published == [str(hosted.id)] and held == []
    from app.repositories.jobs import recover

    await recover(resources.sessions, open_models=False)
    async with resources.sessions() as session:
        untouched = await session.get(BackgroundJob, expired.id)
        assert (untouched.state, untouched.generation) == ("processing", 1)
        pending = (
            await session.scalars(select(JobOutbox.job_id).where(JobOutbox.delivered_at.is_(None)))
        ).all()
    assert set(pending) >= {download.id, local_summary.id}


async def test_given_flag_off_when_dispatcher_runs_then_no_model_preparation(monkeypatch):
    from app.services import dispatcher, local_models

    prepared, dispatched = [], asyncio.Event()

    async def inspect(resources):
        prepared.append(resources)

    async def recover(sessions, **options):
        assert options == {"open_models": False}

    async def dispatch(sessions, publish, **options):
        assert options["open_models"] is False
        dispatched.set()

    monkeypatch.setattr(local_models, "reconcile_local_models", inspect)
    monkeypatch.setattr(dispatcher, "recover", recover)
    monkeypatch.setattr(dispatcher, "dispatch_once", dispatch)
    resources = SimpleNamespace(
        sessions=object(),
        settings=SimpleNamespace(
            recovery_interval_seconds=30,
            dispatch_interval_seconds=0.001,
            experimental_open_models=False,
        ),
    )
    task = asyncio.create_task(dispatcher.dispatcher_loop(resources, lambda *args: None))
    try:
        await asyncio.wait_for(dispatched.wait(), timeout=1)
        await asyncio.sleep(0.01)
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
    assert prepared == []


@pytest.mark.integration
async def test_given_flag_off_without_runtime_when_checking_readiness_then_core_is_ready(
    resources,
):
    from app.services.health import readiness

    # The test stack runs no Ollama at all; readiness checks only the core services.
    assert await readiness(resources) == {"database": "ok", "storage": "ok", "redis": "ok"}
