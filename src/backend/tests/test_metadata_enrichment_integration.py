"""Uploaded PDFs take authoritative metadata from the selected source (ARA-086)."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import select, update
from support.academic import (
    DOI,
    DOI_ABSTRACT,
    openalex_work,
    providers,
    semantic_paper,
)
from support.front_matter import TITLE, toolchain_pdf

pytestmark = pytest.mark.integration

DOI_LINES = ("Exploiting Input Sanitization for", "Regex Denial of Service")
NO_DOI_PAGE = "References\n[1] A reference without identifiers."


async def ingested(resources, data, *, paper_id=None):
    """Upload bytes and run their ingest job, as the worker would."""
    from app.models.jobs import BackgroundJob
    from app.repositories.jobs import claim
    from app.services.ingestion import run_ingest_job
    from app.services.uploads import ingest_pdf_bytes

    accepted = await ingest_pdf_bytes(
        resources, data=data, filename="paper.pdf", request_id=uuid4(), paper_id=paper_id
    )
    async with resources.sessions() as session:
        job = await session.get(BackgroundJob, accepted.job_id)
        generation, payload = job.generation, job.payload
    token = await claim(resources.sessions, accepted.job_id, generation)
    await run_ingest_job(resources, accepted.job_id, generation, token, payload)
    return accepted


async def lookup_job(resources, paper_id):
    from app.models.jobs import BackgroundJob

    async with resources.sessions() as session:
        return await session.scalar(
            select(BackgroundJob).where(
                BackgroundJob.kind == "metadata",
                BackgroundJob.payload["paper_id"].astext == str(paper_id),
            )
        )


async def run_lookup(resources, paper_id, *, due=True):
    """Claim and run the paper's metadata job; `due` skips any scheduled wait."""
    from app.models.jobs import BackgroundJob
    from app.repositories.jobs import claim
    from app.services.metadata import run_metadata_job

    job = await lookup_job(resources, paper_id)
    if due:
        async with resources.sessions() as session, session.begin():
            await session.execute(
                update(BackgroundJob)
                .where(BackgroundJob.id == job.id)
                .values(available_at=datetime.now(UTC) - timedelta(seconds=1))
            )
    token = await claim(resources.sessions, job.id, job.generation)
    assert token is not None
    await run_metadata_job(resources, job.id, job.generation, token, job.payload)
    return await lookup_job(resources, paper_id)


async def detail(resources, paper_id):
    from app.repositories.papers import paper_detail

    async with resources.sessions() as session:
        return await paper_detail(session, paper_id)


def use(resources, client):
    resources.http = client


async def test_doi_clue_fills_the_paper_from_openalex_with_provenance(resources):
    """Given a DOI clue, the selected source fills every field and its record is linked."""
    requests = []
    await resources.http.aclose()

    def openalex(request):
        assert request.url.params["filter"] == f"doi:https://doi.org/{DOI}"
        return httpx.Response(200, json={"results": [openalex_work()]})

    use(resources, providers(requests, openalex=openalex))
    accepted = await ingested(
        resources,
        toolchain_pdf(subject=f"doi:{DOI}", title_lines=DOI_LINES, stamp=None, second_page=None),
    )
    before = await detail(resources, accepted.paper_id)
    # Reading is never blocked: the document is ready before any provider is asked.
    assert before.document_status == "ready" and requests == []
    assert before.title == "Exploiting Input Sanitization for Regex Denial of Service"
    job = await run_lookup(resources, accepted.paper_id, due=False)
    assert job.state == "completed" and job.result["outcome"] == "matched"
    assert job.result["provider"] == "openalex" and job.result["matched_by"] == "doi"
    paper = await detail(resources, accepted.paper_id)
    assert paper.title == "Exploiting Input Sanitization for Regex Denial of Service"
    assert paper.authors == ["Efe Barlas", "Xin Du", "James C. Davis"]
    assert paper.year == 2022 and paper.abstract == DOI_ABSTRACT and paper.doi == DOI
    assert paper.venue == "International Conference on Software Engineering"
    assert [(s.provider, s.external_id) for s in paper.sources] == [("openalex", "W4224987405")]
    for field in ("title", "authors", "year", "abstract", "doi", "venue"):
        assert paper.metadata_provenance[field]["source"] == "openalex", field
    assert len(requests) == 1


