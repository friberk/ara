"""Retrieval settings, embedding profiles and per-paper search indexes over HTTP (ARA-072)."""

from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import func, select

from app.models.jobs import BackgroundJob
from app.models.research import Paper
from app.models.retrieval import RetrievalIndex
from tests.support.papers import CHUNK_SET, OPENAI, QWEN, seed_paper

pytestmark = pytest.mark.integration


@pytest.fixture
async def client(resources):
    from app.main import create_app

    app = create_app(resources.settings)
    app.state.resources = resources
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as http:
        yield http


async def set_index(resources, document_id, profile=OPENAI, **values):
    async with resources.sessions() as session, session.begin():
        session.add(
            RetrievalIndex(
                document_id=document_id, profile=profile, chunk_set=CHUNK_SET, total=5, **values
            )
        )


async def embed_jobs(resources):
    async with resources.sessions() as session:
        return (
            await session.scalars(select(BackgroundJob).where(BackgroundJob.kind == "embed"))
        ).all()


async def test_given_no_providers_when_listing_profiles_then_reasons_are_plain(resources, client):
    resources.settings.openai_api_key = None
    response = await client.get("/api/v1/retrieval/profiles")
    assert response.status_code == 200, response.text
    page = response.json()
    assert page["default_profile"] == OPENAI
    items = {item["key"]: item for item in page["items"]}
    assert list(items) == [OPENAI, QWEN, "qwen3-embed-8b"]
    assert items[OPENAI]["status"] == "unavailable"
    assert items[OPENAI]["unavailable_reason"] == "Add an OpenAI API key on the server."
    assert items[OPENAI]["dimensions"] == 3072 and items[OPENAI]["provider"] == "openai"
    assert items[QWEN] == {
        "key": QWEN,
        "provider": "ollama",
        "model_id": "qwen3-embedding:4b-q4_K_M",
        "display_name": "Qwen3 Embedding 4B",
        "dimensions": 2560,
        "status": "unavailable",
        "unavailable_reason": "Download Qwen3 Embedding 4B in Settings.",
        "local_model_key": "qwen3-embedding-4b",
    }
    resources.settings.openai_api_key = SecretStr("http-fixture-only")
    items = (await client.get("/api/v1/retrieval/profiles")).json()["items"]
    assert items[0]["status"] == "available" and items[0]["unavailable_reason"] is None


