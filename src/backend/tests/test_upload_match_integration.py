"""An uploaded PDF that is a library paper joins it instead of duplicating it (ARA-086).

A new upload whose DOI, arXiv ID or strictly matched title names a library paper is attached to
that paper when it has no PDF; otherwise the user chooses Replace or Cancel, and nothing paid
starts meanwhile. A match the catalog lookup finds later asks the same question.
"""

from uuid import uuid4

import httpx
import pytest
from sqlalchemy import func, select
from support.academic import DOI, DOI_TITLE, openalex_work, providers
from support.cleanup import cleanup_job, run_cleanup
from support.front_matter import TITLE, toolchain_pdf
from support.llm_server import metadata_model
from test_automatic_summary_integration import save_defaults
from test_fulltext_integration import app_client
from test_metadata_enrichment_integration import (
    DOI_LINES,
    NO_DOI_PAGE,
    detail,
    ingested,
    lookup_job,
    run_lookup,
    use,
)

pytestmark = pytest.mark.integration

WITH_DOI = {"subject": f"doi:{DOI}", "title_lines": DOI_LINES, "stamp": None, "second_page": None}


async def library_paper(resources, **fields):
    from app.integrations.academic import normalize
    from app.repositories.papers import save_canonical

    async with resources.sessions() as session, session.begin():
        paper, _ = await save_canonical(session, normalize("openalex", openalex_work(**fields)))
        paper_id = paper.id
    return paper_id


async def with_pdf(resources, paper_id):
    accepted = await ingested(
        resources,
        toolchain_pdf(title_lines=DOI_LINES, stamp=None, body=f"Original {uuid4()}"),
        paper_id=paper_id,
    )
    return accepted.document_id


async def count(resources, model, *where):
    async with resources.sessions() as session:
        return await session.scalar(select(func.count()).select_from(model).where(*where))


async def test_an_upload_matching_a_library_paper_without_a_pdf_is_attached_to_it(resources):
    from app.models.jobs import BackgroundJob
    from app.models.research import Paper

    saved = await library_paper(resources)
    async with metadata_model(resources, {}) as calls:
        await save_defaults(resources, "gpt-5.6-luna", "low")
        accepted = await ingested(resources, toolchain_pdf(**WITH_DOI))
    # The library paper already has its bibliography, so no model is asked for one.
    assert calls == []
    assert accepted.paper_id != saved
    paper = await detail(resources, accepted.paper_id)
    assert paper.id == saved and paper.active_document_id == accepted.document_id
    assert paper.document_status == "ready" and paper.title == DOI_TITLE
    assert paper.upload_match is None
    assert await count(resources, Paper, Paper.id == accepted.paper_id) == 0
    async with app_client(resources) as client:
        listed = (await client.get("/api/v1/papers")).json()["items"]
    assert [item["id"] for item in listed] == [str(saved)]
    async with resources.sessions() as session:
        ingest = await session.get(BackgroundJob, accepted.job_id)
        summary = await session.scalar(
            select(BackgroundJob).where(
                BackgroundJob.kind == "summary",
                BackgroundJob.payload["document_id"].astext == str(accepted.document_id),
            )
        )
    assert ingest.result["match"] == {
        "paper_id": str(saved),
        "outcome": "attached",
        "matched_by": "doi",
    }
    # Processing and the automatic summary continue on the library paper.
    assert summary is not None and summary.payload["paper_id"] == str(saved)


async def pending_upload(resources):
    """A library paper with a PDF, then a different PDF of the same work uploaded on its own."""
    saved = await library_paper(resources)
    original = await with_pdf(resources, saved)
    async with metadata_model(resources, {}) as calls:
        await save_defaults(resources, "gpt-5.6-luna", "low")
        accepted = await ingested(resources, toolchain_pdf(**WITH_DOI))
    assert calls == []
    return saved, original, accepted


