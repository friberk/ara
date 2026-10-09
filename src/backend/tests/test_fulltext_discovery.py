"""Provider-reported access and exact-identity discovery; no live provider calls."""

import httpx
import pytest

from app.core.config import Settings
from app.integrations.academic import AcademicSearch, normalize
from app.schemas.research import SearchResult


def test_search_preserves_semantic_access_metadata():
    """Given a public S2 copy, when normalized, then access/license metadata survives."""
    result = normalize(
        "semantic_scholar",
        {
            "paperId": "s2-one",
            "url": "https://www.semanticscholar.org/paper/s2-one",
            "isOpenAccess": True,
            "openAccessPdf": {
                "url": "https://aclanthology.org/example.pdf",
                "status": "HYBRID",
                "license": "CCBY",
            },
        },
    ).model_dump()
    assert result.get("is_open_access") is True
    assert result.get("locations") == [
        {
            "pdf_url": "https://aclanthology.org/example.pdf",
            "landing_page_url": "https://www.semanticscholar.org/paper/s2-one",
            "is_oa": True,
            "license": "CCBY",
            "version": None,
            "host_type": "unknown",
            "oa_status": "HYBRID",
        }
    ]


def test_search_prefers_openalex_open_copy_and_preserves_publisher():
    """Given a publisher and an accepted OA copy, then both versions remain available."""
    publisher = {
        "pdf_url": "https://link.springer.com/paid.pdf",
        "landing_page_url": "https://link.springer.com/paper",
        "is_oa": False,
        "version": "publishedVersion",
        "source": {"type": "journal"},
    }
    repository = {
        "pdf_url": "https://arxiv.org/pdf/1234",
        "landing_page_url": "https://arxiv.org/abs/1234",
        "is_oa": True,
        "license": "cc-by",
        "version": "acceptedVersion",
        "source": {"type": "repository"},
    }
    result = normalize(
        "openalex",
        {
            "id": "https://openalex.org/W123",
            "open_access": {"is_oa": True},
            "primary_location": publisher,
            "best_oa_location": repository,
            "locations": [publisher, repository],
        },
    ).model_dump()
    assert result["pdf_url"] == "https://arxiv.org/pdf/1234"
    assert result.get("is_open_access") is True
    assert len(result.get("locations", [])) == 2
    assert result["locations"][1]["version"] == "acceptedVersion"
    assert result["locations"][1]["host_type"] == "repository"


def test_old_source_snapshots_remain_unknown_not_paywalled():
    """Given an old/closed record, then absence of an open copy is only metadata."""
    old = SearchResult.model_validate(
        {"provider": "semantic_scholar", "external_id": "old"}
    ).model_dump()
    assert "is_open_access" in old and old["is_open_access"] is None
    assert old.get("locations") == []
    closed = normalize(
        "semantic_scholar", {"paperId": "closed", "isOpenAccess": False}
    ).model_dump()
    assert closed.get("is_open_access") is False
    assert closed.get("locations") == []


@pytest.mark.parametrize("provider", ["openalex", "semantic_scholar"])
async def test_lookup_by_doi_uses_exact_identity(provider):
    """Given a DOI, when looked up, then another title cannot substitute for that work."""

    def respond(request):
        if provider == "openalex":
            assert request.url.params["filter"] == "doi:https://doi.org/10.1000/exact"
            return httpx.Response(
                200,
                json={
                    "results": [
                        {"id": "https://openalex.org/W123", "doi": "https://doi.org/10.1000/exact"}
                    ]
                },
            )
        assert request.url.path == "/graph/v1/paper/DOI:10.1000/exact"
        assert "isOpenAccess" in request.url.params["fields"]
        return httpx.Response(
            200, json={"paperId": "s2-exact", "externalIds": {"DOI": "10.1000/exact"}}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        adapter = AcademicSearch(client, Settings(_env_file=None))
        lookup = getattr(adapter, "by_doi", None)
        assert callable(lookup), "Exact DOI lookup is required for cross-provider PDF discovery"
        result = await lookup(provider, "https://doi.org/10.1000/EXACT")
    assert result is not None and result.doi == "10.1000/exact"


@pytest.mark.parametrize("provider", ["openalex", "semantic_scholar"])
async def test_cross_provider_doi_mismatch_is_rejected(provider):
    def respond(_request):
        row = (
            {"id": "https://openalex.org/W123", "doi": "10.1000/wrong"}
            if provider == "openalex"
            else {"paperId": "wrong", "externalIds": {"DOI": "10.1000/wrong"}}
        )
        return httpx.Response(200, json={"results": [row]} if provider == "openalex" else row)

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        adapter = AcademicSearch(client, Settings(_env_file=None))
        lookup = getattr(adapter, "by_doi", None)
        assert callable(lookup), "Exact DOI lookup must reject a mismatched returned DOI"
        assert await lookup(provider, "10.1000/exact") is None


@pytest.mark.parametrize("provider", ["openalex", "semantic_scholar"])
async def test_missing_doi_lookup_is_not_provider_failure(provider):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(404))
    ) as client:
        adapter = AcademicSearch(client, Settings(_env_file=None))
        lookup = getattr(adapter, "by_doi", None)
        assert callable(lookup), "No exact match must leave browser fallback usable"
        assert await lookup(provider, "10.1000/missing") is None


def test_candidates_prefer_open_versions_deduplicate_fragments_and_bound_attempts():
    from app.schemas.research import FullTextLocation
    from app.services.fulltext_discovery import candidates_from_sources

    source = SearchResult(
        provider="openalex",
        external_id="W123",
        locations=[
            FullTextLocation(
                pdf_url="https://link.springer.com/paid.pdf",
                is_oa=False,
                version="publishedVersion",
            ),
            FullTextLocation(
                pdf_url="https://arxiv.org/pdf/accepted?token=keep#page=1",
                is_oa=True,
                version="acceptedVersion",
            ),
            FullTextLocation(
                pdf_url="https://arxiv.org/pdf/accepted?token=keep#page=2",
                is_oa=True,
                version="acceptedVersion",
            ),
            FullTextLocation(
                pdf_url="https://aclanthology.org/published.pdf",
                is_oa=True,
                version="publishedVersion",
            ),
            *[
                FullTextLocation(pdf_url=f"https://arxiv.org/pdf/extra-{i}", is_oa=True)
                for i in range(10)
            ],
        ],
    )
    candidates = candidates_from_sources([source])
    assert candidates[0].url == "https://aclanthology.org/published.pdf"
    assert candidates[1].url == "https://arxiv.org/pdf/accepted?token=keep"
    assert len(candidates) == 8
    assert len({copy.url for copy in candidates}) == 8
