"""OpenAlex's stored PDFs (ARA-087): a free work lookup, then a metered content download.

The content endpoint answers with a redirect to a temporary signed link in OpenAlex's
Cloudflare R2 bucket. Requests go straight to the pinned transport rather than through an
httpx client, so neither the API key nor a signed link reaches a request log.
"""

import asyncio
import re
from dataclasses import dataclass
from urllib.parse import parse_qsl, quote, urlencode, urljoin, urlsplit, urlunsplit

import httpx

from app.core.errors import AppError
from app.integrations.academic import AcademicSearch
from app.integrations.public_http import DownloadPolicyError, PublicPDFTransport
from app.schemas.fulltext import DownloadResult

CONTENT_HOST = "content.openalex.org"
# The R2 endpoint that help.openalex.org/access/fulltext documents for the openalex-pdfs
# bucket, in path and virtual-host style. Confirm against a live signed link once a key exists.
STORAGE_HOSTS = frozenset(
    {
        "a452eddbbe06eb7d02f4879cee70d29c.r2.cloudflarestorage.com",
        "openalex-pdfs.a452eddbbe06eb7d02f4879cee70d29c.r2.cloudflarestorage.com",
    }
)
DOWNLOAD_SECONDS = 45
MAX_PDF_BYTES = 25 * 1024 * 1024
# A spent daily allowance resets at midnight UTC, so a reported wait can last most of a day.
MAX_WAIT_SECONDS = 86400
WORK_ID = re.compile(r"W\d{1,20}")
HEADERS = {
    "Accept": "application/pdf",
    "Accept-Encoding": "identity",
    "User-Agent": "ai-research-assistant",
}
TIMEOUT = {"connect": 5.0, "read": 10.0, "write": 10.0, "pool": 5.0}


def api_key(settings) -> str | None:
    key = settings.openalex_api_key.get_secret_value().strip() if settings.openalex_api_key else ""
    return key or None


@dataclass(frozen=True)
class StoredWork:
    work_id: str
    has_pdf: bool


async def stored_work(http, settings, *, work_id=None, doi=None) -> StoredWork | None:
    """Whether OpenAlex stores a PDF of this work: a free single-work lookup by ID or DOI.

    None means OpenAlex has no matching work. Rate limits and outages raise AppError.
    """
    if work_id:
        path = f"works/{work_id}"
    elif doi:
        path = "works/" + quote(f"doi:{doi}", safe=":/")
    else:
        return None
    try:
        row = await AcademicSearch(http, settings).request(
            "openalex", path, {"select": "id,has_content"}
        )
    except AppError as error:
        if error.code == "PAPER_NOT_FOUND":
            return None
        raise
    identity = row.get("id")
    content = row.get("has_content") or {}
    work = identity.rsplit("/", 1)[-1] if isinstance(identity, str) else ""
    if not WORK_ID.fullmatch(work) or not isinstance(content, dict):
        raise AppError(
            502, "PROVIDER_INVALID_RESPONSE", "OpenAlex returned malformed work metadata."
        )
    return StoredWork(work_id=work, has_pdf=content.get("pdf") is True)


def content_url(work_id: str) -> str:
    return f"https://{CONTENT_HOST}/works/{work_id}.pdf"


def with_key(url: str, api_key: str) -> str:
    parts = urlsplit(url)
    query = [(name, value) for name, value in parse_qsl(parts.query) if name != "api_key"]
    return urlunsplit(parts._replace(query=urlencode([*query, ("api_key", api_key)])))


def reported_wait(headers) -> int | None:
    """OpenAlex's own wait: Retry-After, else the seconds until its daily allowance resets."""
    for name in ("Retry-After", "X-RateLimit-Reset"):
        value = headers.get(name, "").strip()
        if value.isdigit():
            return min(int(value), MAX_WAIT_SECONDS)
    return None


