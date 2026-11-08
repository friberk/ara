"""A refresh of an upload with no provider record reads its stored PDF again (ARA-095, ARA-117).

These drive `run_metadata_job` through "Look up again" against real PostgreSQL and MinIO, with
providers that find nothing, so what changes on the paper can only have come from the PDF.
"""

import asyncio
from uuid import uuid4

import httpx
import pytest
from minio.error import S3Error
from sqlalchemy import delete, select, update
from support.academic import DOI, providers
from support.front_matter import toolchain_pdf
from test_metadata_enrichment_integration import detail, ingested, run_lookup, use
from test_paper_deletion_integration import client_for

from app.models.jobs import BackgroundJob
from app.models.research import Document, Paper

pytestmark = pytest.mark.integration

NO_DOI_PAGE = "References\n[1] A reference without identifiers."
PDF_AUTHORS = ["Ada Researcher", "Grace Scholar"]
WITH_DOI = {"subject": f"doi:{DOI}", "stamp": None, "second_page": NO_DOI_PAGE}
WITH_AUTHORS = {"info_author": "Ada Researcher; Grace Scholar", "stamp": None}


async def queued_refresh(resources, pdf: dict, **paper_values):
    """An upload whose stored PDF has `pdf`, whose paper now holds `paper_values`, with
    "Look up again" queued. Returns the paper's ID."""
    accepted = await ingested(resources, toolchain_pdf(**pdf))
    async with resources.sessions() as session, session.begin():
        await session.execute(delete(BackgroundJob).where(BackgroundJob.kind == "metadata"))
        await session.execute(
            update(Paper).where(Paper.id == accepted.paper_id).values(**paper_values)
        )
    async with client_for(resources) as client:
        response = await client.post(f"/api/v1/papers/{accepted.paper_id}/metadata-lookup")
    assert response.status_code == 202, response.text
    return accepted.paper_id


async def no_provider_match(resources) -> list:
    requests = []
    await resources.http.aclose()
    use(
        resources,
        providers(
            requests,
            openalex=lambda request: httpx.Response(200, json={"results": []}),
            semantic_scholar=lambda request: httpx.Response(404, json={"error": "not found"}),
        ),
    )
    return requests


async def set_authors(resources, paper_id, names: list[str], source: str | None) -> None:
    from app.repositories.papers import replace_authors

    async with resources.sessions() as session, session.begin():
        await replace_authors(session, paper_id, names)
        paper = await session.get(Paper, paper_id)
        paper.metadata_provenance = {"authors": {"source": source}} if source else {}


async def test_a_doi_in_the_stored_pdf_is_adopted(resources):
    """Given an upload that lost its DOI, the re-read PDF supplies it with its provenance."""
    await no_provider_match(resources)
    paper_id = await queued_refresh(
        resources, WITH_DOI, doi=None, normalized_doi=None, metadata_provenance={}
    )
    job = await run_lookup(resources, paper_id)
    assert job.state == "completed" and job.result["outcome"] == "no_match"
    paper = await detail(resources, paper_id)
    assert paper.doi == DOI and paper.metadata_provenance["doi"] == {"source": "pdf"}


async def test_a_doi_another_paper_owns_is_left_alone(resources):
    """Given another paper with the PDF's DOI, the refresh finishes without taking it."""
    await no_provider_match(resources)
    paper_id = await queued_refresh(
        resources, WITH_DOI, doi=None, normalized_doi=None, metadata_provenance={}
    )
    owner_id = uuid4()
    async with resources.sessions() as session, session.begin():
        session.add(Paper(id=owner_id, title="The owner", doi=DOI, normalized_doi=DOI))
    job = await run_lookup(resources, paper_id)
    assert job.state == "completed" and job.result["outcome"] == "no_match"
    paper = await detail(resources, paper_id)
    assert paper.doi is None and "doi" not in paper.metadata_provenance
    assert (await detail(resources, owner_id)).doi == DOI


@pytest.mark.parametrize("manual", ["10.1000/typed.by.hand", None], ids=["typed", "cleared"])
async def test_a_manual_doi_decision_is_not_replaced_by_the_pdf(resources, manual):
    """Given a DOI the user typed or deliberately cleared, the PDF's DOI does not replace it."""
    await no_provider_match(resources)
    paper_id = await queued_refresh(
        resources,
        WITH_DOI,
        doi=manual,
        normalized_doi=manual,
        metadata_provenance={"doi": {"source": "manual"}},
    )
    job = await run_lookup(resources, paper_id)
    assert job.state == "completed"
    paper = await detail(resources, paper_id)
    assert paper.doi == manual and paper.metadata_provenance["doi"] == {"source": "manual"}


