"""Explicit test transport: OpenAlex's content and storage hosts map only to the HTTP fixture."""

import httpx

from app.core.resources import Resources
from app.integrations.openalex_content import CONTENT_HOST, STORAGE_HOSTS, ContentDownloader
from app.integrations.public_http import DownloadPolicyError

FIXTURE = "http://external-fixtures:8080"


class FixtureResolver:
    async def resolve(self, _host, _port):
        return ("8.8.8.8",)


class FixtureRelay(httpx.AsyncBaseTransport):
    def __init__(self):
        self.transport = httpx.AsyncHTTPTransport(retries=0)

    async def handle_async_request(self, request):
        host, path = request.headers.get("Host"), request.url.path
        if host == CONTENT_HOST and path.startswith("/works/"):
            target = f"{FIXTURE}/content{path}?{request.url.query.decode()}"
        elif host in STORAGE_HOSTS and path.startswith("/openalex-pdfs/"):
            target = f"{FIXTURE}/storage{path}"
        else:
            raise DownloadPolicyError("unsafe_url", "The request is not a configured fixture case.")
        return await self.transport.handle_async_request(
            httpx.Request("GET", target, extensions=request.extensions)
        )

    async def aclose(self):
        await self.transport.aclose()


def fixture_resources(settings):
    if settings.app_env != "test":
        raise RuntimeError("Full-text fixtures require APP_ENV=test")
    downloader = ContentDownloader(resolver=FixtureResolver(), transport_factory=FixtureRelay)
    return Resources(settings, pdf_downloader=downloader)