async def test_a_match_with_a_pdf_waits_for_a_decision_without_paid_work(resources):
    from app.models.jobs import BackgroundJob
    from app.models.research import Document, DocumentPage
    from app.models.retrieval import RetrievalIndex

    saved, original, accepted = await pending_upload(resources)
    paper = await detail(resources, accepted.paper_id)
    assert paper.id == accepted.paper_id
    assert paper.upload_match.model_dump() == {
        "paper_id": saved,
        "title": DOI_TITLE,
        "has_pdf": True,
        "matched_by": "doi",
        "found_by": "ingest",
    }
    async with resources.sessions() as session:
        document = await session.get(Document, accepted.document_id)
        assert document.status == "processing"
    assert await count(resources, DocumentPage, DocumentPage.document_id == document.id) == 0
    assert await count(resources, RetrievalIndex, RetrievalIndex.document_id == document.id) == 0
    assert (
        await count(
            resources,
            BackgroundJob,
            BackgroundJob.kind.in_(["summary", "embed", "metadata"]),
            BackgroundJob.payload["document_id"].astext == str(document.id),
        )
        == 0
    )
    async with app_client(resources) as client:
        listed = (await client.get("/api/v1/papers")).json()["items"]
        pending = (await client.get("/api/v1/uploads/matches")).json()["items"]
    assert [item["id"] for item in listed] == [str(saved)]
    assert [item["id"] for item in pending] == [str(accepted.paper_id)]
    assert (await detail(resources, saved)).active_document_id == original


async def test_replace_makes_the_upload_the_active_pdf_and_keeps_the_earlier_one(resources):
    from app.models.jobs import BackgroundJob
    from app.models.research import Document, Paper
    from app.repositories.jobs import claim
    from app.services.ingestion import run_ingest_job

    saved, original, accepted = await pending_upload(resources)
    async with app_client(resources) as client:
        replaced = await client.post(
            f"/api/v1/uploads/{accepted.paper_id}/match", json={"decision": "attach"}
        )
        again = await client.post(
            f"/api/v1/uploads/{accepted.paper_id}/match", json={"decision": "attach"}
        )
    assert replaced.status_code == 200, replaced.text
    assert replaced.json()["id"] == str(saved) and again.json()["id"] == str(saved)
    assert replaced.json()["active_document_id"] == str(accepted.document_id)
    assert replaced.json()["document_status"] == "processing"
    assert await count(resources, Paper, Paper.id == accepted.paper_id) == 0
    async with resources.sessions() as session:
        earlier = await session.get(Document, original)
        assert earlier.paper_id == saved and earlier.status == "ready"
        reingest = await session.scalar(
            select(BackgroundJob).where(
                BackgroundJob.kind == "ingest",
                BackgroundJob.payload["document_id"].astext == str(accepted.document_id),
                BackgroundJob.state == "queued",
            )
        )
    token = await claim(resources.sessions, reingest.id, reingest.generation)
    async with metadata_model(resources, {}):
        await run_ingest_job(resources, reingest.id, reingest.generation, token, reingest.payload)
    paper = await detail(resources, accepted.paper_id)
    assert paper.id == saved and paper.document_status == "ready"
    assert paper.active_document_id == accepted.document_id
    async with resources.sessions() as session:
        summary = await session.scalar(
            select(BackgroundJob).where(
                BackgroundJob.kind == "summary",
                BackgroundJob.payload["document_id"].astext == str(accepted.document_id),
            )
        )
    assert summary is not None and summary.payload["paper_id"] == str(saved)


async def test_cancel_discards_the_upload_and_its_stored_original(resources):
    from minio.error import S3Error

    from app.models.research import Document, Paper

    saved, original, accepted = await pending_upload(resources)
    async with resources.sessions() as session:
        key = (await session.get(Document, accepted.document_id)).object_key
    async with app_client(resources) as client:
        cancelled = await client.post(
            f"/api/v1/uploads/{accepted.paper_id}/match", json={"decision": "discard"}
        )
        again = await client.post(
            f"/api/v1/uploads/{accepted.paper_id}/match", json={"decision": "discard"}
        )
        invalid = await client.post(f"/api/v1/uploads/{saved}/match", json={"decision": "attach"})
    assert cancelled.status_code == 204 and again.status_code == 204
    assert invalid.status_code == 409 and invalid.json()["code"] == "NO_PENDING_MATCH"
    assert await count(resources, Paper, Paper.id == accepted.paper_id) == 0
    assert await count(resources, Document, Document.id == accepted.document_id) == 0
    # The original is removed by the durable cleanup job that the discard queued (ARA-095).
    assert (await cleanup_job(resources)).payload["object_keys"] == [key]
    assert (await run_cleanup(resources)).state == "completed"
    with pytest.raises(S3Error):
        await resources.storage_call(
            resources.storage.stat_object, resources.settings.minio_bucket, key
        )
    assert (await detail(resources, saved)).active_document_id == original


