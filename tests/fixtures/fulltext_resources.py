"""Explicit test transport: public fixture URLs map only to the isolated HTTP fixture."""

import httpx
from fulltext_fixture import FullTextFixture

from app.core.resources import Resources
from app.integrations.pdf_download import PDFDownloader
from app.integrations.public_http import DownloadPolicyError


class FixtureResolver:
    async def resolve(self, _host, _port):
        return ("8.8.8.8",)


class FixtureRelay(httpx.AsyncBaseTransport):
    def __init__(self):
        self.transport = httpx.AsyncHTTPTransport(retries=0)

    async def handle_async_request(self, request):
        case = request.url.path.removeprefix("/pdf/")
        if request.headers.get("Host") != "arxiv.org" or case not in FullTextFixture.cases:
            raise DownloadPolicyError("unsafe_url", "The request is not a configured fixture case.")
        target = httpx.Request(
            "GET",
            f"http://external-fixtures:8080/fulltext/pdf/{case}",
            extensions=request.extensions,
        )
        return await self.transport.handle_async_request(target)

    async def aclose(self):
        await self.transport.aclose()


def fixture_resources(settings):
    if settings.app_env != "test":
        raise RuntimeError("Full-text fixtures require APP_ENV=test")
    downloader = PDFDownloader(
        settings.fulltext_allowed_hosts, resolver=FixtureResolver(), transport_factory=FixtureRelay
    )
    return Resources(settings, pdf_downloader=downloader)