@pytest.mark.parametrize(
    ("listed", "source", "expected", "recorded"),
    [
        pytest.param([], None, PDF_AUTHORS, {"source": "pdf"}, id="none-yet"),
        pytest.param(["Old Reading"], "pdf", PDF_AUTHORS, {"source": "pdf"}, id="earlier-pdf"),
        pytest.param(["My Name"], "manual", ["My Name"], {"source": "manual"}, id="manual"),
        pytest.param([], "manual", [], {"source": "manual"}, id="manually-cleared"),
        pytest.param(["Model Name"], "llm", ["Model Name"], {"source": "llm"}, id="model"),
    ],
)
async def test_authors_from_the_stored_pdf_replace_only_pdf_values(
    resources, listed, source, expected, recorded
):
    """Given authors from any source, only missing or PDF-read ones take the PDF's list."""
    await no_provider_match(resources)
    paper_id = await queued_refresh(resources, WITH_AUTHORS, metadata_provenance={})
    await set_authors(resources, paper_id, listed, source)
    job = await run_lookup(resources, paper_id)
    assert job.state == "completed"
    paper = await detail(resources, paper_id)
    assert paper.authors == expected and paper.metadata_provenance["authors"] == recorded


async def test_a_paper_deleted_during_the_re_read_settles_the_job_without_a_lookup(
    resources, monkeypatch
):
    """Given a paper deleted while its PDF is being read, the job stops and no provider is asked."""
    from app.services import metadata

    requests = await no_provider_match(resources)
    paper_id = await queued_refresh(resources, WITH_AUTHORS, metadata_provenance={})
    read = metadata.reread_pdf

    async def deleted_meanwhile(resources, object_key):
        found = await read(resources, object_key)
        async with resources.sessions() as session, session.begin():
            await session.execute(
                update(Paper).where(Paper.id == paper_id).values(active_document_id=None)
            )
            await session.execute(delete(Document).where(Document.paper_id == paper_id))
            await session.execute(delete(Paper).where(Paper.id == paper_id))
        return found

    monkeypatch.setattr(metadata, "reread_pdf", deleted_meanwhile)
    job = await run_lookup(resources, paper_id)
    assert job.state == "failed" and job.result["outcome"] == "paper_deleted"
    assert job.lease_token is None
    assert requests == []


async def test_a_stored_pdf_that_is_gone_leaves_the_details_and_the_lookup_continues(
    resources, monkeypatch
):
    """Given a PDF missing from MinIO, the refresh falls back to the paper's own details."""
    from app.services import ingestion

    requests = await no_provider_match(resources)
    junk = {"title": "paper.dvi", "metadata_provenance": {"title": {"source": "pdf"}}}
    paper_id = await queued_refresh(resources, WITH_DOI, **junk)
    async with resources.sessions() as session:
        key = await session.scalar(select(Document.object_key).where(Document.paper_id == paper_id))
    await asyncio.to_thread(resources.storage.remove_object, resources.settings.minio_bucket, key)
    monkeypatch.setattr(
        ingestion, "parse_in_child", lambda *args, **kwargs: pytest.fail("nothing to parse")
    )
    job = await run_lookup(resources, paper_id)
    assert job.state == "completed" and job.result["outcome"] == "no_match"
    assert job.payload["reread"] is True and requests
    assert (await detail(resources, paper_id)).title == "paper.dvi"


@pytest.mark.parametrize(
    "failure",
    [
        pytest.param(S3Error(None, "AccessDenied", "denied", "r", "q", "h"), id="s3-refusal"),
        pytest.param(OSError("storage offline"), id="connection"),
    ],
)
async def test_a_storage_failure_retries_the_job_before_asking_any_provider(
    resources, monkeypatch, failure
):
    """Given storage that cannot answer, the job is retried and the paper does not change."""
    requests = await no_provider_match(resources)
    junk = {"title": "paper.dvi", "metadata_provenance": {"title": {"source": "pdf"}}}
    paper_id = await queued_refresh(resources, WITH_DOI, **junk)

    async def unavailable(*args, **kwargs):
        raise failure

    # Only for this job: the resources fixture needs working storage to clean up afterwards.
    with monkeypatch.context() as patch:
        patch.setattr(resources, "storage_call", unavailable)
        job = await run_lookup(resources, paper_id)
    assert job.state == "queued" and job.error_code == "STORAGE_UNAVAILABLE"
    assert "reread" not in job.payload and requests == []
    assert (await detail(resources, paper_id)).title == "paper.dvi"
