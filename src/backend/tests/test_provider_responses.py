"""A malformed OpenAlex or Semantic Scholar answer is a clear provider error (ARA-121).

Never a crash, and never a row built from nonsense. The strict expected failures record what
the client does wrongly today; they are ARA-121's evidence and turn red when it is fixed.
"""

import json

import httpx
import pytest

from app.core.config import Settings
from app.core.errors import AppError
from app.integrations.academic import AcademicSearch

INVALID = ("error", "PROVIDER_INVALID_RESPONSE")
OA_ROW = {"id": "https://openalex.org/W1", "display_name": "T"}
S2_ROW = {"paperId": "abc", "title": "T"}


def oa_page(row):
    return {"meta": {"count": 1, "next_cursor": None}, "results": [row]}


def s2_page(row):
    return {"total": 1, "data": [row]}


def oa_row(**fields):
    return oa_page({**OA_ROW, **fields})


def s2_row(**fields):
    return s2_page({**S2_ROW, **fields})


async def perform(call, api):
    if call == "oa_search":
        return await api.search("openalex", "q", None, 2)
    if call == "s2_search":
        return await api.search("semantic_scholar", "q", None, 2)
    if call == "oa_doi":
        return await api.by_doi("openalex", "10.1000/x")
    if call == "s2_doi":
        return await api.by_doi("semantic_scholar", "10.1000/x")
    if call == "oa_arxiv":
        return await api.by_arxiv("openalex", "1706.03762")
    if call == "s2_arxiv":
        return await api.by_arxiv("semantic_scholar", "1706.03762")
    if call == "oa_title":
        return await api.match_title("openalex", "a title")
    if call == "s2_title":
        return await api.match_title("semantic_scholar", "a title")
    if call == "oa_save":
        return await api.canonical("openalex", "W1")
    return await api.canonical("semantic_scholar", "abc")


async def outcome(call, payload):
    """("error", code) for a provider error, ("crash", type) if not, ("row", value) on success."""
    content = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=content))
    async with httpx.AsyncClient(transport=transport) as client:
        api = AcademicSearch(client, Settings(_env_file=None))
        try:
            return ("row", await perform(call, api))
        except AppError as error:
            return ("error", error.code)
        except Exception as error:  # noqa: BLE001 -- a crash is the result being measured
            return ("crash", type(error).__name__)


CLEAN = [
    ("oa_search", [], "oa-body-list"),
    ("oa_search", b"<html>busy</html>", "oa-body-not-json"),
    ("oa_search", b"\xff\xfe\x00", "oa-body-not-utf8"),
    ("oa_search", {"meta": {}, "results": "x"}, "oa-results-string"),
    ("oa_search", {"meta": {}}, "oa-results-missing"),
    ("oa_search", {"meta": {}, "results": {}}, "oa-results-empty-object"),
    ("oa_search", {"meta": {}, "results": ["x"]}, "oa-row-string"),
    ("oa_search", {"meta": {}, "results": [None]}, "oa-row-null"),
    ("oa_search", {"meta": {"count": "many"}, "results": [OA_ROW]}, "oa-count-text"),
    ("oa_search", oa_page({"display_name": "T"}), "oa-id-missing"),
    ("oa_search", oa_page({"id": 5, "display_name": "T"}), "oa-id-number"),
    ("oa_search", oa_row(display_name=5), "oa-title-number"),
    ("oa_search", oa_row(publication_year="soon"), "oa-year-text"),
    ("oa_search", oa_row(doi=5), "oa-doi-number"),
    ("oa_search", oa_row(authorships="x"), "oa-authorships-string"),
    ("oa_search", oa_row(authorships=[{"author": {"display_name": 5}}]), "oa-author-number"),
    ("oa_search", oa_row(authorships=[{"author": "x"}]), "oa-author-string"),
    ("oa_search", oa_row(abstract_inverted_index=[1]), "oa-abstract-list"),
    ("oa_search", oa_row(abstract_inverted_index={"a": 5}), "oa-abstract-offsets-number"),
    ("oa_search", oa_row(primary_location="x"), "oa-location-string"),
    ("oa_search", oa_row(primary_location={"pdf_url": 5}), "oa-pdf-url-number"),
    ("oa_search", oa_row(primary_location={"landing_page_url": 5}), "oa-landing-number"),
    ("oa_search", oa_row(locations=["x"]), "oa-locations-string"),
    ("oa_search", oa_row(open_access="x"), "oa-open-access-string"),
    ("s2_search", [], "s2-body-list"),
    ("s2_search", {"data": {"a": 1}}, "s2-data-object"),
    ("s2_search", {"total": 0}, "s2-data-missing"),
    ("s2_search", {"data": {}}, "s2-data-empty-object"),
    ("s2_search", {"data": ["x"]}, "s2-row-string"),
    ("s2_search", {"total": "many", "data": [S2_ROW]}, "s2-total-text"),
    ("s2_search", s2_page({"title": "T"}), "s2-id-missing"),
    ("s2_search", s2_page({"paperId": 5, "title": "T"}), "s2-id-number"),
    ("s2_search", s2_row(authors="x"), "s2-authors-string"),
    ("s2_search", s2_row(authors=[{"name": 5}]), "s2-author-number"),
    ("s2_search", s2_row(externalIds="x"), "s2-ids-string"),
    ("s2_search", s2_row(openAccessPdf="x"), "s2-pdf-string"),
    ("oa_doi", {"results": "x"}, "doi-results-string"),
    ("oa_doi", {"results": {"a": 1}}, "doi-results-object"),
    ("oa_doi", {"results": [{"id": 5}]}, "doi-row-malformed"),
    ("s2_doi", {"paperId": 5}, "s2-doi-row-malformed"),
    ("oa_arxiv", {"results": "x"}, "arxiv-results-string"),
    ("oa_arxiv", {"results": [{"id": 5}]}, "arxiv-row-malformed"),
    ("s2_arxiv", {"paperId": "a", "externalIds": "x"}, "s2-arxiv-ids-string"),
    ("oa_title", {"results": "x"}, "title-results-string"),
    ("oa_title", {"results": [{"id": 5}]}, "title-row-malformed"),
    ("s2_title", {"data": "x"}, "s2-title-data-string"),
    ("oa_save", [], "save-body-list"),
    ("oa_save", {"id": 5}, "save-id-number"),
    ("s2_save", {"title": "T"}, "s2-save-id-missing"),
]


