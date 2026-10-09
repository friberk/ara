"""Credential-free PDF fetching boundary."""

import asyncio
from urllib.parse import urljoin, urlsplit

import httpx

from app.integrations.public_http import DownloadPolicyError, PublicPDFTransport
from app.schemas.fulltext import DownloadResult

CANDIDATE_SECONDS = 45
MAX_PDF_BYTES = 25 * 1024 * 1024


class PDFDownloader:
    def __init__(self, allowed_hosts, *, resolver=None, transport_factory=None):
        self.transport = PublicPDFTransport(
            allowed_hosts, resolver=resolver, transport_factory=transport_factory
        )
        self.client = httpx.AsyncClient(
            transport=self.transport,
            trust_env=False,
            follow_redirects=False,
            timeout=httpx.Timeout(10, connect=5, pool=5),
            headers={"Accept": "application/pdf", "Accept-Encoding": "identity"},
        )

    async def fetch(self, candidate) -> DownloadResult:
        url = candidate.url
        try:
            self.transport.validate(url)
            async with asyncio.timeout(CANDIDATE_SECONDS):
                for hop in range(6):
                    async with self.client.stream("GET", url) as response:
                        status = response.status_code
                        if status in {301, 302, 303, 307, 308}:
                            target = urljoin(url, response.headers.get("Location", ""))
                            if urlsplit(target).path.rstrip("/") in {
                                "/login",
                                "/signin",
                                "/Shibboleth.sso/Login",
                            }:
                                return DownloadResult(
                                    "access_required",
                                    response_status=status,
                                    reason=(
                                        "This source requires authentication. "
                                        "Your university may provide access."
                                    ),
                                )
                            if (
                                urlsplit(url).scheme == "https"
                                and urlsplit(target).scheme != "https"
                            ):
                                raise DownloadPolicyError(
                                    "unsafe_url",
                                    "The PDF link redirects to an insecure destination.",
                                )
                            self.transport.validate(target)
                            if hop == 5 or not response.headers.get("Location"):
                                return DownloadResult(
                                    "unavailable",
                                    response_status=status,
                                    reason="The PDF link redirected too many times.",
                                )
                            url = target
                            continue
                        if status != 200:
                            outcomes = {
                                401: "access_required",
                                403: "blocked",
                                404: "not_found",
                                410: "not_found",
                                429: "rate_limited",
                            }
                            outcome = outcomes.get(status, "unavailable")
                            reasons = {
                                "access_required": (
                                    "This source requires authentication. "
                                    "Your university may provide access."
                                ),
                                "blocked": (
                                    "This site blocked the download. Institutional access "
                                    "or downloading in your browser may help."
                                ),
                                "not_found": "The PDF link is no longer available.",
                                "rate_limited": "This source is rate limited. Try again shortly.",
                                "unavailable": "The PDF source is temporarily unavailable.",
                            }
                            raw_retry = response.headers.get("Retry-After", "30")
                            retry = min(int(raw_retry), 300) if raw_retry.isdigit() else 30
                            return DownloadResult(
                                outcome,
                                response_status=status,
                                reason=reasons[outcome],
                                retry_after=retry if status == 429 else None,
                            )
                        kind = (
                            response.headers.get("Content-Type", "")
                            .split(";", 1)[0]
                            .strip()
                            .lower()
                        )
                        if kind not in {"", "application/pdf", "application/octet-stream"}:
                            return DownloadResult(
                                "invalid_pdf",
                                response_status=status,
                                reason="The link returned a web page instead of a PDF.",
                            )
                        if (
                            response.headers.get("Content-Encoding", "identity").lower()
                            != "identity"
                        ):
                            return DownloadResult(
                                "invalid_pdf",
                                response_status=status,
                                reason="The PDF source returned an unsupported encoded response.",
                            )
                        length = response.headers.get("Content-Length", "")
                        if length.isdigit() and int(length) > MAX_PDF_BYTES:
                            return DownloadResult(
                                "invalid_pdf",
                                response_status=status,
                                reason="The PDF exceeds the 25 MiB limit.",
                            )
                        data = bytearray()
                        async for block in response.aiter_bytes(chunk_size=65536):
                            data.extend(block)
                            if len(data) > MAX_PDF_BYTES:
                                return DownloadResult(
                                    "invalid_pdf",
                                    response_status=status,
                                    reason="The PDF exceeds the 25 MiB limit.",
                                )
                            if not data[:1024].lstrip().startswith(b"%PDF-"):
                                return DownloadResult(
                                    "invalid_pdf",
                                    response_status=status,
                                    reason="The link returned a web page instead of a PDF.",
                                )
                        if not data[:1024].lstrip().startswith(b"%PDF-"):
                            return DownloadResult(
                                "invalid_pdf",
                                response_status=status,
                                reason="The link did not contain a PDF.",
                            )
                        return DownloadResult(
                            "downloaded", data=bytes(data), response_status=status, final_url=url
                        )
        except DownloadPolicyError as error:
            return DownloadResult(error.outcome, reason=error.reason)
        except (TimeoutError, httpx.HTTPError, OSError, ValueError):
            return DownloadResult(
                "unavailable",
                reason="The PDF source could not be reached within the download limit.",
            )
        return DownloadResult("unavailable", reason="The PDF source could not be reached.")

    async def aclose(self):
        await self.client.aclose()