async def test_given_settings_when_saving_then_profile_is_validated_and_stored(resources, client):
    response = await client.get("/api/v1/retrieval/settings")
    assert response.json() == {"embedding_profile": OPENAI, "reranker_enabled": False}
    saved = await client.put(
        "/api/v1/retrieval/settings",
        json={"embedding_profile": "qwen3-embed-8b", "reranker_enabled": True},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json() == {"embedding_profile": "qwen3-embed-8b", "reranker_enabled": True}
    assert (await client.get("/api/v1/retrieval/settings")).json() == saved.json()
    page = (await client.get("/api/v1/retrieval/profiles")).json()
    assert page["default_profile"] == "qwen3-embed-8b"
    invalid = await client.put(
        "/api/v1/retrieval/settings",
        json={"embedding_profile": "bge-small", "reranker_enabled": False},
    )
    assert invalid.status_code == 422 and invalid.json()["code"] == "INVALID_EMBEDDING_PROFILE"
    extra = await client.put(
        "/api/v1/retrieval/settings", json={"embedding_profile": OPENAI, "rerank_top_k": 30}
    )
    assert extra.status_code == 422


async def test_given_paper_without_document_when_reading_then_retrieval_is_unavailable(
    resources, client
):
    async with resources.sessions() as session, session.begin():
        paper = Paper(title="Metadata only")
        session.add(paper)
    response = await client.get(f"/api/v1/papers/{paper.id}/retrieval")
    assert response.status_code == 200, response.text
    assert response.json() == {
        "paper_id": str(paper.id),
        "document_id": None,
        "effective_profile": OPENAI,
        "source": "default",
        "parser": None,
        "chunk_count": 0,
        "section_count": 0,
        "mode": "unavailable",
        "mode_note": "Upload and process a PDF to search this paper.",
        "indexes": [],
    }
    missing = await client.get(f"/api/v1/papers/{uuid4()}/retrieval")
    assert missing.status_code == 404 and missing.json()["code"] == "PAPER_NOT_FOUND"


@pytest.mark.parametrize(
    ("status", "note"),
    [
        ("processing", "The PDF is still being processed."),
        ("failed", "The PDF could not be processed, so it cannot be searched."),
    ],
)
async def test_given_unready_document_when_reading_then_note_names_the_pdf_state(
    resources, client, status, note
):
    from app.models.research import Document

    paper_id, document_id = await seed_paper(resources)
    async with resources.sessions() as session, session.begin():
        (await session.get(Document, document_id)).status = status
    body = (await client.get(f"/api/v1/papers/{paper_id}/retrieval")).json()
    assert (body["mode"], body["mode_note"], body["document_id"]) == (
        "unavailable",
        note,
        str(document_id),
    )
    assert body["chunk_count"] == 0 and body["indexes"] == []


@pytest.mark.parametrize(
    ("index", "mode", "note"),
    [
        (None, "keyword", "Search index has not been built yet."),
        ({"state": "embedding", "embedded": 2}, "keyword", "Search index is building (40%)."),
        (
            {
                "state": "unavailable",
                "error_code": "MODEL_NOT_CONFIGURED",
                "error_message": "Add an OpenAI API key on the server.",
            },
            "keyword",
            "Search index unavailable: Add an OpenAI API key on the server.",
        ),
        (
            {
                "state": "failed",
                "error_code": "EMBEDDING_FAILED",
                "error_message": "The embedding request failed.",
            },
            "keyword",
            "Search index could not be built: The embedding request failed.",
        ),
        ({"state": "ready", "embedded": 5}, "hybrid", None),
    ],
)
async def test_given_index_state_when_reading_paper_then_mode_explains_search(
    resources, client, index, mode, note
):
    paper_id, document_id = await seed_paper(resources)
    if index is not None:
        await set_index(resources, document_id, **index)
    body = (await client.get(f"/api/v1/papers/{paper_id}/retrieval")).json()
    assert (body["mode"], body["mode_note"]) == (mode, note)
    assert body["document_id"] == str(document_id)
    assert (body["parser"], body["chunk_count"], body["section_count"]) == (
        "pymupdf4llm-layout",
        5,
        0,
    )
    if index is None:
        assert body["indexes"] == []
    else:
        (entry,) = body["indexes"]
        assert entry["profile"] == OPENAI and entry["state"] == index["state"]
        assert (entry["embedded"], entry["total"]) == (index.get("embedded", 0), 5)
        assert entry["updated_at"] is not None
        expected = (
            {"code": index["error_code"], "message": index["error_message"]}
            if "error_code" in index
            else None
        )
        assert entry["error"] == expected


async def test_given_other_profile_ready_when_switching_then_it_serves_until_new_is_ready(
    resources, client
):
    paper_id, document_id = await seed_paper(resources, retrieval_profile=QWEN)
    await set_index(resources, document_id, OPENAI, state="ready", embedded=5)
    await set_index(resources, document_id, QWEN, state="embedding", embedded=1)
    body = (await client.get(f"/api/v1/papers/{paper_id}/retrieval")).json()
    assert (body["effective_profile"], body["source"], body["mode"]) == (QWEN, "paper", "hybrid")
    assert body["mode_note"] == (
        "Searching with OpenAI text-embedding-3-large until Qwen3 Embedding 4B is ready (20%)."
    )
    assert [entry["profile"] for entry in body["indexes"]] == [OPENAI, QWEN]


async def test_given_profile_change_when_replayed_then_the_same_body_returns(resources, client):
    paper_id, document_id = await seed_paper(resources)
    identity = str(uuid4())
    url = f"/api/v1/papers/{paper_id}/retrieval"
    first = await client.put(url, json={"profile": QWEN, "request_id": identity})
    assert first.status_code == 200, first.text
    body = first.json()
    assert (body["effective_profile"], body["source"], body["mode"]) == (QWEN, "paper", "keyword")
    assert body["mode_note"] == "Search index is building (0%)."
    (job,) = await embed_jobs(resources)
    assert job.payload["profile"] == QWEN
    async with resources.sessions() as session:
        assert (await session.get(Paper, paper_id)).retrieval_profile == QWEN
    reset = await client.put(url, json={"profile": None, "request_id": str(uuid4())})
    assert reset.status_code == 200
    assert (reset.json()["effective_profile"], reset.json()["source"]) == (OPENAI, "default")
    replay = await client.put(url, json={"profile": QWEN, "request_id": identity})
    assert replay.status_code == 200 and replay.json() == body
    assert len(await embed_jobs(resources)) == 2
    async with resources.sessions() as session:
        assert (await session.get(Paper, paper_id)).retrieval_profile is None
    conflict = await client.put(url, json={"profile": OPENAI, "request_id": identity})
    assert conflict.status_code == 409 and conflict.json()["code"] == "RETRIEVAL_REQUEST_CONFLICT"
    other_paper, _ = await seed_paper(resources)
    foreign = await client.put(
        f"/api/v1/papers/{other_paper}/retrieval", json={"profile": QWEN, "request_id": identity}
    )
    assert foreign.status_code == 409
    invalid = await client.put(url, json={"profile": "bge-small", "request_id": str(uuid4())})
    assert invalid.status_code == 422 and invalid.json()["code"] == "INVALID_EMBEDDING_PROFILE"


async def test_given_ready_index_when_rebuilding_then_it_keeps_serving(resources, client):
    paper_id, document_id = await seed_paper(resources)
    await set_index(resources, document_id, OPENAI, state="ready", embedded=5)
    identity = str(uuid4())
    url = f"/api/v1/papers/{paper_id}/retrieval/rebuild"
    response = await client.post(url, json={"request_id": identity})
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["mode"] == "hybrid"
    assert body["mode_note"] == "Rebuilding the search index (0%). The current index keeps serving."
    (entry,) = body["indexes"]
    assert (entry["profile"], entry["state"], entry["embedded"]) == (OPENAI, "queued", 0)
    replay = await client.post(url, json={"request_id": identity})
    assert replay.status_code == 202 and replay.json() == body
    assert len(await embed_jobs(resources)) == 1
    async with resources.sessions() as session:
        chunk_sets = (
            await session.scalars(
                select(RetrievalIndex.chunk_set).order_by(RetrievalIndex.created_at)
            )
        ).all()
    assert chunk_sets == [CHUNK_SET, CHUNK_SET + "#r"]
    async with resources.sessions() as session, session.begin():
        paper = Paper(title="No PDF")
        session.add(paper)
    missing = await client.post(
        f"/api/v1/papers/{paper.id}/retrieval/rebuild", json={"request_id": str(uuid4())}
    )
    assert missing.status_code == 409 and missing.json()["code"] == "DOCUMENT_NOT_INDEXABLE"
    async with resources.sessions() as session:
        assert await session.scalar(select(func.count()).select_from(BackgroundJob)) == 1


async def test_given_embed_job_when_listing_jobs_then_it_links_to_its_paper(resources, client):
    paper_id, _ = await seed_paper(resources)
    other_paper, _ = await seed_paper(resources)
    for paper in (paper_id, other_paper):
        response = await client.put(
            f"/api/v1/papers/{paper}/retrieval", json={"profile": QWEN, "request_id": str(uuid4())}
        )
        assert response.status_code == 200, response.text
    page = (await client.get("/api/v1/jobs", params={"paper_id": str(paper_id)})).json()
    (job,) = page["items"]
    assert (job["kind"], job["paper_id"], job["paper_title"]) == (
        "embed",
        str(paper_id),
        "Sparse Retrieval",
    )
    listed = (await client.get("/api/v1/jobs")).json()["items"]
    assert {item["paper_id"] for item in listed} == {str(paper_id), str(other_paper)}
