"""Discovery modifies only verified sources on an existing library paper."""

import asyncio

import httpx
from sqlalchemy import func, select, text

from app.models.research import Paper, PaperSource
from app.repositories.papers import save_canonical
from app.schemas.research import PaperPatch, SearchResult


async def test_semantic_paper_finds_openalex_copy_without_duplicate_or_manual_overwrite(resources):
    """Given a saved S2 paper, when DOI discovery runs, then its OA copy stays on that paper."""
    from app.services.fulltext_discovery import discover_fulltext

    async with resources.sessions() as session, session.begin():
        paper, _ = await save_canonical(
            session,
            SearchResult(provider="semantic_scholar", external_id="s2-copy", doi="10.1000/exact"),
        )
        paper.title = "My corrected title"
        paper.metadata_provenance = {"title": {"source": "manual"}}
        paper_id = paper.id

    def respond(request):
        if request.url.host == "api.semanticscholar.org":
            return httpx.Response(
                200,
                json={
                    "paperId": "s2-copy",
                    "title": "Provider title",
                    "externalIds": {"DOI": "10.1000/exact"},
                },
            )
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "id": "https://openalex.org/W998",
                        "doi": "https://doi.org/10.1000/exact",
                        "best_oa_location": {
                            "pdf_url": "https://arxiv.org/pdf/998",
                            "is_oa": True,
                            "version": "acceptedVersion",
                            "source": {"type": "repository"},
                        },
                    }
                ]
            },
        )

    await resources.http.aclose()
    resources.http = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    found = await discover_fulltext(resources, paper_id)
    assert [copy.url for copy in found.candidates] == ["https://arxiv.org/pdf/998"]
    assert found.candidates[0].location.version == "acceptedVersion"
    async with resources.sessions() as session:
        assert await session.scalar(select(func.count()).select_from(Paper)) == 1
        assert (await session.get(Paper, paper_id)).title == "My corrected title"
        assert await session.scalar(select(func.count()).select_from(PaperSource)) == 2


async def test_provider_failure_preserves_stored_candidates(resources):
    from app.services.fulltext_discovery import discover_fulltext

    async with resources.sessions() as session, session.begin():
        paper, _ = await save_canonical(
            session,
            SearchResult(
                provider="openalex", external_id="W123", pdf_url="https://arxiv.org/pdf/123"
            ),
        )
        paper_id = paper.id
    await resources.http.aclose()
    resources.http = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(429)))
    found = await discover_fulltext(resources, paper_id)
    assert [copy.url for copy in found.candidates] == ["https://arxiv.org/pdf/123"]
    assert found.warnings


async def test_malformed_refresh_preserves_a_valid_stored_copy(resources):
    from app.services.fulltext_discovery import discover_fulltext

    async with resources.sessions() as session, session.begin():
        paper, _ = await save_canonical(
            session,
            SearchResult(
                provider="openalex", external_id="W123", pdf_url="https://arxiv.org/pdf/123"
            ),
        )
        paper_id = paper.id
    await resources.http.aclose()
    resources.http = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json={
                    "id": "https://openalex.org/W123",
                    "locations": [{"pdf_url": "https://arxiv.org/pdf/new", "source": ["bad"]}],
                },
            )
        )
    )
    found = await discover_fulltext(resources, paper_id)
    assert [copy.url for copy in found.candidates] == ["https://arxiv.org/pdf/123"]
    assert found.warnings


async def test_discovery_rejects_changed_provider_identity(resources):
    from app.services.fulltext_discovery import discover_fulltext

    async with resources.sessions() as session, session.begin():
        paper, _ = await save_canonical(
            session,
            SearchResult(
                provider="openalex",
                external_id="W123",
                doi="10.1000/exact",
                pdf_url="https://arxiv.org/pdf/original",
            ),
        )
        paper_id = paper.id

    def respond(request):
        if request.url.host == "api.openalex.org":
            return httpx.Response(
                200,
                json={
                    "id": "https://openalex.org/W456",
                    "doi": "10.1000/wrong",
                    "primary_location": {"pdf_url": "https://arxiv.org/pdf/wrong"},
                },
            )
        return httpx.Response(404)

    await resources.http.aclose()
    resources.http = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    found = await discover_fulltext(resources, paper_id)
    assert [copy.url for copy in found.candidates] == ["https://arxiv.org/pdf/original"]
    assert found.warnings


async def test_background_refresh_waits_for_manual_edit_without_overwriting(resources):
    """Given a manual edit holds the row, then refresh merges only after that edit commits."""
    from app.repositories.papers import patch_paper

    async with resources.sessions() as session, session.begin():
        paper, _ = await save_canonical(
            session, SearchResult(provider="openalex", external_id="W123")
        )
        paper_id = paper.id

    async def refresh():
        async with resources.sessions() as session, session.begin():
            await save_canonical(
                session,
                SearchResult(provider="openalex", external_id="W123", title="Provider fallback"),
            )

    async with resources.sessions() as manual:
        await manual.begin()
        await patch_paper(manual, paper_id, PaperPatch(title="My manual correction"))
        pending = asyncio.create_task(refresh())
        try:
            async with asyncio.timeout(5):
                while True:
                    async with resources.sessions() as observer:
                        blocked = await observer.scalar(
                            text(
                                "SELECT count(*) FROM pg_stat_activity "
                                "WHERE datname=current_database() AND wait_event_type='Lock' "
                                "AND query ILIKE '%papers%'"
                            )
                        )
                    if blocked:
                        break
                    await asyncio.sleep(0.02)
            await manual.commit()
        finally:
            await manual.rollback()
            await asyncio.wait_for(pending, 5)
    async with resources.sessions() as session:
        saved = await session.get(Paper, paper_id)
        assert saved.title == "My manual correction"
        assert saved.metadata_provenance["title"]["source"] == "manual"