async def test_arxiv_clue_uses_semantic_scholar_when_it_is_the_chosen_source(resources):
    from app.main import create_app

    requests = []
    await resources.http.aclose()

    def semantic(request):
        assert request.url.path.endswith("/paper/ARXIV:1706.03762")
        return httpx.Response(200, json=semantic_paper(title=TITLE, doi=None, arxiv="1706.03762"))

    use(resources, providers(requests, semantic_scholar=semantic))
    app = create_app(resources.settings)
    app.state.resources = resources
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        assert (await client.get("/api/v1/metadata/settings")).json() == {"source": "openalex"}
        saved = await client.put("/api/v1/metadata/settings", json={"source": "semantic_scholar"})
        assert saved.status_code == 200 and saved.json() == {"source": "semantic_scholar"}
        assert (await client.get("/api/v1/metadata/settings")).json()["source"] == (
            "semantic_scholar"
        )
        invalid = await client.put("/api/v1/metadata/settings", json={"source": "google"})
        assert invalid.status_code == 422
    accepted = await ingested(resources, toolchain_pdf(second_page=NO_DOI_PAGE))
    job = await run_lookup(resources, accepted.paper_id, due=False)
    assert job.result["provider"] == "semantic_scholar" and job.result["matched_by"] == "arxiv"
    paper = await detail(resources, accepted.paper_id)
    assert paper.title == TITLE and paper.authors[0] == "Efe Barlas"
    assert paper.metadata_provenance["authors"]["source"] == "semantic_scholar"
    assert [source.provider for source in paper.sources] == ["semantic_scholar"]
    assert all(request.url.host == "api.semanticscholar.org" for request in requests)


async def test_toolchain_title_is_replaced_through_a_verified_title_search(resources):
    """paper.dvi: the printed title is the clue, and the agreeing record fills the paper."""
    requests = []
    await resources.http.aclose()
    work = openalex_work(
        work_id="W2889518255",
        title=TITLE.lower(),
        year=2018,
        doi=None,
        authors=("Seung-Hun Han", "Wook‐Geun Shin"),
        abstract=None,
        venue="USENIX Security Symposium",
    )

    def openalex(request):
        assert request.url.params["filter"].startswith("title.search:A Bad Dream Subverting")
        return httpx.Response(200, json={"results": [work]})

    use(resources, providers(requests, openalex=openalex))
    accepted = await ingested(resources, toolchain_pdf(stamp=None, second_page=NO_DOI_PAGE))
    assert (await detail(resources, accepted.paper_id)).title == TITLE
    job = await run_lookup(resources, accepted.paper_id, due=False)
    assert job.result["matched_by"] == "title"
    paper = await detail(resources, accepted.paper_id)
    # The record confirms the printed title, whose capitalisation is kept.
    assert paper.title == TITLE
    assert paper.authors == ["Seung-Hun Han", "Wook‐Geun Shin"] and paper.year == 2018
    assert paper.venue == "USENIX Security Symposium"
    assert paper.metadata_provenance["title"]["source"] == "openalex"


async def test_a_record_below_the_match_threshold_leaves_local_metadata(resources):
    requests = []
    await resources.http.aclose()
    unrelated = openalex_work(title="Sleeping beauty: a study of trusted computing", doi=None)

    use(
        resources,
        providers(
            requests,
            openalex=lambda request: httpx.Response(200, json={"results": [unrelated]}),
            semantic_scholar=lambda request: httpx.Response(404, json={"error": "not found"}),
        ),
    )
    accepted = await ingested(resources, toolchain_pdf(stamp=None, second_page=NO_DOI_PAGE))
    job = await run_lookup(resources, accepted.paper_id, due=False)
    assert job.state == "completed" and job.result["outcome"] == "no_match"
    paper = await detail(resources, accepted.paper_id)
    assert paper.title == TITLE and paper.sources == [] and paper.venue is None
    assert paper.metadata_provenance["title"]["source"] == "pdf"