@pytest.mark.parametrize(
    ("call", "payload"), [(c, p) for c, p, _ in CLEAN], ids=[name for _, _, name in CLEAN]
)
async def test_a_malformed_answer_is_a_clear_provider_error(call, payload):
    assert await outcome(call, payload) == INVALID


def known_bug(reason):
    return pytest.mark.xfail(strict=True, raises=AssertionError, reason=f"ARA-121: {reason}")


BROKEN = [
    pytest.param(
        "oa_search",
        {"meta": "oops", "results": [OA_ROW]},
        marks=known_bug("a non-object meta crashes search"),
        id="crash-meta-string",
    ),
    pytest.param(
        "oa_search",
        {"meta": [1], "results": [OA_ROW]},
        marks=known_bug("a non-object meta crashes search"),
        id="crash-meta-list",
    ),
    pytest.param(
        "oa_search",
        oa_page({"id": "", "display_name": "T"}),
        marks=known_bug("an empty OpenAlex id makes a row with no identity"),
        id="empty-id-openalex",
    ),
    pytest.param(
        "oa_search",
        oa_page({"id": "https://openalex.org/", "display_name": "T"}),
        marks=known_bug("an id with no work part makes a row with no identity"),
        id="empty-id-no-work-part",
    ),
    pytest.param(
        "s2_search",
        s2_page({"paperId": "", "title": "T"}),
        marks=known_bug("an empty paperId makes a row with no identity"),
        id="empty-id-semantic-scholar",
    ),
    pytest.param(
        "oa_save",
        {"id": ""},
        marks=known_bug("saving accepts a record with no identity"),
        id="empty-id-save",
    ),
    pytest.param(
        "oa_search",
        oa_row(publication_year=True),
        marks=known_bug("a boolean year becomes 1"),
        id="year-true-openalex",
    ),
    pytest.param(
        "oa_search",
        oa_row(publication_year=99999),
        marks=known_bug("an impossible year is kept"),
        id="year-99999-openalex",
    ),
    pytest.param(
        "oa_search",
        oa_row(publication_year=-3),
        marks=known_bug("a negative year is kept"),
        id="year-negative-openalex",
    ),
    pytest.param(
        "s2_search",
        s2_row(year=True),
        marks=known_bug("a boolean year becomes 1"),
        id="year-true-semantic-scholar",
    ),
    pytest.param(
        "s2_search",
        s2_row(year=99999),
        marks=known_bug("an impossible year is kept"),
        id="year-99999-semantic-scholar",
    ),
    pytest.param(
        "oa_search",
        {"meta": {"next_cursor": {"a": 1}}, "results": [OA_ROW]},
        marks=known_bug("an object cursor is turned into text and offered for Load more"),
        id="cursor-object-openalex",
    ),
    pytest.param(
        "s2_search",
        {"next": "soon", "data": [S2_ROW]},
        marks=known_bug("a text offset is offered for Load more and then refused"),
        id="cursor-text-semantic-scholar",
    ),
    pytest.param(
        "s2_search",
        {"next": {"a": 1}, "data": [S2_ROW]},
        marks=known_bug("an object offset is offered for Load more and then refused"),
        id="cursor-object-semantic-scholar",
    ),
]


