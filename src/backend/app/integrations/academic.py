import asyncio
import json
import re
from urllib.parse import quote

import httpx

from app.core.errors import AppError
from app.schemas.research import SearchHit, SearchPage, SearchResult

FIELDS = "title,authors,year,abstract,externalIds,url,openAccessPdf"


def normalized_doi(doi: str | None) -> str | None:
    if not doi:
        return None
    value = re.sub(r"^(https?://(dx\.)?doi\.org/|doi:\s*)", "", doi.strip(), flags=re.I).lower()
    return value if re.fullmatch(r"10\.\d{4,9}/\S+", value) else None


def normalize(provider: str, row: dict) -> SearchResult:
    if provider == "semantic_scholar":
        return SearchResult(
            provider=provider,
            external_id=row["paperId"],
            title=row.get("title"),
            authors=[a["name"] for a in row.get("authors") or [] if a.get("name")],
            year=row.get("year"),
            abstract=row.get("abstract"),
            doi=normalized_doi((row.get("externalIds") or {}).get("DOI")),
            external_url=row.get("url"),
            pdf_url=(row.get("openAccessPdf") or {}).get("url"),
        )
    index = row.get("abstract_inverted_index") or {}
    positions = {
        position: word
        for word, offsets in index.items()
        for position in offsets
        if isinstance(position, int) and 0 <= position < 50000
    }
    abstract = " ".join(positions[i] for i in sorted(positions)) or None
    location = row.get("primary_location") or {}
    pdf = location.get("pdf_url") or next(
        (x.get("pdf_url") for x in row.get("locations") or [] if x.get("pdf_url")), None
    )
    return SearchResult(
        provider=provider,
        external_id=row["id"].rsplit("/", 1)[-1],
        title=row.get("display_name"),
        authors=[
            x["author"]["display_name"]
            for x in row.get("authorships") or []
            if (x.get("author") or {}).get("display_name")
        ],
        year=row.get("publication_year"),
        abstract=abstract,
        doi=normalized_doi(row.get("doi")),
        external_url=location.get("landing_page_url"),
        pdf_url=pdf,
    )


class AcademicSearch:
    def __init__(self, client: httpx.AsyncClient, settings):
        self.client, self.settings = client, settings

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