@pytest.mark.parametrize("failure", ["rate_limited", "outage"])
async def test_unavailable_sources_keep_local_metadata_and_retry_durably(resources, failure):
    from app.models.jobs import JobOutbox

    requests = []
    await resources.http.aclose()

    def unavailable(request):
        if failure == "outage":
            raise httpx.ConnectError("fixture outage", request=request)
        if request.url.host == "api.openalex.org":
            return httpx.Response(429, headers={"Retry-After": "120"})
        return httpx.Response(429, json={"message": "Too Many Requests"})

    use(resources, providers(requests, openalex=unavailable, semantic_scholar=unavailable))
    accepted = await ingested(resources, toolchain_pdf(stamp=None, second_page=NO_DOI_PAGE))
    started = datetime.now(UTC)
    job = await run_lookup(resources, accepted.paper_id, due=False)
    assert job.state == "queued" and job.stage == "retry_wait" and job.attempts == 1
    wait = (job.available_at - started).total_seconds()
    # Retry-After 120 from OpenAlex wins over the first backoff step of 60 seconds.
    assert (115 <= wait <= 200) if failure == "rate_limited" else (55 <= wait <= 200)
    async with resources.sessions() as session:
        outbox = await session.scalar(
            select(JobOutbox).where(
                JobOutbox.job_id == job.id, JobOutbox.generation == job.generation
            )
        )
    assert outbox is not None and outbox.available_at == job.available_at
    paper = await detail(resources, accepted.paper_id)
    assert paper.document_status == "ready" and paper.title == TITLE and paper.sources == []
    job = await run_lookup(resources, accepted.paper_id)
    assert job.state == "queued" and job.attempts == 2
    job = await run_lookup(resources, accepted.paper_id)
    assert job.state == "failed" and job.attempts == 3
    expected = "PROVIDER_RATE_LIMITED" if failure == "rate_limited" else "PROVIDER_UNAVAILABLE"
    assert job.error_code == expected
    assert "kept" in job.error_message
    assert (await detail(resources, accepted.paper_id)).title == TITLE
    from app.main import create_app

    app = create_app(resources.settings)
    app.state.resources = resources
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        # Details offers "Look up again": a lookup out of attempts is retryable.
        retried = await client.post(f"/api/v1/jobs/{job.id}/retry")
    assert retried.status_code == 202, retried.text
    assert retried.json()["state"] == "queued" and retried.json()["attempts"] == 0


async def test_rate_limited_selected_source_falls_back_to_the_other_source(resources):
    requests = []
    await resources.http.aclose()
    use(
        resources,
        providers(
            requests,
            openalex=lambda request: httpx.Response(429, headers={"Retry-After": "30"}),
            semantic_scholar=lambda request: httpx.Response(
                200,
                json={"data": [semantic_paper(title=TITLE, doi=None, authors=("Seunghun Han",))]},
            ),
        ),
    )
    accepted = await ingested(resources, toolchain_pdf(stamp=None, second_page=NO_DOI_PAGE))
    job = await run_lookup(resources, accepted.paper_id, due=False)
    assert job.state == "completed" and job.result["provider"] == "semantic_scholar"
    assert [request.url.host for request in requests] == [
        "api.openalex.org",
        "api.semanticscholar.org",
    ]


