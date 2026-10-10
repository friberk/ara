"""A one-time metadata refresh for papers saved or read before ARA-086 stored venues (ARA-095).

Papers with a provider record read that record again by its ID. Uploads without one have their
stored PDF read again by the child-process parser, and the lookup runs with those clues. The
refresh fills missing values and values read from the PDF; values from a provider stay, and
manual edits always win. It is queued once, at startup, and never again.
"""

import asyncio
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import delete, func, select, update
from support.academic import DOI_ABSTRACT, openalex_work, providers
from support.front_matter import TITLE, toolchain_pdf
from test_metadata_enrichment_integration import detail, ingested, run_lookup, use
from test_paper_deletion_integration import client_for
from test_upload_match_integration import library_paper

from app.models.jobs import BackgroundJob
from app.models.research import ModelConfiguration, Paper, PaperSource

pytestmark = pytest.mark.integration
ICSE = "International Conference on Software Engineering"
NO_MATCH = {"results": []}


async def backfill(resources) -> int:
    from app.services.metadata import queue_backfill

    return await queue_backfill(resources)


async def metadata_jobs(resources, paper_id=None) -> list[BackgroundJob]:
    async with resources.sessions() as session:
        statement = select(BackgroundJob).where(BackgroundJob.kind == "metadata")
        if paper_id is not None:
            statement = statement.where(BackgroundJob.payload["paper_id"].astext == str(paper_id))
        return list((await session.scalars(statement.order_by(BackgroundJob.created_at))).all())


async def saved_before_venues(resources) -> object:
    """A paper saved from OpenAlex before ARA-086: its record has no venue, its year was
    missing, and the user edited its title."""
    saved = await library_paper(resources)
    async with resources.sessions() as session, session.begin():
        source = await session.scalar(select(PaperSource).where(PaperSource.paper_id == saved))
        snapshot = dict(source.metadata_snapshot)
        snapshot.pop("venue", None)
        source.metadata_snapshot = snapshot
        paper = await session.get(Paper, saved)
        provenance = dict(paper.metadata_provenance)
        provenance.pop("venue", None)
        paper.metadata_provenance = provenance
        paper.year = None
    async with client_for(resources) as client:
        await client.patch(f"/api/v1/papers/{saved}", json={"title": "My reading title"})
    return saved


async def read_before_title_fixes(resources, monkeypatch) -> tuple[object, list]:
    """An upload processed before the first-page title rule: still titled `paper.dvi`, with no
    provider record. Returns the paper and a list of the parser runs from now on."""
    from app.services import ingestion

    accepted = await ingested(resources, toolchain_pdf())
    async with resources.sessions() as session, session.begin():
        await session.execute(
            update(Paper)
            .where(Paper.id == accepted.paper_id)
            .values(title="paper.dvi", metadata_provenance={"title": {"source": "pdf"}})
        )
        # Processed before ARA-086, so it never had a lookup.
        await session.execute(delete(BackgroundJob).where(BackgroundJob.kind == "metadata"))
    parsed = []
    parse = ingestion.parse_in_child

    async def counted(*args, **kwargs):
        parsed.append(kwargs)
        return await parse(*args, **kwargs)

    monkeypatch.setattr(ingestion, "parse_in_child", counted)
    return accepted.paper_id, parsed


async def test_a_saved_paper_gets_its_venue_from_its_record_and_keeps_edits(resources):
    """Given a paper saved before venues were stored, the refresh reads its OpenAlex record by
    ID: the venue and the missing year are filled, the edited title stays, and the abstract
    the provider gave earlier is not replaced."""
    saved = await saved_before_venues(resources)
    requests = []
    await resources.http.aclose()
    record = openalex_work(abstract="A different abstract from a later crawl.")
    use(resources, providers(requests, openalex=lambda request: httpx.Response(200, json=record)))

    assert await backfill(resources) == 1
    (job,) = await metadata_jobs(resources, saved)
    assert job.payload["refresh"] == "backfill"
    finished = await run_lookup(resources, saved)
    assert finished.state == "completed" and finished.result["matched_by"] == "record"
    assert [request.url.path for request in requests] == ["/works/W4224987405"]
    paper = await detail(resources, saved)
    assert paper.venue == ICSE and paper.year == 2022
    assert paper.title == "My reading title"
    assert paper.metadata_provenance["title"] == {"source": "manual"}
    assert paper.abstract == DOI_ABSTRACT


