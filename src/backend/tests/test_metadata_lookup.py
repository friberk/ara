"""Provider lookups and the acceptance rules for uploaded-paper metadata (ARA-086)."""

import httpx
import pytest
from support.front_matter import TITLE

OPENALEX_ROW = {
    "id": "https://openalex.org/W2889518255",
    "display_name": "A bad dream: subverting trusted platform module while you are sleeping",
    "publication_year": 2018,
    "doi": None,
    "authorships": [
        {"author": {"display_name": "Seung-Hun Han"}},
        {"author": {"display_name": "Wook‐Geun Shin"}},
    ],
    "primary_location": {
        "landing_page_url": "https://www.usenix.org/conference/usenixsecurity18/presentation/han",
        "pdf_url": None,
        "source": {"display_name": "USENIX Security Symposium", "type": "conference"},
    },
}
S2_ROW = {
    "paperId": "276d287b26df1a02c9da5475548003c048031e43",
    "externalIds": {"DBLP": "conf/uss/HanSPK18", "ArXiv": "1706.03762"},
    "url": "https://www.semanticscholar.org/paper/276d287b26df1a02c9da5475548003c048031e43",
    "title": TITLE,
    "venue": "",
    "publicationVenue": {"name": "USENIX Security Symposium"},
    "journal": {"pages": "1229-1246"},
    "year": 2018,
    "authors": [{"name": "Seunghun Han"}, {"name": "Wook Shin"}],
    "abstract": None,
    "openAccessPdf": {"url": "", "status": None},
    "matchScore": 328.5,
}


def adapter(respond):
    from app.core.config import Settings
    from app.integrations.academic import AcademicSearch

    client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    return client, AcademicSearch(client, Settings(_env_file=None))


@pytest.mark.parametrize("provider", ["openalex", "semantic_scholar"])
async def test_arxiv_identifier_lookup_and_venue(provider):
    requests = []

    def respond(request):
        requests.append(request)
        if provider == "openalex":
            return httpx.Response(200, json={"results": [OPENALEX_ROW]})
        return httpx.Response(200, json=S2_ROW)

    client, search = adapter(respond)
    async with client:
        result = await search.by_arxiv(provider, "1706.03762")
    assert result.venue == "USENIX Security Symposium"
    assert result.year == 2018
    if provider == "openalex":
        assert requests[0].url.path == "/works"
        assert requests[0].url.params["filter"] == "doi:https://doi.org/10.48550/arxiv.1706.03762"
        assert result.external_id == "W2889518255"
    else:
        assert requests[0].url.path.endswith("/paper/ARXIV:1706.03762")
        assert "venue" in requests[0].url.params["fields"]
        assert result.pdf_url is None


async def test_semantic_scholar_arxiv_record_must_report_the_same_arxiv_id():
    def respond(request):
        return httpx.Response(200, json={**S2_ROW, "externalIds": {"ArXiv": "2001.00001"}})

    client, search = adapter(respond)
    async with client:
        assert await search.by_arxiv("semantic_scholar", "1706.03762") is None


@pytest.mark.parametrize("provider", ["openalex", "semantic_scholar"])
async def test_title_match_queries_titles_not_full_text(provider):
    requests = []

    def respond(request):
        requests.append(request)
        if provider == "openalex":
            return httpx.Response(200, json={"results": [OPENALEX_ROW]})
        return httpx.Response(200, json={"data": [S2_ROW]})

    client, search = adapter(respond)
    async with client:
        results = await search.match_title(provider, TITLE)
    assert [result.venue for result in results] == ["USENIX Security Symposium"]
    if provider == "openalex":
        # Filter syntax treats commas, pipes and colons as operators, so they become spaces.
        assert requests[0].url.params["filter"] == (
            "title.search:A Bad Dream Subverting Trusted Platform Module While You Are Sleeping"
        )
    else:
        assert requests[0].url.path.endswith("/paper/search/match")
        assert requests[0].url.params["query"] == TITLE


async def test_semantic_scholar_title_match_not_found_is_an_empty_answer():
    client, search = adapter(
        lambda request: httpx.Response(404, json={"error": "Title match not found"})
    )
    async with client:
        assert await search.match_title("semantic_scholar", TITLE) == []


async def test_rate_limit_without_retry_after_still_reports_a_wait():
    from app.core.errors import AppError

    client, search = adapter(
        lambda request: httpx.Response(429, json={"message": "Too Many Requests"})
    )
    async with client:
        with pytest.raises(AppError) as failure:
            await search.match_title("semantic_scholar", TITLE)
    assert failure.value.code == "PROVIDER_RATE_LIMITED" and failure.value.retry_after == 30


def candidate(**fields):
    from app.schemas.research import SearchResult

    return SearchResult(
        **{
            "provider": "openalex",
            "external_id": "W2889518255",
            "title": OPENALEX_ROW["display_name"],
            "authors": ["Seung-Hun Han", "Wook‐Geun Shin"],
            "year": 2018,
            **fields,
        }
    )


FIRST_PAGES = f"{TITLE}\nSeunghun Han, Wook Shin, Jun-Hyeok Park, and HyoungChun Kim\nAbstract"


def test_close_title_with_an_author_on_the_first_page_is_accepted():
    from app.services.metadata import Clues, acceptable

    assert acceptable(candidate(), Clues(title=TITLE), FIRST_PAGES, by="title")


def test_close_title_with_matching_year_but_no_author_evidence_is_accepted():
    from app.services.metadata import Clues, acceptable

    assert acceptable(
        candidate(authors=["Somebody Else"]), Clues(title=TITLE, year=2018), "", by="title"
    )


def test_close_title_without_author_or_year_agreement_is_rejected():
    from app.services.metadata import Clues, acceptable

    other = candidate(authors=["Somebody Else"], year=2021)
    assert not acceptable(other, Clues(title=TITLE, year=2018), FIRST_PAGES, by="title")


def test_a_different_title_is_rejected_even_when_authors_agree():
    from app.services.metadata import Clues, acceptable

    other = candidate(title="Trusted platform modules in practice: a decade of measurements")
    assert not acceptable(
        other, Clues(title=TITLE, authors=["Seunghun Han"]), FIRST_PAGES, by="title"
    )


def test_a_truncated_local_title_still_matches_its_full_record():
    from app.services.metadata import Clues, acceptable

    local = "A Bad Dream: Subverting Trusted Platform"
    assert acceptable(candidate(), Clues(title=local, year=2018), FIRST_PAGES, by="title")


def test_an_identifier_hit_must_be_the_paper_on_the_first_pages():
    """A DOI read from a cited reference resolves to that reference, which is not this paper."""
    from app.services.metadata import Clues, acceptable

    reference = candidate(title="An unrelated reference about something else entirely")
    assert not acceptable(
        reference, Clues(title=TITLE, doi="10.9999/unrelated.ref"), FIRST_PAGES, by="doi"
    )
    assert acceptable(candidate(), Clues(title=None), FIRST_PAGES, by="doi")