@pytest.mark.parametrize(("call", "payload"), BROKEN)
async def test_a_malformed_answer_never_crashes_or_builds_a_broken_row(call, payload):
    assert await outcome(call, payload) == INVALID


async def test_a_non_string_pdf_link_is_dropped_and_the_paper_survives():
    """One unusable link is not a malformed paper: the row stays, without the link."""
    kind, page = await outcome("s2_search", s2_row(openAccessPdf={"url": 5}))
    assert kind == "row" and page.items[0].external_id == "abc"
    assert page.items[0].pdf_url is None and page.items[0].locations == []


@pytest.mark.parametrize(
    ("provider", "external_id"),
    [
        ("openalex", "W123/../../admin"),
        ("openalex", "W123?select=id"),
        ("openalex", "W123#x"),
        ("openalex", "123"),
        ("openalex", "works/W123"),
        ("semantic_scholar", "abc def"),
        ("semantic_scholar", "abc?fields=x"),
        ("semantic_scholar", "abc%2f"),
        ("semantic_scholar", "abc#x"),
    ],
)
async def test_a_crafted_paper_id_never_reaches_the_provider(provider, external_id):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        with pytest.raises(AppError) as refused:
            await AcademicSearch(client, Settings(_env_file=None)).canonical(provider, external_id)
    assert refused.value.status_code == 422 and refused.value.code == "INVALID_PAPER_ID"
    assert requests == []


@pytest.mark.parametrize(
    ("provider", "external_id", "path", "row"),
    [
        ("openalex", "W123", "/works/W123", OA_ROW),
        ("semantic_scholar", "ARXIV:1706.03762", "/paper/ARXIV%3A1706.03762", S2_ROW),
        ("semantic_scholar", "10.1000/a.b", "/paper/10.1000%2Fa.b", S2_ROW),
    ],
)
async def test_a_valid_paper_id_is_sent_as_one_path_segment(provider, external_id, path, row):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json=row)

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        await AcademicSearch(client, Settings(_env_file=None)).canonical(provider, external_id)
    (request,) = requests
    assert request.url.raw_path.decode().split("?")[0].endswith(path)


async def test_a_semantic_scholar_key_travels_only_in_its_header():
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json=s2_row())

    settings = Settings(_env_file=None, semantic_scholar_api_key="fixture-s2-key")
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        await AcademicSearch(client, settings).search("semantic_scholar", "q", None, 2)
    (request,) = requests
    assert request.headers["x-api-key"] == "fixture-s2-key"
    assert "fixture-s2-key" not in str(request.url)


@pytest.mark.parametrize("status", [401, 403])
async def test_refused_credentials_are_named_and_not_retried(status):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(status, json={"error": "denied"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        with pytest.raises(AppError) as refused:
            await AcademicSearch(client, Settings(_env_file=None)).search("openalex", "q", None, 2)
    assert refused.value.status_code == 502 and refused.value.code == "PROVIDER_ACCESS_DENIED"
    assert len(requests) == 1


async def test_an_oversized_answer_is_refused():
    kind, code = await outcome("oa_search", b'{"results": "' + b"x" * (5 * 1024 * 1024 + 1) + b'"}')
    assert (kind, code) == ("error", "PROVIDER_RESPONSE_TOO_LARGE")


async def test_the_same_location_reported_twice_is_listed_once():
    """OpenAlex commonly repeats the primary location as the best open-access one."""
    shared = {"pdf_url": "https://example.org/a.pdf", "landing_page_url": "https://example.org/a"}
    other = {"pdf_url": "https://example.org/b.pdf", "landing_page_url": "https://example.org/b"}
    kind, page = await outcome(
        "oa_search",
        oa_row(primary_location=shared, best_oa_location=shared, locations=[shared, other]),
    )
    assert kind == "row"
    assert [location.pdf_url for location in page.items[0].locations] == [
        "https://example.org/a.pdf",
        "https://example.org/b.pdf",
    ]