async def test_the_chosen_source_answering_no_match_is_final_when_the_fallback_is_busy(resources):
    """Observed live: anonymous Semantic Scholar 429s must not keep retrying OpenAlex's answer."""
    requests = []
    await resources.http.aclose()
    use(
        resources,
        providers(
            requests,
            openalex=lambda request: httpx.Response(200, json={"results": []}),
            semantic_scholar=lambda request: httpx.Response(429, json={"message": "Too Many"}),
        ),
    )
    accepted = await ingested(resources, toolchain_pdf(stamp=None, second_page=NO_DOI_PAGE))
    job = await run_lookup(resources, accepted.paper_id, due=False)
    assert job.state == "completed" and job.result["outcome"] == "no_match"
    assert job.error_code is None


async def test_user_edited_fields_survive_enrichment(resources):
    from app.repositories.papers import patch_paper
    from app.schemas.research import PaperPatch

    requests = []
    await resources.http.aclose()
    use(
        resources,
        providers(
            requests,
            openalex=lambda request: httpx.Response(200, json={"results": [openalex_work()]}),
        ),
    )
    accepted = await ingested(
        resources,
        toolchain_pdf(subject=f"doi:{DOI}", title_lines=DOI_LINES, stamp=None, second_page=None),
    )
    async with resources.sessions() as session, session.begin():
        await patch_paper(
            session, accepted.paper_id, PaperPatch(title="My title", authors=["Me Myself"])
        )
    await run_lookup(resources, accepted.paper_id, due=False)
    paper = await detail(resources, accepted.paper_id)
    assert paper.title == "My title" and paper.authors == ["Me Myself"]
    assert paper.metadata_provenance["title"] == {"source": "manual"}
    assert paper.year == 2022 and paper.metadata_provenance["year"]["source"] == "openalex"


async def test_a_record_saved_on_another_paper_keeps_doi_deduplication(resources):
    from app.integrations.academic import normalize
    from app.repositories.papers import save_canonical

    requests = []
    await resources.http.aclose()
    use(
        resources,
        providers(
            requests,
            openalex=lambda request: httpx.Response(200, json={"results": [openalex_work()]}),
        ),
    )
    async with resources.sessions() as session, session.begin():
        saved, _ = await save_canonical(session, normalize("openalex", openalex_work()))
        saved_id = saved.id
    accepted = await ingested(
        resources,
        toolchain_pdf(subject=f"doi:{DOI}", title_lines=DOI_LINES, stamp=None, second_page=None),
    )
    assert accepted.paper_id != saved_id
    job = await run_lookup(resources, accepted.paper_id, due=False)
    assert job.result["outcome"] == "matched"
    assert job.result["duplicate_paper_id"] == str(saved_id)
    paper = await detail(resources, accepted.paper_id)
    assert paper.doi is None and paper.sources == []
    assert paper.title == "Exploiting Input Sanitization for Regex Denial of Service"
    assert paper.year == 2022
    assert [s.external_id for s in (await detail(resources, saved_id)).sources] == ["W4224987405"]


async def test_only_new_unlinked_documents_queue_a_lookup(resources):
    """A re-ingest or a paper saved from search never asks a provider again."""
    from app.integrations.academic import normalize
    from app.models.jobs import BackgroundJob
    from app.repositories.jobs import claim
    from app.repositories.papers import save_canonical
    from app.services.ingestion import run_ingest_job
    from app.services.reindex import enqueue_reindex

    accepted = await ingested(resources, toolchain_pdf(stamp=None, second_page=NO_DOI_PAGE))
    async with resources.sessions() as session, session.begin():
        await session.execute(
            update(BackgroundJob)
            .where(BackgroundJob.kind == "metadata")
            .values(state="completed", stage="completed")
        )
        from app.models.research import Document

        await session.execute(
            update(Document).where(Document.id == accepted.document_id).values(chunk_set="old")
        )
    assert await enqueue_reindex(resources) == 1
    async with resources.sessions() as session:
        reingest = await session.scalar(
            select(BackgroundJob).where(
                BackgroundJob.kind == "ingest", BackgroundJob.id != accepted.job_id
            )
        )
    token = await claim(resources.sessions, reingest.id, 1)
    await run_ingest_job(resources, reingest.id, 1, token, reingest.payload)
    async with resources.sessions() as session:
        lookups = (
            await session.scalars(select(BackgroundJob).where(BackgroundJob.kind == "metadata"))
        ).all()
    assert len(lookups) == 1
    async with resources.sessions() as session, session.begin():
        saved, _ = await save_canonical(session, normalize("openalex", openalex_work()))
        saved_id = saved.id
    await ingested(resources, toolchain_pdf(info_title="Other", stamp=None), paper_id=saved_id)
    assert await lookup_job(resources, saved_id) is None


