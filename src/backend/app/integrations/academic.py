import asyncio
import json
import re
from urllib.parse import quote

import httpx

from app.core.errors import AppError
from app.schemas.research import FullTextLocation, SearchHit, SearchPage, SearchResult

FIELDS = (
    "title,authors,year,abstract,externalIds,url,openAccessPdf,isOpenAccess,"
    "venue,publicationVenue,journal"
)


def normalized_doi(doi: str | None) -> str | None:
    if doi is not None and not isinstance(doi, str):
        raise ValueError("Malformed DOI")
    if not doi:
        return None
    value = re.sub(r"^(https?://(dx\.)?doi\.org/|doi:\s*)", "", doi.strip(), flags=re.I).lower()
    return value if re.fullmatch(r"10\.\d{4,9}/\S+", value) else None


def object_value(value) -> dict:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("Malformed provider object")
    return value


def object_list(value) -> list[dict]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("Malformed provider collection")
    return [object_value(item) for item in value]


def text_value(*values) -> str | None:
    """The first non-blank string; providers report missing names as null or ""."""
    return next((v.strip() for v in values if isinstance(v, str) and v.strip()), None)


def normalize(provider: str, row: dict) -> SearchResult:
    row = object_value(row)
    if provider == "semantic_scholar":
        pdf = object_value(row.get("openAccessPdf"))
        return SearchResult(
            provider=provider,
            external_id=row["paperId"],
            title=row.get("title"),
            authors=[a["name"] for a in object_list(row.get("authors")) if a.get("name")],
            year=row.get("year"),
            abstract=row.get("abstract"),
            doi=normalized_doi(object_value(row.get("externalIds")).get("DOI")),
            external_url=row.get("url"),
            # Live records report a missing open-access copy as url "" (ARA-086).
            pdf_url=text_value(pdf.get("url")),
            is_open_access=row.get("isOpenAccess"),
            locations=[
                FullTextLocation(
                    pdf_url=pdf["url"],
                    landing_page_url=row.get("url"),
                    is_oa=True,
                    license=pdf.get("license"),
                    oa_status=pdf.get("status"),
                )
            ]
            if text_value(pdf.get("url"))
            else [],
            venue=text_value(
                row.get("venue"),
                object_value(row.get("publicationVenue")).get("name"),
                object_value(row.get("journal")).get("name"),
            ),
        )
    index = object_value(row.get("abstract_inverted_index"))
    positions = {
        position: word
        for word, offsets in index.items()
        for position in offsets
        if isinstance(position, int) and 0 <= position < 50000
    }
    abstract = " ".join(positions[i] for i in sorted(positions)) or None
    location = object_value(row.get("primary_location"))
    best = object_value(row.get("best_oa_location"))
    reported = object_list(row.get("locations"))
    pdf = (
        best.get("pdf_url")
        or location.get("pdf_url")
        or next((x.get("pdf_url") for x in reported if x.get("pdf_url")), None)
    )
    locations, seen = [], set()
    for item in [location, best, *reported]:
        if not item or not (item.get("pdf_url") or item.get("landing_page_url")):
            continue
        key = (item.get("pdf_url"), item.get("landing_page_url"))
        if key in seen:
            continue
        seen.add(key)
        source_type = object_value(item.get("source")).get("type")
        locations.append(
            FullTextLocation(
                pdf_url=item.get("pdf_url"),
                landing_page_url=item.get("landing_page_url"),
                is_oa=item.get("is_oa"),
                license=item.get("license"),
                version=item.get("version"),
                host_type="repository"
                if source_type == "repository"
                else "publisher"
                if source_type in {"journal", "conference"}
                else "unknown",
            )
        )
    if not isinstance(row.get("id"), str):
        raise ValueError("Malformed provider identity")
    return SearchResult(
        provider=provider,
        external_id=row["id"].rsplit("/", 1)[-1],
        title=row.get("display_name"),
        authors=[
            x["author"]["display_name"]
            for x in object_list(row.get("authorships"))
            if object_value(x.get("author")).get("display_name")
        ],
        year=row.get("publication_year"),
        abstract=abstract,
        doi=normalized_doi(row.get("doi")),
        external_url=location.get("landing_page_url"),
        pdf_url=pdf,
        is_open_access=object_value(row.get("open_access")).get("is_oa"),
        locations=locations,
        venue=text_value(object_value(location.get("source")).get("display_name")),
    )


