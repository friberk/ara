"""Discovery modifies only verified sources on an existing library paper."""

import httpx
from sqlalchemy import func, select

from app.models.research import Paper, PaperSource
from app.repositories.papers import save_canonical
from app.schemas.research import SearchResult


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