@pytest.mark.parametrize("trigger", ["backfill", "look up again"])
async def test_an_uploads_junk_title_is_fixed_from_its_re_read_pdf(resources, monkeypatch, trigger):
    """Given an upload still titled `paper.dvi` with a manually edited year, the stored PDF is
    read again: the first-page title replaces the junk one even when no catalog matches, and
    the edited year stays. "Look up again" takes the same path."""
    paper_id, parsed = await read_before_title_fixes(resources, monkeypatch)
    async with client_for(resources) as client:
        await client.patch(f"/api/v1/papers/{paper_id}", json={"year": 2019})
        if trigger == "backfill":
            assert await backfill(resources) == 1
        else:
            response = await client.post(f"/api/v1/papers/{paper_id}/metadata-lookup")
            assert response.status_code == 202, response.text
    requests = []
    await resources.http.aclose()
    use(
        resources,
        providers(
            requests,
            openalex=lambda request: httpx.Response(200, json=NO_MATCH),
            semantic_scholar=lambda request: httpx.Response(404, json={}),
        ),
    )
    job = await run_lookup(resources, paper_id)
    assert job.state == "completed" and job.result["outcome"] == "no_match"
    assert len(parsed) == 1
    paper = await detail(resources, paper_id)
    assert paper.title == TITLE and paper.metadata_provenance["title"] == {"source": "pdf"}
    assert paper.year == 2019 and paper.metadata_provenance["year"] == {"source": "manual"}
    # The re-read PDF's arXiv ID was a clue for the lookup.
    assert job.payload["clues"]["arxiv_id"] == "1706.03762"


async def test_the_refresh_is_queued_once_and_never_again(resources, monkeypatch):
    """Concurrent startups queue one refresh per existing paper; later startups, and papers
    added afterwards, queue nothing."""
    from app.services.reindex import prepare_search

    saved = await saved_before_venues(resources)
    upload, _ = await read_before_title_fixes(resources, monkeypatch)
    queued = await asyncio.gather(backfill(resources), backfill(resources))
    assert sorted(queued) == [0, 2]
    assert {job.payload["paper_id"] for job in await metadata_jobs(resources)} == {
        str(saved),
        str(upload),
    }
    async with resources.sessions() as session:
        assert (await session.get(ModelConfiguration, "metadata_backfill")).value["queued"] == 2
    await library_paper(resources, work_id="W77", title="Saved later", doi="10.5555/later")
    await prepare_search(resources)
    assert await backfill(resources) == 0
    assert len(await metadata_jobs(resources)) == 2


async def test_a_rate_limited_refresh_waits_then_finishes_without_reading_the_pdf_again(
    resources, monkeypatch
):
    """Given both catalogs rate limited, the refresh keeps the re-read PDF's values, waits for
    Retry-After and, on its next attempt, matches by arXiv ID without parsing the PDF again."""
    paper_id, parsed = await read_before_title_fixes(resources, monkeypatch)
    assert await backfill(resources) == 1
    limited = {"now": True}

    def openalex(request):
        if limited["now"]:
            return httpx.Response(429, headers={"Retry-After": "90"}, json={"message": "slow"})
        work = openalex_work(
            work_id="W2900000001",
            title=TITLE,
            doi="10.48550/arxiv.1706.03762",
            authors=("Seunghun Han", "Wook Shin"),
            venue="USENIX Security Symposium",
            year=2018,
        )
        return httpx.Response(200, json={"results": [work]})

    def semantic(request):
        return httpx.Response(429, headers={"Retry-After": "90"}, json={"message": "slow"})

    requests = []
    await resources.http.aclose()
    use(resources, providers(requests, openalex=openalex, semantic_scholar=semantic))
    before = datetime.now(UTC)
    waiting = await run_lookup(resources, paper_id)
    assert (waiting.state, waiting.stage, waiting.error_code) == (
        "queued",
        "retry_wait",
        "PROVIDER_RATE_LIMITED",
    )
    assert waiting.available_at >= before + timedelta(seconds=89)
    assert (await detail(resources, paper_id)).title == TITLE

    limited["now"] = False
    done = await run_lookup(resources, paper_id)
    assert done.state == "completed" and done.result["matched_by"] == "arxiv"
    assert len(parsed) == 1
    paper = await detail(resources, paper_id)
    assert paper.venue == "USENIX Security Symposium" and paper.year == 2018
    assert paper.authors == ["Seunghun Han", "Wook Shin"]


async def test_papers_with_nothing_to_refresh_are_left_alone(resources):
    """A paper with neither a provider record nor a stored PDF gets no refresh."""
    async with resources.sessions() as session, session.begin():
        session.add(Paper(title="Notes typed by hand", metadata_provenance={}))
    assert await backfill(resources) == 0
    async with resources.sessions() as session:
        assert await session.scalar(select(func.count()).select_from(BackgroundJob)) == 0