class AcademicSearch:
    def __init__(self, client: httpx.AsyncClient, settings):
        self.client, self.settings = client, settings

    async def by_doi(self, provider: str, doi: str) -> SearchResult | None:
        identity = normalized_doi(doi)
        if identity is None:
            return None
        try:
            if provider == "openalex":
                data = await self.request(
                    provider, "works", {"filter": f"doi:https://doi.org/{identity}", "per-page": 1}
                )
                rows = data.get("results") or []
                if not rows:
                    return None
                row = rows[0]
            else:
                row = await self.request(
                    provider, f"paper/{quote('DOI:' + identity, safe='')}", {"fields": FIELDS}
                )
            result = normalize(provider, row)
        except AppError as error:
            if error.code == "PAPER_NOT_FOUND":
                return None
            raise
        except (ValueError, KeyError, TypeError):
            raise AppError(
                502,
                "PROVIDER_INVALID_RESPONSE",
                "The academic provider returned malformed paper metadata.",
            ) from None
        return result if normalized_doi(result.doi) == identity else None

    async def by_arxiv(self, provider: str, arxiv_id: str) -> SearchResult | None:
        """An arXiv identifier: OpenAlex knows it as the 10.48550 DOI, Semantic Scholar by ID."""
        if not re.fullmatch(r"\d{4}\.\d{4,5}|[a-z-]+(?:\.[A-Z]{2})?/\d{7}", arxiv_id):
            return None
        try:
            if provider == "openalex":
                # The arXiv DOI selects the work; its reported DOI may be a later publication's.
                data = await self.request(
                    provider,
                    "works",
                    {"filter": f"doi:https://doi.org/10.48550/arxiv.{arxiv_id.lower()}"},
                )
                rows = object_list(data.get("results"))
                return normalize(provider, rows[0]) if rows else None
            row = await self.request(
                provider, f"paper/ARXIV:{quote(arxiv_id, safe='/')}", {"fields": FIELDS}
            )
            reported = object_value(row.get("externalIds")).get("ArXiv")
            return normalize(provider, row) if reported == arxiv_id else None
        except AppError as error:
            if error.code == "PAPER_NOT_FOUND":
                return None
            raise
        except (ValueError, KeyError, TypeError):
            raise AppError(
                502,
                "PROVIDER_INVALID_RESPONSE",
                "The academic provider returned malformed paper metadata.",
            ) from None

    async def match_title(self, provider: str, title: str, limit: int = 5) -> list[SearchResult]:
        """Records whose title matches; callers still decide whether one is the same paper."""
        try:
            if provider == "openalex":
                # Commas, pipes and colons are filter operators, so only words are sent.
                words = " ".join(re.sub(r"[^\w\s]", " ", title).split())[:300]
                data = await self.request(
                    provider, "works", {"filter": f"title.search:{words}", "per-page": limit}
                )
                rows = object_list(data.get("results"))
            else:
                data = await self.request(
                    provider, "paper/search/match", {"query": title[:300], "fields": FIELDS}
                )
                rows = object_list(data.get("data"))
            return [normalize(provider, row) for row in rows[:limit]]
        except AppError as error:
            if error.code == "PAPER_NOT_FOUND":
                return []
            raise
        except (ValueError, KeyError, TypeError):
            raise AppError(
                502,
                "PROVIDER_INVALID_RESPONSE",
                "The academic provider returned malformed paper metadata.",
            ) from None

    async def request(self, provider: str, path: str, params: dict) -> dict:
        base = (
            self.settings.openalex_base_url
            if provider == "openalex"
            else self.settings.semantic_scholar_base_url
        )
        headers = {}
        if (
            provider == "openalex"
            and self.settings.openalex_api_key
            and self.settings.openalex_api_key.get_secret_value()
        ):
            params["api_key"] = self.settings.openalex_api_key.get_secret_value()
        if (
            provider == "semantic_scholar"
            and self.settings.semantic_scholar_api_key
            and self.settings.semantic_scholar_api_key.get_secret_value()
        ):
            headers["x-api-key"] = self.settings.semantic_scholar_api_key.get_secret_value()
        for attempt in range(3):
            try:
                async with self.client.stream(
                    "GET",
                    f"{base.rstrip('/')}/{path}",
                    params=params,
                    headers=headers,
                    timeout=httpx.Timeout(15, connect=5),
                ) as response:
                    if response.status_code == 429:
                        retry = response.headers.get("Retry-After", "30")
                        raise AppError(
                            429,
                            "PROVIDER_RATE_LIMITED",
                            "The academic provider is rate limited. Try again shortly.",
                            retry_after=min(int(retry), 300) if retry.isdigit() else 30,
                        )
                    if response.status_code == 404:
                        raise AppError(
                            404, "PAPER_NOT_FOUND", "The provider could not find this paper."
                        )
                    if response.status_code in {401, 403}:
                        raise AppError(
                            502,
                            "PROVIDER_ACCESS_DENIED",
                            "The academic provider rejected server credentials.",
                        )
                    if response.status_code >= 500 and attempt < 2:
                        await asyncio.sleep(0.2 * (2**attempt))
                        continue
                    if response.status_code != 200:
                        raise AppError(
                            502, "PROVIDER_UNAVAILABLE", "The academic provider is unavailable."
                        )
                    body = bytearray()
                    async for data in response.aiter_bytes():
                        body.extend(data)
                        if len(body) > 5 * 1024 * 1024:
                            raise AppError(
                                502,
                                "PROVIDER_RESPONSE_TOO_LARGE",
                                "The academic provider returned too much data.",
                            )
                    parsed = json.loads(body)
                    if not isinstance(parsed, dict):
                        raise ValueError("Expected object")
                    return parsed
            except (httpx.TimeoutException, httpx.NetworkError):
                if attempt == 2:
                    raise AppError(
                        503, "PROVIDER_UNAVAILABLE", "The academic provider could not be reached."
                    ) from None
                await asyncio.sleep(0.2 * (2**attempt))
            except (ValueError, KeyError, TypeError):
                raise AppError(
                    502,
                    "PROVIDER_INVALID_RESPONSE",
                    "The academic provider returned an invalid response.",
                ) from None
        raise AppError(503, "PROVIDER_UNAVAILABLE", "The academic provider could not be reached.")

    async def search(self, provider: str, query: str, cursor: str | None, limit: int) -> SearchPage:
        if provider == "semantic_scholar":
            if cursor is not None and (not cursor.isdigit() or len(cursor) > 7):
                raise AppError(422, "INVALID_CURSOR", "Search cursor is invalid.")
            row = await self.request(
                provider,
                "paper/search",
                {"query": query, "offset": int(cursor or 0), "limit": limit, "fields": FIELDS},
            )
            data, continuation, total = row.get("data"), row.get("next"), row.get("total")
        else:
            if cursor is not None and (len(cursor) > 2000 or any(ord(x) < 32 for x in cursor)):
                raise AppError(422, "INVALID_CURSOR", "Search cursor is invalid.")
            row = await self.request(
                provider, "works", {"search": query, "cursor": cursor or "*", "per-page": limit}
            )
            data, continuation, total = (
                row.get("results"),
                (row.get("meta") or {}).get("next_cursor"),
                (row.get("meta") or {}).get("count"),
            )
        try:
            if not isinstance(data, list):
                raise ValueError("Missing results")
            return SearchPage(
                provider=provider,
                items=[
                    SearchHit.model_validate(normalize(provider, x), from_attributes=True)
                    for x in data
                ],
                next_cursor=str(continuation) if continuation is not None and data else None,
                total=total,
            )
        except (ValueError, KeyError, TypeError):
            raise AppError(
                502,
                "PROVIDER_INVALID_RESPONSE",
                "The academic provider returned malformed paper metadata.",
            ) from None

    async def canonical(self, provider: str, external_id: str) -> SearchResult:
        if provider == "openalex":
            if not re.fullmatch(r"W\d{1,20}", external_id):
                raise AppError(422, "INVALID_PAPER_ID", "OpenAlex paper ID is invalid.")
            path, params = f"works/{external_id}", {}
        else:
            if not re.fullmatch(r"[a-zA-Z0-9:._/-]{1,200}", external_id):
                raise AppError(422, "INVALID_PAPER_ID", "Semantic Scholar paper ID is invalid.")
            path, params = f"paper/{quote(external_id, safe='')}", {"fields": FIELDS}
        row = await self.request(provider, path, params)
        try:
            return normalize(provider, row)
        except (ValueError, KeyError, TypeError):
            raise AppError(
                502,
                "PROVIDER_INVALID_RESPONSE",
                "The academic provider returned malformed paper metadata.",
            ) from None