async def test_a_match_found_later_by_the_catalog_lookup_asks_instead_of_duplicating(resources):
    from app.models.research import ChatPaper, Document, Paper
    from tests.support.chats import chat_with

    # The library paper carries the DOI under a title the user edited, so the PDF alone cannot
    # match it; the catalog record found by title then names the DOI.
    saved = await library_paper(resources, work_id="W999", title="My ReDoS reading notes")
    requests = []
    await resources.http.aclose()
    work = openalex_work(authors=("Seunghun Han",))
    use(
        resources,
        providers(requests, openalex=lambda request: httpx.Response(200, json={"results": [work]})),
    )
    accepted = await ingested(
        resources, toolchain_pdf(title_lines=DOI_LINES, stamp=None, second_page=NO_DOI_PAGE)
    )
    assert (await detail(resources, accepted.paper_id)).upload_match is None
    async with resources.sessions() as session, session.begin():
        await chat_with(session, (accepted.paper_id, accepted.document_id))
    job = await run_lookup(resources, accepted.paper_id, due=False)
    assert job.result["outcome"] == "library_match"
    paper = await detail(resources, accepted.paper_id)
    assert paper.upload_match.model_dump() == {
        "paper_id": saved,
        "title": "My ReDoS reading notes",
        "has_pdf": False,
        "matched_by": "title",
        "found_by": "lookup",
    }
    assert paper.sources == []
    async with app_client(resources) as client:
        assert [i["id"] for i in (await client.get("/api/v1/papers")).json()["items"]] == [
            str(saved)
        ]
        attached = await client.post(
            f"/api/v1/uploads/{accepted.paper_id}/match", json={"decision": "attach"}
        )
    assert attached.status_code == 200 and attached.json()["document_status"] == "ready"
    assert attached.json()["active_document_id"] == str(accepted.document_id)
    async with resources.sessions() as session:
        link = await session.scalar(select(ChatPaper))
        assert (link.paper_id, link.document_id) == (saved, accepted.document_id)
        assert (await session.get(Document, accepted.document_id)).paper_id == saved
    assert await count(resources, Paper, Paper.id == accepted.paper_id) == 0
    assert await lookup_job(resources, saved) is None


async def test_an_upload_into_a_paper_names_a_library_paper_that_owns_its_doi(resources):
    owner = await library_paper(resources)
    target = await library_paper(
        resources, work_id="W5", title="An unrelated saved paper", doi="10.5555/other"
    )
    accepted = await ingested(resources, toolchain_pdf(**WITH_DOI), paper_id=target)
    paper = await detail(resources, target)
    assert accepted.paper_id == target and paper.active_document_id == accepted.document_id
    assert paper.upload_match is None
    assert paper.pdf_doi_owner.model_dump() == {"paper_id": owner, "title": DOI_TITLE}


@pytest.mark.parametrize(
    ("authors", "year", "matches"),
    [(("Seunghun Han",), 2018, True), (("Somebody Else",), 2020, False)],
)
async def test_a_title_only_match_needs_an_agreeing_author_or_year(
    resources, authors, year, matches
):
    saved = await library_paper(
        resources, work_id="W7", title=TITLE, doi=None, authors=authors, year=year
    )
    accepted = await ingested(resources, toolchain_pdf(stamp=None, second_page=NO_DOI_PAGE))
    paper = await detail(resources, accepted.paper_id)
    assert (paper.id == saved) is matches
    assert (paper.active_document_id == accepted.document_id) is True