def refusal(response: httpx.Response, host: str) -> DownloadResult:
    status = response.status_code
    if status in {404, 410}:
        return DownloadResult(
            "not_stored", response_status=status, reason="OpenAlex has no stored copy of this PDF."
        )
    if status in {401, 403} and host == CONTENT_HOST:
        return DownloadResult(
            "api_key_required",
            response_status=status,
            reason="OpenAlex did not accept the configured API key.",
        )
    if status == 429:
        spent = response.headers.get("X-RateLimit-Remaining", "").strip() == "0"
        return DownloadResult(
            "rate_limited",
            response_status=status,
            retry_after=reported_wait(response.headers),
            reason="Today's OpenAlex allowance is used up."
            if spent
            else "OpenAlex is limiting requests.",
        )
    return DownloadResult(
        "unavailable", response_status=status, reason="OpenAlex's PDF storage is unavailable."
    )


async def pdf_body(response: httpx.Response) -> DownloadResult:
    status = response.status_code
    kind = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
    length = response.headers.get("Content-Length", "")
    if kind not in {"", "application/pdf", "application/octet-stream", "binary/octet-stream"}:
        return DownloadResult(
            "invalid_pdf", response_status=status, reason="OpenAlex returned no PDF."
        )
    if response.headers.get("Content-Encoding", "identity").lower() != "identity":
        return DownloadResult(
            "invalid_pdf", response_status=status, reason="OpenAlex returned an encoded file."
        )
    if length.isdigit() and int(length) > MAX_PDF_BYTES:
        return DownloadResult(
            "invalid_pdf", response_status=status, reason="The PDF exceeds the 25 MiB limit."
        )
    data = bytearray()
    async for block in response.aiter_raw(chunk_size=65536):
        data.extend(block)
        if len(data) > MAX_PDF_BYTES:
            return DownloadResult(
                "invalid_pdf", response_status=status, reason="The PDF exceeds the 25 MiB limit."
            )
        if len(data) >= 5 and not data[:1024].lstrip().startswith(b"%PDF-"):
            break
    if not data[:1024].lstrip().startswith(b"%PDF-"):
        return DownloadResult(
            "invalid_pdf", response_status=status, reason="OpenAlex returned no PDF."
        )
    return DownloadResult("downloaded", data=bytes(data), response_status=status)


class ContentDownloader:
    """Fetches one work's stored PDF; redirects may only reach OpenAlex or its storage."""

    def __init__(self, *, resolver=None, transport_factory=None):
        self.transport = PublicPDFTransport(
            {CONTENT_HOST, *STORAGE_HOSTS}, resolver=resolver, transport_factory=transport_factory
        )

    async def fetch(self, work_id: str, api_key: str) -> DownloadResult:
        if not isinstance(work_id, str) or not WORK_ID.fullmatch(work_id):
            return DownloadResult("not_stored", reason="OpenAlex has no record for this paper.")
        url = with_key(content_url(work_id), api_key)
        try:
            async with asyncio.timeout(DOWNLOAD_SECONDS):
                for _ in range(4):
                    host = urlsplit(url).hostname
                    request = httpx.Request(
                        "GET", url, headers=HEADERS, extensions={"timeout": TIMEOUT}
                    )
                    response = await self.transport.handle_async_request(request)
                    try:
                        if response.status_code in {301, 302, 303, 307, 308}:
                            target = urljoin(url, response.headers.get("Location", ""))
                            parts = urlsplit(target)
                            if parts.scheme != "https" or parts.hostname not in {
                                CONTENT_HOST,
                                *STORAGE_HOSTS,
                            }:
                                return DownloadResult(
                                    "unsafe_url",
                                    response_status=response.status_code,
                                    reason="OpenAlex redirected outside its PDF storage.",
                                )
                            # A merged work moves within OpenAlex, which still needs the key.
                            url = (
                                with_key(target, api_key)
                                if parts.hostname == CONTENT_HOST
                                else target
                            )
                            continue
                        if response.status_code != 200:
                            return refusal(response, host)
                        return await pdf_body(response)
                    finally:
                        await response.aclose()
                return DownloadResult("unavailable", reason="OpenAlex redirected too many times.")
        except DownloadPolicyError as error:
            return DownloadResult(error.outcome, reason=error.reason)
        except (TimeoutError, httpx.HTTPError, OSError, ValueError):
            return DownloadResult(
                "unavailable", reason="OpenAlex's PDF storage could not be reached in time."
            )

    async def aclose(self):
        await self.transport.aclose()