async def test_stale_lookup_delivery_changes_nothing(resources):
    from app.services.metadata import run_metadata_job

    requests = []
    await resources.http.aclose()
    use(
        resources,
        providers(
            requests,
            openalex=lambda request: httpx.Response(200, json={"results": [openalex_work()]}),
        ),
    )
    accepted = await ingested(
        resources,
        toolchain_pdf(subject=f"doi:{DOI}", title_lines=DOI_LINES, stamp=None, second_page=None),
    )
    job = await lookup_job(resources, accepted.paper_id)
    await run_metadata_job(resources, job.id, job.generation, uuid4(), job.payload)
    paper = await detail(resources, accepted.paper_id)
    assert paper.sources == [] and paper.year is None
    assert (await lookup_job(resources, accepted.paper_id)).state == "queued"


async def test_jobs_api_links_lookups_to_their_paper(resources):
    from app.main import create_app

    accepted = await ingested(resources, toolchain_pdf(stamp=None, second_page=NO_DOI_PAGE))
    app = create_app(resources.settings)
    app.state.resources = resources
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        page = await client.get(
            "/api/v1/jobs",
            params={"paper_id": str(accepted.paper_id), "kind": "metadata", "active": "true"},
        )
    assert page.status_code == 200, page.text
    [job] = page.json()["items"]
    assert job["kind"] == "metadata" and job["paper_id"] == str(accepted.paper_id)
    assert UUID(job["id"])


async def test_duplicate_pdf_upload_opens_the_existing_paper_with_a_note(resources):
    from app.main import create_app

    data = toolchain_pdf(stamp=None, second_page=NO_DOI_PAGE)
    app = create_app(resources.settings)
    app.state.resources = resources
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:

        async def post(**fields):
            return await client.post(
                "/api/v1/documents",
                files={"file": ("paper.pdf", data, "application/pdf")},
                data={"request_id": str(uuid4()), **fields},
            )

        first = await post()
        assert first.status_code == 202 and first.json()["duplicate"] is False
        again = await post()
        assert again.status_code == 202 and again.json()["duplicate"] is True
        assert again.json()["paper_id"] == first.json()["paper_id"]
    from app.models.research import Paper

    async with resources.sessions() as session, session.begin():
        paper = Paper(metadata_provenance={})
        session.add(paper)
        await session.flush()
        other_id = paper.id
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        conflict = await client.post(
            "/api/v1/documents",
            files={"file": ("paper.pdf", data, "application/pdf")},
            data={"request_id": str(uuid4()), "paper_id": str(other_id)},
        )
    assert conflict.status_code == 409 and conflict.json()["code"] == "DOCUMENT_ALREADY_ATTACHED"
    assert conflict.json()["details"] == [{"paper_id": first.json()["paper_id"]}]


async def test_an_untitled_paper_reports_its_file_name_while_processing(resources):
    """The workspace can name a paper by its file until a title is known."""
    from app.services.uploads import ingest_pdf_bytes

    accepted = await ingest_pdf_bytes(
        resources,
        data=toolchain_pdf(stamp=None, second_page=NO_DOI_PAGE),
        filename="sec18-han.pdf",
        request_id=uuid4(),
        paper_id=None,
    )
    paper = await detail(resources, accepted.paper_id)
    assert paper.title is None and paper.file_name == "sec18-han.pdf"
