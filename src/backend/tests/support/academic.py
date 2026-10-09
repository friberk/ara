"""In-process OpenAlex and Semantic Scholar fixtures for metadata lookups (ARA-086).

Rows mirror the shapes the public APIs returned for a read-only check on 2026-10-09.
"""

import httpx

DOI = "10.1145/3510003.3510047"
DOI_TITLE = "Exploiting input sanitization for regex denial of service"
DOI_ABSTRACT = "Web services use server-side input sanitization to guard against harmful input."


def openalex_work(
    *,
    work_id="W4224987405",
    title=DOI_TITLE,
    year=2022,
    doi=DOI,
    authors=("Efe Barlas", "Xin Du", "James C. Davis"),
    abstract=DOI_ABSTRACT,
    venue="International Conference on Software Engineering",
):
    index = {}
    for position, word in enumerate((abstract or "").split()):
        index.setdefault(word, []).append(position)
    return {
        "id": f"https://openalex.org/{work_id}",
        "display_name": title,
        "publication_year": year,
        "doi": f"https://doi.org/{doi}" if doi else None,
        "authorships": [{"author": {"display_name": name}} for name in authors],
        "abstract_inverted_index": index or None,
        "primary_location": {
            "landing_page_url": f"https://doi.org/{doi}" if doi else None,
            "pdf_url": None,
            "source": {"display_name": venue, "type": "conference"} if venue else None,
        },
    }


def semantic_paper(
    *,
    paper_id="b5e2a1c7f0d64b0e8c1a3f9d2e7b6c5a4d3e2f10",
    title=DOI_TITLE,
    year=2022,
    doi=DOI,
    arxiv=None,
    authors=("Efe Barlas", "Xin Du", "James C. Davis"),
    abstract=DOI_ABSTRACT,
    venue="International Conference on Software Engineering",
):
    ids = {key: value for key, value in (("DOI", doi), ("ArXiv", arxiv)) if value}
    return {
        "paperId": paper_id,
        "externalIds": ids,
        "url": f"https://www.semanticscholar.org/paper/{paper_id}",
        "title": title,
        "venue": venue or "",
        "publicationVenue": {"name": venue} if venue else None,
        "year": year,
        "authors": [{"name": name} for name in authors],
        "abstract": abstract,
        "openAccessPdf": None,
    }


def providers(requests, openalex=None, semantic_scholar=None) -> httpx.AsyncClient:
    """Route each provider's requests to a handler; an unset provider answers 503."""

    def respond(request):
        requests.append(request)
        handler = openalex if request.url.host == "api.openalex.org" else semantic_scholar
        if handler is None:
            return httpx.Response(503, json={"message": "fixture outage"})
        return handler(request)

    return httpx.AsyncClient(transport=httpx.MockTransport(respond))
